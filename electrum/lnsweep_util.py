# Copyright (C) 2018 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

from typing import Optional, Dict, List, Tuple

from .util import bfh, bh2u
from .bitcoin import TYPE_ADDRESS, redeem_script_to_address
from . import ecc
from .lnutil import (EncumberedTransaction,
                     make_commitment_output_to_remote_address, make_commitment_output_to_local_witness_script,
                     derive_privkey, derive_pubkey, derive_blinded_pubkey, derive_blinded_privkey,
                     privkey_to_pubkey, make_htlc_tx_witness,
                     make_htlc_tx_with_open_channel, make_offered_htlc,
                     LOCAL, REMOTE)
from .transaction import Transaction, TxOutput, construct_witness
from .simple_config import SimpleConfig, FEERATE_FALLBACK_STATIC_FEE


def maybe_create_sweeptx_for_their_ctx_to_remote(chan, ctx, their_pcp: bytes,
                                                 sweep_address) -> Optional[EncumberedTransaction]:
    assert isinstance(their_pcp, bytes)
    payment_bp_privkey = ecc.ECPrivkey(chan.config[LOCAL].payment_basepoint.privkey)
    our_payment_privkey = derive_privkey(payment_bp_privkey.secret_scalar, their_pcp)
    our_payment_privkey = ecc.ECPrivkey.from_secret_scalar(our_payment_privkey)
    our_payment_pubkey = our_payment_privkey.get_public_key_bytes(compressed=True)
    to_remote_address = make_commitment_output_to_remote_address(our_payment_pubkey)
    for output_idx, (type_, addr, val) in enumerate(ctx.outputs()):
        if type_ == TYPE_ADDRESS and addr == to_remote_address:
            break
    else:
        return None
    sweep_tx = create_sweeptx_their_ctx_to_remote(address=sweep_address,
                                                  ctx=ctx,
                                                  output_idx=output_idx,
                                                  our_payment_privkey=our_payment_privkey)
    return EncumberedTransaction('their_ctx_to_remote', sweep_tx, csv_delay=0, cltv_expiry=0)


def maybe_create_sweeptx_for_their_ctx_to_local(chan, ctx, per_commitment_secret: bytes,
                                                sweep_address) -> Optional[EncumberedTransaction]:
    assert isinstance(per_commitment_secret, bytes)
    per_commitment_point = ecc.ECPrivkey(per_commitment_secret).get_public_key_bytes(compressed=True)
    revocation_privkey = derive_blinded_privkey(chan.config[LOCAL].revocation_basepoint.privkey,
                                                per_commitment_secret)
    revocation_pubkey = ecc.ECPrivkey(revocation_privkey).get_public_key_bytes(compressed=True)
    to_self_delay = chan.config[LOCAL].to_self_delay
    delayed_pubkey = derive_pubkey(chan.config[REMOTE].delayed_basepoint.pubkey,
                                   per_commitment_point)
    witness_script = bh2u(make_commitment_output_to_local_witness_script(
        revocation_pubkey, to_self_delay, delayed_pubkey))
    to_local_address = redeem_script_to_address('p2wsh', witness_script)
    for output_idx, o in enumerate(ctx.outputs()):
        if o.type == TYPE_ADDRESS and o.address == to_local_address:
            break
    else:
        return None
    sweep_tx = create_sweeptx_ctx_to_local(address=sweep_address,
                                           ctx=ctx,
                                           output_idx=output_idx,
                                           witness_script=witness_script,
                                           privkey=revocation_privkey,
                                           is_revocation=True)
    return EncumberedTransaction('their_ctx_to_local', sweep_tx, csv_delay=0, cltv_expiry=0)


def create_sweeptxs_for_our_ctx(chan, ctx, our_pcp: bytes, sweep_address) \
                                                        -> List[Tuple[Optional[str],EncumberedTransaction]]:
    assert isinstance(our_pcp, bytes)
    delayed_bp_privkey = ecc.ECPrivkey(chan.config[LOCAL].delayed_basepoint.privkey)
    our_localdelayed_privkey = derive_privkey(delayed_bp_privkey.secret_scalar, our_pcp)
    our_localdelayed_privkey = ecc.ECPrivkey.from_secret_scalar(our_localdelayed_privkey)
    our_localdelayed_pubkey = our_localdelayed_privkey.get_public_key_bytes(compressed=True)
    revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey,
                                              our_pcp)
    to_self_delay = chan.config[REMOTE].to_self_delay
    witness_script = bh2u(make_commitment_output_to_local_witness_script(
        revocation_pubkey, to_self_delay, our_localdelayed_pubkey))
    to_local_address = redeem_script_to_address('p2wsh', witness_script)
    txs = []
    for output_idx, o in enumerate(ctx.outputs()):
        if o.type == TYPE_ADDRESS and o.address == to_local_address:
            sweep_tx = create_sweeptx_ctx_to_local(address=sweep_address,
                                                   ctx=ctx,
                                                   output_idx=output_idx,
                                                   witness_script=witness_script,
                                                   privkey=our_localdelayed_privkey.get_secret_bytes(),
                                                   is_revocation=False,
                                                   to_self_delay=to_self_delay)

            txs.append((None, EncumberedTransaction('our_ctx_to_local', sweep_tx, csv_delay=to_self_delay, cltv_expiry=0)))
            break

    # TODO htlc successes
    htlcs = list(chan.included_htlcs(LOCAL, LOCAL)) # timeouts
    for htlc in htlcs:
        witness_script, htlc_tx = make_htlc_tx_with_open_channel(
            chan,
            our_pcp,
            True, # for_us
            False, # we_receive
            ctx, htlc)

        data = chan.config[LOCAL].current_htlc_signatures
        htlc_sigs = [data[i:i+64] for i in range(0, len(data), 64)]
        idx = chan.verify_htlc(htlc, htlc_sigs, False)
        remote_htlc_sig = ecc.der_sig_from_sig_string(htlc_sigs[idx]) + b'\x01'

        remote_revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey, our_pcp)
        remote_htlc_pubkey = derive_pubkey(chan.config[REMOTE].htlc_basepoint.pubkey, our_pcp)
        local_htlc_key = derive_privkey(
            int.from_bytes(chan.config[LOCAL].htlc_basepoint.privkey, 'big'),
            our_pcp).to_bytes(32, 'big')
        program = make_offered_htlc(remote_revocation_pubkey, remote_htlc_pubkey, privkey_to_pubkey(local_htlc_key), htlc.payment_hash)
        local_htlc_sig = bfh(htlc_tx.sign_txin(0, local_htlc_key))

        htlc_tx.inputs()[0]['witness'] = bh2u(make_htlc_tx_witness(remote_htlc_sig, local_htlc_sig, b'', program))

        tx_size_bytes = 999  # TODO
        fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
        fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
        second_stage_outputs = [TxOutput(TYPE_ADDRESS, chan.sweep_address, htlc.amount_msat // 1000 - fee)]
        assert to_self_delay is not None
        second_stage_inputs = [{
            'scriptSig': '',
            'type': 'p2wsh',
            'signatures': [],
            'num_sig': 0,
            'prevout_n': 0,
            'prevout_hash': htlc_tx.txid(),
            'value': htlc_tx.outputs()[0].value,
            'coinbase': False,
            'preimage_script': bh2u(witness_script),
            'sequence': to_self_delay,
        }]
        tx = Transaction.from_io(second_stage_inputs, second_stage_outputs, version=2)

        local_delaykey = derive_privkey(
            int.from_bytes(chan.config[LOCAL].delayed_basepoint.privkey, 'big'),
            our_pcp).to_bytes(32, 'big')
        assert local_delaykey == our_localdelayed_privkey.get_secret_bytes()

        witness = construct_witness([bfh(tx.sign_txin(0, local_delaykey)), 0, witness_script])
        tx.inputs()[0]['witness'] = witness
        assert tx.is_complete()

        txs.append((htlc_tx.txid(), EncumberedTransaction(f'second_stage_to_wallet_{bh2u(htlc.payment_hash)}', tx, csv_delay=to_self_delay, cltv_expiry=0)))
        txs.append((ctx.txid(), EncumberedTransaction(f'our_ctx_htlc_tx_{bh2u(htlc.payment_hash)}', htlc_tx, csv_delay=0, cltv_expiry=htlc.cltv_expiry)))

    return txs

def create_sweeptx_their_ctx_to_remote(address, ctx, output_idx: int, our_payment_privkey: ecc.ECPrivkey,
                                       fee_per_kb: int=None) -> Transaction:
    our_payment_pubkey = our_payment_privkey.get_public_key_hex(compressed=True)
    val = ctx.outputs()[output_idx].value
    sweep_inputs = [{
        'type': 'p2wpkh',
        'x_pubkeys': [our_payment_pubkey],
        'num_sig': 1,
        'prevout_n': output_idx,
        'prevout_hash': ctx.txid(),
        'value': val,
        'coinbase': False,
        'signatures': [None],
    }]
    tx_size_bytes = 110  # approx size of p2wpkh->p2wpkh
    if fee_per_kb is None: fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
    fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
    sweep_outputs = [TxOutput(TYPE_ADDRESS, address, val-fee)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs)
    sweep_tx.set_rbf(True)
    sweep_tx.sign({our_payment_pubkey: (our_payment_privkey.get_secret_bytes(), True)})
    if not sweep_tx.is_complete():
        raise Exception('channel close sweep tx is not complete')
    return sweep_tx


def create_sweeptx_ctx_to_local(address, ctx, output_idx: int, witness_script: str,
                                privkey: bytes, is_revocation: bool,
                                to_self_delay: int=None,
                                fee_per_kb: int=None) -> Transaction:
    """Create a txn that sweeps the 'to_local' output of a commitment
    transaction into our wallet.

    privkey: either revocation_privkey or localdelayed_privkey
    is_revocation: tells us which ^
    """
    val = ctx.outputs()[output_idx].value
    sweep_inputs = [{
        'scriptSig': '',
        'type': 'p2wsh',
        'signatures': [],
        'num_sig': 0,
        'prevout_n': output_idx,
        'prevout_hash': ctx.txid(),
        'value': val,
        'coinbase': False,
        'preimage_script': witness_script,
    }]
    if to_self_delay is not None:
        sweep_inputs[0]['sequence'] = to_self_delay
    tx_size_bytes = 121  # approx size of to_local -> p2wpkh
    if fee_per_kb is None: fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
    fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
    sweep_outputs = [TxOutput(TYPE_ADDRESS, address, val - fee)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs, version=2)
    sig = sweep_tx.sign_txin(0, privkey)
    witness = construct_witness([sig, int(is_revocation), witness_script])
    sweep_tx.inputs()[0]['witness'] = witness
    return sweep_tx

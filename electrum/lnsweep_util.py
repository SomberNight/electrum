# Copyright (C) 2018 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

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

if TYPE_CHECKING:
    from .lnchan import Channel, UpdateAddHtlc


def maybe_create_sweeptx_for_their_ctx_to_remote(chan: 'Channel', ctx: Transaction, their_pcp: bytes,
                                                 sweep_address: str) -> Optional[EncumberedTransaction]:
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
    sweep_tx = create_sweeptx_their_ctx_to_remote(sweep_address=sweep_address,
                                                  ctx=ctx,
                                                  output_idx=output_idx,
                                                  our_payment_privkey=our_payment_privkey)
    return EncumberedTransaction('their_ctx_to_remote', sweep_tx, csv_delay=0, cltv_expiry=0)


def maybe_create_sweeptx_for_their_ctx_to_local(chan: 'Channel', ctx: Transaction, per_commitment_secret: bytes,
                                                sweep_address: str) -> Optional[EncumberedTransaction]:
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
    sweep_tx = create_sweeptx_ctx_to_local(sweep_address=sweep_address,
                                           ctx=ctx,
                                           output_idx=output_idx,
                                           witness_script=witness_script,
                                           privkey=revocation_privkey,
                                           is_revocation=True)
    return EncumberedTransaction('their_ctx_to_local', sweep_tx, csv_delay=0, cltv_expiry=0)


def create_sweeptxs_for_our_ctx(chan: 'Channel', ctx: Transaction, our_pcp: bytes,
                                sweep_address: str) -> List[Tuple[Optional[str],EncumberedTransaction]]:
    delayed_bp_privkey = ecc.ECPrivkey(chan.config[LOCAL].delayed_basepoint.privkey)
    our_localdelayed_privkey = derive_privkey(delayed_bp_privkey.secret_scalar, our_pcp)
    our_localdelayed_privkey = ecc.ECPrivkey.from_secret_scalar(our_localdelayed_privkey)
    remote_revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey, our_pcp)
    to_self_delay = chan.config[REMOTE].to_self_delay

    txs = []
    sweep_tx = create_sweeptx_that_spends_to_local_in_our_ctx(ctx=ctx,
                                                              sweep_address=sweep_address,
                                                              our_localdelayed_privkey=our_localdelayed_privkey,
                                                              remote_revocation_pubkey=remote_revocation_pubkey,
                                                              to_self_delay=to_self_delay)
    if sweep_tx:
        txs.append((None, EncumberedTransaction('our_ctx_to_local', sweep_tx, csv_delay=to_self_delay, cltv_expiry=0)))

    # TODO htlc successes
    offered_htlcs = list(chan.included_htlcs(LOCAL, LOCAL)) # timeouts
    for htlc in offered_htlcs:
        htlctx_witness_script, htlc_tx = create_htlctx_our_ctx_offered(chan=chan, our_pcp=our_pcp, ctx=ctx, htlc=htlc)

        to_wallet_tx = create_sweeptx_that_spends_htlctx_that_spends_offered_htlc_in_our_ctx(
            to_self_delay=to_self_delay,
            htlc_tx=htlc_tx,
            htlctx_witness_script=htlctx_witness_script,
            sweep_address=sweep_address,
            our_localdelayed_privkey=our_localdelayed_privkey
        )

        txs.append((htlc_tx.txid(), EncumberedTransaction(f'second_stage_to_wallet_{bh2u(htlc.payment_hash)}', to_wallet_tx, csv_delay=to_self_delay, cltv_expiry=0)))
        txs.append((ctx.txid(), EncumberedTransaction(f'our_ctx_htlc_tx_{bh2u(htlc.payment_hash)}', htlc_tx, csv_delay=0, cltv_expiry=htlc.cltv_expiry)))

    return txs


def create_sweeptx_that_spends_htlctx_that_spends_offered_htlc_in_our_ctx(
        to_self_delay: int, htlc_tx: Transaction,
        htlctx_witness_script: bytes, sweep_address: str,
        our_localdelayed_privkey: ecc.ECPrivkey, fee_per_kb: int=None) -> Transaction:
    assert to_self_delay is not None
    val = htlc_tx.outputs()[0].value
    second_stage_inputs = [{
        'scriptSig': '',
        'type': 'p2wsh',
        'signatures': [],
        'num_sig': 0,
        'prevout_n': 0,
        'prevout_hash': htlc_tx.txid(),
        'value': val,
        'coinbase': False,
        'preimage_script': bh2u(htlctx_witness_script),
        'sequence': to_self_delay,
    }]
    tx_size_bytes = 999  # TODO
    if fee_per_kb is None: fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
    fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
    second_stage_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, val - fee)]
    tx = Transaction.from_io(second_stage_inputs, second_stage_outputs, version=2)

    our_localdelayed_privkey_bytes = our_localdelayed_privkey.get_secret_bytes()
    witness = construct_witness([bfh(tx.sign_txin(0, our_localdelayed_privkey_bytes)), 0, htlctx_witness_script])
    tx.inputs()[0]['witness'] = witness
    assert tx.is_complete()
    return tx


def create_sweeptx_that_spends_to_local_in_our_ctx(
        ctx: Transaction, sweep_address: str, our_localdelayed_privkey: ecc.ECPrivkey,
        remote_revocation_pubkey: bytes, to_self_delay: int) -> Optional[Transaction]:
    our_localdelayed_pubkey = our_localdelayed_privkey.get_public_key_bytes(compressed=True)
    to_local_witness_script = bh2u(make_commitment_output_to_local_witness_script(
        remote_revocation_pubkey, to_self_delay, our_localdelayed_pubkey))
    to_local_address = redeem_script_to_address('p2wsh', to_local_witness_script)
    for output_idx, o in enumerate(ctx.outputs()):
        if o.type == TYPE_ADDRESS and o.address == to_local_address:
            sweep_tx = create_sweeptx_ctx_to_local(sweep_address=sweep_address,
                                                   ctx=ctx,
                                                   output_idx=output_idx,
                                                   witness_script=to_local_witness_script,
                                                   privkey=our_localdelayed_privkey.get_secret_bytes(),
                                                   is_revocation=False,
                                                   to_self_delay=to_self_delay)
            return sweep_tx
    return None


def create_htlctx_our_ctx_offered(chan: 'Channel', our_pcp: bytes,
                                  ctx: Transaction, htlc: 'UpdateAddHtlc') -> Tuple[bytes, Transaction]:
    witness_script, htlc_tx = make_htlc_tx_with_open_channel(chan=chan,
                                                             pcp=our_pcp,
                                                             for_us=True,
                                                             we_receive=False,
                                                             commit=ctx,
                                                             htlc=htlc)

    remote_htlc_sig = chan.get_remote_htlc_sig_for_htlc(htlc, we_receive=False)

    remote_revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey, our_pcp)
    remote_htlc_pubkey = derive_pubkey(chan.config[REMOTE].htlc_basepoint.pubkey, our_pcp)
    local_htlc_key = derive_privkey(secret=int.from_bytes(chan.config[LOCAL].htlc_basepoint.privkey, 'big'),
                                    per_commitment_point=our_pcp).to_bytes(32, 'big')

    local_htlc_sig = bfh(htlc_tx.sign_txin(0, local_htlc_key))

    program = make_offered_htlc(revocation_pubkey=remote_revocation_pubkey,
                                remote_htlcpubkey=remote_htlc_pubkey,
                                local_htlcpubkey=privkey_to_pubkey(local_htlc_key),
                                payment_hash=htlc.payment_hash)
    htlc_tx.inputs()[0]['witness'] = bh2u(make_htlc_tx_witness(remote_htlc_sig, local_htlc_sig, b'', program))
    return htlc_tx, witness_script


def create_sweeptx_their_ctx_to_remote(sweep_address: str, ctx: Transaction, output_idx: int,
                                       our_payment_privkey: ecc.ECPrivkey,
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
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, val-fee)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs)
    sweep_tx.set_rbf(True)
    sweep_tx.sign({our_payment_pubkey: (our_payment_privkey.get_secret_bytes(), True)})
    if not sweep_tx.is_complete():
        raise Exception('channel close sweep tx is not complete')
    return sweep_tx


def create_sweeptx_ctx_to_local(sweep_address: str, ctx: Transaction, output_idx: int, witness_script: str,
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
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, val - fee)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs, version=2)
    sig = sweep_tx.sign_txin(0, privkey)
    witness = construct_witness([sig, int(is_revocation), witness_script])
    sweep_tx.inputs()[0]['witness'] = witness
    return sweep_tx

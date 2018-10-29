# Copyright (C) 2018 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

from .util import bfh, bh2u, print_error
from .bitcoin import TYPE_ADDRESS, redeem_script_to_address, dust_threshold
from . import ecc
from .lnutil import (EncumberedTransaction,
                     make_commitment_output_to_remote_address, make_commitment_output_to_local_witness_script,
                     derive_privkey, derive_pubkey, derive_blinded_pubkey, derive_blinded_privkey,
                     make_htlc_tx_witness, make_htlc_tx_with_open_channel,
                     LOCAL, REMOTE, make_htlc_output_witness_script, UnknownPaymentHash)
from .transaction import Transaction, TxOutput, construct_witness
from .simple_config import SimpleConfig, FEERATE_FALLBACK_STATIC_FEE

if TYPE_CHECKING:
    from .lnchan import Channel, UpdateAddHtlc


def get_output_idx_from_txn_based_on_address(tx: Transaction, address: str) -> Optional[int]:
    for output_idx, o in enumerate(tx.outputs()):
        if o.type == TYPE_ADDRESS and o.address == address:
            break
    else:
        return None


def maybe_create_sweeptx_for_their_ctx_to_remote(ctx: Transaction, sweep_address: str,
                                                 our_payment_privkey: ecc.ECPrivkey) -> Optional[Transaction]:
    our_payment_pubkey = our_payment_privkey.get_public_key_bytes(compressed=True)
    to_remote_address = make_commitment_output_to_remote_address(our_payment_pubkey)
    output_idx = get_output_idx_from_txn_based_on_address(ctx, to_remote_address)
    if output_idx is None: return None
    sweep_tx = create_sweeptx_their_ctx_to_remote(sweep_address=sweep_address,
                                                  ctx=ctx,
                                                  output_idx=output_idx,
                                                  our_payment_privkey=our_payment_privkey)
    return sweep_tx


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
    output_idx = get_output_idx_from_txn_based_on_address(ctx, to_local_address)
    if output_idx is None: return None
    sweep_tx = create_sweeptx_ctx_to_local(sweep_address=sweep_address,
                                           ctx=ctx,
                                           output_idx=output_idx,
                                           witness_script=witness_script,
                                           privkey=revocation_privkey,
                                           is_revocation=True)
    if sweep_tx is None: return None
    return EncumberedTransaction('their_ctx_to_local', sweep_tx, csv_delay=0, cltv_expiry=0)


def create_sweeptxs_for_our_latest_ctx(chan: 'Channel', ctx: Transaction, our_pcp: bytes,
                                       sweep_address: str) -> List[Tuple[Optional[str],EncumberedTransaction]]:
    assert hasattr(ctx, 'htlc_output_indices'), "our latest ctx missing htlc indices dictionary"  # FIXME
    # prep
    delayed_bp_privkey = ecc.ECPrivkey(chan.config[LOCAL].delayed_basepoint.privkey)
    our_localdelayed_privkey = derive_privkey(delayed_bp_privkey.secret_scalar, our_pcp)
    our_localdelayed_privkey = ecc.ECPrivkey.from_secret_scalar(our_localdelayed_privkey)
    remote_revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey, our_pcp)
    to_self_delay = chan.config[REMOTE].to_self_delay
    local_htlc_privkey = derive_privkey(secret=int.from_bytes(chan.config[LOCAL].htlc_basepoint.privkey, 'big'),
                                        per_commitment_point=our_pcp).to_bytes(32, 'big')
    # to_local
    txs = []
    sweep_tx = maybe_create_sweeptx_that_spends_to_local_in_our_ctx(ctx=ctx,
                                                                    sweep_address=sweep_address,
                                                                    our_localdelayed_privkey=our_localdelayed_privkey,
                                                                    remote_revocation_pubkey=remote_revocation_pubkey,
                                                                    to_self_delay=to_self_delay)
    if sweep_tx:
        txs.append((None, EncumberedTransaction('our_ctx_to_local', sweep_tx, csv_delay=to_self_delay, cltv_expiry=0)))
    # HTLCs
    def create_txns_for_htlc(htlc: UpdateAddHtlc, is_received_htlc: bool) -> Tuple[Optional[Transaction], Optional[Transaction]]:
        if is_received_htlc:
            try:
                preimage, invoice = chan.get_preimage_and_invoice(htlc.payment_hash)
            except UnknownPaymentHash as e:
                print_error(f'trying to sweep htlc from our latest ctx but getting {repr(e)}')
                return None, None
        else:
            preimage = None
        htlctx_witness_script, htlc_tx = create_htlctx_that_spends_from_our_ctx(
            chan=chan,
            our_pcp=our_pcp,
            ctx=ctx,
            htlc=htlc,
            local_htlc_privkey=local_htlc_privkey,
            preimage=preimage,
            is_received_htlc=is_received_htlc)
        to_wallet_tx = create_sweeptx_that_spends_htlctx_that_spends_htlc_in_our_ctx(
            to_self_delay=to_self_delay,
            htlc_tx=htlc_tx,
            htlctx_witness_script=htlctx_witness_script,
            sweep_address=sweep_address,
            our_localdelayed_privkey=our_localdelayed_privkey
        )
        return htlc_tx, to_wallet_tx
    # offered HTLCs, in our ctx --> "timeout"
    offered_htlcs = list(chan.included_htlcs(LOCAL, LOCAL)) # type: List[UpdateAddHtlc]
    for htlc in offered_htlcs:
        htlc_tx, to_wallet_tx = create_txns_for_htlc(htlc, is_received_htlc=False)
        if htlc_tx and to_wallet_tx:
            txs.append((htlc_tx.txid(), EncumberedTransaction(f'second_stage_to_wallet_{bh2u(htlc.payment_hash)}', to_wallet_tx, csv_delay=to_self_delay, cltv_expiry=0)))
            txs.append((ctx.txid(), EncumberedTransaction(f'our_ctx_htlc_tx_{bh2u(htlc.payment_hash)}', htlc_tx, csv_delay=0, cltv_expiry=htlc.cltv_expiry)))
    # received HTLCs, in our ctx --> "success"
    received_htlcs = list(chan.included_htlcs(LOCAL, REMOTE))  # type: List[UpdateAddHtlc]
    for htlc in received_htlcs:
        htlc_tx, to_wallet_tx = create_txns_for_htlc(htlc, is_received_htlc=True)
        if htlc_tx and to_wallet_tx:
            txs.append((htlc_tx.txid(), EncumberedTransaction(f'second_stage_to_wallet_{bh2u(htlc.payment_hash)}', to_wallet_tx, csv_delay=to_self_delay, cltv_expiry=0)))
            txs.append((ctx.txid(), EncumberedTransaction(f'our_ctx_htlc_tx_{bh2u(htlc.payment_hash)}', htlc_tx, csv_delay=0, cltv_expiry=0)))
    return txs


# FIXME 'latest ctx'.. but they sometimes have two valid non-revoked commitment transactions,
# either of which could be broadcast.
def create_sweeptxs_for_their_latest_ctx(chan: 'Channel', ctx: Transaction, their_pcp: bytes,
                                         sweep_address: str) -> List[Tuple[Optional[str],EncumberedTransaction]]:
    # assert ctn(ctx) == ctn(their_pcp)
    # FIXME ^ use correct pcp...
    # try with self.config[REMOTE].next_per_commitment_point
    #     and also try with both self.config[REMOTE].current_per_commitment_point
    # add assert that compares extracted ctn to self.config[REMOTE].ctn
    # prep
    remote_revocation_pubkey = derive_blinded_pubkey(chan.config[REMOTE].revocation_basepoint.pubkey, their_pcp)
    local_htlc_privkey = derive_privkey(secret=int.from_bytes(chan.config[LOCAL].htlc_basepoint.privkey, 'big'),
                                        per_commitment_point=their_pcp)
    local_htlc_privkey = ecc.ECPrivkey.from_secret_scalar(local_htlc_privkey)
    remote_htlc_pubkey = derive_pubkey(chan.config[REMOTE].htlc_basepoint.pubkey, their_pcp)
    payment_bp_privkey = ecc.ECPrivkey(chan.config[LOCAL].payment_basepoint.privkey)
    our_payment_privkey = derive_privkey(payment_bp_privkey.secret_scalar, their_pcp)
    our_payment_privkey = ecc.ECPrivkey.from_secret_scalar(our_payment_privkey)
    # to_remote
    txs = []
    sweep_tx = maybe_create_sweeptx_for_their_ctx_to_remote(ctx=ctx,
                                                            sweep_address=sweep_address,
                                                            our_payment_privkey=our_payment_privkey)
    if sweep_tx:
        txs.append((None, EncumberedTransaction('their_ctx_to_remote', sweep_tx, csv_delay=0, cltv_expiry=0)))
    # HTLCs
    def create_sweeptx_for_htlc(htlc: UpdateAddHtlc, is_received_htlc: bool) -> Optional[Transaction]:
        if not is_received_htlc:
            try:
                preimage, invoice = chan.get_preimage_and_invoice(htlc.payment_hash)
            except UnknownPaymentHash as e:
                print_error(f'trying to sweep htlc from their latest ctx but getting {repr(e)}')
                return None
        else:
            preimage = None
        htlc_output_witness_script = make_htlc_output_witness_script(
            is_received_htlc=is_received_htlc,
            remote_revocation_pubkey=remote_revocation_pubkey,
            remote_htlc_pubkey=remote_htlc_pubkey,
            local_htlc_pubkey=local_htlc_privkey.get_public_key_bytes(compressed=True),
            payment_hash=htlc.payment_hash,
            cltv_expiry=htlc.cltv_expiry)
        sweep_tx = maybe_create_sweeptx_for_their_latest_ctx_htlc(
            ctx=ctx,
            sweep_address=sweep_address,
            htlc_output_witness_script=htlc_output_witness_script,
            our_local_htlc_privkey=local_htlc_privkey,
            preimage=preimage)
        return sweep_tx
    # received HTLCs, in their ctx --> "timeout"
    received_htlcs = list(chan.included_htlcs(REMOTE, LOCAL)) # type: List[UpdateAddHtlc]
    for htlc in received_htlcs:
        sweep_tx = create_sweeptx_for_htlc(htlc, is_received_htlc=True)
        if sweep_tx:
            txs.append((ctx.txid(), EncumberedTransaction(f'their_ctx_sweep_htlc_{bh2u(htlc.payment_hash)}', sweep_tx, csv_delay=0, cltv_expiry=htlc.cltv_expiry)))
    # offered HTLCs, in their ctx --> "success"
    offered_htlcs = list(chan.included_htlcs(REMOTE, REMOTE))  # type: List[UpdateAddHtlc]
    for htlc in offered_htlcs:
        sweep_tx = create_sweeptx_for_htlc(htlc, is_received_htlc=False)
        if sweep_tx:
            txs.append((ctx.txid(), EncumberedTransaction(f'their_ctx_sweep_htlc_{bh2u(htlc.payment_hash)}', sweep_tx, csv_delay=0, cltv_expiry=0)))
    return txs


def create_sweeptx_that_spends_htlctx_that_spends_htlc_in_our_ctx(
        to_self_delay: int, htlc_tx: Transaction,
        htlctx_witness_script: bytes, sweep_address: str,
        our_localdelayed_privkey: ecc.ECPrivkey, fee_per_kb: int=None) -> Transaction:
    assert to_self_delay is not None
    val = htlc_tx.outputs()[0].value
    sweep_inputs = [{
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
    tx_size_bytes = 200  # TODO
    if fee_per_kb is None: fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
    fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, val - fee)]
    tx = Transaction.from_io(sweep_inputs, sweep_outputs, version=2)

    our_localdelayed_privkey_bytes = our_localdelayed_privkey.get_secret_bytes()
    local_delayed_sig = bfh(tx.sign_txin(0, our_localdelayed_privkey_bytes))
    witness = construct_witness([local_delayed_sig, 0, htlctx_witness_script])
    tx.inputs()[0]['witness'] = witness
    assert tx.is_complete()
    return tx


def maybe_create_sweeptx_that_spends_to_local_in_our_ctx(
        ctx: Transaction, sweep_address: str, our_localdelayed_privkey: ecc.ECPrivkey,
        remote_revocation_pubkey: bytes, to_self_delay: int) -> Optional[Transaction]:
    our_localdelayed_pubkey = our_localdelayed_privkey.get_public_key_bytes(compressed=True)
    to_local_witness_script = bh2u(make_commitment_output_to_local_witness_script(
        remote_revocation_pubkey, to_self_delay, our_localdelayed_pubkey))
    to_local_address = redeem_script_to_address('p2wsh', to_local_witness_script)
    output_idx = get_output_idx_from_txn_based_on_address(ctx, to_local_address)
    if output_idx is None: return None
    sweep_tx = create_sweeptx_ctx_to_local(sweep_address=sweep_address,
                                           ctx=ctx,
                                           output_idx=output_idx,
                                           witness_script=to_local_witness_script,
                                           privkey=our_localdelayed_privkey.get_secret_bytes(),
                                           is_revocation=False,
                                           to_self_delay=to_self_delay)
    if sweep_tx is None: return None
    return sweep_tx


def create_htlctx_that_spends_from_our_ctx(chan: 'Channel', our_pcp: bytes,
                                           ctx: Transaction, htlc: 'UpdateAddHtlc',
                                           local_htlc_privkey: bytes, preimage: Optional[bytes],
                                           is_received_htlc: bool) -> Tuple[bytes, Transaction]:
    assert is_received_htlc == bool(preimage), 'preimage is required iff htlc is received'
    preimage = preimage or b''
    witness_script, htlc_tx = make_htlc_tx_with_open_channel(chan=chan,
                                                             pcp=our_pcp,
                                                             for_us=True,
                                                             we_receive=is_received_htlc,
                                                             commit=ctx,
                                                             htlc=htlc)
    remote_htlc_sig = chan.get_remote_htlc_sig_for_htlc(htlc, we_receive=is_received_htlc)
    local_htlc_sig = bfh(htlc_tx.sign_txin(0, local_htlc_privkey))
    txin = htlc_tx.inputs()[0]
    witness_program = bfh(Transaction.get_preimage_script(txin))
    txin['witness'] = bh2u(make_htlc_tx_witness(remote_htlc_sig, local_htlc_sig, preimage, witness_program))
    return witness_script, htlc_tx


def maybe_create_sweeptx_for_their_latest_ctx_htlc(ctx: Transaction, sweep_address: str,
                                                   htlc_output_witness_script: bytes,
                                                   our_local_htlc_privkey: ecc.ECPrivkey,
                                                   preimage: Optional[bytes]) -> Optional[Transaction]:
    htlc_address = redeem_script_to_address('p2wsh', bh2u(htlc_output_witness_script))
    output_idx = get_output_idx_from_txn_based_on_address(ctx, htlc_address)
    if output_idx is None: return None
    sweep_tx = create_sweeptx_their_latest_ctx_htlc(ctx=ctx,
                                                    witness_script=htlc_output_witness_script,
                                                    sweep_address=sweep_address,
                                                    preimage=preimage,
                                                    output_idx=output_idx,
                                                    our_local_htlc_privkey=our_local_htlc_privkey)
    return sweep_tx


def create_sweeptx_their_latest_ctx_htlc(ctx: Transaction, witness_script: bytes, sweep_address: str,
                                         preimage: Optional[bytes], output_idx: int,
                                         our_local_htlc_privkey: ecc.ECPrivkey,
                                         fee_per_kb: int=None) -> Optional[Transaction]:
    preimage = preimage or b''  # preimage is required iff htlc is offered
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
        'preimage_script': bh2u(witness_script),
    }]
    tx_size_bytes = 200  # TODO
    if fee_per_kb is None: fee_per_kb = FEERATE_FALLBACK_STATIC_FEE
    fee = SimpleConfig.estimate_fee_for_feerate(fee_per_kb, tx_size_bytes)
    outvalue = val - fee
    if outvalue <= dust_threshold(): return None
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, outvalue)]
    tx = Transaction.from_io(sweep_inputs, sweep_outputs, version=2)

    our_local_htlc_privkey_bytes = our_local_htlc_privkey.get_secret_bytes()
    sig = bfh(tx.sign_txin(0, our_local_htlc_privkey_bytes))
    witness = construct_witness([sig, preimage, witness_script])
    tx.inputs()[0]['witness'] = witness
    assert tx.is_complete()
    return tx


def create_sweeptx_their_ctx_to_remote(sweep_address: str, ctx: Transaction, output_idx: int,
                                       our_payment_privkey: ecc.ECPrivkey,
                                       fee_per_kb: int=None) -> Optional[Transaction]:
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
    outvalue = val - fee
    if outvalue <= dust_threshold(): return None
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, outvalue)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs)
    sweep_tx.set_rbf(True)
    sweep_tx.sign({our_payment_pubkey: (our_payment_privkey.get_secret_bytes(), True)})
    if not sweep_tx.is_complete():
        raise Exception('channel close sweep tx is not complete')
    return sweep_tx


def create_sweeptx_ctx_to_local(sweep_address: str, ctx: Transaction, output_idx: int, witness_script: str,
                                privkey: bytes, is_revocation: bool,
                                to_self_delay: int=None,
                                fee_per_kb: int=None) -> Optional[Transaction]:
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
    outvalue = val - fee
    if outvalue <= dust_threshold(): return None
    sweep_outputs = [TxOutput(TYPE_ADDRESS, sweep_address, outvalue)]
    sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs, version=2)
    sig = sweep_tx.sign_txin(0, privkey)
    witness = construct_witness([sig, int(is_revocation), witness_script])
    sweep_tx.inputs()[0]['witness'] = witness
    return sweep_tx

from .util import PrintError, bh2u, bfh
from .lnutil import (funding_output_script, extract_ctn_from_tx, derive_privkey,
                     get_per_commitment_secret_from_seed, derive_pubkey,
                     make_commitment_output_to_remote_address,
                     RevocationStore, UnableToDeriveSecret)
from . import lnutil
from .bitcoin import redeem_script_to_address, TYPE_ADDRESS
from . import transaction
from .transaction import Transaction
from . import ecc

class LNWatcher(PrintError):

    def __init__(self, network):
        self.network = network
        self.watched_channels = {}

    def parse_response(self, response):
        if response.get('error'):
            self.print_error("response error:", response)
            return None, None
        return response['params'], response['result']

    def watch_channel(self, chan, callback):
        funding_address = funding_address_for_channel(chan)
        self.watched_channels[funding_address] = chan, callback
        self.network.subscribe_to_addresses([funding_address], self.on_address_status)

    def on_address_status(self, response):
        params, result = self.parse_response(response)
        if not params:
            return
        addr = params[0]
        self.network.request_address_utxos(addr, self.on_utxos)

    def on_utxos(self, response):
        params, result = self.parse_response(response)
        if not params:
            return
        addr = params[0]
        chan, callback = self.watched_channels[addr]
        callback(chan, result)


def funding_address_for_channel(chan):
    script = funding_output_script(chan.local_config, chan.remote_config)
    return redeem_script_to_address('p2wsh', script)


class LNChanCloseHandler(PrintError):

    def __init__(self, network, wallet, chan):
        self.network = network
        self.wallet = wallet
        self.chan = chan
        self.funding_address = funding_address_for_channel(chan)
        network.request_address_history(self.funding_address, self.on_history)

    # TODO: de-duplicate?
    def parse_response(self, response):
        if response.get('error'):
            self.print_error("response error:", response)
            return None, None
        return response['params'], response['result']

    def on_history(self, response):
        params, result = self.parse_response(response)
        if not params:
            return
        addr = params[0]
        if self.funding_address != addr:
            self.print_error("unexpected funding address: {} != {}"
                             .format(self.funding_address, addr))
            return
        txids = set(map(lambda item: item['tx_hash'], result))
        self.network.get_transactions(txids, self.on_tx_response)

    def on_tx_response(self, response):
        params, result = self.parse_response(response)
        if not params:
            return
        tx_hash = params[0]
        tx = Transaction(result)
        try:
            tx.deserialize()
        except Exception:
            self.print_msg("cannot deserialize transaction", tx_hash)
            return
        if tx_hash != tx.txid():
            self.print_error("received tx does not match expected txid ({} != {})"
                             .format(tx_hash, tx.txid()))
            return
        funding_outpoint = self.chan.funding_outpoint
        for i, txin in enumerate(tx.inputs()):
            if txin['prevout_hash'] == funding_outpoint.txid \
                    and txin['prevout_n'] == funding_outpoint.output_index:
                self.print_error("funding outpoint {} is spent by {}"
                                 .format(funding_outpoint, tx_hash))
                self.inspect_spending_tx(tx, i)
                break

    # TODO batch txns
    def inspect_spending_tx(self, ctx, txin_index):
        chan = self.chan
        ctn = extract_ctn_from_tx(ctx, txin_index,
                                  chan.local_config.payment_basepoint,
                                  chan.remote_config.payment_basepoint)
        latest_local_ctn = chan.local_state.ctn - 1
        latest_remote_ctn = chan.remote_state.ctn
        self.print_error("ctx {} has ctn {}. latest local ctn is {}, latest remote ctn is {}"
                         .format(ctx.txid(), ctn, latest_local_ctn, latest_remote_ctn))
        # figure out our payment privkey from ctn
        payment_bp_secret = chan.local_config.payment_basepoint.privkey
        our_per_commitment_secret = get_per_commitment_secret_from_seed(
            chan.local_state.per_commitment_secret_seed, RevocationStore.start_index - ctn)
        our_per_commitment_point = ecc.ECPrivkey(our_per_commitment_secret).get_public_key_bytes(compressed=True)
        our_payment_privkey = derive_privkey(payment_bp_secret, our_per_commitment_point)
        our_payment_privkey = ecc.ECPrivkey.from_secret_scalar(our_payment_privkey)
        # calc what to_remote output that pays to our_payment_privkey would look like
        our_payment_pubkey = our_payment_privkey.get_public_key_bytes(compressed=True)
        to_remote_address = make_commitment_output_to_remote_address(our_payment_pubkey)
        # if *they* broadcasted commitment txn, there should be a to_remote output
        # paying to us -- unless it was trimmed (dust)
        for output_idx, (type, addr, val) in enumerate(ctx.outputs()):
            if type == TYPE_ADDRESS and addr == to_remote_address:
                self.print_error("found to_remote output paying to us: ctx {}:{}".
                                 format(ctx.txid(), output_idx))
                if ctn == latest_remote_ctn:
                    self.print_error("ctx {} is normal unilateral close by them".format(ctx.txid()))
                else:
                    self.print_error("ctx {} is breach!! by them. ctn {}, latest remote ctn {}"
                                     .format(ctx.txid(), ctn, latest_remote_ctn))
                self.sweep_our_to_remote(ctx, output_idx, our_payment_privkey)
        # see if we have a revoked secret for this ctn
        try:
            per_commitment_secret = chan.remote_state.revocation_store.retrieve_secret(
                RevocationStore.start_index - ctn)
        except UnableToDeriveSecret:
            pass
        else:
            if our_per_commitment_secret == per_commitment_secret:
                # this is our ctx.. we did a unilateral close
                if ctn == latest_local_ctn:
                    self.print_error("ctx {} is normal unilateral close by them".format(ctx.txid()))
                else:
                    self.print_error("ctx {} is breach by us. :( ctn {}, latest remote ctn {}"
                                     .format(ctx.txid(), ctn, latest_local_ctn))
                # TODO utxo nursery
            else:
                self.print_error("ctx {} is breach!! by them and we have the revocation secret. "
                                 "yay, free money".format(ctx.txid()))
                self.sweep_their_to_local(ctx, per_commitment_secret)
                # TODO sweep other outputs

    def sweep_our_to_remote(self, ctx, output_idx, our_payment_privkey: ecc.ECPrivkey):
        our_payment_pubkey = our_payment_privkey.get_public_key_hex(compressed=True)
        val = ctx.outputs()[output_idx][2]
        sweep_inputs = [{
            'type': 'p2wpkh',
            'x_pubkeys': [our_payment_pubkey],
            'num_sig': 1,
            'prevout_n': output_idx,
            'prevout_hash': ctx.txid(),
            'value': val,
            'coinbase': False,
        }]
        fee = self.network.config.estimate_fee(110)  # approx size of p2wpkh->p2wpkh
        sweep_outputs = [(TYPE_ADDRESS, self.wallet.get_receiving_address(), val-fee)]
        locktime = self.network.get_local_height()
        sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs, locktime=locktime)
        sweep_tx.set_rbf(True)
        sweep_tx.sign({our_payment_pubkey: (our_payment_privkey.get_secret_bytes(), True)})
        if not sweep_tx.is_complete():
            raise Exception('channel close sweep tx is not complete')
        self.network.broadcast_transaction(sweep_tx)

    def sweep_their_to_local(self, ctx, per_commitment_secret: bytes):
        per_commitment_point = ecc.ECPrivkey(per_commitment_secret).get_public_key_bytes(compressed=True)
        revocation_privkey = lnutil.derive_blinded_privkey(self.chan.local_config.revocation_basepoint.privkey,
                                                           per_commitment_secret)
        revocation_pubkey = ecc.ECPrivkey(revocation_privkey).get_public_key_bytes(compressed=True)
        to_self_delay = self.chan.local_config.to_self_delay
        delayed_pubkey = derive_pubkey(self.chan.remote_config.delayed_basepoint,
                                       per_commitment_point)
        witness_script = lnutil.make_commitment_output_to_local_witness_script(
            revocation_pubkey, to_self_delay, delayed_pubkey)
        to_local_address = redeem_script_to_address('p2wsh', bh2u(witness_script))
        for output_idx, (type, addr, val) in enumerate(ctx.outputs()):
            if type == TYPE_ADDRESS and addr == to_local_address:
                break
        else:
            self.print_error('could not find to_local output in their ctx {}'.format(ctx.txid()))
            return
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
        fee = self.network.config.estimate_fee(200)  # TODO calc size
        sweep_outputs = [(TYPE_ADDRESS, self.wallet.get_receiving_address(), val - fee)]
        locktime = self.network.get_local_height()
        sweep_tx = Transaction.from_io(sweep_inputs, sweep_outputs, locktime=locktime)
        sweep_tx.set_rbf(True)
        revocation_sig = sweep_tx.sign_txin(0, revocation_privkey)
        witness = transaction.construct_witness([revocation_sig, 1, witness_script])
        sweep_tx.inputs()[0]['witness'] = witness
        self.network.broadcast_transaction(sweep_tx)

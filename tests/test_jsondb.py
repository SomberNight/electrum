import copy
import json
import os
from typing import Dict
from unittest import mock

from . import ElectrumTestCase
from .test_txbatcher import SWAPDATA

from electrum.wallet import restore_wallet_from_text, Abstract_Wallet
from electrum.simple_config import SimpleConfig
from electrum.submarine_swaps import SwapData
from electrum.crypto import sha256
from electrum.daemon import Daemon
from electrum.storage import WalletStorage


class TestJsonDB(ElectrumTestCase):

    def setUp(self):
        super().setUp()
        self.config = SimpleConfig({'electrum_path': self.electrum_path})
        self.wallet_path = os.path.join(self.electrum_path, "somewallet")

    @mock.patch.object(WalletStorage, 'needs_consolidation', new=lambda storage: False)
    async def test_pop_outer_object_then_modify_contents_of_orphaned_reference(self):
        wallet: Abstract_Wallet = restore_wallet_from_text(
            'bitter grass shiver impose acquire brush forget axis eager alone wine silver',
            gap_limit=2,
            path=self.wallet_path,
            config=self.config)['wallet']
        swaps = wallet.db.get_dict('submarine_swaps')  # type: Dict[str, SwapData]
        swap1 = copy.deepcopy(SWAPDATA)
        swap1._payment_hash = sha256(b"deadbeef1")
        swap2 = copy.deepcopy(SWAPDATA)
        swap2._payment_hash = sha256(b"deadbeef2")

        cnt_pending_changes = 0
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))

        swaps[swap1.payment_hash.hex()] = swap1
        cnt_pending_changes += 1
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))
        self.assertEqual(json.loads(wallet.db.pending_changes[-1])["op"], "add")
        self.assertEqual(len(swaps), 1)

        swaps[swap2.payment_hash.hex()] = swap2
        cnt_pending_changes += 1
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))
        self.assertEqual(json.loads(wallet.db.pending_changes[-1])["op"], "add")
        self.assertEqual(len(swaps), 2)

        swap1.spending_txid = 64 * "1"
        cnt_pending_changes += 1
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))
        self.assertEqual(json.loads(wallet.db.pending_changes[-1])["op"], "replace")

        swaps.pop(swap1.payment_hash.hex())
        cnt_pending_changes += 1
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))
        self.assertEqual(json.loads(wallet.db.pending_changes[-1])["op"], "remove")
        self.assertEqual(len(swaps), 1)

        swap1.spending_txid = 64 * "2"  # FIXME maybe this should raise?? ref is already orphaned.
        cnt_pending_changes += 1
        self.assertEqual(cnt_pending_changes, len(wallet.db.pending_changes))
        self.assertEqual(json.loads(wallet.db.pending_changes[-1])["op"], "replace")

        await wallet.stop()
        del wallet
        del swaps
        wallet = Daemon._load_wallet(self.wallet_path, password=None, config=self.config)
        self.assertEqual(len(wallet.db.pending_changes), 0)
        swaps = wallet.db.get_dict('submarine_swaps')  # type: Dict[str, SwapData]
        self.assertEqual(len(swaps), 1)

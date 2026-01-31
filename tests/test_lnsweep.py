import os

from electrum.simple_config import SimpleConfig

from . import ElectrumTestCase
from . import restore_wallet_from_text__for_unittest


class TestLNSweep(ElectrumTestCase):
    REGTEST = True

    def setUp(self):
        super().setUp()
        self.config = SimpleConfig({'electrum_path': self.electrum_path})
        self.wallets_path = self.config.get_datadir_wallet_path()

    async def test_foo(self):
        w1 = restore_wallet_from_text__for_unittest("9dk", passphrase="alice", path=os.path.join(self.wallets_path, "alice"), config=self.config)['wallet']
        assert w1.lnworker




# Copyright (C) 2020 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel

from electrum.i18n import _
from electrum.network import Network
from electrum.bip39_recovery import account_discovery

from .util import WindowModalDialog, MessageBoxMixin, TaskThread, Buttons, CancelButton, OkButton

class Bip39RecoveryDialog(WindowModalDialog):
    def __init__(self, parent: QWidget, seed, passphrase):
        assert parent
        if isinstance(parent, MessageBoxMixin):
            parent = parent.top_level_window()
        self.seed = seed
        self.passphrase = passphrase
        WindowModalDialog.__init__(self, parent, _('BIP39 Recovery'))
        self.setMinimumWidth(400)
        vbox = QVBoxLayout(self)
        h = QGridLayout()
        h.addWidget(QLabel(_('Loading...')))
        vbox.addLayout(h)
        vbox.addLayout(Buttons(CancelButton(self), OkButton(self)))
        self.show()
        self.thread = TaskThread(self)
        self.thread.finished.connect(self.deleteLater) # see #3956
        self.thread.add(self.recovery, self.on_recovery_success, None, self.on_recovery_error)

    def recovery(self):
        network = Network.get_instance()
        coro = account_discovery(network, self.seed, self.passphrase)
        return network.run_from_another_thread(coro)

    def on_recovery_success(self, result):
        print("success", result)

    def on_recovery_error(self, result):
        print("error", result)

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
        self.seed = seed
        self.passphrase = passphrase
        WindowModalDialog.__init__(self, parent, _('BIP39 Recovery'))
        self.setMinimumWidth(400)
        vbox = QVBoxLayout(self)
        self.content = QVBoxLayout()
        self.content.addWidget(QLabel(_('Loading...')))
        vbox.addLayout(self.content)
        vbox.addLayout(Buttons(CancelButton(self), OkButton(self)))
        self.show()
        self.thread = TaskThread(self)
        self.thread.finished.connect(self.deleteLater) # see #3956
        self.thread.add(self.recovery, self.on_recovery_success, None, self.on_recovery_error)

    def recovery(self):
        network = Network.get_instance()
        coroutine = account_discovery(network, self.seed, self.passphrase)
        return network.run_from_another_thread(coroutine)

    def on_recovery_success(self, result):
        self.clear_content()
        self.content.addWidget(QLabel(_('Success!')))
        print("success", result)

    def on_recovery_error(self, error):
        self.clear_content()
        self.content.addWidget(QLabel(_('Error: Account discovery failed.')))

    def clear_content(self):
        for i in reversed(range(self.content.count())):
            self.content.itemAt(i).widget().setParent(None)

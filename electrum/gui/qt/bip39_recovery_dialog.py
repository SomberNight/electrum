# Copyright (C) 2020 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel
from electrum.i18n import _
from .util import WindowModalDialog, MessageBoxMixin, Buttons, CancelButton, OkButton

class Bip39RecoveryDialog(WindowModalDialog):
    def __init__(self, parent: QWidget):
        assert parent
        if isinstance(parent, MessageBoxMixin):
            parent = parent.top_level_window()
        WindowModalDialog.__init__(self, parent, _('BIP39 Recovery'))
        self.setMinimumWidth(400)
        vbox = QVBoxLayout(self)
        h = QGridLayout()
        h.addWidget(QLabel(_('Loading...')))
        vbox.addLayout(h)
        vbox.addLayout(Buttons(CancelButton(self), OkButton(self)))
        self.exec()

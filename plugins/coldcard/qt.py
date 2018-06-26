import time

from electrum.i18n import _
from electrum.plugins import hook
from electrum.wallet import Standard_Wallet
from electrum_gui.qt.util import *

from .coldcard import ColdcardPlugin
from ..hw_wallet.qt import QtHandlerBase, QtPluginBase


class Plugin(ColdcardPlugin, QtPluginBase):
    icon_unpaired = ":icons/coldcard_unpaired.png"
    icon_paired = ":icons/coldcard.png"

    def create_handler(self, window):
        return Coldcard_Handler(window)

    @hook
    def receive_menu(self, menu, addrs, wallet):
        if type(wallet) is not Standard_Wallet:
            return
        keystore = wallet.get_keystore()
        if type(keystore) == self.keystore_class and len(addrs) == 1:
            def show_address():
                keystore.thread.add(partial(self.show_address, wallet, addrs[0]))
            menu.addAction(_("Show on Coldcard"), show_address)

    @hook
    def transaction_dialog(self, dia):
        # see gui/qt/transaction_dialog.py

        keystore = dia.wallet.get_keystore()
        if type(keystore) != self.keystore_class:
            # not a Coldcard wallet, hide feature
            return

        # - add a new button, near "export"
        btn = QPushButton(_("Save PSBT"))
        btn.clicked.connect(lambda unused: self.export_psbt(dia))
        if dia.tx.is_complete():
            # but disable it for signed transactions (nothing to do if already signed)
            btn.setDisabled(True)

        dia.sharing_buttons.append(btn)

    def export_psbt(self, dia):
        # Called from hook in transaction dialog
        tx = dia.tx
        assert not tx.is_complete(), 'expect unsigned txn'

        # can only expect Coldcard wallets to work with these files (right now)
        keystore = dia.wallet.get_keystore()
        assert type(keystore) == self.keystore_class

        # convert to PSBT
        raw_psbt = keystore.build_psbt(tx, wallet=dia.wallet)

        name = (dia.wallet.basename() + time.strftime('-%y%m%d-%H%M.psbt')).replace(' ', '-')
        fileName = dia.main_window.getSaveFileName(_("Select where to save the PSBT file"),
                                                        name, "*.psbt")
        if fileName:
            with open(fileName, "wb+") as f:
                f.write(raw_psbt)
            dia.show_message(_("Transaction exported successfully"))
            dia.saved = True


class Coldcard_Handler(QtHandlerBase):
    setup_signal = pyqtSignal()
    #auth_signal = pyqtSignal(object)

    def __init__(self, win):
        super(Coldcard_Handler, self).__init__(win, 'Coldcard')
        self.setup_signal.connect(self.setup_dialog)
        #self.auth_signal.connect(self.auth_dialog)

    
    def message_dialog(self, msg):
        self.clear_dialog()
        self.dialog = dialog = WindowModalDialog(self.top_level_window(), _("Coldcard Status"))
        l = QLabel(msg)
        vbox = QVBoxLayout(dialog)
        vbox.addWidget(l)
        dialog.show()
        
    def get_setup(self):
        self.done.clear()
        self.setup_signal.emit()
        self.done.wait()
        return 
        
    def setup_dialog(self):
        self.show_error(_('Please initialization your Coldcard while disconnected.'))
        return

# EOF

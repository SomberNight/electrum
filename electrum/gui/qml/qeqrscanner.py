import os

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot, QObject

from electrum.util import send_exception_to_crash_reporter
from electrum.logging import get_logger


if 'ANDROID_DATA' in os.environ:
    from jnius import autoclass, cast
    from android import activity

    jpythonActivity = autoclass('org.kivy.android.PythonActivity').mActivity
    jString = autoclass('java.lang.String')
    jIntent = autoclass('android.content.Intent')


class QEQRScanner(QObject):
    _logger = get_logger(__name__)

    found = pyqtSignal([str], arguments=['data'])

    @pyqtSlot(str)
    def scan_qr(self, hint: str):
        if 'ANDROID_DATA' not in os.environ:
            return
        SimpleScannerActivity = autoclass("org.electrum.qr.SimpleScannerActivity")
        intent = jIntent(jpythonActivity, SimpleScannerActivity)
        intent.putExtra(jIntent.EXTRA_TEXT, jString(hint))

        def on_qr_result(requestCode, resultCode, intent):
            try:
                if resultCode == -1:  # RESULT_OK:
                    #  this doesn't work due to some bug in jnius:
                    # contents = intent.getStringExtra("text")
                    contents = intent.getStringExtra(jString("text"))
                    self._logger.info(f"on_qr_result. {contents=!r}")
                    self.found.emit(contents)
            except Exception as e:  # exc would otherwise get lost
                send_exception_to_crash_reporter(e)
            finally:
                activity.unbind(on_activity_result=on_qr_result)
        activity.bind(on_activity_result=on_qr_result)
        jpythonActivity.startActivityForResult(intent, 0)

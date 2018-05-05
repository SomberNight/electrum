from keepkeylib.client import proto, BaseClient, ProtocolMixin

from .clientbase import KeepKeyClientBase
from ..hw_wallet import run_in_threadpool


class KeepKeyClient(KeepKeyClientBase, ProtocolMixin, BaseClient):
    def __init__(self, transport, handler, plugin):
        BaseClient.__init__(self, transport)
        ProtocolMixin.__init__(self, transport)
        KeepKeyClientBase.__init__(self, handler, plugin, proto)

        try:
            transport._read = run_in_threadpool(transport._read, client=self)
        except:
            self.print_error('monkey-patching transport._read failed')

    def recovery_device(self, *args):
        ProtocolMixin.recovery_device(self, False, *args)


KeepKeyClientBase.wrap_methods(KeepKeyClient)

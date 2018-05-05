from trezorlib.client import proto, BaseClient, ProtocolMixin

from .clientbase import TrezorClientBase
from ..hw_wallet import run_in_threadpool


class TrezorClient(TrezorClientBase, ProtocolMixin, BaseClient):
    def __init__(self, transport, handler, plugin):
        BaseClient.__init__(self, transport=transport)
        ProtocolMixin.__init__(self, transport=transport)
        TrezorClientBase.__init__(self, handler, plugin, proto)

        try:
            transport.read = run_in_threadpool(transport.read, client=self)
        except:
            self.print_error('monkey-patching transport.read failed')


TrezorClientBase.wrap_methods(TrezorClient)

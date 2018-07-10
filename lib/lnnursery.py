import queue

from .util import PrintError
from .lnutil import Outpoint

NUM_BLOCK_DEPTH = 6  # num confs we consider 'sufficiently deep' for most purposes

class LNNursery(PrintError):

    _taskq_counter = 0  # just to break ties; implementation detail

    def __init__(self, network, wallet):
        self.network = network
        self.wallet = wallet
        self.last_height_handled = 0  # TODO persist
        self.blockchain = network.blockchain()  # TODO persist
        self._tasks = queue.PriorityQueue()  # values: (height, _, NurseryTask)  # TODO persist
        network.register_callback(self.on_network_update, ['updated'])

    def on_network_update(self, event):
        network_chain = self.network.blockchain()
        if network_chain != self.blockchain:
            self.blockchain = network_chain
            self.handle_reorg()
        h = self.network.get_local_height()
        if h <= self.last_height_handled:
            return
        # TODO ...

        self.last_height_handled = h

    def handle_reorg(self):
        pass  # TODO
        # roll back self.last_height_handled


class NurseryTask:

    def __init__(self, prevout: Outpoint, csv_lock: int, localdelayed_privkey: bytes, witness_script: str):
        pass

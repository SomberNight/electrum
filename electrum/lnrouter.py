# -*- coding: utf-8 -*-
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2018 The Electrum developers
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import queue
import traceback
import sys
import binascii
import hashlib
import hmac
import os
import json
import threading
from collections import namedtuple, defaultdict
from typing import Sequence, Union, Tuple, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.backends import default_backend

from . import bitcoin
from . import ecc
from . import crypto
from . import constants
from .crypto import sha256
from .util import PrintError, bh2u, profiler, xor_bytes, get_headers_dir, bfh
from .lnutil import get_ecdh
from .storage import JsonDB
from .lnchanannverifier import LNChanAnnVerifier


class ChannelInfo(PrintError):
    # TODO other fields from channel announcement

    def __init__(self, channel_announcement_payload):
        self.channel_id = channel_announcement_payload['short_channel_id']
        self.node_id_1 = channel_announcement_payload['node_id_1']
        self.node_id_2 = channel_announcement_payload['node_id_2']
        assert type(self.node_id_1) is bytes
        assert type(self.node_id_2) is bytes
        assert list(sorted([self.node_id_1, self.node_id_2])) == [self.node_id_1, self.node_id_2]

        # this field does not get persisted
        self.msg_payload = channel_announcement_payload

        self.capacity_sat = None
        self.policy_node1 = None
        self.policy_node2 = None

    def to_json(self) -> dict:
        d = {}
        d['short_channel_id'] = bh2u(self.channel_id)
        d['node_id_1'] = bh2u(self.node_id_1)
        d['node_id_2'] = bh2u(self.node_id_2)
        d['policy_node1'] = self.policy_node1
        d['policy_node2'] = self.policy_node2
        d['capacity_sat'] = self.capacity_sat
        return d

    @classmethod
    def from_json(cls, d: dict):
        d2 = {}
        d2['short_channel_id'] = bfh(d['short_channel_id'])
        d2['node_id_1'] = bfh(d['node_id_1'])
        d2['node_id_2'] = bfh(d['node_id_2'])
        ci = ChannelInfo(d2)
        ci.capacity_sat = d['capacity_sat']
        ci.policy_node1 = ChannelInfoDirectedPolicy.from_json(d['policy_node1'])
        ci.policy_node2 = ChannelInfoDirectedPolicy.from_json(d['policy_node2'])
        return ci

    def set_capacity(self, capacity):
        self.capacity_sat = capacity

    def on_channel_update(self, msg_payload):
        assert self.channel_id == msg_payload['short_channel_id']
        flags = int.from_bytes(msg_payload['flags'], 'big')
        direction = flags & 1
        # TODO compare timestamps if already have a channel update for the direction
        if direction == 0:
            self.policy_node1 = ChannelInfoDirectedPolicy(msg_payload)
        else:
            self.policy_node2 = ChannelInfoDirectedPolicy(msg_payload)
        #self.print_error('channel update', binascii.hexlify(self.channel_id).decode("ascii"), flags)

    def get_policy_for_node(self, node_id):
        if node_id == self.node_id_1:
            return self.policy_node1
        elif node_id == self.node_id_2:
            return self.policy_node2
        else:
            raise Exception('node_id {} not in channel {}'.format(node_id, self.channel_id))


class ChannelInfoDirectedPolicy:
    # TODO other fields from channel update

    def __init__(self, channel_update_payload):
        cltv_expiry_delta           = channel_update_payload['cltv_expiry_delta']
        htlc_minimum_msat           = channel_update_payload['htlc_minimum_msat']
        fee_base_msat               = channel_update_payload['fee_base_msat']
        fee_proportional_millionths = channel_update_payload['fee_proportional_millionths']
        flags                       = channel_update_payload['flags']

        self.cltv_expiry_delta           = int.from_bytes(cltv_expiry_delta, "big")
        self.htlc_minimum_msat           = int.from_bytes(htlc_minimum_msat, "big")
        self.fee_base_msat               = int.from_bytes(fee_base_msat, "big")
        self.fee_proportional_millionths = int.from_bytes(fee_proportional_millionths, "big")
        self.flags                       = int.from_bytes(flags, "big")

    def to_json(self) -> dict:
        d = {}
        d['cltv_expiry_delta'] = self.cltv_expiry_delta
        d['htlc_minimum_msat'] = self.htlc_minimum_msat
        d['fee_base_msat'] = self.fee_base_msat
        d['fee_proportional_millionths'] = self.fee_proportional_millionths
        d['flags'] = self.flags
        return d

    @classmethod
    def from_json(cls, d: dict):
        if d is None: return None
        d2 = {}
        d2['cltv_expiry_delta'] = d['cltv_expiry_delta'].to_bytes(2, "big")
        d2['htlc_minimum_msat'] = d['htlc_minimum_msat'].to_bytes(8, "big")
        d2['fee_base_msat'] = d['fee_base_msat'].to_bytes(4, "big")
        d2['fee_proportional_millionths'] = d['fee_proportional_millionths'].to_bytes(4, "big")
        d2['flags'] = d['flags'].to_bytes(2, "big")
        return ChannelInfoDirectedPolicy(d2)


class ChannelDB(JsonDB):

    def __init__(self, network):
        self.network = network

        path = os.path.join(get_headers_dir(network.config), 'channel_db')
        JsonDB.__init__(self, path)

        self.lock = threading.Lock()
        self._id_to_channel_info = {}
        self._channels_for_node = defaultdict(set)  # node -> set(short_channel_id)

        self.ca_verifier = LNChanAnnVerifier(network, self)
        self.network.add_jobs([self.ca_verifier])

        self.load_data()

    def load_data(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding='utf-8') as f:
                raw = f.read()
                self.data = json.loads(raw)
        channel_infos = self.get('channel_infos', {})
        for short_channel_id, channel_info_d in channel_infos.items():
            channel_info = ChannelInfo.from_json(channel_info_d)
            short_channel_id = bfh(short_channel_id)
            self.add_verified_channel_info(short_channel_id, channel_info)

    def save_data(self):
        with self.lock:
            channel_infos = {}
            for short_channel_id, channel_info in self._id_to_channel_info.items():
                channel_infos[bh2u(short_channel_id)] = channel_info
            self.put('channel_infos', channel_infos)
        self.write()

    def __len__(self):
        return len(self._id_to_channel_info)

    def get_channel_info(self, channel_id) -> Optional[ChannelInfo]:
        return self._id_to_channel_info.get(channel_id, None)

    def get_channels_for_node(self, node_id):
        """Returns the set of channels that have node_id as one of the endpoints."""
        return self._channels_for_node[node_id]

    def add_verified_channel_info(self, short_channel_id: bytes, channel_info: ChannelInfo):
        with self.lock:
            self._id_to_channel_info[short_channel_id] = channel_info
            self._channels_for_node[channel_info.node_id_1].add(short_channel_id)
            self._channels_for_node[channel_info.node_id_2].add(short_channel_id)

    def on_channel_announcement(self, msg_payload):
        short_channel_id = msg_payload['short_channel_id']
        if short_channel_id in self._id_to_channel_info:
            return
        if constants.net.rev_genesis_bytes() != msg_payload['chain_hash']:
            return
        channel_info = ChannelInfo(msg_payload)
        self.ca_verifier.add_new_channel_info(channel_info)

    def on_channel_update(self, msg_payload):
        short_channel_id = msg_payload['short_channel_id']
        if constants.net.rev_genesis_bytes() != msg_payload['chain_hash']:
            return
        # try finding channel in verified db
        channel_info = self._id_to_channel_info.get(short_channel_id, None)
        if channel_info is None:
            # try finding channel in pending db
            channel_info = self.ca_verifier.get_pending_channel_info(short_channel_id)
        if channel_info is None:
            # try finding channel in verified db, again
            # (maybe this is redundant but this should prevent a race..)
            channel_info = self._id_to_channel_info.get(short_channel_id, None)
        if channel_info is None:
            self.print_error("could not find", short_channel_id)
            return
        channel_info.on_channel_update(msg_payload)

    def remove_channel(self, short_channel_id):
        try:
            channel_info = self._id_to_channel_info[short_channel_id]
        except KeyError:
            self.print_error('cannot find channel {}'.format(short_channel_id))
            return
        self._id_to_channel_info.pop(short_channel_id, None)
        for node in (channel_info.node_id_1, channel_info.node_id_2):
            try:
                self._channels_for_node[node].remove(short_channel_id)
            except KeyError:
                pass

    def print_graph(self, full_ids=False):
        # used for debugging.
        # FIXME there is a race here - iterables could change size from another thread
        def other_node_id(node_id, channel_id):
            channel_info = self._id_to_channel_info[channel_id]
            if node_id == channel_info.node_id_1:
                other = channel_info.node_id_2
            else:
                other = channel_info.node_id_1
            return other if full_ids else other[-4:]

        self.print_msg('node: {(channel, other_node), ...}')
        for node_id, short_channel_ids in list(self._channels_for_node.items()):
            short_channel_ids = {(bh2u(cid), bh2u(other_node_id(node_id, cid)))
                                 for cid in short_channel_ids}
            node_id = bh2u(node_id) if full_ids else bh2u(node_id[-4:])
            self.print_msg('{}: {}'.format(node_id, short_channel_ids))

        self.print_msg('channel: node1, node2, direction')
        for short_channel_id, channel_info in list(self._id_to_channel_info.items()):
            node1 = channel_info.node_id_1
            node2 = channel_info.node_id_2
            direction1 = channel_info.get_policy_for_node(node1) is not None
            direction2 = channel_info.get_policy_for_node(node2) is not None
            if direction1 and direction2:
                direction = 'both'
            elif direction1:
                direction = 'forward'
            elif direction2:
                direction = 'backward'
            else:
                direction = 'none'
            self.print_msg('{}: {}, {}, {}'
                           .format(bh2u(short_channel_id),
                                   bh2u(node1) if full_ids else bh2u(node1[-4:]),
                                   bh2u(node2) if full_ids else bh2u(node2[-4:]),
                                   direction))


class RouteEdge:

    def __init__(self, node_id: bytes, short_channel_id: bytes,
                 channel_policy: ChannelInfoDirectedPolicy):
        # "if you travel through short_channel_id, you will reach node_id"
        self.node_id = node_id
        self.short_channel_id = short_channel_id
        self.channel_policy = channel_policy


class LNPathFinder(PrintError):

    def __init__(self, channel_db):
        self.channel_db = channel_db
        self.blacklist = set()

    def _edge_cost(self, short_channel_id: bytes, start_node: bytes, payment_amt_msat: int,
                   ignore_cltv=False) -> float:
        """Heuristic cost of going through a channel.
        direction: 0 or 1. --- 0 means node_id_1 -> node_id_2
        """
        channel_info = self.channel_db.get_channel_info(short_channel_id)
        if channel_info is None:
            return float('inf')

        channel_policy = channel_info.get_policy_for_node(start_node)
        if channel_policy is None: return float('inf')
        cltv_expiry_delta           = channel_policy.cltv_expiry_delta
        htlc_minimum_msat           = channel_policy.htlc_minimum_msat
        fee_base_msat               = channel_policy.fee_base_msat
        fee_proportional_millionths = channel_policy.fee_proportional_millionths
        if payment_amt_msat is not None:
            if payment_amt_msat < htlc_minimum_msat:
                return float('inf')  # payment amount too little
            if channel_info.capacity_sat is not None and \
                    payment_amt_msat // 1000 > channel_info.capacity_sat:
                return float('inf')  # payment amount too large
        amt = payment_amt_msat or 50000 * 1000  # guess for typical payment amount
        fee_msat = fee_base_msat + amt * fee_proportional_millionths / 1000000
        # TODO revise
        # paying 10 more satoshis ~ waiting one more block
        fee_cost = fee_msat / 1000 / 10
        cltv_cost = cltv_expiry_delta if not ignore_cltv else 0
        return cltv_cost + fee_cost + 1

    @profiler
    def find_path_for_payment(self, from_node_id: bytes, to_node_id: bytes,
                              amount_msat: int=None) -> Sequence[Tuple[bytes, bytes]]:
        """Return a path between from_node_id and to_node_id.

        Returns a list of (node_id, short_channel_id) representing a path.
        To get from node ret[n][0] to ret[n+1][0], use channel ret[n+1][1];
        i.e. an element reads as, "to get to node_id, travel through short_channel_id"
        """
        if amount_msat is not None: assert type(amount_msat) is int
        # TODO find multiple paths??

        # run Dijkstra
        distance_from_start = defaultdict(lambda: float('inf'))
        distance_from_start[from_node_id] = 0
        prev_node = {}
        nodes_to_explore = queue.PriorityQueue()
        nodes_to_explore.put((0, from_node_id))

        while nodes_to_explore.qsize() > 0:
            dist_to_cur_node, cur_node = nodes_to_explore.get()
            if cur_node == to_node_id:
                break
            if dist_to_cur_node != distance_from_start[cur_node]:
                # queue.PriorityQueue does not implement decrease_priority,
                # so instead of decreasing priorities, we add items again into the queue.
                # so there are duplicates in the queue, that we discard now:
                continue
            for edge_channel_id in self.channel_db.get_channels_for_node(cur_node):
                if edge_channel_id in self.blacklist: continue
                channel_info = self.channel_db.get_channel_info(edge_channel_id)
                node1, node2 = channel_info.node_id_1, channel_info.node_id_2
                neighbour = node2 if node1 == cur_node else node1
                ignore_cltv_delta_in_edge_cost = cur_node == from_node_id
                edge_cost = self._edge_cost(edge_channel_id, cur_node, amount_msat,
                                            ignore_cltv=ignore_cltv_delta_in_edge_cost)
                alt_dist_to_neighbour = distance_from_start[cur_node] + edge_cost
                if alt_dist_to_neighbour < distance_from_start[neighbour]:
                    distance_from_start[neighbour] = alt_dist_to_neighbour
                    prev_node[neighbour] = cur_node, edge_channel_id
                    nodes_to_explore.put((alt_dist_to_neighbour, neighbour))
        else:
            return None  # no path found

        # backtrack from end to start
        cur_node = to_node_id
        path = []
        while cur_node != from_node_id:
            prev_node_id, edge_taken = prev_node[cur_node]
            path += [(cur_node, edge_taken)]
            cur_node = prev_node_id
        path.reverse()
        return path

    def create_route_from_path(self, path, from_node_id: bytes) -> Sequence[RouteEdge]:
        assert type(from_node_id) is bytes
        if path is None:
            raise Exception('cannot create route from None path')
        route = []
        prev_node_id = from_node_id
        for node_id, short_channel_id in path:
            channel_info = self.channel_db.get_channel_info(short_channel_id)
            if channel_info is None:
                raise Exception('cannot find channel info for short_channel_id: {}'.format(bh2u(short_channel_id)))
            channel_policy = channel_info.get_policy_for_node(prev_node_id)
            if channel_policy is None:
                raise Exception('cannot find channel policy for short_channel_id: {}'.format(bh2u(short_channel_id)))
            route.append(RouteEdge(node_id, short_channel_id, channel_policy))
            prev_node_id = node_id
        return route


# bolt 04, "onion"  ----->

NUM_MAX_HOPS_IN_PATH = 20
HOPS_DATA_SIZE = 1300      # also sometimes called routingInfoSize in bolt-04
PER_HOP_FULL_SIZE = 65     # HOPS_DATA_SIZE / 20
NUM_STREAM_BYTES = HOPS_DATA_SIZE + PER_HOP_FULL_SIZE
PER_HOP_HMAC_SIZE = 32


class UnsupportedOnionPacketVersion(Exception): pass
class InvalidOnionMac(Exception): pass


class OnionPerHop:

    def __init__(self, short_channel_id: bytes, amt_to_forward: bytes, outgoing_cltv_value: bytes):
        self.short_channel_id = short_channel_id
        self.amt_to_forward = amt_to_forward
        self.outgoing_cltv_value = outgoing_cltv_value

    def to_bytes(self) -> bytes:
        ret = self.short_channel_id
        ret += self.amt_to_forward
        ret += self.outgoing_cltv_value
        ret += bytes(12)  # padding
        if len(ret) != 32:
            raise Exception('unexpected length {}'.format(len(ret)))
        return ret

    @classmethod
    def from_bytes(cls, b: bytes):
        if len(b) != 32:
            raise Exception('unexpected length {}'.format(len(b)))
        return OnionPerHop(
            short_channel_id=b[:8],
            amt_to_forward=b[8:16],
            outgoing_cltv_value=b[16:20]
        )


class OnionHopsDataSingle:  # called HopData in lnd

    def __init__(self, per_hop: OnionPerHop = None):
        self.realm = 0
        self.per_hop = per_hop
        self.hmac = None

    def to_bytes(self) -> bytes:
        ret = bytes([self.realm])
        ret += self.per_hop.to_bytes()
        ret += self.hmac if self.hmac is not None else bytes(PER_HOP_HMAC_SIZE)
        if len(ret) != PER_HOP_FULL_SIZE:
            raise Exception('unexpected length {}'.format(len(ret)))
        return ret

    @classmethod
    def from_bytes(cls, b: bytes):
        if len(b) != PER_HOP_FULL_SIZE:
            raise Exception('unexpected length {}'.format(len(b)))
        ret = OnionHopsDataSingle()
        ret.realm = b[0]
        if ret.realm != 0:
            raise Exception('only realm 0 is supported')
        ret.per_hop = OnionPerHop.from_bytes(b[1:33])
        ret.hmac = b[33:]
        return ret


class OnionPacket:

    def __init__(self, public_key: bytes, hops_data: bytes, hmac: bytes):
        self.version = 0
        self.public_key = public_key
        self.hops_data = hops_data  # also called RoutingInfo in bolt-04
        self.hmac = hmac

    def to_bytes(self) -> bytes:
        ret = bytes([self.version])
        ret += self.public_key
        ret += self.hops_data
        ret += self.hmac
        if len(ret) != 1366:
            raise Exception('unexpected length {}'.format(len(ret)))
        return ret

    @classmethod
    def from_bytes(cls, b: bytes):
        if len(b) != 1366:
            raise Exception('unexpected length {}'.format(len(b)))
        version = b[0]
        if version != 0:
            raise UnsupportedOnionPacketVersion('version {} is not supported'.format(version))
        return OnionPacket(
            public_key=b[1:34],
            hops_data=b[34:1334],
            hmac=b[1334:]
        )


def get_bolt04_onion_key(key_type: bytes, secret: bytes) -> bytes:
    if key_type not in (b'rho', b'mu', b'um', b'ammag'):
        raise Exception('invalid key_type {}'.format(key_type))
    key = hmac.new(key_type, msg=secret, digestmod=hashlib.sha256).digest()
    return key


def get_shared_secrets_along_route(payment_path_pubkeys: Sequence[bytes],
                                   session_key: bytes) -> Sequence[bytes]:
    num_hops = len(payment_path_pubkeys)
    hop_shared_secrets = num_hops * [b'']
    ephemeral_key = session_key
    # compute shared key for each hop
    for i in range(0, num_hops):
        hop_shared_secrets[i] = get_ecdh(ephemeral_key, payment_path_pubkeys[i])
        ephemeral_pubkey = ecc.ECPrivkey(ephemeral_key).get_public_key_bytes()
        blinding_factor = sha256(ephemeral_pubkey + hop_shared_secrets[i])
        blinding_factor_int = int.from_bytes(blinding_factor, byteorder="big")
        ephemeral_key_int = int.from_bytes(ephemeral_key, byteorder="big")
        ephemeral_key_int = ephemeral_key_int * blinding_factor_int % ecc.CURVE_ORDER
        ephemeral_key = ephemeral_key_int.to_bytes(32, byteorder="big")
    return hop_shared_secrets


def new_onion_packet(payment_path_pubkeys: Sequence[bytes], session_key: bytes,
                     hops_data: Sequence[OnionHopsDataSingle], associated_data: bytes) -> OnionPacket:
    num_hops = len(payment_path_pubkeys)
    hop_shared_secrets = get_shared_secrets_along_route(payment_path_pubkeys, session_key)

    filler = generate_filler(b'rho', num_hops, PER_HOP_FULL_SIZE, hop_shared_secrets)
    mix_header = bytes(HOPS_DATA_SIZE)
    next_hmac = bytes(PER_HOP_HMAC_SIZE)

    # compute routing info and MAC for each hop
    for i in range(num_hops-1, -1, -1):
        rho_key = get_bolt04_onion_key(b'rho', hop_shared_secrets[i])
        mu_key = get_bolt04_onion_key(b'mu', hop_shared_secrets[i])
        hops_data[i].hmac = next_hmac
        stream_bytes = generate_cipher_stream(rho_key, NUM_STREAM_BYTES)
        mix_header = mix_header[:-PER_HOP_FULL_SIZE]
        mix_header = hops_data[i].to_bytes() + mix_header
        mix_header = xor_bytes(mix_header, stream_bytes)
        if i == num_hops - 1 and len(filler) != 0:
            mix_header = mix_header[:-len(filler)] + filler
        packet = mix_header + associated_data
        next_hmac = hmac.new(mu_key, msg=packet, digestmod=hashlib.sha256).digest()

    return OnionPacket(
        public_key=ecc.ECPrivkey(session_key).get_public_key_bytes(),
        hops_data=mix_header,
        hmac=next_hmac)


def generate_filler(key_type: bytes, num_hops: int, hop_size: int,
                    shared_secrets: Sequence[bytes]) -> bytes:
    filler_size = (NUM_MAX_HOPS_IN_PATH + 1) * hop_size
    filler = bytearray(filler_size)

    for i in range(0, num_hops-1):  # -1, as last hop does not obfuscate
        filler = filler[hop_size:]
        filler += bytearray(hop_size)
        stream_key = get_bolt04_onion_key(key_type, shared_secrets[i])
        stream_bytes = generate_cipher_stream(stream_key, filler_size)
        filler = xor_bytes(filler, stream_bytes)

    return filler[(NUM_MAX_HOPS_IN_PATH-num_hops+2)*hop_size:]


def generate_cipher_stream(stream_key: bytes, num_bytes: int) -> bytes:
    algo = algorithms.ChaCha20(stream_key, nonce=bytes(16))
    cipher = Cipher(algo, mode=None, backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(bytes(num_bytes))


ProcessedOnionPacket = namedtuple("ProcessedOnionPacket", ["are_we_final", "hop_data", "next_packet"])


# TODO replay protection
def process_onion_packet(onion_packet: OnionPacket, associated_data: bytes,
                         our_onion_private_key: bytes) -> ProcessedOnionPacket:
    shared_secret = get_ecdh(our_onion_private_key, onion_packet.public_key)

    # check message integrity
    mu_key = get_bolt04_onion_key(b'mu', shared_secret)
    calculated_mac = hmac.new(mu_key, msg=onion_packet.hops_data+associated_data,
                              digestmod=hashlib.sha256).digest()
    if onion_packet.hmac != calculated_mac:
        raise InvalidOnionMac()

    # peel an onion layer off
    rho_key = get_bolt04_onion_key(b'rho', shared_secret)
    stream_bytes = generate_cipher_stream(rho_key, NUM_STREAM_BYTES)
    padded_header = onion_packet.hops_data + bytes(PER_HOP_FULL_SIZE)
    next_hops_data = xor_bytes(padded_header, stream_bytes)

    # calc next ephemeral key
    blinding_factor = sha256(onion_packet.public_key + shared_secret)
    blinding_factor_int = int.from_bytes(blinding_factor, byteorder="big")
    next_public_key_int = ecc.ECPubkey(onion_packet.public_key) * blinding_factor_int
    next_public_key = next_public_key_int.get_public_key_bytes()

    hop_data = OnionHopsDataSingle.from_bytes(next_hops_data[:PER_HOP_FULL_SIZE])
    next_onion_packet = OnionPacket(
        public_key=next_public_key,
        hops_data=next_hops_data[PER_HOP_FULL_SIZE:],
        hmac=hop_data.hmac
    )
    if hop_data.hmac == bytes(PER_HOP_HMAC_SIZE):
        # we are the destination / exit node
        are_we_final = True
    else:
        # we are an intermediate node; forwarding
        are_we_final = False
    return ProcessedOnionPacket(are_we_final, hop_data, next_onion_packet)


class FailedToDecodeOnionError(Exception): pass


class OnionRoutingFailureMessage:

    def __init__(self, code: int, data: bytes):
        self.code = code
        self.data = data

    def __repr__(self):
        return repr((self.code, self.data))


def _decode_onion_error(error_packet: bytes, payment_path_pubkeys: Sequence[bytes],
                        session_key: bytes) -> (bytes, int):
    """Returns the decoded error bytes, and the index of the sender of the error."""
    num_hops = len(payment_path_pubkeys)
    hop_shared_secrets = get_shared_secrets_along_route(payment_path_pubkeys, session_key)
    for i in range(num_hops):
        ammag_key = get_bolt04_onion_key(b'ammag', hop_shared_secrets[i])
        um_key = get_bolt04_onion_key(b'um', hop_shared_secrets[i])
        stream_bytes = generate_cipher_stream(ammag_key, len(error_packet))
        error_packet = xor_bytes(error_packet, stream_bytes)
        hmac_computed = hmac.new(um_key, msg=error_packet[32:], digestmod=hashlib.sha256).digest()
        hmac_found = error_packet[:32]
        if hmac_computed == hmac_found:
            return error_packet, i
    raise FailedToDecodeOnionError()


def decode_onion_error(error_packet: bytes, payment_path_pubkeys: Sequence[bytes],
                       session_key: bytes) -> (OnionRoutingFailureMessage, int):
    """Returns the failure message, and the index of the sender of the error."""
    decrypted_error, sender_index = _decode_onion_error(error_packet, payment_path_pubkeys, session_key)
    failure_msg = get_failure_msg_from_onion_error(decrypted_error)
    return failure_msg, sender_index


def get_failure_msg_from_onion_error(decrypted_error_packet: bytes) -> OnionRoutingFailureMessage:
    # get failure_msg bytes from error packet
    failure_len = int.from_bytes(decrypted_error_packet[32:34], byteorder='big')
    failure_msg = decrypted_error_packet[34:34+failure_len]
    # create failure message object
    failure_code = int.from_bytes(failure_msg[:2], byteorder='big')
    failure_data = failure_msg[2:]
    return OnionRoutingFailureMessage(failure_code, failure_data)




# <----- bolt 04, "onion"


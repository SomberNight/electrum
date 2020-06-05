#!/usr/bin/env python3

import sys
import asyncio

from electrum import keystore, bitcoin
from electrum.util import create_and_start_event_loop, log_exceptions
from electrum.simple_config import SimpleConfig
from electrum.network import Network


try:
    mnemonic = sys.argv[1]
except Exception:
    print("usage: bip39_recovery <mnemonic>")
    sys.exit(1)

loop, stopping_fut, loop_thread = create_and_start_event_loop()

config = SimpleConfig()
network = Network(config)
network.start()

async def account_discovery(mnemonic):
    derivation_path = "m/84'/0'/0'"
    gap_limit = 20

    node = keystore.from_bip39_seed(mnemonic, "", derivation_path)
    pubkey = node.derive_pubkey(0, 0).hex()
    scripthash = pubkey_to_scripthash(pubkey, "p2wpkh")
    history = await network.get_history_for_scripthash(scripthash)
    has_history = len(history) > 0

    print("pubkey       ", pubkey)
    print("has_history  ", has_history)

def pubkey_to_scripthash(pubkey, script_type):
    address = bitcoin.pubkey_to_address(script_type, pubkey)
    script = bitcoin.address_to_script(address)
    scripthash = bitcoin.script_to_scripthash(script)
    return scripthash

@log_exceptions
async def f():
    try:
        await account_discovery(mnemonic)
    finally:
        stopping_fut.set_result(1)

asyncio.run_coroutine_threadsafe(f(), loop)

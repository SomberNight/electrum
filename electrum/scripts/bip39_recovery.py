#!/usr/bin/env python3

import sys
import asyncio

from electrum import keystore, bitcoin
from electrum.util import create_and_start_event_loop, log_exceptions
from electrum.simple_config import SimpleConfig
from electrum.network import Network

WALLET_FORMATS = [
    {
        "description": "Standard legacy (BIP44) path",
        "derivation_path": "m/44'/0'/0'",
        "script_type": "p2pkh",
    },
    {
        "description": "Standard p2sh segwit (BIP49) path",
        "derivation_path": "m/49'/0'/0'",
        "script_type": "p2wpkh-p2sh",
    },
    {
        "description": "Standard native segwit (BIP84) path",
        "derivation_path": "m/84'/0'/0'",
        "script_type": "p2wpkh",
    },
]

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
    active_accounts = []
    for account in WALLET_FORMATS:
        node = keystore.from_bip39_seed(mnemonic, "", account["derivation_path"])
        has_history = await account_has_history(node, account["script_type"]);
        if has_history:
            active_accounts.append(account)
    return active_accounts

async def account_has_history(node, script_type):
    gap_limit = 20
    for index in range(gap_limit):
        pubkey = node.derive_pubkey(0, index).hex()
        scripthash = pubkey_to_scripthash(pubkey, script_type)
        history = await network.get_history_for_scripthash(scripthash)
        if len(history) > 0:
            return True
    return False

def pubkey_to_scripthash(pubkey, script_type):
    address = bitcoin.pubkey_to_address(script_type, pubkey)
    script = bitcoin.address_to_script(address)
    scripthash = bitcoin.script_to_scripthash(script)
    return scripthash

@log_exceptions
async def f():
    try:
        active_accounts = await account_discovery(mnemonic)
        print(f"Found {len(active_accounts)} active accounts")
        for account in active_accounts:
            print(
                account["description"],
                account["derivation_path"],
                account["script_type"],
            )
    finally:
        stopping_fut.set_result(1)

asyncio.run_coroutine_threadsafe(f(), loop)

#!/usr/bin/env python3

import sys
import asyncio

from electrum import keystore, bitcoin
from electrum.bip32 import BIP32Node
from electrum.util import json_encode, print_msg, create_and_start_event_loop, log_exceptions
from electrum.simple_config import SimpleConfig
from electrum.network import Network

try:
    mnemonic = sys.argv[1]
    passphrase = sys.argv[2] if len(sys.argv) > 2 else ""
except Exception:
    print("usage: bip39_recovery <mnemonic> [<passphrase>]")
    sys.exit(1)

loop, stopping_fut, loop_thread = create_and_start_event_loop()

config = SimpleConfig()
network = Network(config)
network.start()

@log_exceptions
async def f():
    try:
        active_accounts = await account_discovery(mnemonic, passphrase)
        print_msg(json_encode(active_accounts))
    finally:
        stopping_fut.set_result(1)

asyncio.run_coroutine_threadsafe(f(), loop)

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

async def account_discovery(mnemonic, passphrase=""):
    k = keystore.from_bip39_seed(mnemonic, passphrase, "m")
    root_node = BIP32Node.from_xkey(k.xprv)
    active_accounts = []
    for account in WALLET_FORMATS:
        has_history = await account_has_history(root_node, account["derivation_path"], account["script_type"]);
        if has_history:
            active_accounts.append(account)
    return active_accounts

async def account_has_history(root_node, derivation_path, script_type):
    account_node = root_node.subkey_at_private_derivation(derivation_path)
    account_keystore = keystore.from_xprv(account_node.to_xprv())
    gap_limit = 20
    for address_index in range(gap_limit):
        scripthash = derive_scripthash(account_keystore, address_index, script_type)
        history = await network.get_history_for_scripthash(scripthash)
        if len(history) > 0:
            return True
    return False

def derive_scripthash(k, index, script_type):
    pubkey = k.derive_pubkey(0, index).hex()
    address = bitcoin.pubkey_to_address(script_type, pubkey)
    script = bitcoin.address_to_script(address)
    scripthash = bitcoin.script_to_scripthash(script)
    return scripthash

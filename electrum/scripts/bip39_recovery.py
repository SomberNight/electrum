#!/usr/bin/env python3

import sys
import asyncio

from electrum import keystore, bitcoin
from electrum.bip32 import BIP32Node, convert_bip32_path_to_list_of_uint32, convert_bip32_intpath_to_strpath
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
        "description": "Standard legacy",
        "derivation_path": "m/44'/0'/0'",
        "script_type": "p2pkh",
        "iterate_accounts": True,
    },
    {
        "description": "Standard compatibility segwit",
        "derivation_path": "m/49'/0'/0'",
        "script_type": "p2wpkh-p2sh",
        "iterate_accounts": True,
    },
    {
        "description": "Standard native segwit",
        "derivation_path": "m/84'/0'/0'",
        "script_type": "p2wpkh",
        "iterate_accounts": True,
    },
]

async def account_discovery(mnemonic, passphrase=""):
    k = keystore.from_bip39_seed(mnemonic, passphrase, "m")
    root_node = BIP32Node.from_xkey(k.xprv)
    active_accounts = []
    for wallet_format in WALLET_FORMATS:
        account_path = wallet_format["derivation_path"]
        while True:
            has_history = await account_has_history(root_node, account_path, wallet_format["script_type"]);
            if not has_history:
                break
            description = wallet_format["description"]
            if wallet_format["iterate_accounts"]:
                account_index = account_path.split("/")[-1].replace("'", "")
                description = f'{description} (Account {account_index})'
            active_accounts.append({
                "description": description,
                "derivation_path": account_path,
                "script_type": wallet_format["script_type"],
            })
            if not wallet_format["iterate_accounts"]:
                break
            try:
                account_path = increment_bip32_path(account_path)
            except:
                # Stop looping if we go out of range
                break
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

def increment_bip32_path(path):
    ints = convert_bip32_path_to_list_of_uint32(path)
    ints[-1] = ints[-1] + 1
    return convert_bip32_intpath_to_strpath(ints)

#!/usr/bin/env python3

import sys
import asyncio

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

from electrum import bitcoin
from electrum.keystore import bip39_to_seed
from electrum.bip32 import BIP32Node, convert_bip32_path_to_list_of_uint32, convert_bip32_intpath_to_strpath

WALLET_FORMATS = [
    {
        "description": "Standard BIP44 legacy",
        "derivation_path": "m/44'/0'/0'",
        "script_type": "p2pkh",
        "iterate_accounts": True,
    },
    {
        "description": "Standard BIP49 compatibility segwit",
        "derivation_path": "m/49'/0'/0'",
        "script_type": "p2wpkh-p2sh",
        "iterate_accounts": True,
    },
    {
        "description": "Standard BIP84 native segwit",
        "derivation_path": "m/84'/0'/0'",
        "script_type": "p2wpkh",
        "iterate_accounts": True,
    },
    {
        "description": "Non-standard legacy",
        "derivation_path": "m/0'",
        "script_type": "p2pkh",
        "iterate_accounts": True,
    },
    {
        "description": "Non-standard compatibility segwit",
        "derivation_path": "m/0'",
        "script_type": "p2wpkh-p2sh",
        "iterate_accounts": True,
    },
    {
        "description": "Non-standard native segwit",
        "derivation_path": "m/0'",
        "script_type": "p2wpkh",
        "iterate_accounts": True,
    },
    {
        "description": "Samourai Whirlpool post-mix",
        "derivation_path": "m/84'/0'/2147483646'",
        "script_type": "p2wpkh",
        "iterate_accounts": False,
    },
]

async def account_discovery(mnemonic, passphrase=""):
    seed = bip39_to_seed(mnemonic, passphrase)
    root_node = BIP32Node.from_rootseed(seed, xtype="standard")
    active_accounts = []
    for wallet_format in WALLET_FORMATS:
        account_path = wallet_format["derivation_path"]
        while True:
            account_node = root_node.subkey_at_private_derivation(account_path)
            has_history = await account_has_history(account_node, wallet_format["script_type"]);
            if has_history:
                description = wallet_format["description"]
                if wallet_format["iterate_accounts"]:
                    account_index = account_path.split("/")[-1].replace("'", "")
                    description = f'{description} (Account {account_index})'
                active_accounts.append({
                    "description": description,
                    "derivation_path": account_path,
                    "script_type": wallet_format["script_type"],
                })
            if not has_history or not wallet_format["iterate_accounts"]:
                break
            account_path = increment_bip32_path(account_path)
    return active_accounts

async def account_has_history(account_node, script_type):
    gap_limit = 20
    for address_index in range(gap_limit):
        address_node = account_node.subkey_at_public_derivation("0/" + str(address_index))
        pubkey = address_node.eckey.get_public_key_hex()
        address = bitcoin.pubkey_to_address(script_type, pubkey)
        script = bitcoin.address_to_script(address)
        scripthash = bitcoin.script_to_scripthash(script)
        history = await network.get_history_for_scripthash(scripthash)
        if len(history) > 0:
            return True
    return False

def increment_bip32_path(path):
    ints = convert_bip32_path_to_list_of_uint32(path)
    ints[-1] = ints[-1] + 1
    return convert_bip32_intpath_to_strpath(ints)

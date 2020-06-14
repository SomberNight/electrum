# Copyright (C) 2020 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php

from . import bitcoin
from .keystore import bip39_to_seed
from .bip32 import BIP32_PRIME, BIP32Node
from .bip32 import convert_bip32_path_to_list_of_uint32 as bip32_str_to_ints
from .bip32 import convert_bip32_intpath_to_strpath as bip32_ints_to_str

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

async def account_discovery(network, mnemonic, passphrase=""):
    seed = bip39_to_seed(mnemonic, passphrase)
    root_node = BIP32Node.from_rootseed(seed, xtype="standard")
    active_accounts = []
    for wallet_format in WALLET_FORMATS:
        account_path = bip32_str_to_ints(wallet_format["derivation_path"])
        while True:
            account_node = root_node.subkey_at_private_derivation(account_path)
            has_history = await account_has_history(network, account_node, wallet_format["script_type"]);
            if has_history:
                account = format_account(wallet_format, account_path)
                active_accounts.append(account)
            if not has_history or not wallet_format["iterate_accounts"]:
                break
            account_path[-1] = account_path[-1] + 1
    return active_accounts

async def account_has_history(network, account_node, script_type):
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

def format_account(wallet_format, account_path):
    description = wallet_format["description"]
    if wallet_format["iterate_accounts"]:
        account_index = account_path[-1] % BIP32_PRIME
        description = f'{description} (Account {account_index})'
    return {
        "description": description,
        "derivation_path": bip32_ints_to_str(account_path),
        "script_type": wallet_format["script_type"],
    }

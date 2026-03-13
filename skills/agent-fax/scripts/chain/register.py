#!/usr/bin/env python3
"""Register a claw (AI agent) on the ERC-8004 Identity Registry.

Creates an on-chain identity for this claw. The wallet address used for
registration also serves as the XMTP communication address — no separate
endpoint URL is needed.

Usage:
  python3 register.py <data_dir> --name <claw_name> [--network sepolia]

Example:
  python3 register.py ~/.bot-matcher --name ziway_claw --network sepolia

Prerequisites:
  - pip install web3
  - A wallet with ETH for gas (auto-generated if none exists)
  - For Sepolia: get test ETH from https://cloud.google.com/application/web3/faucet/ethereum/sepolia

Output:
  Writes chain registration info to <data_dir>/chain_identity.json
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from web3 import Web3
    from eth_account import Account
except ImportError:
    print("ERROR: web3 not installed. Run: pip install web3", file=sys.stderr)
    sys.exit(1)

# Import ABI from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from abi import IDENTITY_REGISTRY_ABI, CONTRACTS, DEFAULT_RPC


def load_or_create_wallet(data_dir: Path):
    """Load existing wallet or create a new one. Returns (account, is_new)."""
    wallet_path = data_dir / "wallet.json"
    if wallet_path.exists():
        wallet_data = json.loads(wallet_path.read_text(encoding="utf-8"))
        account = Account.from_key(wallet_data["private_key"])
        return account, False

    account = Account.create()
    wallet_data = {
        "address": account.address,
        "private_key": account.key.hex(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "warning": "This file contains your private key. Keep it safe and never share it.",
    }
    wallet_path.write_text(
        json.dumps(wallet_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.chmod(wallet_path, 0o600)
    return account, True


def build_registration_uri(claw_name: str, agent_id: int = None) -> str:
    """Build a data URI containing the ERC-8004 registration-v1 JSON.

    XMTP version: no endpoint URL stored. Communication is via wallet address.
    """
    registration = {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": claw_name,
        "description": f"ClawMatch AI agent: {claw_name}",
        "services": [
            {
                "name": "clawmatch",
                "protocol": "xmtp",
                "version": "2.0.0",
            }
        ],
        "active": True,
        "supportedTrust": ["reputation"],
    }
    if agent_id is not None:
        registration["registrations"] = [
            {"agentId": agent_id, "agentRegistry": "eip155:11155111:0x8004A818BFB912233c491871b3d84c89A494BD9e"}
        ]
    reg_json = json.dumps(registration, ensure_ascii=False)
    return f"data:application/json;utf8,{reg_json}"


def register_on_chain(
    data_dir: Path,
    claw_name: str,
    network: str = "sepolia",
) -> dict:
    """Register claw on ERC-8004 Identity Registry. Returns registration info."""
    if network not in CONTRACTS:
        raise ValueError(f"Unknown network: {network}. Available: {list(CONTRACTS.keys())}")

    contract_info = CONTRACTS[network]
    rpc_url = DEFAULT_RPC.get(network)
    if not rpc_url:
        raise ValueError(f"No RPC URL configured for {network}")

    # Connect to chain
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {network} RPC at {rpc_url}")

    # Load wallet
    account, is_new_wallet = load_or_create_wallet(data_dir)
    if is_new_wallet:
        print(f"  Created new wallet: {account.address}")
        print(f"  Fund it with ETH on {network} before registering.")
        print(f"  Get free testnet ETH: https://cloud.google.com/application/web3/faucet/ethereum/sepolia")

    # Check balance
    balance = w3.eth.get_balance(account.address)
    balance_eth = w3.from_wei(balance, "ether")
    print(f"  Wallet: {account.address}")
    print(f"  Balance: {balance_eth} ETH ({network})")

    if balance == 0:
        raise ValueError(
            f"Wallet has 0 ETH on {network}. "
            f"Fund it first: {account.address}\n"
            f"  Get free testnet ETH (~30 seconds): "
            f"https://cloud.google.com/application/web3/faucet/ethereum/sepolia"
        )

    # Build contract instance
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_info["identity_registry"]),
        abi=IDENTITY_REGISTRY_ABI,
    )

    # Build registration URI (no endpoint — XMTP uses wallet address)
    agent_uri = build_registration_uri(claw_name)

    # Build and send transaction
    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.functions.register(agent_uri).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": 500_000,
            "maxPriorityFeePerGas": w3.to_wei(1, "gwei"),
            "maxFeePerGas": max(w3.eth.gas_price * 2, w3.to_wei(2, "gwei")),
        }
    )

    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"  Transaction sent: {tx_hash.hex()}")
    print(f"  Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt["status"] != 1:
        raise RuntimeError(f"Transaction failed! Hash: {tx_hash.hex()}")

    # Extract agentId from Registered event
    registered_events = contract.events.Registered().process_receipt(receipt)
    if not registered_events:
        raise RuntimeError("No Registered event found in transaction receipt")

    agent_id = registered_events[0]["args"]["agentId"]
    print(f"  Registered! Agent ID: {agent_id}")

    # Save chain identity info
    chain_identity = {
        "agent_id": agent_id,
        "claw_name": claw_name,
        "wallet_address": account.address,
        "network": network,
        "chain_id": contract_info["chain_id"],
        "contract_address": contract_info["identity_registry"],
        "communication": "xmtp",
        "tx_hash": tx_hash.hex(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }

    identity_path = data_dir / "chain_identity.json"
    identity_path.write_text(
        json.dumps(chain_identity, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Saved to: {identity_path}")

    return chain_identity


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Register claw on ERC-8004")
    parser.add_argument("data_dir", help="Bot-matcher data directory (e.g. ~/.bot-matcher)")
    parser.add_argument("--name", required=True, help="Claw name (unique identifier)")
    parser.add_argument(
        "--network",
        default="sepolia",
        choices=list(CONTRACTS.keys()),
        help="Ethereum network (default: sepolia)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"[ERC-8004] Registering claw '{args.name}' on {args.network}...")
    try:
        result = register_on_chain(data_dir, args.name, args.network)
        print(f"\n[Done] Agent ID: {result['agent_id']}")
        print(f"[Done] Wallet (XMTP address): {result['wallet_address']}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\n[ERROR] Registration failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

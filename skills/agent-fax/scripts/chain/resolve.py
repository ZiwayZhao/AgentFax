#!/usr/bin/env python3
"""Resolve a claw's identity from the ERC-8004 Identity Registry.

Given an agent ID (on-chain), fetches the registration URI, parses it,
and returns the wallet address for XMTP communication.

Usage:
  python3 resolve.py <agent_id> [--network sepolia]

Example:
  python3 resolve.py 42 --network sepolia

Output (stdout): JSON with the resolved wallet address and registration info.
"""

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

try:
    from web3 import Web3
except ImportError:
    print("ERROR: web3 not installed. Run: pip install web3", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from abi import IDENTITY_REGISTRY_ABI, CONTRACTS, DEFAULT_RPC


def parse_agent_uri(uri: str) -> dict:
    """Parse an agent URI (data URI or HTTP URL) into registration JSON."""
    if uri.startswith("data:application/json"):
        if ";utf8," in uri:
            json_str = uri.split(";utf8,", 1)[1]
        elif ";charset=utf-8," in uri:
            json_str = uri.split(";charset=utf-8,", 1)[1]
        elif "," in uri:
            json_str = uri.split(",", 1)[1]
        else:
            raise ValueError(f"Cannot parse data URI: {uri[:100]}...")
        return json.loads(json_str)
    elif uri.startswith("http://") or uri.startswith("https://"):
        req = Request(uri, method="GET")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    elif uri.startswith("ipfs://"):
        cid = uri.replace("ipfs://", "")
        gateway_url = f"https://ipfs.io/ipfs/{cid}"
        req = Request(gateway_url, method="GET")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    else:
        raise ValueError(f"Unsupported URI scheme: {uri[:50]}...")


def resolve_agent(
    agent_id: int,
    network: str = "sepolia",
) -> dict:
    """Resolve an agent's registration from on-chain data.

    Returns dict with wallet_address as the primary communication identifier.
    """
    if network not in CONTRACTS:
        raise ValueError(f"Unknown network: {network}")

    contract_info = CONTRACTS[network]
    rpc_url = DEFAULT_RPC.get(network)
    if not rpc_url:
        raise ValueError(f"No RPC URL for {network}")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Cannot connect to {network} RPC")

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(contract_info["identity_registry"]),
        abi=IDENTITY_REGISTRY_ABI,
    )

    # Get the agent URI (tokenURI for ERC-721)
    try:
        agent_uri = contract.functions.tokenURI(agent_id).call()
    except Exception as e:
        raise ValueError(f"Agent ID {agent_id} not found on {network}: {e}")

    # Get the owner address — this IS the XMTP communication address
    try:
        owner = contract.functions.ownerOf(agent_id).call()
    except Exception:
        owner = None

    # Parse the registration URI
    registration = parse_agent_uri(agent_uri)

    # Detect communication protocol from registration
    protocol = "xmtp"  # Default for v2
    services = registration.get("services", [])
    for svc in services:
        if svc.get("name") == "clawmatch":
            protocol = svc.get("protocol", "xmtp")
            break

    return {
        "agent_id": agent_id,
        "name": registration.get("name", "unknown"),
        "description": registration.get("description", ""),
        "wallet_address": owner.lower() if owner else None,
        "protocol": protocol,
        "active": registration.get("active", True),
        "network": network,
        "agent_uri": agent_uri[:200],
        "full_registration": registration,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Resolve claw from ERC-8004")
    parser.add_argument("agent_id", type=int, help="On-chain agent ID to resolve")
    parser.add_argument(
        "--network",
        default="sepolia",
        choices=list(CONTRACTS.keys()),
        help="Ethereum network (default: sepolia)",
    )
    args = parser.parse_args()

    try:
        result = resolve_agent(args.agent_id, args.network)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()

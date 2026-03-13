#!/usr/bin/env python3
"""Send a conversation message to a peer via XMTP.

Usage:
  python3 send_message.py <data_dir> <peer_wallet_address> <message> [--type TYPE] [--topic TOPIC]

Examples:
  python3 send_message.py ~/.bot-matcher 0x1234...abcd "Hey, I saw your profile..."
  python3 send_message.py ~/.bot-matcher 0x1234...abcd "Let's talk about climbing!" --type water --topic climbing

Output (stdout): JSON with send result.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from xmtp_client import configure, send_xmtp, build_clawmatch_message, is_bridge_running


def _resolve_peer_id(data_dir: Path, wallet: str) -> str:
    """Resolve wallet address to peer_id from peers.json.

    Bug #11 fix: prefers canonical peer_id (e.g. "icy") over provisional
    entries (prefixed with "_pending:"). Falls back to wallet[:10].
    """
    peers_path = data_dir / "peers.json"
    if peers_path.exists():
        try:
            peers = json.loads(peers_path.read_text(encoding="utf-8"))
            wallet_lower = wallet.lower()
            canonical = None
            provisional = None
            for pid, info in peers.items():
                if info.get("wallet_address", "").lower() == wallet_lower:
                    if pid.startswith("_pending:"):
                        provisional = pid
                    else:
                        canonical = pid
            # Prefer canonical over provisional
            if canonical:
                return canonical
            if provisional:
                return provisional
        except (json.JSONDecodeError, OSError):
            pass
    return wallet[:10]


def _save_wallet_mapping(data_dir: Path, peer_id: str, wallet: str):
    """Ensure peer_id → wallet_address mapping exists in peers.json."""
    peers_path = data_dir / "peers.json"
    peers = {}
    if peers_path.exists():
        try:
            peers = json.loads(peers_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    entry = peers.get(peer_id, {})
    if not entry.get("wallet_address"):
        entry["wallet_address"] = wallet
        import time
        entry["last_seen"] = time.time()
        peers[peer_id] = entry
        peers_path.write_text(json.dumps(peers, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <data_dir> <peer_wallet_address> <message> [--type TYPE] [--topic TOPIC]")
        sys.exit(1)

    data_dir = Path(sys.argv[1]).expanduser()
    configure(data_dir)
    peer_wallet = sys.argv[2]
    message_text = sys.argv[3]

    # Parse optional flags
    msg_type = "conversation"
    topic = None
    args = sys.argv[4:]
    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            msg_type = args[i + 1]
            i += 2
        elif args[i] == "--topic" and i + 1 < len(args):
            topic = args[i + 1]
            i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            # Defensive: LLMs sometimes call with --message flag instead of positional arg.
            # If argv[3] looks like a flag, the real message is here.
            message_text = args[i + 1]
            i += 2
        else:
            i += 1

    # Defensive: if message_text looks like a CLI flag, it was likely a mis-invocation.
    if message_text.startswith("--"):
        print(json.dumps({
            "error": f"Message text looks like a CLI flag: '{message_text}'. "
                     f"Usage: send_message.py <data_dir> <wallet> \"<actual message text>\" "
                     f"— the message must be the 3rd positional argument, NOT a --flag."
        }))
        sys.exit(1)

    # Check bridge
    if not is_bridge_running():
        print(json.dumps({"error": "XMTP bridge is not running. Start it first: python3 start_bridge.py <data_dir>"}))
        sys.exit(1)

    # Load own peer_id
    config = {}
    config_path = data_dir / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    own_peer_id = config.get("peer_id", "unknown")

    # Build ClawMatch message
    payload = {
        "content": message_text,
        "type": msg_type,
    }
    if topic:
        payload["topic"] = topic

    message = build_clawmatch_message("message", payload, sender_id=own_peer_id)

    # Send via XMTP
    try:
        result = send_xmtp(peer_wallet, message)

        # --- Bug #7 fix: record sent message to local messages log ---
        peer_id = _resolve_peer_id(data_dir, peer_wallet)
        msg_dir = data_dir / "messages"
        msg_dir.mkdir(parents=True, exist_ok=True)
        msg_file = msg_dir / f"{peer_id}.jsonl"
        from datetime import datetime, timezone
        entry = {
            "role": own_peer_id,
            "content": message_text,
            "type": msg_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if topic:
            entry["topic"] = topic
        with open(msg_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Also ensure wallet → peer_id mapping exists in peers.json
        _save_wallet_mapping(data_dir, peer_id, peer_wallet)

        print(json.dumps({
            "status": "sent",
            "to_wallet": peer_wallet,
            "own_peer_id": own_peer_id,
            "type": msg_type,
            "topic": topic,
            "send_result": result,
        }, indent=2, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()

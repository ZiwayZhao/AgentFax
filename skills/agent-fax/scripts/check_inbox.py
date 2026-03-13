#!/usr/bin/env python3
"""Check for new profiles, messages, and connection requests.

Pulls new messages from the XMTP bridge, processes them into local files,
then scans local directories for actionable items.

Usage:
  python3 check_inbox.py <data_dir>

Example:
  python3 check_inbox.py ~/.bot-matcher

Output (stdout): JSON summary of:
  - new_cards: peers who sent Profile A but haven't been evaluated yet
  - new_messages: peers with unread conversation messages
  - pending_connections: incoming connection requests awaiting acceptance
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from xmtp_client import configure, get_inbox, is_bridge_running, parse_clawmatch_message


def pull_xmtp_messages(data_dir: Path) -> int:
    """Pull new messages from XMTP bridge and process into local files.

    Returns count of new messages processed.
    """
    if not is_bridge_running():
        return 0

    try:
        messages = get_inbox(clear=True)
    except Exception:
        return 0

    processed = 0
    for raw_msg in messages:
        content_str = raw_msg.get("content", "")
        sender_inbox_id = raw_msg.get("senderInboxId", "unknown")

        # Parse ClawMatch protocol message
        msg = parse_clawmatch_message(content_str)

        if msg.get("protocol") != "clawmatch":
            # Not a ClawMatch message, skip
            continue

        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})
        sender_id = payload.get("sender_id", sender_inbox_id[:12])

        if msg_type == "card":
            # Profile A received — save to inbox
            profile = payload.get("profile", "")
            if profile:
                inbox_dir = data_dir / "inbox"
                inbox_dir.mkdir(parents=True, exist_ok=True)
                card_path = inbox_dir / f"{sender_id}.md"
                card_path.write_text(profile, encoding="utf-8")

                # Save peer info
                _save_peer_info(data_dir, sender_id, payload)
                processed += 1

        elif msg_type == "message":
            # Conversation/water message — append to messages/
            content = payload.get("content", "")
            msg_sub_type = payload.get("type", "conversation")
            topic = payload.get("topic")

            msg_dir = data_dir / "messages"
            msg_dir.mkdir(parents=True, exist_ok=True)
            msg_file = msg_dir / f"{sender_id}.jsonl"

            entry = {
                "role": sender_id,
                "content": content,
                "type": msg_sub_type,
                "timestamp": raw_msg.get("sentAt", datetime.now(timezone.utc).isoformat()),
            }
            if topic:
                entry["topic"] = topic

            with open(msg_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            processed += 1

        elif msg_type == "connect":
            # Connection request — update connections.json
            connections_file = data_dir / "connections.json"
            connections = {}
            if connections_file.exists():
                try:
                    connections = json.loads(connections_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass

            if sender_id not in connections:
                connections[sender_id] = {
                    "from_peer": sender_id,
                    "wallet_address": payload.get("wallet_address", ""),
                    "agent_id": payload.get("agent_id"),
                    "status": "pending",
                    "visibility": "shadow",
                    "received_at": raw_msg.get("sentAt", datetime.now(timezone.utc).isoformat()),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                connections[sender_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            connections_file.write_text(
                json.dumps(connections, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            _save_peer_info(data_dir, sender_id, payload)
            processed += 1

        elif msg_type == "accept":
            # Connection accepted by peer — update our handshake
            hs_path = data_dir / "handshakes" / f"{sender_id}.json"
            if hs_path.exists():
                hs = json.loads(hs_path.read_text(encoding="utf-8"))
                hs["visibility"]["sideB"] = "revealed"
                hs_path.write_text(
                    json.dumps(hs, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            processed += 1

    return processed


def _consolidate_peer(data_dir: Path, canonical_id: str, wallet: str):
    """Bug #11 fix: merge provisional/alias peer entries under the canonical sender_id.

    When send_card.py sends a card, it creates a provisional entry like
    ``_pending:0x320ecc6f`` because we don't yet know the peer's sender_id.
    Once we receive their first message, we learn the real sender_id (e.g. "icy").
    This function:
      1. Finds any peers.json entries with the same wallet but a different key.
      2. Merges their data (agent_id, wallet) into the canonical entry.
      3. Removes the old entry.
      4. Renames any message files from old key to canonical key.
    """
    if not wallet:
        return

    peers_path = data_dir / "peers.json"
    if not peers_path.exists():
        return
    try:
        peers = json.loads(peers_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return

    wallet_lower = wallet.lower()
    aliases_to_remove = []
    merged_data = {}

    for pid, info in peers.items():
        if pid == canonical_id:
            continue
        if info.get("wallet_address", "").lower() == wallet_lower:
            aliases_to_remove.append(pid)
            # Collect data from alias (agent_id, wallet, etc.)
            for k, v in info.items():
                if v is not None and k != "last_seen":
                    merged_data[k] = v

    if not aliases_to_remove:
        return

    # Merge into canonical entry
    canonical = peers.get(canonical_id, {})
    for k, v in merged_data.items():
        if not canonical.get(k):
            canonical[k] = v
    peers[canonical_id] = canonical

    # Remove aliases
    for alias in aliases_to_remove:
        del peers[alias]

    peers_path.write_text(json.dumps(peers, indent=2, ensure_ascii=False), encoding="utf-8")

    # Rename message files: messages/{alias}.jsonl → merge into messages/{canonical}.jsonl
    msg_dir = data_dir / "messages"
    if msg_dir.exists():
        canonical_file = msg_dir / "{}.jsonl".format(canonical_id)
        for alias in aliases_to_remove:
            alias_file = msg_dir / "{}.jsonl".format(alias)
            if alias_file.exists():
                # Append alias messages to canonical file
                alias_content = alias_file.read_text(encoding="utf-8").strip()
                if alias_content:
                    with open(canonical_file, "a", encoding="utf-8") as f:
                        f.write(alias_content + "\n")
                alias_file.unlink()

    # Migrate read cursors
    cursor_path = data_dir / "read_cursors.json"
    if cursor_path.exists():
        try:
            cursors = json.loads(cursor_path.read_text(encoding="utf-8"))
            changed = False
            for alias in aliases_to_remove:
                if alias in cursors:
                    # Add alias cursor to canonical cursor
                    cursors[canonical_id] = cursors.get(canonical_id, 0) + cursors.pop(alias)
                    changed = True
            if changed:
                cursor_path.write_text(
                    json.dumps(cursors, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except (json.JSONDecodeError, OSError):
            pass


def _save_peer_info(data_dir: Path, peer_id: str, payload: dict, wallet_address: str = None):
    """Save peer info (wallet_address, agent_id) to peers.json.

    Bug #9 fix: consistently store wallet_address for peer_id ↔ wallet mapping.
    Bug #11 fix: after saving, consolidate any aliases with same wallet.
    """
    peers_path = data_dir / "peers.json"
    peers = {}
    if peers_path.exists():
        try:
            peers = json.loads(peers_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    import time
    peer_entry = peers.get(peer_id, {})
    # Accept wallet from payload OR explicit parameter
    w = wallet_address or payload.get("wallet_address")
    if w:
        peer_entry["wallet_address"] = w
    if payload.get("agent_id") is not None:
        peer_entry["agent_id"] = payload["agent_id"]
    peer_entry["last_seen"] = time.time()
    peers[peer_id] = peer_entry

    peers_path.write_text(json.dumps(peers, indent=2, ensure_ascii=False), encoding="utf-8")

    # Bug #11: consolidate any provisional/alias entries with same wallet
    if w:
        _consolidate_peer(data_dir, peer_id, w)


def resolve_wallet_for_peer(data_dir: Path, peer_id: str) -> Optional[str]:
    """Look up wallet_address for a peer_id from peers.json."""
    peers_path = data_dir / "peers.json"
    if peers_path.exists():
        try:
            peers = json.loads(peers_path.read_text(encoding="utf-8"))
            return peers.get(peer_id, {}).get("wallet_address")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _load_read_cursors(data_dir: Path) -> dict:
    """Load read cursors from read_cursors.json."""
    cursor_path = data_dir / "read_cursors.json"
    if cursor_path.exists():
        try:
            return json.loads(cursor_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_read_cursors(data_dir: Path, cursors: dict):
    """Save read cursors to read_cursors.json."""
    cursor_path = data_dir / "read_cursors.json"
    cursor_path.write_text(json.dumps(cursors, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <data_dir>")
        sys.exit(1)

    data_dir = Path(sys.argv[1]).expanduser()
    configure(data_dir)

    # Bug #10 fix: ensure all required directories exist on first run
    inbox_dir = data_dir / "inbox"
    matches_dir = data_dir / "matches"
    messages_dir = data_dir / "messages"
    conversations_dir = data_dir / "conversations"
    criteria_dir = data_dir / "criteria"
    handshakes_dir = data_dir / "handshakes"
    connections_file = data_dir / "connections.json"
    for d in [inbox_dir, matches_dir, messages_dir, conversations_dir, criteria_dir, handshakes_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # --- 0. Pull new messages from XMTP ---
    xmtp_pulled = pull_xmtp_messages(data_dir)

    # --- 1. New cards (in inbox but no match evaluation yet) ---
    new_cards = []
    if inbox_dir.exists():
        for card_file in sorted(inbox_dir.glob("*.md")):
            peer_id = card_file.stem
            match_file = matches_dir / f"{peer_id}.md"
            if not match_file.exists():
                content = card_file.read_text(encoding="utf-8")
                preview = content[:200] + "..." if len(content) > 200 else content
                new_cards.append({
                    "peer_id": peer_id,
                    "file": str(card_file),
                    "preview": preview,
                })

    # --- 2. New messages (using read cursor to track unread) ---
    cursors = _load_read_cursors(data_dir)
    new_messages = []
    if messages_dir.exists():
        for msg_file in sorted(messages_dir.glob("*.jsonl")):
            peer_id = msg_file.stem
            all_lines = msg_file.read_text(encoding="utf-8").strip().split("\n")
            all_lines = [line for line in all_lines if line.strip()]
            total_count = len(all_lines)

            # Read cursor: how many lines we've already "seen"
            cursor = cursors.get(peer_id, 0)
            unread = total_count - cursor
            if unread > 0:
                latest = []
                for line in all_lines[cursor:]:
                    try:
                        latest.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                new_messages.append({
                    "peer_id": peer_id,
                    "unread_count": unread,
                    "latest": latest[-3:],
                })

    # Auto-advance cursors after reading (mark as read)
    if new_messages:
        for msg_file in messages_dir.glob("*.jsonl"):
            peer_id = msg_file.stem
            all_lines = msg_file.read_text(encoding="utf-8").strip().split("\n")
            cursors[peer_id] = len([l for l in all_lines if l.strip()])
        _save_read_cursors(data_dir, cursors)

    # --- 3. Pending connection requests ---
    pending_connections = []
    if connections_file.exists():
        try:
            connections = json.loads(connections_file.read_text(encoding="utf-8"))
            for peer_id, conn in connections.items():
                if conn.get("status") == "pending":
                    pending_connections.append({
                        "peer_id": peer_id,
                        "agent_id": conn.get("agent_id"),
                        "wallet_address": conn.get("wallet_address"),
                        "received_at": conn.get("received_at"),
                    })
        except (json.JSONDecodeError, KeyError):
            pass

    result = {
        "xmtp_pulled": xmtp_pulled,
        "new_cards": new_cards,
        "new_cards_count": len(new_cards),
        "new_messages": new_messages,
        "new_messages_count": len(new_messages),
        "pending_connections": pending_connections,
        "pending_connections_count": len(pending_connections),
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

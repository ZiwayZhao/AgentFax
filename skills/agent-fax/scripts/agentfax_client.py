#!/usr/bin/env python3
"""
AgentFax Client — protocol builder, parser, and XMTP bridge interface.

This is the core library for AgentFax. It handles:
  1. Building AgentFax protocol envelopes
  2. Parsing incoming messages
  3. Sending/receiving via the local XMTP bridge

Usage as library:
    from agentfax_client import AgentFaxClient

    fax = AgentFaxClient("~/.agentfax")
    fax.send("0xPEER...", "ping", {"message": "hello"})
    messages = fax.receive()

Usage as CLI:
    python3 agentfax_client.py ~/.agentfax health
    python3 agentfax_client.py ~/.agentfax send 0xPEER '{"type":"ping"}'
    python3 agentfax_client.py ~/.agentfax inbox
"""

import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


PROTOCOL_NAME = "agentfax"
PROTOCOL_VERSION = "1.0"


# ── Bridge communication ───────────────────────────────────────────

def _read_bridge_port(data_dir: str) -> int:
    """Read the XMTP bridge port from data directory."""
    port_file = Path(data_dir).expanduser() / "bridge_port"
    if not port_file.exists():
        raise FileNotFoundError(
            f"No bridge_port file at {port_file}. Is the XMTP bridge running?"
        )
    return int(port_file.read_text().strip())


def _bridge_url(data_dir: str, endpoint: str) -> str:
    port = _read_bridge_port(data_dir)
    return f"http://localhost:{port}{endpoint}"


def _bridge_get(data_dir: str, endpoint: str, params: dict = None) -> dict:
    url = _bridge_url(data_dir, endpoint)
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _bridge_post(data_dir: str, endpoint: str, body: dict) -> dict:
    url = _bridge_url(data_dir, endpoint)
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ── Protocol envelope ──────────────────────────────────────────────

def build_message(
    msg_type: str,
    payload: dict,
    sender_id: str = None,
    correlation_id: str = None,
    ttl: int = 3600,
) -> dict:
    """Build an AgentFax protocol envelope.

    Args:
        msg_type: Message type (ping, pong, discover, task_request, etc.)
        payload: Message payload (arbitrary dict)
        sender_id: Sender's human-readable agent name
        correlation_id: For request/response tracking
        ttl: Time-to-live in seconds (default 1 hour)

    Returns:
        AgentFax protocol envelope dict
    """
    msg = {
        "protocol": PROTOCOL_NAME,
        "version": PROTOCOL_VERSION,
        "type": msg_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ttl": ttl,
    }
    if sender_id:
        msg["sender_id"] = sender_id
    if correlation_id:
        msg["correlation_id"] = correlation_id
    return msg


def parse_message(raw_content: str) -> Optional[dict]:
    """Parse a raw XMTP message into an AgentFax envelope.

    Returns the parsed dict if it's a valid AgentFax message, None otherwise.
    """
    try:
        msg = json.loads(raw_content)
        if isinstance(msg, dict) and msg.get("protocol") == PROTOCOL_NAME:
            return msg
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def is_expired(msg: dict) -> bool:
    """Check if a message has exceeded its TTL."""
    try:
        ts = datetime.fromisoformat(msg["timestamp"])
        ttl = msg.get("ttl", 3600)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age > ttl
    except (KeyError, ValueError):
        return False


# ── High-level client ──────────────────────────────────────────────

class AgentFaxClient:
    """High-level AgentFax client wrapping the XMTP bridge."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self._sender_id = self._load_sender_id()

    def _load_sender_id(self) -> str:
        """Load agent name from config or chain identity."""
        for fname in ("chain_identity.json", "config.json"):
            fpath = os.path.join(self.data_dir, fname)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    data = json.load(f)
                name = data.get("claw_name") or data.get("name") or data.get("peer_id")
                if name:
                    return name
        return "unknown"

    def health(self) -> dict:
        """Check XMTP bridge health."""
        return _bridge_get(self.data_dir, "/health")

    def can_message(self, wallet_address: str) -> bool:
        """Check if a wallet address is reachable via XMTP."""
        result = _bridge_get(self.data_dir, "/can-message", {"address": wallet_address})
        return result.get("canMessage", False)

    def send(
        self,
        to_wallet: str,
        msg_type: str,
        payload: dict,
        correlation_id: str = None,
        ttl: int = 3600,
    ) -> dict:
        """Send an AgentFax message to a wallet address.

        Args:
            to_wallet: Recipient's Ethereum wallet address (0x...)
            msg_type: Message type (ping, task_request, etc.)
            payload: Message payload
            correlation_id: Optional correlation ID for tracking
            ttl: Message time-to-live in seconds

        Returns:
            Bridge response with messageId, conversationId, etc.
        """
        envelope = build_message(
            msg_type=msg_type,
            payload=payload,
            sender_id=self._sender_id,
            correlation_id=correlation_id,
            ttl=ttl,
        )
        return _bridge_post(self.data_dir, "/send", {
            "to": to_wallet,
            "content": json.dumps(envelope),
        })

    def send_file(
        self,
        to_wallet: str,
        file_path: str,
        msg_type: str = "file_transfer",
        correlation_id: str = None,
    ) -> dict:
        """Send a file as an inline XMTP attachment (< 1MB).

        Args:
            to_wallet: Recipient wallet address
            file_path: Path to the file to send
            msg_type: AgentFax message type (default: file_transfer)
            correlation_id: Optional correlation ID

        Returns:
            Bridge response with messageId, etc.
        """
        fpath = Path(file_path).expanduser()
        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")

        file_bytes = fpath.read_bytes()
        if len(file_bytes) > 1_000_000:
            raise ValueError(
                f"File too large ({len(file_bytes)} bytes). "
                "Use send_remote_attachment for files > 1MB."
            )

        mime_type = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
        content_b64 = base64.b64encode(file_bytes).decode("ascii")

        # Send via bridge attachment endpoint
        result = _bridge_post(self.data_dir, "/send-attachment", {
            "to": to_wallet,
            "filename": fpath.name,
            "mimeType": mime_type,
            "content": content_b64,
        })

        # Also send an AgentFax protocol notification so receiver knows context
        envelope = build_message(
            msg_type=msg_type,
            payload={
                "filename": fpath.name,
                "mimeType": mime_type,
                "size": len(file_bytes),
                "message": f"File sent: {fpath.name}",
            },
            sender_id=self._sender_id,
            correlation_id=correlation_id or f"file_{int(time.time())}",
        )
        _bridge_post(self.data_dir, "/send", {
            "to": to_wallet,
            "content": json.dumps(envelope),
        })

        return result

    def send_image(self, to_wallet: str, image_path: str) -> dict:
        """Convenience method to send an image file.

        Args:
            to_wallet: Recipient wallet address
            image_path: Path to the image file (jpg, png, gif, etc.)

        Returns:
            Bridge response
        """
        return self.send_file(
            to_wallet, image_path,
            msg_type="image_transfer",
            correlation_id=f"img_{int(time.time())}",
        )

    def broadcast(
        self,
        wallets: List[str],
        msg_type: str,
        payload: dict,
        correlation_id: str = None,
        ttl: int = 3600,
    ) -> dict:
        """Send the same AgentFax message to multiple recipients.

        Args:
            wallets: List of recipient wallet addresses
            msg_type: Message type
            payload: Message payload
            correlation_id: Optional correlation ID
            ttl: Time-to-live in seconds

        Returns:
            Bridge broadcast response with per-recipient results
        """
        envelope = build_message(
            msg_type=msg_type,
            payload=payload,
            sender_id=self._sender_id,
            correlation_id=correlation_id or f"bcast_{int(time.time())}",
            ttl=ttl,
        )
        return _bridge_post(self.data_dir, "/broadcast", {
            "to": wallets,
            "content": json.dumps(envelope),
        })

    def receive(self, since: str = None, clear: bool = False) -> List[dict]:
        """Receive AgentFax messages from the bridge inbox.

        Args:
            since: ISO timestamp to filter messages after
            clear: Clear inbox after reading

        Returns:
            List of parsed AgentFax message dicts (non-agentfax messages filtered out)
        """
        params = {}
        if since:
            params["since"] = since
        if clear:
            params["clear"] = "1"

        result = _bridge_get(self.data_dir, "/inbox", params if params else None)
        messages = []
        for raw in result.get("messages", []):
            content_type = raw.get("contentType", "text")

            # Handle attachment messages (non-text)
            if content_type in ("attachment", "remoteAttachment"):
                entry = {
                    "protocol": PROTOCOL_NAME,
                    "version": PROTOCOL_VERSION,
                    "type": "attachment_received",
                    "payload": {
                        "content_type": content_type,
                        "content": raw.get("content", ""),
                        "attachment": raw.get("attachment"),
                    },
                    "timestamp": raw.get("sentAt", datetime.now(timezone.utc).isoformat()),
                    "ttl": 86400,
                    "_xmtp_id": raw.get("id"),
                    "_xmtp_sender": raw.get("senderInboxId"),
                    "_xmtp_sent_at": raw.get("sentAt"),
                    "_xmtp_received_at": raw.get("receivedAt"),
                }
                messages.append(entry)
                continue

            # Handle regular text (AgentFax protocol messages)
            parsed = parse_message(raw.get("content", ""))
            if parsed and not is_expired(parsed):
                parsed["_xmtp_id"] = raw.get("id")
                parsed["_xmtp_sender"] = raw.get("senderInboxId")
                parsed["_xmtp_sent_at"] = raw.get("sentAt")
                parsed["_xmtp_received_at"] = raw.get("receivedAt")
                messages.append(parsed)
        return messages

    def resolve_agent(self, agent_id: int) -> Optional[str]:
        """Resolve an on-chain Agent ID to a wallet address.

        Uses chain/resolve.py under the hood.
        """
        import subprocess
        script = os.path.join(
            os.path.dirname(__file__), "chain", "resolve.py"
        )
        try:
            result = subprocess.run(
                ["python3", script, str(agent_id), "--network", "sepolia"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if line.strip().startswith("0x"):
                        return line.strip()
            return None
        except Exception:
            return None

    def ping(self, to_wallet: str) -> dict:
        """Send a ping and return the bridge response."""
        return self.send(to_wallet, "ping", {
            "message": f"ping from {self._sender_id}"
        }, correlation_id=f"ping_{int(time.time())}")

    def pong(self, to_wallet: str, correlation_id: str) -> dict:
        """Send a pong response."""
        return self.send(to_wallet, "pong", {
            "message": f"pong from {self._sender_id}",
            "received_correlation_id": correlation_id,
        }, correlation_id=f"pong_{int(time.time())}")


# ── CLI ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 agentfax_client.py <data_dir> <command> [args...]")
        print("Commands: health, send, inbox, ping, can-message")
        sys.exit(1)

    data_dir = sys.argv[1]
    command = sys.argv[2]
    fax = AgentFaxClient(data_dir)

    if command == "health":
        print(json.dumps(fax.health(), indent=2))

    elif command == "send":
        if len(sys.argv) < 5:
            print("Usage: ... send <wallet> <type> [payload_json]")
            sys.exit(1)
        wallet = sys.argv[3]
        msg_type = sys.argv[4]
        payload = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
        result = fax.send(wallet, msg_type, payload)
        print(json.dumps(result, indent=2))

    elif command == "inbox":
        messages = fax.receive()
        if not messages:
            print("No AgentFax messages in inbox.")
        else:
            for msg in messages:
                print(f"[{msg.get('type')}] from={msg.get('sender_id', '?')} "
                      f"corr={msg.get('correlation_id', '-')}")
                print(f"  payload: {json.dumps(msg.get('payload', {}))}")
                print()

    elif command == "ping":
        if len(sys.argv) < 4:
            print("Usage: ... ping <wallet>")
            sys.exit(1)
        result = fax.ping(sys.argv[3])
        print(json.dumps(result, indent=2))

    elif command == "can-message":
        if len(sys.argv) < 4:
            print("Usage: ... can-message <wallet>")
            sys.exit(1)
        reachable = fax.can_message(sys.argv[3])
        print(f"{'Reachable' if reachable else 'Not reachable'}: {sys.argv[3]}")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()

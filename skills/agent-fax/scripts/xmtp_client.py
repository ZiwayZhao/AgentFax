#!/usr/bin/env python3
"""Python wrapper for the XMTP Bridge HTTP API.

Provides simple functions for sending/receiving XMTP messages.
The bridge port is auto-discovered from <data_dir>/bridge_port.

Usage as a library:
    from xmtp_client import configure, send_xmtp, get_inbox, is_bridge_running
    configure("~/.bot-matcher")   # reads port from bridge_port file

Usage as CLI (for testing):
    python3 xmtp_client.py <data_dir> health
    python3 xmtp_client.py <data_dir> send <wallet_address> '{"protocol":"clawmatch",...}'
    python3 xmtp_client.py <data_dir> inbox [--since ISO] [--clear]
"""

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


_bridge_url = "http://127.0.0.1:3500"  # default, overridden by configure()


def configure(data_dir):
    """Read bridge port from data_dir/bridge_port and set the bridge URL.

    Call this once at startup before using any other function.
    If the port file doesn't exist, falls back to default 3500.
    """
    global _bridge_url
    port_file = Path(data_dir).expanduser() / "bridge_port"
    if port_file.exists():
        try:
            port = int(port_file.read_text().strip())
            _bridge_url = f"http://127.0.0.1:{port}"
            return
        except (ValueError, OSError):
            pass
    _bridge_url = "http://127.0.0.1:3500"


def _request(method: str, path: str, body: dict = None, timeout: int = 30) -> dict:
    """Make an HTTP request to the local XMTP bridge."""
    url = f"{_bridge_url}{path}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def is_bridge_running() -> bool:
    """Check if the XMTP bridge is running and connected."""
    try:
        result = _request("GET", "/health")
        return result.get("status") == "connected"
    except (URLError, OSError):
        return False


def get_bridge_health() -> dict:
    """Get bridge health info (address, env, inbox count, etc.)."""
    return _request("GET", "/health")


def send_xmtp(to_address: str, content: dict, timeout: int = 30) -> dict:
    """Send a ClawMatch message via XMTP.

    Args:
        to_address: Ethereum wallet address of the recipient.
        content: Message content (will be JSON-serialized).
        timeout: Request timeout in seconds.

    Returns:
        dict with status, messageId, conversationId.

    Raises:
        URLError: If bridge is not running or send fails.
    """
    return _request("POST", "/send", {
        "to": to_address,
        "content": json.dumps(content, ensure_ascii=False),
    }, timeout=timeout)


def get_inbox(since: str = None, clear: bool = False) -> list:
    """Get messages from the XMTP inbox buffer.

    Args:
        since: ISO timestamp to filter messages after.
        clear: If True, clear the inbox after reading.

    Returns:
        List of message dicts with id, senderInboxId, content, sentAt, etc.
    """
    params = []
    if since:
        params.append(f"since={since}")
    if clear:
        params.append("clear=1")
    query = f"?{'&'.join(params)}" if params else ""
    result = _request("GET", f"/inbox{query}")
    return result.get("messages", [])


def clear_inbox() -> int:
    """Clear the inbox buffer. Returns number of messages cleared."""
    result = _request("POST", "/clear-inbox")
    return result.get("cleared", 0)


def can_message(address: str) -> bool:
    """Check if an address can receive XMTP messages."""
    result = _request("GET", f"/can-message?address={address}")
    return result.get("canMessage", False)


def parse_clawmatch_message(raw_content: str) -> dict:
    """Parse a raw XMTP message content string into a ClawMatch message.

    ClawMatch messages are JSON strings with the format:
    {"protocol": "clawmatch", "version": "2.0", "type": "...", "payload": {...}}

    Returns the parsed dict, or wraps plain text in a basic message format.
    """
    if not raw_content:
        return {"protocol": "unknown", "type": "empty", "payload": {}}
    try:
        msg = json.loads(raw_content)
        if isinstance(msg, dict) and msg.get("protocol") == "clawmatch":
            return msg
        # Valid JSON but not a clawmatch message
        return {"protocol": "unknown", "type": "raw_json", "payload": msg}
    except (json.JSONDecodeError, TypeError):
        # Plain text — wrap it
        return {
            "protocol": "unknown",
            "type": "plain_text",
            "payload": {"text": raw_content},
        }


def build_clawmatch_message(msg_type: str, payload: dict, sender_id: str = None) -> dict:
    """Build a ClawMatch protocol message.

    Args:
        msg_type: One of "card", "message", "connect", "accept".
        payload: Message-specific payload.
        sender_id: Sender's peer_id (optional, included in payload).

    Returns:
        Formatted ClawMatch message dict.
    """
    msg = {
        "protocol": "clawmatch",
        "version": "2.0",
        "type": msg_type,
        "payload": payload,
    }
    if sender_id:
        msg["payload"]["sender_id"] = sender_id
    return msg


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 xmtp_client.py <data_dir> health")
        print("  python3 xmtp_client.py <data_dir> send <wallet_address> '<json_content>'")
        print("  python3 xmtp_client.py <data_dir> inbox [--since ISO] [--clear]")
        print("  python3 xmtp_client.py <data_dir> can-message <wallet_address>")
        sys.exit(1)

    data_dir = sys.argv[1]
    configure(data_dir)
    cmd = sys.argv[2]

    if cmd == "health":
        try:
            result = get_bridge_health()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except URLError as e:
            print(json.dumps({"error": f"Bridge not running: {e}"}))
            sys.exit(1)

    elif cmd == "send":
        if len(sys.argv) < 5:
            print("Usage: python3 xmtp_client.py <data_dir> send <wallet_address> '<json_content>'")
            sys.exit(1)
        to_addr = sys.argv[3]
        content = json.loads(sys.argv[4])
        try:
            result = send_xmtp(to_addr, content)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except URLError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)

    elif cmd == "inbox":
        since = None
        clear = False
        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--since" and i + 1 < len(args):
                since = args[i + 1]
                i += 2
            elif args[i] == "--clear":
                clear = True
                i += 1
            else:
                i += 1
        messages = get_inbox(since=since, clear=clear)
        print(json.dumps({"messages": messages, "count": len(messages)}, indent=2, ensure_ascii=False))

    elif cmd == "can-message":
        if len(sys.argv) < 4:
            print("Usage: python3 xmtp_client.py <data_dir> can-message <wallet_address>")
            sys.exit(1)
        addr = sys.argv[3]
        try:
            result = can_message(addr)
            print(json.dumps({"address": addr, "canMessage": result}))
        except URLError as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()

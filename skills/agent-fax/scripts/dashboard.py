#!/usr/bin/env python3
"""
AgentFax Dashboard — real-time communication monitor.

A self-contained web dashboard for observing agent-to-agent fax communication.
Shows message flow, task collaboration, network topology, and statistics.

Usage:
    python3 dashboard.py ~/.agentfax              # Default port 8080
    python3 dashboard.py ~/.agentfax --port 9000  # Custom port
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from store import InboxStore, OutboxStore
from task_manager import TaskManager
from peers import PeerManager


# ── Data Access Layer ────────────────────────────────────────────

class DashboardAPI:
    """Read-only data access for the dashboard."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self._config = self._load_config()

    def _load_config(self) -> dict:
        config_file = os.path.join(self.data_dir, "config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _load_identity(self) -> dict:
        """Load chain identity info."""
        id_file = os.path.join(self.data_dir, "chain_identity.json")
        if os.path.exists(id_file):
            try:
                with open(id_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    def _load_wallet(self) -> str:
        """Load wallet address."""
        wallet_file = os.path.join(self.data_dir, "wallet.json")
        if os.path.exists(wallet_file):
            try:
                with open(wallet_file) as f:
                    data = json.load(f)
                    return data.get("address", "")
            except (json.JSONDecodeError, IOError):
                pass
        return ""

    def get_stats(self) -> dict:
        inbox = InboxStore(self.data_dir)
        outbox = OutboxStore(self.data_dir)
        tasks = TaskManager(self.data_dir)
        peers = PeerManager(self.data_dir)

        try:
            # Message type distribution from inbox
            msg_types = {}
            try:
                rows = inbox.conn.execute(
                    "SELECT msg_type, COUNT(*) FROM messages GROUP BY msg_type"
                ).fetchall()
                msg_types = {(row[0] or "unknown"): row[1] for row in rows}
            except Exception:
                pass

            # Task state counts
            task_states = {}
            for state in ["pending", "sent", "acked", "in_progress",
                          "completed", "failed", "cancelled", "timed_out"]:
                count = len(tasks.query(state=state))
                if count > 0:
                    task_states[state] = count

            return {
                "inbox": {
                    "total": inbox.count(),
                    "new": inbox.count("new"),
                    "processing": inbox.count("processing"),
                    "processed": inbox.count("processed"),
                    "failed": inbox.count("failed"),
                },
                "outbox": {
                    "total": outbox.count(),
                    "sent": outbox.count("sent"),
                    "acked": outbox.count("acked"),
                },
                "tasks": {
                    "total": len(tasks.query()),
                    **task_states,
                },
                "peers": {
                    "total": peers.count(),
                    "online": len(peers.get_online()),
                },
                "msg_types": msg_types,
                "agent": {
                    **self._config,
                    "wallet": self._load_wallet(),
                    **self._load_identity(),
                },
            }
        finally:
            inbox.close()
            outbox.close()
            tasks.close()

    def get_messages(self, msg_type=None, sender=None, status=None,
                     limit=50, offset=0) -> dict:
        inbox = InboxStore(self.data_dir)
        outbox = OutboxStore(self.data_dir)

        try:
            # Inbox messages
            in_msgs = inbox.query(
                msg_type=msg_type, sender_id=sender,
                status=status, limit=200,
            )
            for m in in_msgs:
                m["direction"] = "in"
                m["timestamp"] = m.get("received_at", "")

            # Outbox messages
            out_msgs = outbox.query(status=status, limit=200)
            for m in out_msgs:
                m["direction"] = "out"
                m["timestamp"] = m.get("sent_at", "")

            # Apply type filter to outbox
            if msg_type:
                out_msgs = [m for m in out_msgs if m.get("msg_type") == msg_type]

            # Merge and sort by time
            all_msgs = in_msgs + out_msgs
            all_msgs.sort(key=lambda m: m.get("timestamp", ""), reverse=True)

            total = len(all_msgs)
            page = all_msgs[offset:offset + limit]

            return {"messages": page, "total": total}
        finally:
            inbox.close()
            outbox.close()

    def get_tasks(self, state=None, role=None, skill=None, limit=50) -> dict:
        tasks = TaskManager(self.data_dir)
        try:
            result = tasks.query(state=state, role=role, skill=skill, limit=limit)
            return {"tasks": result}
        finally:
            tasks.close()

    def get_peers(self) -> dict:
        peers = PeerManager(self.data_dir)
        all_peers = peers.list_all()
        online_peers = peers.get_online()
        online_names = {p["name"] for p in online_peers}

        peer_list = []
        for name, data in all_peers.items():
            peer_list.append({
                "name": name,
                "wallet": data.get("wallet", ""),
                "last_seen": data.get("last_seen", ""),
                "online": name in online_names,
                "latency_ms": data.get("avg_latency_ms", data.get("latency_ms")),
                "skills": data.get("skills", []),
                "seen_count": data.get("seen_count", 0),
                "capabilities": data.get("capabilities"),
            })

        return {
            "peers": peer_list,
            "self": {
                **self._config,
                "wallet": self._load_wallet(),
            },
        }

    def get_activity(self, limit=20) -> dict:
        inbox = InboxStore(self.data_dir)
        outbox = OutboxStore(self.data_dir)
        tasks = TaskManager(self.data_dir)

        try:
            events = []

            # Inbox events
            for m in inbox.query(limit=limit):
                events.append({
                    "time": m.get("received_at", ""),
                    "type": "msg_in",
                    "icon": "↓",
                    "detail": f"Received {m.get('msg_type', '?')} from {m.get('sender_id', '?')}",
                    "msg_type": m.get("msg_type"),
                })

            # Outbox events
            for m in outbox.query(limit=limit):
                wallet = m.get("recipient_wallet", "?")
                short_wallet = f"{wallet[:6]}…{wallet[-4:]}" if len(wallet) > 12 else wallet
                events.append({
                    "time": m.get("sent_at", ""),
                    "type": "msg_out",
                    "icon": "↑",
                    "detail": f"Sent {m.get('msg_type', '?')} to {short_wallet}",
                    "msg_type": m.get("msg_type"),
                })

            # Task events
            for t in tasks.query(limit=limit):
                state = t.get("state", "?")
                skill = t.get("skill", "?")
                peer = t.get("peer_name", "?")
                dur = t.get("duration_ms")
                dur_str = f" ({dur:.0f}ms)" if dur else ""
                events.append({
                    "time": (t.get("completed_at") or t.get("started_at")
                             or t.get("created_at", "")),
                    "type": "task",
                    "icon": "⚡",
                    "detail": f"Task {skill} [{state}] peer={peer}{dur_str}",
                    "msg_type": f"task_{state}",
                })

            events.sort(key=lambda e: e.get("time", ""), reverse=True)
            return {"events": events[:limit]}
        finally:
            inbox.close()
            outbox.close()
            tasks.close()


# ── HTTP Handler ─────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    api: DashboardAPI = None
    html_path: str = None

    def log_message(self, format, *args):
        pass  # Suppress default access logging

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _param(self, params, key, default=None):
        values = params.get(key, [])
        return values[0] if values else default

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self._serve_html()

            elif path == "/api/stats":
                self._send_json(self.api.get_stats())

            elif path == "/api/messages":
                self._send_json(self.api.get_messages(
                    msg_type=self._param(params, "type"),
                    sender=self._param(params, "sender"),
                    status=self._param(params, "status"),
                    limit=int(self._param(params, "limit", "50")),
                    offset=int(self._param(params, "offset", "0")),
                ))

            elif path == "/api/tasks":
                self._send_json(self.api.get_tasks(
                    state=self._param(params, "state"),
                    role=self._param(params, "role"),
                    skill=self._param(params, "skill"),
                    limit=int(self._param(params, "limit", "50")),
                ))

            elif path == "/api/peers":
                self._send_json(self.api.get_peers())

            elif path == "/api/activity":
                self._send_json(self.api.get_activity(
                    limit=int(self._param(params, "limit", "20")),
                ))

            else:
                self.send_error(404, "Not Found")

        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def _serve_html(self):
        try:
            with open(self.html_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, "dashboard.html not found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Dashboard — real-time communication monitor"
    )
    parser.add_argument("data_dir", help="AgentFax data directory (e.g., ~/.agentfax)")
    parser.add_argument("--port", "-p", type=int, default=8080,
                        help="HTTP port (default: 8080)")

    args = parser.parse_args()
    data_dir = str(Path(args.data_dir).expanduser())

    if not os.path.isdir(data_dir):
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    api = DashboardAPI(data_dir)

    # Set class-level references for the handler
    DashboardHandler.api = api
    DashboardHandler.html_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard.html"
    )

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)

    print("=" * 50)
    print("📠 AgentFax Dashboard")
    print(f"   Data:  {data_dir}")
    print(f"   URL:   http://localhost:{args.port}")
    print("   Press Ctrl+C to stop")
    print("=" * 50)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()

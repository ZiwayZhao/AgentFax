#!/usr/bin/env python3
"""
AgentFax Dashboard Server v2 — modular HTTP server.

Serves:
  /api/*     → JSON API (dashboard_api.py)
  /app/*     → React SPA (Vite build output)
  /legacy    → Original dashboard.html
  /          → SPA index.html (or legacy if no build found)

Usage:
    python3 dashboard_server.py ~/.agentfax              # Default port 8080
    python3 dashboard_server.py ~/.agentfax --port 9000
"""

import argparse
import json
import logging
import mimetypes
import os
import re
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard_api import DashboardAPIv2

logger = logging.getLogger("agentfax.dashboard_server")

# ── Threaded HTTP Server ──────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ── Request Handler ───────────────────────────────────────────────

class DashboardV2Handler(BaseHTTPRequestHandler):
    """Route requests to API handlers or static file serving."""

    api: DashboardAPIv2 = None
    spa_dir: str = None       # Path to frontend/dist
    legacy_path: str = None   # Path to dashboard.html

    _ALLOWED_ORIGINS = {"http://localhost:5173", "http://localhost:8080", "http://127.0.0.1:5173", "http://127.0.0.1:8080"}

    def _cors_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        if origin in self._ALLOWED_ORIGINS:
            return origin
        return "http://localhost:5173"

    def log_message(self, format, *args):
        pass  # Suppress default logging

    # ── JSON helpers ──────────────────────────────────────────

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON body")

    def _param(self, params, key, default=None):
        values = params.get(key, [])
        return values[0] if values else default

    # ── Static file serving ───────────────────────────────────

    def _serve_file(self, filepath):
        if not os.path.isfile(filepath):
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(filepath)
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)

    def _serve_spa_index(self):
        """Serve SPA index.html for client-side routing."""
        if self.spa_dir:
            index = os.path.join(self.spa_dir, "index.html")
            if os.path.isfile(index):
                self._serve_file(index)
                return
        # Fallback to legacy
        if self.legacy_path and os.path.isfile(self.legacy_path):
            self._serve_file(self.legacy_path)
        else:
            self.send_error(404, "No frontend build found")

    # ── Route matching ────────────────────────────────────────

    def _match_path(self, path: str, pattern: str) -> dict:
        """Match /api/peers/:peer_id style routes. Returns params dict or None."""
        parts = pattern.split("/")
        actual = path.split("/")
        if len(parts) != len(actual):
            return None
        params = {}
        for p, a in zip(parts, actual):
            if p.startswith(":"):
                params[p[1:]] = a
            elif p != a:
                return None
        return params

    # ── GET routes ────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        try:
            # ── API routes ────────────────────────────────
            if path == "/api/health":
                self._send_json(self.api.get_health())

            elif path == "/api/agent/profile":
                self._send_json(self.api.get_agent_profile())

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

            elif path == "/api/sessions":
                self._send_json(self.api.get_sessions(
                    state=self._param(params, "state"),
                ))

            elif path == "/api/skill-cards":
                self._send_json(self.api.get_skill_cards())

            elif path == "/api/workflows":
                self._send_json(self.api.get_workflows(
                    state=self._param(params, "state"),
                ))

            elif path == "/api/settings/context-policy":
                self._send_json(self.api.get_context_policy())

            elif path.startswith("/api/metering/receipts"):
                self._send_json(self.api.get_metering_receipts(
                    limit=int(self._param(params, "limit", "50")),
                ))

            # Parameterized API routes
            elif (m := self._match_path(path, "/api/peers/:peer_id/reputation")) is not None:
                self._send_json(self.api.get_peer_reputation(m["peer_id"]))

            elif (m := self._match_path(path, "/api/sessions/:id")) is not None:
                self._send_json(self.api.get_session(m["id"]))

            elif (m := self._match_path(path, "/api/workflows/:id")) is not None:
                self._send_json(self.api.get_workflow(m["id"]))

            # ── Legacy dashboard ──────────────────────────
            elif path == "/legacy":
                if self.legacy_path and os.path.isfile(self.legacy_path):
                    self._serve_file(self.legacy_path)
                else:
                    self.send_error(404, "Legacy dashboard not found")

            # ── SPA static assets ─────────────────────────
            elif self.spa_dir and path.startswith("/assets/"):
                filepath = os.path.realpath(os.path.join(self.spa_dir, path.lstrip("/")))
                spa_real = os.path.realpath(self.spa_dir)
                if not filepath.startswith(spa_real + os.sep):
                    self.send_error(403, "Forbidden")
                    return
                self._serve_file(filepath)

            # ── SPA fallback (client-side routing) ────────
            else:
                self._serve_spa_index()

        except Exception as e:
            logger.error(f"Request error: {e}", exc_info=True)
            self._send_json({"error": str(e)}, status=500)

    # ── POST/PATCH routes ─────────────────────────────────────

    def do_POST(self):
        # Future: session actions, workflow commands
        self._send_json({"error": "not implemented"}, status=501)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if (m := self._match_path(path, "/api/peers/:peer_id/trust")) is not None:
                body = self._read_body()
                tier = body.get("trust_tier", 0)
                self._send_json(self.api.set_peer_trust(m["peer_id"], int(tier)))

            elif path == "/api/settings/context-policy":
                body = self._read_body()
                self._send_json(self.api.update_context_policy(body))

            else:
                self._send_json({"error": "not found"}, status=404)
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Dashboard v2 — React SPA + API server"
    )
    parser.add_argument("data_dir", help="AgentFax data directory (e.g., ~/.agentfax)")
    parser.add_argument("--port", "-p", type=int, default=8080, help="HTTP port (default: 8080)")

    args = parser.parse_args()
    data_dir = str(Path(args.data_dir).expanduser())

    if not os.path.isdir(data_dir):
        print(f"Error: Data directory not found: {data_dir}")
        sys.exit(1)

    api = DashboardAPIv2(data_dir)

    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(scripts_dir)))

    DashboardV2Handler.api = api
    DashboardV2Handler.spa_dir = os.path.join(repo_root, "frontend", "dist")
    DashboardV2Handler.legacy_path = os.path.join(scripts_dir, "dashboard.html")

    server = ThreadedHTTPServer(("0.0.0.0", args.port), DashboardV2Handler)

    spa_status = "found" if os.path.isdir(DashboardV2Handler.spa_dir) else "not found (using legacy)"

    print("=" * 50)
    print("AgentFax Dashboard v2")
    print(f"  Data:    {data_dir}")
    print(f"  URL:     http://localhost:{args.port}")
    print(f"  SPA:     {spa_status}")
    print(f"  Legacy:  http://localhost:{args.port}/legacy")
    print("  Press Ctrl+C to stop")
    print("=" * 50)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
AgentFax Daemon — always-on message processor.

The "fax machine" — stays running in the background, automatically
processing incoming messages via the router and built-in handlers.

Features:
- Polls bridge inbox every N seconds (configurable)
- Dispatches messages to registered handlers
- Sends automatic ack receipts
- Stores messages in SQLite
- Tracks peers in address book
- Sends heartbeat pings to known peers

Usage:
    # Start daemon (foreground, for development)
    python3 daemon.py ~/.agentfax start

    # Start daemon (background)
    python3 daemon.py ~/.agentfax start --background

    # Stop background daemon
    python3 daemon.py ~/.agentfax stop

    # Check daemon status
    python3 daemon.py ~/.agentfax status
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentfax_client import AgentFaxClient
from router import MessageRouter, RouterContext
from store import InboxStore, OutboxStore
from peers import PeerManager
from handlers.builtin import register_builtin_handlers

# ── Logging setup ─────────────────────────────────────────────────

def setup_logging(data_dir: str, verbose: bool = False):
    """Configure logging to both console and file."""
    log_level = logging.DEBUG if verbose else logging.INFO

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))

    # File handler
    log_file = os.path.join(data_dir, "daemon.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    ))

    root_logger = logging.getLogger("agentfax")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console)
    root_logger.addHandler(file_handler)

    return logging.getLogger("agentfax.daemon")


# ── Daemon ────────────────────────────────────────────────────────

class AgentFaxDaemon:
    """The always-on message processing daemon."""

    def __init__(self, data_dir: str, poll_interval: float = 2.0):
        self.data_dir = str(Path(data_dir).expanduser())
        self.poll_interval = poll_interval
        self.running = False

        # Core components
        self.client = AgentFaxClient(self.data_dir)
        self.router = MessageRouter()
        self.inbox_store = InboxStore(self.data_dir)
        self.outbox_store = OutboxStore(self.data_dir)
        self.peer_manager = PeerManager(self.data_dir)

        # Router context
        self.ctx = RouterContext(
            client=self.client,
            inbox_store=self.inbox_store,
            outbox_store=self.outbox_store,
            peer_manager=self.peer_manager,
        )

        # Register built-in handlers
        register_builtin_handlers(self.router, self.data_dir)

        # Stats
        self._start_time = None
        self._cycles = 0
        self._total_processed = 0

        self.logger = logging.getLogger("agentfax.daemon")

    def _resolve_sender_wallet(self, msg: dict) -> dict:
        """Try to add sender wallet address to message if missing.

        The bridge gives us senderInboxId but not wallet.
        We look up the wallet from our peers database.
        """
        if msg.get("_xmtp_sender_wallet"):
            return msg

        sender_id = msg.get("sender_id")
        if sender_id:
            peer = self.peer_manager.get(sender_id)
            if peer and peer.get("wallet"):
                msg["_xmtp_sender_wallet"] = peer["wallet"]

        return msg

    def _send_ack(self, msg: dict):
        """Send automatic delivery acknowledgment."""
        sender_wallet = msg.get("_xmtp_sender_wallet")
        corr_id = msg.get("correlation_id")

        if not sender_wallet or not corr_id:
            return

        # Don't ack acks (infinite loop prevention)
        if msg.get("type") in ("ack", "pong", "error"):
            return

        try:
            self.client.send(
                to_wallet=sender_wallet,
                msg_type="ack",
                payload={
                    "correlation_id": corr_id,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                },
                correlation_id=f"ack_{int(time.time())}",
            )
        except Exception as e:
            self.logger.debug(f"Failed to send ack: {e}")

    def run(self):
        """Main daemon loop — poll, store, route, ack."""
        self.running = True
        self._start_time = time.time()

        self.logger.info("=" * 60)
        self.logger.info(f"AgentFax Daemon starting")
        self.logger.info(f"  Agent: {self.client._sender_id}")
        self.logger.info(f"  Data:  {self.data_dir}")
        self.logger.info(f"  Poll:  {self.poll_interval}s")
        self.logger.info(f"  Handlers: {', '.join(self.router.registered_types)}")
        self.logger.info("=" * 60)

        # Verify bridge is accessible
        try:
            health = self.client.health()
            self.logger.info(
                f"Bridge connected: {health.get('address', '?')}"
            )
        except Exception as e:
            self.logger.error(f"Bridge not accessible: {e}")
            self.logger.error("Is the XMTP bridge running?")
            return

        # Write PID file
        pid_file = os.path.join(self.data_dir, "daemon.pid")
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

        try:
            while self.running:
                try:
                    self._cycle()
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    self.logger.error(f"Cycle error: {e}")
                    time.sleep(5)  # Back off on errors

                time.sleep(self.poll_interval)

        finally:
            # Cleanup
            if os.path.exists(pid_file):
                os.remove(pid_file)
            self.inbox_store.close()
            self.outbox_store.close()
            self.logger.info("Daemon stopped.")

    def _cycle(self):
        """One poll cycle: pull messages → store → dispatch → ack."""
        self._cycles += 1

        messages = self.client.receive(clear=True)
        if not messages:
            return

        self.logger.info(f"Received {len(messages)} message(s)")

        for msg in messages:
            msg = self._resolve_sender_wallet(msg)

            # Store
            is_new = self.inbox_store.save(msg)
            if not is_new:
                continue  # Skip duplicates

            # Mark as processing
            msg_id = msg.get("_xmtp_id")
            if msg_id:
                self.inbox_store.mark_status(msg_id, "processing")

            # Dispatch to router
            try:
                self.router.dispatch(msg, self.ctx)

                # Mark processed
                if msg_id:
                    self.inbox_store.mark_status(msg_id, "processed")

                # Send ack
                self._send_ack(msg)

                self._total_processed += 1

            except Exception as e:
                self.logger.error(f"Dispatch error: {e}")
                if msg_id:
                    self.inbox_store.mark_status(msg_id, "failed")

    def stop(self):
        """Signal the daemon to stop."""
        self.running = False

    def status(self) -> dict:
        """Get daemon status."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "running": self.running,
            "agent": self.client._sender_id,
            "uptime_seconds": round(uptime, 1),
            "cycles": self._cycles,
            "total_processed": self._total_processed,
            "handlers": self.router.registered_types,
            "router_stats": self.router.stats,
            "inbox_count": self.inbox_store.count(),
            "inbox_new": self.inbox_store.count("new"),
            "outbox_count": self.outbox_store.count(),
            "peers": self.peer_manager.count(),
        }


# ── CLI ───────────────────────────────────────────────────────────

def get_daemon_pid(data_dir: str) -> int:
    """Read daemon PID from file."""
    pid_file = os.path.join(str(Path(data_dir).expanduser()), "daemon.pid")
    if os.path.exists(pid_file):
        try:
            return int(open(pid_file).read().strip())
        except (ValueError, IOError):
            pass
    return 0


def is_daemon_running(data_dir: str) -> bool:
    """Check if daemon is running."""
    pid = get_daemon_pid(data_dir)
    if not pid:
        return False
    try:
        os.kill(pid, 0)  # Signal 0 = check if process exists
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Daemon — always-on message processor"
    )
    parser.add_argument("data_dir", help="AgentFax data directory")
    parser.add_argument("command", choices=["start", "stop", "status"],
                        help="Daemon command")
    parser.add_argument("--poll", type=float, default=2.0,
                        help="Poll interval in seconds (default 2.0)")
    parser.add_argument("--background", "-b", action="store_true",
                        help="Run in background (daemonize)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose logging")

    args = parser.parse_args()
    data_dir = str(Path(args.data_dir).expanduser())

    if args.command == "status":
        if is_daemon_running(data_dir):
            pid = get_daemon_pid(data_dir)
            print(f"Daemon is RUNNING (PID: {pid})")
        else:
            print("Daemon is STOPPED")

        # Show store stats
        try:
            inbox = InboxStore(data_dir)
            outbox = OutboxStore(data_dir)
            peers = PeerManager(data_dir)
            print(f"  Inbox:  {inbox.count()} total, {inbox.count('new')} new")
            print(f"  Outbox: {outbox.count()} total")
            print(f"  Peers:  {peers.count()} known")
            inbox.close()
            outbox.close()
        except Exception:
            pass
        return

    if args.command == "stop":
        pid = get_daemon_pid(data_dir)
        if pid and is_daemon_running(data_dir):
            os.kill(pid, signal.SIGTERM)
            print(f"Daemon stopped (PID: {pid})")
        else:
            print("Daemon is not running")
        return

    if args.command == "start":
        if is_daemon_running(data_dir):
            pid = get_daemon_pid(data_dir)
            print(f"Daemon already running (PID: {pid})")
            return

        logger = setup_logging(data_dir, verbose=args.verbose)

        if args.background:
            # Fork to background
            pid = os.fork()
            if pid > 0:
                print(f"Daemon started in background (PID: {pid})")
                return
            # Child process continues
            os.setsid()

        daemon = AgentFaxDaemon(data_dir, poll_interval=args.poll)

        # Handle signals
        def signal_handler(sig, frame):
            logger.info("Received shutdown signal")
            daemon.stop()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        daemon.run()


if __name__ == "__main__":
    main()

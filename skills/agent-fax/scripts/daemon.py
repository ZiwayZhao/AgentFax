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
from task_manager import TaskManager
from executor import TaskExecutor, register_builtin_skills
from security import TrustManager
from reputation import ReputationManager
from context_manager import ContextManager
from workflow import WorkflowManager
from handlers.builtin import register_builtin_handlers
from handlers.task_handler import register_task_handlers
from handlers.context_handler import register_context_handlers
from handlers.workflow_handler import register_workflow_handlers
from handlers.skill_handler import register_skill_handlers
from handlers.session_handler import register_session_handlers
from skill_registry import PeerSkillCache
from session import SessionManager
from metering import MeteringManager

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
        self.logger = logging.getLogger("agentfax.daemon")

        # Core components
        self.client = AgentFaxClient(self.data_dir)
        self.router = MessageRouter()
        self.inbox_store = InboxStore(self.data_dir)
        self.outbox_store = OutboxStore(self.data_dir)
        self.peer_manager = PeerManager(self.data_dir)
        self.task_manager = TaskManager(self.data_dir)
        self.executor = TaskExecutor()

        # Trust & Reputation
        self.trust_manager = TrustManager(self.data_dir)
        self.reputation_manager = ReputationManager(self.data_dir)

        # Phase 6: Context Exchange
        self.context_manager = ContextManager(self.data_dir)

        # LLM-driven context projection (optional, degrades gracefully)
        try:
            from llm_projection import LLMProjectionEngine
            llm_engine = LLMProjectionEngine()
            if llm_engine.is_available:
                self.context_manager.set_llm_engine(llm_engine)
                self.logger.info("LLM projection engine enabled")
            else:
                self.logger.info("LLM projection engine unavailable, using fallback")
        except Exception as e:
            self.logger.info(f"LLM projection not loaded: {e}")

        # Skill Card cache (peer cards)
        self.peer_skill_cache = PeerSkillCache(self.data_dir)
        self.peer_manager.set_skill_cache(self.peer_skill_cache)

        # Phase 7: Workflow Orchestration
        self.workflow_manager = WorkflowManager(self.data_dir)

        # S2: Session Manager
        self.session_manager = SessionManager(self.data_dir)

        # S3: Metering Manager
        self.metering_manager = MeteringManager(self.data_dir)

        # Router context
        self.ctx = RouterContext(
            client=self.client,
            inbox_store=self.inbox_store,
            outbox_store=self.outbox_store,
            peer_manager=self.peer_manager,
            trust_manager=self.trust_manager,
            reputation_manager=self.reputation_manager,
            context_manager=self.context_manager,
            workflow_manager=self.workflow_manager,
            session_manager=self.session_manager,
            metering_manager=self.metering_manager,
        )

        # Register built-in handlers (ping/pong/discover/ack)
        register_builtin_handlers(self.router, self.data_dir)

        # Register task handlers (task_request/response/ack/cancel)
        register_task_handlers(self.router, self.task_manager, self.executor)

        # Register context handlers (context_sync/query/response)
        register_context_handlers(
            self.router, self.context_manager, self.trust_manager
        )

        # Register workflow handlers (workflow_request)
        register_workflow_handlers(
            self.router, self.workflow_manager,
            self.task_manager, self.executor
        )

        # Register skill handlers (skill_card_query/list/get/card + legacy)
        register_skill_handlers(
            self.router, self.executor, self.data_dir,
            peer_skill_cache=self.peer_skill_cache,
        )

        # Register session handlers (session_propose/accept/reject/close)
        register_session_handlers(
            self.router, self.session_manager, self.executor
        )

        # Register built-in skills (echo, reverse, word_count)
        register_builtin_skills(self.executor)

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

        ack_payload = {
            "correlation_id": corr_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        ack_corr = f"ack_{int(time.time())}"

        try:
            self.client.send(
                to_wallet=sender_wallet,
                msg_type="ack",
                payload=ack_payload,
                correlation_id=ack_corr,
            )
        except Exception as e:
            self.logger.debug(f"Failed to send ack, queuing for retry: {e}")
            self.outbox_store.record_pending(
                recipient_wallet=sender_wallet,
                msg_type="ack",
                payload=ack_payload,
                correlation_id=ack_corr,
            )

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

        pid_file = os.path.join(self.data_dir, "daemon.pid")

        try:
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
            with open(pid_file, "w") as f:
                f.write(str(os.getpid()))

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
            # Cleanup — always runs, even on early return
            if os.path.exists(pid_file):
                os.remove(pid_file)
            self.inbox_store.close()
            self.outbox_store.close()
            self.peer_skill_cache.close()
            self.session_manager.close()
            self.metering_manager.close()
            self.reputation_manager.close()
            self.context_manager.close()
            self.workflow_manager.close()
            self.logger.info("Daemon stopped.")

    def _cycle(self):
        """One poll cycle: pull messages → store → dispatch → ack → check timeouts."""
        self._cycles += 1

        # Check for timed-out tasks periodically (every 30 cycles ~ 1 min)
        if self._cycles % 30 == 0:
            timed_out = self.task_manager.check_timeouts()
            if timed_out:
                self.logger.warning(f"Tasks timed out: {timed_out}")

            # Check reputation and auto-promote/demote trust tiers
            changes = self.reputation_manager.check_and_update_tiers(
                self.trust_manager
            )
            for c in changes:
                self.logger.info(
                    f"Trust tier change: {c['peer_id']} "
                    f"{c['old']} → {c['new']}"
                )

            # Cleanup expired context items
            self.context_manager.cleanup_expired()

            # Expire stale sessions
            self.session_manager.expire_stale_sessions()

        # ── Outbox retry — resend pending messages ────────────────
        try:
            # Recover stale retrying rows (e.g. from previous crash)
            recovered = self.outbox_store.recover_stale_retrying(stale_seconds=60)
            if recovered:
                self.logger.info(f"Recovered {recovered} stale retrying messages")
            self._retry_pending_sends()
        except Exception as e:
            self.logger.error(f"Outbox retry error: {e}")

        # ── Workflow step dispatch ────────────────────────────────
        # Check running workflows and dispatch ready steps
        try:
            self._dispatch_workflow_steps()
        except Exception as e:
            self.logger.error(f"Workflow dispatch error: {e}")

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

    def _retry_pending_sends(self):
        """Retry messages that failed to send."""
        retryable = self.outbox_store.get_retryable(limit=5)
        for msg in retryable:
            row_id = msg["id"]
            try:
                result = self.client.send(
                    to_wallet=msg["recipient_wallet"],
                    msg_type=msg["msg_type"],
                    payload=msg["payload"] if isinstance(msg["payload"], dict)
                            else {},
                    correlation_id=msg.get("correlation_id"),
                )
                self.outbox_store.mark_retry_sent(row_id, result)
                self.logger.info(
                    f"Retry success: {msg['msg_type']} → {msg['recipient_wallet'][:10]}..."
                )
            except Exception as e:
                self.outbox_store.mark_retry_failed(row_id, str(e))
                self.logger.warning(
                    f"Retry failed: {msg['msg_type']} → {msg['recipient_wallet'][:10]}...: {e}"
                )

    def _dispatch_workflow_steps(self):
        """Check running workflows and dispatch ready steps."""
        running = self.workflow_manager.list_workflows(state="running")
        for wf in running:
            wf_id = wf["workflow_id"]
            ready_steps = self.workflow_manager.get_ready_steps(wf_id)

            for step in ready_steps:
                step_id = step["step_id"]
                skill = step["skill"]
                target_peer = step.get("target_peer")

                # Resolve input from previous steps
                resolved_input = self.workflow_manager.resolve_step_input(
                    wf_id, step_id
                )

                if target_peer:
                    # Remote execution: send workflow_request to peer
                    peer = self.peer_manager.get(target_peer)
                    if not peer or not peer.get("wallet"):
                        self.logger.warning(
                            f"Cannot dispatch step {step_id}: "
                            f"peer '{target_peer}' not found"
                        )
                        self.workflow_manager.fail_step(
                            wf_id, step_id,
                            f"Peer '{target_peer}' not found"
                        )
                        continue

                    # Project context for this step (S4: enforce skill privacy cap)
                    context_items = []
                    if self.context_manager:
                        peer_tier = self.trust_manager.get_trust_tier(
                            target_peer
                        )
                        # Compute skill privacy cap
                        privacy_tier_map = {"L1_PUBLIC": 1, "L2_TRUSTED": 2, "L3_PRIVATE": 3}
                        skill_def = self.executor.get_skill(skill) if self.executor.has_skill(skill) else None
                        max_priv = skill_def.max_context_privacy_tier if skill_def else "L1_PUBLIC"
                        privacy_cap = privacy_tier_map.get(max_priv, 1)
                        try:
                            context_items = self.context_manager.project_for_task(
                                skill, peer_tier,
                                max_privacy_tier=privacy_cap,
                                peer_name=target_peer,
                            )
                        except Exception as e:
                            self.logger.error(f"Context projection failed for workflow step {step_id}: {e}")
                            context_items = []

                    # Send workflow_request
                    task_id = f"wf_{wf_id}_{step_id}_{int(time.time())}"
                    corr_id = f"wf_{wf_id}_{step_id}"

                    try:
                        self.client.send(
                            to_wallet=peer["wallet"],
                            msg_type="workflow_request",
                            payload={
                                "workflow_id": wf_id,
                                "step": {
                                    "step_id": step_id,
                                    "skill": skill,
                                    "input": resolved_input,
                                    "context": context_items,
                                    "timeout_seconds": step.get(
                                        "timeout_seconds", 300
                                    ),
                                },
                                "workflow_metadata": {
                                    "initiator": self.client._sender_id,
                                },
                            },
                            correlation_id=corr_id,
                        )
                        self.workflow_manager.dispatch_step(
                            wf_id, step_id, task_id
                        )
                        self.logger.info(
                            f"Dispatched workflow step {step_id} "
                            f"to {target_peer}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to dispatch step {step_id}: {e}"
                        )
                        self.workflow_manager.fail_step(
                            wf_id, step_id, str(e)
                        )

                else:
                    # Local execution
                    self.workflow_manager.start_step(wf_id, step_id)
                    exec_result = self.executor.execute(skill, resolved_input)

                    if exec_result.get("success"):
                        newly_ready = self.workflow_manager.complete_step(
                            wf_id, step_id, exec_result.get("result", {})
                        )
                        self.logger.info(
                            f"Local step {step_id} completed. "
                            f"Newly ready: {newly_ready}"
                        )
                    else:
                        self.workflow_manager.fail_step(
                            wf_id, step_id,
                            exec_result.get("error", "execution failed")
                        )

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

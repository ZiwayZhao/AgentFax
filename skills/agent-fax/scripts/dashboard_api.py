#!/usr/bin/env python3
"""
AgentFax Dashboard API v2 — modular API handler.

Extends the original dashboard.py DashboardAPI with endpoints for S0-S5 features:
trust, reputation, sessions, skill cards, workflows, metering, context policy.

All reads go through per-request manager instances (no shared state, safe for
concurrent requests on ThreadingHTTPServer).
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("agentfax.dashboard_api")

# Lazy imports — only import when method is called, so missing managers
# don't crash the whole API.


class DashboardAPIv2:
    """Read/write data access for Dashboard v2."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self._config = self._load_json("config.json")
        self._identity = self._load_json("chain_identity.json")
        self._wallet = self._load_json("wallet.json").get("address", "")

    def _load_json(self, filename: str) -> dict:
        path = os.path.join(self.data_dir, filename)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}

    # ── Health + Profile ──────────────────────────────────────

    def get_health(self) -> dict:
        return {"status": "ok"}

    def get_agent_profile(self) -> dict:
        return {
            **self._config,
            **self._identity,
            "wallet": self._wallet,
        }

    # ── Stats (existing, refactored) ─────────────────────────

    def get_stats(self) -> dict:
        result = {"agent": self.get_agent_profile()}

        # Each section wrapped in try/except for resilience
        try:
            from store import InboxStore
            inbox = InboxStore(self.data_dir)
            msg_types = {}
            try:
                rows = inbox.conn.execute(
                    "SELECT msg_type, COUNT(*) FROM messages GROUP BY msg_type"
                ).fetchall()
                msg_types = {(row[0] or "unknown"): row[1] for row in rows}
            except Exception:
                pass
            result["inbox_count"] = inbox.count()
            result["message_types"] = msg_types
            inbox.close()
        except Exception:
            result.setdefault("inbox_count", 0)
            result.setdefault("message_types", {})

        try:
            from store import OutboxStore
            outbox = OutboxStore(self.data_dir)
            result["outbox_count"] = outbox.count()
            outbox.close()
        except Exception:
            result.setdefault("outbox_count", 0)

        try:
            from task_manager import TaskManager
            tasks = TaskManager(self.data_dir)
            task_states = {}
            for state in ["pending", "sent", "acked", "in_progress",
                          "completed", "failed", "cancelled", "timed_out"]:
                count = len(tasks.query(state=state))
                if count > 0:
                    task_states[state] = count
            result["task_count"] = len(tasks.query())
            result["task_states"] = task_states
            tasks.close()
        except Exception:
            result.setdefault("task_count", 0)
            result.setdefault("task_states", {})

        try:
            from peers import PeerManager
            peers = PeerManager(self.data_dir)
            result["peer_count"] = peers.count()
        except Exception:
            result.setdefault("peer_count", 0)

        return result

    # ── Messages ──────────────────────────────────────────────

    def get_messages(self, msg_type=None, sender=None, status=None,
                     limit=50, offset=0) -> dict:
        all_msgs = []

        try:
            from store import InboxStore
            inbox = InboxStore(self.data_dir)
            in_msgs = inbox.query(
                msg_type=msg_type, sender_id=sender,
                status=status, limit=200,
            )
            for m in in_msgs:
                m["direction"] = "in"
                m["timestamp"] = m.get("received_at", "")
            all_msgs.extend(in_msgs)
            inbox.close()
        except Exception:
            pass

        try:
            from store import OutboxStore
            outbox = OutboxStore(self.data_dir)
            out_msgs = outbox.query(status=status, limit=200)
            for m in out_msgs:
                m["direction"] = "out"
                m["timestamp"] = m.get("sent_at", "")
            if msg_type:
                out_msgs = [m for m in out_msgs if m.get("msg_type") == msg_type]
            all_msgs.extend(out_msgs)
            outbox.close()
        except Exception:
            pass

        all_msgs.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        return {"messages": all_msgs[offset:offset + limit], "total": len(all_msgs)}

    # ── Tasks ─────────────────────────────────────────────────

    def get_tasks(self, state=None, role=None, skill=None, limit=50) -> dict:
        from task_manager import TaskManager
        tasks = TaskManager(self.data_dir)
        try:
            return {"tasks": tasks.query(state=state, role=role, skill=skill, limit=limit)}
        finally:
            tasks.close()

    # ── Peers ─────────────────────────────────────────────────

    def get_peers(self) -> list:
        from peers import PeerManager
        peers = PeerManager(self.data_dir)
        all_peers = peers.list_all()
        online_peers = peers.get_online()
        online_names = {p["name"] for p in online_peers}

        # Get trust tiers
        trust_tiers = {}
        try:
            from security import TrustManager
            tm = TrustManager(self.data_dir)
            for name in all_peers:
                trust_tiers[name] = tm.get_trust_tier(name)
        except Exception:
            pass

        peer_list = []
        for name, data in all_peers.items():
            peer_list.append({
                "name": name,
                "wallet": data.get("wallet", ""),
                "last_seen": data.get("last_seen", ""),
                "is_online": name in online_names,
                "trust_tier": trust_tiers.get(name, 0),
                "latency_ms": data.get("avg_latency_ms", data.get("latency_ms")),
                "skills": data.get("skills", []),
            })

        return peer_list

    def get_peer_reputation(self, peer_id: str) -> dict:
        try:
            from reputation import ReputationManager
            rm = ReputationManager(self.data_dir)
            return rm.get_reputation(peer_id)
        except Exception as e:
            return {"error": str(e)}

    def set_peer_trust(self, peer_id: str, tier: int) -> dict:
        try:
            from security import TrustManager
            tm = TrustManager(self.data_dir)
            tm.set_trust_override(peer_id, tier)
            return {"ok": True, "peer_id": peer_id, "trust_tier": tier}
        except Exception as e:
            return {"error": str(e)}

    # ── Sessions ──────────────────────────────────────────────

    def get_sessions(self, state=None) -> list:
        try:
            from session import SessionManager
            sm = SessionManager(self.data_dir)
            sessions = sm.list_sessions(state=state) if state else sm.list_sessions()
            sm.close()
            return sessions
        except Exception as e:
            logger.error(f"get_sessions error: {e}")
            return []

    def get_session(self, session_id: str) -> dict:
        try:
            from session import SessionManager
            sm = SessionManager(self.data_dir)
            s = sm.get_session(session_id)
            sm.close()
            return s or {"error": "not found"}
        except Exception as e:
            return {"error": str(e)}

    # ── Skill Cards ───────────────────────────────────────────

    def get_skill_cards(self) -> list:
        try:
            from skill_registry import PeerSkillCache
            cache = PeerSkillCache(self.data_dir)
            cards = cache.list_all_cards()
            cache.close()
            return cards
        except Exception as e:
            logger.error(f"get_skill_cards error: {e}")
            return []

    # ── Workflows ─────────────────────────────────────────────

    def get_workflows(self, state=None) -> list:
        try:
            from workflow import WorkflowManager
            wm = WorkflowManager(self.data_dir)
            workflows = wm.list_workflows(state=state) if state else wm.list_workflows()
            wm.close()
            return workflows
        except Exception as e:
            logger.error(f"get_workflows error: {e}")
            return []

    def get_workflow(self, workflow_id: str) -> dict:
        try:
            from workflow import WorkflowManager
            wm = WorkflowManager(self.data_dir)
            wf = wm.get_workflow(workflow_id)
            wm.close()
            return wf or {"error": "not found"}
        except Exception as e:
            return {"error": str(e)}

    # ── Metering ──────────────────────────────────────────────

    def get_metering_receipts(self, limit=50) -> list:
        try:
            from metering import MeteringManager
            mm = MeteringManager(self.data_dir)
            receipts = mm.list_receipts(limit=limit)
            mm.close()
            return receipts
        except Exception as e:
            logger.error(f"get_metering_receipts error: {e}")
            return []

    # ── Activity (enhanced) ───────────────────────────────────

    def get_activity(self, limit=20) -> list:
        events = []

        try:
            from store import InboxStore
            inbox = InboxStore(self.data_dir)
            for m in inbox.query(limit=limit):
                events.append({
                    "id": m.get("xmtp_id", ""),
                    "type": "message",
                    "title": f"Received {m.get('msg_type', '?')} from {m.get('sender_id', '?')}",
                    "description": "",
                    "timestamp": m.get("received_at", ""),
                    "peer": m.get("sender_id"),
                })
            inbox.close()
        except Exception:
            pass

        try:
            from store import OutboxStore
            outbox = OutboxStore(self.data_dir)
            for m in outbox.query(limit=limit):
                w = m.get("recipient_wallet", "?")
                short = f"{w[:6]}...{w[-4:]}" if len(w) > 12 else w
                events.append({
                    "id": str(m.get("id", "")),
                    "type": "message",
                    "title": f"Sent {m.get('msg_type', '?')} to {short}",
                    "description": "",
                    "timestamp": m.get("sent_at", ""),
                })
            outbox.close()
        except Exception:
            pass

        try:
            from task_manager import TaskManager
            tasks = TaskManager(self.data_dir)
            for t in tasks.query(limit=limit):
                state = t.get("state", "?")
                skill = t.get("skill", "?")
                peer = t.get("peer_name", "?")
                dur = t.get("duration_ms")
                dur_str = f" ({dur:.0f}ms)" if dur else ""
                events.append({
                    "id": t.get("task_id", ""),
                    "type": "task",
                    "title": f"{skill} [{state}] — {peer}{dur_str}",
                    "description": "",
                    "timestamp": t.get("completed_at") or t.get("started_at") or t.get("created_at", ""),
                    "peer": peer,
                    "status": state,
                })
            tasks.close()
        except Exception:
            pass

        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[:limit]

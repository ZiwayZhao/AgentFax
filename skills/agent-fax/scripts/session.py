#!/usr/bin/env python3
"""
AgentFax Session Manager — collaboration session lifecycle.

Implements the 7-state protocol state machine:
  [none] → proposed → active → closing → completed / closed / expired / rejected

Sessions give task_requests a context: agreed skills, trust tier, privacy cap,
call limits, and TTL. Without a session, tasks run as standalone (backwards compat).

Usage:
    from session import SessionManager, SessionState

    sm = SessionManager("~/.agentfax")
    sid = sm.create_session(
        peer_id="icy",
        proposed_skills=["echo"],
        proposed_trust_tier=1,
        proposed_max_context_privacy="L1_PUBLIC",
        proposed_max_calls=10,
        ttl_seconds=3600,
    )
    sm.accept_session(sid, agreed_skills=["echo"], ...)
    sm.increment_call_count(sid)
    sm.close_session(sid)
"""

import enum
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.session")


class SessionState(enum.Enum):
    """Protocol-layer session states (7 states)."""
    PROPOSED = "proposed"
    ACTIVE = "active"
    CLOSING = "closing"
    COMPLETED = "completed"
    CLOSED = "closed"
    EXPIRED = "expired"
    REJECTED = "rejected"


# Terminal states — no further transitions allowed
TERMINAL_STATES = {
    SessionState.COMPLETED,
    SessionState.CLOSED,
    SessionState.EXPIRED,
    SessionState.REJECTED,
}

# Valid state transitions
VALID_TRANSITIONS = {
    SessionState.PROPOSED: {SessionState.ACTIVE, SessionState.REJECTED, SessionState.EXPIRED},
    SessionState.ACTIVE: {SessionState.CLOSING, SessionState.EXPIRED},
    SessionState.CLOSING: {SessionState.COMPLETED, SessionState.CLOSED},
}


class SessionManager:
    """Manages collaboration sessions with SQLite persistence."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_sessions.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                peer_id TEXT NOT NULL,
                role TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'proposed',

                -- Proposed terms (by initiator)
                proposed_skills TEXT,
                proposed_trust_tier INTEGER DEFAULT 1,
                proposed_max_context_privacy TEXT DEFAULT 'L1_PUBLIC',
                proposed_max_calls INTEGER DEFAULT 10,
                ttl_seconds INTEGER DEFAULT 3600,

                -- Agreed terms (filled on accept)
                agreed_skills TEXT,
                agreed_skill_version TEXT,
                agreed_schema_hash TEXT,
                agreed_trust_tier INTEGER,
                agreed_max_context_privacy TEXT,
                agreed_max_calls INTEGER,
                agreed_pricing_snapshot TEXT,

                -- Counters
                call_count INTEGER DEFAULT 0,
                tasks_completed INTEGER DEFAULT 0,
                tasks_failed INTEGER DEFAULT 0,
                tasks_in_flight INTEGER DEFAULT 0,

                -- Timestamps
                created_at TEXT NOT NULL,
                accepted_at TEXT,
                expires_at TEXT,
                closed_at TEXT,
                completed_at TEXT,

                -- Metadata
                close_reason TEXT,
                initiator_id TEXT,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_peer
                ON sessions(peer_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_state
                ON sessions(state);
        """)
        self.conn.commit()

    # ── Session lifecycle ────────────────────────────────────

    def create_session(
        self,
        peer_id: str,
        role: str = "initiator",
        proposed_skills: list = None,
        proposed_trust_tier: int = 1,
        proposed_max_context_privacy: str = "L1_PUBLIC",
        proposed_max_calls: int = 10,
        ttl_seconds: int = 3600,
        initiator_id: str = "",
    ) -> str:
        """Create a new session in PROPOSED state.

        Args:
            peer_id: The other party
            role: 'initiator' or 'responder'
            proposed_skills: Skills to use in this session
            proposed_trust_tier: Minimum trust tier proposed
            proposed_max_context_privacy: Max context privacy tier
            proposed_max_calls: Max number of task calls
            ttl_seconds: Session TTL
            initiator_id: Who initiated (for responder-created records)

        Returns:
            session_id
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        expires_at = datetime.fromtimestamp(
            time.time() + ttl_seconds, tz=timezone.utc
        ).isoformat()

        self.conn.execute("""
            INSERT INTO sessions
                (session_id, peer_id, role, state,
                 proposed_skills, proposed_trust_tier,
                 proposed_max_context_privacy, proposed_max_calls,
                 ttl_seconds, created_at, expires_at, initiator_id)
            VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, peer_id, role,
            json.dumps(proposed_skills or []),
            proposed_trust_tier,
            proposed_max_context_privacy,
            proposed_max_calls,
            ttl_seconds,
            now, expires_at,
            initiator_id,
        ))
        self.conn.commit()

        logger.info(
            f"Session {session_id} created: peer={peer_id}, role={role}, "
            f"skills={proposed_skills}, ttl={ttl_seconds}s"
        )
        return session_id

    def accept_session(
        self,
        session_id: str,
        agreed_skills: list = None,
        agreed_skill_version: str = "1.0.0",
        agreed_schema_hash: str = "",
        agreed_trust_tier: int = None,
        agreed_max_context_privacy: str = None,
        agreed_max_calls: int = None,
        agreed_pricing_snapshot: dict = None,
    ) -> bool:
        """Transition session from PROPOSED → ACTIVE.

        Fills in agreed terms. Returns True on success.
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"accept_session: session {session_id} not found")
            return False

        if not self._can_transition(session, SessionState.ACTIVE):
            logger.warning(
                f"accept_session: invalid transition from {session['state']}"
            )
            return False

        now = datetime.now(timezone.utc).isoformat()

        # Default agreed terms to proposed terms if not specified
        final_skills = agreed_skills or json.loads(session["proposed_skills"] or "[]")
        final_trust = agreed_trust_tier if agreed_trust_tier is not None else session["proposed_trust_tier"]
        final_privacy = agreed_max_context_privacy or session["proposed_max_context_privacy"]
        final_calls = agreed_max_calls if agreed_max_calls is not None else session["proposed_max_calls"]

        self.conn.execute("""
            UPDATE sessions SET
                state = 'active',
                agreed_skills = ?,
                agreed_skill_version = ?,
                agreed_schema_hash = ?,
                agreed_trust_tier = ?,
                agreed_max_context_privacy = ?,
                agreed_max_calls = ?,
                agreed_pricing_snapshot = ?,
                accepted_at = ?
            WHERE session_id = ?
        """, (
            json.dumps(final_skills),
            agreed_skill_version,
            agreed_schema_hash,
            final_trust,
            final_privacy,
            final_calls,
            json.dumps(agreed_pricing_snapshot or {"model": "free", "amount": 0}),
            now,
            session_id,
        ))
        self.conn.commit()

        logger.info(
            f"Session {session_id} accepted: skills={final_skills}, "
            f"trust={final_trust}, privacy={final_privacy}, max_calls={final_calls}"
        )
        return True

    def reject_session(self, session_id: str, reason: str = "") -> bool:
        """Transition session from PROPOSED → REJECTED."""
        return self._transition(session_id, SessionState.REJECTED,
                                close_reason=reason)

    def close_session(self, session_id: str, reason: str = "") -> bool:
        """Transition session from ACTIVE → CLOSING."""
        return self._transition(session_id, SessionState.CLOSING,
                                close_reason=reason)

    def complete_session(self, session_id: str) -> bool:
        """Transition session from CLOSING → COMPLETED (all tasks settled)."""
        session = self.get_session(session_id)
        if not session:
            return False
        if session["tasks_in_flight"] > 0:
            logger.warning(
                f"complete_session: {session_id} still has "
                f"{session['tasks_in_flight']} tasks in flight"
            )
            return False
        return self._transition(session_id, SessionState.COMPLETED)

    def force_close_session(self, session_id: str, reason: str = "") -> bool:
        """Force CLOSING → CLOSED (some tasks may not be settled)."""
        return self._transition(session_id, SessionState.CLOSED,
                                close_reason=reason)

    def expire_session(self, session_id: str) -> bool:
        """Transition PROPOSED or ACTIVE → EXPIRED."""
        return self._transition(session_id, SessionState.EXPIRED)

    # ── Task tracking within session ─────────────────────────

    def increment_call_count(self, session_id: str) -> bool:
        """Atomically increment call counter. Returns False if limit exceeded.

        Uses a conditional UPDATE to avoid TOCTOU race conditions.
        """
        cursor = self.conn.execute(
            "UPDATE sessions SET call_count = call_count + 1, "
            "tasks_in_flight = tasks_in_flight + 1 "
            "WHERE session_id = ? AND state = 'active' "
            "AND (agreed_max_calls IS NULL OR call_count < agreed_max_calls)",
            (session_id,),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def task_completed(self, session_id: str):
        """Record a task completion in session."""
        self.conn.execute(
            "UPDATE sessions SET tasks_completed = tasks_completed + 1, "
            "tasks_in_flight = MAX(0, tasks_in_flight - 1) "
            "WHERE session_id = ?",
            (session_id,),
        )
        self.conn.commit()
        self._check_auto_complete(session_id)

    def task_failed(self, session_id: str):
        """Record a task failure in session."""
        self.conn.execute(
            "UPDATE sessions SET tasks_failed = tasks_failed + 1, "
            "tasks_in_flight = MAX(0, tasks_in_flight - 1) "
            "WHERE session_id = ?",
            (session_id,),
        )
        self.conn.commit()
        self._check_auto_complete(session_id)

    def _check_auto_complete(self, session_id: str):
        """If session is CLOSING and no tasks in flight, auto-complete."""
        session = self.get_session(session_id)
        if (session and
            session["state"] == SessionState.CLOSING.value and
            session["tasks_in_flight"] <= 0):
            self.complete_session(session_id)

    # ── Session validation for task_request ───────────────────

    def validate_task_request(self, session_id: str, skill: str,
                              sender_id: str) -> tuple:
        """Validate a task_request against its session.

        Returns:
            (ok: bool, error_code: str, error_message: str)
        """
        session = self.get_session(session_id)
        if not session:
            return (False, "SESSION_NOT_FOUND",
                    f"Session {session_id} does not exist")

        if session["state"] != SessionState.ACTIVE.value:
            return (False, "SESSION_NOT_ACTIVE",
                    f"Session {session_id} is {session['state']}, not active")

        # Check expiry
        if session["expires_at"]:
            now = datetime.now(timezone.utc).isoformat()
            if now > session["expires_at"]:
                self.expire_session(session_id)
                return (False, "SESSION_EXPIRED",
                        f"Session {session_id} has expired")

        # Check peer matches
        if session["peer_id"] != sender_id:
            return (False, "SESSION_PEER_MISMATCH",
                    f"Session {session_id} is with {session['peer_id']}, "
                    f"not {sender_id}")

        # Check skill is in agreed list
        agreed_skills = json.loads(session["agreed_skills"] or "[]")
        if agreed_skills and skill not in agreed_skills:
            return (False, "SKILL_NOT_IN_SESSION",
                    f"Skill '{skill}' not agreed in session. "
                    f"Agreed: {agreed_skills}")

        # Check call limit
        max_calls = session["agreed_max_calls"]
        if max_calls and session["call_count"] >= max_calls:
            return (False, "CALL_LIMIT_EXCEEDED",
                    f"Session {session_id} call limit reached "
                    f"({session['call_count']}/{max_calls})")

        return (True, "", "")

    # ── Expiry management ────────────────────────────────────

    def expire_stale_sessions(self) -> int:
        """Expire sessions past their TTL. Returns count expired."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "SELECT session_id FROM sessions "
            "WHERE state IN ('proposed', 'active') "
            "AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        expired_ids = [row["session_id"] for row in cursor.fetchall()]
        for sid in expired_ids:
            self.expire_session(sid)
        if expired_ids:
            logger.info(f"Expired {len(expired_ids)} stale sessions")
        return len(expired_ids)

    # ── Queries ──────────────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get a session by ID."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_active_session(self, peer_id: str) -> Optional[dict]:
        """Get the active session with a specific peer (if any)."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE peer_id = ? AND state = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (peer_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, state: str = None, peer_id: str = None,
                      limit: int = 50) -> List[dict]:
        """List sessions with optional filters."""
        conditions = []
        params = []
        if state:
            conditions.append("state = ?")
            params.append(state)
        if peer_id:
            conditions.append("peer_id = ?")
            params.append(peer_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(
            f"SELECT * FROM sessions WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def count(self, state: str = None) -> int:
        """Count sessions."""
        if state:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE state = ?", (state,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()
        return row[0]

    # ── Internal helpers ─────────────────────────────────────

    def _can_transition(self, session: dict, target: SessionState) -> bool:
        """Check if a transition is valid."""
        current = SessionState(session["state"])
        if current in TERMINAL_STATES:
            return False
        valid = VALID_TRANSITIONS.get(current, set())
        return target in valid

    def _transition(self, session_id: str, target: SessionState,
                    close_reason: str = "") -> bool:
        """Execute a state transition."""
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"_transition: session {session_id} not found")
            return False

        if not self._can_transition(session, target):
            logger.warning(
                f"_transition: invalid {session['state']} → {target.value} "
                f"for session {session_id}"
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        updates = {"state": target.value}

        if target in TERMINAL_STATES:
            if target == SessionState.COMPLETED:
                updates["completed_at"] = now
            else:
                updates["closed_at"] = now
        if target == SessionState.CLOSING:
            updates["closed_at"] = now
        if close_reason:
            updates["close_reason"] = close_reason

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [session_id]
        self.conn.execute(
            f"UPDATE sessions SET {set_clause} WHERE session_id = ?",
            values,
        )
        self.conn.commit()

        logger.info(
            f"Session {session_id}: {session['state']} → {target.value}"
            + (f" ({close_reason})" if close_reason else "")
        )
        return True

    def close(self):
        self.conn.close()

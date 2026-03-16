#!/usr/bin/env python3
"""
AgentFax Task Manager — manages the lifecycle of delegated tasks.

Task lifecycle state machine:
    task_request → task_ack → task_progress → task_response
                 ↘ task_reject
                 ↘ task_timeout (auto, based on TTL)
                 ↘ task_cancel (sender cancels)

Usage (as task sender/requester):
    tm = TaskManager(data_dir)
    task_id = tm.create_task("summarize", {"text": "..."}, peer_wallet="0x...")
    # ... later, when response arrives:
    tm.complete_task(task_id, result={...})

Usage (as task executor/receiver):
    tm = TaskManager(data_dir)
    tm.accept_task(task_id)
    tm.update_progress(task_id, 50, "halfway done")
    tm.complete_task(task_id, result={...})
"""

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


class TaskState:
    """Task lifecycle states."""
    PENDING = "pending"           # Created, not yet sent
    SENT = "sent"                 # Sent to executor
    ACKED = "acked"              # Executor acknowledged receipt
    REJECTED = "rejected"         # Executor rejected the task
    IN_PROGRESS = "in_progress"  # Executor is working on it
    COMPLETED = "completed"       # Task finished successfully
    FAILED = "failed"            # Task failed with error
    CANCELLED = "cancelled"       # Task cancelled by requester
    TIMED_OUT = "timed_out"      # TTL exceeded


class TaskManager:
    """Manages task lifecycle with SQLite persistence."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_tasks.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                skill TEXT NOT NULL,
                input_data TEXT,
                output_data TEXT,
                role TEXT NOT NULL,
                peer_wallet TEXT,
                peer_name TEXT,
                correlation_id TEXT,
                state TEXT DEFAULT 'pending',
                progress_pct INTEGER DEFAULT 0,
                progress_text TEXT,
                error_message TEXT,
                timeout_seconds INTEGER DEFAULT 300,
                created_at TEXT,
                sent_at TEXT,
                acked_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms REAL,
                session_id TEXT,
                skill_version TEXT,
                receipt_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_state
                ON tasks(state);
            CREATE INDEX IF NOT EXISTS idx_tasks_role
                ON tasks(role);
            CREATE INDEX IF NOT EXISTS idx_tasks_correlation
                ON tasks(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_session
                ON tasks(session_id);
        """)
        self.conn.commit()
        self._migrate_s3_columns()

    def _migrate_s3_columns(self):
        """Add S3 columns to existing databases (idempotent)."""
        for col, col_type in [
            ("session_id", "TEXT"),
            ("skill_version", "TEXT"),
            ("receipt_id", "TEXT"),
        ]:
            try:
                self.conn.execute(f"SELECT {col} FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                self.conn.execute(
                    f"ALTER TABLE tasks ADD COLUMN {col} {col_type}"
                )
                self.conn.commit()

    def set_receipt_id(self, task_id: str, receipt_id: str):
        """Link a usage receipt to a task."""
        self.conn.execute(
            "UPDATE tasks SET receipt_id = ? WHERE task_id = ?",
            (receipt_id, task_id),
        )
        self.conn.commit()

    def set_session_id(self, task_id: str, session_id: str):
        """Set the session_id for a task."""
        self.conn.execute(
            "UPDATE tasks SET session_id = ? WHERE task_id = ?",
            (session_id, task_id),
        )
        self.conn.commit()

    # ── Task creation (requester side) ─────────────────────────

    def create_task(
        self,
        skill: str,
        input_data: dict,
        peer_wallet: str = None,
        peer_name: str = None,
        timeout_seconds: int = 300,
    ) -> str:
        """Create a new outgoing task request.

        Args:
            skill: Skill name to execute
            input_data: Task input data
            peer_wallet: Target executor wallet
            peer_name: Target executor name
            timeout_seconds: Task timeout

        Returns:
            Generated task_id
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        correlation_id = f"task_{int(time.time())}_{task_id[-8:]}"
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute("""
            INSERT INTO tasks
                (task_id, skill, input_data, role, peer_wallet, peer_name,
                 correlation_id, state, timeout_seconds, created_at)
            VALUES (?, ?, ?, 'requester', ?, ?, ?, 'pending', ?, ?)
        """, (
            task_id, skill, json.dumps(input_data),
            peer_wallet, peer_name,
            correlation_id, timeout_seconds, now,
        ))
        self.conn.commit()
        return task_id

    def mark_sent(self, task_id: str):
        """Mark task as sent to executor."""
        self.conn.execute(
            "UPDATE tasks SET state = 'sent', sent_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        self.conn.commit()

    # ── Task handling (executor side) ───────────────────────────

    def receive_task(
        self,
        task_id: str,
        skill: str,
        input_data: dict,
        peer_wallet: str,
        peer_name: str = None,
        correlation_id: str = None,
        timeout_seconds: int = 300,
    ) -> bool:
        """Record an incoming task request (executor side).

        Returns:
            True if this is a new task, False if duplicate (already exists).
        """
        now = datetime.now(timezone.utc).isoformat()

        # Check for duplicate
        existing = self.conn.execute(
            "SELECT task_id FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if existing:
            return False

        self.conn.execute("""
            INSERT INTO tasks
                (task_id, skill, input_data, role, peer_wallet, peer_name,
                 correlation_id, state, timeout_seconds, created_at)
            VALUES (?, ?, ?, 'executor', ?, ?, ?, 'pending', ?, ?)
        """, (
            task_id, skill, json.dumps(input_data),
            peer_wallet, peer_name,
            correlation_id, timeout_seconds, now,
        ))
        self.conn.commit()
        return True

    def accept_task(self, task_id: str):
        """Accept a task (executor side) — send ack."""
        self.conn.execute(
            "UPDATE tasks SET state = 'acked', acked_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        self.conn.commit()

    def reject_task(self, task_id: str, reason: str = ""):
        """Reject a task (executor side)."""
        self.conn.execute(
            "UPDATE tasks SET state = 'rejected', error_message = ? WHERE task_id = ?",
            (reason, task_id),
        )
        self.conn.commit()

    def start_task(self, task_id: str):
        """Mark task as in progress (executor side)."""
        self.conn.execute(
            "UPDATE tasks SET state = 'in_progress', started_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        self.conn.commit()

    def update_progress(self, task_id: str, percent: int, text: str = ""):
        """Update task progress (executor side)."""
        self.conn.execute(
            "UPDATE tasks SET progress_pct = ?, progress_text = ? WHERE task_id = ?",
            (percent, text, task_id),
        )
        self.conn.commit()

    # ── Completion (both sides) ────────────────────────────────

    def complete_task(self, task_id: str, result: dict = None):
        """Mark task as completed with result."""
        now = datetime.now(timezone.utc).isoformat()

        # Calculate duration
        task = self.get_task(task_id)
        duration_ms = None
        if task and task.get("started_at"):
            try:
                start = datetime.fromisoformat(task["started_at"])
                duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            except (ValueError, TypeError):
                pass

        self.conn.execute(
            "UPDATE tasks SET state = 'completed', output_data = ?, "
            "completed_at = ?, duration_ms = ?, progress_pct = 100 "
            "WHERE task_id = ?",
            (json.dumps(result) if result else None, now, duration_ms, task_id),
        )
        self.conn.commit()

    def fail_task(self, task_id: str, error: str):
        """Mark task as failed."""
        self.conn.execute(
            "UPDATE tasks SET state = 'failed', error_message = ?, "
            "completed_at = ? WHERE task_id = ?",
            (error, datetime.now(timezone.utc).isoformat(), task_id),
        )
        self.conn.commit()

    def cancel_task(self, task_id: str):
        """Cancel a task (requester side)."""
        self.conn.execute(
            "UPDATE tasks SET state = 'cancelled', completed_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        self.conn.commit()

    # ── Queries ────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[dict]:
        """Get a task by ID."""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_correlation(self, correlation_id: str) -> Optional[dict]:
        """Get a task by correlation_id."""
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE correlation_id = ?", (correlation_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def query(
        self,
        state: str = None,
        role: str = None,
        skill: str = None,
        limit: int = 50,
    ) -> List[dict]:
        """Query tasks with optional filters."""
        conditions = []
        params = []

        if state:
            conditions.append("state = ?")
            params.append(state)
        if role:
            conditions.append("role = ?")
            params.append(role)
        if skill:
            conditions.append("skill = ?")
            params.append(skill)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def check_timeouts(self) -> List[str]:
        """Find and mark timed-out tasks.

        Returns list of timed-out task IDs.
        """
        active_states = (
            TaskState.PENDING, TaskState.SENT,
            TaskState.ACKED, TaskState.IN_PROGRESS,
        )
        placeholders = ",".join("?" for _ in active_states)

        rows = self.conn.execute(
            f"SELECT task_id, created_at, timeout_seconds FROM tasks "
            f"WHERE state IN ({placeholders})",
            active_states,
        ).fetchall()

        timed_out = []
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                created = datetime.fromisoformat(row["created_at"])
                timeout = row["timeout_seconds"] or 300
                if (now - created).total_seconds() > timeout:
                    self.conn.execute(
                        "UPDATE tasks SET state = 'timed_out', "
                        "completed_at = ? WHERE task_id = ?",
                        (now.isoformat(), row["task_id"]),
                    )
                    timed_out.append(row["task_id"])
            except (ValueError, TypeError):
                pass

        if timed_out:
            self.conn.commit()
        return timed_out

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for field in ("input_data", "output_data"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    def close(self):
        self.conn.close()

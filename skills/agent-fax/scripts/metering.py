#!/usr/bin/env python3
"""
AgentFax Metering — usage receipt generation and storage.

Every task execution produces a UsageReceipt that records:
- Who called what skill, when, how long, how much data
- Session context (if any)
- Pricing snapshot at time of call

Receipts are immutable once created — append-only ledger.

Usage:
    from metering import MeteringManager

    mm = MeteringManager("~/.agentfax")
    receipt_id = mm.create_receipt(
        session_id="sess_abc",
        task_id="task_123",
        caller="icy",
        provider="ziway",
        skill_name="data_analysis",
        skill_version="1.0.0",
        status="completed",
        started_at="...",
        completed_at="...",
        duration_ms=1200,
        input_size_bytes=512,
        output_size_bytes=1024,
        pricing_model="free",
        amount=0,
    )
    receipt = mm.get_receipt(receipt_id)
    summary = mm.get_session_summary("sess_abc")
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.metering")


class MeteringManager:
    """Immutable usage receipt ledger with SQLite persistence."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_metering.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS usage_receipts (
                receipt_id TEXT PRIMARY KEY,
                session_id TEXT,
                task_id TEXT NOT NULL,
                caller TEXT NOT NULL,
                provider TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                skill_version TEXT,
                status TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER,
                input_size_bytes INTEGER,
                output_size_bytes INTEGER,
                pricing_model TEXT DEFAULT 'free',
                amount REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_receipts_session
                ON usage_receipts(session_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_task
                ON usage_receipts(task_id);
            CREATE INDEX IF NOT EXISTS idx_receipts_caller
                ON usage_receipts(caller);
            CREATE INDEX IF NOT EXISTS idx_receipts_provider
                ON usage_receipts(provider);
            CREATE INDEX IF NOT EXISTS idx_receipts_skill
                ON usage_receipts(skill_name);
        """)
        self.conn.commit()

    # ── Receipt creation ──────────────────────────────────────

    def create_receipt(
        self,
        task_id: str,
        caller: str,
        provider: str,
        skill_name: str,
        status: str,
        session_id: str = None,
        skill_version: str = None,
        started_at: str = None,
        completed_at: str = None,
        duration_ms: int = None,
        input_size_bytes: int = None,
        output_size_bytes: int = None,
        pricing_model: str = "free",
        amount: float = 0,
        currency: str = "USD",
    ) -> str:
        """Create an immutable usage receipt.

        Returns:
            receipt_id
        """
        receipt_id = f"rcpt_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute("""
            INSERT INTO usage_receipts
                (receipt_id, session_id, task_id, caller, provider,
                 skill_name, skill_version, status,
                 started_at, completed_at, duration_ms,
                 input_size_bytes, output_size_bytes,
                 pricing_model, amount, currency, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            receipt_id, session_id, task_id, caller, provider,
            skill_name, skill_version, status,
            started_at, completed_at, duration_ms,
            input_size_bytes, output_size_bytes,
            pricing_model, amount, currency, now,
        ))
        self.conn.commit()

        logger.info(
            f"Receipt {receipt_id}: {caller}→{provider} "
            f"skill={skill_name} status={status} "
            f"duration={duration_ms}ms amount={amount}"
        )
        return receipt_id

    # ── Queries ───────────────────────────────────────────────

    def get_receipt(self, receipt_id: str) -> Optional[dict]:
        """Get a receipt by ID."""
        row = self.conn.execute(
            "SELECT * FROM usage_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_by_task(self, task_id: str) -> Optional[dict]:
        """Get receipt for a specific task."""
        row = self.conn.execute(
            "SELECT * FROM usage_receipts WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_receipts(
        self,
        session_id: str = None,
        caller: str = None,
        provider: str = None,
        skill_name: str = None,
        status: str = None,
        limit: int = 50,
    ) -> List[dict]:
        """List receipts with optional filters."""
        conditions = []
        params = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if caller:
            conditions.append("caller = ?")
            params.append(caller)
        if provider:
            conditions.append("provider = ?")
            params.append(provider)
        if skill_name:
            conditions.append("skill_name = ?")
            params.append(skill_name)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(
            f"SELECT * FROM usage_receipts WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_session_summary(self, session_id: str) -> dict:
        """Get aggregated usage summary for a session.

        Returns:
            {total_calls, completed, failed, total_duration_ms,
             total_amount, skills_used}
        """
        row = self.conn.execute("""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(COALESCE(duration_ms, 0)) as total_duration_ms,
                SUM(COALESCE(amount, 0)) as total_amount,
                SUM(COALESCE(input_size_bytes, 0)) as total_input_bytes,
                SUM(COALESCE(output_size_bytes, 0)) as total_output_bytes
            FROM usage_receipts WHERE session_id = ?
        """, (session_id,)).fetchone()

        skills_row = self.conn.execute(
            "SELECT DISTINCT skill_name FROM usage_receipts "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchall()

        return {
            "session_id": session_id,
            "total_calls": row["total_calls"] or 0,
            "completed": row["completed"] or 0,
            "failed": row["failed"] or 0,
            "total_duration_ms": row["total_duration_ms"] or 0,
            "total_amount": row["total_amount"] or 0,
            "total_input_bytes": row["total_input_bytes"] or 0,
            "total_output_bytes": row["total_output_bytes"] or 0,
            "skills_used": [r["skill_name"] for r in skills_row],
        }

    def get_peer_summary(self, peer_id: str, role: str = "caller") -> dict:
        """Get aggregated usage summary for a peer.

        Args:
            peer_id: The peer identifier
            role: 'caller' or 'provider' — which side of the interaction
        """
        col = "caller" if role == "caller" else "provider"
        row = self.conn.execute(f"""
            SELECT
                COUNT(*) as total_calls,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(COALESCE(duration_ms, 0)) as total_duration_ms,
                SUM(COALESCE(amount, 0)) as total_amount
            FROM usage_receipts WHERE {col} = ?
        """, (peer_id,)).fetchone()

        return {
            "peer_id": peer_id,
            "role": role,
            "total_calls": row["total_calls"] or 0,
            "completed": row["completed"] or 0,
            "failed": row["failed"] or 0,
            "total_duration_ms": row["total_duration_ms"] or 0,
            "total_amount": row["total_amount"] or 0,
        }

    def count(self, status: str = None) -> int:
        """Count receipts."""
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM usage_receipts WHERE status = ?",
                (status,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM usage_receipts"
            ).fetchone()
        return row[0]

    def close(self):
        self.conn.close()

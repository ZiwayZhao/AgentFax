#!/usr/bin/env python3
"""
AgentFax Persistent Store — SQLite-backed inbox/outbox.

Replaces the bridge's in-memory buffer with durable storage.
Messages survive bridge restarts and can be queried by type, sender, status.

Usage:
    from store import InboxStore, OutboxStore

    inbox = InboxStore("~/.agentfax")
    inbox.save(message_dict)
    new_msgs = inbox.query(status="new")
    inbox.mark_processed(msg_id)
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


class InboxStore:
    """Persistent storage for received AgentFax messages."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_inbox.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender_inbox_id TEXT,
                sender_id TEXT,
                conversation_id TEXT,
                content_type TEXT DEFAULT 'text',
                raw_content TEXT,
                msg_type TEXT,
                payload TEXT,
                correlation_id TEXT,
                sent_at TEXT,
                received_at TEXT,
                status TEXT DEFAULT 'new',
                processed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_status
                ON messages(status);
            CREATE INDEX IF NOT EXISTS idx_messages_msg_type
                ON messages(msg_type);
            CREATE INDEX IF NOT EXISTS idx_messages_sender_id
                ON messages(sender_id);
            CREATE INDEX IF NOT EXISTS idx_messages_received_at
                ON messages(received_at);
        """)
        self.conn.commit()

    def save(self, msg: dict) -> bool:
        """Save a parsed AgentFax message to the store.

        Args:
            msg: Parsed message dict (from AgentFaxClient.receive())

        Returns:
            True if saved (new), False if duplicate
        """
        msg_id = msg.get("_xmtp_id") or f"local_{datetime.now(timezone.utc).timestamp()}"

        # Check for duplicates
        existing = self.conn.execute(
            "SELECT id FROM messages WHERE id = ?", (msg_id,)
        ).fetchone()
        if existing:
            return False

        self.conn.execute("""
            INSERT INTO messages
                (id, sender_inbox_id, sender_id, conversation_id,
                 content_type, raw_content, msg_type, payload,
                 correlation_id, sent_at, received_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        """, (
            msg_id,
            msg.get("_xmtp_sender"),
            msg.get("sender_id"),
            msg.get("_xmtp_conversation_id"),
            msg.get("payload", {}).get("content_type", "text"),
            json.dumps(msg),
            msg.get("type"),
            json.dumps(msg.get("payload", {})),
            msg.get("correlation_id"),
            msg.get("_xmtp_sent_at"),
            msg.get("_xmtp_received_at") or datetime.now(timezone.utc).isoformat(),
        ))
        self.conn.commit()
        return True

    def query(
        self,
        status: str = None,
        msg_type: str = None,
        sender_id: str = None,
        since: str = None,
        limit: int = 100,
    ) -> List[dict]:
        """Query stored messages with optional filters.

        Args:
            status: Filter by status (new, processing, processed, failed)
            msg_type: Filter by AgentFax message type
            sender_id: Filter by sender agent name
            since: ISO timestamp — only messages after this time
            limit: Max results (default 100)

        Returns:
            List of message dicts
        """
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if msg_type:
            conditions.append("msg_type = ?")
            params.append(msg_type)
        if sender_id:
            conditions.append("sender_id = ?")
            params.append(sender_id)
        if since:
            conditions.append("received_at > ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        rows = self.conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY received_at DESC LIMIT ?",
            params,
        ).fetchall()

        return [self._row_to_dict(row) for row in rows]

    def mark_status(self, msg_id: str, status: str):
        """Update message status."""
        now = datetime.now(timezone.utc).isoformat()
        processed_at = now if status in ("processed", "failed") else None
        self.conn.execute(
            "UPDATE messages SET status = ?, processed_at = ? WHERE id = ?",
            (status, processed_at, msg_id),
        )
        self.conn.commit()

    def mark_processed(self, msg_id: str):
        """Mark message as processed."""
        self.mark_status(msg_id, "processed")

    def count(self, status: str = None) -> int:
        """Count messages, optionally filtered by status."""
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM messages WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0]

    def get_by_correlation(self, correlation_id: str) -> List[dict]:
        """Find messages by correlation_id (for request/response tracking)."""
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE correlation_id = ? ORDER BY received_at",
            (correlation_id,),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a message dict."""
        d = dict(row)
        # Parse JSON fields back
        if d.get("raw_content"):
            try:
                d["raw_content"] = json.loads(d["raw_content"])
            except (json.JSONDecodeError, TypeError):
                pass
        if d.get("payload"):
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d

    def close(self):
        self.conn.close()


class OutboxStore:
    """Persistent storage for sent AgentFax messages."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_outbox.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_wallet TEXT NOT NULL,
                msg_type TEXT,
                payload TEXT,
                correlation_id TEXT,
                message_id TEXT,
                conversation_id TEXT,
                sent_at TEXT,
                status TEXT DEFAULT 'sent',
                acked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_sent_status
                ON sent_messages(status);
            CREATE INDEX IF NOT EXISTS idx_sent_correlation
                ON sent_messages(correlation_id);
        """)
        self.conn.commit()

    def record(
        self,
        recipient_wallet: str,
        msg_type: str,
        payload: dict,
        bridge_response: dict,
        correlation_id: str = None,
    ):
        """Record a sent message.

        Args:
            recipient_wallet: Recipient's wallet address
            msg_type: AgentFax message type
            payload: Message payload
            bridge_response: Response from bridge /send endpoint
            correlation_id: Correlation ID for tracking
        """
        self.conn.execute("""
            INSERT INTO sent_messages
                (recipient_wallet, msg_type, payload, correlation_id,
                 message_id, conversation_id, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'sent')
        """, (
            recipient_wallet,
            msg_type,
            json.dumps(payload),
            correlation_id,
            bridge_response.get("messageId"),
            bridge_response.get("conversationId"),
            datetime.now(timezone.utc).isoformat(),
        ))
        self.conn.commit()

    def mark_acked(self, correlation_id: str):
        """Mark a sent message as acknowledged."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE sent_messages SET status = 'acked', acked_at = ? "
            "WHERE correlation_id = ? AND status = 'sent'",
            (now, correlation_id),
        )
        self.conn.commit()

    def query(self, status: str = None, limit: int = 50) -> List[dict]:
        """Query sent messages."""
        if status:
            rows = self.conn.execute(
                "SELECT * FROM sent_messages WHERE status = ? "
                "ORDER BY sent_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM sent_messages ORDER BY sent_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results

    def count(self, status: str = None) -> int:
        """Count sent messages."""
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sent_messages WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM sent_messages").fetchone()
        return row[0]

    def close(self):
        self.conn.close()

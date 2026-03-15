#!/usr/bin/env python3
"""
AgentFax Context Manager — privacy-tiered context sharing between agents.

Manages local context items (skills, preferences, project info) and
controls what gets shared with which peers based on privacy tiers
and trust levels.

Privacy Tiers:
  L1 (Public)   — shareable with any KNOWN+ peer
  L2 (Trusted)  — only INTERNAL+ peers
  L3 (Private)  — never shared, local only

Core concept: Task-Relevant Projection
  Instead of sharing all context or nothing, project only the items
  relevant to the current task, filtered by the peer's trust level.

Usage:
    from context_manager import ContextManager, PrivacyTier

    cm = ContextManager("~/.agentfax")
    cm.add_context("tech_stack", ["python", "nodejs"], category="skill",
                    privacy_tier=PrivacyTier.L1_PUBLIC)
    cm.add_context("api_key", "sk-xxx", category="credential",
                    privacy_tier=PrivacyTier.L3_PRIVATE)

    # Project for a task — only returns L1+L2 for INTERNAL peers
    items = cm.project_for_task("code_review", peer_trust_tier=2)
"""

import enum
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.context")


class PrivacyTier(enum.IntEnum):
    """Privacy levels for context items."""
    L1_PUBLIC = 1     # Shareable with KNOWN+ peers
    L2_TRUSTED = 2    # Only INTERNAL+ peers
    L3_PRIVATE = 3    # Never shared


# ── Category → task type relevance mapping ────────────────────────
# Used by project_for_task to select relevant categories

TASK_CATEGORY_MAP = {
    # task_type → relevant context categories
    "code_review": ["skill", "project", "preference"],
    "security_analysis": ["skill", "project"],
    "summarize": ["skill", "preference"],
    "echo": ["skill"],
    "reverse": ["skill"],
    "word_count": ["skill"],
    "default": ["skill", "general"],
}


class ContextManager:
    """Manages local context items and peer context exchange."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_context.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"ContextManager initialized: {db_path}")

    def _init_schema(self):
        """Create context tables."""
        cur = self.conn.cursor()

        # Local context items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS context_items (
                context_id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                privacy_tier INTEGER DEFAULT 2,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                version INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_category
            ON context_items(category)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ctx_privacy
            ON context_items(privacy_tier)
        """)

        # Context received from peers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS peer_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_id TEXT NOT NULL,
                context_id TEXT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT,
                received_at TEXT NOT NULL,
                correlation_id TEXT,
                expires_at TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pctx_peer
            ON peer_context(peer_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pctx_category
            ON peer_context(category)
        """)

        # Projection log (what was shared with whom)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS context_projections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                peer_id TEXT,
                context_ids TEXT,
                projected_at TEXT NOT NULL,
                trust_tier_at_time INTEGER
            )
        """)

        self.conn.commit()

    # ── Local context CRUD ────────────────────────────────────────

    def add_context(
        self,
        key: str,
        value: Any,
        category: str = "general",
        privacy_tier: int = PrivacyTier.L2_TRUSTED,
        tags: List[str] = None,
        expires_at: str = None,
    ) -> str:
        """Add a context item. Returns context_id."""
        context_id = f"ctx_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        value_json = json.dumps(value) if not isinstance(value, str) else value
        tags_json = json.dumps(tags) if tags else None

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO context_items
                (context_id, key, value, category, privacy_tier, tags,
                 created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (context_id, key, value_json, category, privacy_tier,
              tags_json, now, now, expires_at))
        self.conn.commit()

        logger.debug(f"Added context: {key} (L{privacy_tier}, {category})")
        return context_id

    def get_context(self, context_id: str) -> Optional[dict]:
        """Get a single context item by ID."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM context_items WHERE context_id = ?",
            (context_id,)
        )
        row = cur.fetchone()
        if row:
            return self._row_to_dict(row)
        return None

    def query_context(
        self,
        category: str = None,
        tags: List[str] = None,
        privacy_max: int = None,
        include_expired: bool = False,
    ) -> List[dict]:
        """Query local context items with filters."""
        conditions = []
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if privacy_max is not None:
            conditions.append("privacy_tier <= ?")
            params.append(privacy_max)

        if not include_expired:
            now = datetime.now(timezone.utc).isoformat()
            conditions.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(now)

        where = " AND ".join(conditions) if conditions else "1=1"
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT * FROM context_items WHERE {where} ORDER BY updated_at DESC",
            params
        )
        items = [self._row_to_dict(row) for row in cur.fetchall()]

        # Tag filtering (post-query since tags is JSON)
        if tags:
            filtered = []
            for item in items:
                item_tags = item.get("tags") or []
                if any(t in item_tags for t in tags):
                    filtered.append(item)
            items = filtered

        return items

    def update_context(self, context_id: str, value: Any):
        """Update a context item's value."""
        now = datetime.now(timezone.utc).isoformat()
        value_json = json.dumps(value) if not isinstance(value, str) else value

        cur = self.conn.cursor()
        cur.execute("""
            UPDATE context_items SET value = ?, updated_at = ?, version = version + 1
            WHERE context_id = ?
        """, (value_json, now, context_id))
        self.conn.commit()

    def delete_context(self, context_id: str):
        """Delete a context item."""
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM context_items WHERE context_id = ?",
            (context_id,)
        )
        self.conn.commit()

    # ── Task-relevant projection ──────────────────────────────────

    def project_for_task(
        self,
        task_type: str,
        peer_trust_tier: int,
        max_items: int = 10,
    ) -> List[dict]:
        """Auto-select context items relevant to a task, filtered by peer's trust.

        This is the core innovation: instead of sharing everything or nothing,
        project only what's relevant and permitted.

        Rules:
        - peer KNOWN (tier 1) → only L1_PUBLIC items
        - peer INTERNAL (tier 2+) → L1 + L2 items
        - L3_PRIVATE items → NEVER projected, regardless of tier
        - Items matched by task_type → relevant categories from TASK_CATEGORY_MAP
        """
        # Clean up expired items first to prevent stale data leakage
        self.cleanup_expired()

        # Determine max privacy tier based on peer trust
        if peer_trust_tier >= 2:  # INTERNAL+
            privacy_max = PrivacyTier.L2_TRUSTED
        elif peer_trust_tier >= 1:  # KNOWN
            privacy_max = PrivacyTier.L1_PUBLIC
        else:
            return []  # UNTRUSTED gets nothing

        # Get relevant categories for this task type
        categories = TASK_CATEGORY_MAP.get(
            task_type,
            TASK_CATEGORY_MAP["default"]
        )

        # Query matching items
        all_items = []
        for cat in categories:
            items = self.query_context(category=cat, privacy_max=privacy_max)
            all_items.extend(items)

        # Deduplicate and limit
        seen_ids = set()
        result = []
        for item in all_items:
            if item["context_id"] not in seen_ids:
                seen_ids.add(item["context_id"])
                # Strip internal fields for projection
                result.append({
                    "context_id": item["context_id"],
                    "key": item["key"],
                    "value": item["value"],
                    "category": item["category"],
                })
                if len(result) >= max_items:
                    break

        return result

    # ── Peer context (received from others) ───────────────────────

    def store_peer_context(
        self,
        peer_id: str,
        context_items: List[dict],
        correlation_id: str = None,
    ) -> int:
        """Store context received from a peer. Returns count stored."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        count = 0

        for item in context_items:
            cur.execute("""
                INSERT INTO peer_context
                    (peer_id, context_id, key, value, category,
                     received_at, correlation_id, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                peer_id,
                item.get("context_id"),
                item.get("key", "unknown"),
                json.dumps(item.get("value", "")),
                item.get("category"),
                now,
                correlation_id,
                item.get("expires_at"),
            ))
            count += 1

        self.conn.commit()
        logger.debug(f"Stored {count} context items from {peer_id}")
        return count

    def query_peer_context(
        self,
        peer_id: str = None,
        category: str = None,
    ) -> List[dict]:
        """Query context received from peers."""
        conditions = []
        params = []

        if peer_id:
            conditions.append("peer_id = ?")
            params.append(peer_id)
        if category:
            conditions.append("category = ?")
            params.append(category)

        # Exclude expired
        now = datetime.now(timezone.utc).isoformat()
        conditions.append("(expires_at IS NULL OR expires_at > ?)")
        params.append(now)

        where = " AND ".join(conditions) if conditions else "1=1"
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT * FROM peer_context WHERE {where} "
            "ORDER BY received_at DESC",
            params
        )

        results = []
        for row in cur.fetchall():
            d = dict(row)
            try:
                d["value"] = json.loads(d["value"])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(d)
        return results

    # ── Protocol helpers ──────────────────────────────────────────

    def build_context_sync_payload(
        self,
        peer_trust_tier: int,
        categories: List[str] = None,
        since: str = None,
    ) -> dict:
        """Build payload for a context_sync message.

        Respects privacy tiers based on peer's trust level.
        """
        # Determine privacy max
        if peer_trust_tier >= 2:
            privacy_max = PrivacyTier.L2_TRUSTED
        elif peer_trust_tier >= 1:
            privacy_max = PrivacyTier.L1_PUBLIC
        else:
            return {"items": [], "sync_mode": "incremental"}

        items = []
        if categories:
            for cat in categories:
                items.extend(self.query_context(
                    category=cat, privacy_max=privacy_max
                ))
        else:
            items = self.query_context(privacy_max=privacy_max)

        # Filter by since timestamp if incremental
        if since:
            items = [i for i in items if i.get("updated_at", "") > since]

        # Strip internal fields
        clean_items = []
        for item in items:
            clean_items.append({
                "context_id": item["context_id"],
                "key": item["key"],
                "value": item["value"],
                "category": item["category"],
                "updated_at": item["updated_at"],
                "expires_at": item.get("expires_at"),
            })

        return {
            "items": clean_items,
            "sync_mode": "incremental" if since else "full",
            "since": since,
        }

    def build_context_response_payload(
        self,
        query: dict,
        peer_trust_tier: int,
    ) -> dict:
        """Build response payload for a context_query.

        Filters by categories, tags, and peer trust level.
        """
        categories = query.get("categories")
        tags = query.get("tags")
        max_items = query.get("max_items", 10)

        # Determine privacy max
        if peer_trust_tier >= 2:
            privacy_max = PrivacyTier.L2_TRUSTED
        elif peer_trust_tier >= 1:
            privacy_max = PrivacyTier.L1_PUBLIC
        else:
            return {"items": [], "filtered_by_trust": 0}

        # Count total items vs what we can share (for transparency)
        all_items = self.query_context()
        total_count = len(all_items)

        # Get filtered items
        items = []
        if categories:
            for cat in categories:
                items.extend(self.query_context(
                    category=cat, tags=tags, privacy_max=privacy_max
                ))
        else:
            items = self.query_context(tags=tags, privacy_max=privacy_max)

        # Deduplicate
        seen = set()
        unique = []
        for item in items:
            if item["context_id"] not in seen:
                seen.add(item["context_id"])
                unique.append({
                    "context_id": item["context_id"],
                    "key": item["key"],
                    "value": item["value"],
                    "category": item["category"],
                })
                if len(unique) >= max_items:
                    break

        filtered_count = total_count - len(unique)

        return {
            "items": unique,
            "total_available": total_count,
            "filtered_by_trust": filtered_count,
        }

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup_expired(self) -> int:
        """Remove expired context items and peer context. Returns count removed."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        cur.execute(
            "DELETE FROM context_items WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        count1 = cur.rowcount

        cur.execute(
            "DELETE FROM peer_context WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        count2 = cur.rowcount

        self.conn.commit()
        total = count1 + count2
        if total > 0:
            logger.info(f"Cleaned up {total} expired context items")
        return total

    def close(self):
        """Close the database connection."""
        self.conn.close()

    # ── Internal helpers ──────────────────────────────────────────

    def _row_to_dict(self, row) -> dict:
        """Convert a sqlite3.Row to a dict with parsed JSON fields."""
        d = dict(row)
        # Parse JSON value
        try:
            d["value"] = json.loads(d["value"])
        except (json.JSONDecodeError, TypeError):
            pass
        # Parse JSON tags
        if d.get("tags"):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d

#!/usr/bin/env python3
"""
AgentFax Reputation Manager — tracks peer reliability and auto-adjusts trust tiers.

Records every interaction (task completion, failure, ping response, etc.)
in SQLite and maintains aggregated reputation summaries per peer.
Periodically checks if peers should be promoted or demoted.

Usage:
    from reputation import ReputationManager

    rm = ReputationManager("~/.agentfax")
    rm.record_interaction("icy", "task_completed", True, latency_ms=42.5)

    rep = rm.get_reputation("icy")
    # → {peer_id: "icy", success_rate: 0.95, total: 20, ...}

    changes = rm.check_and_update_tiers(security_manager)
    # → [{"peer_id": "icy", "old": "KNOWN", "new": "INTERNAL"}]
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("agentfax.reputation")


# ── Promotion/demotion thresholds ──────────────────────────────────

TIER_THRESHOLDS = {
    # tier: (min_interactions, min_success_rate)
    0: (0, 0.0),       # UNTRUSTED: default
    1: (3, 0.5),        # KNOWN: >= 3 interactions, >= 50% success
    2: (10, 0.8),       # INTERNAL: >= 10 interactions, >= 80% success
    # PRIVILEGED (3): manual only, never auto-promoted
}


class ReputationManager:
    """SQLite-backed peer reputation tracking with auto trust tier promotion/demotion."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_reputation.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"ReputationManager initialized: {db_path}")

    def _init_schema(self):
        """Create reputation tables."""
        cur = self.conn.cursor()

        # Individual interaction log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS peer_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_id TEXT NOT NULL,
                interaction_type TEXT NOT NULL,
                success INTEGER NOT NULL,
                latency_ms REAL,
                metadata TEXT,
                recorded_at TEXT NOT NULL,
                weight REAL DEFAULT 1.0
            )
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pi_peer_id
            ON peer_interactions(peer_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_pi_recorded_at
            ON peer_interactions(recorded_at)
        """)

        # Aggregated summary (materialized view)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS peer_reputation_summary (
                peer_id TEXT PRIMARY KEY,
                total_interactions INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0.0,
                avg_latency_ms REAL,
                first_seen TEXT,
                last_seen TEXT,
                current_tier INTEGER DEFAULT 0
            )
        """)

        self.conn.commit()

    def record_interaction(
        self,
        peer_id: str,
        interaction_type: str,
        success: bool,
        latency_ms: float = None,
        metadata: dict = None,
    ):
        """Record a single interaction with a peer.

        Args:
            peer_id: The peer's agent name
            interaction_type: e.g. "task_completed", "task_failed", "ping_response"
            success: Whether the interaction was successful
            latency_ms: Optional latency measurement
            metadata: Optional extra data (JSON-serializable)
        """
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata) if metadata else None

        cur = self.conn.cursor()

        # Insert interaction record
        cur.execute("""
            INSERT INTO peer_interactions
                (peer_id, interaction_type, success, latency_ms, metadata, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (peer_id, interaction_type, int(success), latency_ms, meta_json, now))

        # Update summary (upsert)
        cur.execute("""
            INSERT INTO peer_reputation_summary (peer_id, total_interactions, successes,
                failures, success_rate, avg_latency_ms, first_seen, last_seen)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(peer_id) DO UPDATE SET
                total_interactions = total_interactions + 1,
                successes = successes + ?,
                failures = failures + ?,
                success_rate = CAST(successes + ? AS REAL) /
                    (total_interactions + 1),
                avg_latency_ms = CASE
                    WHEN ? IS NOT NULL THEN
                        COALESCE((avg_latency_ms * total_interactions + ?) /
                            (total_interactions + 1), ?)
                    ELSE avg_latency_ms
                END,
                last_seen = ?
        """, (
            peer_id,
            int(success), int(not success),
            1.0 if success else 0.0,
            latency_ms, now, now,
            # ON CONFLICT params
            int(success), int(not success),
            int(success),
            latency_ms, latency_ms, latency_ms,
            now,
        ))

        self.conn.commit()

        logger.debug(
            f"Recorded interaction: {peer_id} {interaction_type} "
            f"{'ok' if success else 'fail'}"
            + (f" {latency_ms:.0f}ms" if latency_ms else "")
        )

    def get_reputation(self, peer_id: str) -> Optional[dict]:
        """Get aggregated reputation stats for a peer."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM peer_reputation_summary WHERE peer_id = ?",
            (peer_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)

    def get_all_reputations(self) -> List[dict]:
        """Get all peer reputation summaries."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM peer_reputation_summary ORDER BY success_rate DESC"
        )
        return [dict(row) for row in cur.fetchall()]

    def suggest_trust_tier(self, peer_id: str) -> int:
        """Calculate suggested trust tier based on reputation metrics.

        Rules:
        - < 3 interactions → UNTRUSTED (0)
        - >= 3 interactions & success_rate >= 0.5 → KNOWN (1)
        - >= 10 interactions & success_rate >= 0.8 → INTERNAL (2)
        - PRIVILEGED (3) → manual only, never auto-promoted
        """
        rep = self.get_reputation(peer_id)
        if not rep:
            return 0  # UNTRUSTED

        total = rep["total_interactions"]
        rate = rep["success_rate"]

        # Check from highest eligible tier downward
        for tier in sorted(TIER_THRESHOLDS.keys(), reverse=True):
            min_interactions, min_rate = TIER_THRESHOLDS[tier]
            if total >= min_interactions and rate >= min_rate:
                return tier

        return 0

    def check_and_update_tiers(self, security_manager) -> List[dict]:
        """Check all peers and auto-promote/demote based on reputation.

        Does NOT touch PRIVILEGED (3) or SYSTEM (4) tiers — those are manual only.

        Args:
            security_manager: SecurityManager instance to update tiers on

        Returns:
            List of changes: [{"peer_id": "icy", "old": "KNOWN", "new": "INTERNAL"}]
        """
        from security import TrustTier

        changes = []
        all_reps = self.get_all_reputations()

        for rep in all_reps:
            peer_id = rep["peer_id"]
            current_tier = security_manager.get_trust_tier(peer_id)

            # Skip manually managed tiers
            if current_tier >= TrustTier.PRIVILEGED:
                continue

            suggested = self.suggest_trust_tier(peer_id)

            if suggested != current_tier:
                old_name = TrustTier(current_tier).name
                new_name = TrustTier(suggested).name

                security_manager.set_trust_tier(peer_id, TrustTier(suggested))

                # Update summary table
                cur = self.conn.cursor()
                cur.execute(
                    "UPDATE peer_reputation_summary SET current_tier = ? "
                    "WHERE peer_id = ?",
                    (suggested, peer_id)
                )
                self.conn.commit()

                changes.append({
                    "peer_id": peer_id,
                    "old": old_name,
                    "new": new_name,
                    "total": rep["total_interactions"],
                    "success_rate": rep["success_rate"],
                })

                logger.info(
                    f"Trust tier changed: {peer_id} {old_name} → {new_name} "
                    f"(interactions={rep['total_interactions']}, "
                    f"rate={rep['success_rate']:.2f})"
                )

        return changes

    def get_interaction_history(
        self, peer_id: str, limit: int = 50
    ) -> List[dict]:
        """Get recent interaction history for a peer."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM peer_interactions
            WHERE peer_id = ?
            ORDER BY recorded_at DESC
            LIMIT ?
        """, (peer_id, limit))
        return [dict(row) for row in cur.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()

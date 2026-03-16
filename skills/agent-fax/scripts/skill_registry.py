#!/usr/bin/env python3
"""
AgentFax Skill Registry — Skill Card data model + peer card cache.

A Skill Card is the public interface of a skill: schema, trust requirements,
pricing, timeouts, capabilities. Implementation code never leaves the provider.

Usage:
    from skill_registry import SkillCard, PeerSkillCache

    # Build a card from a local SkillDefinition
    card = SkillCard.from_skill_def(skill_def, agent_id="ziway", wallet="0x...")

    # Cache peer cards
    cache = PeerSkillCache("~/.agentfax")
    cache.store_cards("icy", [card1.to_dict(), card2.to_dict()])
    cards = cache.get_cards("icy")
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.skill_registry")


class SkillCard:
    """Immutable public interface of a skill — never contains implementation."""

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        skill_name: str,
        description: str = "",
        skill_version: str = "1.0.0",
        provider_agent_id: str = "",
        provider_wallet: str = "",
        provider_display_name: str = "",
        input_schema: dict = None,
        output_schema: dict = None,
        min_trust_tier: int = 1,
        max_context_privacy_tier: str = "L1_PUBLIC",
        pricing_model: str = "free",
        pricing_amount: float = 0,
        pricing_currency: str = "USD",
        pricing_cost_unit: str = "per_call",
        task_ttl_seconds: int = 300,
        ack_timeout_seconds: int = 5,
        idempotent: bool = False,
        streaming_progress: bool = False,
        supports_cancel: bool = True,
        session_required: bool = False,
        tags: list = None,
        examples: list = None,
        updated_at: str = None,
    ):
        self.skill_name = skill_name
        self.description = description or f"Skill: {skill_name}"
        self.skill_version = skill_version
        self.provider_agent_id = provider_agent_id
        self.provider_wallet = provider_wallet
        self.provider_display_name = provider_display_name
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}
        self.min_trust_tier = min_trust_tier
        self.max_context_privacy_tier = max_context_privacy_tier
        self.pricing_model = pricing_model
        self.pricing_amount = pricing_amount
        self.pricing_currency = pricing_currency
        self.pricing_cost_unit = pricing_cost_unit
        self.task_ttl_seconds = task_ttl_seconds
        self.ack_timeout_seconds = ack_timeout_seconds
        self.idempotent = idempotent
        self.streaming_progress = streaming_progress
        self.supports_cancel = supports_cancel
        self.session_required = session_required
        self.tags = tags or []
        self.examples = examples or []
        self.updated_at = updated_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Serialize to the canonical Skill Card JSON format."""
        d = {
            "schema_version": self.SCHEMA_VERSION,
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "description": self.description,
            "provider": {
                "agent_id": self.provider_agent_id,
                "wallet": self.provider_wallet,
                "display_name": self.provider_display_name,
            },
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "trust_requirements": {
                "min_trust_tier": self.min_trust_tier,
                "max_context_privacy_tier": self.max_context_privacy_tier,
            },
            "pricing": {
                "model": self.pricing_model,
                "amount": self.pricing_amount,
                "currency": self.pricing_currency,
                "cost_unit": self.pricing_cost_unit,
            },
            "timeouts": {
                "task_ttl_seconds": self.task_ttl_seconds,
                "ack_timeout_seconds": self.ack_timeout_seconds,
            },
            "capabilities": {
                "idempotent": self.idempotent,
                "streaming_progress": self.streaming_progress,
                "supports_cancel": self.supports_cancel,
                "session_required": self.session_required,
            },
            "tags": self.tags,
            "examples": self.examples,
            "schema_hash": self.schema_hash,
            "updated_at": self.updated_at,
        }
        return d

    @property
    def schema_hash(self) -> str:
        """SHA-256 hash of input+output schemas for version pinning."""
        content = json.dumps(
            {"input": self.input_schema, "output": self.output_schema},
            sort_keys=True,
        )
        return "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]

    @classmethod
    def from_dict(cls, d: dict) -> "SkillCard":
        """Deserialize from Skill Card JSON."""
        provider = d.get("provider", {})
        trust = d.get("trust_requirements", {})
        pricing = d.get("pricing", {})
        timeouts = d.get("timeouts", {})
        caps = d.get("capabilities", {})

        return cls(
            skill_name=d.get("skill_name", ""),
            description=d.get("description", ""),
            skill_version=d.get("skill_version", "1.0.0"),
            provider_agent_id=provider.get("agent_id", ""),
            provider_wallet=provider.get("wallet", ""),
            provider_display_name=provider.get("display_name", ""),
            input_schema=d.get("input_schema", {}),
            output_schema=d.get("output_schema", {}),
            min_trust_tier=trust.get("min_trust_tier", 1),
            max_context_privacy_tier=trust.get("max_context_privacy_tier", "L1_PUBLIC"),
            pricing_model=pricing.get("model", "free"),
            pricing_amount=pricing.get("amount", 0),
            pricing_currency=pricing.get("currency", "USD"),
            pricing_cost_unit=pricing.get("cost_unit", "per_call"),
            task_ttl_seconds=timeouts.get("task_ttl_seconds", 300),
            ack_timeout_seconds=timeouts.get("ack_timeout_seconds", 5),
            idempotent=caps.get("idempotent", False),
            streaming_progress=caps.get("streaming_progress", False),
            supports_cancel=caps.get("supports_cancel", True),
            session_required=caps.get("session_required", False),
            tags=d.get("tags", []),
            examples=d.get("examples", []),
            updated_at=d.get("updated_at"),
        )

    @classmethod
    def from_skill_def(cls, skill_def, agent_id: str = "", wallet: str = "",
                       display_name: str = "") -> "SkillCard":
        """Build a SkillCard from a local SkillDefinition (executor.py)."""
        return cls(
            skill_name=skill_def.name,
            description=skill_def.description,
            provider_agent_id=agent_id,
            provider_wallet=wallet,
            provider_display_name=display_name or agent_id,
            input_schema=skill_def.input_schema,
            output_schema=skill_def.output_schema,
            min_trust_tier=skill_def.min_trust_tier,
            max_context_privacy_tier=skill_def.max_context_privacy_tier,
        )


class PeerSkillCache:
    """SQLite cache of Skill Cards received from peers.

    Separate from peers.json — this stores the full structured card data
    and supports queries by skill name, tag, peer, trust tier.
    """

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_skill_cards.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS peer_skill_cards (
                peer_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                skill_version TEXT DEFAULT '1.0.0',
                card_json TEXT NOT NULL,
                schema_hash TEXT,
                min_trust_tier INTEGER DEFAULT 1,
                tags TEXT,
                received_at TEXT NOT NULL,
                expires_at TEXT,
                PRIMARY KEY (peer_id, skill_name)
            );

            CREATE INDEX IF NOT EXISTS idx_psc_skill
                ON peer_skill_cards(skill_name);
            CREATE INDEX IF NOT EXISTS idx_psc_peer
                ON peer_skill_cards(peer_id);
        """)
        self.conn.commit()

    def store_cards(self, peer_id: str, cards: List[dict],
                    ttl_seconds: int = 3600) -> int:
        """Store or update Skill Cards from a peer.

        Args:
            peer_id: The peer who published these cards
            cards: List of Skill Card dicts
            ttl_seconds: Cache TTL (default 1 hour)

        Returns:
            Number of cards stored
        """
        now = datetime.now(timezone.utc).isoformat()
        expires = datetime.fromtimestamp(
            time.time() + ttl_seconds, tz=timezone.utc
        ).isoformat()
        count = 0

        for card_dict in cards:
            skill_name = card_dict.get("skill_name") or card_dict.get("name", "")
            if not skill_name:
                continue

            skill_version = card_dict.get("skill_version", "1.0.0")
            schema_hash = card_dict.get("schema_hash", "")
            trust = card_dict.get("trust_requirements", {})
            min_tier = trust.get("min_trust_tier",
                                 card_dict.get("min_trust_tier", 1))
            tags = json.dumps(card_dict.get("tags", []))

            self.conn.execute("""
                INSERT OR REPLACE INTO peer_skill_cards
                    (peer_id, skill_name, skill_version, card_json,
                     schema_hash, min_trust_tier, tags, received_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                peer_id, skill_name, skill_version,
                json.dumps(card_dict), schema_hash,
                min_tier, tags, now, expires,
            ))
            count += 1

        self.conn.commit()
        logger.info(f"Cached {count} skill cards from {peer_id}")
        return count

    def get_cards(self, peer_id: str, include_expired: bool = False) -> List[dict]:
        """Get all cached Skill Cards from a peer."""
        now = datetime.now(timezone.utc).isoformat()
        if include_expired:
            rows = self.conn.execute(
                "SELECT card_json FROM peer_skill_cards WHERE peer_id = ?",
                (peer_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT card_json FROM peer_skill_cards "
                "WHERE peer_id = ? AND (expires_at IS NULL OR expires_at > ?)",
                (peer_id, now),
            ).fetchall()

        return [json.loads(row["card_json"]) for row in rows]

    def get_card(self, peer_id: str, skill_name: str) -> Optional[dict]:
        """Get a specific Skill Card from a peer."""
        now = datetime.now(timezone.utc).isoformat()
        row = self.conn.execute(
            "SELECT card_json FROM peer_skill_cards "
            "WHERE peer_id = ? AND skill_name = ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (peer_id, skill_name, now),
        ).fetchone()
        return json.loads(row["card_json"]) if row else None

    def find_by_skill(self, skill_name: str) -> List[dict]:
        """Find all peers that offer a specific skill.

        Returns list of dicts with peer_id and card data.
        """
        now = datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            "SELECT peer_id, card_json FROM peer_skill_cards "
            "WHERE skill_name = ? AND (expires_at IS NULL OR expires_at > ?)",
            (skill_name, now),
        ).fetchall()
        return [
            {"peer_id": row["peer_id"], "card": json.loads(row["card_json"])}
            for row in rows
        ]

    def find_by_tag(self, tag: str) -> List[dict]:
        """Find all cached cards that have a specific tag."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self.conn.execute(
            "SELECT peer_id, card_json, tags FROM peer_skill_cards "
            "WHERE (expires_at IS NULL OR expires_at > ?)",
            (now,),
        ).fetchall()
        results = []
        for row in rows:
            tags = json.loads(row["tags"] or "[]")
            if tag in tags:
                results.append({
                    "peer_id": row["peer_id"],
                    "card": json.loads(row["card_json"]),
                })
        return results

    def list_all_peers(self) -> List[str]:
        """List all peers with cached cards."""
        rows = self.conn.execute(
            "SELECT DISTINCT peer_id FROM peer_skill_cards"
        ).fetchall()
        return [row["peer_id"] for row in rows]

    def count(self, peer_id: str = None) -> int:
        """Count cached cards."""
        if peer_id:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM peer_skill_cards WHERE peer_id = ?",
                (peer_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM peer_skill_cards"
            ).fetchone()
        return row[0]

    def evict_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "DELETE FROM peer_skill_cards WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        self.conn.commit()
        return cursor.rowcount

    def clear_peer(self, peer_id: str):
        """Remove all cached cards for a peer."""
        self.conn.execute(
            "DELETE FROM peer_skill_cards WHERE peer_id = ?", (peer_id,)
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

#!/usr/bin/env python3
"""
AgentFax Peer Manager — address book for known agents.

Tracks:
- Wallet addresses and agent IDs
- Last seen timestamps
- Capabilities/skills
- Round-trip latency
- Online/offline status

Usage:
    from peers import PeerManager

    peers = PeerManager("~/.agentfax")
    peers.update_seen("icy", wallet="0x320E...")
    peers.update_capabilities("icy", wallet="0x320E...", capabilities={...})
    online = peers.get_online(timeout_seconds=120)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


class PeerManager:
    """Manages the local address book of known peers."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self.peers_file = os.path.join(self.data_dir, "peers.json")
        self._peers: Dict[str, dict] = {}
        self._load()

    def _load(self):
        """Load peers from disk."""
        if os.path.exists(self.peers_file):
            try:
                with open(self.peers_file) as f:
                    self._peers = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._peers = {}

    def _save(self):
        """Persist peers to disk."""
        with open(self.peers_file, "w") as f:
            json.dump(self._peers, f, indent=2, ensure_ascii=False)

    def update_seen(
        self,
        sender_id: str,
        wallet: str = None,
        latency_ms: float = None,
    ):
        """Update a peer's last-seen timestamp.

        Args:
            sender_id: Agent name/ID
            wallet: Wallet address (optional, set if known)
            latency_ms: Round-trip latency in milliseconds
        """
        if sender_id not in self._peers:
            self._peers[sender_id] = {}

        peer = self._peers[sender_id]
        peer["last_seen"] = datetime.now(timezone.utc).isoformat()
        peer["seen_count"] = peer.get("seen_count", 0) + 1

        if wallet:
            peer["wallet"] = wallet.lower()
        if latency_ms is not None:
            peer["latency_ms"] = round(latency_ms, 1)
            # Track average latency
            prev_avg = peer.get("avg_latency_ms", latency_ms)
            count = peer.get("latency_samples", 0)
            peer["avg_latency_ms"] = round(
                (prev_avg * count + latency_ms) / (count + 1), 1
            )
            peer["latency_samples"] = count + 1

        self._save()

    def update_capabilities(
        self,
        sender_id: str,
        wallet: str = None,
        capabilities: dict = None,
    ):
        """Update a peer's capability manifest.

        Args:
            sender_id: Agent name/ID
            wallet: Wallet address
            capabilities: Full capabilities dict from discover response
        """
        if sender_id not in self._peers:
            self._peers[sender_id] = {}

        peer = self._peers[sender_id]
        if wallet:
            peer["wallet"] = wallet.lower()
        if capabilities:
            peer["capabilities"] = capabilities
            peer["skills"] = [
                s.get("skill_name") or s.get("name")
                for s in capabilities.get("skills", [])
                if s.get("skill_name") or s.get("name")
            ]
            peer["capabilities_updated"] = datetime.now(timezone.utc).isoformat()

        self._save()

    def get(self, sender_id: str) -> Optional[dict]:
        """Get peer info by name."""
        return self._peers.get(sender_id)

    def get_by_wallet(self, wallet: str) -> Optional[dict]:
        """Get peer info by wallet address."""
        wallet_lower = wallet.lower()
        for name, peer in self._peers.items():
            if peer.get("wallet") == wallet_lower:
                return {**peer, "name": name}
        return None

    def find_by_skill(self, skill_name: str) -> List[dict]:
        """Find peers that have a specific skill.

        Args:
            skill_name: Name of the skill to search for

        Returns:
            List of peer dicts that have this skill
        """
        results = []
        for name, peer in self._peers.items():
            skills = peer.get("skills", [])
            if skill_name in skills:
                results.append({**peer, "name": name})
        return results

    def get_online(self, timeout_seconds: int = 120) -> List[dict]:
        """Get peers that were seen recently.

        Args:
            timeout_seconds: Consider offline if not seen within this time

        Returns:
            List of online peer dicts
        """
        now = datetime.now(timezone.utc)
        results = []
        for name, peer in self._peers.items():
            last_seen = peer.get("last_seen")
            if last_seen:
                try:
                    ts = datetime.fromisoformat(last_seen)
                    age = (now - ts).total_seconds()
                    if age <= timeout_seconds:
                        results.append({**peer, "name": name, "age_seconds": age})
                except (ValueError, TypeError):
                    pass
        return sorted(results, key=lambda p: p.get("age_seconds", 999))

    def list_all(self) -> Dict[str, dict]:
        """List all known peers."""
        return dict(self._peers)

    def remove(self, sender_id: str):
        """Remove a peer from the address book."""
        if sender_id in self._peers:
            del self._peers[sender_id]
            self._save()

    def set_skill_cache(self, skill_cache):
        """Attach a PeerSkillCache for rich skill queries.

        Args:
            skill_cache: PeerSkillCache instance
        """
        self._skill_cache = skill_cache

    def get_skill_cards(self, sender_id: str) -> list:
        """Get cached Skill Cards for a peer (requires skill_cache)."""
        cache = getattr(self, "_skill_cache", None)
        if cache:
            return cache.get_cards(sender_id)
        return []

    def find_by_skill_card(self, skill_name: str) -> list:
        """Find peers that offer a specific skill via Skill Card cache.

        Returns list of dicts with peer_id, card, and peer info.
        """
        cache = getattr(self, "_skill_cache", None)
        if not cache:
            return self.find_by_skill(skill_name)

        results = []
        for entry in cache.find_by_skill(skill_name):
            peer_id = entry["peer_id"]
            peer_info = self._peers.get(peer_id, {})
            results.append({
                **peer_info,
                "name": peer_id,
                "card": entry["card"],
            })
        return results

    def count(self) -> int:
        """Number of known peers."""
        return len(self._peers)

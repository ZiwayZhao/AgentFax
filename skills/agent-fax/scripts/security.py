#!/usr/bin/env python3
"""
AgentFax Trust Manager — local trust tiers for peer relationships.

In a decentralized system (XMTP + ERC-8004), security is handled at the
protocol layer:
  - Message authenticity → XMTP MLS encryption + wallet signatures
  - Replay protection → XMTP message dedup
  - Identity verification → ERC-8004 on-chain registry

This module handles the APPLICATION-LEVEL concern: how much do I trust
this specific peer? This determines what context I'm willing to share
and what task types I'll accept from them.

Usage:
    from security import TrustManager, TrustTier

    tm = TrustManager("~/.agentfax")
    tier = tm.get_trust_tier("icy")
    tm.set_trust_override("icy", TrustTier.INTERNAL)
"""

import enum
import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("agentfax.trust")


class TrustTier(enum.IntEnum):
    """Trust levels for peers — local perspective only.

    Each agent independently decides how much to trust each peer.
    There is no global authority.
    """
    UNTRUSTED = 0   # Never interacted — only basic protocol (ping/discover)
    KNOWN = 1       # Has interacted — can request/accept tasks
    INTERNAL = 2    # Trusted peer — can exchange context (L1+L2)
    PRIVILEGED = 3  # Highly trusted — full collaboration access


class TrustManager:
    """Manages local trust decisions about peers.

    Trust is subjective and local — my trust in peer A is independent
    of anyone else's trust in peer A.
    """

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self._trust_overrides: Dict[str, TrustTier] = {}
        self._load_trust_overrides()

        logger.info(f"TrustManager initialized: {len(self._trust_overrides)} overrides")

    def _load_trust_overrides(self):
        """Load manual trust overrides from trust.json."""
        trust_path = os.path.join(self.data_dir, "trust.json")
        if os.path.exists(trust_path):
            try:
                with open(trust_path) as f:
                    data = json.load(f)
                for peer_id, tier_value in data.items():
                    if isinstance(tier_value, str):
                        self._trust_overrides[peer_id] = TrustTier[tier_value.upper()]
                    else:
                        self._trust_overrides[peer_id] = TrustTier(tier_value)
            except (json.JSONDecodeError, IOError, KeyError, ValueError) as e:
                logger.warning(f"Failed to load trust.json: {e}")

    def _save_trust_overrides(self):
        """Persist trust overrides to trust.json."""
        trust_path = os.path.join(self.data_dir, "trust.json")
        data = {
            peer_id: tier.name.lower()
            for peer_id, tier in self._trust_overrides.items()
        }
        try:
            with open(trust_path, "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save trust.json: {e}")

    def get_trust_tier(self, peer_id: str) -> TrustTier:
        """Get my trust level for a peer.

        Priority:
        1. Manual override (user explicitly set)
        2. Reputation-based (set by ReputationManager)
        3. Default: UNTRUSTED
        """
        return self._trust_overrides.get(peer_id, TrustTier.UNTRUSTED)

    def set_trust_tier(self, peer_id: str, tier: TrustTier):
        """Set trust tier (called by ReputationManager for auto-promotion).

        In-memory only — not persisted. Reputation-based tiers are
        recalculated on each interaction.
        """
        self._trust_overrides[peer_id] = tier
        logger.info(f"Trust updated: {peer_id} → {tier.name}")

    def set_trust_override(self, peer_id: str, tier: TrustTier):
        """Manually set and persist a trust override.

        This is the user saying "I trust/distrust this peer" explicitly.
        Overrides reputation-based tier.
        """
        self._trust_overrides[peer_id] = tier
        self._save_trust_overrides()
        logger.info(f"Trust override saved: {peer_id} → {tier.name}")

    def remove_trust_override(self, peer_id: str):
        """Remove a manual trust override, reverting to reputation-based."""
        if peer_id in self._trust_overrides:
            del self._trust_overrides[peer_id]
            self._save_trust_overrides()
            logger.info(f"Trust override removed: {peer_id}")

    @property
    def all_tiers(self) -> Dict[str, str]:
        """Return all current trust tiers."""
        return {
            peer_id: tier.name
            for peer_id, tier in self._trust_overrides.items()
        }

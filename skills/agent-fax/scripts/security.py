#!/usr/bin/env python3
"""
AgentFax Security Manager — trust tiers, message validation, rate limiting, replay detection.

Provides a middleware for the MessageRouter that validates incoming messages
before they reach handlers. Enforces:
  1. Trust-based ACL (what message types each peer can send)
  2. Rate limiting per sender
  3. Replay detection (content hash dedup)
  4. TTL validation
  5. Payload size limits

Usage:
    from security import SecurityManager, TrustTier

    sm = SecurityManager("~/.agentfax")
    router.add_middleware(sm.security_middleware)

    # Manual trust override
    sm.set_trust_override("icy", TrustTier.INTERNAL)
"""

import collections
import enum
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger("agentfax.security")


class TrustTier(enum.IntEnum):
    """Trust levels for peers, from least to most trusted."""
    UNTRUSTED = 0     # Unknown peer — only ping/discover/ack
    KNOWN = 1         # Has interacted — basic task operations
    INTERNAL = 2      # Trusted peer — full task + context + workflow
    PRIVILEGED = 3    # Admin — can modify config
    SYSTEM = 4        # Local daemon internals only


# ── ACL matrix ────────────────────────────────────────────────────

# Message types allowed at each trust tier (cumulative)
TIER_PERMISSIONS = {
    TrustTier.UNTRUSTED: {
        "ping", "pong", "discover", "capabilities", "ack", "error",
    },
    TrustTier.KNOWN: {
        "ping", "pong", "discover", "capabilities", "ack", "error",
        "task_request", "task_ack", "task_reject",
        "task_response", "task_error", "task_progress", "task_cancel",
    },
    TrustTier.INTERNAL: {
        "ping", "pong", "discover", "capabilities", "ack", "error",
        "task_request", "task_ack", "task_reject",
        "task_response", "task_error", "task_progress", "task_cancel",
        "context_sync", "context_query", "context_response",
        "workflow_request",
        "broadcast", "attachment_received",
    },
    TrustTier.PRIVILEGED: None,  # None = allow all
    TrustTier.SYSTEM: None,
}

# Message types exempt from rate limiting (high-frequency protocol messages)
RATE_LIMIT_EXEMPT = {"ping", "pong", "ack", "error"}


class SecurityManager:
    """Validates messages, enforces trust tiers, rate limits, and replay detection."""

    def __init__(self, data_dir: str, config: dict = None):
        self.data_dir = str(Path(data_dir).expanduser())
        self.config = config or self._load_config()

        # Rate limiting: {sender_id: deque of timestamps}
        self._rate_windows: Dict[str, collections.deque] = {}

        # Replay detection: ordered dict as LRU cache
        self._seen_hashes: collections.OrderedDict = collections.OrderedDict()
        self._seen_max = 10000

        # Trust overrides (manual)
        self._trust_overrides: Dict[str, TrustTier] = {}
        self._load_trust_overrides()

        # Configurable limits
        self.max_payload_bytes = self.config.get("max_payload_bytes", 65536)  # 64KB
        self.rate_limit_per_minute = self.config.get("rate_limit_per_minute", 30)
        self.rate_limit_window = 60  # seconds
        self.min_ttl = self.config.get("min_ttl", 10)
        self.max_ttl = self.config.get("max_ttl", 86400)  # 24h

        # Stats
        self._stats = {
            "validated": 0,
            "blocked_ttl": 0,
            "blocked_replay": 0,
            "blocked_rate": 0,
            "blocked_size": 0,
            "blocked_permission": 0,
        }

        logger.info(
            f"SecurityManager initialized: "
            f"rate_limit={self.rate_limit_per_minute}/min, "
            f"max_payload={self.max_payload_bytes}B, "
            f"overrides={len(self._trust_overrides)}"
        )

    def _load_config(self) -> dict:
        """Load security config from data_dir/security.json if exists."""
        config_path = os.path.join(self.data_dir, "security.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load security.json: {e}")
        return {}

    def _load_trust_overrides(self):
        """Load manual trust overrides from security.json."""
        overrides = self.config.get("trust_overrides", {})
        for peer_id, tier_value in overrides.items():
            try:
                if isinstance(tier_value, str):
                    self._trust_overrides[peer_id] = TrustTier[tier_value.upper()]
                else:
                    self._trust_overrides[peer_id] = TrustTier(tier_value)
            except (KeyError, ValueError):
                logger.warning(f"Invalid trust override for {peer_id}: {tier_value}")

    def _save_trust_overrides(self):
        """Persist trust overrides to security.json."""
        self.config["trust_overrides"] = {
            peer_id: tier.name.lower()
            for peer_id, tier in self._trust_overrides.items()
        }
        config_path = os.path.join(self.data_dir, "security.json")
        try:
            with open(config_path, "w") as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save security.json: {e}")

    # ── Trust tier management ─────────────────────────────────────

    def get_trust_tier(self, sender_id: str, sender_wallet: str = None) -> TrustTier:
        """Get the trust tier for a peer.

        Priority:
        1. Manual override (from security.json)
        2. Reputation-based tier (set by ReputationManager)
        3. Default: UNTRUSTED
        """
        # Check overrides first (by name, then by wallet)
        if sender_id in self._trust_overrides:
            return self._trust_overrides[sender_id]
        if sender_wallet and sender_wallet in self._trust_overrides:
            return self._trust_overrides[sender_wallet]

        return TrustTier.UNTRUSTED

    def set_trust_tier(self, peer_id: str, tier: TrustTier):
        """Set trust tier for a peer (used by ReputationManager for auto-promotion).

        This does NOT persist — it's an in-memory update from reputation checks.
        """
        self._trust_overrides[peer_id] = tier
        logger.info(f"Trust tier updated: {peer_id} → {tier.name}")

    def set_trust_override(self, peer_id: str, tier: TrustTier):
        """Manually set and persist a trust override for a peer."""
        self._trust_overrides[peer_id] = tier
        self._save_trust_overrides()
        logger.info(f"Trust override saved: {peer_id} → {tier.name}")

    # ── Message validation ────────────────────────────────────────

    def validate_message(self, msg: dict) -> Tuple[bool, str]:
        """Validate an incoming message for security.

        Returns:
            (True, "ok") if valid
            (False, reason) if blocked
        """
        self._stats["validated"] += 1

        # 1. TTL bounds check
        ttl = msg.get("ttl", 3600)
        if ttl < self.min_ttl:
            self._stats["blocked_ttl"] += 1
            return False, f"TTL too low: {ttl} < {self.min_ttl}"
        if ttl > self.max_ttl:
            self._stats["blocked_ttl"] += 1
            return False, f"TTL too high: {ttl} > {self.max_ttl}"

        # 2. TTL expiry check
        timestamp_str = msg.get("timestamp")
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age > ttl:
                    self._stats["blocked_ttl"] += 1
                    return False, f"Message expired: age={age:.0f}s > ttl={ttl}s"
                if age < -60:  # Allow 60s clock skew
                    self._stats["blocked_ttl"] += 1
                    return False, f"Message from future: age={age:.0f}s"
            except (ValueError, TypeError):
                pass  # Skip TTL check if timestamp is unparseable

        # 3. Payload size check
        payload = msg.get("payload", {})
        payload_size = len(json.dumps(payload)) if payload else 0
        if payload_size > self.max_payload_bytes:
            self._stats["blocked_size"] += 1
            return False, f"Payload too large: {payload_size}B > {self.max_payload_bytes}B"

        # 4. Replay detection
        msg_hash = self._hash_message(msg)
        if msg_hash in self._seen_hashes:
            self._stats["blocked_replay"] += 1
            return False, "Replay detected: duplicate message hash"
        self._seen_hashes[msg_hash] = True
        # Batch evict old hashes if over limit (clear 20% at once)
        if len(self._seen_hashes) > self._seen_max:
            evict_count = max(1, self._seen_max // 5)
            for _ in range(evict_count):
                if self._seen_hashes:
                    self._seen_hashes.popitem(last=False)

        # 5. Rate limiting (per sender, exempt certain types)
        msg_type = msg.get("type", "")
        if msg_type not in RATE_LIMIT_EXEMPT:
            sender_id = msg.get("sender_id", "unknown")
            if not self._check_rate_limit(sender_id):
                self._stats["blocked_rate"] += 1
                return False, f"Rate limit exceeded for {sender_id}"

        return True, "ok"

    def check_permission(
        self, sender_id: str, msg_type: str, sender_wallet: str = None
    ) -> Tuple[bool, str]:
        """Check if a sender has permission to send this message type.

        Returns:
            (True, "ok") if allowed
            (False, reason) if denied
        """
        tier = self.get_trust_tier(sender_id, sender_wallet)
        allowed = TIER_PERMISSIONS.get(tier)

        if allowed is None:
            # PRIVILEGED and SYSTEM allow everything
            return True, "ok"

        if msg_type in allowed:
            return True, "ok"

        self._stats["blocked_permission"] += 1
        return (
            False,
            f"Permission denied: {sender_id} (tier={tier.name}) "
            f"cannot send '{msg_type}'. "
            f"Required: {self._min_tier_for_type(msg_type)}"
        )

    def _min_tier_for_type(self, msg_type: str) -> str:
        """Find the minimum trust tier that allows a message type."""
        for tier in TrustTier:
            allowed = TIER_PERMISSIONS.get(tier)
            if allowed is None or msg_type in allowed:
                return tier.name
        return "UNKNOWN"

    # ── Router middleware ─────────────────────────────────────────

    def security_middleware(self, msg: dict, ctx) -> bool:
        """Router middleware function.

        Returns True to continue processing, False to block.
        Registered via router.add_middleware(sm.security_middleware).
        """
        # Validate message structure and content
        ok, reason = self.validate_message(msg)
        if not ok:
            sender = msg.get("sender_id", "?")
            logger.warning(f"[SECURITY] Blocked from {sender}: {reason}")
            return False

        # Check ACL permissions
        sender_id = msg.get("sender_id", "unknown")
        sender_wallet = msg.get("_xmtp_sender_wallet")
        msg_type = msg.get("type", "")

        ok, reason = self.check_permission(sender_id, msg_type, sender_wallet)
        if not ok:
            logger.warning(f"[SECURITY] {reason}")
            return False

        return True

    # ── Helpers ───────────────────────────────────────────────────

    def _hash_message(self, msg: dict) -> str:
        """Generate a dedup hash from message content."""
        # Hash the key fields that define message uniqueness
        key_parts = [
            msg.get("sender_id", ""),
            msg.get("type", ""),
            msg.get("timestamp", ""),
            msg.get("correlation_id", ""),
            json.dumps(msg.get("payload", {}), sort_keys=True),
        ]
        content = "|".join(key_parts)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _check_rate_limit(self, sender_id: str) -> bool:
        """Check if sender is within rate limit. Returns True if allowed."""
        now = time.time()
        window_start = now - self.rate_limit_window

        if sender_id not in self._rate_windows:
            self._rate_windows[sender_id] = collections.deque()

        window = self._rate_windows[sender_id]

        # Remove old entries
        while window and window[0] < window_start:
            window.popleft()

        # Check limit
        if len(window) >= self.rate_limit_per_minute:
            return False

        # Record this request
        window.append(now)
        return True

    @property
    def stats(self) -> dict:
        """Return security statistics."""
        return dict(self._stats)

    @property
    def trust_overrides(self) -> dict:
        """Return current trust overrides."""
        return {
            peer_id: tier.name
            for peer_id, tier in self._trust_overrides.items()
        }

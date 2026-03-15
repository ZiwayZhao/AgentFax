"""Tests for SecurityManager — trust tiers, ACL, rate limiting, replay detection."""

import json
import time
import pytest
from datetime import datetime, timezone, timedelta

from security import SecurityManager, TrustTier, TIER_PERMISSIONS


class TestTrustTiers:
    """Test trust tier management."""

    def test_default_tier_is_untrusted(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        assert sm.get_trust_tier("unknown_peer") == TrustTier.UNTRUSTED

    def test_set_trust_tier_in_memory(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("icy", TrustTier.INTERNAL)
        assert sm.get_trust_tier("icy") == TrustTier.INTERNAL

    def test_set_trust_override_persists(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_override("icy", TrustTier.KNOWN)

        # Create new instance — should load from file
        sm2 = SecurityManager(tmp_data_dir)
        assert sm2.get_trust_tier("icy") == TrustTier.KNOWN

    def test_trust_override_by_wallet(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("0xABC", TrustTier.INTERNAL)
        assert sm.get_trust_tier("unknown", sender_wallet="0xABC") == TrustTier.INTERNAL

    def test_trust_override_name_takes_priority(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("icy", TrustTier.PRIVILEGED)
        sm.set_trust_tier("0xICY", TrustTier.KNOWN)
        # Name match should take priority over wallet
        assert sm.get_trust_tier("icy", sender_wallet="0xICY") == TrustTier.PRIVILEGED

    def test_load_trust_overrides_from_config(self, tmp_data_dir):
        # Write config with string tier names
        config = {"trust_overrides": {"icy": "internal", "bad_bot": "untrusted"}}
        with open(f"{tmp_data_dir}/security.json", "w") as f:
            json.dump(config, f)

        sm = SecurityManager(tmp_data_dir)
        assert sm.get_trust_tier("icy") == TrustTier.INTERNAL
        assert sm.get_trust_tier("bad_bot") == TrustTier.UNTRUSTED


class TestACL:
    """Test permission checking per trust tier."""

    def test_untrusted_can_ping(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        ok, _ = sm.check_permission("stranger", "ping")
        assert ok is True

    def test_untrusted_cannot_task_request(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        ok, reason = sm.check_permission("stranger", "task_request")
        assert ok is False
        assert "Permission denied" in reason

    def test_known_can_task_request(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("peer_a", TrustTier.KNOWN)
        ok, _ = sm.check_permission("peer_a", "task_request")
        assert ok is True

    def test_known_cannot_context_sync(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("peer_a", TrustTier.KNOWN)
        ok, _ = sm.check_permission("peer_a", "context_sync")
        assert ok is False

    def test_internal_can_context_sync(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("peer_a", TrustTier.INTERNAL)
        ok, _ = sm.check_permission("peer_a", "context_sync")
        assert ok is True

    def test_internal_can_workflow_request(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("peer_a", TrustTier.INTERNAL)
        ok, _ = sm.check_permission("peer_a", "workflow_request")
        assert ok is True

    def test_privileged_allows_everything(self, tmp_data_dir):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("admin", TrustTier.PRIVILEGED)
        ok, _ = sm.check_permission("admin", "any_random_type")
        assert ok is True

    def test_all_tier_permissions_are_cumulative(self, tmp_data_dir):
        """Higher tiers should have all lower tier permissions."""
        for tier in [TrustTier.KNOWN, TrustTier.INTERNAL]:
            allowed = TIER_PERMISSIONS[tier]
            for lower_tier_val in range(tier):
                lower_allowed = TIER_PERMISSIONS[TrustTier(lower_tier_val)]
                if lower_allowed is not None:
                    assert lower_allowed.issubset(allowed), \
                        f"{TrustTier(lower_tier_val).name} permissions not in {tier.name}"


class TestMessageValidation:
    """Test validate_message checks."""

    def test_valid_message_passes(self, tmp_data_dir, sample_message):
        sm = SecurityManager(tmp_data_dir)
        ok, reason = sm.validate_message(sample_message)
        assert ok is True
        assert reason == "ok"

    def test_ttl_too_low(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        msg = make_message(ttl=1)  # below min_ttl=10
        ok, reason = sm.validate_message(msg)
        assert ok is False
        assert "TTL too low" in reason

    def test_ttl_too_high(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        msg = make_message(ttl=200000)  # above max_ttl=86400
        ok, reason = sm.validate_message(msg)
        assert ok is False
        assert "TTL too high" in reason

    def test_expired_message_blocked(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        msg = make_message(ttl=3600)
        msg["timestamp"] = old_time
        ok, reason = sm.validate_message(msg)
        assert ok is False
        assert "expired" in reason

    def test_future_message_blocked(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        msg = make_message()
        msg["timestamp"] = future_time
        ok, reason = sm.validate_message(msg)
        assert ok is False
        assert "future" in reason

    def test_payload_too_large(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir, config={"max_payload_bytes": 100})
        msg = make_message(payload={"data": "x" * 200})
        ok, reason = sm.validate_message(msg)
        assert ok is False
        assert "too large" in reason

    def test_replay_detection(self, tmp_data_dir, sample_message):
        sm = SecurityManager(tmp_data_dir)
        ok1, _ = sm.validate_message(sample_message)
        assert ok1 is True

        ok2, reason = sm.validate_message(sample_message)
        assert ok2 is False
        assert "Replay" in reason

    def test_replay_cache_eviction(self, tmp_data_dir, make_message):
        """After eviction limit, old hashes should be removed."""
        sm = SecurityManager(tmp_data_dir)
        sm._seen_max = 5  # Low limit for testing

        # Fill cache
        for i in range(6):
            msg = make_message(sender_id=f"peer_{i}", correlation_id=f"corr_{i}")
            sm.validate_message(msg)

        # Cache should have evicted oldest entries
        assert len(sm._seen_hashes) <= 5


class TestRateLimiting:
    """Test rate limiting per sender."""

    def test_within_limit_passes(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir, config={"rate_limit_per_minute": 5})
        for i in range(5):
            msg = make_message(
                msg_type="task_request",
                correlation_id=f"corr_{i}",
            )
            ok, _ = sm.validate_message(msg)
            assert ok is True

    def test_exceeds_limit_blocked(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir, config={"rate_limit_per_minute": 3})
        results = []
        for i in range(5):
            msg = make_message(
                msg_type="task_request",
                correlation_id=f"corr_rate_{i}",
            )
            ok, _ = sm.validate_message(msg)
            results.append(ok)

        # First 3 should pass, rest should fail
        assert results[:3] == [True, True, True]
        assert False in results[3:]

    def test_ping_exempt_from_rate_limit(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir, config={"rate_limit_per_minute": 2})
        for i in range(10):
            msg = make_message(
                msg_type="ping",
                correlation_id=f"corr_ping_{i}",
            )
            ok, _ = sm.validate_message(msg)
            assert ok is True  # ping is exempt


class TestSecurityMiddleware:
    """Test the router middleware function."""

    def test_middleware_passes_valid_ping(self, tmp_data_dir, sample_message):
        sm = SecurityManager(tmp_data_dir)
        result = sm.security_middleware(sample_message, None)
        assert result is True

    def test_middleware_blocks_untrusted_task(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        msg = make_message(msg_type="task_request")
        result = sm.security_middleware(msg, None)
        assert result is False

    def test_middleware_allows_known_task(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir)
        sm.set_trust_tier("test_peer", TrustTier.KNOWN)
        msg = make_message(msg_type="task_request")
        result = sm.security_middleware(msg, None)
        assert result is True


class TestStats:
    """Test security statistics tracking."""

    def test_stats_count_validated(self, tmp_data_dir, sample_message):
        sm = SecurityManager(tmp_data_dir)
        sm.validate_message(sample_message)
        assert sm.stats["validated"] == 1

    def test_stats_count_blocked(self, tmp_data_dir, make_message):
        sm = SecurityManager(tmp_data_dir, config={"max_payload_bytes": 10})
        msg = make_message(payload={"data": "x" * 100})
        sm.validate_message(msg)
        assert sm.stats["blocked_size"] == 1

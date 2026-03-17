#!/usr/bin/env python3
"""
AgentFax Session Handler — collaboration session lifecycle messages.

Message types:
  session_propose  — initiate a collaboration session
  session_accept   — accept with agreed terms
  session_reject   — decline collaboration
  session_close    — close an active session
"""

import logging

logger = logging.getLogger("agentfax.handlers.session")


def register_session_handlers(router, session_manager, executor):
    """Register session-related handlers with the router.

    Args:
        router: MessageRouter instance
        session_manager: SessionManager instance
        executor: TaskExecutor instance (to validate proposed skills)
    """

    def _make_error(error_code, error_message, retryable=False, scope="session"):
        return {
            "type": "task_error",
            "payload": {
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
                "scope": scope,
            },
        }

    # ── session_propose ──────────────────────────────────────

    @router.handler("session_propose")
    def handle_session_propose(msg, ctx):
        """Handle incoming session proposal — create local record as responder."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})

        proposed_skills = payload.get("proposed_skills", [])
        proposed_trust_tier = payload.get("proposed_trust_tier", 1)
        proposed_max_context_privacy = payload.get(
            "proposed_max_context_privacy", "L1_PUBLIC"
        )
        proposed_max_calls = payload.get("proposed_max_calls", 10)
        ttl_seconds = payload.get("ttl_seconds", 3600)
        remote_session_id = payload.get("session_id", "")

        logger.info(
            f"session_propose from {sender}: skills={proposed_skills}, "
            f"trust={proposed_trust_tier}, ttl={ttl_seconds}s"
        )

        # Trust check: KNOWN+ required to propose sessions
        if ctx.trust_manager:
            from security import TrustTier
            peer_tier = ctx.trust_manager.get_trust_tier(sender)
            if peer_tier < TrustTier.KNOWN:
                logger.warning(
                    f"session_propose rejected: {sender} is "
                    f"{TrustTier(peer_tier).name}, need KNOWN+"
                )
                return _make_error(
                    "TRUST_TIER_TOO_LOW",
                    f"Session propose requires KNOWN+ trust, "
                    f"you have {TrustTier(peer_tier).name}",
                    scope="authorization",
                )

        # Validate proposed skills exist locally
        missing = [s for s in proposed_skills if not executor.has_skill(s)]
        if missing:
            return _make_error(
                "SKILL_NOT_FOUND",
                f"Unknown skills: {missing}. "
                f"Available: {executor.skill_names}",
                scope="routing",
            )

        # Create local session record as responder
        session_id = session_manager.create_session(
            peer_id=sender,
            role="responder",
            proposed_skills=proposed_skills,
            proposed_trust_tier=proposed_trust_tier,
            proposed_max_context_privacy=proposed_max_context_privacy,
            proposed_max_calls=proposed_max_calls,
            ttl_seconds=ttl_seconds,
            initiator_id=sender,
        )

        # Auto-accept for MVP: accept with proposed terms
        # (In production, this could go through a review/approval flow)
        agreed_skills = proposed_skills
        agreed_trust = proposed_trust_tier
        agreed_privacy = proposed_max_context_privacy
        agreed_calls = proposed_max_calls

        # Build schema hashes for agreed skills
        schema_hashes = []
        for skill_name in agreed_skills:
            skill_def = executor.get_skill(skill_name)
            if skill_def:
                card = skill_def.to_skill_card()
                schema_hashes.append(card.schema_hash)

        session_manager.accept_session(
            session_id,
            agreed_skills=agreed_skills,
            agreed_trust_tier=agreed_trust,
            agreed_max_context_privacy=agreed_privacy,
            agreed_max_calls=agreed_calls,
            agreed_schema_hash=",".join(schema_hashes),
        )

        # S5: Slack notification — session proposed & auto-accepted
        if ctx.slack_notifier:
            try:
                ctx.slack_notifier.notify_session_proposed(
                    peer_id=sender, skills=proposed_skills,
                    trust_tier=proposed_trust_tier, session_id=session_id,
                )
                session_data = session_manager.get_session(session_id)
                if session_data:
                    ctx.slack_notifier.notify_session_accepted(session_data)
            except Exception as e:
                logger.debug(f"Slack notify failed (session_propose): {e}")

        return {
            "type": "session_accept",
            "payload": {
                "session_id": session_id,
                "remote_session_id": remote_session_id,
                "agreed_skills": agreed_skills,
                "agreed_skill_version": "1.0.0",
                "agreed_schema_hash": ",".join(schema_hashes),
                "agreed_trust_tier": agreed_trust,
                "agreed_max_context_privacy": agreed_privacy,
                "agreed_max_calls": agreed_calls,
                "agreed_pricing_snapshot": {"model": "free", "amount": 0},
                "expires_at": session_manager.get_session(session_id).get("expires_at", ""),
            },
        }

    # ── session_accept ───────────────────────────────────────

    @router.handler("session_accept")
    def handle_session_accept(msg, ctx):
        """Handle peer's acceptance — activate our local session."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})

        remote_session_id = payload.get("session_id", "")
        local_session_id = payload.get("remote_session_id", "")

        logger.info(
            f"session_accept from {sender}: "
            f"local={local_session_id}, remote={remote_session_id}"
        )

        if not local_session_id:
            logger.warning("session_accept: no remote_session_id to match")
            return None

        session = session_manager.get_session(local_session_id)
        if not session:
            logger.warning(
                f"session_accept: local session {local_session_id} not found"
            )
            return None

        # Verify sender matches session peer
        if session["peer_id"] != sender:
            logger.warning(
                f"session_accept: sender {sender} != session peer "
                f"{session['peer_id']} — ignoring"
            )
            return _make_error(
                "SESSION_PEER_MISMATCH",
                f"Session {local_session_id} is with {session['peer_id']}, "
                f"not {sender}",
                scope="authorization",
            )

        # Activate with agreed terms from peer
        session_manager.accept_session(
            local_session_id,
            agreed_skills=payload.get("agreed_skills"),
            agreed_skill_version=payload.get("agreed_skill_version", "1.0.0"),
            agreed_schema_hash=payload.get("agreed_schema_hash", ""),
            agreed_trust_tier=payload.get("agreed_trust_tier"),
            agreed_max_context_privacy=payload.get("agreed_max_context_privacy"),
            agreed_max_calls=payload.get("agreed_max_calls"),
            agreed_pricing_snapshot=payload.get("agreed_pricing_snapshot"),
        )

        logger.info(f"Session {local_session_id} now ACTIVE with {sender}")

        # S5: Slack notification — our proposal was accepted by peer
        if ctx.slack_notifier:
            try:
                session_data = session_manager.get_session(local_session_id)
                if session_data:
                    ctx.slack_notifier.notify_session_accepted(session_data)
            except Exception as e:
                logger.debug(f"Slack notify failed (session_accept): {e}")

        return None

    # ── session_reject ───────────────────────────────────────

    @router.handler("session_reject")
    def handle_session_reject(msg, ctx):
        """Handle peer's rejection of our session proposal."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})

        local_session_id = payload.get("remote_session_id", "")
        reason = payload.get("reason", "")

        logger.info(
            f"session_reject from {sender}: session={local_session_id}, "
            f"reason={reason}"
        )

        if local_session_id:
            session = session_manager.get_session(local_session_id)
            if session and session["peer_id"] != sender:
                logger.warning(
                    f"session_reject: sender {sender} != peer "
                    f"{session['peer_id']} — ignoring"
                )
                return None
            session_manager.reject_session(local_session_id, reason)

            # S5: Slack notification
            if ctx.slack_notifier:
                try:
                    ctx.slack_notifier.notify_session_rejected(
                        peer_id=sender, reason=reason,
                        session_id=local_session_id,
                    )
                except Exception as e:
                    logger.debug(f"Slack notify failed (session_reject): {e}")

        return None

    # ── session_close ────────────────────────────────────────

    @router.handler("session_close")
    def handle_session_close(msg, ctx):
        """Handle session close request from either party."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})

        session_id = payload.get("session_id", "")
        reason = payload.get("reason", "")

        logger.info(
            f"session_close from {sender}: session={session_id}, "
            f"reason={reason}"
        )

        if not session_id:
            return _make_error(
                "MISSING_SESSION_ID",
                "session_close requires session_id",
                scope="session",
            )

        session = session_manager.get_session(session_id)
        if not session:
            return _make_error(
                "SESSION_NOT_FOUND",
                f"Session {session_id} does not exist",
                scope="session",
            )

        # Verify sender matches session peer
        if session["peer_id"] != sender:
            return _make_error(
                "SESSION_PEER_MISMATCH",
                f"Session {session_id} is with {session['peer_id']}, "
                f"not {sender}",
                scope="authorization",
            )

        # Close the session
        ok = session_manager.close_session(session_id, reason)
        if not ok:
            # Try force close if already closing
            ok = session_manager.force_close_session(session_id, reason)

        if not ok:
            return _make_error(
                "SESSION_CLOSE_FAILED",
                f"Cannot close session {session_id} "
                f"(current state: {session['state']})",
                scope="session",
            )

        # Try to auto-complete if no tasks in flight
        session_manager.complete_session(session_id)

        # S5: Slack notification
        if ctx.slack_notifier:
            try:
                session_data = session_manager.get_session(session_id)
                if session_data:
                    ctx.slack_notifier.notify_session_closed(session_data)
            except Exception as e:
                logger.debug(f"Slack notify failed (session_close): {e}")

        final = session_manager.get_session(session_id)
        return {
            "type": "session_close",
            "payload": {
                "session_id": session_id,
                "status": final["state"] if final else "closed",
                "reason": reason,
            },
        }

    logger.info(
        "Registered session handlers: session_propose, session_accept, "
        "session_reject, session_close"
    )

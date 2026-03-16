#!/usr/bin/env python3
"""
AgentFax Task Handler — handles task_request/response/ack/cancel messages.

Integrates TaskManager + TaskExecutor with the message router.
When a task_request arrives, it:
1. Records the task in TaskManager
2. Sends task_ack back to requester
3. Executes the skill via TaskExecutor
4. Sends task_response with result (or task_error)

On the requester side, handles incoming task_ack, task_response, task_progress.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("agentfax.handlers.task")


def register_task_handlers(router, task_manager, executor):
    """Register task-related handlers with the router.

    Args:
        router: MessageRouter instance
        task_manager: TaskManager instance
        executor: TaskExecutor instance
    """

    # ── Unified error response builder ──────────────────────────

    def _make_error(task_id, skill, error_code, error_message, retryable=False, scope="execution"):
        """Build a standardized error response."""
        return {
            "type": "task_error",
            "payload": {
                "task_id": task_id,
                "skill": skill,
                "error_code": error_code,
                "error_message": error_message,
                "retryable": retryable,
                "scope": scope,
            },
        }

    # ── Dedup cache (sender+correlation_id → response) ──────
    # Key is (sender, correlation_id) to prevent cross-sender leakage.
    # TTL and size bounded to prevent memory exhaustion.

    _dedup_cache = {}
    _dedup_timestamps = {}
    _DEDUP_TTL_SECONDS = 300
    _DEDUP_MAX_ENTRIES = 1000

    def _dedup_key(sender, correlation_id):
        return f"{sender}:{correlation_id}"

    def _dedup_cleanup():
        """Evict expired entries and enforce size limit."""
        now = time.time()
        expired = [k for k, ts in _dedup_timestamps.items()
                   if now - ts > _DEDUP_TTL_SECONDS]
        for k in expired:
            _dedup_cache.pop(k, None)
            _dedup_timestamps.pop(k, None)
        # If still over limit, evict oldest
        while len(_dedup_cache) > _DEDUP_MAX_ENTRIES:
            oldest_key = min(_dedup_timestamps, key=_dedup_timestamps.get)
            _dedup_cache.pop(oldest_key, None)
            _dedup_timestamps.pop(oldest_key, None)

    # ── Executor side: handle incoming task requests ───────────

    @router.handler("task_request")
    def handle_task_request(msg, ctx):
        payload = msg.get("payload", {})
        skill = payload.get("skill")
        input_data = payload.get("input")
        task_id = payload.get("task_id") or msg.get("correlation_id", f"task_{int(time.time())}")
        timeout = payload.get("timeout", 300)
        sender = msg.get("sender_id", "unknown")
        sender_wallet = msg.get("_xmtp_sender_wallet")
        correlation_id = msg.get("correlation_id", "")
        session_id = payload.get("session_id")  # S2: optional session binding

        logger.info(f"Task request from {sender}: skill={skill}, task_id={task_id}")

        # ── Check 1: Trust — is this peer allowed to call? ──────
        # Trust check BEFORE dedup to prevent auth bypass via cached responses.
        if ctx.trust_manager:
            from security import TrustTier
            peer_tier = ctx.trust_manager.get_trust_tier(sender)

            # Get skill's minimum trust requirement
            skill_def = executor.get_skill(skill) if executor.has_skill(skill) else None
            min_tier = skill_def.min_trust_tier if skill_def else 1

            if peer_tier < min_tier:
                logger.warning(
                    f"Trust check FAILED: {sender} has tier {peer_tier} "
                    f"({TrustTier(peer_tier).name}), skill '{skill}' requires {min_tier}"
                )
                return _make_error(
                    task_id, skill,
                    "TRUST_TIER_TOO_LOW",
                    f"Requires trust tier {min_tier} ({TrustTier(min_tier).name}), "
                    f"you have {peer_tier} ({TrustTier(peer_tier).name})",
                    retryable=False,
                    scope="authorization",
                )

        # ── Check 2: Idempotency — after trust, before execution ──
        # Cleanup first so expired entries don't get returned.
        _dedup_cleanup()
        dedup_k = _dedup_key(sender, correlation_id) if correlation_id else None
        if dedup_k and dedup_k in _dedup_cache:
            logger.info(f"Duplicate request from {sender}, returning cached response")
            return _dedup_cache[dedup_k]

        # ── Check 3: Skill exists ──────────────────────────────
        if not executor.has_skill(skill):
            logger.warning(f"Unknown skill requested: {skill}")
            return _make_error(
                task_id, skill,
                "SKILL_NOT_FOUND",
                f"Unknown skill: {skill}. Available: {executor.skill_names}",
                retryable=False,
                scope="routing",
            )

        # ── Check 4: Session validation (if session_id present) ──
        session_privacy_cap = None  # Will be used for context projection
        if session_id and ctx.session_manager:
            ok, err_code, err_msg = ctx.session_manager.validate_task_request(
                session_id, skill, sender
            )
            if not ok:
                logger.warning(f"Session check FAILED: {err_code} — {err_msg}")
                return _make_error(
                    task_id, skill, err_code, err_msg,
                    retryable=False, scope="session",
                )

            # Enforce session agreed_trust_tier
            session_data = ctx.session_manager.get_session(session_id)
            if session_data and ctx.trust_manager:
                from security import TrustTier
                agreed_tier = session_data.get("agreed_trust_tier")
                if agreed_tier is not None:
                    peer_tier = ctx.trust_manager.get_trust_tier(sender)
                    if peer_tier < agreed_tier:
                        return _make_error(
                            task_id, skill,
                            "TRUST_TIER_DEGRADED",
                            f"Peer trust {peer_tier} dropped below session "
                            f"agreed tier {agreed_tier}",
                            retryable=False, scope="authorization",
                        )
                # Save session privacy cap for context projection
                session_privacy_cap = session_data.get("agreed_max_context_privacy")

            # Atomic increment call counter
            if not ctx.session_manager.increment_call_count(session_id):
                return _make_error(
                    task_id, skill,
                    "CALL_LIMIT_EXCEEDED",
                    f"Session {session_id} call limit reached",
                    retryable=False, scope="session",
                )

        # Record the task
        task_manager.receive_task(
            task_id=task_id,
            skill=skill,
            input_data=input_data or {},
            peer_wallet=sender_wallet or "",
            peer_name=sender,
            correlation_id=correlation_id,
            timeout_seconds=timeout,
        )

        # Send ack
        task_manager.accept_task(task_id)

        # Send ack message back
        if sender_wallet:
            try:
                ctx.client.send(
                    to_wallet=sender_wallet,
                    msg_type="task_ack",
                    payload={
                        "task_id": task_id,
                        "skill": skill,
                        "status": "accepted",
                        "estimated_duration": "unknown",
                    },
                    correlation_id=correlation_id,
                )
            except Exception as e:
                logger.error(f"Failed to send task_ack: {e}")

        # Project relevant context for this task (Phase 6)
        # Enforce min(peer trust, skill privacy cap, session privacy cap).
        task_context = None
        if ctx.context_manager and ctx.trust_manager:
            privacy_tier_map = {"L1_PUBLIC": 1, "L2_TRUSTED": 2, "L3_PRIVATE": 3}
            peer_tier = ctx.trust_manager.get_trust_tier(sender)
            skill_def = executor.get_skill(skill)
            max_privacy = skill_def.max_context_privacy_tier if skill_def else "L1_PUBLIC"
            privacy_cap = privacy_tier_map.get(max_privacy, 1)
            # Also apply session privacy cap if present
            if session_privacy_cap:
                session_cap = privacy_tier_map.get(session_privacy_cap, 1)
                privacy_cap = min(privacy_cap, session_cap)
            effective_tier = min(peer_tier, privacy_cap)

            task_context = ctx.context_manager.project_for_task(
                skill, effective_tier
            )
            if task_context:
                logger.debug(
                    f"Projected {len(task_context)} context items for task {task_id} "
                    f"(max_privacy={max_privacy})"
                )

        # Execute the skill (pass context as part of input if available)
        task_manager.start_task(task_id)
        exec_input = input_data
        if task_context and isinstance(input_data, dict):
            exec_input = {**input_data, "_context": task_context}

        try:
            exec_result = executor.execute(skill, exec_input)
        except Exception as e:
            # Safety net: executor.execute() should not raise, but if it does,
            # ensure session/task counters stay consistent.
            logger.error(f"Executor crash for task {task_id}: {e}")
            exec_result = {"success": False, "error": str(e)}

        if exec_result.get("success"):
            duration = exec_result.get("duration_ms", 0)
            task_manager.complete_task(task_id, result=exec_result.get("result"))
            logger.info(f"Task {task_id} completed: {duration:.0f}ms")

            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_completed", True, latency_ms=duration
                )
            if session_id and ctx.session_manager:
                ctx.session_manager.task_completed(session_id)

            response = {
                "type": "task_response",
                "payload": {
                    "task_id": task_id,
                    "skill": skill,
                    "status": "completed",
                    "output": exec_result.get("result"),
                    "duration_ms": duration,
                    "session_id": session_id,
                },
            }
        else:
            error_msg = exec_result.get("error", "unknown error")
            task_manager.fail_task(task_id, error_msg)
            logger.error(f"Task {task_id} failed: {error_msg}")

            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_failed", False,
                    metadata={"error": error_msg}
                )
            if session_id and ctx.session_manager:
                ctx.session_manager.task_failed(session_id)

            response = _make_error(
                task_id, skill,
                "EXECUTION_FAILED",
                error_msg,
                retryable=False,
                scope="execution",
            )

        # Cache response for dedup (keyed by sender+correlation_id)
        if dedup_k:
            _dedup_cache[dedup_k] = response
            _dedup_timestamps[dedup_k] = time.time()

        return response

    # ── Requester side: handle task responses ──────────────────

    @router.handler("task_ack")
    def handle_task_ack(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        sender = msg.get("sender_id", "unknown")
        logger.info(f"Task {task_id} accepted by {sender}")

        # Update local task state
        task = task_manager.get_by_correlation(msg.get("correlation_id", ""))
        if task:
            task_manager.accept_task(task["task_id"])
        return None

    @router.handler("task_reject")
    def handle_task_reject(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        reason = payload.get("reason", "no reason")
        sender = msg.get("sender_id", "unknown")
        logger.warning(f"Task {task_id} rejected by {sender}: {reason}")

        task = task_manager.get_by_correlation(msg.get("correlation_id", ""))
        if task:
            task_manager.reject_task(task["task_id"], reason)
        return None

    @router.handler("task_response")
    def handle_task_response(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        output = payload.get("output")
        duration = payload.get("duration_ms")
        sender = msg.get("sender_id", "unknown")

        logger.info(
            f"Task {task_id} response from {sender}"
            + (f" ({duration:.0f}ms)" if duration else "")
        )

        task = task_manager.get_by_correlation(msg.get("correlation_id", ""))
        if task:
            task_manager.complete_task(task["task_id"], result=output)

        # Record reputation — peer completed our task
        if ctx.reputation_manager:
            ctx.reputation_manager.record_interaction(
                sender, "task_completed", True, latency_ms=duration
            )

        # Phase 7: If this task is part of a workflow, complete the step
        workflow_id = payload.get("workflow_id")
        step_id = payload.get("step_id")
        if workflow_id and step_id and ctx.workflow_manager:
            try:
                newly_ready = ctx.workflow_manager.complete_step(
                    workflow_id, step_id, output or {}
                )
                if newly_ready:
                    logger.info(
                        f"Workflow {workflow_id}: step {step_id} done, "
                        f"newly ready: {newly_ready}"
                    )
            except Exception as e:
                logger.error(f"Workflow step completion error: {e}")

        return None

    @router.handler("task_error")
    def handle_task_error(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        # Support both new format (error_code+error_message) and old (error)
        error_code = payload.get("error_code", "")
        error_message = payload.get("error_message", "")
        error = error_message or payload.get("error", "unknown")
        retryable = payload.get("retryable", False)
        scope = payload.get("scope", "")
        sender = msg.get("sender_id", "unknown")

        logger.error(
            f"Task {task_id} error from {sender}: "
            f"[{error_code}] {error} (retryable={retryable}, scope={scope})"
        )

        task = task_manager.get_by_correlation(msg.get("correlation_id", ""))
        if task:
            task_manager.fail_task(task["task_id"], error)

        # Record reputation — peer failed our task
        if ctx.reputation_manager:
            ctx.reputation_manager.record_interaction(
                sender, "task_failed", False, metadata={"error": error}
            )

        # Phase 7: If this task is part of a workflow, fail the step
        workflow_id = payload.get("workflow_id")
        step_id = payload.get("step_id")
        if workflow_id and step_id and ctx.workflow_manager:
            try:
                ctx.workflow_manager.fail_step(workflow_id, step_id, error)
            except Exception as e:
                logger.error(f"Workflow step failure error: {e}")

        return None

    @router.handler("task_progress")
    def handle_task_progress(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        percent = payload.get("percent", 0)
        text = payload.get("status_text", "")
        sender = msg.get("sender_id", "unknown")

        logger.info(f"Task {task_id} progress from {sender}: {percent}% {text}")

        task = task_manager.get_by_correlation(msg.get("correlation_id", ""))
        if task:
            task_manager.update_progress(task["task_id"], percent, text)
        return None

    @router.handler("task_cancel")
    def handle_task_cancel(msg, ctx):
        payload = msg.get("payload", {})
        task_id = payload.get("task_id")
        sender = msg.get("sender_id", "unknown")

        logger.info(f"Task {task_id} cancelled by {sender}")

        task = task_manager.get_task(task_id)
        if task:
            task_manager.cancel_task(task_id)
        return None

    logger.info("Registered task handlers: task_request, task_ack, task_reject, "
                "task_response, task_error, task_progress, task_cancel")

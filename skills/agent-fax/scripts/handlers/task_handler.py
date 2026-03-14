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

        logger.info(f"Task request from {sender}: skill={skill}, task_id={task_id}")

        # Check if we have this skill
        if not executor.has_skill(skill):
            logger.warning(f"Unknown skill requested: {skill}")
            return {
                "type": "task_reject",
                "payload": {
                    "task_id": task_id,
                    "reason": f"Unknown skill: {skill}",
                    "available_skills": executor.skill_names,
                },
            }

        # Record the task
        task_manager.receive_task(
            task_id=task_id,
            skill=skill,
            input_data=input_data or {},
            peer_wallet=sender_wallet or "",
            peer_name=sender,
            correlation_id=msg.get("correlation_id"),
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
                    correlation_id=msg.get("correlation_id"),
                )
            except Exception as e:
                logger.error(f"Failed to send task_ack: {e}")

        # Project relevant context for this task (Phase 6)
        task_context = None
        if ctx.context_manager and ctx.security_manager:
            peer_tier = ctx.security_manager.get_trust_tier(sender, sender_wallet)
            task_context = ctx.context_manager.project_for_task(
                skill, peer_tier
            )
            if task_context:
                logger.debug(
                    f"Projected {len(task_context)} context items for task {task_id}"
                )

        # Execute the skill (pass context as part of input if available)
        task_manager.start_task(task_id)
        exec_input = input_data
        if task_context and isinstance(input_data, dict):
            exec_input = {**input_data, "_context": task_context}
        exec_result = executor.execute(skill, exec_input)

        if exec_result.get("success"):
            duration = exec_result.get("duration_ms", 0)
            task_manager.complete_task(task_id, result=exec_result.get("result"))
            logger.info(f"Task {task_id} completed: {duration:.0f}ms")

            # Record reputation — successful task execution
            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_completed", True, latency_ms=duration
                )

            return {
                "type": "task_response",
                "payload": {
                    "task_id": task_id,
                    "skill": skill,
                    "status": "completed",
                    "output": exec_result.get("result"),
                    "duration_ms": duration,
                },
            }
        else:
            error_msg = exec_result.get("error", "unknown error")
            task_manager.fail_task(task_id, error_msg)
            logger.error(f"Task {task_id} failed: {error_msg}")

            # Record reputation — failed task execution
            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_failed", False,
                    metadata={"error": error_msg}
                )

            return {
                "type": "task_error",
                "payload": {
                    "task_id": task_id,
                    "skill": skill,
                    "status": "failed",
                    "error": error_msg,
                },
            }

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
        error = payload.get("error", "unknown")
        sender = msg.get("sender_id", "unknown")

        logger.error(f"Task {task_id} error from {sender}: {error}")

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

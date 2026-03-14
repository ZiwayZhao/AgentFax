#!/usr/bin/env python3
"""
AgentFax Workflow Handler — handles workflow_request messages.

When a peer sends a workflow_request, we treat it as a task_request
with additional workflow metadata. The response goes back as a
standard task_response with workflow_id in the payload.
"""

import logging
import time

logger = logging.getLogger("agentfax.handlers.workflow")


def register_workflow_handlers(router, workflow_manager, task_manager, executor):
    """Register workflow-related handlers with the router.

    Args:
        router: MessageRouter instance
        workflow_manager: WorkflowManager instance
        task_manager: TaskManager instance
        executor: TaskExecutor instance
    """

    @router.handler("workflow_request")
    def handle_workflow_request(msg, ctx):
        """Handle incoming workflow step request from a peer.

        This is essentially a task_request with workflow metadata.
        We execute the skill and return a task_response with workflow_id.
        """
        payload = msg.get("payload", {})
        workflow_id = payload.get("workflow_id")
        step_info = payload.get("step", {})
        wf_metadata = payload.get("workflow_metadata", {})

        step_id = step_info.get("step_id")
        skill = step_info.get("skill")
        input_data = step_info.get("input", {})
        step_context = step_info.get("context", [])
        timeout = step_info.get("timeout_seconds", 300)

        sender = msg.get("sender_id", "unknown")
        sender_wallet = msg.get("_xmtp_sender_wallet")

        task_id = f"wf_{workflow_id}_{step_id}_{int(time.time())}"

        logger.info(
            f"Workflow request from {sender}: "
            f"wf={workflow_id}, step={step_id}, skill={skill}"
        )

        # Check if we have this skill
        if not executor.has_skill(skill):
            logger.warning(f"Unknown skill in workflow: {skill}")
            return {
                "type": "task_error",
                "payload": {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "skill": skill,
                    "status": "failed",
                    "error": f"Unknown skill: {skill}",
                },
            }

        # Record as a task
        task_manager.receive_task(
            task_id=task_id,
            skill=skill,
            input_data=input_data,
            peer_wallet=sender_wallet or "",
            peer_name=sender,
            correlation_id=msg.get("correlation_id"),
            timeout_seconds=timeout,
        )
        task_manager.accept_task(task_id)

        # Send ack
        if sender_wallet:
            try:
                ctx.client.send(
                    to_wallet=sender_wallet,
                    msg_type="task_ack",
                    payload={
                        "task_id": task_id,
                        "workflow_id": workflow_id,
                        "step_id": step_id,
                        "skill": skill,
                        "status": "accepted",
                    },
                    correlation_id=msg.get("correlation_id"),
                )
            except Exception as e:
                logger.error(f"Failed to send workflow task_ack: {e}")

        # Merge step context into input if available
        exec_input = input_data
        if step_context and isinstance(input_data, dict):
            exec_input = {**input_data, "_context": step_context}

        # Execute the skill
        task_manager.start_task(task_id)
        exec_result = executor.execute(skill, exec_input)

        if exec_result.get("success"):
            duration = exec_result.get("duration_ms", 0)
            task_manager.complete_task(task_id, result=exec_result.get("result"))

            logger.info(
                f"Workflow step {step_id} completed: {duration:.0f}ms"
            )

            # Record reputation
            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_completed", True, latency_ms=duration
                )

            return {
                "type": "task_response",
                "payload": {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "skill": skill,
                    "status": "completed",
                    "output": exec_result.get("result"),
                    "duration_ms": duration,
                },
            }
        else:
            error_msg = exec_result.get("error", "unknown error")
            task_manager.fail_task(task_id, error_msg)

            logger.error(f"Workflow step {step_id} failed: {error_msg}")

            # Record reputation
            if ctx.reputation_manager:
                ctx.reputation_manager.record_interaction(
                    sender, "task_failed", False,
                    metadata={"error": error_msg}
                )

            return {
                "type": "task_error",
                "payload": {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "step_id": step_id,
                    "skill": skill,
                    "status": "failed",
                    "error": error_msg,
                },
            }

    logger.info("Registered workflow handler: workflow_request")

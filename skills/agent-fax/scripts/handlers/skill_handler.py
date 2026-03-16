#!/usr/bin/env python3
"""
AgentFax Skill Handler — remote skill installation and discovery.

Message types:
  skill_install  — push a skill (Python code) to a peer
  skill_query    — ask a peer what skills they have
  skill_list     — response listing available skills
"""

import logging
import os

logger = logging.getLogger("agentfax.handlers.skill")


def register_skill_handlers(router, executor, data_dir: str):
    """Register skill-related handlers with the router.

    Args:
        router: MessageRouter instance
        executor: TaskExecutor instance
        data_dir: AgentFax data directory (for persisting installed skills)
    """

    custom_skills_dir = os.path.join(data_dir, "custom_skills")

    @router.handler("skill_install")
    def handle_skill_install(msg, ctx):
        """Receive and install a skill from a peer.

        Expected payload:
            name: str         — skill name
            code: str         — Python source (must define handler(input_data))
            description: str  — what the skill does
            input_schema: dict (optional)
            output_schema: dict (optional)
        """
        payload = msg.get("payload", {})
        name = payload.get("name")
        code = payload.get("code")
        sender = msg.get("sender_id", "unknown")

        if not name or not code:
            logger.warning(f"skill_install from {sender}: missing name or code")
            return {
                "type": "skill_install_result",
                "payload": {
                    "name": name or "?",
                    "success": False,
                    "error": "missing name or code",
                },
            }

        logger.info(f"skill_install from {sender}: installing '{name}' ({len(code)} bytes)")

        result = executor.install_from_code(
            name=name,
            code=code,
            description=payload.get("description", f"Installed by {sender}"),
            input_schema=payload.get("input_schema"),
            output_schema=payload.get("output_schema"),
            save_dir=custom_skills_dir,
        )

        if result["success"]:
            logger.info(f"Skill '{name}' installed successfully from {sender}")
        else:
            logger.error(f"Skill '{name}' install failed: {result.get('error')}")

        return {
            "type": "skill_install_result",
            "payload": result,
        }

    @router.handler("skill_install_result")
    def handle_skill_install_result(msg, ctx):
        """Handle the result of a skill installation we requested."""
        payload = msg.get("payload", {})
        name = payload.get("name", "?")
        success = payload.get("success", False)
        sender = msg.get("sender_id", "unknown")

        if success:
            logger.info(f"Skill '{name}' installed on {sender} ✓")
        else:
            logger.error(f"Skill '{name}' install failed on {sender}: {payload.get('error')}")
        return None

    @router.handler("skill_query")
    def handle_skill_query(msg, ctx):
        """Respond with our list of available skills."""
        sender = msg.get("sender_id", "unknown")
        logger.info(f"skill_query from {sender}")
        return {
            "type": "skill_list",
            "payload": {
                "skills": executor.list_skills(),
                "count": len(executor.skill_names),
            },
        }

    @router.handler("skill_list")
    def handle_skill_list(msg, ctx):
        """Handle a peer's skill list response."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        skills = payload.get("skills", [])
        logger.info(
            f"Skill list from {sender}: {len(skills)} skills — "
            + ", ".join(s.get("name", "?") for s in skills)
        )

        # Update peer capabilities
        if ctx.peer_manager:
            capabilities = [s.get("name") for s in skills if s.get("name")]
            peer = ctx.peer_manager.get(sender)
            if peer:
                peer["capabilities"] = capabilities
                ctx.peer_manager.save(sender, peer)
                logger.info(f"Updated {sender} capabilities: {capabilities}")

        return None

    logger.info("Registered skill handlers: skill_install, skill_query, skill_list")

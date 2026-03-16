#!/usr/bin/env python3
"""
AgentFax Skill Handler — Skill Card discovery (Skill-as-API model).

Code transfer is forbidden. Skills are exposed as API interfaces via
Skill Cards — only input/output schemas are shared, never implementation.

Message types:
  skill_card_query  — ask a peer what skills they have (returns card summaries)
  skill_card_list   — response listing Skill Card summaries
  skill_card_get    — request a single Skill Card's full details
  skill_card        — response with full Skill Card

Legacy compatibility:
  skill_query       — maps to skill_card_query
  skill_list        — maps to skill_card_list
  skill_install     — rejected with CODE_TRANSFER_FORBIDDEN
"""

import logging

logger = logging.getLogger("agentfax.handlers.skill")


def register_skill_handlers(router, executor, data_dir: str):
    """Register skill-related handlers with the router."""

    # ── Skill Card discovery ─────────────────────────────────

    @router.handler("skill_card_query")
    def handle_skill_card_query(msg, ctx):
        """Return summaries of all available Skill Cards."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})
        tags_filter = payload.get("tags")
        names_filter = payload.get("names")

        logger.info(f"skill_card_query from {sender}")

        cards = []
        for skill_dict in executor.list_skills():
            # Apply filters
            if names_filter and skill_dict["name"] not in names_filter:
                continue
            cards.append(skill_dict)

        return {
            "type": "skill_card_list",
            "payload": {
                "skills": cards,
                "count": len(cards),
            },
        }

    @router.handler("skill_card_list")
    def handle_skill_card_list(msg, ctx):
        """Handle a peer's Skill Card list response."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        skills = payload.get("skills", [])
        logger.info(
            f"Skill card list from {sender}: {len(skills)} skills — "
            + ", ".join(s.get("name", "?") for s in skills)
        )

        # Update peer capabilities (must pass skill objects, not bare names)
        if ctx.peer_manager:
            ctx.peer_manager.update_capabilities(
                sender, capabilities={"skills": skills}
            )

        return None

    @router.handler("skill_card_get")
    def handle_skill_card_get(msg, ctx):
        """Return full details for a specific Skill Card."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        skill_name = payload.get("skill_name")

        logger.info(f"skill_card_get from {sender}: {skill_name}")

        skill_def = executor.get_skill(skill_name) if skill_name else None
        if not skill_def:
            return {
                "type": "task_error",
                "payload": {
                    "error_code": "SKILL_NOT_FOUND",
                    "error_message": f"No skill named '{skill_name}'",
                    "retryable": False,
                    "scope": "routing",
                },
            }

        return {
            "type": "skill_card",
            "payload": {
                "card": skill_def.to_dict(),
            },
        }

    @router.handler("skill_card")
    def handle_skill_card(msg, ctx):
        """Handle a full Skill Card response from a peer."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        card = payload.get("card", {})
        logger.info(f"Skill card from {sender}: {card.get('name', '?')}")
        return None

    # ── Legacy compatibility ─────────────────────────────────

    @router.handler("skill_query")
    def handle_skill_query(msg, ctx):
        """Legacy: returns skill_list (old type name) for backwards compat."""
        sender = msg.get("sender_id", "unknown")
        logger.info(f"skill_query (legacy) from {sender}")
        cards = executor.list_skills()
        return {
            "type": "skill_list",
            "payload": {
                "skills": cards,
                "count": len(cards),
            },
        }

    @router.handler("skill_list")
    def handle_skill_list(msg, ctx):
        """Legacy: same processing as skill_card_list."""
        return handle_skill_card_list(msg, ctx)

    @router.handler("skill_install")
    def handle_skill_install(msg, ctx):
        """Reject remote code installation — code transfer is forbidden."""
        sender = msg.get("sender_id", "unknown")
        logger.warning(f"skill_install REJECTED from {sender}: code transfer forbidden")
        return {
            "type": "skill_install_result",
            "payload": {
                "name": msg.get("payload", {}).get("name", "?"),
                "success": False,
                "error_code": "CODE_TRANSFER_FORBIDDEN",
                "error": "Remote code installation is not supported. "
                         "Use skill_card_query to discover available skills.",
            },
        }

    @router.handler("skill_install_result")
    def handle_skill_install_result(msg, ctx):
        """Legacy no-op."""
        return None

    logger.info("Registered skill handlers: skill_card_query/list/get/card, "
                "skill_query (legacy), skill_install (rejected)")

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


def register_skill_handlers(router, executor, data_dir: str,
                            peer_skill_cache=None):
    """Register skill-related handlers with the router.

    Args:
        router: MessageRouter instance
        executor: TaskExecutor instance
        data_dir: Data directory path
        peer_skill_cache: Optional PeerSkillCache for caching peer cards
    """

    # ── Helper: resolve agent identity for Skill Card provider field ──

    def _get_agent_identity(ctx):
        """Extract agent_id and wallet from context/client."""
        agent_id = ""
        wallet = ""
        if ctx.client:
            agent_id = getattr(ctx.client, "agent_id", "") or ""
            wallet = getattr(ctx.client, "wallet_address", "") or ""
        return agent_id, wallet

    # ── Skill Card discovery ─────────────────────────────────

    @router.handler("skill_card_query")
    def handle_skill_card_query(msg, ctx):
        """Return full Skill Cards for all available skills."""
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})
        tags_filter = payload.get("tags")
        names_filter = payload.get("names")

        logger.info(f"skill_card_query from {sender}")

        agent_id, wallet = _get_agent_identity(ctx)
        all_cards = executor.list_skill_cards(
            agent_id=agent_id, wallet=wallet
        )

        cards = []
        for card in all_cards:
            # Filter by names
            if names_filter and card.get("skill_name") not in names_filter:
                continue
            # Filter by tags
            if tags_filter:
                card_tags = card.get("tags", [])
                if not any(t in card_tags for t in tags_filter):
                    continue
            cards.append(card)

        return {
            "type": "skill_card_list",
            "payload": {
                "skills": cards,
                "count": len(cards),
            },
        }

    @router.handler("skill_card_list")
    def handle_skill_card_list(msg, ctx):
        """Handle a peer's Skill Card list response — cache the cards."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        skills = payload.get("skills", [])
        logger.info(
            f"Skill card list from {sender}: {len(skills)} skills — "
            + ", ".join(
                s.get("skill_name") or s.get("name", "?") for s in skills
            )
        )

        # Cache in PeerSkillCache (SQLite)
        if peer_skill_cache and skills:
            peer_skill_cache.store_cards(sender, skills)

        # Update peer capabilities (backwards compat with peers.json)
        if ctx.peer_manager:
            ctx.peer_manager.update_capabilities(
                sender, capabilities={"skills": skills}
            )

        return None

    @router.handler("skill_card_get")
    def handle_skill_card_get(msg, ctx):
        """Return full Skill Card for a specific skill."""
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

        agent_id, wallet = _get_agent_identity(ctx)
        card = skill_def.to_skill_card(
            agent_id=agent_id, wallet=wallet
        )

        return {
            "type": "skill_card",
            "payload": {
                "card": card.to_dict(),
            },
        }

    @router.handler("skill_card")
    def handle_skill_card(msg, ctx):
        """Handle a full Skill Card response from a peer — cache it."""
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        card = payload.get("card", {})
        card_name = card.get("skill_name") or card.get("name", "?")
        logger.info(f"Skill card from {sender}: {card_name}")

        # Cache the single card
        if peer_skill_cache and card:
            peer_skill_cache.store_cards(sender, [card])

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

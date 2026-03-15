#!/usr/bin/env python3
"""
AgentFax Context Handlers — handles context_sync, context_query, context_response.

These handlers enable privacy-aware context exchange between agents.
All context sharing respects trust tiers and privacy levels.
"""

import logging

logger = logging.getLogger("agentfax.handlers.context")


def register_context_handlers(router, context_manager, trust_manager):
    """Register context-related handlers with the router.

    Args:
        router: MessageRouter instance
        context_manager: ContextManager instance
        trust_manager: TrustManager instance
    """

    # ── context_sync: receive context items from a peer ──────────

    @router.handler("context_sync")
    def handle_context_sync(msg, ctx):
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        items = payload.get("items", [])
        sync_mode = payload.get("sync_mode", "incremental")

        logger.info(
            f"Received context_sync from {sender}: "
            f"{len(items)} items ({sync_mode})"
        )

        if not items:
            return None

        # Store peer context
        count = context_manager.store_peer_context(
            peer_id=sender,
            context_items=items,
            correlation_id=msg.get("correlation_id"),
        )

        logger.info(f"Stored {count} context items from {sender}")

        # Acknowledge with count
        return {
            "type": "ack",
            "payload": {
                "correlation_id": msg.get("correlation_id"),
                "context_items_stored": count,
            },
        }

    # ── context_query: peer requests our context ─────────────────

    @router.handler("context_query")
    def handle_context_query(msg, ctx):
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        sender_wallet = msg.get("_xmtp_sender_wallet")

        logger.info(
            f"Received context_query from {sender}: "
            f"categories={payload.get('categories')}, "
            f"max_items={payload.get('max_items', 10)}"
        )

        # Get sender's trust tier to determine what we can share
        peer_tier = trust_manager.get_trust_tier(sender)

        # Build filtered response based on trust
        response_payload = context_manager.build_context_response_payload(
            query=payload,
            peer_trust_tier=peer_tier,
        )

        logger.info(
            f"Responding to {sender} with {len(response_payload['items'])} items "
            f"(filtered {response_payload['filtered_by_trust']} by trust)"
        )

        return {
            "type": "context_response",
            "payload": response_payload,
        }

    # ── context_response: receive query results from peer ────────

    @router.handler("context_response")
    def handle_context_response(msg, ctx):
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        items = payload.get("items", [])
        filtered = payload.get("filtered_by_trust", 0)

        logger.info(
            f"Received context_response from {sender}: "
            f"{len(items)} items (peer filtered {filtered})"
        )

        if items:
            count = context_manager.store_peer_context(
                peer_id=sender,
                context_items=items,
                correlation_id=msg.get("correlation_id"),
            )
            logger.info(f"Stored {count} queried context items from {sender}")

        return None

    logger.info(
        "Registered context handlers: context_sync, context_query, context_response"
    )

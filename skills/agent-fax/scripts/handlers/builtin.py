#!/usr/bin/env python3
"""
AgentFax Built-in Handlers — auto-registered by the daemon.

Handles: ping, pong, discover, capabilities, ack, error
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("agentfax.handlers")


def register_builtin_handlers(router, data_dir: str):
    """Register all built-in handlers with the router.

    Args:
        router: MessageRouter instance
        data_dir: AgentFax data directory path
    """
    data_dir = str(Path(data_dir).expanduser())

    # ── ping → auto pong ──────────────────────────────────────────

    @router.handler("ping")
    def handle_ping(msg, ctx):
        sender = msg.get("sender_id", "unknown")
        logger.info(f"Received ping from {sender}")

        # Update peer info
        if ctx.peer_manager:
            ctx.peer_manager.update_seen(
                sender_id=sender,
                wallet=msg.get("_xmtp_sender_wallet"),
            )

        return {
            "type": "pong",
            "payload": {
                "message": f"pong from {ctx.client._sender_id}",
                "received_ping_corr": msg.get("correlation_id"),
                "timestamp": time.time(),
            },
        }

    # ── pong → log receipt ────────────────────────────────────────

    @router.handler("pong")
    def handle_pong(msg, ctx):
        sender = msg.get("sender_id", "unknown")
        latency = None
        payload = msg.get("payload", {})

        # Try to calculate round-trip latency
        ping_corr = payload.get("received_ping_corr", "")
        if ping_corr.startswith("ping_"):
            try:
                ping_ts = float(ping_corr.split("_")[1])
                latency = (time.time() - ping_ts) * 1000  # ms
            except (ValueError, IndexError):
                pass

        logger.info(
            f"Received pong from {sender}"
            + (f" (RTT: {latency:.0f}ms)" if latency else "")
        )

        # Update peer with latency
        if ctx.peer_manager:
            ctx.peer_manager.update_seen(
                sender_id=sender,
                wallet=msg.get("_xmtp_sender_wallet"),
                latency_ms=latency,
            )

        # Record reputation
        if ctx.reputation_manager:
            ctx.reputation_manager.record_interaction(
                sender, "ping_response", True, latency_ms=latency
            )

        return None  # No reply needed

    # ── discover → reply with capabilities ────────────────────────

    @router.handler("discover")
    def handle_discover(msg, ctx):
        sender = msg.get("sender_id", "unknown")
        logger.info(f"Received discover request from {sender}")

        # Load capabilities file
        caps_file = os.path.join(data_dir, "capabilities.json")
        if os.path.exists(caps_file):
            with open(caps_file) as f:
                capabilities = json.load(f)
        else:
            # Default capabilities
            capabilities = {
                "agent_id": ctx.client._sender_id,
                "name": ctx.client._sender_id,
                "skills": [],
                "transport": ["xmtp"],
                "version": "1.0",
            }

        return {
            "type": "capabilities",
            "payload": capabilities,
        }

    # ── capabilities → cache peer's skills ────────────────────────

    @router.handler("capabilities")
    def handle_capabilities(msg, ctx):
        sender = msg.get("sender_id", "unknown")
        payload = msg.get("payload", {})
        skills = payload.get("skills", [])
        logger.info(
            f"Received capabilities from {sender}: "
            f"{len(skills)} skills"
        )

        # Cache to peers
        if ctx.peer_manager:
            ctx.peer_manager.update_capabilities(
                sender_id=sender,
                wallet=msg.get("_xmtp_sender_wallet"),
                capabilities=payload,
            )

        return None

    # ── ack → mark outbox message as acknowledged ─────────────────

    @router.handler("ack")
    def handle_ack(msg, ctx):
        payload = msg.get("payload", {})
        acked_corr = payload.get("correlation_id")
        sender = msg.get("sender_id", "unknown")

        logger.info(f"Received ack from {sender} for corr={acked_corr}")

        if acked_corr and ctx.outbox_store:
            ctx.outbox_store.mark_acked(acked_corr)

        return None

    # ── error → log error from peer ───────────────────────────────

    @router.handler("error")
    def handle_error(msg, ctx):
        payload = msg.get("payload", {})
        sender = msg.get("sender_id", "unknown")
        error_msg = payload.get("error", "unknown error")
        original_type = payload.get("original_type", "?")

        logger.error(
            f"Error from {sender} (re: {original_type}): {error_msg}"
        )
        return None

    logger.info(
        f"Registered {len(router.registered_types)} built-in handlers: "
        f"{', '.join(router.registered_types)}"
    )

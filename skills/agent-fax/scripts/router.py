#!/usr/bin/env python3
"""
AgentFax Message Router — dispatches incoming messages to handlers.

The router is the brain of the daemon. When a message arrives, it:
1. Parses the AgentFax envelope
2. Looks up a registered handler for the message type
3. Dispatches to the handler
4. Sends any response back via the bridge

Usage:
    from router import MessageRouter
    from agentfax_client import AgentFaxClient

    router = MessageRouter()

    @router.handler("echo")
    def handle_echo(msg, ctx):
        return {"type": "echo_response", "payload": {"echo": msg["payload"]}}

    # Process messages
    fax = AgentFaxClient("~/.agentfax")
    for msg in fax.receive(clear=True):
        router.dispatch(msg, fax)
"""

import json
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Any

logger = logging.getLogger("agentfax.router")


class RouterContext:
    """Context passed to message handlers.

    Provides access to the client, store, and peer info
    so handlers can send responses and update state.
    """

    def __init__(self, client, inbox_store=None, outbox_store=None, peer_manager=None):
        self.client = client
        self.inbox_store = inbox_store
        self.outbox_store = outbox_store
        self.peer_manager = peer_manager

    def reply(self, original_msg: dict, msg_type: str, payload: dict) -> Optional[dict]:
        """Send a reply to the sender of the original message.

        Automatically sets correlation_id from the original message.
        """
        sender_wallet = original_msg.get("_xmtp_sender_wallet")
        if not sender_wallet:
            logger.warning("Cannot reply: no sender wallet in message")
            return None

        corr_id = original_msg.get("correlation_id")
        result = self.client.send(
            to_wallet=sender_wallet,
            msg_type=msg_type,
            payload=payload,
            correlation_id=corr_id,
        )

        if self.outbox_store:
            self.outbox_store.record(
                recipient_wallet=sender_wallet,
                msg_type=msg_type,
                payload=payload,
                bridge_response=result,
                correlation_id=corr_id,
            )

        return result


class MessageRouter:
    """Routes incoming AgentFax messages to registered handlers."""

    def __init__(self):
        self._handlers: Dict[str, Callable] = {}
        self._fallback: Optional[Callable] = None
        self._middleware: list = []
        self._stats = {
            "dispatched": 0,
            "handled": 0,
            "unhandled": 0,
            "errors": 0,
        }

    def handler(self, msg_type: str):
        """Decorator to register a handler for a message type.

        The handler function receives (message_dict, RouterContext).
        It can return a dict with {type, payload} to auto-reply,
        or None for no reply.

        Example:
            @router.handler("ping")
            def handle_ping(msg, ctx):
                return {"type": "pong", "payload": {"message": "pong!"}}
        """
        def decorator(func):
            self._handlers[msg_type] = func
            logger.info(f"Registered handler: {msg_type} → {func.__name__}")
            return func
        return decorator

    def register(self, msg_type: str, func: Callable):
        """Register a handler function for a message type (non-decorator)."""
        self._handlers[msg_type] = func
        logger.info(f"Registered handler: {msg_type} → {func.__name__}")

    def set_fallback(self, func: Callable):
        """Set a fallback handler for unrecognized message types."""
        self._fallback = func

    def add_middleware(self, func: Callable):
        """Add middleware that runs before dispatch.

        Middleware receives (message, context) and returns True to continue
        or False to stop processing.
        """
        self._middleware.append(func)

    def dispatch(self, msg: dict, ctx: RouterContext) -> Optional[dict]:
        """Dispatch a message to the appropriate handler.

        Args:
            msg: Parsed AgentFax message dict
            ctx: Router context with client/store access

        Returns:
            Handler result (dict or None)
        """
        self._stats["dispatched"] += 1
        msg_type = msg.get("type", "unknown")
        sender = msg.get("sender_id", "?")
        corr = msg.get("correlation_id", "-")

        logger.debug(f"Dispatching [{msg_type}] from={sender} corr={corr}")

        # Run middleware
        for mw in self._middleware:
            try:
                if not mw(msg, ctx):
                    logger.debug(f"Middleware {mw.__name__} stopped processing")
                    return None
            except Exception as e:
                logger.error(f"Middleware {mw.__name__} error: {e}")

        # Find handler
        handler_func = self._handlers.get(msg_type)
        if not handler_func and self._fallback:
            handler_func = self._fallback

        if not handler_func:
            self._stats["unhandled"] += 1
            logger.warning(f"No handler for [{msg_type}] from={sender}")
            return None

        # Execute handler
        try:
            result = handler_func(msg, ctx)
            self._stats["handled"] += 1

            # Auto-reply if handler returns a response dict
            if isinstance(result, dict) and "type" in result and "payload" in result:
                reply_result = ctx.reply(msg, result["type"], result["payload"])
                if reply_result:
                    logger.info(
                        f"Auto-reply [{result['type']}] to {sender}"
                    )
                return result

            return result

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Handler error for [{msg_type}]: {e}")
            logger.debug(traceback.format_exc())

            # Try to send error response
            try:
                ctx.reply(msg, "error", {
                    "error": str(e),
                    "original_type": msg_type,
                    "correlation_id": corr,
                })
            except Exception:
                pass

            return None

    def process_inbox(self, client, ctx: RouterContext, clear: bool = True) -> int:
        """Pull messages from bridge and dispatch all of them.

        Args:
            client: AgentFaxClient instance
            ctx: Router context
            clear: Clear bridge inbox after reading

        Returns:
            Number of messages processed
        """
        messages = client.receive(clear=clear)
        count = 0
        for msg in messages:
            # Save to store if available
            if ctx.inbox_store:
                ctx.inbox_store.save(msg)

            # Update peer tracking
            if ctx.peer_manager and msg.get("sender_id"):
                ctx.peer_manager.update_seen(
                    sender_id=msg.get("sender_id"),
                    wallet=msg.get("_xmtp_sender_wallet"),
                )

            self.dispatch(msg, ctx)
            count += 1

        return count

    @property
    def stats(self) -> dict:
        """Return dispatch statistics."""
        return dict(self._stats)

    @property
    def registered_types(self) -> list:
        """List all registered message types."""
        return list(self._handlers.keys())

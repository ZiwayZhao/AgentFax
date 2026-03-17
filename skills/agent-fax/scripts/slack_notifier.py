#!/usr/bin/env python3
"""
AgentFax Slack Notifier — collaboration events → Slack notifications.

Makes the invisible agent-to-agent coordination process visible to humans.
Uses only stdlib (urllib.request) — zero external dependencies.

Notification events:
  - Session proposed/accepted/rejected/closed
  - Task accepted/completed/failed
  - Trust tier changes
  - Workflow step progress

Configuration:
  Reads from ~/.agentfax/slack_config.json:
  {
    "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx",
    "bot_token": "xoxb-...",           (optional, for richer API)
    "channel": "#agent-collab",
    "notify_events": ["session", "task", "trust", "workflow"],
    "quiet_hours": {"start": "22:00", "end": "08:00"},
    "summary_only": false
  }

Usage:
    from slack_notifier import SlackNotifier

    notifier = SlackNotifier("~/.agentfax")
    notifier.notify_session_accepted(session_data)
    notifier.notify_task_completed(task_id, skill, duration_ms, output_summary)
"""

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.slack")


# ── Slack Block Kit Builders ─────────────────────────────────────


def _header_block(text: str) -> dict:
    """Block Kit header."""
    return {"type": "header", "text": {"type": "plain_text", "text": text[:150]}}


def _section_block(text: str) -> dict:
    """Block Kit section with markdown."""
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}


def _fields_block(fields: List[str]) -> dict:
    """Block Kit section with fields (max 10)."""
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f[:2000]} for f in fields[:10]],
    }


def _context_block(texts: List[str]) -> dict:
    """Block Kit context (small grey text)."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": t[:2000]} for t in texts[:10]],
    }


def _divider() -> dict:
    return {"type": "divider"}


def _trust_tier_label(tier: int) -> str:
    """Human-readable trust tier."""
    labels = {0: "UNTRUSTED", 1: "KNOWN", 2: "INTERNAL", 3: "PRIVILEGED", 4: "SYSTEM"}
    return labels.get(tier, f"TIER_{tier}")


def _privacy_label(privacy: str) -> str:
    """Human-readable privacy tier."""
    return {"L1_PUBLIC": "Public", "L2_TRUSTED": "Trusted", "L3_PRIVATE": "Private"}.get(
        privacy, privacy
    )


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text for Slack display."""
    s = str(text)
    return s[:max_len] + "..." if len(s) > max_len else s


import re as _re

# Patterns that might leak secrets in error messages
_SENSITIVE_PATTERNS = _re.compile(
    r"(sk-[a-zA-Z0-9]{10,}|xoxb-[^\s]+|/Users/[^\s]+|"
    r"password\s*[:=]\s*\S+|token\s*[:=]\s*\S+|"
    r"api[_-]?key\s*[:=]\s*\S+)",
    _re.IGNORECASE,
)


def _sanitize_error(text: str) -> str:
    """Remove potentially sensitive data from error messages before Slack."""
    sanitized = _SENSITIVE_PATTERNS.sub("[REDACTED]", str(text))
    return _truncate(sanitized, 300)


# ── Skill Card Block Kit ────────────────────────────────────────


def build_skill_card_blocks(card: dict) -> List[dict]:
    """Render a Skill Card as Slack Block Kit blocks."""
    blocks = [
        _header_block(f"Skill: {card.get('skill_name', '?')}"),
        _fields_block([
            f"*Version:* {card.get('skill_version', '?')}",
            f"*Provider:* {card.get('provider', {}).get('agent_id', '?')}",
            f"*Trust Required:* {card.get('trust_requirements', {}).get('min_trust_tier', '?')}",
            f"*Privacy Cap:* {_privacy_label(card.get('trust_requirements', {}).get('max_context_privacy_tier', '?'))}",
        ]),
    ]
    desc = card.get("description", "")
    if desc:
        blocks.append(_section_block(desc))

    pricing = card.get("pricing", {})
    if pricing:
        model = pricing.get("model", "free")
        amount = pricing.get("amount", 0)
        blocks.append(_context_block([f"Pricing: {model} ({amount})"]))

    return blocks


# ── Session Timeline Blocks ─────────────────────────────────────


def build_session_timeline_blocks(session: dict) -> List[dict]:
    """Render a session as a timeline view."""
    state = session.get("state", "?")
    peer = session.get("peer_id", "?")
    state_emoji = {
        "proposed": ":hourglass:",
        "active": ":white_check_mark:",
        "closing": ":warning:",
        "completed": ":checkered_flag:",
        "closed": ":lock:",
        "expired": ":clock1:",
        "rejected": ":x:",
    }.get(state, ":question:")

    blocks = [
        _header_block(f"{state_emoji} Session with {peer}"),
        _fields_block([
            f"*State:* {state}",
            f"*Session ID:* `{session.get('session_id', '?')[:20]}`",
            f"*Trust Tier:* {_trust_tier_label(session.get('agreed_trust_tier', 0))}",
            f"*Privacy Cap:* {_privacy_label(session.get('agreed_max_context_privacy', '?'))}",
            f"*Calls:* {session.get('call_count', 0)} / {session.get('agreed_max_calls', '?')}",
            f"*Tasks:* {session.get('tasks_completed', 0)} done, {session.get('tasks_failed', 0)} failed",
        ]),
    ]

    # Timestamps
    ts = []
    if session.get("created_at"):
        ts.append(f"Created: {session['created_at'][:19]}")
    if session.get("accepted_at"):
        ts.append(f"Accepted: {session['accepted_at'][:19]}")
    if session.get("closed_at"):
        ts.append(f"Closed: {session['closed_at'][:19]}")
    if ts:
        blocks.append(_context_block(ts))

    return blocks


# ── SlackNotifier ────────────────────────────────────────────────


class SlackNotifier:
    """Sends AgentFax events to Slack via webhook or bot token."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        self._config = self._load_config()
        self._enabled = bool(
            self._config.get("webhook_url") or self._config.get("bot_token")
        )
        self._notify_events = set(self._config.get("notify_events", [
            "session", "task", "trust", "workflow",
        ]))
        self._summary_only = self._config.get("summary_only", False)
        self._send_count = 0
        self._error_count = 0

        if self._enabled:
            logger.info(
                f"SlackNotifier enabled: events={self._notify_events}, "
                f"channel={self._config.get('channel', 'webhook default')}"
            )
        else:
            logger.info("SlackNotifier disabled: no webhook_url or bot_token configured")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def stats(self) -> dict:
        return {"sent": self._send_count, "errors": self._error_count}

    def _load_config(self) -> dict:
        """Load Slack config from slack_config.json or environment."""
        config_path = os.path.join(self.data_dir, "slack_config.json")
        config = {}

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
                logger.debug(f"Loaded Slack config from {config_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load Slack config: {e}")

        # Environment overrides
        if os.environ.get("AGENTFAX_SLACK_WEBHOOK"):
            config["webhook_url"] = os.environ["AGENTFAX_SLACK_WEBHOOK"]
        if os.environ.get("AGENTFAX_SLACK_TOKEN"):
            config["bot_token"] = os.environ["AGENTFAX_SLACK_TOKEN"]
        if os.environ.get("AGENTFAX_SLACK_CHANNEL"):
            config["channel"] = os.environ["AGENTFAX_SLACK_CHANNEL"]

        return config

    # ── Low-level send ───────────────────────────────────────

    def _send(self, blocks: List[dict], text: str = "", thread_ts: str = None) -> bool:
        """Send blocks to Slack. Returns True on success."""
        if not self._enabled:
            return False

        webhook_url = self._config.get("webhook_url")
        bot_token = self._config.get("bot_token")
        channel = self._config.get("channel")

        if bot_token and channel:
            return self._send_via_api(bot_token, channel, blocks, text, thread_ts)
        elif webhook_url:
            return self._send_via_webhook(webhook_url, blocks, text)
        return False

    def _send_via_webhook(self, url: str, blocks: List[dict], text: str) -> bool:
        """POST to Slack incoming webhook."""
        payload = {"blocks": blocks}
        if text:
            payload["text"] = text  # Fallback for notifications
        return self._http_post(url, payload)

    def _send_via_api(self, token: str, channel: str, blocks: List[dict],
                      text: str, thread_ts: str = None) -> bool:
        """POST to Slack chat.postMessage API."""
        payload = {
            "channel": channel,
            "blocks": blocks,
            "text": text or "AgentFax notification",
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        return self._http_post(
            "https://slack.com/api/chat.postMessage",
            payload,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _http_post(self, url: str, payload: dict, headers: dict = None) -> bool:
        """HTTP POST with JSON body. Returns True on success."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                body = resp.read().decode("utf-8")
                if resp.status == 200:
                    # Slack Web API returns {"ok": false} on app-level errors
                    try:
                        parsed = json.loads(body)
                        if isinstance(parsed, dict) and parsed.get("ok") is False:
                            logger.warning(f"Slack API error: {parsed.get('error', body[:200])}")
                            self._error_count += 1
                            return False
                    except json.JSONDecodeError:
                        pass  # Webhook returns plain "ok"
                    self._send_count += 1
                    return True
                logger.warning(f"Slack response {resp.status}: {body[:200]}")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            logger.error(f"Slack send failed: {e}")
        except Exception as e:
            logger.error(f"Slack send unexpected error: {e}")

        self._error_count += 1
        return False

    # ── Event helpers (check if event type is enabled) ───────

    def _should_notify(self, event_type: str) -> bool:
        return self._enabled and event_type in self._notify_events

    # ── Session events ───────────────────────────────────────

    def notify_session_proposed(self, peer_id: str, skills: list,
                                trust_tier: int, session_id: str):
        """Notify when a peer proposes a collaboration session."""
        if not self._should_notify("session"):
            return

        blocks = [
            _header_block(f"Session Proposed by {peer_id}"),
            _fields_block([
                f"*Skills:* {', '.join(skills)}",
                f"*Trust Tier:* {_trust_tier_label(trust_tier)}",
                f"*Session:* `{session_id[:20]}`",
            ]),
            _context_block([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]),
        ]
        self._send(blocks, text=f"Session proposed by {peer_id}: {', '.join(skills)}")

    def notify_session_accepted(self, session: dict):
        """Notify when a session is accepted and active."""
        if not self._should_notify("session"):
            return

        peer = session.get("peer_id", "?")
        skills_json = session.get("agreed_skills", "[]")
        skills = json.loads(skills_json) if isinstance(skills_json, str) else skills_json

        blocks = [
            _header_block(f"Session Active with {peer}"),
            _fields_block([
                f"*Skills:* {', '.join(skills)}",
                f"*Trust:* {_trust_tier_label(session.get('agreed_trust_tier', 0))}",
                f"*Privacy Cap:* {_privacy_label(session.get('agreed_max_context_privacy', '?'))}",
                f"*Max Calls:* {session.get('agreed_max_calls', '?')}",
            ]),
            _context_block([
                f"Session: {session.get('session_id', '?')[:20]}",
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            ]),
        ]
        self._send(blocks, text=f"Collaboration started with {peer}")

    def notify_session_rejected(self, peer_id: str, reason: str, session_id: str):
        """Notify when a session proposal is rejected."""
        if not self._should_notify("session"):
            return

        blocks = [
            _header_block(f"Session Rejected by {peer_id}"),
            _section_block(f"*Reason:* {_sanitize_error(reason) or 'No reason given'}"),
            _context_block([f"Session: {session_id[:20]}"]),
        ]
        self._send(blocks, text=f"Session rejected by {peer_id}: {reason}")

    def notify_session_closed(self, session: dict):
        """Notify when a session is closed/completed."""
        if not self._should_notify("session"):
            return

        blocks = build_session_timeline_blocks(session)
        peer = session.get("peer_id", "?")
        state = session.get("state", "closed")
        self._send(blocks, text=f"Session with {peer} {state}")

    # ── Task events ──────────────────────────────────────────

    def notify_task_accepted(self, task_id: str, skill: str, sender: str):
        """Notify when a task is accepted for execution."""
        if not self._should_notify("task"):
            return

        blocks = [
            _section_block(
                f"*Task Accepted:* `{skill}` from {sender}\n"
                f"Task ID: `{task_id[:20]}`"
            ),
        ]
        self._send(blocks, text=f"Executing {skill} for {sender}")

    def notify_task_completed(self, task_id: str, skill: str, sender: str,
                              duration_ms: float = 0, output_summary: str = ""):
        """Notify when a task completes successfully."""
        if not self._should_notify("task"):
            return

        summary = _truncate(output_summary) if output_summary and not self._summary_only else ""
        duration_str = f"{duration_ms:.0f}ms" if duration_ms else "?"

        blocks = [
            _section_block(
                f"*Task Completed:* `{skill}` for {sender}\n"
                f"Duration: {duration_str}"
            ),
        ]
        if summary:
            blocks.append(_context_block([f"Output: {summary}"]))

        self._send(blocks, text=f"Task {skill} completed ({duration_str})")

    def notify_task_failed(self, task_id: str, skill: str, sender: str,
                           error_code: str = "", error_message: str = ""):
        """Notify when a task fails."""
        if not self._should_notify("task"):
            return

        blocks = [
            _section_block(
                f"*Task Failed:* `{skill}` for {sender}\n"
                f"Error: `{error_code}` — {_sanitize_error(error_message)}"
            ),
            _context_block([f"Task: {task_id[:20]}"]),
        ]
        self._send(blocks, text=f"Task {skill} failed: {error_code}")

    # ── Trust events ─────────────────────────────────────────

    def notify_trust_change(self, peer_id: str, old_tier: int, new_tier: int,
                            reason: str = ""):
        """Notify when a peer's trust tier changes."""
        if not self._should_notify("trust"):
            return

        direction = "promoted" if new_tier > old_tier else "demoted"
        blocks = [
            _section_block(
                f"*Trust {direction.title()}:* {peer_id}\n"
                f"{_trust_tier_label(old_tier)} → {_trust_tier_label(new_tier)}"
            ),
        ]
        if reason:
            blocks.append(_context_block([reason]))

        self._send(blocks, text=f"Peer {peer_id} {direction} to {_trust_tier_label(new_tier)}")

    # ── Workflow events ──────────────────────────────────────

    def notify_workflow_started(self, workflow_id: str, name: str, total_steps: int):
        """Notify when a workflow begins execution."""
        if not self._should_notify("workflow"):
            return

        blocks = [
            _header_block(f"Workflow Started: {name}"),
            _fields_block([
                f"*Steps:* {total_steps}",
                f"*Workflow:* `{workflow_id[:20]}`",
            ]),
        ]
        self._send(blocks, text=f"Workflow {name} started ({total_steps} steps)")

    def notify_workflow_step_completed(self, workflow_id: str, step_id: str,
                                       skill: str, step_index: int, total_steps: int):
        """Notify when a workflow step completes."""
        if not self._should_notify("workflow"):
            return

        blocks = [
            _section_block(
                f"*Workflow Step {step_index}/{total_steps}:* `{skill}` completed\n"
                f"Workflow: `{workflow_id[:20]}`"
            ),
        ]
        self._send(blocks, text=f"Workflow step {step_index}/{total_steps}: {skill} done")

    def notify_workflow_completed(self, workflow_id: str, name: str,
                                  total_steps: int, duration_ms: float = 0):
        """Notify when a workflow completes all steps."""
        if not self._should_notify("workflow"):
            return

        blocks = [
            _header_block(f"Workflow Completed: {name}"),
            _fields_block([
                f"*Steps:* {total_steps} completed",
                f"*Duration:* {duration_ms:.0f}ms" if duration_ms else "*Duration:* ?",
            ]),
            _context_block([f"Workflow: {workflow_id[:20]}"]),
        ]
        self._send(blocks, text=f"Workflow {name} completed")

    def notify_workflow_failed(self, workflow_id: str, name: str,
                               failed_step: str, error: str):
        """Notify when a workflow fails."""
        if not self._should_notify("workflow"):
            return

        blocks = [
            _header_block(f"Workflow Failed: {name}"),
            _section_block(
                f"*Failed Step:* `{failed_step}`\n"
                f"*Error:* {_truncate(error, 300)}"
            ),
            _context_block([f"Workflow: {workflow_id[:20]}"]),
        ]
        self._send(blocks, text=f"Workflow {name} failed at {failed_step}")

    # ── Skill Card display ───────────────────────────────────

    def notify_skill_card(self, card: dict, context: str = ""):
        """Display a Skill Card in Slack."""
        if not self._should_notify("session"):
            return

        blocks = build_skill_card_blocks(card)
        if context:
            blocks.insert(0, _section_block(context))

        self._send(
            blocks,
            text=f"Skill Card: {card.get('skill_name', '?')}",
        )

    def close(self):
        """No resources to clean up, but matches other manager patterns."""
        logger.info(
            f"SlackNotifier closed: {self._send_count} sent, "
            f"{self._error_count} errors"
        )

#!/usr/bin/env python3
"""
AgentFax LLM Projection Engine — intelligent context selection for task collaboration.

Replaces hardcoded TASK_CATEGORY_MAP with LLM-driven semantic matching.
The LLM decides which context items are relevant to share for a given task,
respecting privacy tiers.

Architecture:
    1. Hard rules filter first (L3 NEVER shared, trust tier caps privacy)
    2. LLM evaluates remaining items for task relevance
    3. Fallback to static TASK_CATEGORY_MAP if LLM unavailable

Usage:
    from llm_projection import LLMProjectionEngine

    engine = LLMProjectionEngine(provider="anthropic", api_key="sk-...")
    result = engine.project(
        task_description="Review this Python code for security issues",
        task_type="code_review",
        available_items=[...],  # pre-filtered by privacy rules
        peer_name="icy",
    )
    # result.selected_items, result.rationale, result.method
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.llm_projection")

# ── Prompt template ──────────────────────────────────────────────

PROJECTION_SYSTEM_PROMPT = """\
You are a context projection engine for an agent collaboration system.
Your job: given a task description and a list of context items, select ONLY the items
that are genuinely relevant and useful for completing the task.

Rules:
- Be conservative: only select items that would meaningfully help the task
- Consider semantic relevance, not just keyword matching
- A "skill" item about Python is relevant to a code review task, but not to a meeting scheduling task
- A "preference" about coding style is relevant to code review, but not to data analysis
- Return ONLY the IDs of selected items and a brief rationale for each

Respond in valid JSON with this exact structure:
{
  "selected": [
    {"id": "<context_id>", "reason": "<why this item is relevant>"}
  ],
  "overall_rationale": "<1-sentence summary of selection logic>"
}

If NO items are relevant, return: {"selected": [], "overall_rationale": "No items relevant to this task"}
"""

PROJECTION_USER_TEMPLATE = """\
## Task
Type: {task_type}
Description: {task_description}
Peer: {peer_name}

## Available Context Items
{items_block}

Select the relevant items for this task. Return valid JSON only.
"""


@dataclass
class ProjectionResult:
    """Result of an LLM projection."""
    selected_items: List[dict] = field(default_factory=list)
    rationale: str = ""
    method: str = "fallback"  # "llm" or "fallback"
    latency_ms: float = 0.0
    model: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)


class LLMProjectionEngine:
    """Uses LLM to select task-relevant context items."""

    def __init__(
        self,
        provider: str = "anthropic",
        api_key: str = None,
        model: str = None,
    ):
        """Initialize with LLM provider.

        Args:
            provider: "anthropic" or "openai"
            api_key: API key (falls back to env var)
            model: Model name (defaults per provider)
        """
        self.provider = provider.lower()

        if self.provider == "anthropic":
            self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            self.model = model or "claude-sonnet-4-20250514"
        elif self.provider == "openai":
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
            self.model = model or "gpt-4o-mini"
        else:
            raise ValueError(f"Unknown provider: {provider}")

        self._client = None
        self._available = None  # lazy check

        logger.info(f"LLMProjectionEngine: provider={self.provider}, model={self.model}")

    @property
    def is_available(self) -> bool:
        """Check if LLM is available (has API key and client)."""
        if self._available is not None:
            return self._available

        if not self.api_key:
            logger.warning("LLM projection unavailable: no API key")
            self._available = False
            return False

        try:
            self._init_client()
            self._available = True
        except Exception as e:
            logger.warning(f"LLM projection unavailable: {e}")
            self._available = False

        return self._available

    def _init_client(self):
        """Lazy-init the LLM client."""
        if self._client is not None:
            return

        if self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        elif self.provider == "openai":
            import openai
            self._client = openai.OpenAI(api_key=self.api_key)

    def project(
        self,
        task_description: str,
        task_type: str,
        available_items: List[dict],
        peer_name: str = "unknown",
    ) -> ProjectionResult:
        """Select relevant context items using LLM.

        Args:
            task_description: What the task is about
            task_type: Task type (e.g., "code_review", "summarize")
            available_items: Pre-filtered items (already passed privacy rules).
                Each item: {"context_id": ..., "key": ..., "value": ..., "category": ...}
            peer_name: Name of the requesting peer (for context)

        Returns:
            ProjectionResult with selected items and rationale
        """
        if not available_items:
            return ProjectionResult(
                selected_items=[],
                rationale="No items available to project",
                method="empty",
            )

        if not self.is_available:
            logger.info("LLM unavailable, using fallback projection")
            return self._fallback_project(task_type, available_items)

        try:
            return self._llm_project(
                task_description, task_type, available_items, peer_name
            )
        except Exception as e:
            logger.error(f"LLM projection failed: {e}, falling back")
            return self._fallback_project(task_type, available_items)

    def _llm_project(
        self,
        task_description: str,
        task_type: str,
        available_items: List[dict],
        peer_name: str,
    ) -> ProjectionResult:
        """Call LLM to select relevant items."""
        self._init_client()

        # Build items block for prompt
        items_block = self._format_items_for_prompt(available_items)

        user_msg = PROJECTION_USER_TEMPLATE.format(
            task_type=task_type,
            task_description=task_description or f"Execute {task_type} task",
            peer_name=peer_name,
            items_block=items_block,
        )

        start = time.time()

        if self.provider == "anthropic":
            response = self._call_anthropic(user_msg)
        else:
            response = self._call_openai(user_msg)

        latency = (time.time() - start) * 1000

        # Parse LLM response
        selected_ids, rationale, token_usage = self._parse_response(
            response, available_items
        )

        # Map selected IDs back to full items
        items_by_id = {item["context_id"]: item for item in available_items}
        selected_items = [
            items_by_id[sid] for sid in selected_ids if sid in items_by_id
        ]

        result = ProjectionResult(
            selected_items=selected_items,
            rationale=rationale,
            method="llm",
            latency_ms=latency,
            model=self.model,
            token_usage=token_usage,
        )

        logger.info(
            f"LLM projection: {len(selected_items)}/{len(available_items)} items "
            f"selected in {latency:.0f}ms ({self.model})"
        )
        return result

    def _call_anthropic(self, user_msg: str) -> dict:
        """Call Anthropic Claude API."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=PROJECTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        return {
            "content": response.content[0].text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    def _call_openai(self, user_msg: str) -> dict:
        """Call OpenAI API."""
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": PROJECTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
        )
        return {
            "content": response.choices[0].message.content,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
        }

    def _parse_response(
        self, response: dict, available_items: List[dict]
    ) -> tuple:
        """Parse LLM response JSON.

        Returns: (selected_ids, rationale, token_usage)
        """
        content = response["content"]
        token_usage = response.get("usage", {})

        try:
            # Try to extract JSON from response
            data = self._extract_json(content)
            selected = data.get("selected", [])
            rationale = data.get("overall_rationale", "")

            valid_ids = {item["context_id"] for item in available_items}
            selected_ids = [
                s["id"] for s in selected
                if isinstance(s, dict) and s.get("id") in valid_ids
            ]

            # Enhance rationale with per-item reasons
            if selected:
                reasons = [
                    f"- {s.get('id', '?')}: {s.get('reason', '?')}"
                    for s in selected
                    if isinstance(s, dict)
                ]
                if reasons:
                    rationale += "\n" + "\n".join(reasons)

            return selected_ids, rationale, token_usage

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            # If parse fails, fall back to returning all items
            return (
                [item["context_id"] for item in available_items],
                f"LLM response parse failed ({e}), returning all items",
                token_usage,
            )

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response text, handling markdown code blocks."""
        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` block
        if "```" in text:
            start = text.find("```")
            end = text.rfind("```")
            if start != end:
                block = text[start:end]
                # Remove ```json or ``` prefix
                block = block.split("\n", 1)[-1] if "\n" in block else block[3:]
                try:
                    return json.loads(block.strip())
                except json.JSONDecodeError:
                    pass

        # Try finding first { to last }
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            try:
                return json.loads(text[brace_start:brace_end + 1])
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("No valid JSON found in response", text, 0)

    def _format_items_for_prompt(self, items: List[dict]) -> str:
        """Format context items as a readable list for the prompt."""
        lines = []
        for item in items:
            value_preview = str(item.get("value", ""))
            if len(value_preview) > 100:
                value_preview = value_preview[:100] + "..."

            lines.append(
                f"- ID: {item['context_id']}\n"
                f"  Key: {item['key']}\n"
                f"  Category: {item.get('category', 'general')}\n"
                f"  Value: {value_preview}"
            )
        return "\n".join(lines)

    # ── Fallback (static table) ──────────────────────────────────

    def _fallback_project(
        self, task_type: str, available_items: List[dict]
    ) -> ProjectionResult:
        """Fallback to static category mapping when LLM is unavailable."""
        from context_manager import TASK_CATEGORY_MAP

        relevant_categories = TASK_CATEGORY_MAP.get(
            task_type, TASK_CATEGORY_MAP.get("default", ["skill", "general"])
        )

        selected = [
            item for item in available_items
            if item.get("category") in relevant_categories
        ]

        return ProjectionResult(
            selected_items=selected,
            rationale=f"Fallback: matched categories {relevant_categories} for task type '{task_type}'",
            method="fallback",
        )

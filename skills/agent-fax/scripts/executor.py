#!/usr/bin/env python3
"""
AgentFax Task Executor — plugin-based skill execution framework.

Register skills that your agent can perform, and the executor will
handle incoming task_requests by running the matching skill function.

Usage:
    from executor import TaskExecutor

    executor = TaskExecutor()

    @executor.skill("echo")
    def echo_handler(input_data):
        return {"echo": input_data}

    @executor.skill("summarize", description="Summarize text")
    def summarize_handler(input_data):
        return {"summary": "..."}

    # In daemon's router:
    result = executor.execute("echo", {"text": "hello"})
"""

import json
import logging
import os
import time
import traceback
from typing import Callable, Dict, Optional, Any, List

logger = logging.getLogger("agentfax.executor")


class SkillDefinition:
    """Metadata about a registered skill."""

    def __init__(
        self,
        name: str,
        func: Callable,
        description: str = "",
        input_schema: dict = None,
        output_schema: dict = None,
        min_trust_tier: int = 1,
        max_context_privacy_tier: str = "L1_PUBLIC",
    ):
        self.name = name
        self.func = func
        self.description = description or f"Skill: {name}"
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}
        self.min_trust_tier = min_trust_tier
        self.max_context_privacy_tier = max_context_privacy_tier

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "min_trust_tier": self.min_trust_tier,
            "max_context_privacy_tier": self.max_context_privacy_tier,
        }

    def to_skill_card(self, agent_id: str = "", wallet: str = "",
                      display_name: str = "") -> "SkillCard":
        """Build a full Skill Card from this definition.

        Requires skill_registry to be importable.
        """
        from skill_registry import SkillCard
        return SkillCard.from_skill_def(
            self, agent_id=agent_id, wallet=wallet,
            display_name=display_name,
        )


class TaskExecutor:
    """Registers and executes skills for incoming task requests."""

    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}
        self._stats = {
            "executed": 0,
            "succeeded": 0,
            "failed": 0,
        }

    def skill(
        self,
        name: str,
        description: str = "",
        input_schema: dict = None,
        output_schema: dict = None,
        min_trust_tier: int = 1,
        max_context_privacy_tier: str = "L1_PUBLIC",
    ):
        """Decorator to register a skill function.

        The function receives input_data (dict) and returns result (dict).

        Example:
            @executor.skill("echo", description="Echo input back")
            def echo(input_data):
                return {"echo": input_data}
        """
        def decorator(func):
            skill_def = SkillDefinition(
                name=name,
                func=func,
                description=description,
                input_schema=input_schema,
                output_schema=output_schema,
                min_trust_tier=min_trust_tier,
                max_context_privacy_tier=max_context_privacy_tier,
            )
            self._skills[name] = skill_def
            logger.info(f"Registered skill: {name}")
            return func
        return decorator

    def register_skill(
        self,
        name: str,
        func: Callable,
        description: str = "",
        input_schema: dict = None,
        output_schema: dict = None,
        min_trust_tier: int = 1,
        max_context_privacy_tier: str = "L1_PUBLIC",
    ):
        """Register a skill function (non-decorator version)."""
        skill_def = SkillDefinition(
            name=name, func=func,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            min_trust_tier=min_trust_tier,
            max_context_privacy_tier=max_context_privacy_tier,
        )
        self._skills[name] = skill_def
        logger.info(f"Registered skill: {name}")

    def execute(self, skill_name: str, input_data: Any) -> dict:
        """Execute a skill with given input.

        Args:
            skill_name: Name of the skill to execute
            input_data: Input data for the skill

        Returns:
            dict with keys: success, result/error, duration_ms

        Raises:
            ValueError if skill not found
        """
        self._stats["executed"] += 1

        skill_def = self._skills.get(skill_name)
        if not skill_def:
            self._stats["failed"] += 1
            return {
                "success": False,
                "error": f"Unknown skill: {skill_name}",
                "available_skills": list(self._skills.keys()),
            }

        logger.info(f"Executing skill: {skill_name}")
        start = time.time()

        try:
            result = skill_def.func(input_data)
            duration_ms = (time.time() - start) * 1000
            self._stats["succeeded"] += 1

            logger.info(f"Skill {skill_name} completed in {duration_ms:.0f}ms")

            return {
                "success": True,
                "result": result,
                "duration_ms": round(duration_ms, 1),
            }

        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            self._stats["failed"] += 1

            logger.error(f"Skill {skill_name} failed: {e}")
            logger.debug(traceback.format_exc())

            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "duration_ms": round(duration_ms, 1),
            }

    def has_skill(self, name: str) -> bool:
        """Check if a skill is registered."""
        return name in self._skills

    def list_skills(self) -> List[dict]:
        """List all registered skills as dicts (for capabilities response)."""
        return [s.to_dict() for s in self._skills.values()]

    @property
    def skill_names(self) -> List[str]:
        """List registered skill names."""
        return list(self._skills.keys())

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill definition by name."""
        return self._skills.get(name)

    def list_skill_cards(self, agent_id: str = "", wallet: str = "",
                         display_name: str = "") -> List[dict]:
        """List all registered skills as full Skill Card dicts."""
        return [
            s.to_skill_card(agent_id, wallet, display_name).to_dict()
            for s in self._skills.values()
        ]

    @property
    def stats(self) -> dict:
        return dict(self._stats)


# ── Built-in Skills ───────────────────────────────────────────────

def register_builtin_skills(executor: TaskExecutor):
    """Register built-in demonstration skills."""

    @executor.skill("echo", description="Echo input back unchanged")
    def echo(input_data):
        return {"echo": input_data}

    @executor.skill("ping_skill", description="Simple liveness check skill")
    def ping_skill(input_data):
        return {
            "status": "alive",
            "timestamp": time.time(),
            "received": input_data,
        }

    @executor.skill(
        "reverse",
        description="Reverse a text string",
        input_schema={"text": "string"},
        output_schema={"reversed": "string"},
    )
    def reverse(input_data):
        text = input_data if isinstance(input_data, str) else str(input_data.get("text", ""))
        return {"reversed": text[::-1]}

    @executor.skill(
        "word_count",
        description="Count words in text",
        input_schema={"text": "string"},
        output_schema={"count": "integer", "words": "list"},
    )
    def word_count(input_data):
        text = input_data if isinstance(input_data, str) else str(input_data.get("text", ""))
        words = text.split()
        return {"count": len(words), "words": words}

    logger.info(f"Registered {len(executor.skill_names)} built-in skills: "
                f"{', '.join(executor.skill_names)}")

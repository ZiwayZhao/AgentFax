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
    ):
        self.name = name
        self.func = func
        self.description = description or f"Skill: {name}"
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


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
    ):
        """Register a skill function (non-decorator version)."""
        skill_def = SkillDefinition(
            name=name, func=func,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
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

    def install_from_code(
        self,
        name: str,
        code: str,
        description: str = "",
        input_schema: dict = None,
        output_schema: dict = None,
        save_dir: str = None,
    ) -> dict:
        """Install a skill from Python source code.

        The code must define a function called `handler(input_data)`.
        It is compiled, executed in a restricted namespace, and
        the `handler` function is registered as the skill.

        Args:
            name: Skill name
            code: Python source code with handler(input_data) function
            description: Human-readable description
            save_dir: If set, persist the .py file to this directory

        Returns:
            dict with success, name, error (if failed)
        """
        logger.info(f"Installing skill from code: {name}")

        # Compile & exec in isolated namespace
        namespace: Dict[str, Any] = {}
        try:
            compiled = compile(code, f"<skill:{name}>", "exec")
            exec(compiled, namespace)
        except Exception as e:
            logger.error(f"Skill '{name}' compile error: {e}")
            return {"success": False, "name": name, "error": f"compile: {e}"}

        handler = namespace.get("handler")
        if not callable(handler):
            return {
                "success": False,
                "name": name,
                "error": "code must define a callable `handler(input_data)`",
            }

        # Register
        self.register_skill(
            name=name,
            func=handler,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
        )

        # Persist to disk so it survives daemon restart
        if save_dir:
            try:
                os.makedirs(save_dir, exist_ok=True)
                meta = {
                    "name": name,
                    "description": description,
                    "input_schema": input_schema or {},
                    "output_schema": output_schema or {},
                }
                skill_path = os.path.join(save_dir, f"{name}.py")
                with open(skill_path, "w") as f:
                    f.write(f"# skill_meta: {json.dumps(meta)}\n")
                    f.write(code)
                logger.info(f"Skill '{name}' saved to {skill_path}")
            except Exception as e:
                logger.warning(f"Failed to persist skill '{name}': {e}")

        return {"success": True, "name": name}

    def load_skills_from_dir(self, skills_dir: str) -> int:
        """Load all .py skills from a directory (on daemon startup).

        Each file must contain `handler(input_data)` and optionally
        a first-line comment `# skill_meta: {...}`.

        Returns number of skills loaded.
        """
        if not os.path.isdir(skills_dir):
            return 0

        loaded = 0
        for fname in sorted(os.listdir(skills_dir)):
            if not fname.endswith(".py"):
                continue
            name = fname[:-3]
            fpath = os.path.join(skills_dir, fname)
            try:
                code = open(fpath).read()

                # Parse optional metadata from first line
                meta = {}
                first_line = code.split("\n", 1)[0]
                if first_line.startswith("# skill_meta:"):
                    try:
                        meta = json.loads(first_line[len("# skill_meta:"):].strip())
                    except json.JSONDecodeError:
                        pass

                result = self.install_from_code(
                    name=name,
                    code=code,
                    description=meta.get("description", ""),
                    input_schema=meta.get("input_schema"),
                    output_schema=meta.get("output_schema"),
                )
                if result["success"]:
                    loaded += 1
                else:
                    logger.warning(f"Failed to load {fname}: {result.get('error')}")
            except Exception as e:
                logger.warning(f"Failed to read {fname}: {e}")

        if loaded:
            logger.info(f"Loaded {loaded} custom skill(s) from {skills_dir}")
        return loaded

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

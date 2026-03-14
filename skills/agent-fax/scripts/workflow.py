#!/usr/bin/env python3
"""
AgentFax Workflow Manager — DAG-based multi-step task coordination.

Enables multi-step workflows where each step can execute locally or
be delegated to a remote peer. Steps can depend on other steps,
forming a DAG (Directed Acyclic Graph).

Features:
  - DAG validation (reject cycles at creation time)
  - Step dependency tracking (a step runs only when all deps are done)
  - Input template resolution ($step_X.output.key references)
  - State machine for workflow and step lifecycle
  - Retry support per step

Usage:
    from workflow import WorkflowManager

    wm = WorkflowManager("~/.agentfax")

    wf_id = wm.create_workflow("PR Review", steps=[
        {"step_id": "scan",    "skill": "code_scan",   "depends_on": []},
        {"step_id": "analyze", "skill": "security",    "depends_on": ["scan"],
         "target_peer": "icy"},
        {"step_id": "report",  "skill": "summarize",   "depends_on": ["scan", "analyze"]},
    ])

    ready = wm.start_workflow(wf_id)   # → ["scan"]
    wm.complete_step(wf_id, "scan", {"findings": [...]})
    # → ["analyze"] now ready
"""

import enum
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agentfax.workflow")


class StepState(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowState(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowManager:
    """DAG-based workflow engine with dependency tracking."""

    def __init__(self, data_dir: str):
        self.data_dir = str(Path(data_dir).expanduser())
        db_path = os.path.join(self.data_dir, "agentfax_workflows.db")
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
        logger.info(f"WorkflowManager initialized: {db_path}")

    def _init_schema(self):
        """Create workflow tables."""
        cur = self.conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS workflows (
                workflow_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                state TEXT DEFAULT 'draft',
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                timeout_seconds INTEGER DEFAULT 1800,
                initiator_id TEXT,
                error_message TEXT,
                metadata TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_wf_state
            ON workflows(state)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS workflow_steps (
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                step_order INTEGER DEFAULT 0,
                skill TEXT NOT NULL,
                target_peer TEXT,
                input_template TEXT,
                resolved_input TEXT,
                output TEXT,
                depends_on TEXT,
                state TEXT DEFAULT 'pending',
                task_id TEXT,
                context_categories TEXT,
                timeout_seconds INTEGER DEFAULT 300,
                retry_count INTEGER DEFAULT 0,
                retries_used INTEGER DEFAULT 0,
                dispatched_at TEXT,
                completed_at TEXT,
                error_message TEXT,
                PRIMARY KEY (workflow_id, step_id),
                FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ws_workflow
            ON workflow_steps(workflow_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ws_state
            ON workflow_steps(state)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ws_task
            ON workflow_steps(task_id)
        """)

        self.conn.commit()

    # ── Workflow CRUD ─────────────────────────────────────────────

    def create_workflow(
        self,
        name: str,
        steps: List[dict],
        description: str = "",
        timeout_seconds: int = 1800,
        initiator_id: str = None,
        metadata: dict = None,
    ) -> str:
        """Create a new workflow definition.

        Each step dict:
        {
            "step_id": "step_1",
            "skill": "summarize",
            "target_peer": "icy" or None,
            "input_template": {...},
            "depends_on": ["step_0"],
            "timeout_seconds": 300,
            "retry_count": 1,
            "context_categories": ["project"],
        }

        Validates DAG (no cycles). Raises ValueError if invalid.
        """
        # Validate DAG
        self._validate_dag(steps)

        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata) if metadata else None

        cur = self.conn.cursor()

        # Create workflow record
        cur.execute("""
            INSERT INTO workflows
                (workflow_id, name, description, state, created_at,
                 timeout_seconds, initiator_id, metadata)
            VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
        """, (workflow_id, name, description, now,
              timeout_seconds, initiator_id, meta_json))

        # Create step records
        for i, step in enumerate(steps):
            cur.execute("""
                INSERT INTO workflow_steps
                    (workflow_id, step_id, step_order, skill, target_peer,
                     input_template, depends_on, state, timeout_seconds,
                     retry_count, context_categories)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """, (
                workflow_id,
                step["step_id"],
                i,
                step["skill"],
                step.get("target_peer"),
                json.dumps(step.get("input_template")) if step.get("input_template") else None,
                json.dumps(step.get("depends_on", [])),
                step.get("timeout_seconds", 300),
                step.get("retry_count", 0),
                json.dumps(step.get("context_categories")) if step.get("context_categories") else None,
            ))

        self.conn.commit()
        logger.info(f"Created workflow '{name}' ({workflow_id}) with {len(steps)} steps")
        return workflow_id

    def start_workflow(self, workflow_id: str) -> List[str]:
        """Start a workflow. Returns list of step_ids that are immediately ready."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        # Update workflow state
        cur.execute("""
            UPDATE workflows SET state = 'running', started_at = ?
            WHERE workflow_id = ? AND state = 'draft'
        """, (now, workflow_id))

        if cur.rowcount == 0:
            raise ValueError(f"Workflow {workflow_id} not in draft state")

        # Find steps with no dependencies → mark as ready
        cur.execute("""
            SELECT step_id, depends_on FROM workflow_steps
            WHERE workflow_id = ?
        """, (workflow_id,))

        ready_ids = []
        for row in cur.fetchall():
            deps = json.loads(row["depends_on"]) if row["depends_on"] else []
            if not deps:
                cur.execute("""
                    UPDATE workflow_steps SET state = 'ready'
                    WHERE workflow_id = ? AND step_id = ?
                """, (workflow_id, row["step_id"]))
                ready_ids.append(row["step_id"])

        self.conn.commit()
        logger.info(f"Started workflow {workflow_id}: {len(ready_ids)} steps ready")
        return ready_ids

    def get_workflow(self, workflow_id: str) -> Optional[dict]:
        """Get a workflow with all its steps."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM workflows WHERE workflow_id = ?",
            (workflow_id,)
        )
        wf_row = cur.fetchone()
        if not wf_row:
            return None

        wf = dict(wf_row)

        # Get steps
        cur.execute("""
            SELECT * FROM workflow_steps
            WHERE workflow_id = ?
            ORDER BY step_order
        """, (workflow_id,))
        wf["steps"] = [self._step_row_to_dict(row) for row in cur.fetchall()]

        return wf

    def list_workflows(
        self, state: str = None, limit: int = 50
    ) -> List[dict]:
        """List workflows, optionally filtered by state."""
        cur = self.conn.cursor()
        if state:
            cur.execute("""
                SELECT * FROM workflows WHERE state = ?
                ORDER BY created_at DESC LIMIT ?
            """, (state, limit))
        else:
            cur.execute("""
                SELECT * FROM workflows
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
        return [dict(row) for row in cur.fetchall()]

    # ── Step management ───────────────────────────────────────────

    def get_ready_steps(self, workflow_id: str) -> List[dict]:
        """Get steps that are ready to execute (all deps completed)."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM workflow_steps
            WHERE workflow_id = ? AND state = 'ready'
            ORDER BY step_order
        """, (workflow_id,))
        return [self._step_row_to_dict(row) for row in cur.fetchall()]

    def dispatch_step(
        self, workflow_id: str, step_id: str, task_id: str
    ):
        """Mark a step as dispatched with associated task_id."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE workflow_steps
            SET state = 'dispatched', task_id = ?, dispatched_at = ?
            WHERE workflow_id = ? AND step_id = ?
        """, (task_id, now, workflow_id, step_id))
        self.conn.commit()

    def start_step(self, workflow_id: str, step_id: str):
        """Mark a step as in_progress."""
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE workflow_steps SET state = 'in_progress'
            WHERE workflow_id = ? AND step_id = ?
        """, (workflow_id, step_id))
        self.conn.commit()

    def complete_step(
        self, workflow_id: str, step_id: str, output: dict
    ) -> List[str]:
        """Complete a step and return newly ready step_ids.

        After completing a step, check all dependent steps.
        If all their dependencies are now completed, mark them as ready.
        """
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        # Mark step completed
        cur.execute("""
            UPDATE workflow_steps
            SET state = 'completed', output = ?, completed_at = ?
            WHERE workflow_id = ? AND step_id = ?
        """, (json.dumps(output), now, workflow_id, step_id))

        # Find dependent steps that might now be ready
        cur.execute("""
            SELECT step_id, depends_on, state FROM workflow_steps
            WHERE workflow_id = ? AND state = 'pending'
        """, (workflow_id,))

        newly_ready = []
        for row in cur.fetchall():
            deps = json.loads(row["depends_on"]) if row["depends_on"] else []
            if step_id not in deps:
                continue

            # Check if ALL dependencies are completed
            all_done = True
            for dep_id in deps:
                cur.execute("""
                    SELECT state FROM workflow_steps
                    WHERE workflow_id = ? AND step_id = ?
                """, (workflow_id, dep_id))
                dep_row = cur.fetchone()
                if not dep_row or dep_row["state"] != "completed":
                    all_done = False
                    break

            if all_done:
                cur.execute("""
                    UPDATE workflow_steps SET state = 'ready'
                    WHERE workflow_id = ? AND step_id = ?
                """, (workflow_id, row["step_id"]))
                newly_ready.append(row["step_id"])

        self.conn.commit()

        # Check if workflow is fully complete
        self.check_workflow_completion(workflow_id)

        logger.info(
            f"Step {step_id} completed in {workflow_id}. "
            f"Newly ready: {newly_ready}"
        )
        return newly_ready

    def fail_step(
        self, workflow_id: str, step_id: str, error: str
    ):
        """Fail a step. Marks dependent steps as skipped."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        # Check if we can retry
        cur.execute("""
            SELECT retry_count, retries_used FROM workflow_steps
            WHERE workflow_id = ? AND step_id = ?
        """, (workflow_id, step_id))
        row = cur.fetchone()

        if row and row["retries_used"] < row["retry_count"]:
            # Retry: reset to ready
            cur.execute("""
                UPDATE workflow_steps
                SET state = 'ready', retries_used = retries_used + 1,
                    error_message = ?
                WHERE workflow_id = ? AND step_id = ?
            """, (error, workflow_id, step_id))
            self.conn.commit()
            logger.info(
                f"Step {step_id} failed, retrying "
                f"({row['retries_used'] + 1}/{row['retry_count']})"
            )
            return

        # No retries left — mark as failed
        cur.execute("""
            UPDATE workflow_steps
            SET state = 'failed', error_message = ?, completed_at = ?
            WHERE workflow_id = ? AND step_id = ?
        """, (error, now, workflow_id, step_id))

        # Skip dependent steps
        self._skip_dependents(workflow_id, step_id, cur)

        self.conn.commit()

        # Mark workflow as failed
        cur.execute("""
            UPDATE workflows
            SET state = 'failed', error_message = ?, completed_at = ?
            WHERE workflow_id = ?
        """, (f"Step {step_id} failed: {error}", now, workflow_id))
        self.conn.commit()

        logger.error(f"Step {step_id} failed in {workflow_id}: {error}")

    def _skip_dependents(self, workflow_id: str, failed_step_id: str, cur):
        """Recursively skip steps that depend on the failed step."""
        cur.execute("""
            SELECT step_id, depends_on FROM workflow_steps
            WHERE workflow_id = ? AND state IN ('pending', 'ready')
        """, (workflow_id,))

        for row in cur.fetchall():
            deps = json.loads(row["depends_on"]) if row["depends_on"] else []
            if failed_step_id in deps:
                cur.execute("""
                    UPDATE workflow_steps
                    SET state = 'skipped',
                        error_message = ?
                    WHERE workflow_id = ? AND step_id = ?
                """, (f"Skipped: dependency {failed_step_id} failed",
                      workflow_id, row["step_id"]))
                # Recursively skip dependents of skipped step
                self._skip_dependents(workflow_id, row["step_id"], cur)

    # ── Input resolution ──────────────────────────────────────────

    def resolve_step_input(self, workflow_id: str, step_id: str) -> dict:
        """Resolve a step's input_template by substituting previous step outputs.

        Template syntax: "$step_X.output.key" → value from step_X's output

        Examples:
            {"text": "$scan.output.findings"} → {"text": [...findings...]}
            {"from_step": "$step_0.output"} → {"from_step": {...full output...}}
        """
        cur = self.conn.cursor()
        cur.execute("""
            SELECT input_template FROM workflow_steps
            WHERE workflow_id = ? AND step_id = ?
        """, (workflow_id, step_id))
        row = cur.fetchone()

        if not row or not row["input_template"]:
            return {}

        template = json.loads(row["input_template"])
        resolved = self._resolve_refs(template, workflow_id, cur)

        # Save resolved input
        cur.execute("""
            UPDATE workflow_steps SET resolved_input = ?
            WHERE workflow_id = ? AND step_id = ?
        """, (json.dumps(resolved), workflow_id, step_id))
        self.conn.commit()

        return resolved

    def _resolve_refs(self, obj: Any, workflow_id: str, cur) -> Any:
        """Recursively resolve $ref references in an object."""
        if isinstance(obj, str) and obj.startswith("$"):
            return self._resolve_single_ref(obj, workflow_id, cur)
        elif isinstance(obj, dict):
            return {k: self._resolve_refs(v, workflow_id, cur)
                    for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_refs(item, workflow_id, cur) for item in obj]
        return obj

    def _resolve_single_ref(
        self, ref: str, workflow_id: str, cur
    ) -> Any:
        """Resolve a single $ref like "$scan.output.findings".

        Format: $<step_id>.output[.key[.subkey...]]
        """
        parts = ref[1:].split(".")  # Remove $ prefix, split by .
        if len(parts) < 2 or parts[1] != "output":
            logger.warning(f"Invalid ref format: {ref}")
            return ref

        ref_step_id = parts[0]

        cur.execute("""
            SELECT output, state FROM workflow_steps
            WHERE workflow_id = ? AND step_id = ?
        """, (workflow_id, ref_step_id))
        row = cur.fetchone()

        if not row:
            logger.warning(f"Ref step not found: {ref_step_id}")
            return None

        if row["state"] != "completed":
            logger.warning(f"Ref step not completed: {ref_step_id}")
            return None

        output = json.loads(row["output"]) if row["output"] else {}

        # Navigate into nested keys: $scan.output.findings.0
        result = output
        for key in parts[2:]:
            if isinstance(result, dict):
                result = result.get(key)
            elif isinstance(result, list):
                try:
                    result = result[int(key)]
                except (ValueError, IndexError):
                    result = None
            else:
                result = None
            if result is None:
                break

        return result

    # ── Lifecycle ─────────────────────────────────────────────────

    def check_workflow_completion(self, workflow_id: str) -> bool:
        """Check if all steps are done. Mark workflow completed if so."""
        cur = self.conn.cursor()

        cur.execute("""
            SELECT state FROM workflow_steps
            WHERE workflow_id = ?
        """, (workflow_id,))
        states = [row["state"] for row in cur.fetchall()]

        if not states:
            return False

        terminal = {"completed", "failed", "skipped", "cancelled"}
        if all(s in terminal for s in states):
            now = datetime.now(timezone.utc).isoformat()

            # If any step failed, workflow is failed (already handled in fail_step)
            if "failed" in states:
                return True

            # All completed (or skipped/cancelled)
            cur.execute("""
                UPDATE workflows SET state = 'completed', completed_at = ?
                WHERE workflow_id = ? AND state = 'running'
            """, (now, workflow_id))
            self.conn.commit()
            logger.info(f"Workflow {workflow_id} completed")
            return True

        return False

    def cancel_workflow(self, workflow_id: str):
        """Cancel a workflow and all non-completed steps."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()

        cur.execute("""
            UPDATE workflows SET state = 'cancelled', completed_at = ?
            WHERE workflow_id = ?
        """, (now, workflow_id))

        cur.execute("""
            UPDATE workflow_steps
            SET state = 'cancelled'
            WHERE workflow_id = ? AND state IN ('pending', 'ready', 'dispatched', 'in_progress')
        """, (workflow_id,))

        self.conn.commit()
        logger.info(f"Workflow {workflow_id} cancelled")

    def pause_workflow(self, workflow_id: str):
        """Pause a running workflow."""
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE workflows SET state = 'paused'
            WHERE workflow_id = ? AND state = 'running'
        """, (workflow_id,))
        self.conn.commit()

    def resume_workflow(self, workflow_id: str) -> List[str]:
        """Resume a paused workflow. Returns ready step_ids."""
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE workflows SET state = 'running'
            WHERE workflow_id = ? AND state = 'paused'
        """, (workflow_id,))
        self.conn.commit()
        return [s["step_id"] for s in self.get_ready_steps(workflow_id)]

    # ── Step lookup by task_id ────────────────────────────────────

    def get_step_by_task(self, task_id: str) -> Optional[dict]:
        """Find a workflow step by its associated task_id."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM workflow_steps WHERE task_id = ?
        """, (task_id,))
        row = cur.fetchone()
        if row:
            return self._step_row_to_dict(row)
        return None

    # ── DAG validation ────────────────────────────────────────────

    def _validate_dag(self, steps: List[dict]):
        """Validate that steps form a valid DAG (no cycles).

        Uses Kahn's algorithm (topological sort).
        Raises ValueError if cycle detected or invalid references.
        """
        step_ids = {s["step_id"] for s in steps}

        # Validate references
        for step in steps:
            for dep in step.get("depends_on", []):
                if dep not in step_ids:
                    raise ValueError(
                        f"Step '{step['step_id']}' depends on "
                        f"unknown step '{dep}'"
                    )

        # Kahn's algorithm
        in_degree = {s["step_id"]: 0 for s in steps}
        adj = {s["step_id"]: [] for s in steps}

        for step in steps:
            for dep in step.get("depends_on", []):
                adj[dep].append(step["step_id"])
                in_degree[step["step_id"]] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        sorted_count = 0

        while queue:
            node = queue.pop(0)
            sorted_count += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if sorted_count != len(steps):
            raise ValueError(
                "Workflow steps contain a cycle — "
                "DAG validation failed"
            )

    # ── Helpers ───────────────────────────────────────────────────

    def _step_row_to_dict(self, row) -> dict:
        """Convert a step row to dict with parsed JSON fields."""
        d = dict(row)
        for field in ("input_template", "resolved_input", "output",
                       "depends_on", "context_categories"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d

    def close(self):
        """Close the database connection."""
        self.conn.close()

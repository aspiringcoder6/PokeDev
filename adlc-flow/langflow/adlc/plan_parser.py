"""Parse and normalize plan responses from the DSH planner.

The DSH LLM is asked to emit a JSON document describing the execution
plan. This module:

1. Extracts the JSON payload from the LLM's reply (which may be wrapped
   in markdown fences or prose).
2. Validates the payload against :class:`PlanSpec`.
3. Normalizes legacy "linear" plans (single objective per task, no
   subtasks) into the new hierarchical shape so older prompts keep
   working during the migration.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langflow.adlc.plan_models import (
    PLAN_CONTRACT_VERSION,
    PlanSpec,
    SubtaskSpec,
    TaskSpec,
)
from langflow.adlc.plan_validator import PlanValidationError, validate_plan

logger = logging.getLogger(__name__)


class PlanParseError(ValueError):
    """Raised when a DSH reply cannot be turned into a valid PlanSpec."""


# Match a JSON object inside ```json ... ``` fences.
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _find_balanced_json_object(text: str) -> str | None:
    """Find the first balanced ``{...}`` substring in ``text``.

    Handles arbitrary nesting depth by counting braces while respecting
    JSON string literals (so braces inside strings don't confuse the
    counter).
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for end in range(start, len(text)):
            char = text[end]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : end + 1]
        start = text.find("{", start + 1)
    return None


def _extract_json_payload(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM reply."""
    fenced = _FENCED_JSON.search(text)
    if fenced is not None:
        candidate = fenced.group(1)
    else:
        candidate = _find_balanced_json_object(text)
        if candidate is None:
            msg = "DSH reply did not contain a JSON object."
            raise PlanParseError(msg)

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        msg = f"DSH reply contained invalid JSON: {exc.msg} at pos {exc.pos}."
        raise PlanParseError(msg) from exc

    if not isinstance(payload, dict):
        msg = "DSH reply JSON must be an object at the top level."
        raise PlanParseError(msg)
    return payload


def _normalize_legacy_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a legacy linear plan into the hierarchical shape.

    A legacy plan has tasks with ``objective`` but no ``subtasks``. We
    wrap each such task in a single subtask so the executor can treat
    both shapes uniformly.
    """
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return payload

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if "subtasks" in task and task["subtasks"]:
            continue  # already hierarchical
        # Wrap the task's own objective into a single subtask.
        objective = task.get("objective") or task.get("description") or task.get("name") or ""
        deps = task.get("dependencies", [])
        task_id = task.get("id") or "task"
        task["subtasks"] = [
            {
                "id": f"{task_id}.only",
                "name": task.get("name", task_id),
                "description": task.get("description", ""),
                "objective": objective,
                "dependencies": deps,
                "trigger": "on_success",
            }
        ]
        # Clear top-level deps on the task — they now live on the subtask.
        task.pop("dependencies", None)
    return payload


def _ensure_schema_version(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject the schema version if missing so Pydantic accepts the payload."""
    if "schema_version" not in payload:
        payload["schema_version"] = PLAN_CONTRACT_VERSION
    return payload


def parse_plan_response(text: str, *, validate: bool = True) -> PlanSpec:
    """Parse a DSH reply into a validated :class:`PlanSpec`.

    Parameters
    ----------
    text:
        The raw text returned by the DSH LLM.
    validate:
        When ``True`` (default), run :func:`validate_plan` after parsing
        and raise :class:`PlanValidationError` on structural problems.

    Raises
    ------
    PlanParseError:
        The reply could not be turned into a JSON object.
    pydantic.ValidationError:
        The JSON did not match the :class:`PlanSpec` schema.
    PlanValidationError:
        The plan has structural problems (cycles, missing deps, ...).
    """
    payload = _extract_json_payload(text)
    payload = _normalize_legacy_plan(payload)
    payload = _ensure_schema_version(payload)
    plan = PlanSpec.model_validate(payload)
    if validate:
        validate_plan(plan)
    return plan


def plan_to_subtask_specs(plan: PlanSpec) -> list[SubtaskSpec]:
    """Flatten a plan into the list of subtasks that need to be executed.

    Useful for the executor: it can iterate over this list and dispatch
    each subtask as an independent ADLC task.
    """
    return [subtask for task in plan.tasks for subtask in task.subtasks]


def find_task_for_subtask(plan: PlanSpec, subtask_id: str) -> TaskSpec | None:
    """Return the :class:`TaskSpec` that owns the given subtask id."""
    for task in plan.tasks:
        for subtask in task.subtasks:
            if subtask.id == subtask_id:
                return task
    return None


def parse_subtask_response(
    text: str,
    *,
    task_id: str,
    validate: bool = True,
) -> list[SubtaskSpec]:
    """Parse a DSH reply into a list of :class:`SubtaskSpec`.

    Used for on-demand subtask generation: after the user accepts the
    high-level plan, the system SDKs to DSH for each task and asks
    "how would you divide this task into subtasks?". The response is
    a JSON object with a ``subtasks`` array.

    Parameters
    ----------
    text:
        The raw text returned by the DSH LLM.
    task_id:
        The ID of the parent task. Used to scope subtask IDs and for
        error messages.
    validate:
        When ``True`` (default), validate each subtask's dependencies
        are well-formed (no cycles, no missing deps).

    Raises
    ------
    PlanParseError:
        The reply could not be turned into a JSON object.
    pydantic.ValidationError:
        The JSON did not match the :class:`SubtaskSpec` schema.
    """
    payload = _extract_json_payload(text)

    # Accept both {"subtasks": [...]} and {"tasks": [{"subtasks": [...]}]}
    # shapes for flexibility.
    subtasks_data: list[dict[str, Any]] | None = None

    if isinstance(payload, dict):
        if "subtasks" in payload and isinstance(payload["subtasks"], list):
            subtasks_data = payload["subtasks"]
        elif "tasks" in payload and isinstance(payload["tasks"], list):
            # Legacy shape: extract subtasks from the first task.
            for task in payload["tasks"]:
                if isinstance(task, dict) and "subtasks" in task:
                    if isinstance(task["subtasks"], list):
                        subtasks_data = task["subtasks"]
                        break

    if subtasks_data is None:
        msg = (
            f"DSH reply for task {task_id} did not contain a 'subtasks' array."
        )
        raise PlanParseError(msg)

    # Parse each subtask.
    subtasks: list[SubtaskSpec] = []
    for raw in subtasks_data:
        if not isinstance(raw, dict):
            continue
        # Ensure the subtask has an id; if not, generate one.
        if "id" not in raw or not raw["id"]:
            raw["id"] = f"{task_id}.sub-{len(subtasks) + 1}"
        # Ensure dependencies is a list.
        if "dependencies" not in raw:
            raw["dependencies"] = []
        # Ensure trigger is set.
        if "trigger" not in raw:
            raw["trigger"] = "on_success"
        try:
            subtask = SubtaskSpec.model_validate(raw)
            subtasks.append(subtask)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to parse subtask for task %s: %s. Skipping.",
                task_id,
                exc,
            )

    if not subtasks:
        msg = f"DSH reply for task {task_id} contained no valid subtasks."
        raise PlanParseError(msg)

    if validate:
        _validate_subtask_graph(subtasks, task_id)
        _warn_subtask_count(subtasks, task_id)

    return subtasks


def _warn_subtask_count(subtasks: list[SubtaskSpec], task_id: str) -> None:
    """Log a warning when the subtask count is outside the 2–5 guideline.

    The subtask planner prompt asks for 2–5 subtasks per task. A single
    subtask is only acceptable for genuinely atomic work. More than 5
    usually means over-decomposition.
    """
    count = len(subtasks)
    if count == 1:
        logger.warning(
            "Task %s was divided into only 1 subtask. "
            "This is acceptable only for genuinely atomic work — "
            "consider whether the task can be split for parallelism.",
            task_id,
        )
    elif count > 5:
        logger.warning(
            "Task %s was divided into %d subtasks (>5). "
            "This may be over-decomposed — consider grouping related work.",
            task_id,
            count,
        )


def _validate_subtask_graph(subtasks: list[SubtaskSpec], task_id: str) -> None:
    """Validate that the subtask graph is acyclic and all deps exist."""
    ids = {s.id for s in subtasks}
    for subtask in subtasks:
        for dep in subtask.dependencies:
            if dep not in ids:
                logger.warning(
                    "Subtask %s depends on unknown subtask %s. Removing dep.",
                    subtask.id,
                    dep,
                )
                subtask.dependencies.remove(dep)

    # Cycle detection via DFS.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s.id: WHITE for s in subtasks}

    def visit(node_id: str) -> bool:
        color[node_id] = GRAY
        node = next((s for s in subtasks if s.id == node_id), None)
        if node is None:
            return False
        for dep in node.dependencies:
            if dep not in color:
                continue
            if color[dep] == GRAY:
                return True  # cycle
            if color[dep] == WHITE and visit(dep):
                return True
        color[node_id] = BLACK
        return False

    for subtask in subtasks:
        if color[subtask.id] == WHITE:
            if visit(subtask.id):
                logger.warning(
                    "Subtask graph for task %s contains a cycle. "
                    "Breaking cycles by removing back-edges.",
                    task_id,
                )
                # Break cycles by removing the last dep that caused the cycle.
                for s in subtasks:
                    s.dependencies = [
                        d for d in s.dependencies
                        if color.get(d) != GRAY
                    ]


__all__ = [
    "PlanParseError",
    "find_task_for_subtask",
    "parse_plan_response",
    "parse_subtask_response",
    "plan_to_subtask_specs",
]

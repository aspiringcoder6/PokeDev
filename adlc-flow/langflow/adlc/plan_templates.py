"""Deterministic subtask templates — the "mock planner" for task decomposition.

Instead of asking the LLM to produce a :class:`PlanSpec`, every task is
expanded into a fixed DAG of subtasks chosen by its type/name. This mirrors
the subtask templates the frontend uses for demo data, so the backend and
UI stay aligned. Each template subtask is later dispatched as an
independent DSH session by :class:`PlanExecutor`.

The LLM planner remains available (``ADLC_PLAN_SOURCE=llm``) for
objectives that do not fit a template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langflow.adlc.plan_models import (
    ObjectiveText,
    PlanSpec,
    SubtaskSpec,
    SubtaskTrigger,
    TaskSpec,
)

if TYPE_CHECKING:
    from langflow.adlc.models import TaskRun

TEMPLATE_KINDS = ("research", "implementation", "testing", "refactor", "default")

Kind = str


@dataclass(frozen=True, slots=True)
class SubtaskTemplate:
    """One fixed subtask in a template DAG (dependencies are template indices)."""

    name: str
    description: str
    deps: tuple[int, ...] = ()


# Mirrors the frontend fixtures in
# frontend/src/pages/RunDetailPage/__fixtures__/mockSubtaskData.ts so the
# projected subtask names stay consistent between demo and live data.
SUBTASK_TEMPLATES: dict[Kind, tuple[SubtaskTemplate, ...]] = {
    "research": (
        SubtaskTemplate("Search documentation", "Find relevant docs and references"),
        SubtaskTemplate("Read source code", "Analyze existing implementation", deps=(0,)),
        SubtaskTemplate("Identify patterns", "Extract common patterns and conventions", deps=(1,)),
        SubtaskTemplate("Summarize findings", "Write up research summary", deps=(2,)),
    ),
    "implementation": (
        SubtaskTemplate("Design data model", "Define types, schemas, interfaces"),
        SubtaskTemplate("Implement core logic", "Write the main business logic", deps=(0,)),
        SubtaskTemplate("Add error handling", "Handle edge cases and errors", deps=(1,)),
        SubtaskTemplate("Write unit tests", "Cover core logic with tests", deps=(1,)),
        SubtaskTemplate("Integration tests", "Test end-to-end flows", deps=(2, 3)),
        SubtaskTemplate("Final review", "Code review and cleanup", deps=(4,)),
    ),
    "testing": (
        SubtaskTemplate("Set up test environment", "Configure test fixtures and mocks"),
        SubtaskTemplate("Write test cases", "Cover happy path and edge cases", deps=(0,)),
        SubtaskTemplate("Run test suite", "Execute and collect results", deps=(1,)),
        SubtaskTemplate("Final review", "Review test coverage and quality", deps=(2,)),
    ),
    "refactor": (
        SubtaskTemplate("Identify code smells", "Find areas needing improvement"),
        SubtaskTemplate("Plan refactoring", "Design the refactoring approach", deps=(0,)),
        SubtaskTemplate("Apply changes", "Implement the refactoring", deps=(1,)),
        SubtaskTemplate("Verify behavior", "Ensure no regressions", deps=(2,)),
        SubtaskTemplate("Final review", "Review changes and cleanup", deps=(3,)),
    ),
    "default": (
        SubtaskTemplate("Analyze requirements", "Understand what needs to be done"),
        SubtaskTemplate("Plan approach", "Design the solution", deps=(0,)),
        SubtaskTemplate("Execute work", "Implement the solution", deps=(1,)),
        SubtaskTemplate("Verify results", "Check correctness", deps=(2,)),
        SubtaskTemplate("Final review", "Review and finalize", deps=(3,)),
    ),
}

_KIND_RULES: tuple[tuple[Kind, tuple[str, ...]], ...] = (
    ("research", ("research", "analyze", "investigate")),
    ("implementation", ("implement", "build", "code", "create")),
    ("testing", ("test", "verify", "check", "validate")),
    ("refactor", ("refactor", "cleanup", "improve")),
)


def classify_task(task: TaskRun) -> Kind:
    """Pick the template kind from the task type, then the task name."""
    haystack = f"{task.task_type} {task.name}".lower()
    for kind, keywords in _KIND_RULES:
        if any(keyword in haystack for keyword in keywords):
            return kind
    return "default"


def _slug(value: str) -> str:
    """Normalize a task key/name into a NodeId-safe prefix."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-")
    return slug[:64] or "task"


def _subtask_objective(objective: str, template: SubtaskTemplate) -> str:
    """Compose a dispatchable objective for one subtask (min length 10)."""
    head = objective.strip() or template.name
    return f"{head}\n\nSubtask: {template.name} — {template.description}."


def build_task_plan(task: TaskRun) -> PlanSpec:
    """Expand one task run into its fixed subtask DAG as a valid PlanSpec."""
    kind = classify_task(task)
    templates = SUBTASK_TEMPLATES[kind]
    slug = _slug(task.key or task.name)

    input_payload = task.request.input if task.request is not None and isinstance(task.request.input, dict) else {}
    objective = input_payload.get("objective") if isinstance(input_payload.get("objective"), str) else task.name
    objective = objective.strip() or task.name

    subtasks: list[SubtaskSpec] = []
    for index, template in enumerate(templates):
        subtasks.append(
            SubtaskSpec(
                id=f"{slug}.sub-{index + 1}",
                name=template.name,
                description=template.description,
                objective=ObjectiveText(_subtask_objective(objective, template)),
                dependencies=[f"{slug}.sub-{dep + 1}" for dep in template.deps],
                trigger=SubtaskTrigger.ON_SUCCESS,
                metadata={"template_kind": kind},
            )
        )
    return PlanSpec(
        objective=ObjectiveText(objective if len(objective) >= 10 else f"{objective} (task {task.name})"),
        description=f"Deterministic {kind} subtasks for task {task.name}.",
        tasks=[
            TaskSpec(
                id=slug,
                name=task.name,
                description=f"Fixed {kind} subtask decomposition.",
                objective=ObjectiveText(objective if len(objective) >= 10 else f"{objective} (task {task.name})"),
                subtasks=subtasks,
            )
        ],
        metadata={"plan_source": "template", "template_kind": kind},
    )


__all__ = [
    "SUBTASK_TEMPLATES",
    "SubtaskTemplate",
    "build_task_plan",
    "classify_task",
]

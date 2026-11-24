# ruff: noqa: INP001, S101, S106

"""Unit tests for :mod:`langflow.adlc.plan_models`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from langflow.adlc.plan_models import (
    AggregationStrategy,
    PlanSpec,
    SubtaskSpec,
    SubtaskTrigger,
    TaskSpec,
)


def _subtask(
    id: str = "task-1.sub-1",
    *,
    objective: str = "Do something meaningful for the agent to execute.",
    dependencies: list[str] | None = None,
    trigger: SubtaskTrigger = SubtaskTrigger.ON_SUCCESS,
) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        name="Subtask",
        description="",
        objective=objective,
        dependencies=dependencies or [],
        trigger=trigger,
    )


def _task(
    id: str = "task-1",
    *,
    subtasks: list[SubtaskSpec] | None = None,
    dependencies: list[str] | None = None,
    aggregation: AggregationStrategy = AggregationStrategy.COLLECT,
    finalize_subtask_id: str | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=id,
        name="Task",
        description="",
        objective="Top-level objective that the agent will execute end to end.",
        subtasks=subtasks or [_subtask()],
        dependencies=dependencies or [],
        aggregation=aggregation,
        finalize_subtask_id=finalize_subtask_id,
    )


def _plan(tasks: list[TaskSpec] | None = None) -> PlanSpec:
    return PlanSpec(
        objective="Build a thing",
        tasks=tasks or [_task()],
    )


def test_subtask_rejects_self_dependency() -> None:
    with pytest.raises(ValidationError, match="cannot depend on itself"):
        SubtaskSpec(
            id="task-1.sub-1",
            name="Subtask",
            objective="Do something meaningful for the agent to execute.",
            dependencies=["task-1.sub-1"],
        )


def test_subtask_rejects_short_objective() -> None:
    with pytest.raises(ValidationError, match="at least 10 characters"):
        SubtaskSpec(
            id="task-1.sub-1",
            name="Subtask",
            objective="too short",
        )


def test_subtask_rejects_invalid_id() -> None:
    with pytest.raises(ValidationError, match="String should match pattern"):
        SubtaskSpec(
            id="Task-1.Sub-1",  # uppercase not allowed
            name="Subtask",
            objective="Do something meaningful for the agent to execute.",
        )


def test_task_requires_at_least_one_subtask() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        TaskSpec(
            id="task-1",
            name="Task",
            objective="Top-level objective that the agent will execute end to end.",
            subtasks=[],
        )


def test_task_finalize_requires_subtask_id() -> None:
    with pytest.raises(ValidationError, match="finalize_subtask_id is not set"):
        TaskSpec(
            id="task-1",
            name="Task",
            objective="Top-level objective that the agent will execute end to end.",
            subtasks=[_subtask()],
            aggregation=AggregationStrategy.FINALIZE_SUBTASK,
        )


def test_task_finalize_subtask_id_must_match() -> None:
    with pytest.raises(ValidationError, match="does not match any subtask"):
        TaskSpec(
            id="task-1",
            name="Task",
            objective="Top-level objective that the agent will execute end to end.",
            subtasks=[_subtask()],
            aggregation=AggregationStrategy.FINALIZE_SUBTASK,
            finalize_subtask_id="task-1.sub-99",
        )


def test_plan_rejects_duplicate_task_ids() -> None:
    with pytest.raises(ValidationError, match="Duplicate task id"):
        _plan([_task(id="task-1"), _task(id="task-1")])


def test_plan_rejects_duplicate_subtask_ids() -> None:
    with pytest.raises(ValidationError, match="Duplicate subtask id"):
        _plan(
            [
                _task(
                    id="task-1",
                    subtasks=[_subtask(id="task-1.sub-1"), _subtask(id="task-1.sub-1")],
                ),
            ]
        )


def test_plan_rejects_more_than_ten_tasks() -> None:
    tasks = [_task(id=f"task-{i}") for i in range(11)]
    with pytest.raises(ValidationError, match="at most 10"):
        PlanSpec(objective="Build a thing", tasks=tasks)


def test_plan_rejects_zero_tasks() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        PlanSpec(objective="Build a thing", tasks=[])


def test_plan_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        PlanSpec.model_validate(
            {
                "objective": "Build a thing",
                "tasks": [_task().model_dump()],
                "unknown_field": "nope",
            }
        )


def test_plan_accepts_well_formed_input() -> None:
    plan = _plan(
        [
            _task(
                id="task-1",
                subtasks=[
                    _subtask(id="task-1.sub-1"),
                    _subtask(id="task-1.sub-2", dependencies=["task-1.sub-1"]),
                ],
            ),
            _task(
                id="task-2",
                subtasks=[_subtask(id="task-2.sub-1", dependencies=["task-1.sub-2"])],
            ),
        ]
    )
    assert plan.schema_version == "0.1"
    assert len(plan.tasks) == 2
    assert len(plan_to_subtasks(plan)) == 3


def plan_to_subtasks(plan: PlanSpec) -> list[SubtaskSpec]:
    return [s for t in plan.tasks for s in t.subtasks]

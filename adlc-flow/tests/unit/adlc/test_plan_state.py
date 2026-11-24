# ruff: noqa: INP001, S101, S106

"""Unit tests for :mod:`langflow.adlc.plan_state`."""

from __future__ import annotations

from langflow.adlc.plan_models import (
    AggregationStrategy,
    PlanSpec,
    SubtaskSpec,
    TaskSpec,
)
from langflow.adlc.plan_state import (
    PlanState,
    SubtaskState,
    SubtaskStatus,
    TaskState,
    initialize_plan_state,
)


def _subtask(id: str, *, dependencies: list[str] | None = None) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        name=id,
        objective="Do something meaningful for the agent to execute.",
        dependencies=dependencies or [],
    )


def _task(id: str, subtasks: list[SubtaskSpec]) -> TaskSpec:
    return TaskSpec(
        id=id,
        name=id,
        objective="Top-level objective that the agent will execute end to end.",
        subtasks=subtasks,
    )


def _plan() -> PlanSpec:
    return PlanSpec(
        objective="Build a thing",
        tasks=[
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1"),
                    _subtask("task-1.sub-2", dependencies=["task-1.sub-1"]),
                ],
            ),
            _task(
                "task-2",
                [_subtask("task-2.sub-1", dependencies=["task-1.sub-2"])],
            ),
        ],
    )


def test_initialize_creates_pending_states() -> None:
    plan = _plan()
    state = initialize_plan_state(plan, "plan-1")
    assert state.plan_id == "plan-1"
    assert state.status is SubtaskStatus.PENDING
    assert len(state.task_states) == 2
    assert state.total == 3
    assert state.pending == 3
    assert state.succeeded == 0
    assert state.failed == 0


def test_subtask_state_is_terminal() -> None:
    state = SubtaskState(subtask_id="x", task_id="t")
    assert not state.is_terminal
    state.status = SubtaskStatus.SUCCEEDED
    assert state.is_terminal
    state.status = SubtaskStatus.FAILED
    assert state.is_terminal
    state.status = SubtaskStatus.SKIPPED
    assert state.is_terminal
    state.status = SubtaskStatus.CANCELLED
    assert state.is_terminal
    state.status = SubtaskStatus.RUNNING
    assert not state.is_terminal


def test_task_state_aggregates_counts() -> None:
    plan = _plan()
    state = initialize_plan_state(plan, "plan-1")
    task_state = state.task_states["task-1"]
    task_state.subtask_states["task-1.sub-1"].status = SubtaskStatus.SUCCEEDED
    task_state.subtask_states["task-1.sub-2"].status = SubtaskStatus.RUNNING
    assert task_state.total == 2
    assert task_state.succeeded == 1
    assert task_state.running == 1
    assert task_state.pending == 0


def test_task_state_is_terminal_when_all_subtasks_terminal() -> None:
    plan = _plan()
    state = initialize_plan_state(plan, "plan-1")
    task_state = state.task_states["task-1"]
    assert not task_state.is_terminal
    for sub in task_state.subtask_states.values():
        sub.status = SubtaskStatus.SUCCEEDED
    assert task_state.is_terminal


def test_plan_state_is_terminal_when_all_tasks_terminal() -> None:
    plan = _plan()
    state = initialize_plan_state(plan, "plan-1")
    assert not state.is_terminal
    for task_state in state.task_states.values():
        for sub in task_state.subtask_states.values():
            sub.status = SubtaskStatus.SUCCEEDED
    assert state.is_terminal


def test_all_subtask_states_flattens() -> None:
    plan = _plan()
    state = initialize_plan_state(plan, "plan-1")
    all_states = state.all_subtask_states()
    assert len(all_states) == 3
    ids = {s.subtask_id for s in all_states}
    assert ids == {"task-1.sub-1", "task-1.sub-2", "task-2.sub-1"}

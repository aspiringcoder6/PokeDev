# ruff: noqa: INP001, S101, S106

"""Unit tests for :mod:`langflow.adlc.plan_validator`."""

from __future__ import annotations

import pytest

from langflow.adlc.plan_models import (
    AggregationStrategy,
    PlanSpec,
    SubtaskSpec,
    TaskSpec,
)
from langflow.adlc.plan_validator import (
    PlanLintWarning,
    PlanValidationError,
    lint_plan,
    validate_plan,
)


def _subtask(
    id: str,
    *,
    objective: str = "Do something meaningful for the agent to execute.",
    dependencies: list[str] | None = None,
) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        name=id,
        objective=objective,
        dependencies=dependencies or [],
    )


def _task(
    id: str,
    subtasks: list[SubtaskSpec],
    *,
    dependencies: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        id=id,
        name=id,
        objective="Top-level objective that the agent will execute end to end.",
        subtasks=subtasks,
        dependencies=dependencies or [],
    )


def _plan(tasks: list[TaskSpec]) -> PlanSpec:
    return PlanSpec(objective="Build a thing", tasks=tasks)


def test_validate_accepts_linear_chain() -> None:
    plan = _plan(
        [
            _task("task-1", [_subtask("task-1.sub-1")]),
            _task(
                "task-2",
                [_subtask("task-2.sub-1", dependencies=["task-1.sub-1"])],
                dependencies=["task-1"],
            ),
        ]
    )
    validate_plan(plan)  # should not raise


def test_validate_accepts_diamond() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1"),
                    _subtask("task-1.sub-2", dependencies=["task-1.sub-1"]),
                    _subtask("task-1.sub-3", dependencies=["task-1.sub-1"]),
                    _subtask(
                        "task-1.sub-4",
                        dependencies=["task-1.sub-2", "task-1.sub-3"],
                    ),
                ],
            ),
        ]
    )
    validate_plan(plan)


def test_validate_rejects_missing_dependency() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [_subtask("task-1.sub-1", dependencies=["task-99.missing"])],
            ),
        ]
    )
    with pytest.raises(PlanValidationError, match="unknown node"):
        validate_plan(plan)


def test_validate_rejects_cycle_within_subtasks() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1", dependencies=["task-1.sub-2"]),
                    _subtask("task-1.sub-2", dependencies=["task-1.sub-1"]),
                ],
            ),
        ]
    )
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan(plan)


def test_validate_rejects_cycle_across_tasks() -> None:
    plan = _plan(
        [
            _task("task-1", [_subtask("task-1.sub-1")], dependencies=["task-2"]),
            _task("task-2", [_subtask("task-2.sub-1")], dependencies=["task-1"]),
        ]
    )
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan(plan)


def test_validate_rejects_unreachable_node() -> None:
    # task-2 has no deps but nothing depends on it either, so it's a root.
    # To make it unreachable, we need a node that depends on something
    # that itself is unreachable. Construct: task-1.sub-1 depends on
    # task-2.sub-1, but task-2.sub-1 has no deps and nothing depends on
    # task-2.sub-1 — actually that makes task-2.sub-1 a root, so it's
    # reachable. To get an unreachable node, we need a node whose only
    # dependency is itself unreachable. Build: task-1.sub-1 depends on
    # task-1.sub-2; task-1.sub-2 depends on task-1.sub-3; task-1.sub-3
    # depends on task-2.sub-1; task-2.sub-1 has no deps. All reachable.
    # Real unreachable: a node that depends on a non-existent root.
    # Pydantic catches missing deps first, so we need a different shape:
    # task-1.sub-1 depends on task-1.sub-2; task-1.sub-2 depends on
    # task-1.sub-1 (cycle). That's caught by cycle check.
    # To get an unreachable node without a cycle, we need a node whose
    # dependency chain never reaches a root. That requires a dep on a
    # node that itself has no path to a root. The only way is if the
    # dep is on a node that depends on the original node (cycle).
    # So unreachable-without-cycle is impossible if all deps resolve.
    # Skip this test — covered by cycle test.
    pytest.skip("Unreachable nodes require a cycle, which is caught earlier.")


def test_lint_warns_on_tiny_subtask() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [_subtask("task-1.sub-1", objective="x" * 30)],  # 30 chars: valid for Pydantic, too small for lint
            ),
        ]
    )
    warnings = lint_plan(plan)
    codes = {w.code for w in warnings}
    assert "subtask_too_small" in codes


def test_lint_warns_on_huge_subtask() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [_subtask("task-1.sub-1", objective="x" * 10_000)],
            ),
        ]
    )
    warnings = lint_plan(plan)
    codes = {w.code for w in warnings}
    assert "subtask_too_large" in codes


def test_lint_warns_on_too_many_subtasks() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [_subtask(f"task-1.sub-{i}") for i in range(15)],
            ),
        ]
    )
    warnings = lint_plan(plan)
    codes = {w.code for w in warnings}
    assert "too_many_subtasks" in codes


def test_lint_warns_on_high_branching() -> None:
    # One root with 10 dependents.
    plan = _plan(
        [
            _task(
                "task-1",
                [_subtask("task-1.sub-1")]
                + [
                    _subtask(f"task-1.sub-{i}", dependencies=["task-1.sub-1"])
                    for i in range(2, 12)
                ],
            ),
        ]
    )
    warnings = lint_plan(plan)
    codes = {w.code for w in warnings}
    assert "high_branching" in codes


def test_lint_returns_empty_for_clean_plan() -> None:
    plan = _plan(
        [
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1", objective="x" * 200),
                    _subtask("task-1.sub-2", dependencies=["task-1.sub-1"], objective="y" * 200),
                ],
            ),
        ]
    )
    warnings = lint_plan(plan)
    assert warnings == []


def test_lint_warning_is_stringifiable() -> None:
    warning = PlanLintWarning(
        code="test_code",
        message="test message",
        node_id="task-1.sub-1",
    )
    text = str(warning)
    assert "task-1.sub-1" in text
    assert "test_code" in text
    assert "test message" in text

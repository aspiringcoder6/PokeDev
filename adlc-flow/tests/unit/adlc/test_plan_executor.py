# ruff: noqa: INP001, S101, S105, S106

"""Unit tests for :mod:`langflow.adlc.plan_executor`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.adapter_interfaces import StateChangeCallback
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.models import (
    ExecutorTarget,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)
from langflow.adlc.plan_executor import (
    PlanExecutionError,
    PlanExecutor,
)
from langflow.adlc.plan_models import (
    PlanSpec,
    SubtaskSpec,
    SubtaskTrigger,
    TaskSpec,
)
from langflow.adlc.plan_state import SubtaskStatus


# ----------------------------------------------------------------------
# Fake executor
# ----------------------------------------------------------------------


@dataclass
class _FakeTaskExecutor:
    """Stand-in for :class:`DeepSeekHarnessTaskExecutor` that returns scripted results."""

    results: dict[str, TaskResult] = field(default_factory=dict)
    default_status: TaskResultStatus = TaskResultStatus.SUCCEEDED
    default_output: Any = field(default_factory=lambda: {"summary": "done"})
    calls: list[TaskRequest] = field(default_factory=list)
    in_flight: int = 0
    max_in_flight: int = 0
    work_delay_seconds: float = 0.05  # Simulate real work so parallelism is observable.

    async def execute(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> TaskResult:
        import asyncio

        self.calls.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.work_delay_seconds)
            subtask_id = request.input.get("subtask_id", "")
            scripted = self.results.get(subtask_id)
            if scripted is not None:
                return scripted
            return _make_result(
                request,
                status=self.default_status,
                output=self.default_output,
            )
        finally:
            self.in_flight -= 1


def _make_result(
    request: TaskRequest,
    *,
    status: TaskResultStatus,
    output: Any = None,
    error: ServiceError | None = None,
) -> TaskResult:
    now = datetime.now(timezone.utc)
    return TaskResult(
        schema_version="0.1",
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
        status=status,
        output=output or {},
        artifacts=[],
        error=error,
        started_at=now,
        completed_at=now,
    )


def _service_error(code: str = "TEST_ERROR") -> ServiceError:
    return ServiceError(
        schema_version="0.1",
        error_id=uuid4(),
        code=code,
        category="EXECUTION",
        message="test failure",
        retryable=False,
        service="test",
        occurred_at=datetime.now(timezone.utc),
    )


# ----------------------------------------------------------------------
# Plan builders
# ----------------------------------------------------------------------


def _subtask(
    id: str,
    *,
    dependencies: list[str] | None = None,
    trigger: SubtaskTrigger = SubtaskTrigger.ON_SUCCESS,
) -> SubtaskSpec:
    return SubtaskSpec(
        id=id,
        name=id,
        objective="Do something meaningful for the agent to execute.",
        dependencies=dependencies or [],
        trigger=trigger,
    )


def _task(id: str, subtasks: list[SubtaskSpec]) -> TaskSpec:
    return TaskSpec(
        id=id,
        name=id,
        objective="Top-level objective that the agent will execute end to end.",
        subtasks=subtasks,
    )


def _linear_plan() -> PlanSpec:
    """task-1.sub-1 -> task-1.sub-2 -> task-2.sub-1."""
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


def _parallel_plan() -> PlanSpec:
    """Three independent subtasks."""
    return PlanSpec(
        objective="Build a thing",
        tasks=[
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1"),
                    _subtask("task-1.sub-2"),
                    _subtask("task-1.sub-3"),
                ],
            ),
        ],
    )


def _diamond_plan() -> PlanSpec:
    """sub-1 -> {sub-2, sub-3} -> sub-4."""
    return PlanSpec(
        objective="Build a thing",
        tasks=[
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
        ],
    )


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


async def test_executor_runs_linear_plan_in_order() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _linear_plan()

    result = await executor.execute(plan, workflow_run_id=uuid4())

    assert result.status is SubtaskStatus.SUCCEEDED
    assert result.succeeded == 3
    assert result.failed == 0
    assert len(fake.calls) == 3
    # Verify execution order: sub-1 first, then sub-2, then task-2.sub-1.
    order = [c.input["subtask_id"] for c in fake.calls]
    assert order.index("task-1.sub-1") < order.index("task-1.sub-2")
    assert order.index("task-1.sub-2") < order.index("task-2.sub-1")


async def test_executor_runs_parallel_subtasks_concurrently() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake, max_parallel_subtasks=3)  # type: ignore[arg-type]
    plan = _parallel_plan()

    result = await executor.execute(plan, workflow_run_id=uuid4())

    assert result.status is SubtaskStatus.SUCCEEDED
    assert result.succeeded == 3
    # All three should have been in flight at the same time.
    assert fake.max_in_flight == 3


async def test_executor_respects_max_parallel_limit() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake, max_parallel_subtasks=2)  # type: ignore[arg-type]
    plan = _parallel_plan()

    await executor.execute(plan, workflow_run_id=uuid4())

    # With 3 independent subtasks and max_parallel=2, at most 2 should
    # ever be in flight at the same time.
    assert fake.max_in_flight == 2


async def test_executor_runs_diamond_plan() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _diamond_plan()

    result = await executor.execute(plan, workflow_run_id=uuid4())

    assert result.status is SubtaskStatus.SUCCEEDED
    assert result.succeeded == 4
    order = [c.input["subtask_id"] for c in fake.calls]
    assert order.index("task-1.sub-1") < order.index("task-1.sub-2")
    assert order.index("task-1.sub-1") < order.index("task-1.sub-3")
    assert order.index("task-1.sub-2") < order.index("task-1.sub-4")
    assert order.index("task-1.sub-3") < order.index("task-1.sub-4")


async def test_executor_marks_downstream_as_skipped_on_failure() -> None:
    fake = _FakeTaskExecutor(
        results={
            "task-1.sub-1": _make_result(
                TaskRequest(
                    schema_version="0.1",
                    request_id=uuid4(),
                    workflow_run_id=uuid4(),
                    task_run_id=uuid4(),
                    attempt_id=uuid4(),
                    task_definition_id=uuid4(),
                    task_type="plan_subtask",
                    name="x",
                    executor=ExecutorTarget(service="x", operation="x"),
                    input={"subtask_id": "task-1.sub-1"},
                    dependency_task_run_ids=[],
                    idempotency_key="x",
                    requested_at=datetime.now(timezone.utc),
                ),
                status=TaskResultStatus.FAILED,
                error=_service_error(),
            ),
        },
    )
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _linear_plan()

    result = await executor.execute(plan, workflow_run_id=uuid4())

    # task-1.sub-1 failed, task-1.sub-2 and task-2.sub-1 should be skipped.
    assert result.status is SubtaskStatus.FAILED
    task1 = result.task_results["task-1"]
    assert task1.subtask_results["task-1.sub-1"].status is SubtaskStatus.FAILED
    assert task1.subtask_results["task-1.sub-2"].status is SubtaskStatus.SKIPPED
    task2 = result.task_results["task-2"]
    assert task2.subtask_results["task-2.sub-1"].status is SubtaskStatus.SKIPPED


async def test_executor_runs_on_failure_handler() -> None:
    """A subtask with trigger=on_failure should run when its dep fails."""
    plan = PlanSpec(
        objective="Build a thing",
        tasks=[
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1"),
                    _subtask(
                        "task-1.sub-2",
                        dependencies=["task-1.sub-1"],
                        trigger=SubtaskTrigger.ON_FAILURE,
                    ),
                ],
            ),
        ],
    )
    fake = _FakeTaskExecutor(
        results={
            "task-1.sub-1": _make_result(
                TaskRequest(
                    schema_version="0.1",
                    request_id=uuid4(),
                    workflow_run_id=uuid4(),
                    task_run_id=uuid4(),
                    attempt_id=uuid4(),
                    task_definition_id=uuid4(),
                    task_type="plan_subtask",
                    name="x",
                    executor=ExecutorTarget(service="x", operation="x"),
                    input={"subtask_id": "task-1.sub-1"},
                    dependency_task_run_ids=[],
                    idempotency_key="x",
                    requested_at=datetime.now(timezone.utc),
                ),
                status=TaskResultStatus.FAILED,
                error=_service_error(),
            ),
        },
    )
    executor = PlanExecutor(fake)  # type: ignore[arg-type]

    result = await executor.execute(plan, workflow_run_id=uuid4())

    # sub-1 failed, sub-2 (on_failure handler) should have run.
    assert result.task_results["task-1"].subtask_results["task-1.sub-2"].status is SubtaskStatus.SUCCEEDED


async def test_executor_runs_on_completed_handler_regardless() -> None:
    """A subtask with trigger=on_completed should run whether dep succeeds or fails."""
    plan = PlanSpec(
        objective="Build a thing",
        tasks=[
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1"),
                    _subtask(
                        "task-1.sub-2",
                        dependencies=["task-1.sub-1"],
                        trigger=SubtaskTrigger.ON_COMPLETED,
                    ),
                ],
            ),
        ],
    )
    fake = _FakeTaskExecutor(
        results={
            "task-1.sub-1": _make_result(
                TaskRequest(
                    schema_version="0.1",
                    request_id=uuid4(),
                    workflow_run_id=uuid4(),
                    task_run_id=uuid4(),
                    attempt_id=uuid4(),
                    task_definition_id=uuid4(),
                    task_type="plan_subtask",
                    name="x",
                    executor=ExecutorTarget(service="x", operation="x"),
                    input={"subtask_id": "task-1.sub-1"},
                    dependency_task_run_ids=[],
                    idempotency_key="x",
                    requested_at=datetime.now(timezone.utc),
                ),
                status=TaskResultStatus.FAILED,
                error=_service_error(),
            ),
        },
    )
    executor = PlanExecutor(fake)  # type: ignore[arg-type]

    result = await executor.execute(plan, workflow_run_id=uuid4())

    # sub-1 failed, but sub-2 (on_completed) should still run.
    assert result.task_results["task-1"].subtask_results["task-1.sub-2"].status is SubtaskStatus.SUCCEEDED


async def test_executor_rejects_invalid_plan() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    # Build a plan with a cycle.
    plan = PlanSpec(
        objective="Build a thing",
        tasks=[
            _task(
                "task-1",
                [
                    _subtask("task-1.sub-1", dependencies=["task-1.sub-2"]),
                    _subtask("task-1.sub-2", dependencies=["task-1.sub-1"]),
                ],
            ),
        ],
    )
    with pytest.raises(Exception):  # PlanValidationError
        await executor.execute(plan, workflow_run_id=uuid4())


async def test_executor_requires_workflow_run_id() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _linear_plan()
    with pytest.raises(PlanExecutionError, match="workflow_run_id"):
        await executor.execute(plan)


async def test_executor_rejects_zero_max_parallel() -> None:
    fake = _FakeTaskExecutor()
    with pytest.raises(ValueError, match="at least 1"):
        PlanExecutor(fake, max_parallel_subtasks=0)  # type: ignore[arg-type]


async def test_executor_invokes_state_change_callback() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _parallel_plan()

    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    await executor.execute(plan, workflow_run_id=uuid4(), on_state_change=on_state_change)

    # Should have at least one RUNNING transition per subtask.
    assert TaskRunStatus.RUNNING in transitions


async def test_executor_aggregates_results_per_task() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _linear_plan()

    result = await executor.execute(plan, workflow_run_id=uuid4())

    assert "task-1" in result.task_results
    assert "task-2" in result.task_results
    assert result.task_results["task-1"].total == 2
    assert result.task_results["task-2"].total == 1
    assert result.task_results["task-1"].succeeded == 2
    assert result.task_results["task-2"].succeeded == 1


async def test_executor_passes_subtask_objective_to_executor() -> None:
    fake = _FakeTaskExecutor()
    executor = PlanExecutor(fake)  # type: ignore[arg-type]
    plan = _parallel_plan()

    await executor.execute(plan, workflow_run_id=uuid4())

    # Each call should carry the subtask's objective in the input.
    for call in fake.calls:
        assert "objective" in call.input
        assert "subtask_id" in call.input
        assert call.input["objective"].startswith("Do something meaningful")

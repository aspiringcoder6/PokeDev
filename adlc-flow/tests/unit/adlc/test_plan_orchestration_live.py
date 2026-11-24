# ruff: noqa: INP001, S101, S105

"""Unit tests for live plan orchestration: template planning, the subtask
registry, and the observer hooks that expose real subtask progress."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.adapter_interfaces import StateChangeCallback
from langflow.adlc.models import (
    CreateWorkflowRunRequest,
    ExecutorTarget,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
)
from langflow.adlc.plan_executor import PlanExecutor
from langflow.adlc.plan_orchestrator import PlanOrchestratingExecutor
from langflow.adlc.plan_state import SubtaskStatus
from langflow.adlc.plan_templates import SUBTASK_TEMPLATES, build_task_plan, classify_task
from langflow.adlc.plan_validator import validate_plan
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.subtask_registry import SubtaskRegistry, get_subtask_registry
from langflow.adlc.task_subtasks import TaskSubtasksResponse


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _make_task_run(
    *,
    name: str = "Implement backend API",
    task_type: str = "IMPLEMENTATION",
    key: str = "implement_backend",
) -> TaskRun:
    return TaskRun(
        id=uuid4(),
        workflow_run_id=uuid4(),
        task_definition_id=uuid4(),
        key=key,
        name=name,
        task_type=task_type,
        status=TaskRunStatus.RUNNING,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
    )


def _make_request(workflow_run_id: UUID | None = None) -> TaskRequest:
    workflow_run_id = workflow_run_id or uuid4()
    task_run_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="IMPLEMENTATION",
        name="Implement backend API",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={"objective": "Build the payment API endpoints."},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 60_000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}",
        requested_at=datetime.now(),
    )


def _make_result(request: TaskRequest, *, status: TaskResultStatus, output: Any = None) -> TaskResult:
    now = datetime.now()
    return TaskResult(
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
        status=status,
        output=output if output is not None else {},
        artifacts=[],
        error=None,
        started_at=now,
        completed_at=now,
        metadata={"harness_session_id": "dsh-session-42"},
    )


class _RecordingExecutor:
    """Duck-typed DeepSeekHarnessTaskExecutor: one DSH session per execute."""

    def __init__(self, *, fail_subtask: str | None = None) -> None:
        self.calls: list[TaskRequest] = []
        self._fail_subtask = fail_subtask

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        self.calls.append(request)
        now = datetime.now()
        if self._fail_subtask is not None and request.input.get("subtask_id") == self._fail_subtask:
            return TaskResult(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
                status=TaskResultStatus.FAILED,
                output={},
                artifacts=[],
                error=ServiceError(
                    error_id=uuid4(),
                    code="SUBTASK_FAILED",
                    category="EXECUTION",
                    message="boom",
                    retryable=False,
                    service="test",
                    occurred_at=now,
                ),
                started_at=now,
                completed_at=now,
                metadata={"harness_session_id": f"dsh-{len(self.calls)}"},
            )
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "done"},
            artifacts=[],
            error=None,
            started_at=now,
            completed_at=now,
            metadata={"harness_session_id": f"dsh-{len(self.calls)}"},
        )


# ----------------------------------------------------------------------
# Template planning
# ----------------------------------------------------------------------


def test_classify_task_picks_template_by_type_and_name() -> None:
    assert classify_task(_make_task_run(name="Implement backend API")) == "implementation"
    assert classify_task(_make_task_run(name="Research vector stores")) == "research"
    assert classify_task(_make_task_run(name="Verify rollout", task_type="TESTING")) == "testing"
    assert classify_task(_make_task_run(name="Unknown thing", task_type="CUSTOM")) == "default"


def test_build_task_plan_produces_valid_dag() -> None:
    task = _make_task_run()
    plan = build_task_plan(plan_task := task)

    assert plan.metadata["plan_source"] == "template"
    validate_plan(plan)  # raises on invalid DAG
    assert len(plan.tasks) == 1
    task_spec = plan.tasks[0]
    assert task_spec.id == "implement_backend"
    assert len(task_spec.subtasks) == len(SUBTASK_TEMPLATES["implementation"])
    ids = {subtask.id for subtask in task_spec.subtasks}
    assert all(subtask.dependencies and set(subtask.dependencies) <= ids for subtask in task_spec.subtasks[1:])
    assert task_spec.subtasks[0].dependencies == []
    assert plan.objective  # non-empty
    del plan_task


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


def test_registry_register_observe_snapshot() -> None:
    task = _make_task_run()
    plan = build_task_plan(task)
    registry = SubtaskRegistry()
    registry.register_plan(task.workflow_run_id, task.id, plan)

    snapshot = registry.snapshot(task.workflow_run_id, task.id)
    assert snapshot is not None
    assert snapshot.is_mock is False
    assert snapshot.summary.total == len(plan.tasks[0].subtasks)
    assert snapshot.summary.pending == len(plan.tasks[0].subtasks)

    first = plan.tasks[0].subtasks[0]
    registry.observe(
        task.workflow_run_id,
        task.id,
        first.id,
        status=SubtaskStatus.SUCCEEDED,
        attempt_id="att-1",
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        duration_ms=60_000,
        result={"session_id": "dsh-1", "output": {"summary": "done"}},
    )
    updated = registry.snapshot(task.workflow_run_id, task.id)
    assert updated is not None
    row = next(s for s in updated.subtasks if s.id == first.id)
    assert row.status == "succeeded"
    assert row.attempt_id == "att-1"
    assert row.duration_ms == 60_000
    assert row.result is not None and row.result["session_id"] == "dsh-1"
    assert updated.summary.succeeded == 1

    registry.forget(task.workflow_run_id, task.id)
    assert registry.snapshot(task.workflow_run_id, task.id) is None


# ----------------------------------------------------------------------
# PlanOrchestratingExecutor in template mode
# ----------------------------------------------------------------------


async def test_template_mode_dispatches_each_subtask_as_own_session() -> None:
    request = _make_request()
    registry = get_subtask_registry()
    registry.forget(request.workflow_run_id, request.task_run_id)
    fake = _RecordingExecutor()
    executor = PlanOrchestratingExecutor(fake)  # type: ignore[arg-type]

    result = await executor.execute(request, _noop_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    # Every subtask got its own execute() call == its own DSH session.
    expected = len(SUBTASK_TEMPLATES["implementation"])
    assert len(fake.calls) == expected
    assert len({call.request_id for call in fake.calls}) == expected
    # Registry captured the live DAG.
    snapshot = registry.snapshot(request.workflow_run_id, request.task_run_id)
    assert snapshot is not None
    assert snapshot.summary.total == expected
    assert snapshot.summary.succeeded == expected
    assert snapshot.is_mock is False
    # Execution detail captured from the TaskResult metadata.
    assert all(
        subtask.result is not None and subtask.result.get("session_id")
        for subtask in snapshot.subtasks
    )
    registry.forget(request.workflow_run_id, request.task_run_id)


async def test_template_mode_failure_marks_subtasks_in_registry() -> None:
    request = _make_request()
    registry = get_subtask_registry()
    registry.forget(request.workflow_run_id, request.task_run_id)
    # Fail the first subtask; downstream on_success subtasks must be skipped.
    fake = _RecordingExecutor(fail_subtask="task.sub-1")
    executor = PlanOrchestratingExecutor(fake)  # type: ignore[arg-type]

    result = await executor.execute(request, _noop_state_change)

    assert result.status is TaskResultStatus.FAILED
    snapshot = registry.snapshot(request.workflow_run_id, request.task_run_id)
    assert snapshot is not None
    statuses = {subtask.id: subtask.status for subtask in snapshot.subtasks}
    assert statuses["task.sub-1"] == "failed"
    failed_row = next(s for s in snapshot.subtasks if s.id == "task.sub-1")
    assert failed_row.error is not None and failed_row.error["code"] == "SUBTASK_FAILED"
    assert any(status == "skipped" for status in statuses.values())
    registry.forget(request.workflow_run_id, request.task_run_id)


async def test_disabled_planning_delegates_to_base_executor() -> None:
    request = _make_request()
    fake = _RecordingExecutor()
    executor = PlanOrchestratingExecutor(fake, enable_planning=False)  # type: ignore[arg-type]

    result = await executor.execute(request, _noop_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(fake.calls) == 1  # the original task only


async def test_observer_failures_do_not_break_execution() -> None:
    request = _make_request()
    fake = _RecordingExecutor()

    class BrokenRegistry(SubtaskRegistry):
        def observe(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            raise RuntimeError("registry down")

    broken = BrokenRegistry()
    executor = PlanOrchestratingExecutor(fake)  # type: ignore[arg-type]
    executor._plan_executor._observer = (  # noqa: SLF001
        lambda plan, sub_state, result_: (_ for _ in ()).throw(RuntimeError("observer down"))
    )

    result = await executor.execute(request, _noop_state_change)
    assert result.status is TaskResultStatus.SUCCEEDED
    del broken


async def _noop_state_change(_status: TaskRunStatus, _result: TaskResult | None) -> None:
    return None


# ----------------------------------------------------------------------
# run_service integration: registry wins over the static template
# ----------------------------------------------------------------------


async def test_get_task_subtasks_returns_live_registry_snapshot() -> None:
    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Subtask slice",
        definitions=_single_task_definitions(),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    task = run.tasks[0]

    # Before orchestration: static template projection.
    static = await service.get_task_subtasks(run.id, task, owner_id="owner-1")
    assert static.is_mock is True

    # Simulate plan orchestration registering live progress.
    plan = build_task_plan(task)
    get_subtask_registry().register_plan(run.id, task.id, plan)
    first = plan.tasks[0].subtasks[0]
    get_subtask_registry().observe(
        run.id,
        task.id,
        first.id,
        status=SubtaskStatus.RUNNING,
        attempt_id="att-live",
    )
    try:
        live = await service.get_task_subtasks(run.id, task, owner_id="owner-1")
        assert live.is_mock is False
        assert live.summary.running == 1
        assert live.subtasks[0].attempt_id == "att-live"
    finally:
        get_subtask_registry().forget(run.id, task.id)


async def test_prepare_plan_subtasks_stores_in_plan_cache() -> None:
    """prepare_plan_subtasks must store subtasks in the plan-level cache."""
    from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Prepare slice",
        definitions=_single_task_definitions(),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    task = run.tasks[0]
    plan_id = uuid4()

    cache = get_plan_subtask_cache()
    cache.forget(plan_id)
    try:
        # Use the sync variant so the test can assert on the final state.
        result = await service.prepare_plan_subtasks_sync(
            plan_id, [task], owner_id="owner-1"
        )
        assert result["status"] == "ready"
        assert result["total_tasks"] == 1
        assert result["prepared_tasks"] == 1
        assert cache.is_ready(plan_id) is True
        stored = cache.get_subtasks(plan_id, task.id)
        assert stored is not None
        assert len(stored.subtasks) >= 1
    finally:
        cache.forget(plan_id)


async def test_prepare_plan_subtasks_returns_immediately() -> None:
    """prepare_plan_subtasks must return immediately with status 'pending'."""
    from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Async prepare slice",
        definitions=_single_task_definitions(),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    task = run.tasks[0]
    plan_id = uuid4()

    cache = get_plan_subtask_cache()
    cache.forget(plan_id)
    try:
        # The async variant must return immediately with status "pending".
        result = await service.prepare_plan_subtasks(
            plan_id, [task], owner_id="owner-1"
        )
        assert result["status"] == "pending"
        assert result["total_tasks"] == 1
        # Wait for the background task to finish (poll up to 5s).
        for _ in range(100):
            await asyncio.sleep(0.05)
            if cache.is_ready(plan_id):
                break
        assert cache.is_ready(plan_id) is True, (
            f"Background task did not finish; status={cache.get_status(plan_id)}"
        )
    finally:
        cache.forget(plan_id)


async def test_get_task_subtasks_uses_plan_cache_when_available() -> None:
    """get_task_subtasks must return pre-generated subtasks from the plan cache."""
    from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Plan cache slice",
        definitions=_single_task_definitions(),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    task = run.tasks[0]
    plan_id = uuid4()

    cache = get_plan_subtask_cache()
    cache.forget(plan_id)
    try:
        await service.prepare_plan_subtasks_sync(
            plan_id, [task], owner_id="owner-1"
        )
        # Re-key the cached subtasks under the real run_id so
        # get_task_subtasks can find them.
        cached = cache.get_subtasks(plan_id, task.id)
        assert cached is not None
        cache.store_subtasks(run.id, task.id, cached)
        cache.forget(plan_id)

        response = await service.get_task_subtasks(
            run.id, task, owner_id="owner-1"
        )
        assert response.is_mock is True  # mock fallback (no DSH in tests)
        assert len(response.subtasks) >= 1
    finally:
        cache.forget(run.id)


async def test_prepare_plan_subtasks_runs_in_parallel() -> None:
    """Subtask generation must run in parallel, not sequentially.

    We monkey-patch ``_generate_subtasks_for_task`` to sleep for 0.5s
    per task. With 4 tasks, sequential execution would take ~2s; parallel
    execution should finish in well under 1s.
    """
    import time

    from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Parallel prep slice",
        definitions=_single_task_definitions() * 4,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    tasks = run.tasks[:4]
    plan_id = uuid4()

    cache = get_plan_subtask_cache()
    cache.forget(plan_id)

    # Patch the generator to simulate a slow DSH call.
    original = service._generate_subtasks_for_task

    async def slow_generate(task, run_arg):
        await asyncio.sleep(0.5)
        return await original(task, run_arg)

    service._generate_subtasks_for_task = slow_generate  # type: ignore[method-assign]

    try:
        start = time.monotonic()
        await service.prepare_plan_subtasks_sync(
            plan_id, tasks, owner_id="owner-1"
        )
        elapsed = time.monotonic() - start

        # Sequential would be ~2s (4 × 0.5s). Parallel should be ~0.5s.
        # Allow generous margin for CI overhead.
        assert elapsed < 1.5, (
            f"Subtask generation took {elapsed:.2f}s — looks sequential. "
            f"Expected <1.5s for 4 parallel tasks."
        )
        assert cache.is_ready(plan_id) is True
    finally:
        service._generate_subtasks_for_task = original  # type: ignore[method-assign]
        cache.forget(plan_id)


def _single_task_definitions() -> list[Any]:
    from langflow.adlc.models import AdlcTaskDefinition, MockArtifactSpec

    return [
        AdlcTaskDefinition(
            id=uuid4(),
            key="implement_backend",
            name="Implement backend API",
            task_type="IMPLEMENTATION",
            dependencies=[],
            predetermined_output={"summary": "Done."},
            artifact=MockArtifactSpec(
                kind="MOCK",
                name="backend.json",
                media_type="application/json",
                content="{}",
            ),
            delay_ms=0,
        )
    ]


# keep asyncio import meaningful for the async tests above
_ = asyncio

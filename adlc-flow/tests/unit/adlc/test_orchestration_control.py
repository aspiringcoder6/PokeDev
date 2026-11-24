# ruff: noqa: INP001, PLR2004, S101, SLF001

"""Orchestrator control plane: cancel, pause, auto-retry, deadlines, recovery, persistence."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.mock_adapters import utc_now
from langflow.adlc.models import (
    Actor,
    AdlcTaskDefinition,
    ApprovalStatus,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    MockArtifactSpec,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from langflow.adlc.run_service import (
    AdlcRunNotFoundError,
    AdlcRunService,
    AdlcRunStateError,
)

SYSTEM_ACTOR = Actor(type="SYSTEM", id="test", display_name="Test")


def _artifact_spec(key: str) -> MockArtifactSpec:
    return MockArtifactSpec(kind="DOCUMENT", name=f"{key}.txt", media_type="text/plain", content=f"content {key}")


def _definition(key: str, *, dependencies: list[str] | None = None, **overrides: Any) -> AdlcTaskDefinition:
    payload: dict[str, Any] = {
        "id": uuid4(),
        "key": key,
        "name": key.replace("_", " ").title(),
        "task_type": "IMPLEMENTATION",
        "dependencies": dependencies or [],
        "predetermined_output": {"summary": f"Result for {key}."},
        "artifact": _artifact_spec(key),
        "delay_ms": 0,
    }
    payload.update(overrides)
    return AdlcTaskDefinition(**payload)


def _harness_target(operation: str) -> ExecutorTarget:
    return ExecutorTarget(service="agent-provider:deepseek-harness", operation=operation)


def _start_request() -> CreateWorkflowRunRequest:
    flow_id = uuid4()
    return CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0)


def _succeeded_result(request: TaskRequest) -> TaskResult:
    return TaskResult(
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
        status=TaskResultStatus.SUCCEEDED,
        output={"outputs": {"value": request.task_definition_id.hex}},
        artifacts=[],
        error=None,
        metrics=TaskMetrics(duration_ms=1),
        started_at=utc_now(),
        completed_at=utc_now(),
        metadata={},
    )


def _failed_result(request: TaskRequest, *, code: str = "TRANSIENT_FAILURE", retryable: bool = True) -> TaskResult:
    return TaskResult(
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
        status=TaskResultStatus.FAILED,
        output=None,
        artifacts=[],
        error=ServiceError(
            error_id=uuid4(),
            code=code,
            category="EXECUTION" if code != "TASK_DEADLINE_EXCEEDED" else "TIMEOUT",
            message=f"Simulated {code}.",
            retryable=retryable,
            service="test-executor",
            occurred_at=utc_now(),
        ),
        metrics=TaskMetrics(duration_ms=1),
        started_at=utc_now(),
        completed_at=utc_now(),
        metadata={},
    )


_TERMINAL_SCHEDULER_STATUS = {
    TaskResultStatus.SUCCEEDED: TaskRunStatus.SUCCEEDED,
    TaskResultStatus.FAILED: TaskRunStatus.FAILED,
    TaskResultStatus.CANCELLED: TaskRunStatus.CANCELLED,
}


class _GateExecutor:
    """Harness-shaped executor whose first request blocks until released."""

    service_name = "agent-provider:deepseek-harness"
    capabilities = ("harness:session",)

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def execute(self, request: TaskRequest, on_state_change) -> TaskResult:
        self.calls += 1
        await on_state_change(TaskRunStatus.RUNNING, None)
        if self.calls == 1:
            self.started.set()
            await self.release.wait()
        result = _succeeded_result(request)
        await on_state_change(_TERMINAL_SCHEDULER_STATUS[result.status], result)
        return result


class _FlakyExecutor:
    """Fail the first N attempts with a retryable error, then succeed."""

    service_name = "mock"
    capabilities = ("test",)

    def __init__(self, failures: int, *, retryable: bool = True) -> None:
        self.failures = failures
        self.retryable = retryable
        self.attempts = 0

    async def execute(self, request: TaskRequest, on_state_change) -> TaskResult:
        self.attempts += 1
        await on_state_change(TaskRunStatus.RUNNING, None)
        if self.attempts <= self.failures:
            result = _failed_result(request, retryable=self.retryable)
        else:
            result = _succeeded_result(request)
        await on_state_change(_TERMINAL_SCHEDULER_STATUS[result.status], result)
        return result


class _HangingExecutor:
    """Never report a terminal result; the coordinator deadline must intervene."""

    service_name = "mock"
    capabilities = ("test",)

    async def execute(self, request: TaskRequest, on_state_change) -> TaskResult:
        await on_state_change(TaskRunStatus.RUNNING, None)
        await asyncio.sleep(3600)
        return _succeeded_result(request)  # pragma: no cover - never reached


class _RecordingPersistence:
    """In-memory AdlcRunPersistence double that counts snapshot writes."""

    def __init__(self) -> None:
        self.snapshots: dict[UUID, tuple[str, WorkflowRun, list[AdlcTaskDefinition]]] = {}
        self.save_count = 0

    async def save(self, *, owner_id: str, run: WorkflowRun, definitions: dict[str, AdlcTaskDefinition]) -> None:
        self.save_count += 1
        self.snapshots[run.id] = (
            owner_id,
            run.model_copy(deep=True),
            [definition.model_copy(deep=True) for definition in definitions.values()],
        )

    async def load(self, *, owner_id: str | None = None) -> list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]]:
        rows = [row for row in self.snapshots.values() if owner_id is None or row[0] == owner_id]
        rows.sort(key=lambda row: row[1].created_at)
        return [
            (owner, run.model_copy(deep=True), [d.model_copy(deep=True) for d in defs]) for owner, run, defs in rows
        ]

    async def clear(self) -> None:
        self.snapshots.clear()


async def _wait_for_status(
    service: AdlcRunService, run_id: UUID, owner_id: str, status: WorkflowRunStatus
) -> WorkflowRun:
    for _ in range(500):
        run = await service.get_run(run_id, owner_id=owner_id)
        if run.status is status:
            return run
        await asyncio.sleep(0.01)
    pytest.fail(f"Run did not reach {status} in time; last status {run.status}")


# ---------------------------------------------------------------------------
# P0-1: cancel
# ---------------------------------------------------------------------------


async def test_cancel_background_run_midflight_cancels_tasks_and_run() -> None:
    executor = _GateExecutor()
    service = AdlcRunService(executor)
    definitions = [
        _definition("coding", executor_target=_harness_target("coding")),
        _definition("review", dependencies=["coding"], executor_target=_harness_target("review")),
    ]
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Cancel slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    assert started.status is WorkflowRunStatus.RUNNING
    await asyncio.wait_for(executor.started.wait(), timeout=2)

    cancelled = await service.cancel_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)

    assert cancelled.status is WorkflowRunStatus.CANCELLED
    coding = next(task for task in cancelled.tasks if task.key == "coding")
    review = next(task for task in cancelled.tasks if task.key == "review")
    assert coding.status is TaskRunStatus.CANCELLED
    assert review.status is TaskRunStatus.CANCELLED
    assert cancelled.completed_at is not None
    assert any(event.event_type == "workflow_run.cancelled" for event in cancelled.events)
    assert any(
        event.event_type == "task_run.cancelled" and event.payload.get("reason") == "workflow_cancelled"
        for event in cancelled.events
    )
    with pytest.raises(AdlcRunStateError, match="terminal"):
        await service.cancel_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)
    await service.clear()


async def test_cancel_waiting_approval_run_cancels_pending_approval() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _definition(
            "approval",
            dependencies=["coding"],
            task_type="APPROVAL",
            executor_target=ExecutorTarget(service="control:approval", operation="after-task"),
            approval_gate="ACTION",
        ),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Cancel approval slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert run.approval_requests[0].status is ApprovalStatus.PENDING

    cancelled = await service.cancel_run(run.id, owner_id="owner-1", actor=SYSTEM_ACTOR)

    assert cancelled.status is WorkflowRunStatus.CANCELLED
    assert cancelled.approval_requests[0].status is ApprovalStatus.CANCELLED
    assert cancelled.tasks[-1].status is TaskRunStatus.CANCELLED
    assert any(event.event_type == "approval_request.cancelled" for event in cancelled.events)


async def test_cancel_terminal_run_is_rejected() -> None:
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Terminal slice",
        definitions=[_definition("only")],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.SUCCEEDED
    with pytest.raises(AdlcRunStateError, match="terminal"):
        await service.cancel_run(run.id, owner_id="owner-1", actor=SYSTEM_ACTOR)


async def test_cancel_runs_outside_owner_are_not_visible() -> None:
    executor = _GateExecutor()
    service = AdlcRunService(executor)
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Owner slice",
        definitions=[_definition("coding", executor_target=_harness_target("coding"))],
        request=_start_request(),
        owner_id="owner-1",
    )
    with pytest.raises(AdlcRunNotFoundError):
        await service.cancel_run(started.id, owner_id="owner-2", actor=SYSTEM_ACTOR)
    await service.cancel_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)
    await service.clear()


# ---------------------------------------------------------------------------
# P0-2: pause / resume
# ---------------------------------------------------------------------------


async def test_pause_stops_new_dispatch_until_resume() -> None:
    executor = _GateExecutor()
    service = AdlcRunService(executor)
    definitions = [
        _definition("first", executor_target=_harness_target("first")),
        _definition("second", dependencies=["first"], executor_target=_harness_target("second")),
    ]
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Pause slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    await asyncio.wait_for(executor.started.wait(), timeout=2)

    paused = await service.pause_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)
    assert paused.status is WorkflowRunStatus.RUNNING  # in-flight work still running

    executor.release.set()
    paused_run = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.PAUSED)
    first = next(task for task in paused_run.tasks if task.key == "first")
    second = next(task for task in paused_run.tasks if task.key == "second")
    assert first.status is TaskRunStatus.SUCCEEDED
    assert second.status is TaskRunStatus.PENDING  # pause blocked the follow-up dispatch
    paused_event = next(event for event in paused_run.events if event.event_type == "workflow_run.paused")
    assert paused_event.payload["reason"] == "user_pause"

    with pytest.raises(AdlcRunStateError, match="already paused"):
        await service.pause_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)

    resumed = await service.resume_run(started.id, owner_id="owner-1")
    assert resumed.status is WorkflowRunStatus.RUNNING
    final = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert second.id in {task.id for task in final.tasks if task.status is TaskRunStatus.SUCCEEDED}
    await service.clear()


async def test_pause_rejects_waiting_approval_and_terminal_runs() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _definition(
            "approval",
            dependencies=["coding"],
            task_type="APPROVAL",
            executor_target=ExecutorTarget(service="control:approval", operation="after-task"),
            approval_gate="ACTION",
        ),
    ]
    waiting = await service.start_run(
        flow_id=uuid4(),
        flow_name="Pause approval slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    assert waiting.status is WorkflowRunStatus.WAITING_APPROVAL
    with pytest.raises(AdlcRunStateError, match="approval"):
        await service.pause_run(waiting.id, owner_id="owner-1", actor=SYSTEM_ACTOR)

    done = await service.approve(
        waiting.approval_requests[0].approval_request_id,
        owner_id="owner-1",
        actor=SYSTEM_ACTOR,
        comment=None,
    )
    assert done.status is WorkflowRunStatus.SUCCEEDED
    with pytest.raises(AdlcRunStateError, match="terminal"):
        await service.pause_run(done.id, owner_id="owner-1", actor=SYSTEM_ACTOR)


async def test_emit_event_on_user_paused_run_records_but_does_not_resume() -> None:
    executor = _GateExecutor()
    service = AdlcRunService(executor)
    definitions = [
        _definition("first", executor_target=_harness_target("first")),
        _definition("second", dependencies=["first"], executor_target=_harness_target("second")),
    ]
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Pause event slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    await asyncio.wait_for(executor.started.wait(), timeout=2)
    await service.pause_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)
    executor.release.set()
    await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.PAUSED)

    recorded = await service.emit_event(started.id, "external.signal", owner_id="owner-1", payload={"k": "v"})

    assert recorded.status is WorkflowRunStatus.PAUSED
    assert any(
        event.event_type == "workflow_run.event_emitted" and event.payload.get("event_name") == "external.signal"
        for event in recorded.events
    )
    resumed = await service.resume_run(started.id, owner_id="owner-1")
    assert resumed.status is WorkflowRunStatus.RUNNING
    final = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in final.tasks)
    await service.clear()


# ---------------------------------------------------------------------------
# P1-5: automatic retry with backoff
# ---------------------------------------------------------------------------


async def test_auto_retry_succeeds_after_retryable_failure() -> None:
    executor = _FlakyExecutor(failures=1)
    service = AdlcRunService(executor)
    definition = _definition("flaky", constraints={"max_attempts": 2, "retry_backoff_ms": 0})

    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Auto retry slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.SUCCEEDED
    task = run.tasks[0]
    assert task.status is TaskRunStatus.SUCCEEDED
    assert task.retry_count == 1
    assert executor.attempts == 2
    retry_events = [event for event in run.events if event.event_type == "task_run.retry_scheduled"]
    assert len(retry_events) == 1
    assert retry_events[0].payload["retry_count"] == 1
    assert retry_events[0].payload["backoff_ms"] == 0
    assert retry_events[0].payload["error_code"] == "TRANSIENT_FAILURE"


async def test_auto_retry_backoff_uses_exponential_delay() -> None:
    executor = _FlakyExecutor(failures=2)
    service = AdlcRunService(executor)
    definition = _definition("flaky", constraints={"max_attempts": 3, "retry_backoff_ms": 10})

    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Backoff slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.SUCCEEDED
    backoffs = [event.payload["backoff_ms"] for event in run.events if event.event_type == "task_run.retry_scheduled"]
    assert backoffs == [10, 20]


async def test_auto_retry_budget_exhaustion_pauses_for_manual_retry() -> None:
    executor = _FlakyExecutor(failures=99)
    service = AdlcRunService(executor)
    definition = _definition("always", constraints={"max_attempts": 2, "retry_backoff_ms": 0})

    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Exhaustion slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.PAUSED
    assert run.tasks[0].status is TaskRunStatus.FAILED
    assert run.tasks[0].retry_count == 1
    assert executor.attempts == 2
    paused_event = next(event for event in run.events if event.event_type == "workflow_run.paused")
    assert paused_event.payload["reason"] == "retry_available"

    with pytest.raises(AdlcRunStateError, match="exhausted"):
        await service.retry_task(run.tasks[0].id, owner_id="owner-1")


async def test_non_retryable_failure_skips_auto_retry() -> None:
    executor = _FlakyExecutor(failures=99, retryable=False)
    service = AdlcRunService(executor)
    definition = _definition("terminal", constraints={"max_attempts": 2, "retry_backoff_ms": 0})

    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Non retryable slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.PAUSED
    assert run.tasks[0].retry_count == 0
    assert executor.attempts == 1
    assert not any(event.event_type == "task_run.retry_scheduled" for event in run.events)


# ---------------------------------------------------------------------------
# P1-6: coordinator deadline
# ---------------------------------------------------------------------------


async def test_coordinator_deadline_fails_hung_executor_without_retry_budget() -> None:
    executor = _HangingExecutor()
    service = AdlcRunService(executor)
    definition = _definition("hung", constraints={"timeout_ms": 50, "max_attempts": 1})

    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Deadline slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )

    assert run.status is WorkflowRunStatus.PAUSED
    task = run.tasks[0]
    assert task.status is TaskRunStatus.FAILED
    assert task.result is not None
    assert task.result.error is not None
    assert task.result.error.code == "TASK_DEADLINE_EXCEEDED"
    assert task.result.metadata["coordinator_deadline"] is True
    assert task.worker_id is not None  # retained for audit after the attempt ends
    assert task.deadline_at is None


async def test_deadline_renews_while_task_waits_for_human_decision() -> None:
    class _HumanGateExecutor:
        service_name = "agent-provider:deepseek-harness"
        capabilities = ("harness:session",)

        def __init__(self) -> None:
            self.waiting = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, request: TaskRequest, on_state_change) -> TaskResult:
            await on_state_change(TaskRunStatus.RUNNING, None)
            await on_state_change(TaskRunStatus.WAITING_APPROVAL, None)
            self.waiting.set()
            await asyncio.sleep(0.15)  # longer than the coordinator deadline
            await self.release.wait()
            await on_state_change(TaskRunStatus.RUNNING, None)
            result = _succeeded_result(request)
            await on_state_change(_TERMINAL_SCHEDULER_STATUS[result.status], result)
            return result

    executor = _HumanGateExecutor()
    service = AdlcRunService(executor)
    definition = _definition(
        "hitl",
        constraints={"timeout_ms": 50},
        executor_target=_harness_target("hitl"),
    )
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Deadline renewal slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert started.status is WorkflowRunStatus.RUNNING
    await asyncio.wait_for(executor.waiting.wait(), timeout=2)
    await asyncio.sleep(0.2)  # the 50 ms deadline elapses twice while humans decide

    executor.release.set()
    run = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert run.tasks[0].status is TaskRunStatus.SUCCEEDED
    await service.clear()


# ---------------------------------------------------------------------------
# P1-4: recovery after restart + P1-3: persistence boundaries
# ---------------------------------------------------------------------------


async def test_recovery_reattaches_orphaned_attempt_after_restart() -> None:
    persistence = _RecordingPersistence()
    blocker = _GateExecutor()
    first = AdlcRunService(blocker, persistence=persistence)
    started = await first.start_run(
        flow_id=uuid4(),
        flow_name="Recovery slice",
        definitions=[_definition("coding", executor_target=_harness_target("coding"))],
        request=_start_request(),
        owner_id="owner-1",
    )
    await asyncio.wait_for(blocker.started.wait(), timeout=2)
    # Snapshot once the attempt is RUNNING so the store holds an orphaned attempt.
    running = await first.get_run(started.id, owner_id="owner-1")
    assert running.tasks[0].status is TaskRunStatus.RUNNING
    await persistence.save(
        owner_id="owner-1",
        run=running,
        definitions=first._runs[started.id].definitions,
    )

    await first.shutdown()

    class _ResumingExecutor(_GateExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.resumed_requests: list[TaskRequest] = []

        async def resume(self, request: TaskRequest, on_state_change) -> TaskResult:
            self.resumed_requests.append(request)
            result = _succeeded_result(request)
            await on_state_change(TaskRunStatus.SUCCEEDED, result)
            return result

    # A new coordinator observes the frozen request through resume, never execute.
    observer = _ResumingExecutor()
    replacement = AdlcRunService(executor=observer, persistence=persistence)
    recovered = await replacement.get_run(started.id, owner_id="owner-1")

    assert recovered.status is WorkflowRunStatus.RUNNING
    final = await _wait_for_status(replacement, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert final.tasks[0].status is TaskRunStatus.SUCCEEDED
    assert final.tasks[0].request == running.tasks[0].request
    assert final.tasks[0].current_attempt_id == running.tasks[0].current_attempt_id
    assert observer.resumed_requests == [running.tasks[0].request]
    assert observer.calls == 0
    assert replacement._recovery_done is True
    await replacement.clear()


async def test_recovery_leaves_paused_and_approval_runs_untouched() -> None:
    persistence = _RecordingPersistence()
    service = AdlcRunService(persistence=persistence)
    definitions = [
        _definition("coding", simulate_failure=True),
        _definition(
            "approval",
            dependencies=["coding"],
            task_type="APPROVAL",
            executor_target=ExecutorTarget(service="control:approval", operation="after-task"),
            approval_gate="ACTION",
        ),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Recovery paused slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.PAUSED  # simulate_failure is non-retryable

    replacement = AdlcRunService(persistence=persistence)
    restored = await replacement.get_run(run.id, owner_id="owner-1")

    assert restored.status is WorkflowRunStatus.PAUSED
    assert replacement._runs[run.id].scheduler_task is None
    assert replacement._runs[run.id].pause_reason == "retry_available"
    await service.clear()
    await replacement.clear()


async def test_recovery_preserves_concurrency_budget_while_observing_an_attempt() -> None:
    persistence = _RecordingPersistence()
    original_executor = _GateExecutor()
    first = AdlcRunService(original_executor, persistence=persistence)
    started = await first.start_run(
        flow_id=uuid4(),
        flow_name="Recovery concurrency",
        definitions=[
            _definition("coding", executor_target=_harness_target("coding")),
            _definition("review", executor_target=_harness_target("review")),
        ],
        request=_start_request().model_copy(update={"max_concurrency": 1}),
        owner_id="owner-1",
    )
    await asyncio.wait_for(original_executor.started.wait(), timeout=2)
    running = await first.get_run(started.id, owner_id="owner-1")
    await first.shutdown()

    class _Observer(_GateExecutor):
        async def resume(self, request: TaskRequest, on_state_change) -> TaskResult:
            self.started.set()
            await self.release.wait()
            result = _succeeded_result(request)
            await on_state_change(TaskRunStatus.SUCCEEDED, result)
            return result

    observer = _Observer()
    replacement = AdlcRunService(observer, persistence=persistence)
    await replacement.recover()
    await asyncio.wait_for(observer.started.wait(), timeout=2)
    assert replacement._runs[started.id].max_concurrency == 1
    assert observer.calls == 0
    restored = await replacement.get_run(started.id, owner_id="owner-1")
    assert restored.tasks[1].request is None
    observer.release.set()
    final = await _wait_for_status(replacement, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert observer.calls == 1
    assert final.tasks[0].request == running.tasks[0].request
    assert final.tasks[0].retry_count == 0
    await replacement.clear()


async def test_persistence_records_state_at_reap_and_command_boundaries() -> None:
    persistence = _RecordingPersistence()
    service = AdlcRunService(persistence=persistence)
    await service.start_run(
        flow_id=uuid4(),
        flow_name="Persistence slice",
        definitions=[_definition("alpha"), _definition("beta", dependencies=["alpha"])],
        request=_start_request(),
        owner_id="owner-1",
    )
    start_saves = persistence.save_count
    assert start_saves >= 2  # reap boundary + command boundary

    # The run ended WAITING_APPROVAL-free but terminal; use a paused run to
    # exercise the event-command persistence boundary instead.
    paused_service = AdlcRunService(persistence=persistence)
    event_run = await paused_service.start_run(
        flow_id=uuid4(),
        flow_name="Persistence event slice",
        definitions=[_definition("gated", waits_for=["manual.gate"])],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert event_run.status is WorkflowRunStatus.PAUSED
    saves_before_event = persistence.save_count

    resolved = await paused_service.emit_event(event_run.id, "manual.gate", owner_id="owner-1")

    assert persistence.save_count > saves_before_event
    assert resolved.status is WorkflowRunStatus.SUCCEEDED
    assert persistence.snapshots[event_run.id][1].status is WorkflowRunStatus.SUCCEEDED


async def test_hydration_restores_pause_reason_from_events() -> None:
    persistence = _RecordingPersistence()
    service = AdlcRunService(persistence=persistence)
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Pause reason slice",
        definitions=[_definition("solo", waits_for=["manual.gate"])],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.PAUSED

    replacement = AdlcRunService(persistence=persistence)
    restored = await replacement.get_run(run.id, owner_id="owner-1")
    assert restored.status is WorkflowRunStatus.PAUSED
    assert replacement._runs[run.id].pause_reason == "waiting_for_events"
    with pytest.raises(AdlcRunStateError, match="awaiting manual retry"):
        await replacement.retry_task(run.tasks[0].id, owner_id="owner-1")
    await service.clear()


# ---------------------------------------------------------------------------
# Regression: user pause must not block the retry_available path
# ---------------------------------------------------------------------------


async def test_manual_retry_still_works_after_retry_available_pause() -> None:
    service = AdlcRunService()
    definition = _definition("solo", simulate_failure=True)
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Manual retry slice",
        definitions=[definition],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.PAUSED

    retried = await service.retry_task(run.tasks[0].id, owner_id="owner-1")

    assert retried.status is WorkflowRunStatus.SUCCEEDED
    assert retried.tasks[0].retry_count == 1
    assert any(event.event_type == "task_run.retry_requested" for event in retried.events)


async def test_resumed_run_reuses_background_scheduler_for_async_executors() -> None:
    executor = _GateExecutor()
    service = AdlcRunService(executor)
    definitions = [
        _definition("first", executor_target=_harness_target("first")),
        _definition("second", dependencies=["first"], executor_target=_harness_target("second")),
    ]
    started = await service.start_run(
        flow_id=uuid4(),
        flow_name="Resume background slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    await asyncio.wait_for(executor.started.wait(), timeout=2)
    await service.pause_run(started.id, owner_id="owner-1", actor=SYSTEM_ACTOR)
    executor.release.set()
    paused = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.PAUSED)
    assert paused.tasks[1].status is TaskRunStatus.PENDING

    executor.release.set()
    resumed = await service.resume_run(started.id, owner_id="owner-1")
    assert resumed.status is WorkflowRunStatus.RUNNING
    assert service._runs[started.id].scheduler_task is not None

    final = await _wait_for_status(service, started.id, "owner-1", WorkflowRunStatus.SUCCEEDED)
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in final.tasks)
    await service.clear()

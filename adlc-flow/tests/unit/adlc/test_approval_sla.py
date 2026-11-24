# ruff: noqa: INP001, PLR2004, S101

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from langflow.adlc.adapter_runtime import utc_now
from langflow.adlc.metrics import AdlcAlertThresholds, AdlcMetricsCollector
from langflow.adlc.models import (
    Actor,
    ApprovalStatus,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    MockArtifactSpec,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.adlc.notifications import InMemoryAdlcNotificationSink
from langflow.adlc.observability import AdlcObservationOutcome, AdlcObservationType, AdlcOperationObservation
from langflow.adlc.run_service import AdlcRunService

SYSTEM_ACTOR = Actor(type="SYSTEM", id="test", display_name="Test")


def _artifact_spec(key: str) -> MockArtifactSpec:
    return MockArtifactSpec(kind="DOCUMENT", name=f"{key}.txt", media_type="text/plain", content=f"content {key}")


def _definition(key: str, *, dependencies: list[str] | None = None, **overrides: Any) -> Any:
    from langflow.adlc.models import AdlcTaskDefinition

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


def _approval_definition(key: str = "approval", *, ttl_seconds: float | None = None, **overrides: Any) -> Any:
    overrides.setdefault("task_type", "APPROVAL")
    overrides.setdefault("executor_target", ExecutorTarget(service="control:approval", operation="after-task"))
    overrides.setdefault("approval_gate", "ACTION")
    if ttl_seconds is not None:
        constraints = dict(overrides.get("constraints") or {})
        constraints["approval_ttl_seconds"] = ttl_seconds
        overrides["constraints"] = constraints
    return _definition(key, **overrides)


def _start_request(**overrides: Any) -> CreateWorkflowRunRequest:
    payload: dict[str, Any] = {
        "flowId": uuid4(),
        "executionMode": "LEGACY_FLOW",
        "delayMs": 0,
    }
    payload.update(overrides)
    return CreateWorkflowRunRequest(**payload)


def _approval_definitions() -> list[Any]:
    return [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"]),
    ]


class _PendingApprovalFlakyExecutor:
    """Fail every attempt with a retryable error until told to succeed."""

    service_name = "mock"
    capabilities = ("test",)

    def __init__(self, failures: int, *, retryable: bool = True) -> None:
        self.failures = failures
        self.retryable = retryable
        self.attempts = 0

    async def execute(self, request: TaskRequest, on_state_change) -> TaskResult:
        self.attempts += 1
        await on_state_change(TaskRunStatus.RUNNING, None)
        status = TaskResultStatus.FAILED if self.attempts <= self.failures else TaskResultStatus.SUCCEEDED
        now = utc_now()
        result = TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=status,
            output={"outputs": {}} if status is TaskResultStatus.SUCCEEDED else None,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code="TRANSIENT_FAILURE",
                category="EXECUTION",
                message="synthetic failure",
                retryable=self.retryable,
                service="mock",
                occurred_at=now,
            )
            if status is TaskResultStatus.FAILED
            else None,
            metrics=None,
            started_at=now,
            completed_at=now,
            metadata={},
        )
        mapping = {
            TaskResultStatus.SUCCEEDED: TaskRunStatus.SUCCEEDED,
            TaskResultStatus.FAILED: TaskRunStatus.FAILED,
            TaskResultStatus.CANCELLED: TaskRunStatus.CANCELLED,
        }
        await on_state_change(mapping[result.status], result)
        return result


async def test_approval_ttl_sets_expires_at_and_default_stays_open() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=30),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="TTL slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    approval = run.approval_requests[0]
    assert approval.expires_at is not None
    assert approval.expires_at - approval.created_at == timedelta(seconds=30)
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL

    open_run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Open slice",
        definitions=_approval_definitions(),
        request=_start_request(),
        owner_id="owner-1",
    )
    assert open_run.approval_requests[0].expires_at is None


async def test_expire_due_approvals_fails_task_and_terminalizes_run() -> None:
    notifications = InMemoryAdlcNotificationSink()
    service = AdlcRunService(notification_sink=notifications)
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=30),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Expiry slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    before = (await service.get_events(run.id, owner_id="owner-1")).__len__()

    expired = await service.expire_due_approvals(now=utc_now() + timedelta(seconds=60))

    assert len(expired) == 1
    updated = await service.get_run(run.id, owner_id="owner-1")
    approval = updated.approval_requests[0]
    assert approval.status is ApprovalStatus.EXPIRED
    task = updated.tasks[-1]
    assert task.status is TaskRunStatus.FAILED
    assert task.result is not None
    assert task.result.error is not None
    assert task.result.error.code == "APPROVAL_EXPIRED"
    assert updated.status is WorkflowRunStatus.FAILED
    event_types = [event.event_type for event in updated.events]
    assert "approval_request.expired" in event_types
    assert len(updated.events) > before
    kinds = [notification.kind.value for notification in notifications.notifications]
    assert kinds.count("APPROVAL_REQUIRED") == 1
    assert kinds.count("APPROVAL_EXPIRED") == 1


async def test_expired_approval_run_surfaces_in_dead_letters() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=30),
    ]
    await service.start_run(
        flow_id=uuid4(),
        flow_name="Expiry DLQ slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    await service.expire_due_approvals(now=utc_now() + timedelta(seconds=60))

    letters = await service.list_dead_letters(owner_id="owner-1")
    assert [letter.task_key for letter in letters] == ["approval"]
    assert letters[0].error_code == "APPROVAL_EXPIRED"
    assert letters[0].run_status is WorkflowRunStatus.FAILED


async def test_expire_ignores_future_ttl_and_terminal_approvals() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=3600),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Future TTL slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    expired = await service.expire_due_approvals(now=utc_now() + timedelta(seconds=60))
    assert expired == []
    updated = await service.get_run(run.id, owner_id="owner-1")
    assert updated.status is WorkflowRunStatus.WAITING_APPROVAL
    assert updated.approval_requests[0].status is ApprovalStatus.PENDING


async def test_sla_breach_recorded_once_and_notified() -> None:
    notifications = InMemoryAdlcNotificationSink()
    service = AdlcRunService(notification_sink=notifications)
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=3600),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="SLA slice",
        definitions=definitions,
        request=_start_request(slaSeconds=30),
        owner_id="owner-1",
    )
    assert run.sla_deadline_at is not None
    assert run.sla_breached_at is None

    breached = await service.check_run_slas(now=run.sla_deadline_at + timedelta(seconds=1))
    assert run.id in breached
    updated = await service.get_run(run.id, owner_id="owner-1")
    assert updated.sla_breached_at is not None
    assert sum(1 for event in updated.events if event.event_type == "workflow_run.sla_breached") == 1
    assert any(notification.kind.value == "SLA_BREACHED" for notification in notifications.notifications)

    again = await service.check_run_slas(now=run.sla_deadline_at + timedelta(seconds=2))
    assert again == []
    final = await service.get_run(run.id, owner_id="owner-1")
    assert sum(1 for event in final.events if event.event_type == "workflow_run.sla_breached") == 1


async def test_sla_not_breached_for_terminal_or_future_runs() -> None:
    service = AdlcRunService()
    done = await service.start_run(
        flow_id=uuid4(),
        flow_name="Terminal SLA slice",
        definitions=[_definition("only")],
        request=_start_request(slaSeconds=30),
        owner_id="owner-1",
    )
    assert done.status is WorkflowRunStatus.SUCCEEDED
    breached = await service.check_run_slas(now=utc_now() + timedelta(hours=1))
    assert done.id not in breached


async def test_dead_letters_list_only_exhausted_tasks() -> None:
    exhausted_executor = _PendingApprovalFlakyExecutor(failures=5)
    service = AdlcRunService(exhausted_executor)
    exhausted = await service.start_run(
        flow_id=uuid4(),
        flow_name="Exhausted slice",
        definitions=[_definition("alpha", constraints={"max_attempts": 2})],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert exhausted.status is WorkflowRunStatus.PAUSED

    letters = await service.list_dead_letters(owner_id="owner-1")
    assert len(letters) == 1
    letter = letters[0]
    assert letter.task_key == "alpha"
    assert letter.error_code == "TRANSIENT_FAILURE"
    assert letter.max_attempts == 2
    assert letter.retry_count == 1

    healthy_service = AdlcRunService()
    healthy = await healthy_service.start_run(
        flow_id=uuid4(),
        flow_name="Healthy slice",
        definitions=[_definition("beta")],
        request=_start_request(),
        owner_id="owner-1",
    )
    assert healthy.status is WorkflowRunStatus.SUCCEEDED
    still = await service.list_dead_letters(owner_id="owner-1")
    assert [letter.task_key for letter in still] == ["alpha"]

    other = await service.list_dead_letters(owner_id="owner-2")
    assert other == []


async def test_sweeper_loop_expires_overdue_approval_in_real_time() -> None:
    service = AdlcRunService()
    definitions = [
        _definition("coding"),
        _approval_definition("approval", dependencies=["coding"], ttl_seconds=0.05),
    ]
    run = await service.start_run(
        flow_id=uuid4(),
        flow_name="Sweeper slice",
        definitions=definitions,
        request=_start_request(),
        owner_id="owner-1",
    )
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    service.start_approval_sweeper(interval_seconds=0.02)
    try:
        for _ in range(100):
            state = await service.get_run(run.id, owner_id="owner-1")
            if state.status is WorkflowRunStatus.FAILED:
                break
            await asyncio.sleep(0.02)
        assert state.status is WorkflowRunStatus.FAILED
        assert state.approval_requests[0].status is ApprovalStatus.EXPIRED
    finally:
        await service.stop_approval_sweeper()


async def test_metrics_thresholds_are_configurable_per_collector() -> None:
    events = [
        _dispatch_observation(AdlcObservationOutcome.FAILED),
        _dispatch_observation(AdlcObservationOutcome.SUCCEEDED),
    ]
    strict = AdlcMetricsCollector(
        thresholds=AdlcAlertThresholds(failure_min_samples=2, failure_rate=0.5, denied_dispatches=1)
    )
    for event in events:
        strict.emit(event)
    assert strict.snapshot().alerts != []

    default = AdlcMetricsCollector()
    for event in events:
        default.emit(event)
    assert default.snapshot().alerts == []


def _dispatch_observation(outcome: AdlcObservationOutcome) -> AdlcOperationObservation:
    return AdlcOperationObservation(
        event_type=AdlcObservationType.TASK_DISPATCH_COMPLETED,
        outcome=outcome,
        duration_ms=10.0,
        occurred_at=datetime.now(timezone.utc),
    )

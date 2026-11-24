# ruff: noqa: INP001, S101, S105, S106

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from langflow.adlc.harness_callbacks import (
    HarnessCallbackReceiver,
    HarnessCallbackSettings,
    sign_harness_delivery,
)
from langflow.adlc.harness_client import HarnessClientError
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.harness_models import (
    HarnessResultDelivery,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
)
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus


def _request() -> TaskRequest:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="coding",
        name="Harness task",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={"objective": "Implement it.", "requirement": "Implement it."},
        context={},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
        metadata={
            "resolved_configuration": {
                "submission_mode": "AUTO",
                "result_schema_ref": "adlc://schemas/source-patch/0.1",
                "plugin_lock": [],
            }
        },
    )


class _ImmediateCallbackClient:
    def __init__(self, callbacks: HarnessCallbackReceiver, secret: str) -> None:
        self.callbacks = callbacks
        self.secret = secret

    async def health(self) -> dict[str, object]:
        return {"ready": True}

    async def create_session(self, request):
        now = datetime.now(timezone.utc)
        result = HarnessSessionResult(
            session_id="session-fast",
            correlation=request.correlation,
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "done"},
            artifacts=[],
            error=None,
            started_at=now,
            completed_at=now,
        )
        delivery = HarnessResultDelivery(
            delivery_id=uuid4(),
            callback_ref="adlc-primary",
            created_at=now,
            result=result,
        )
        body = delivery.model_dump_json().encode()
        timestamp = "1700000000"
        await self.callbacks.receive(
            body,
            delivery_id=str(delivery.delivery_id),
            timestamp=timestamp,
            signature=sign_harness_delivery(self.secret, timestamp, body),
        )
        return HarnessSessionAccepted(
            session=HarnessSessionRead(
                session_id="session-fast",
                correlation=request.correlation,
                idempotency_key=request.idempotency_key,
                status=HarnessSessionStatus.DELIVERING,
                submission_mode=request.submission_mode,
                created_at=now,
                updated_at=now,
            )
        )

    async def get_session(self, session_id: str):  # pragma: no cover - protocol completeness
        raise NotImplementedError(session_id)

    async def submit_session(self, session_id: str):  # pragma: no cover - not needed for delivering state
        raise NotImplementedError(session_id)

    async def cancel_session(self, session_id: str):  # pragma: no cover - protocol completeness
        raise NotImplementedError(session_id)


class _PollingResultClient:
    def __init__(self, initial_status: HarnessSessionStatus, submission_mode: HarnessSubmissionMode) -> None:
        self.initial_status = initial_status
        self.submission_mode = submission_mode
        self.request = None
        self.submit_calls = 0

    async def create_session(self, request):
        self.request = request
        now = datetime.now(timezone.utc)
        return HarnessSessionAccepted(
            session=HarnessSessionRead(
                session_id="session-poll",
                correlation=request.correlation,
                idempotency_key=request.idempotency_key,
                status=self.initial_status,
                submission_mode=self.submission_mode,
                created_at=now,
                updated_at=now,
            )
        )

    async def get_session(self, session_id: str):
        assert session_id == "session-poll"
        now = datetime.now(timezone.utc)
        result = HarnessSessionResult(
            session_id=session_id,
            correlation=self.request.correlation,
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "reconciled"},
            artifacts=[],
            error=None,
            started_at=now,
            completed_at=now,
        )
        return HarnessSessionRead(
            session_id=session_id,
            correlation=self.request.correlation,
            idempotency_key=self.request.idempotency_key,
            status=HarnessSessionStatus.SUCCEEDED,
            submission_mode=self.submission_mode,
            result=result,
            created_at=now,
            updated_at=now,
        )

    async def submit_session(self, _session_id: str):
        self.submit_calls += 1

    async def cancel_session(self, _session_id: str):  # pragma: no cover - protocol completeness
        return None


class _TransientPollingClient(_PollingResultClient):
    """Polling client that raises retryable errors before succeeding."""

    def __init__(self, *args, failures: int = 0, error: HarnessClientError | None = None) -> None:
        super().__init__(*args)
        self.remaining = failures
        self.error = error or HarnessClientError("HARNESS_SERVER_UNAVAILABLE")
        self.get_calls = 0

    async def get_session(self, session_id: str):
        self.get_calls += 1
        if self.get_calls <= self.remaining:
            raise self.error
        return await super().get_session(session_id)


async def test_executor_handles_a_valid_callback_that_arrives_before_create_returns() -> None:
    secret = "callback-secret"
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret=secret), clock=lambda: 1_700_000_000)
    executor = DeepSeekHarnessTaskExecutor(_ImmediateCallbackClient(callbacks, secret), callbacks)
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await executor.execute(_request(), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.metadata["harness_session_id"] == "session-fast"
    assert transitions == [TaskRunStatus.RUNNING, TaskRunStatus.SUCCEEDED]


async def test_executor_projects_agent_interaction_waiting_and_recovers_result_by_polling() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    client = _PollingResultClient(
        HarnessSessionStatus.WAITING_INTERACTION,
        HarnessSubmissionMode.MANUAL,
    )
    executor = DeepSeekHarnessTaskExecutor(
        client,
        callbacks,
        result_timeout_seconds=1,
        status_poll_interval_seconds=0.001,
    )
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await executor.execute(_request(), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert transitions == [
        TaskRunStatus.RUNNING,
        TaskRunStatus.WAITING_APPROVAL,
        TaskRunStatus.RUNNING,
        TaskRunStatus.SUCCEEDED,
    ]
    assert client.submit_calls == 0


async def test_executor_does_not_auto_submit_a_manual_ready_session() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    client = _PollingResultClient(
        HarnessSessionStatus.READY_FOR_SUBMISSION,
        HarnessSubmissionMode.MANUAL,
    )
    executor = DeepSeekHarnessTaskExecutor(
        client,
        callbacks,
        result_timeout_seconds=1,
        status_poll_interval_seconds=0.001,
    )

    result = await executor.execute(_request(), lambda _status, _result: _async_none())

    assert result.status is TaskResultStatus.SUCCEEDED
    assert client.submit_calls == 0


async def _async_none() -> None:
    return None


async def test_executor_survives_a_transient_get_session_poll_failure() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    client = _TransientPollingClient(
        HarnessSessionStatus.WAITING_INTERACTION,
        HarnessSubmissionMode.MANUAL,
        failures=1,
    )
    executor = DeepSeekHarnessTaskExecutor(
        client,
        callbacks,
        result_timeout_seconds=1,
        status_poll_interval_seconds=0.001,
    )

    result = await executor.execute(_request(), lambda _status, _result: _async_none())

    assert result.status is TaskResultStatus.SUCCEEDED
    assert client.get_calls >= 2


async def test_executor_fails_after_poll_failure_budget_is_exhausted() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    client = _TransientPollingClient(
        HarnessSessionStatus.WAITING_INTERACTION,
        HarnessSubmissionMode.MANUAL,
        failures=999,
    )
    executor = DeepSeekHarnessTaskExecutor(
        client,
        callbacks,
        result_timeout_seconds=1,
        status_poll_interval_seconds=0.001,
        poll_failure_budget_seconds=0.0,
    )

    result = await executor.execute(_request(), lambda _status, _result: _async_none())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "HARNESS_SERVER_UNAVAILABLE"
    assert result.error.retryable is True


class _CancelRecordingClient:
    """HarnessClient stub that records cancel_session calls."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def health(self) -> dict[str, object]:
        return {"ready": True}

    async def cancel_session(self, session_id: str) -> None:
        self.cancelled.append(session_id)

    async def create_session(self, request):  # pragma: no cover - unused here
        raise NotImplementedError(request)

    async def get_session(self, session_id: str):  # pragma: no cover - unused here
        raise NotImplementedError(session_id)

    async def submit_session(self, session_id: str):  # pragma: no cover - unused here
        raise NotImplementedError(session_id)


async def test_cancel_orphaned_plan_sessions_cancels_only_this_tasks_attempts() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    client = _CancelRecordingClient()
    executor = DeepSeekHarnessTaskExecutor(client, callbacks)

    workflow_run_id = uuid4()
    parent_task_run_id = uuid4()
    other_parent = uuid4()

    def _subtask_request(parent: uuid.UUID) -> TaskRequest:
        base = _request()
        workflow = base.workflow_run_id
        return base.model_copy(
            update={
                "workflow_run_id": workflow_run_id,
                "idempotency_key": f"{workflow}:plan-{parent}:task.sub-1:{uuid4()}",
            }
        )

    orphan = await callbacks.register_attempt(_subtask_request(parent_task_run_id))
    await callbacks.bind_session(orphan.attempt_id, "session-orphan")
    other_task = await callbacks.register_attempt(_subtask_request(other_parent))
    await callbacks.bind_session(other_task.attempt_id, "session-other-task")

    cancelled = await executor.cancel_orphaned_plan_sessions(workflow_run_id, parent_task_run_id)

    assert cancelled == 1
    assert client.cancelled == ["session-orphan"]
    assert (await callbacks.attempts.get(orphan.attempt_id)).status is TaskAttemptStatus.CANCELLED
    assert (await callbacks.attempts.get(other_task.attempt_id)).status is TaskAttemptStatus.DISPATCHED

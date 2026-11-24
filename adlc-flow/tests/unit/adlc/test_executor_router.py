# ruff: noqa: INP001, S101

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus


def _request(service: str) -> TaskRequest:
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
        name="Routed task",
        executor=ExecutorTarget(service=service, operation="coding-task"),
        input={
            "delayMs": 0,
            "predeterminedResult": {"summary": "routed"},
            "artifact": {"name": "routed.txt", "content": "routed"},
        },
        context={},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
        metadata={"mock": True},
    )


async def test_router_dispatches_a_package_service_alias_to_its_executor() -> None:
    mock_executor = MockExecutor()
    router = TaskExecutorRouter(
        mock_executor,
        routes={"agent-provider:mock": mock_executor},
    )
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await router.execute(_request("agent-provider:mock"), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert transitions == [TaskRunStatus.RUNNING, TaskRunStatus.SUCCEEDED]
    assert router.available_services == ("agent-provider:mock", "mock-agent-adapter")


async def test_router_fails_an_unregistered_service_without_falling_back() -> None:
    router = TaskExecutorRouter(MockExecutor())
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await router.execute(_request("agent-provider:missing"), on_state_change)

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "EXECUTOR_SERVICE_NOT_REGISTERED"
    assert result.error.retryable is False
    assert result.error.details == {"requested_service": "agent-provider:missing"}
    assert transitions == [TaskRunStatus.RUNNING, TaskRunStatus.FAILED]

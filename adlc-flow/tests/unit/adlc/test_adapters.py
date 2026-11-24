# ruff: noqa: INP001, S101

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from langflow.adlc.adapter_interfaces import (
    AgentAdapter,
    MemoryAdapter,
    SandboxAdapter,
    SandboxSession,
)
from langflow.adlc.adapter_interfaces import TestingAdapter as AdapterTestingProtocol
from langflow.adlc.local_worktree_sandbox import LocalWorktreeSandboxError
from langflow.adlc.mock_adapters import (
    MockAgentAdapter,
    MockMemoryAdapter,
    MockSandboxAdapter,
    MockTestingAdapter,
)
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus


def _request(*, simulate_failure: bool = False) -> TaskRequest:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="mock.test",
        name="Adapter test",
        executor=ExecutorTarget(
            service=MockAgentAdapter.service_name,
            operation="test",
            capabilities=list(MockAgentAdapter.capabilities),
        ),
        input={
            "delayMs": 0,
            "simulateFailure": simulate_failure,
            "predeterminedResult": {"summary": "done"},
            "artifact": {"name": "adapter-test.txt", "content": "adapter output"},
        },
        context={"memory_refs": ["memory://project/one"], "variables": {"branch": "main"}},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000, "priority": 50, "max_attempts": 1},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
        trace_context={},
        metadata={"mock": True},
    )


async def test_mock_executor_composes_all_four_adapter_interfaces() -> None:
    sandbox = MockSandboxAdapter()
    memory = MockMemoryAdapter()
    testing = MockTestingAdapter()
    agent = MockAgentAdapter()
    executor = MockExecutor(sandbox=sandbox, memory=memory, testing=testing, agent=agent)
    request = _request()
    transitions: list[tuple[TaskRunStatus, TaskResult | None]] = []

    async def on_state_change(status: TaskRunStatus, result: TaskResult | None) -> None:
        transitions.append((status, result))

    result = await executor.execute(request, on_state_change)

    assert isinstance(sandbox, SandboxAdapter)
    assert isinstance(memory, MemoryAdapter)
    assert isinstance(testing, AdapterTestingProtocol)
    assert isinstance(agent, AgentAdapter)
    assert [status for status, _ in transitions] == [TaskRunStatus.RUNNING, TaskRunStatus.SUCCEEDED]
    assert result.status is TaskResultStatus.SUCCEEDED
    assert sandbox.opened_attempt_ids == [request.attempt_id]
    assert sandbox.closed_attempt_ids == [request.attempt_id]
    assert not sandbox.open_sessions
    assert memory.loaded_attempt_ids == [request.attempt_id]
    assert memory.recorded_results[request.attempt_id] == result
    assert testing.evaluated_attempt_ids == [request.attempt_id]
    assert agent.executed_attempt_ids == [request.attempt_id]
    assert result.metadata["adapter_services"] == {
        "sandbox": MockSandboxAdapter.service_name,
        "memory": MockMemoryAdapter.service_name,
        "testing": MockTestingAdapter.service_name,
        "agent": MockAgentAdapter.service_name,
    }
    assert result.metadata["testing"]["outcome"] == "PASSED"
    assert result.metadata["memory_refs"] == ["memory://project/one"]


async def test_mock_failure_still_flows_through_testing_memory_and_cleanup() -> None:
    sandbox = MockSandboxAdapter()
    memory = MockMemoryAdapter()
    testing = MockTestingAdapter()
    agent = MockAgentAdapter()
    executor = MockExecutor(sandbox=sandbox, memory=memory, testing=testing, agent=agent)
    request = _request(simulate_failure=True)
    statuses: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        statuses.append(status)

    result = await executor.execute(request, on_state_change)

    assert statuses == [TaskRunStatus.RUNNING, TaskRunStatus.FAILED]
    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "MOCK_EXECUTION_FAILED"
    assert testing.evaluated_attempt_ids == [request.attempt_id]
    assert memory.recorded_results[request.attempt_id] == result
    assert sandbox.closed_attempt_ids == [request.attempt_id]
    assert result.metadata["testing"]["outcome"] == "NOT_RUN"


async def test_adapter_exception_becomes_failed_result_and_closes_sandbox() -> None:
    class FailingTestingAdapter(MockTestingAdapter):
        service_name = "failing-testing-adapter"

        async def evaluate(self, request: TaskRequest, _result: TaskResult) -> TaskResult:
            self.evaluated_attempt_ids.append(request.attempt_id)
            raise ConnectionError

    sandbox = MockSandboxAdapter()
    memory = MockMemoryAdapter()
    testing = FailingTestingAdapter()
    executor = MockExecutor(
        sandbox=sandbox,
        memory=memory,
        testing=testing,
        agent=MockAgentAdapter(),
    )
    request = _request()
    statuses: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        statuses.append(status)

    result = await executor.execute(request, on_state_change)

    assert statuses == [TaskRunStatus.RUNNING, TaskRunStatus.FAILED]
    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "ADAPTER_EXECUTION_FAILED"
    assert result.error.service == FailingTestingAdapter.service_name
    assert result.artifacts
    assert request.attempt_id not in memory.recorded_results
    assert sandbox.closed_attempt_ids == [request.attempt_id]


async def test_worktree_failure_preserves_safe_error_code() -> None:
    class FailingSandbox(MockSandboxAdapter):
        service_name = "sandbox:local-git-worktree"

        async def open_session(self, request: TaskRequest) -> SandboxSession:  # noqa: ARG002
            code = "LOCAL_WORKTREE_CREATE_FAILED"
            raise LocalWorktreeSandboxError(code, operation="worktree")

    executor = MockExecutor(
        sandbox=FailingSandbox(),
        memory=MockMemoryAdapter(),
        testing=MockTestingAdapter(),
        agent=MockAgentAdapter(),
    )
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await executor.execute(_request(), on_state_change)

    assert transitions == [TaskRunStatus.RUNNING, TaskRunStatus.FAILED]
    assert result.error is not None
    assert result.error.code == "LOCAL_WORKTREE_CREATE_FAILED"
    assert result.error.details == {
        "exception_type": "LocalWorktreeSandboxError",
        "operation": "worktree",
    }
    assert result.error.service == "sandbox:local-git-worktree"

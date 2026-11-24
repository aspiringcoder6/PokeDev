# ruff: noqa: INP001, S101, S106, S108, PLR2004, SLF001

"""Unit tests for the DSHAgentAdapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.adapter_interfaces import MemoryContext, SandboxSession
from langflow.adlc.adapters.dsh_agent import (
    DEFAULT_DSH_PLUGIN_LOCK,
    DSHAgentAdapter,
    DSHAgentConfig,
    ERR_DSH_DISABLED,
    ERR_DSH_SESSION_REJECTED,
    ERR_DSH_SESSION_TIMEOUT,
)
from langflow.adlc.harness_client import HarnessClientError
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    TaskResultStatus,
)
from langflow.adlc.models import (
    ExecutorTarget,
    ServiceError,
    TaskMetrics,
    TaskRequest,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _FakeDshClient:
    """Minimal fake of DshHarnessClient for unit tests."""

    create_session_result: HarnessSessionAccepted | None = None
    create_session_error: HarnessClientError | None = None
    get_session_results: dict[str, HarnessSessionRead] = field(default_factory=dict)
    get_session_error: HarnessClientError | None = None
    get_session_error_times: int | None = None
    create_calls: list[Any] = field(default_factory=list)
    get_calls: list[str] = field(default_factory=list)

    async def create_session(self, request: Any) -> HarnessSessionAccepted:
        self.create_calls.append(request)
        if self.create_session_error is not None:
            raise self.create_session_error
        assert self.create_session_result is not None
        return self.create_session_result

    async def get_session(self, session_id: str) -> HarnessSessionRead:
        self.get_calls.append(session_id)
        if self.get_session_error is not None:
            times = self.get_session_error_times
            if times is None or len(self.get_calls) <= times:
                raise self.get_session_error
        return self.get_session_results[session_id]


def _request() -> TaskRequest:
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="code_generation",
        name="Implement feature X",
        executor=ExecutorTarget(service="agent-provider:dsh", operation="execute_task"),
        input={"spec": "Add a new endpoint"},
        dependency_task_run_ids=[],
        idempotency_key="run-1:task-1:attempt-1",
        requested_at=_utc_now(),
    )


def _sandbox() -> SandboxSession:
    return SandboxSession(
        session_id="sandbox-1",
        workspace_uri="file:///workspace",
        metadata={"opencode_directory": "/workspace/repo"},
    )


def _memory() -> MemoryContext:
    return MemoryContext(memory_refs=("ref-1",), variables={"ref-1": {"hint": "use pytest"}})


def _correlation() -> HarnessCorrelation:
    return HarnessCorrelation(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
    )


def _accepted(session_id: str = "dsh-session-1") -> HarnessSessionAccepted:
    session = HarnessSessionRead(
        session_id=session_id,
        correlation=_correlation(),
        idempotency_key="run-1:task-1:attempt-1",
        status=HarnessSessionStatus.RUNNING,
        submission_mode=HarnessSubmissionMode.AUTO,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    return HarnessSessionAccepted(session=session, replayed=False)


def _session_read(
    session_id: str,
    status: HarnessSessionStatus,
    result: HarnessSessionResult | None = None,
) -> HarnessSessionRead:
    return HarnessSessionRead(
        session_id=session_id,
        correlation=_correlation(),
        idempotency_key="run-1:task-1:attempt-1",
        status=status,
        submission_mode=HarnessSubmissionMode.AUTO,
        result=result,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )


def _success_result(session_id: str = "dsh-session-1") -> HarnessSessionResult:
    return HarnessSessionResult(
        session_id=session_id,
        correlation=_correlation(),
        status=TaskResultStatus.SUCCEEDED,
        output={"summary": "Task completed"},
        artifacts=[],
        metrics=TaskMetrics(duration_ms=1000),
        trace_ref="trace-1",
        error=None,
        started_at=_utc_now(),
        completed_at=_utc_now(),
    )


def _failed_result(session_id: str = "dsh-session-1") -> HarnessSessionResult:
    return HarnessSessionResult(
        session_id=session_id,
        correlation=_correlation(),
        status=TaskResultStatus.FAILED,
        output=None,
        artifacts=[],
        metrics=TaskMetrics(duration_ms=500),
        error=ServiceError(
            error_id=uuid4(),
            code="DSH_INTERNAL_ERROR",
            category="EXECUTION",
            message="DSH agent crashed",
            retryable=False,
            service="agent-provider:dsh",
            occurred_at=_utc_now(),
        ),
        started_at=_utc_now(),
        completed_at=_utc_now(),
    )


def _adapter(client: _FakeDshClient, **kwargs: Any) -> DSHAgentAdapter:
    config = DSHAgentConfig(api_token="test-token", **kwargs)
    return DSHAgentAdapter(client, config=config)  # type: ignore[arg-type]


async def test_execute_returns_failure_when_token_missing() -> None:
    client = _FakeDshClient()
    adapter = DSHAgentAdapter(client, config=DSHAgentConfig(api_token=""))

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == ERR_DSH_DISABLED
    assert client.create_calls == []


async def test_execute_creates_session_and_returns_result() -> None:
    session_id = "dsh-session-42"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.output == {"summary": "Task completed"}
    assert result.metadata["dsh_session_id"] == session_id
    assert len(client.create_calls) == 1
    assert client.get_calls == [session_id]


async def test_execute_returns_failure_when_create_session_raises() -> None:
    client = _FakeDshClient(
        create_session_error=HarnessClientError(
            code=ERR_DSH_SESSION_REJECTED,
            category="VALIDATION",
            retryable=False,
        ),
    )
    adapter = _adapter(client)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == ERR_DSH_SESSION_REJECTED


async def test_execute_returns_timeout_when_session_does_not_finalize() -> None:
    session_id = "dsh-session-stuck"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(session_id, HarnessSessionStatus.RUNNING),
        },
    )
    adapter = _adapter(client, timeout_seconds=0.1)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == ERR_DSH_SESSION_TIMEOUT
    assert result.error.retryable is True


async def test_execute_synthesizes_failure_when_session_ends_without_result() -> None:
    session_id = "dsh-session-no-result"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(session_id, HarnessSessionStatus.FAILED),
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert "no result" in result.error.message.lower()


async def test_default_plugin_lock_is_empty() -> None:
    """The default plugin lock is empty; callers must provide explicit entries."""
    assert DEFAULT_DSH_PLUGIN_LOCK == ()


async def test_from_environment_reads_token_from_settings() -> None:
    import os

    os.environ["ADLC_HARNESS_BASE_URL"] = "http://example:9982"
    os.environ["ADLC_HARNESS_API_TOKEN"] = "env-token"
    try:
        adapter = DSHAgentAdapter.from_environment()
        assert adapter.config.base_url == "http://example:9982"
        assert adapter.config.api_token == "env-token"
    finally:
        del os.environ["ADLC_HARNESS_BASE_URL"]
        del os.environ["ADLC_HARNESS_API_TOKEN"]


async def test_execute_includes_memory_refs_in_context() -> None:
    session_id = "dsh-session-mem"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)

    await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    create_call = client.create_calls[0]
    assert "memory_refs" in create_call.context
    assert create_call.context["memory_refs"] == ["ref-1"]
    assert "cwd" in create_call.context
    assert create_call.context["cwd"] == "/workspace/repo"


async def test_execute_resolves_workspace_fallback_when_no_opencode_directory() -> None:
    session_id = "dsh-session-ws"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)
    sandbox = SandboxSession(
        session_id="sandbox-2",
        workspace_uri="file:///workspace",
        metadata={"workspace": "/workspace/fallback"},
    )

    await adapter.execute(_request(), sandbox=sandbox, memory=_memory())

    create_call = client.create_calls[0]
    assert create_call.context["cwd"] == "/workspace/fallback"


async def test_execute_omits_cwd_when_sandbox_has_no_workspace() -> None:
    session_id = "dsh-session-no-cwd"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)
    sandbox = SandboxSession(session_id="sandbox-3", workspace_uri="file:///workspace")

    await adapter.execute(_request(), sandbox=sandbox, memory=_memory())

    create_call = client.create_calls[0]
    assert "cwd" not in create_call.context


async def test_execute_propagates_session_error() -> None:
    session_id = "dsh-session-err"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.FAILED,
                result=_failed_result(session_id),
            )
        },
    )
    adapter = _adapter(client, timeout_seconds=10.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DSH_INTERNAL_ERROR"
    assert result.error.message == "DSH agent crashed"


async def test_execute_returns_failure_when_get_session_raises() -> None:
    session_id = "dsh-session-get-err"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_error=HarnessClientError(
            code="DSH_TRANSPORT_ERROR",
            category="DEPENDENCY",
            retryable=True,
        ),
    )
    adapter = _adapter(client, timeout_seconds=10.0, poll_failure_budget_seconds=0.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "DSH_TRANSPORT_ERROR"
    assert result.error.retryable is True


async def test_execute_survives_transient_retryable_get_session_failure() -> None:
    session_id = "dsh-session-transient"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
        get_session_error=HarnessClientError(
            code="HARNESS_SERVER_UNAVAILABLE",
            category="DEPENDENCY",
            retryable=True,
        ),
        get_session_error_times=1,
    )
    adapter = _adapter(client, timeout_seconds=10.0, poll_failure_budget_seconds=30.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(client.get_calls) >= 2


async def test_execute_fails_after_poll_failure_budget_is_exhausted() -> None:
    session_id = "dsh-session-budget"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
        get_session_error=HarnessClientError(
            code="HARNESS_SERVER_UNAVAILABLE",
            category="DEPENDENCY",
            retryable=True,
        ),
    )
    adapter = _adapter(client, timeout_seconds=10.0, poll_failure_budget_seconds=0.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "HARNESS_SERVER_UNAVAILABLE"


async def test_execute_propagates_non_retryable_get_session_failure() -> None:
    session_id = "dsh-session-non-retryable"
    client = _FakeDshClient(
        create_session_result=_accepted(session_id),
        get_session_results={
            session_id: _session_read(
                session_id,
                HarnessSessionStatus.SUCCEEDED,
                result=_success_result(session_id),
            )
        },
        get_session_error=HarnessClientError(
            code="HARNESS_RESPONSE_INVALID",
            category="VALIDATION",
            retryable=False,
        ),
        get_session_error_times=1,
    )
    adapter = _adapter(client, timeout_seconds=10.0, poll_failure_budget_seconds=30.0)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=_memory())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "HARNESS_RESPONSE_INVALID"

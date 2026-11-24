# ruff: noqa: INP001, S101

"""Unit tests for production adapter selection and workspace bridging.

Covers the opt-in wiring of the Phase 4 real adapters
(``ADLC_TESTING_ADAPTER``, ``ADLC_MEMORY_ADAPTER``, ``ADLC_SANDBOX_ADAPTER``)
and the sandbox-workspace bridge that exposes the live worktree to testing
adapters via ``request.context["workspace"]``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.adapter_interfaces import AdapterBundle, MemoryContext, SandboxSession
from langflow.adlc.adapter_runtime import AdapterTaskExecutor, _request_with_workspace
from langflow.adlc.mock_adapters import MockMemoryAdapter, MockTestingAdapter
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus
from langflow.adlc.opencode_runtime import select_memory_adapter, select_sandbox_adapter, select_testing_adapter


def _request(*, context: dict[str, Any] | None = None) -> TaskRequest:
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
        name="Selection task",
        executor=ExecutorTarget(service="agent-provider:opencode", operation="coding-task"),
        input={"objective": "Wire the real adapters."},
        context=context or {},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
    )


def _session(metadata: dict[str, Any] | None = None) -> SandboxSession:
    return SandboxSession(
        session_id="ses_test",
        workspace_uri="file:///tmp/nonexistent-workspace",
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Adapter selection (env opt-in)
# ---------------------------------------------------------------------------


def test_testing_adapter_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADLC_TESTING_ADAPTER", raising=False)
    assert isinstance(select_testing_adapter(), MockTestingAdapter)


def test_testing_adapter_opts_into_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("real", "pytest"):
        monkeypatch.setenv("ADLC_TESTING_ADAPTER", value)
        adapter = select_testing_adapter()
        assert type(adapter).__name__ == "PytestTestingAdapter"
        assert adapter._config.coverage_enabled is False  # noqa: SLF001


def test_memory_adapter_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADLC_MEMORY_ADAPTER", raising=False)
    assert isinstance(select_memory_adapter(), MockMemoryAdapter)


def test_memory_adapter_opts_into_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADLC_MEMORY_ADAPTER", "real")
    adapter = select_memory_adapter()
    assert type(adapter).__name__ == "SQLiteMemoryAdapter"


def test_memory_adapter_dsh_requires_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADLC_MEMORY_ADAPTER", "dsh")
    assert isinstance(select_memory_adapter(dsh_client=None), MockMemoryAdapter)

    class _Client:
        pass

    adapter = select_memory_adapter(dsh_client=_Client())
    assert type(adapter).__name__ == "DSHMemoryAdapter"


def test_sandbox_adapter_defaults_to_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADLC_SANDBOX_ADAPTER", raising=False)
    adapter = select_sandbox_adapter(tmp_path, worktree_root=None, base_ref="HEAD")
    assert type(adapter).__name__ == "LocalWorktreeSandboxAdapter"


def test_sandbox_adapter_opts_into_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADLC_SANDBOX_ADAPTER", "docker")
    adapter = select_sandbox_adapter(tmp_path, worktree_root=None, base_ref="HEAD")
    assert type(adapter).__name__ == "DockerSandboxAdapter"


# ---------------------------------------------------------------------------
# Workspace bridging
# ---------------------------------------------------------------------------


def test_request_workspace_bridge_uses_sandbox_metadata() -> None:
    session = _session({"opencode_directory": "/tmp/actual-worktree"})
    bridged = _request_with_workspace(_request(), session)

    assert bridged.context is not None
    assert bridged.context["workspace"] == "/tmp/actual-worktree"


def test_request_workspace_bridge_falls_back_to_workspace_uri() -> None:
    bridged = _request_with_workspace(_request(), _session())

    assert bridged.context is not None
    assert bridged.context["workspace"] == "file:///tmp/nonexistent-workspace"


def test_request_workspace_bridge_respects_existing_workspace() -> None:
    session = _session({"opencode_directory": "/tmp/actual-worktree"})
    original = _request(context={"workspace": "/tmp/explicit"})

    bridged = _request_with_workspace(original, session)

    assert bridged is original
    assert bridged.context is not None
    assert bridged.context["workspace"] == "/tmp/explicit"


def test_request_workspace_bridge_returns_request_without_workspace() -> None:
    empty = SandboxSession(session_id="ses_empty", workspace_uri="", metadata={})
    original = _request()

    assert _request_with_workspace(original, empty) is original


async def test_executor_bridges_workspace_into_testing_adapter(tmp_path: Path) -> None:
    observed: dict[str, Any] = {}

    class RecordingTestingAdapter(MockTestingAdapter):
        async def evaluate(self, request: TaskRequest, result: TaskResult) -> TaskResult:
            observed["workspace"] = (request.context or {}).get("workspace")
            return await super().evaluate(request, result)

    class FakeSandbox:
        service_name = "sandbox:test"

        async def open_session(self, request: TaskRequest) -> SandboxSession:  # noqa: ARG002
            workspace = tmp_path / "worktree"
            workspace.mkdir(exist_ok=True)
            return SandboxSession(
                session_id="ses_test",
                workspace_uri=workspace.as_uri(),
                metadata={"opencode_directory": str(workspace), "mock": True},
            )

        async def close_session(self, request: TaskRequest, session: SandboxSession) -> None:  # noqa: ARG002
            return None

        async def check_readiness(self) -> bool:
            return True

    class FakeAgent:
        service_name = "agent-provider:opencode"
        capabilities = ("code_edit",)

        async def execute(
            self,
            request: TaskRequest,  # noqa: ARG002
            *,
            sandbox: SandboxSession,  # noqa: ARG002
            memory: MemoryContext,  # noqa: ARG002
        ) -> TaskResult:
            now = datetime.now(timezone.utc)
            return TaskResult(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
                status=TaskResultStatus.SUCCEEDED,
                output={},
                artifacts=[],
                error=None,
                started_at=now,
                completed_at=now,
            )

    executor = AdapterTaskExecutor(
        AdapterBundle(
            sandbox=FakeSandbox(),
            memory=MockMemoryAdapter(),
            testing=RecordingTestingAdapter(),
            agent=FakeAgent(),
        )
    )

    async def on_state_change(_status: TaskRunStatus, _result: TaskResult | None) -> None:
        return None

    result = await executor.execute(_request(), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert observed["workspace"] == str(tmp_path / "worktree")


# ---------------------------------------------------------------------------
# Workspace path resolution (file:// URI support)
# ---------------------------------------------------------------------------


def test_resolve_workspace_accepts_plain_path(tmp_path: Path) -> None:
    from langflow.adlc.adapters.real_testing import PytestTestingAdapter

    adapter = PytestTestingAdapter()
    resolved = adapter._resolve_workspace(  # noqa: SLF001
        _request(context={"workspace": str(tmp_path)}),
        _fake_result(),
    )

    assert resolved == tmp_path


def test_resolve_workspace_accepts_file_uri(tmp_path: Path) -> None:
    from langflow.adlc.adapters.real_testing import PytestTestingAdapter

    adapter = PytestTestingAdapter()
    resolved = adapter._resolve_workspace(  # noqa: SLF001
        _request(context={"workspace": tmp_path.as_uri()}),
        _fake_result(),
    )

    assert resolved == tmp_path


def test_resolve_workspace_rejects_missing_directory(tmp_path: Path) -> None:
    from langflow.adlc.adapters.real_testing import PytestTestingAdapter

    adapter = PytestTestingAdapter()
    missing = tmp_path / "does-not-exist"
    resolved = adapter._resolve_workspace(  # noqa: SLF001
        _request(context={"workspace": str(missing)}),
        _fake_result(),
    )

    assert resolved is None


def _fake_result(request: TaskRequest | None = None) -> Any:
    from datetime import datetime as _dt

    from langflow.adlc.models import TaskResult, TaskResultStatus

    req = request or _request()
    now = _dt.now(timezone.utc)
    return TaskResult(
        request_id=req.request_id,
        workflow_run_id=req.workflow_run_id,
        task_run_id=req.task_run_id,
        attempt_id=req.attempt_id,
        status=TaskResultStatus.SUCCEEDED,
        output={},
        artifacts=[],
        error=None,
        started_at=now,
        completed_at=now,
    )

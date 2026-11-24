# ruff: noqa: ARG002, INP001, PLR2004, S101

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from langflow.adlc.adapter_interfaces import AgentAdapter, MemoryContext, SandboxSession
from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResultStatus
from langflow.adlc.opencode_adapter import OpenCodeAgentAdapter, deterministic_opencode_artifact_id
from langflow.adlc.opencode_client import (
    OpenCodeClientError,
    OpenCodeFileDiff,
    OpenCodePromptResult,
    OpenCodeSession,
    OpenCodeTokenUsage,
)

if TYPE_CHECKING:
    from langflow.adlc.opencode_client import OpenCodeModelSelection


class StubOpenCodeClient:
    def __init__(self, *, prompt_error: OpenCodeClientError | None = None, prompt_delay: float = 0) -> None:
        self.prompt_error = prompt_error
        self.prompt_delay = prompt_delay
        self.created_directories: list[str] = []
        self.prompts: list[str] = []
        self.models: list[OpenCodeModelSelection | None] = []
        self.aborted_sessions: list[str] = []
        self.disposed_directories: list[str] = []

    async def health(self, *, timeout_ms: int = 5000) -> str:
        return "1.2.3"

    async def create_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:
        self.created_directories.append(directory)
        return OpenCodeSession(session_id="ses_test", directory=directory)

    async def prompt(
        self,
        session_id: str,
        *,
        directory: str,
        prompt: str,
        system: str,
        model: OpenCodeModelSelection | None,
        agent: str | None,
        timeout_ms: int,
    ) -> OpenCodePromptResult:
        self.prompts.append(prompt)
        self.models.append(model)
        if self.prompt_delay:
            await asyncio.sleep(self.prompt_delay)
        if self.prompt_error is not None:
            raise self.prompt_error
        return OpenCodePromptResult(
            message_id="msg_test",
            text="Implemented the requested change.",
            changed_files=("src/app.py",),
            provider_id="anthropic",
            model_id="claude-test",
            finish="stop",
            cost=0.25,
            token_usage=OpenCodeTokenUsage(
                input_tokens=10,
                output_tokens=20,
                reasoning_tokens=3,
                cache_read_tokens=4,
                cache_write_tokens=5,
            ),
        )

    async def get_workspace_diff(
        self,
        *,
        directory: str,
        timeout_ms: int,
    ) -> tuple[OpenCodeFileDiff, ...]:
        return (
            OpenCodeFileDiff(
                file="src/app.py",
                patch="--- a/src/app.py\n+++ b/src/app.py\n-old\n+new\n",
                additions=1,
                deletions=1,
                status="modified",
            ),
        )

    async def abort(self, session_id: str, *, directory: str, timeout_ms: int = 5000) -> None:
        self.aborted_sessions.append(session_id)

    async def dispose_instance(self, *, directory: str, timeout_ms: int = 5000) -> None:
        self.disposed_directories.append(directory)


def _request(*, timeout_ms: int = 1000) -> TaskRequest:
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
        name="Implement backend",
        executor=ExecutorTarget(service=OpenCodeAgentAdapter.service_name, operation="coding-task"),
        input={
            "objective": "Implement the backend route.",
            "namedInputs": {"requirement": "Add a health endpoint."},
        },
        context={"upstream_results": [{"output": "plan"}]},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": timeout_ms},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
        metadata={"credential": "TOP_SECRET_MUST_NOT_REACH_PROMPT"},
    )


def _sandbox(*, mock: bool = False) -> SandboxSession:
    return SandboxSession(
        session_id="sandbox-test",
        workspace_uri="sandbox://test/workspace",
        metadata={"opencode_directory": "D:/sandbox/workspace", "mock": mock},
    )


async def test_opencode_adapter_returns_contract_result_and_diff_artifact() -> None:
    client = StubOpenCodeClient()
    adapter = OpenCodeAgentAdapter(client, model="anthropic/claude-test", agent="build")
    request = _request()

    result = await adapter.execute(
        request,
        sandbox=_sandbox(),
        memory=MemoryContext(variables={"branch": "feature"}),
    )

    assert isinstance(adapter, AgentAdapter)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.request_id == request.request_id
    assert result.output["summary"] == "Implemented the requested change."
    assert result.output["outputs"]["source_patch"]["changed_files"] == ["src/app.py"]
    assert result.artifacts[0].artifact_id == deterministic_opencode_artifact_id(request.attempt_id)
    assert result.artifacts[0].uri == (
        f"adlc://runs/{request.workflow_run_id}/artifacts/{result.artifacts[0].artifact_id}"
    )
    assert result.artifacts[0].media_type == "application/vnd.opencode.vcs-diff+json"
    assert result.artifacts[0].metadata["capture"] == "workspace-vcs-diff"
    assert result.artifacts[0].metadata["payload_retained"] is True
    assert result.artifacts[0].metadata["diff_file_count"] == 1
    payload = adapter.artifact_payloads.read(result.artifacts[0])
    assert hashlib.sha256(payload).hexdigest() == result.artifacts[0].checksum.value
    assert json.loads(payload)["files"][0]["patch"] == "--- a/src/app.py\n+++ b/src/app.py\n-old\n+new\n"
    assert result.metrics is not None
    assert result.metrics.token_usage.total_tokens == 33
    assert result.metadata["opencode_session_id"] == "ses_test"
    assert client.created_directories == ["D:/sandbox/workspace"]
    assert client.models[0] is not None
    assert client.models[0].provider_id == "anthropic"
    assert "Add a health endpoint." in client.prompts[0]
    assert "TOP_SECRET_MUST_NOT_REACH_PROMPT" not in client.prompts[0]
    assert client.disposed_directories == ["D:/sandbox/workspace"]


async def test_opencode_adapter_fails_when_patch_exceeds_review_limit() -> None:
    client = StubOpenCodeClient()
    payloads = BoundedArtifactPayloadStore(max_artifact_bytes=16, max_total_bytes=16)
    adapter = OpenCodeAgentAdapter(client, artifact_payloads=payloads)

    result = await adapter.execute(_request(), sandbox=_sandbox(), memory=MemoryContext())

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "ARTIFACT_PAYLOAD_TOO_LARGE"
    assert payloads.total_bytes == 0
    assert client.disposed_directories == ["D:/sandbox/workspace"]


async def test_opencode_adapter_maps_sanitized_provider_error() -> None:
    client = StubOpenCodeClient(
        prompt_error=OpenCodeClientError(
            code="OPENCODE_PROVIDER_AUTHENTICATION_FAILED",
            category="AUTHENTICATION",
            retryable=False,
        )
    )
    result = await OpenCodeAgentAdapter(client).execute(
        _request(),
        sandbox=_sandbox(),
        memory=MemoryContext(),
    )

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "OPENCODE_PROVIDER_AUTHENTICATION_FAILED"
    assert result.error.category == "AUTHENTICATION"
    assert result.error.details == {}
    assert client.disposed_directories == ["D:/sandbox/workspace"]


async def test_opencode_adapter_aborts_session_on_deadline() -> None:
    client = StubOpenCodeClient(prompt_delay=0.05)
    result = await OpenCodeAgentAdapter(client).execute(
        _request(timeout_ms=1),
        sandbox=_sandbox(),
        memory=MemoryContext(),
    )

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "OPENCODE_TASK_TIMEOUT"
    assert result.error.category == "TIMEOUT"
    assert client.aborted_sessions == ["ses_test"]
    assert client.disposed_directories == ["D:/sandbox/workspace"]


async def test_opencode_adapter_rejects_missing_or_implicit_mock_workspace() -> None:
    client = StubOpenCodeClient()
    adapter = OpenCodeAgentAdapter(client)

    missing = await adapter.execute(
        _request(),
        sandbox=SandboxSession(session_id="missing", workspace_uri="mock://missing"),
        memory=MemoryContext(),
    )
    mocked = await adapter.execute(_request(), sandbox=_sandbox(mock=True), memory=MemoryContext())

    assert missing.error is not None
    assert missing.error.code == "OPENCODE_WORKSPACE_UNAVAILABLE"
    assert mocked.error is not None
    assert mocked.error.code == "OPENCODE_REAL_SANDBOX_REQUIRED"
    assert not client.created_directories


async def test_opencode_adapter_allows_explicit_development_mock_workspace() -> None:
    client = StubOpenCodeClient()
    adapter = OpenCodeAgentAdapter(client, allow_mock_sandbox=True)

    result = await adapter.execute(_request(), sandbox=_sandbox(mock=True), memory=MemoryContext())

    assert result.status is TaskResultStatus.SUCCEEDED
    assert client.created_directories == ["D:/sandbox/workspace"]

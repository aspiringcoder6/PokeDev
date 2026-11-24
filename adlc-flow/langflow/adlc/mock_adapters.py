"""Deterministic in-memory implementations of the ADLC adapter interfaces."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5

from langflow.adlc.adapter_interfaces import MemoryContext, SandboxSession
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MockSandboxAdapter:
    """Create deterministic mock sandbox handles without touching the filesystem."""

    service_name = "mock-sandbox-adapter"

    def __init__(self) -> None:
        self.opened_attempt_ids: list[UUID] = []
        self.closed_attempt_ids: list[UUID] = []
        self.open_sessions: dict[str, SandboxSession] = {}

    async def open_session(self, request: TaskRequest) -> SandboxSession:
        session_id = f"mock-{request.attempt_id}"
        session = SandboxSession(
            session_id=session_id,
            workspace_uri=f"mock://sandboxes/{session_id}/workspace",
            metadata={"mock": True},
        )
        self.opened_attempt_ids.append(request.attempt_id)
        self.open_sessions[session_id] = session
        return session

    async def close_session(self, request: TaskRequest, session: SandboxSession) -> None:
        self.closed_attempt_ids.append(request.attempt_id)
        self.open_sessions.pop(session.session_id, None)


class MockMemoryAdapter:
    """Echo request context and retain final results in process memory."""

    service_name = "mock-memory-adapter"

    def __init__(self) -> None:
        self.loaded_attempt_ids: list[UUID] = []
        self.recorded_results: dict[UUID, TaskResult] = {}

    async def load_context(self, request: TaskRequest) -> MemoryContext:
        context = request.context if isinstance(request.context, dict) else {}
        raw_refs = context.get("memory_refs", [])
        raw_variables = context.get("variables", {})
        memory_refs = tuple(str(value) for value in raw_refs) if isinstance(raw_refs, list) else ()
        variables = dict(raw_variables) if isinstance(raw_variables, dict) else {}
        self.loaded_attempt_ids.append(request.attempt_id)
        return MemoryContext(
            memory_refs=memory_refs,
            variables=variables,
            metadata={"adapter": self.service_name, "mock": True},
        )

    async def record_result(self, request: TaskRequest, result: TaskResult) -> None:
        self.recorded_results[request.attempt_id] = result.model_copy(deep=True)


class MockTestingAdapter:
    """Record a deterministic pass for successful results and otherwise no-op."""

    service_name = "mock-testing-adapter"

    def __init__(self) -> None:
        self.evaluated_attempt_ids: list[UUID] = []

    async def evaluate(self, request: TaskRequest, result: TaskResult) -> TaskResult:
        self.evaluated_attempt_ids.append(request.attempt_id)
        metadata = dict(result.metadata)
        metadata["testing"] = {
            "adapter": self.service_name,
            "outcome": "PASSED" if result.status is TaskResultStatus.SUCCEEDED else "NOT_RUN",
        }
        return result.model_copy(update={"metadata": metadata}, deep=True)


class MockAgentAdapter:
    """Wait briefly and return the predetermined v0.1 TaskResult."""

    service_name = "mock-agent-adapter"
    capabilities = (
        "predetermined_result",
        "mock_artifact",
        "state_events",
        "sandbox_context",
        "memory_context",
        "testing_hook",
    )

    def __init__(self) -> None:
        self.executed_attempt_ids: list[UUID] = []

    async def execute(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        memory: MemoryContext,
    ) -> TaskResult:
        started_at = utc_now()
        self.executed_attempt_ids.append(request.attempt_id)
        input_payload = request.input if isinstance(request.input, dict) else {}
        delay_ms = self._integer(input_payload.get("delayMs"), default=50)
        await asyncio.sleep(max(0, delay_ms) / 1000)

        completed_at = utc_now()
        artifact = self._build_artifact(request, input_payload, completed_at)
        if input_payload.get("simulateFailure") is True:
            return self._failed_result(request, artifact, started_at, completed_at, delay_ms)

        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output=input_payload.get("predeterminedResult", {}),
            artifacts=[artifact],
            error=None,
            metrics=TaskMetrics(duration_ms=delay_ms),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "agent_adapter": self.service_name,
                "deterministic": True,
                "sandbox_session_id": sandbox.session_id,
                "memory_refs": list(memory.memory_refs),
            },
        )

    def _build_artifact(
        self,
        request: TaskRequest,
        input_payload: dict[str, Any],
        created_at: datetime,
    ) -> Artifact:
        spec = input_payload.get("artifact")
        artifact_spec = spec if isinstance(spec, dict) else {}
        content = str(artifact_spec.get("content", "mock artifact"))
        content_bytes = content.encode("utf-8")
        artifact_id = deterministic_attempt_artifact_id(request.attempt_id)
        return Artifact(
            artifact_id=artifact_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            kind=str(artifact_spec.get("kind", "DOCUMENT")),
            name=str(artifact_spec.get("name", "mock-result.txt")),
            media_type=str(artifact_spec.get("mediaType", "text/plain")),
            uri=f"mock://artifacts/{artifact_id}",
            size_bytes=len(content_bytes),
            checksum=Checksum(value=hashlib.sha256(content_bytes).hexdigest()),
            producer=self.service_name,
            created_at=created_at,
            metadata={"mock": True},
        )

    def _failed_result(
        self,
        request: TaskRequest,
        artifact: Artifact,
        started_at: datetime,
        completed_at: datetime,
        delay_ms: int,
    ) -> TaskResult:
        error = ServiceError(
            error_id=uuid4(),
            code="MOCK_EXECUTION_FAILED",
            category="EXECUTION",
            message="The mock agent adapter was configured to fail this task.",
            retryable=False,
            service=self.service_name,
            details={"simulateFailure": True},
            correlation_id=f"run-{request.workflow_run_id}/task-{request.task_run_id}",
            occurred_at=completed_at,
        )
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[artifact],
            error=error,
            metrics=TaskMetrics(duration_ms=delay_ms),
            started_at=started_at,
            completed_at=completed_at,
            metadata={"agent_adapter": self.service_name, "deterministic": True},
        )

    @staticmethod
    def _integer(value: Any, *, default: int) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else default


def deterministic_attempt_artifact_id(attempt_id: UUID) -> UUID:
    """Expose the mock artifact identity rule for consumers and tests."""
    return uuid5(attempt_id, "mock-artifact")

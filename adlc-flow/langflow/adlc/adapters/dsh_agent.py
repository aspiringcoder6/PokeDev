"""DSH Agent Adapter — execute ADLC tasks via the remote DSH server.

This adapter implements the ``AgentAdapter`` protocol by delegating task
execution to a DeepSeek Harness (DSH) session running on a remote server.
The DSH server already hosts the vai-sandbox, vai-testforce, and
vai_agentmemory plugins, so the ADLC backend only needs the DSH SDK to
invoke them — no plugin code is downloaded or executed locally.

Flow:
    ADLC scheduler -> DSHAgentAdapter.execute()
        -> DshHarnessClient.create_session(prompt=task_objective)
        -> DSH LLM agent invokes vai-sandbox / vai-testforce / vai_agentmemory
        -> DSH session finalizes with a structured result
        -> DSHAgentAdapter projects the result into a v0.1 TaskResult

This adapter is opt-in: set ``ADLC_AGENT_ADAPTER=dsh`` to enable. The
``OpenCodeAgentAdapter`` remains the default for backward compatibility.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any
from uuid import UUID, uuid4

from langflow.adlc.adapter_interfaces import MemoryContext, SandboxSession
from langflow.adlc.harness_client import (
    HarnessClientError,
    HarnessServerSettings,
)
from langflow.adlc.harness_dsh_client import DshHarnessClient
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessExecutionSpec,
    HarnessPluginLockEntry,
    HarnessSessionRequest,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    TaskResultStatus,
)
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Stable error codes for DSH agent failures.
ERR_DSH_DISABLED = "DSH_AGENT_DISABLED"
ERR_DSH_NOT_READY = "DSH_AGENT_NOT_READY"
ERR_DSH_SESSION_REJECTED = "DSH_AGENT_SESSION_REJECTED"
ERR_DSH_SESSION_TIMEOUT = "DSH_AGENT_SESSION_TIMEOUT"
ERR_DSH_SESSION_FAILED = "DSH_AGENT_SESSION_FAILED"
ERR_DSH_INVALID_RESULT = "DSH_AGENT_INVALID_RESULT"


# Default plugin lock for DSH sessions: empty by default. The DSH server
# reports plugin integrity via /dsh-plugin-hub/installed; if specific
# plugins are required, callers can pass them via DSHAgentConfig.plugin_lock.
# Note: HarnessPluginLockEntry requires a valid SemanticVersion and Sha256Digest,
# so we cannot use "*" as a wildcard here.
DEFAULT_DSH_PLUGIN_LOCK: tuple[HarnessPluginLockEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class DSHAgentConfig:
    """Configuration for the DSHAgentAdapter."""

    base_url: str = "http://127.0.0.1:9982"
    api_token: str = ""
    idle_grace_seconds: float = 30.0
    goal_idle_grace_seconds: float = 120.0
    goal_enabled: bool = True
    plugin_lock: tuple[HarnessPluginLockEntry, ...] = DEFAULT_DSH_PLUGIN_LOCK
    timeout_seconds: float = 600.0  # 10 minutes default
    # How long consecutive retryable get_session() failures are tolerated
    # before the task fails; 0 disables tolerance (first failure surfaces).
    poll_failure_budget_seconds: float = 30.0


class DSHAgentAdapter:
    """AgentAdapter that delegates task execution to a remote DSH session.

    The DSH server hosts the vai-sandbox, vai-testforce, and vai_agentmemory
    plugins. This adapter creates a DSH session with a prompt that instructs
    the LLM agent to use those plugins, then projects the session result
    back into the ADLC v0.1 TaskResult contract.
    """

    service_name = "agent-provider:dsh"
    capabilities = (
        "dsh_session",
        "remote_sandbox",
        "remote_testing",
        "remote_memory",
        "plugin_lock",
        "structured_result",
    )

    def __init__(
        self,
        client: DshHarnessClient,
        *,
        config: DSHAgentConfig | None = None,
    ) -> None:
        self._client = client
        self._config = config or DSHAgentConfig()

    @property
    def config(self) -> DSHAgentConfig:
        return self._config

    @classmethod
    def from_environment(
        cls,
        *,
        client: DshHarnessClient | None = None,
    ) -> DSHAgentAdapter:
        """Build the adapter from ``ADLC_HARNESS_*`` environment variables."""
        settings = HarnessServerSettings.from_environment()
        config = DSHAgentConfig(
            base_url=settings.base_url,
            api_token=settings.api_token,
        )
        if client is None:
            client = DshHarnessClient(settings)
        return cls(client, config=config)

    @property
    def client(self) -> DshHarnessClient:
        return self._client

    async def execute(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        memory: MemoryContext,
    ) -> TaskResult:
        """Execute one ADLC task by creating a DSH session and awaiting its result."""
        started_at = _utc_now()
        started_at_ns = perf_counter_ns()

        if not self._config.api_token:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=ERR_DSH_DISABLED,
                category="VALIDATION",
                message="DSH agent adapter requires ADLC_HARNESS_API_TOKEN.",
                retryable=False,
            )

        cwd = self._resolve_cwd(sandbox)
        session_request = self._build_session_request(request, memory, cwd=cwd)

        try:
            accepted = await self._client.create_session(session_request)
        except HarnessClientError as exc:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code or ERR_DSH_SESSION_REJECTED,
                category=exc.category or "EXECUTION",
                message=str(exc),
                retryable=exc.retryable,
            )

        session_id = accepted.session.session_id
        try:
            result = await self._await_result(session_id, started_at_ns)
        except HarnessClientError as exc:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code or ERR_DSH_SESSION_FAILED,
                category=exc.category or "EXECUTION",
                message=str(exc),
                retryable=exc.retryable,
            )
        except TimeoutError:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=ERR_DSH_SESSION_TIMEOUT,
                category="TIMEOUT",
                message=f"DSH session {session_id} did not finalize within {self._config.timeout_seconds}s.",
                retryable=True,
            )

        return self._project_result(request, result, started_at, started_at_ns)

    async def _await_result(
        self,
        session_id: str,
        started_at_ns: int,
    ) -> HarnessSessionResult:
        """Poll the DSH session until it finalizes or times out."""
        import asyncio

        deadline = started_at_ns + int(self._config.timeout_seconds * 1_000_000_000)
        poll_interval = 2.0
        poll_failures_started: int | None = None
        while True:
            try:
                session = await self._client.get_session(session_id)
            except HarnessClientError as exc:
                # Survive transient transport blips (connection reset, brief
                # server restart) that must not destroy minutes of agent work;
                # surface the failure only once the retry budget is spent.
                if not exc.retryable:
                    raise
                now_ns = perf_counter_ns()
                if poll_failures_started is None:
                    poll_failures_started = now_ns
                if now_ns - poll_failures_started >= int(
                    self._config.poll_failure_budget_seconds * 1_000_000_000
                ):
                    raise
                await asyncio.sleep(poll_interval)
                continue
            poll_failures_started = None
            if session.result is not None:
                return session.result
            if session.status in (
                HarnessSessionStatus.SUCCEEDED,
                HarnessSessionStatus.FAILED,
                HarnessSessionStatus.CANCELLED,
            ):
                # Terminal without result — synthesize a failure.
                return HarnessSessionResult(
                    session_id=session_id,
                    correlation=session.correlation,
                    status=TaskResultStatus.FAILED,
                    output=None,
                    artifacts=[],
                    error=ServiceError(
                        error_id=uuid4(),
                        code=ERR_DSH_INVALID_RESULT,
                        category="EXECUTION",
                        message=f"DSH session ended with status {session.status} but no result.",
                        retryable=False,
                        service=self.service_name,
                        occurred_at=_utc_now(),
                    ),
                    metrics=TaskMetrics(duration_ms=0),
                    started_at=_utc_now(),
                    completed_at=_utc_now(),
                    metadata={"dsh_session_id": session_id},
                    plugin_lock=[],
                    trace_ref=None,
                    verification_reports=[],
                    interaction_records=[],
                )
            if perf_counter_ns() >= deadline:
                raise TimeoutError
            await asyncio.sleep(poll_interval)

    def _build_session_request(
        self,
        request: TaskRequest,
        memory: MemoryContext,
        *,
        cwd: str | None,
    ) -> HarnessSessionRequest:
        """Compose the DSH session request from the ADLC task request."""
        correlation = HarnessCorrelation(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
        )
        execution = HarnessExecutionSpec(
            profile_ref="adlc-dsh-agent",
            operation="execute_task",
            plugin_lock=list(self._config.plugin_lock),
        )
        objective = self._compose_objective(request, memory)
        context: dict[str, Any] = {}
        if cwd:
            context["cwd"] = cwd
        if memory.memory_refs:
            context["memory_refs"] = [str(ref) for ref in memory.memory_refs]
        return HarnessSessionRequest(
            correlation=correlation,
            idempotency_key=request.idempotency_key,
            objective=objective,
            input=request.input,
            result_schema_ref="adlc.task_result.v0.1",
            submission_mode=HarnessSubmissionMode.AUTO,
            execution=execution,
            context=context,
        )

    def _compose_objective(
        self,
        request: TaskRequest,
        memory: MemoryContext,
    ) -> str:
        """Render the ADLC task as a DSH prompt with plugin usage hints."""
        objective_parts: list[str] = [
            f"Task: {request.name}",
            f"Type: {request.task_type}",
            "",
            "Instructions:",
            "1. Use the vai-sandbox plugin to create an isolated execution environment.",
            "2. Use the vai-testforce plugin to run automated tests against your work.",
            "3. Use the vai_agentmemory plugin to persist and recall relevant context.",
            "4. When you have completed the task, reply with a single final message",
            "   summarizing the outcome. If you created or modified any files,",
            "   include their complete content wrapped in <adlc:file path=\"...\"> blocks.",
            "",
            "Task input:",
            json.dumps(request.input, default=str, indent=2) if request.input else "(none)",
        ]
        if memory.memory_refs:
            objective_parts.extend([
                "",
                "Memory context:",
                json.dumps(
                    [str(ref) for ref in memory.memory_refs],
                    indent=2,
                ),
            ])
        return "\n".join(objective_parts)

    def _resolve_cwd(self, sandbox: SandboxSession) -> str | None:
        """Extract the working directory from the sandbox session metadata."""
        cwd = sandbox.metadata.get("opencode_directory")
        if isinstance(cwd, str) and cwd.strip():
            return cwd
        workspace = sandbox.metadata.get("workspace")
        if isinstance(workspace, str) and workspace.strip():
            return workspace
        return None

    def _project_result(
        self,
        request: TaskRequest,
        result: HarnessSessionResult,
        started_at: datetime,
        started_at_ns: int,
    ) -> TaskResult:
        """Project a DSH session result into the ADLC v0.1 TaskResult contract."""
        completed_at = result.completed_at or _utc_now()
        duration_ms = int((perf_counter_ns() - started_at_ns) / 1_000_000)
        artifacts = [
            Artifact(
                artifact_id=uuid4(),
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
                kind=artifact.kind,
                name=artifact.name,
                media_type=artifact.media_type,
                uri=artifact.uri,
                size_bytes=artifact.size_bytes,
                checksum=Checksum(value=artifact.checksum),
                producer=self.service_name,
                created_at=artifact.created_at,
                metadata=artifact.metadata,
            )
            for artifact in result.artifacts
        ]
        error = None
        if result.error is not None:
            error = ServiceError(
                error_id=result.error.error_id,
                code=result.error.code,
                category=result.error.category,
                message=result.error.message,
                retryable=result.error.retryable,
                service=result.error.service,
                http_status=result.error.http_status,
                details=result.error.details,
                correlation_id=result.error.correlation_id,
                occurred_at=result.error.occurred_at,
            )
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=result.status,
            output=result.output,
            artifacts=artifacts,
            error=error,
            metrics=TaskMetrics(
                duration_ms=duration_ms,
                token_usage=result.metrics.token_usage,
                custom={
                    **result.metrics.custom,
                    "dsh_session_id": result.session_id,
                    "dsh_trace_ref": result.trace_ref,
                },
            ),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "dsh_session_id": result.session_id,
                "dsh_trace_ref": result.trace_ref,
                "dsh_plugin_lock": [entry.model_dump(mode="json") for entry in result.plugin_lock],
            },
        )

    def _failure_result(
        self,
        request: TaskRequest,
        *,
        started_at: datetime,
        started_at_ns: int,
        code: str,
        category: str,
        message: str,
        retryable: bool,
    ) -> TaskResult:
        completed_at = _utc_now()
        duration_ms = int((perf_counter_ns() - started_at_ns) / 1_000_000)
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
                category=category,  # type: ignore[arg-type]
                message=message,
                retryable=retryable,
                service=self.service_name,
                occurred_at=completed_at,
            ),
            metrics=TaskMetrics(duration_ms=duration_ms),
            started_at=started_at,
            completed_at=completed_at,
            metadata={"dsh_agent_error": code},
        )


__all__ = [
    "DSHAgentAdapter",
    "DSHAgentConfig",
    "DEFAULT_DSH_PLUGIN_LOCK",
    "ERR_DSH_DISABLED",
    "ERR_DSH_NOT_READY",
    "ERR_DSH_SESSION_REJECTED",
    "ERR_DSH_SESSION_TIMEOUT",
    "ERR_DSH_SESSION_FAILED",
    "ERR_DSH_INVALID_RESULT",
]

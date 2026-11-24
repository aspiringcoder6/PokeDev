"""OpenCode implementation of the stable ADLC AgentAdapter protocol."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4, uuid5

from langflow.adlc.artifact_payload_store import ArtifactPayloadStoreError, BoundedArtifactPayloadStore
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)
from langflow.adlc.opencode_client import (
    OpenCodeClientError,
    OpenCodeFileDiff,
    OpenCodeHttpClient,
    OpenCodeModelSelection,
    OpenCodePromptResult,
    OpenCodeServerSettings,
)

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import MemoryContext, SandboxSession
    from langflow.adlc.opencode_client import OpenCodeClient

_SYSTEM_PROMPT = """You are the coding agent for one ADLC task.
Work only inside the supplied workspace. Complete only the requested task, preserve unrelated work, and return a
concise factual summary. Do not expose credentials, environment secrets, or hidden configuration in your response.
"""
_WINDOWS_ABSOLUTE_PATH_PREFIX_LENGTH = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OpenCodeAgentAdapter:
    """Execute one ADLC task through a separately managed OpenCode server."""

    service_name = "agent-provider:opencode"
    capabilities = (
        "opencode_session",
        "code_analysis",
        "code_edit",
        "session_abort",
        "diff_artifact",
        "token_usage",
    )

    def __init__(
        self,
        client: OpenCodeClient,
        *,
        model: str | None = None,
        agent: str | None = None,
        allow_mock_sandbox: bool = False,
        artifact_payloads: BoundedArtifactPayloadStore | None = None,
    ) -> None:
        self._client = client
        self._model = OpenCodeModelSelection.parse(model)
        self._agent = agent
        self._allow_mock_sandbox = allow_mock_sandbox
        self._artifact_payloads = artifact_payloads if artifact_payloads is not None else BoundedArtifactPayloadStore()

    @classmethod
    def from_environment(
        cls,
        *,
        allow_mock_sandbox: bool = False,
        artifact_payloads: BoundedArtifactPayloadStore | None = None,
    ) -> OpenCodeAgentAdapter:
        """Build the adapter from server settings; provider keys stay owned by OpenCode."""
        settings = OpenCodeServerSettings.from_environment()
        return cls(
            OpenCodeHttpClient(settings),
            model=settings.model,
            agent=settings.agent,
            allow_mock_sandbox=allow_mock_sandbox,
            artifact_payloads=artifact_payloads,
        )

    @property
    def artifact_payloads(self) -> BoundedArtifactPayloadStore:
        return self._artifact_payloads

    async def execute(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        memory: MemoryContext,
    ) -> TaskResult:
        started_at = utc_now()
        started_at_ns = perf_counter_ns()
        directory = sandbox.metadata.get("opencode_directory")
        if not isinstance(directory, str) or not directory.strip():
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="OPENCODE_WORKSPACE_UNAVAILABLE",
                category="DEPENDENCY",
                message="The sandbox did not provide an OpenCode workspace directory.",
                retryable=False,
            )
        if sandbox.metadata.get("mock") is True and not self._allow_mock_sandbox:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="OPENCODE_REAL_SANDBOX_REQUIRED",
                category="DEPENDENCY",
                message="Live OpenCode execution requires a real sandbox or explicit development opt-in.",
                retryable=False,
            )

        timeout_ms = self._timeout_ms(request)
        session_id: str | None = None
        try:
            session = await self._client.create_session(
                directory=directory,
                title=f"ADLC task {request.task_run_id}",
                timeout_ms=min(timeout_ms, 10_000),
            )
            session_id = session.session_id
            prompt = self._build_prompt(request, memory)
            resumed_from = sandbox.metadata.get("resumed_from")
            if isinstance(resumed_from, str) and resumed_from:
                prompt += (
                    "\n\n[resume] Workspace nay da chua ket qua Mot LAN THU TRUOC (task bi timeout/loi giua chung). "
                    f"Snapshot: {resumed_from}. Hay KIEM TRA cac file da ton tai va TIEP TUC phan con lai, "
                    "dung viet lai tu dau; chi bo sung/sua nhung gi con thieu hoac sai."
                )
            prompt_result = await asyncio.wait_for(
                self._client.prompt(
                    session.session_id,
                    directory=directory,
                    prompt=prompt,
                    system=_SYSTEM_PROMPT,
                    model=self._model,
                    agent=self._agent,
                    timeout_ms=timeout_ms,
                ),
                timeout=timeout_ms / 1000,
            )
            diffs = await self._client.get_workspace_diff(
                directory=directory,
                timeout_ms=min(timeout_ms, 10_000),
            )
            return self._success_result(
                request,
                sandbox=sandbox,
                started_at=started_at,
                started_at_ns=started_at_ns,
                session_id=session_id,
                prompt_result=prompt_result,
                diffs=diffs,
            )
        except TimeoutError:
            await self._best_effort_abort(session_id, directory)
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="OPENCODE_TASK_TIMEOUT",
                category="TIMEOUT",
                message="OpenCode did not complete the task before its deadline.",
                retryable=True,
                session_id=session_id,
            )
        except asyncio.CancelledError:
            await self._best_effort_abort(session_id, directory)
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="OPENCODE_TASK_CANCELLED",
                category="CANCELLED",
                message="OpenCode execution was cancelled.",
                retryable=False,
                session_id=session_id,
                status=TaskResultStatus.CANCELLED,
            )
        except OpenCodeClientError as exc:
            if exc.category in {"TIMEOUT", "CANCELLED"}:
                await self._best_effort_abort(session_id, directory)
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code,
                category=exc.category,
                message="OpenCode could not complete the task.",
                retryable=exc.retryable,
                http_status=exc.http_status,
                session_id=session_id,
                status=(TaskResultStatus.CANCELLED if exc.category == "CANCELLED" else TaskResultStatus.FAILED),
            )
        except ArtifactPayloadStoreError as exc:
            return self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code,
                category="DEPENDENCY",
                message="The source patch could not be retained for review.",
                retryable=False,
                session_id=session_id,
            )
        finally:
            await self._best_effort_dispose(directory)

    async def _best_effort_abort(self, session_id: str | None, directory: str) -> None:
        if session_id is None:
            return
        try:
            await self._client.abort(session_id, directory=directory)
        except (OpenCodeClientError, TimeoutError):
            return

    async def _best_effort_dispose(self, directory: str) -> None:
        try:
            await self._client.dispose_instance(directory=directory)
        except (OpenCodeClientError, TimeoutError):
            return

    def _success_result(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        started_at: datetime,
        started_at_ns: int,
        session_id: str,
        prompt_result: OpenCodePromptResult,
        diffs: tuple[OpenCodeFileDiff, ...],
    ) -> TaskResult:
        completed_at = utc_now()
        usage = prompt_result.token_usage
        changed_files = self._changed_files(
            directory=str(sandbox.metadata["opencode_directory"]),
            values=(*prompt_result.changed_files, *(item.file for item in diffs)),
        )
        artifact, payload = self._build_artifact(
            request,
            session_id,
            prompt_result.message_id,
            diffs,
            changed_files,
            completed_at,
            directory=str(sandbox.metadata["opencode_directory"]),
        )
        self._artifact_payloads.retain(artifact, payload)
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output={
                "summary": prompt_result.text,
                "outputs": {
                    "source_patch": {
                        "artifact_id": str(artifact.artifact_id),
                        "uri": artifact.uri,
                        "changed_files": list(changed_files),
                    }
                },
            },
            artifacts=[artifact],
            error=None,
            metrics=TaskMetrics(
                duration_ms=self._duration_ms(started_at_ns),
                token_usage={
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.input_tokens + usage.output_tokens + usage.reasoning_tokens,
                },
                custom={
                    "reasoning_tokens": usage.reasoning_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "cost": prompt_result.cost,
                },
            ),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "agent_adapter": self.service_name,
                "opencode_session_id": session_id,
                "opencode_message_id": prompt_result.message_id,
                "provider_id": prompt_result.provider_id,
                "model_id": prompt_result.model_id,
                "finish": prompt_result.finish,
                "changed_file_count": len(changed_files),
                "sandbox_session_id": sandbox.session_id,
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
        http_status: int | None = None,
        session_id: str | None = None,
        status: TaskResultStatus = TaskResultStatus.FAILED,
    ) -> TaskResult:
        completed_at = utc_now()
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=status,
            output=None,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code=code,
                category=category,
                message=message,
                retryable=retryable,
                service=self.service_name,
                http_status=http_status,
                details={},
                correlation_id=f"run-{request.workflow_run_id}/task-{request.task_run_id}",
                occurred_at=completed_at,
            ),
            metrics=TaskMetrics(duration_ms=self._duration_ms(started_at_ns)),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "agent_adapter": self.service_name,
                "opencode_session_id": session_id,
            },
        )

    @staticmethod
    def _build_prompt(request: TaskRequest, memory: MemoryContext) -> str:
        input_payload = request.input if isinstance(request.input, dict) else {}
        context = request.context if isinstance(request.context, dict) else {}
        payload: dict[str, Any] = {
            "task": {
                "name": request.name,
                "type": request.task_type,
                "objective": input_payload.get("objective"),
                "named_inputs": input_payload.get("namedInputs", {}),
            },
            "context": {
                "memory_variables": memory.variables,
                "upstream_results": context.get("upstream_results", []),
                "resolved_input_bindings": context.get("resolved_input_bindings", []),
            },
        }
        return "Execute this ADLC task:\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    def _build_artifact(
        self,
        request: TaskRequest,
        session_id: str,
        message_id: str,
        diffs: tuple[OpenCodeFileDiff, ...],
        changed_files: tuple[str, ...],
        created_at: datetime,
        *,
        directory: str,
    ) -> tuple[Artifact, bytes]:
        files: list[dict[str, Any]] = []
        for item in diffs:
            relative = self._changed_files(directory=directory, values=(item.file,))
            if len(relative) != 1:
                code = "ARTIFACT_FILE_PATH_INVALID"
                raise ArtifactPayloadStoreError(code)
            files.append(
                {
                    "file": relative[0],
                    "patch": item.patch,
                    "additions": item.additions,
                    "deletions": item.deletions,
                    "status": item.status,
                }
            )
        snapshot = {
            "format": "opencode-vcs-diff-v1",
            "files": files,
            "reported_files": list(changed_files),
        }
        content = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        artifact_id = uuid5(request.attempt_id, "opencode-session-diff")
        artifact = Artifact(
            artifact_id=artifact_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            kind="SOURCE_PATCH",
            name="source-patch.json",
            media_type="application/vnd.opencode.vcs-diff+json",
            uri=f"adlc://runs/{request.workflow_run_id}/artifacts/{artifact_id}",
            size_bytes=len(content),
            checksum=Checksum(value=hashlib.sha256(content).hexdigest()),
            producer=OpenCodeAgentAdapter.service_name,
            created_at=created_at,
            expires_at=self._artifact_payloads.expires_at(created_at),
            metadata={
                "opencode_session_id": session_id,
                "opencode_message_id": message_id,
                "capture": "workspace-vcs-diff",
                "payload_retained": True,
                "changed_file_count": len(changed_files),
                "diff_file_count": len(diffs),
            },
        )
        return artifact, content

    @staticmethod
    def _changed_files(*, directory: str, values: tuple[str, ...]) -> tuple[str, ...]:
        workspace = directory.replace("\\", "/").rstrip("/")
        workspace_prefix = f"{workspace}/"
        normalized: list[str] = []
        for value in values:
            candidate = value.replace("\\", "/")
            if candidate.casefold().startswith(workspace_prefix.casefold()):
                candidate = candidate[len(workspace_prefix) :]
            elif candidate.startswith("/") or (
                len(candidate) >= _WINDOWS_ABSOLUTE_PATH_PREFIX_LENGTH and candidate[1:3] == ":/"
            ):
                continue
            candidate = candidate.removeprefix("./")
            if candidate and all(part not in {"", ".", ".."} for part in candidate.split("/")):
                normalized.append(candidate)
        return tuple(dict.fromkeys(normalized))

    @staticmethod
    def _timeout_ms(request: TaskRequest) -> int:
        constraints = request.constraints if isinstance(request.constraints, dict) else {}
        value = constraints.get("timeout_ms")
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 120_000

    @staticmethod
    def _duration_ms(started_at_ns: int) -> int:
        return max(0, (perf_counter_ns() - started_at_ns) // 1_000_000)


def deterministic_opencode_artifact_id(attempt_id: UUID) -> UUID:
    return uuid5(attempt_id, "opencode-session-diff")


__all__ = ["OpenCodeAgentAdapter", "deterministic_opencode_artifact_id"]

"""Adapter composition runtime hidden behind the scheduler's execution port."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from langflow.adlc.local_worktree_sandbox import LocalWorktreeSandboxError
from langflow.adlc.models import (
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import AdapterBundle, SandboxSession, StateChangeCallback
    from langflow.adlc.models import Artifact

_TERMINAL_TASK_STATUS = {
    TaskResultStatus.SUCCEEDED: TaskRunStatus.SUCCEEDED,
    TaskResultStatus.FAILED: TaskRunStatus.FAILED,
    TaskResultStatus.CANCELLED: TaskRunStatus.CANCELLED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _request_with_workspace(request: TaskRequest, session: SandboxSession) -> TaskRequest:
    """Expose the sandbox workspace to downstream adapters via ``request.context``.

    Testing adapters resolve the directory under test from
    ``request.context["workspace"]``; the sandbox is the component that
    actually knows the live worktree path, so the runtime bridges the two
    instead of every adapter re-deriving it.
    """
    workspace = session.metadata.get("opencode_directory") or session.workspace_uri
    context = dict(request.context) if isinstance(request.context, dict) else {}
    if not workspace or context.get("workspace"):
        return request
    context["workspace"] = str(workspace)
    return request.model_copy(update={"context": context})


class AdapterTaskExecutor:
    """Compose adapters while presenting one stable execution port to schedulers."""

    def __init__(self, adapters: AdapterBundle) -> None:
        self.adapters = adapters
        self.service_name = adapters.agent.service_name
        self.capabilities = adapters.agent.capabilities

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        started_at = utc_now()
        await on_state_change(TaskRunStatus.RUNNING, None)

        session: SandboxSession | None = None
        result: TaskResult | None = None
        active_service = self.adapters.sandbox.service_name
        try:
            session = await self.adapters.sandbox.open_session(request)
            active_service = self.adapters.memory.service_name
            memory = await self.adapters.memory.load_context(request)
            active_service = self.adapters.agent.service_name
            result = await self.adapters.agent.execute(request, sandbox=session, memory=memory)
            active_service = self.adapters.testing.service_name
            if session is not None:
                request = _request_with_workspace(request, session)
            result = await self.adapters.testing.evaluate(request, result)
            result = self._with_adapter_metadata(result, request)
            active_service = self.adapters.memory.service_name
            await self.adapters.memory.record_result(request, result)
        except Exception as exc:  # noqa: BLE001 - adapter failures are normalized at this boundary.
            result = self._failure_result(
                request,
                started_at=started_at,
                service=active_service,
                error=exc,
                artifacts=result.artifacts if result else [],
            )
        finally:
            if session is not None:
                try:
                    await self.adapters.sandbox.close_session(request, session)
                except Exception as exc:  # noqa: BLE001 - cleanup failures must not strand a RUNNING task.
                    if result is None or result.status is TaskResultStatus.SUCCEEDED:
                        result = self._failure_result(
                            request,
                            started_at=started_at,
                            service=self.adapters.sandbox.service_name,
                            error=exc,
                            artifacts=result.artifacts if result else [],
                        )

        if result is None:
            result = self._failure_result(
                request,
                started_at=started_at,
                service="adapter-task-executor",
                error=RuntimeError("The adapter chain returned no TaskResult."),
                artifacts=[],
            )

        await on_state_change(_TERMINAL_TASK_STATUS[result.status], result)
        return result

    def _with_adapter_metadata(self, result: TaskResult, request: TaskRequest) -> TaskResult:
        metadata = dict(result.metadata)
        metadata["adapter_services"] = {
            "sandbox": self.adapters.sandbox.service_name,
            "memory": self.adapters.memory.service_name,
            "testing": self.adapters.testing.service_name,
            "agent": self.adapters.agent.service_name,
        }
        traceability = request.metadata.get("plan_traceability")
        artifacts = result.artifacts
        if isinstance(traceability, dict):
            metadata["plan_traceability"] = dict(traceability)
            artifacts = [
                artifact.model_copy(
                    update={"metadata": {**artifact.metadata, "plan_traceability": dict(traceability)}},
                    deep=True,
                )
                for artifact in result.artifacts
            ]
        return result.model_copy(update={"metadata": metadata, "artifacts": artifacts}, deep=True)

    def _failure_result(
        self,
        request: TaskRequest,
        *,
        started_at: datetime,
        service: str,
        error: Exception,
        artifacts: list[Artifact],
    ) -> TaskResult:
        completed_at = utc_now()
        duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        worktree_error = error if isinstance(error, LocalWorktreeSandboxError) else None
        service_error = ServiceError(
            error_id=uuid4(),
            code=worktree_error.code if worktree_error else "ADAPTER_EXECUTION_FAILED",
            category="DEPENDENCY",
            message=f"The {service} adapter failed while executing the task.",
            retryable=True,
            service=service,
            details={
                "exception_type": type(error).__name__,
                **({"operation": worktree_error.operation} if worktree_error else {}),
            },
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
            artifacts=artifacts,
            error=service_error,
            metrics=TaskMetrics(duration_ms=duration_ms),
            started_at=started_at,
            completed_at=completed_at,
            metadata={"adapter_failure": True, "failed_adapter": service},
        )

"""Service-keyed task-executor routing behind the scheduler's stable port."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from langflow.adlc.models import ServiceError, TaskMetrics, TaskResult, TaskResultStatus, TaskRunStatus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langflow.adlc.adapter_interfaces import StateChangeCallback, TaskExecutor
    from langflow.adlc.models import TaskRequest


class TaskExecutorRecoveryError(RuntimeError):
    """The registered service cannot observe an already-dispatched attempt."""


class TaskExecutorRouter:
    """Dispatch task requests by their exact ``ExecutorTarget.service`` value."""

    router_service_name = "adlc-task-executor-router"

    def __init__(
        self,
        default_executor: TaskExecutor,
        *,
        routes: Mapping[str, TaskExecutor] | None = None,
    ) -> None:
        self._default_executor = default_executor
        self.service_name = default_executor.service_name
        self.capabilities = default_executor.capabilities
        self._routes: dict[str, TaskExecutor] = {default_executor.service_name: default_executor}
        for service, executor in (routes or {}).items():
            if not service.strip():
                msg = "Executor route service cannot be empty."
                raise ValueError(msg)
            existing = self._routes.get(service)
            if existing is not None and existing is not executor:
                msg = f"Executor route {service} is already registered."
                raise ValueError(msg)
            self._routes[service] = executor

    @property
    def available_services(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def bind_workflow_authority(self, authorize) -> None:
        for executor in self._routes.values():
            bind = getattr(executor, "bind_workflow_authority", None)
            if callable(bind):
                bind(authorize)

    def bind_plugin_workflow_authority(self, authorize) -> None:
        for executor in self._routes.values():
            bind = getattr(executor, "bind_plugin_workflow_authority", None)
            if callable(bind):
                bind(authorize)

    async def resume(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        executor = self._routes.get(request.executor.service)
        resume = getattr(executor, "resume", None)
        if not callable(resume):
            code = "ADLC_EXECUTOR_RECOVERY_NOT_SUPPORTED"
            raise TaskExecutorRecoveryError(code)
        return await resume(request, on_state_change)

    async def get_saved_result(self, request: TaskRequest) -> TaskResult | None:
        """Read an immutable completed attempt without dispatching provider work."""
        executor = self._routes.get(request.executor.service)
        read = getattr(executor, "get_saved_result", None)
        return await read(request) if callable(read) else None

    async def inspect_loop(self, request: TaskRequest):
        read = getattr(self._routes.get(request.executor.service), "inspect_loop", None)
        return await read(request) if callable(read) else None

    async def inspect_loop_runtime(self, request: TaskRequest):
        read = getattr(self._routes.get(request.executor.service), "inspect_loop_runtime", None)
        return await read(request) if callable(read) else None

    async def get_loop_request(self, service, run_id, task_id, definition_id):
        read = getattr(self._routes.get(service), "get_loop_request", None)
        return await read(service, run_id, task_id, definition_id) if callable(read) else None

    async def get_loop_artifact(self, request: TaskRequest, artifact_id):
        read = getattr(self._routes.get(request.executor.service), "get_loop_artifact", None)
        return await read(request, artifact_id) if callable(read) else None

    def validate_result(self, request: TaskRequest, result: TaskResult, *, owner_id: str) -> None:
        """Delegate kernel-owned final evidence checks without any provider call."""
        from langflow.adlc.contract_repository import ContractError

        executor = self._routes.get(request.executor.service)
        validate = getattr(executor, "validate_result", None)
        if not callable(validate):
            code = "CODING_AGENT_CONTRACT_EVIDENCE_UNAVAILABLE"
            raise ContractError(code, 422)
        validate(request, result, owner_id=owner_id)

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        executor = self._routes.get(request.executor.service)
        if executor is not None:
            return await executor.execute(request, on_state_change)

        started_at = datetime.now(timezone.utc)
        await on_state_change(TaskRunStatus.RUNNING, None)
        completed_at = datetime.now(timezone.utc)
        result = TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code="EXECUTOR_SERVICE_NOT_REGISTERED",
                category="DEPENDENCY",
                message="No task executor is registered for the requested service.",
                retryable=False,
                service=self.router_service_name,
                details={"requested_service": request.executor.service},
                correlation_id=f"run-{request.workflow_run_id}/task-{request.task_run_id}",
                occurred_at=completed_at,
            ),
            metrics=TaskMetrics(
                duration_ms=max(0, int((completed_at - started_at).total_seconds() * 1000)),
            ),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "executor_router": self.router_service_name,
                "requested_service": request.executor.service,
            },
        )
        await on_state_change(TaskRunStatus.FAILED, result)
        return result


__all__ = ["TaskExecutorRouter"]

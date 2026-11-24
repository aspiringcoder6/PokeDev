"""Plan-aware executor that combines planning and parallel execution.

This executor sits on top of :class:`DeepSeekHarnessTaskExecutor` and
:class:`PlanExecutor`. The flow is:

1. A plan for the task is produced. Two plan sources are supported:

   - ``template`` (default): a deterministic subtask DAG chosen by the
     task's type/name via :mod:`langflow.adlc.plan_templates`. No planner
     session is spent.
   - ``llm``: a "planner" DSH session is created with a prompt asking the
     LLM to produce a structured :class:`PlanSpec`.

2. The plan is validated.
3. :class:`PlanExecutor` dispatches each subtask as an independent ADLC
   task via :class:`DeepSeekHarnessTaskExecutor` — every subtask gets its
   own DSH session.
4. Results are aggregated into a single :class:`TaskResult` while subtask
   progress is mirrored into the subtask registry for the run-detail API.

If plan generation fails (e.g. the LLM returns prose instead of JSON in
``llm`` mode), the executor falls back to running the original task as a
single subtask. This keeps backward compatibility with prompts that don't
yet produce structured plans.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from langflow.adlc.adapter_interfaces import StateChangeCallback
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.models import (
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
)
from langflow.adlc.plan_executor import PlanExecutionResult, PlanExecutor
from langflow.adlc.plan_models import PlanSpec
from langflow.adlc.plan_parser import PlanParseError, parse_plan_response
from langflow.adlc.plan_prompt import render_plan_prompt
from langflow.adlc.plan_state import SubtaskState, SubtaskStatus
from langflow.adlc.plan_templates import build_task_plan
from langflow.adlc.plan_validator import PlanValidationError
from langflow.adlc.subtask_registry import get_subtask_registry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PlanOrchestratingExecutor:
    """Execute a task by first generating a plan, then running it in parallel.

    This executor implements the same interface as
    :class:`DeepSeekHarnessTaskExecutor` so it can be used as a drop-in
    replacement in the executor router.
    """

    service_name = "agent-provider:deepseek-harness"
    capabilities = (
        "harness:session",
        "harness:structured-result",
        "harness:signed-callback",
        "harness:verification",
        "harness:plan-orchestration",
    )

    def __init__(
        self,
        task_executor: DeepSeekHarnessTaskExecutor,
        *,
        max_parallel_subtasks: int = 5,
        enable_planning: bool = True,
        planning_mode: str = "template",
    ) -> None:
        self._task_executor = task_executor
        self._plan_executor = PlanExecutor(
            task_executor,
            max_parallel_subtasks=max_parallel_subtasks,
            observer=self._observe_subtask,
        )
        self._enable_planning = enable_planning
        self._planning_mode = planning_mode if planning_mode in {"template", "llm"} else "template"
        # (workflow_run_id, task_run_id) of the plan currently being executed.
        self._current: tuple[UUID, UUID] | None = None

    async def execute(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> TaskResult:
        """Execute the request, using plan orchestration when possible."""
        started_at = datetime.now(timezone.utc)
        await on_state_change(TaskRunStatus.RUNNING, None)

        if not self._enable_planning:
            return await self._task_executor.execute(request, on_state_change)

        # A fresh plan execution invalidates any subtask sessions left running
        # by a previous dispatch of this same task (retry / recovery).
        with suppress(Exception):
            await self._task_executor.cancel_orphaned_plan_sessions(
                request.workflow_run_id, request.task_run_id
            )

        # Step 1: Produce the plan.
        if self._planning_mode == "template":
            plan = self._template_plan(request)
        else:
            plan = await self._generate_plan(request, on_state_change)
        if plan is None:
            # Fallback: run the original task as a single subtask.
            logger.info(
                "Plan generation failed for request %s; falling back to single-task execution.",
                request.request_id,
            )
            return await self._task_executor.execute(request, on_state_change)

        # Register the subtasks so the run-detail API can expose live progress.
        self._register_plan(request, plan)
        self._current = (request.workflow_run_id, request.task_run_id)
        try:
            # Step 2: Execute the plan.
            try:
                plan_result = await self._plan_executor.execute(
                    plan,
                    workflow_run_id=request.workflow_run_id,
                    on_state_change=on_state_change,
                    parent_task_run_id=request.task_run_id,
                )
            except PlanValidationError as exc:
                logger.warning(
                    "Generated plan failed validation for request %s: %s. Falling back.",
                    request.request_id,
                    exc,
                )
                return await self._task_executor.execute(request, on_state_change)

            # Step 3: Aggregate into a TaskResult.
            return self._build_task_result(request, plan_result, started_at)
        finally:
            self._current = None

    async def resume(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> TaskResult:
        """Resume is not supported for plan orchestration; delegate to underlying executor."""
        return await self._task_executor.resume(request, on_state_change)

    # ------------------------------------------------------------------
    # Template planning + subtask registry
    # ------------------------------------------------------------------

    def _template_plan(self, request: TaskRequest) -> PlanSpec:
        """Build the deterministic subtask DAG for this task run."""
        task_run = TaskRun(
            id=request.task_run_id,
            workflow_run_id=request.workflow_run_id,
            task_definition_id=request.task_definition_id,
            key="task",
            name=request.name,
            task_type=request.task_type,
            status=TaskRunStatus.RUNNING,
            dependency_task_run_ids=list(request.dependency_task_run_ids),
            executor=request.executor,
            request=request,
        )
        return build_task_plan(task_run)

    def _register_plan(self, request: TaskRequest, plan: PlanSpec) -> None:
        """Seed the subtask registry for the run-detail endpoint."""
        try:
            get_subtask_registry().register_plan(request.workflow_run_id, request.task_run_id, plan)
        except Exception:  # noqa: BLE001 - registry mirroring must not break dispatch
            logger.warning("Failed to register plan subtasks for request %s.", request.request_id, exc_info=True)

    def _observe_subtask(self, plan: PlanSpec, sub_state: SubtaskState, result: TaskResult | None) -> None:
        """Mirror one subtask state change into the registry (best-effort).

        The observer receives the subtask's live state from the plan executor
        plus the terminal TaskResult (when available) so execution detail —
        session id, output, timing — can be attached for the detail view.
        """
        if self._current is None:
            return
        workflow_run_id, task_run_id = self._current
        detail: dict[str, Any] | None = None
        error: dict[str, str] | None = None
        if result is not None:
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            detail = {
                "session_id": metadata.get("harness_session_id")
                or metadata.get("dsh_session_id"),
                "output": result.output,
                "verification_reports": len(metadata.get("harness_verification_reports") or []),
                "interaction_records": len(metadata.get("harness_interaction_records") or []),
                "artifact_count": len(result.artifacts),
            }
            if result.error is not None:
                error = {"code": result.error.code, "message": result.error.message}
        elif sub_state.status is SubtaskStatus.FAILED and sub_state.error is not None:
            error = {"code": sub_state.error.code, "message": sub_state.error.message}

        duration_ms = None
        if sub_state.started_at is not None and sub_state.completed_at is not None:
            duration_ms = int((sub_state.completed_at - sub_state.started_at).total_seconds() * 1000)

        try:
            get_subtask_registry().observe(
                workflow_run_id,
                task_run_id,
                sub_state.subtask_id,
                status=sub_state.status,
                attempt_id=sub_state.attempt_id,
                started_at=sub_state.started_at.isoformat() if sub_state.started_at else None,
                completed_at=sub_state.completed_at.isoformat() if sub_state.completed_at else None,
                duration_ms=duration_ms,
                result=detail,
                error=error,
            )
        except Exception:  # noqa: BLE001 - registry mirroring must not break dispatch
            logger.warning("Failed to mirror subtask %s state.", sub_state.subtask_id, exc_info=True)

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _generate_plan(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> PlanSpec | None:
        """Run a planner session and parse the response into a PlanSpec."""
        objective = self._extract_objective(request)
        if not objective:
            return None

        planner_request = self._build_planner_request(request, objective)
        try:
            result = await self._task_executor.execute(planner_request, on_state_change)
        except Exception as exc:  # noqa: BLE001 - planner failure is non-fatal
            logger.warning("Planner session failed: %s", exc)
            return None

        if result.status is not TaskResultStatus.SUCCEEDED:
            logger.warning(
                "Planner session did not succeed: status=%s error=%s",
                result.status,
                result.error,
            )
            return None

        final_text = self._extract_final_text(result)
        if not final_text:
            return None

        try:
            return parse_plan_response(final_text, validate=True)
        except (PlanParseError, PlanValidationError) as exc:
            logger.info("Could not parse plan from planner output: %s", exc)
            return None

    @staticmethod
    def _extract_objective(request: TaskRequest) -> str:
        """Pull the user-facing objective out of a TaskRequest."""
        if isinstance(request.input, dict):
            obj = request.input.get("objective")
            if isinstance(obj, str) and obj.strip():
                return obj.strip()
        return request.name or ""

    def _build_planner_request(
        self,
        original: TaskRequest,
        objective: str,
    ) -> TaskRequest:
        """Build a TaskRequest that asks the LLM to produce a plan."""
        planner_prompt = render_plan_prompt(objective)
        return TaskRequest(
            request_id=uuid4(),
            workflow_run_id=original.workflow_run_id,
            task_run_id=original.task_run_id,
            attempt_id=uuid4(),
            task_definition_id=original.task_definition_id,
            task_type="plan_planner",
            name=f"Plan: {original.name}",
            executor=original.executor,
            input={
                "objective": planner_prompt,
                "original_objective": objective,
                "is_planner": True,
            },
            dependency_task_run_ids=list(original.dependency_task_run_ids),
            constraints={"timeout_ms": 300_000},  # 5 min for planning
            idempotency_key=f"{original.workflow_run_id}:planner:{original.task_run_id}",
            requested_at=datetime.now(timezone.utc),
            metadata={
                **original.metadata,
                "is_planner": True,
                "original_request_id": str(original.request_id),
            },
        )

    @staticmethod
    def _extract_final_text(result: TaskResult) -> str:
        """Pull the LLM's final text out of a TaskResult."""
        if isinstance(result.output, dict):
            for key in ("final_text", "summary", "output", "text"):
                value = result.output.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        if isinstance(result.output, str):
            return result.output
        return ""

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------

    def _build_task_result(
        self,
        request: TaskRequest,
        plan_result: PlanExecutionResult,
        started_at: datetime,
    ) -> TaskResult:
        """Convert a PlanExecutionResult into a TaskResult."""
        completed_at = datetime.now(timezone.utc)
        if plan_result.status is SubtaskStatus.SUCCEEDED:
            status = TaskResultStatus.SUCCEEDED
            error = None
        elif plan_result.status is SubtaskStatus.FAILED:
            status = TaskResultStatus.FAILED
            error = self._first_error(plan_result)
        elif plan_result.status is SubtaskStatus.CANCELLED:
            status = TaskResultStatus.CANCELLED
            error = None
        else:
            status = TaskResultStatus.FAILED
            error = ServiceError(
                error_id=uuid4(),
                code="PLAN_INCOMPLETE",
                category="EXECUTION",
                message=f"Plan ended in non-terminal state: {plan_result.status}",
                retryable=False,
                service=self.service_name,
                occurred_at=completed_at,
            )

        output = {
            "plan_id": plan_result.plan_id,
            "total_subtasks": plan_result.total,
            "succeeded": plan_result.succeeded,
            "failed": plan_result.failed,
            "task_results": {
                task_id: {
                    "status": tr.status.value,
                    "succeeded": tr.succeeded,
                    "failed": tr.failed,
                    "total": tr.total,
                    "subtask_results": {
                        sub_id: {
                            "status": sr.status.value,
                            "result": sr.result,
                            "error": sr.error.model_dump() if sr.error else None,
                        }
                        for sub_id, sr in tr.subtask_results.items()
                    },
                }
                for task_id, tr in plan_result.task_results.items()
            },
        }

        return TaskResult(
            schema_version="0.1",
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=status,
            output=output,
            artifacts=[],
            error=error,
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "plan_id": plan_result.plan_id,
                "subtask_count": plan_result.total,
            },
        )

    @staticmethod
    def _first_error(plan_result: PlanExecutionResult) -> ServiceError | None:
        """Return the first error from any subtask, if any."""
        for task_result in plan_result.task_results.values():
            for sub_result in task_result.subtask_results.values():
                if sub_result.error is not None:
                    return sub_result.error
        return None


# ----------------------------------------------------------------------
# Exports
# ----------------------------------------------------------------------


__all__ = ["PlanOrchestratingExecutor"]

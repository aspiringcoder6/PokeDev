"""DAG-based executor for :class:`PlanSpec`.

The executor walks the plan's task/subtask graph and dispatches each
subtask as an independent ADLC task via :class:`DeepSeekHarnessTaskExecutor`.
Subtasks with no outstanding dependencies run in parallel, up to
``max_parallel_subtasks`` at a time.

Failure semantics:

* If a subtask fails, every downstream subtask with ``trigger=on_success``
  is marked ``SKIPPED``.
* If a subtask fails and no downstream ``on_failure`` handler exists,
  the parent task is marked ``FAILED``.
* If a subtask succeeds, downstream ``on_success`` subtasks become ready.
* ``on_completed`` triggers fire regardless of success/failure.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID, uuid4

from langflow.adlc.adapter_interfaces import StateChangeCallback
from langflow.adlc.models import (
    ExecutorTarget,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)
from langflow.adlc.plan_models import (
    PlanSpec,
    SubtaskSpec,
    SubtaskTrigger,
    TaskSpec,
)
from langflow.adlc.plan_state import (
    PlanState,
    SubtaskState,
    SubtaskStatus,
    TaskState,
    initialize_plan_state,
)
from langflow.adlc.plan_validator import validate_plan

if TYPE_CHECKING:
    from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor

    #: Invoked after each subtask state change so callers can mirror progress
    #: (e.g. into the subtask registry) without coupling the executor to it.
    SubtaskObserver = Callable[[PlanSpec, SubtaskState, TaskResult | None], None]


class PlanExecutionError(RuntimeError):
    """Raised when the plan executor cannot proceed (e.g. invalid plan)."""


class PlanExecutor:
    """Execute a :class:`PlanSpec` by dispatching each subtask as an ADLC task."""

    def __init__(
        self,
        task_executor: DeepSeekHarnessTaskExecutor,
        *,
        max_parallel_subtasks: int = 5,
        observer: SubtaskObserver | None = None,
    ) -> None:
        if max_parallel_subtasks < 1:
            msg = "max_parallel_subtasks must be at least 1."
            raise ValueError(msg)
        self._task_executor = task_executor
        self._max_parallel = max_parallel_subtasks
        self._observer = observer

    async def execute(
        self,
        plan: PlanSpec,
        *,
        plan_id: str | None = None,
        workflow_run_id: UUID | None = None,
        on_state_change: StateChangeCallback | None = None,
        parent_task_run_id: UUID | None = None,
    ) -> PlanExecutionResult:
        """Execute the plan and return the aggregated result.

        Parameters
        ----------
        plan:
            The validated plan to execute.
        plan_id:
            Optional identifier for the plan instance. Defaults to a
            random UUID.
        workflow_run_id:
            The workflow run that owns this plan. Required so subtasks
            can be correlated back to the run.
        on_state_change:
            Optional callback invoked when a subtask transitions state.
        parent_task_run_id:
            The parent task run that owns this plan. Embedded in each
            subtask's idempotency key so orphaned sessions from a previous
            dispatch of the same task can be identified and cancelled.
        """
        validate_plan(plan)
        if workflow_run_id is None:
            msg = "workflow_run_id is required."
            raise PlanExecutionError(msg)

        plan_id = plan_id or str(uuid4())
        state = initialize_plan_state(plan, plan_id)
        callback = on_state_change or _noop_callback

        # Main loop: find ready subtasks, dispatch a batch, repeat.
        while not state.is_terminal:
            ready = self._get_ready_subtasks(plan, state)
            if not ready:
                # No ready subtasks but not terminal = deadlock (shouldn't
                # happen if the plan was validated).
                break

            batch = ready[: self._max_parallel]
            await self._dispatch_batch(plan, state, batch, workflow_run_id, callback, parent_task_run_id)

        return self._build_result(plan, state)

    # ------------------------------------------------------------------
    # Ready-node computation
    # ------------------------------------------------------------------

    def _get_ready_subtasks(self, plan: PlanSpec, state: PlanState) -> list[str]:
        """Return subtask IDs whose dependencies are all satisfied."""
        ready: list[str] = []
        for task in plan.tasks:
            for subtask in task.subtasks:
                sub_state = state.task_states[task.id].subtask_states[subtask.id]
                if sub_state.status is not SubtaskStatus.PENDING:
                    continue
                if self._dependencies_satisfied(subtask, state):
                    ready.append(subtask.id)
        return ready

    def _dependencies_satisfied(
        self,
        subtask: SubtaskSpec,
        state: PlanState,
    ) -> bool:
        """Check whether all of ``subtask``'s dependencies are satisfied."""
        for dep_id in subtask.dependencies:
            dep_state = self._find_subtask_state(state, dep_id)
            if dep_state is None:
                return False
            if subtask.trigger is SubtaskTrigger.ON_SUCCESS:
                if dep_state.status is not SubtaskStatus.SUCCEEDED:
                    return False
            elif subtask.trigger is SubtaskTrigger.ON_FAILURE:
                if dep_state.status is not SubtaskStatus.FAILED:
                    return False
            elif subtask.trigger is SubtaskTrigger.ON_COMPLETED:
                if dep_state.status not in (
                    SubtaskStatus.SUCCEEDED,
                    SubtaskStatus.FAILED,
                ):
                    return False
        return True

    # ------------------------------------------------------------------
    # Batch dispatch
    # ------------------------------------------------------------------

    async def _dispatch_batch(
        self,
        plan: PlanSpec,
        state: PlanState,
        batch: list[str],
        workflow_run_id: UUID,
        callback: StateChangeCallback,
        parent_task_run_id: UUID | None = None,
    ) -> None:
        """Dispatch a batch of subtasks in parallel."""
        tasks = [
            self._run_subtask(plan, state, subtask_id, workflow_run_id, callback, parent_task_run_id)
            for subtask_id in batch
        ]
        # return_exceptions=True so one failure doesn't cancel siblings.
        await asyncio.gather(*tasks, return_exceptions=True)
        # After the batch, propagate failures to downstream subtasks.
        self._propagate_failures(plan, state)

    async def _run_subtask(
        self,
        plan: PlanSpec,
        state: PlanState,
        subtask_id: str,
        workflow_run_id: UUID,
        callback: StateChangeCallback,
        parent_task_run_id: UUID | None = None,
    ) -> None:
        """Execute a single subtask and update its state."""
        found = self._find_subtask(plan, subtask_id)
        if found is None:
            return
        task, subtask = found
        task_state = state.task_states[task.id]
        sub_state = task_state.subtask_states[subtask_id]

        attempt_id = uuid4()
        sub_state.attempt_id = str(attempt_id)
        sub_state.status = SubtaskStatus.RUNNING
        sub_state.started_at = _utc_now()
        task_state.status = SubtaskStatus.RUNNING
        self._notify(plan, sub_state, None)
        await callback(TaskRunStatus.RUNNING, None)

        try:
            request = self._build_request(subtask, task, plan, workflow_run_id, attempt_id, parent_task_run_id)
            result = await self._task_executor.execute(request, callback)
            sub_state.completed_at = _utc_now()
            if result.status is TaskResultStatus.SUCCEEDED:
                sub_state.status = SubtaskStatus.SUCCEEDED
                sub_state.result = result.output
            else:
                sub_state.status = SubtaskStatus.FAILED
                sub_state.error = result.error
        except Exception as exc:  # noqa: BLE001 - convert to ServiceError
            sub_state.status = SubtaskStatus.FAILED
            sub_state.completed_at = _utc_now()
            sub_state.error = _exception_to_service_error(exc)
            result = None

        # Update parent task status.
        self._refresh_task_status(task_state)
        self._notify(plan, sub_state, result if isinstance(result, TaskResult) else None)

    def _build_request(
        self,
        subtask: SubtaskSpec,
        task: TaskSpec,
        plan: PlanSpec,
        workflow_run_id: UUID,
        attempt_id: UUID,
        parent_task_run_id: UUID | None = None,
    ) -> TaskRequest:
        """Build a :class:`TaskRequest` for a subtask."""
        task_run_id = uuid4()
        if parent_task_run_id is not None:
            idempotency_key = f"{workflow_run_id}:plan-{parent_task_run_id}:{subtask.id}:{attempt_id}"
        else:
            idempotency_key = f"{workflow_run_id}:{subtask.id}:{attempt_id}"
        return TaskRequest(
            request_id=uuid4(),
            workflow_run_id=workflow_run_id,
            task_run_id=task_run_id,
            attempt_id=attempt_id,
            task_definition_id=uuid4(),
            task_type="plan_subtask",
            name=subtask.name,
            executor=ExecutorTarget(
                service="agent-provider:deepseek-harness",
                operation="execute_subtask",
            ),
            input={
                "objective": subtask.objective,
                "subtask_id": subtask.id,
                "task_id": task.id,
                "plan_objective": plan.objective,
                "expected_outputs": subtask.expected_outputs,
            },
            dependency_task_run_ids=[],
            constraints={
                "timeout_ms": int((subtask.timeout_seconds or 900) * 1000),
            },
            idempotency_key=idempotency_key,
            requested_at=_utc_now(),
            metadata={
                "subtask_id": subtask.id,
                "task_id": task.id,
                "plan_id": plan.objective,
            },
        )

    # ------------------------------------------------------------------
    # Failure propagation
    # ------------------------------------------------------------------

    def _propagate_failures(self, plan: PlanSpec, state: PlanState) -> None:
        """Mark downstream subtasks as SKIPPED when their trigger can't fire."""
        for task in plan.tasks:
            for subtask in task.subtasks:
                sub_state = state.task_states[task.id].subtask_states[subtask.id]
                if sub_state.status is not SubtaskStatus.PENDING:
                    continue
                for dep_id in subtask.dependencies:
                    dep_state = self._find_subtask_state(state, dep_id)
                    if dep_state is None:
                        continue
                    if self._should_skip(subtask.trigger, dep_state.status):
                        sub_state.status = SubtaskStatus.SKIPPED
                        sub_state.completed_at = _utc_now()
                        self._notify(plan, sub_state, None)
                        break

    def _notify(self, plan: PlanSpec, sub_state: SubtaskState, result: TaskResult | None) -> None:
        """Forward one subtask state change to the observer, if one is attached."""
        if self._observer is None:
            return
        with contextlib.suppress(Exception):  # noqa: SIM105 - observation must not break dispatch
            self._observer(plan, sub_state, result)

    @staticmethod
    def _should_skip(trigger: SubtaskTrigger, dep_status: SubtaskStatus) -> bool:
        """Whether a subtask with ``trigger`` should be skipped given ``dep_status``."""
        if trigger is SubtaskTrigger.ON_SUCCESS:
            return dep_status in (SubtaskStatus.FAILED, SubtaskStatus.SKIPPED, SubtaskStatus.CANCELLED)
        if trigger is SubtaskTrigger.ON_FAILURE:
            return dep_status in (SubtaskStatus.SUCCEEDED, SubtaskStatus.SKIPPED, SubtaskStatus.CANCELLED)
        # ON_COMPLETED: never skip based on dep status.
        return False

    # ------------------------------------------------------------------
    # Result aggregation
    # ------------------------------------------------------------------

    def _build_result(self, plan: PlanSpec, state: PlanState) -> PlanExecutionResult:
        """Aggregate the final result from the plan state."""
        task_results: dict[str, TaskExecutionResult] = {}
        for task in plan.tasks:
            task_state = state.task_states[task.id]
            task_results[task.id] = TaskExecutionResult(
                task_id=task.id,
                status=task_state.status,
                subtask_results={
                    sub_id: SubtaskExecutionResult(
                        subtask_id=sub_id,
                        status=sub_state.status,
                        result=sub_state.result,
                        error=sub_state.error,
                        started_at=sub_state.started_at,
                        completed_at=sub_state.completed_at,
                    )
                    for sub_id, sub_state in task_state.subtask_states.items()
                },
            )
        # Refresh plan-level status from task statuses.
        state.status = self._aggregate_plan_status(state)
        return PlanExecutionResult(
            plan_id=state.plan_id,
            status=state.status,
            task_results=task_results,
        )

    @staticmethod
    def _aggregate_plan_status(state: PlanState) -> SubtaskStatus:
        """Compute the plan-level status from task statuses."""
        statuses = {t.status for t in state.task_states.values()}
        if SubtaskStatus.RUNNING in statuses:
            return SubtaskStatus.RUNNING
        if SubtaskStatus.FAILED in statuses:
            return SubtaskStatus.FAILED
        if SubtaskStatus.CANCELLED in statuses:
            return SubtaskStatus.CANCELLED
        if statuses == {SubtaskStatus.SUCCEEDED}:
            return SubtaskStatus.SUCCEEDED
        if statuses == {SubtaskStatus.SKIPPED}:
            return SubtaskStatus.SKIPPED
        return SubtaskStatus.PENDING

    def _refresh_task_status(self, task_state: TaskState) -> None:
        """Update a task's status based on its subtasks."""
        statuses = {s.status for s in task_state.subtask_states.values()}
        if SubtaskStatus.RUNNING in statuses:
            task_state.status = SubtaskStatus.RUNNING
        elif SubtaskStatus.FAILED in statuses:
            task_state.status = SubtaskStatus.FAILED
        elif statuses == {SubtaskStatus.SUCCEEDED}:
            task_state.status = SubtaskStatus.SUCCEEDED
        elif SubtaskStatus.SUCCEEDED in statuses and SubtaskStatus.SKIPPED in statuses:
            # Partial: some succeeded, some skipped (due to failed deps).
            task_state.status = SubtaskStatus.FAILED
        elif statuses == {SubtaskStatus.SKIPPED}:
            task_state.status = SubtaskStatus.SKIPPED
        elif statuses == {SubtaskStatus.CANCELLED}:
            task_state.status = SubtaskStatus.CANCELLED
        else:
            task_state.status = SubtaskStatus.PENDING

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_subtask(plan: PlanSpec, subtask_id: str) -> tuple[TaskSpec, SubtaskSpec] | None:
        for task in plan.tasks:
            for subtask in task.subtasks:
                if subtask.id == subtask_id:
                    return task, subtask
        return None

    @staticmethod
    def _find_subtask_state(state: PlanState, subtask_id: str) -> SubtaskState | None:
        for task_state in state.task_states.values():
            if subtask_id in task_state.subtask_states:
                return task_state.subtask_states[subtask_id]
        return None


# ----------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------


class SubtaskExecutionResult:
    """Final result for a single subtask."""

    def __init__(
        self,
        *,
        subtask_id: str,
        status: SubtaskStatus,
        result: Any,
        error: ServiceError | None,
        started_at: datetime | None,
        completed_at: datetime | None,
    ) -> None:
        self.subtask_id = subtask_id
        self.status = status
        self.result = result
        self.error = error
        self.started_at = started_at
        self.completed_at = completed_at


class TaskExecutionResult:
    """Final result for one task (group of subtasks)."""

    def __init__(
        self,
        *,
        task_id: str,
        status: SubtaskStatus,
        subtask_results: dict[str, SubtaskExecutionResult],
    ) -> None:
        self.task_id = task_id
        self.status = status
        self.subtask_results = subtask_results

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.subtask_results.values() if r.status is SubtaskStatus.SUCCEEDED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.subtask_results.values() if r.status is SubtaskStatus.FAILED)

    @property
    def total(self) -> int:
        return len(self.subtask_results)


class PlanExecutionResult:
    """Final result for the whole plan."""

    def __init__(
        self,
        *,
        plan_id: str,
        status: SubtaskStatus,
        task_results: dict[str, TaskExecutionResult],
    ) -> None:
        self.plan_id = plan_id
        self.status = status
        self.task_results = task_results

    @property
    def succeeded(self) -> int:
        return sum(t.succeeded for t in self.task_results.values())

    @property
    def failed(self) -> int:
        return sum(t.failed for t in self.task_results.values())

    @property
    def total(self) -> int:
        return sum(t.total for t in self.task_results.values())


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _noop_callback(_status: TaskRunStatus, _result: TaskResult | None) -> None:
    return None


def _exception_to_service_error(exc: Exception) -> ServiceError:
    return ServiceError(
        error_id=uuid4(),
        code="PLAN_SUBTASK_EXCEPTION",
        category="EXECUTION",
        message=str(exc) or exc.__class__.__name__,
        retryable=False,
        service="plan_executor",
        occurred_at=_utc_now(),
    )


__all__ = [
    "PlanExecutionError",
    "PlanExecutionResult",
    "PlanExecutor",
    "SubtaskExecutionResult",
    "TaskExecutionResult",
]

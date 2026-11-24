"""Scheduler-facing executor for asynchronous DeepSeek Harness sessions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from time import perf_counter, perf_counter_ns
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import ValidationError

from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_callbacks import HarnessCallbackError, HarnessCallbackReceiver
from langflow.adlc.harness_client import HarnessClient, HarnessClientError
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessExecutionSpec,
    HarnessPluginLockEntry,
    HarnessSessionRead,
    HarnessSessionRequest,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    TaskAttemptStatus,
)
from langflow.adlc.models import (
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.adapter_interfaces import StateChangeCallback


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def harness_result_to_task_result(result: HarnessSessionResult) -> TaskResult:
    """Use the same acceptance mapping for a live callback and restart recovery."""
    return TaskResult(
        request_id=result.correlation.request_id,
        workflow_run_id=result.correlation.workflow_run_id,
        task_run_id=result.correlation.task_run_id,
        attempt_id=result.correlation.attempt_id,
        status=result.status,
        output=result.output,
        artifacts=[artifact.model_copy(deep=True) for artifact in result.artifacts],
        error=result.error.model_copy(deep=True) if result.error is not None else None,
        metrics=result.metrics,
        started_at=result.started_at,
        completed_at=result.completed_at,
        metadata={
            **result.metadata,
            "harness_session_id": result.session_id,
            "harness_trace_ref": result.trace_ref,
            "harness_plugin_lock": [entry.model_dump(mode="json") for entry in result.plugin_lock],
            "harness_verification_reports": [report.model_dump(mode="json") for report in result.verification_reports],
            "harness_interaction_records": [record.model_dump(mode="json") for record in result.interaction_records],
        },
    )


class DeepSeekHarnessTaskExecutor:
    """Dispatch one ADLC task attempt and await its authenticated callback."""

    service_name = "agent-provider:deepseek-harness"
    capabilities = (
        "harness:session",
        "harness:structured-result",
        "harness:signed-callback",
        "harness:verification",
    )

    def __init__(
        self,
        client: HarnessClient,
        callbacks: HarnessCallbackReceiver,
        *,
        result_timeout_seconds: float = 900,
        status_poll_interval_seconds: float = 0.5,
        poll_failure_budget_seconds: float = 30.0,
    ) -> None:
        if result_timeout_seconds <= 0:
            msg = "Harness result timeout must be positive."
            raise ValueError(msg)
        if status_poll_interval_seconds <= 0:
            msg = "Harness status poll interval must be positive."
            raise ValueError(msg)
        if poll_failure_budget_seconds < 0:
            msg = "Harness poll failure budget must not be negative."
            raise ValueError(msg)
        self._client = client
        self._callbacks = callbacks
        self._result_timeout_seconds = result_timeout_seconds
        self._status_poll_interval_seconds = status_poll_interval_seconds
        self._poll_failure_budget_seconds = poll_failure_budget_seconds

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        started_at = utc_now()
        started_at_ns = perf_counter_ns()
        await on_state_change(TaskRunStatus.RUNNING, None)
        session_id: str | None = None
        try:
            await self._callbacks.register_attempt(request)
            session_request = self._session_request(request)
            accepted = await self._client.create_session(session_request)
            session_id = accepted.session.session_id
            bound_attempt = await self._callbacks.bind_session(request.attempt_id, session_id)
            if bound_attempt.status is TaskAttemptStatus.DISPATCHED:
                await self._callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.RUNNING)

            timeout_seconds = self._timeout_seconds(request)
            result = await self._wait_for_result(
                request,
                accepted.session,
                on_state_change,
                timeout_seconds=timeout_seconds,
            )
            task_result = harness_result_to_task_result(result)
        except HarnessClientError as exc:
            task_result = self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code,
                category=exc.category,
                retryable=exc.retryable,
                session_id=session_id,
            )
        except HarnessCallbackError as exc:
            if exc.code == "HARNESS_RESULT_TIMEOUT" and session_id is not None:
                with suppress(HarnessClientError):
                    await self._client.cancel_session(session_id)
            task_result = self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code,
                category="TIMEOUT" if exc.code == "HARNESS_RESULT_TIMEOUT" else "DEPENDENCY",
                retryable=exc.code in {"HARNESS_RESULT_TIMEOUT", "HARNESS_RESULT_MISSING"},
                session_id=session_id,
            )
        except (ValidationError, ValueError) as exc:
            task_result = self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="HARNESS_REQUEST_CONFIGURATION_INVALID",
                category="VALIDATION",
                retryable=False,
                session_id=session_id,
                details={"exception_type": type(exc).__name__},
            )
        except HarnessAttemptError as exc:
            task_result = self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code=exc.code,
                category="CONFLICT",
                retryable=False,
                session_id=session_id,
            )

        if task_result.status is TaskResultStatus.FAILED:
            await self._mark_attempt_failed(request.attempt_id)

        terminal_status = {
            TaskResultStatus.SUCCEEDED: TaskRunStatus.SUCCEEDED,
            TaskResultStatus.FAILED: TaskRunStatus.FAILED,
            TaskResultStatus.CANCELLED: TaskRunStatus.CANCELLED,
        }[task_result.status]
        await on_state_change(terminal_status, task_result)
        return task_result

    async def resume(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        """Observe an existing attempt only: never create, follow up, or cancel a remote session."""
        started_at = utc_now()
        started_at_ns = perf_counter_ns()
        session_id: str | None = None
        try:
            attempt = await self._callbacks.attempts.get(request.attempt_id)
            expected = HarnessCorrelation(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
            )
            if (
                attempt.request_id != request.request_id
                or attempt.workflow_run_id != request.workflow_run_id
                or attempt.task_run_id != request.task_run_id
                or attempt.idempotency_key != request.idempotency_key
            ):
                code = "HARNESS_RECOVERY_CORRELATION_MISMATCH"
                raise HarnessAttemptError(code, "The stored attempt does not match the request.")
            if attempt.result is not None:
                result = attempt.result
            else:
                session_id = attempt.external_session_id
                if session_id is None:
                    code = "HARNESS_RECOVERY_SESSION_MISSING"
                    raise HarnessAttemptError(code, "No existing session is bound to this attempt.")
                session = await self._client.get_session(session_id)
                if session.session_id != session_id or session.correlation != expected:
                    code = "HARNESS_RECOVERY_CORRELATION_MISMATCH"
                    raise HarnessAttemptError(code, "The live session does not match the stored request.")
                result = await self._wait_for_result(
                    request,
                    session,
                    on_state_change,
                    timeout_seconds=self._timeout_seconds(request),
                    initial_scheduler_status=None,
                )
            if result.correlation != expected:
                code = "HARNESS_RECOVERY_CORRELATION_MISMATCH"
                raise HarnessAttemptError(code, "The result does not match the stored request.")
            task_result = harness_result_to_task_result(result)
        except (HarnessClientError, HarnessAttemptError, HarnessCallbackError) as exc:
            task_result = self._failure_result(
                request,
                started_at=started_at,
                started_at_ns=started_at_ns,
                code="HARNESS_RECOVERY_SESSION_UNAVAILABLE",
                category="DEPENDENCY",
                retryable=True,
                session_id=session_id,
                details={"cause_code": exc.code, "replacement_started": False},
            )
            if task_result.error is not None:
                task_result.error.message = (
                    "The existing Harness attempt could not be reattached. No replacement session was started; "
                    "review its state before requesting Retry."
                )
        await on_state_change(TaskRunStatus(task_result.status.value), task_result)
        return task_result

    async def _wait_for_result(
        self,
        request: TaskRequest,
        initial_session: HarnessSessionRead,
        on_state_change: StateChangeCallback,
        *,
        timeout_seconds: float,
        initial_scheduler_status: TaskRunStatus | None = TaskRunStatus.RUNNING,
    ) -> HarnessSessionResult:
        result_waiter = asyncio.create_task(
            self._callbacks.wait_for_result(request.attempt_id, timeout_seconds=timeout_seconds)
        )
        session = initial_session
        expected_correlation = HarnessCorrelation(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
        )
        scheduler_status = initial_scheduler_status
        submitted = False
        poll_failures_started: float | None = None
        try:
            while True:
                if result_waiter.done():
                    return await result_waiter
                if session.session_id != initial_session.session_id or session.correlation != expected_correlation:
                    code = "HARNESS_SESSION_CORRELATION_MISMATCH"
                    raise HarnessAttemptError(code, "The observed session does not match the existing request.")
                scheduler_status, submitted = await self._observe_session(
                    request,
                    session,
                    on_state_change,
                    scheduler_status=scheduler_status,
                    submitted=submitted,
                )
                if result_waiter.done():
                    return await result_waiter
                done, _pending = await asyncio.wait(
                    {result_waiter},
                    timeout=self._status_poll_interval_seconds,
                )
                if done:
                    return await result_waiter
                # One transient transport blip (connection reset, proxy hiccup,
                # a brief Harness server restart) must not destroy a task that
                # the agent has been working on for minutes. Tolerate
                # consecutive retryable poll failures for a bounded budget and
                # only surface the failure once that budget is exhausted.
                try:
                    session = await self._client.get_session(session.session_id)
                except HarnessClientError as exc:
                    if not exc.retryable:
                        raise
                    now = perf_counter()
                    if poll_failures_started is None:
                        poll_failures_started = now
                    if now - poll_failures_started >= self._poll_failure_budget_seconds:
                        raise
                else:
                    poll_failures_started = None
        finally:
            if not result_waiter.done():
                result_waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await result_waiter

    async def _observe_session(
        self,
        request: TaskRequest,
        session: HarnessSessionRead,
        on_state_change: StateChangeCallback,
        *,
        scheduler_status: TaskRunStatus | None,
        submitted: bool,
    ) -> tuple[TaskRunStatus, bool]:
        attempt_status = {
            HarnessSessionStatus.ACCEPTED: TaskAttemptStatus.RUNNING,
            HarnessSessionStatus.PROVISIONING: TaskAttemptStatus.RUNNING,
            HarnessSessionStatus.RUNNING: TaskAttemptStatus.RUNNING,
            HarnessSessionStatus.WAITING_INTERACTION: TaskAttemptStatus.WAITING_INTERACTION,
            HarnessSessionStatus.VERIFYING: TaskAttemptStatus.VERIFYING,
            HarnessSessionStatus.READY_FOR_SUBMISSION: TaskAttemptStatus.READY_TO_SUBMIT,
        }.get(session.status)
        if attempt_status is not None:
            attempt = await self._callbacks.attempts.get(request.attempt_id)
            if attempt.result is None and attempt.status is not attempt_status:
                # A poll/restart can miss the short RUNNING phase between a
                # resolved interaction and verification/manual submission.
                try:
                    if attempt.status in {TaskAttemptStatus.DISPATCHED, TaskAttemptStatus.WAITING_INTERACTION} and (
                        attempt_status in {TaskAttemptStatus.VERIFYING, TaskAttemptStatus.READY_TO_SUBMIT}
                    ):
                        await self._callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.RUNNING)
                    await self._callbacks.attempts.update_status(request.attempt_id, attempt_status)
                except HarnessAttemptError:
                    # The signed callback may commit between our read and
                    # status projection. Its accepted result wins that race.
                    latest = await self._callbacks.attempts.get(request.attempt_id)
                    if latest.result is None:
                        raise

        waiting_for_human = session.status is HarnessSessionStatus.WAITING_INTERACTION or (
            session.status is HarnessSessionStatus.READY_FOR_SUBMISSION
            and session.submission_mode is HarnessSubmissionMode.MANUAL
        )
        desired_scheduler_status = TaskRunStatus.WAITING_APPROVAL if waiting_for_human else TaskRunStatus.RUNNING
        if desired_scheduler_status is not scheduler_status:
            await on_state_change(desired_scheduler_status, None)
            scheduler_status = desired_scheduler_status

        if (
            session.status is HarnessSessionStatus.READY_FOR_SUBMISSION
            and session.submission_mode is HarnessSubmissionMode.AUTO
            and not submitted
        ):
            await self._client.submit_session(session.session_id)
            submitted = True

        if session.result is not None and session.status in {
            HarnessSessionStatus.SUCCEEDED,
            HarnessSessionStatus.FAILED,
            HarnessSessionStatus.CANCELLED,
        }:
            await self._callbacks.accept_reconciled_result(session.result)

        return scheduler_status, submitted

    def _session_request(self, request: TaskRequest) -> HarnessSessionRequest:
        configuration = request.metadata.get("resolved_configuration", {})
        if not isinstance(configuration, dict):
            configuration = {}
        raw_plugin_lock = configuration.get("plugin_lock", [])
        if not isinstance(raw_plugin_lock, list):
            raw_plugin_lock = []
        plugin_lock = [HarnessPluginLockEntry.model_validate(entry) for entry in raw_plugin_lock]
        submission_mode = HarnessSubmissionMode(str(configuration.get("submission_mode", "AUTO")))
        objective = request.input.get("objective") if isinstance(request.input, dict) else None
        if not isinstance(objective, str) or not objective.strip():
            objective = request.name
        safe_metadata: dict[str, Any] = {}
        traceability = request.metadata.get("plan_traceability")
        if isinstance(traceability, dict):
            safe_metadata["plan_traceability"] = dict(traceability)
        source = request.metadata.get("source")
        if isinstance(source, str):
            safe_metadata["source"] = source
        return HarnessSessionRequest(
            correlation=HarnessCorrelation(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
            ),
            idempotency_key=request.idempotency_key,
            objective=objective,
            input=request.input,
            context=dict(request.context or {}),
            constraints=dict(request.constraints or {}),
            execution=HarnessExecutionSpec(
                profile_ref=str(configuration.get("harness_profile_ref", "harness-profile:adlc-coding/0.1.0")),
                operation=request.executor.operation,
                plugin_lock=plugin_lock,
            ),
            result_schema_ref=str(configuration.get("result_schema_ref", "adlc://schemas/source-patch/0.1")),
            submission_mode=submission_mode,
            callback_ref=str(configuration.get("callback_ref", "adlc-primary")),
            metadata=safe_metadata,
        )

    def _timeout_seconds(self, request: TaskRequest) -> float:
        constraints = request.constraints or {}
        timeout_ms = constraints.get("timeout_ms")
        if isinstance(timeout_ms, int) and not isinstance(timeout_ms, bool) and timeout_ms > 0:
            return min(self._result_timeout_seconds, timeout_ms / 1000)
        return self._result_timeout_seconds

    async def _mark_attempt_failed(self, attempt_id: UUID) -> None:
        try:
            attempt = await self._callbacks.attempts.get(attempt_id)
            if attempt.status not in {
                TaskAttemptStatus.SUCCEEDED,
                TaskAttemptStatus.FAILED,
                TaskAttemptStatus.CANCELLED,
            }:
                await self._callbacks.attempts.update_status(attempt_id, TaskAttemptStatus.FAILED)
        except HarnessAttemptError:
            pass

    async def cancel_orphaned_plan_sessions(self, workflow_run_id: UUID, parent_task_run_id: UUID) -> int:
        """Cancel non-terminal plan-subtask sessions left by a previous dispatch.

        Re-running a plan (task retry, recovery after a restart) previously
        left the old subtask sessions running on the DSH server, which made
        one logical subtask appear to use several sessions. Only attempts
        whose idempotency key carries this task's ``plan-<task_run_id>``
        marker are considered orphans, so concurrent plan-orchestrated tasks
        never cancel each other's sessions.
        """
        marker = f":plan-{parent_task_run_id}:"
        try:
            attempts = await self._callbacks.attempts.list_for_workflow_run(workflow_run_id)
        except HarnessAttemptError:
            return 0
        cancelled = 0
        for attempt in attempts:
            if attempt.status in {
                TaskAttemptStatus.SUCCEEDED,
                TaskAttemptStatus.FAILED,
                TaskAttemptStatus.CANCELLED,
            }:
                continue
            if marker not in str(attempt.idempotency_key):
                continue
            if not attempt.external_session_id:
                continue
            try:
                await self._client.cancel_session(attempt.external_session_id)
            except HarnessClientError:
                continue
            with suppress(HarnessAttemptError):
                await self._callbacks.attempts.update_status(attempt.attempt_id, TaskAttemptStatus.CANCELLED)
            cancelled += 1
        return cancelled

    @staticmethod
    def _failure_result(
        request: TaskRequest,
        *,
        started_at: datetime,
        started_at_ns: int,
        code: str,
        category: str,
        retryable: bool,
        session_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> TaskResult:
        completed_at = utc_now()
        duration_ms = max(0, int((perf_counter_ns() - started_at_ns) / 1_000_000))
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
                category=category,
                message="The DeepSeek Harness attempt could not produce an accepted result.",
                retryable=retryable,
                service=DeepSeekHarnessTaskExecutor.service_name,
                details=details or {},
                correlation_id=f"run-{request.workflow_run_id}/task-{request.task_run_id}",
                occurred_at=completed_at,
            ),
            metrics=TaskMetrics(duration_ms=duration_ms),
            started_at=started_at,
            completed_at=completed_at,
            metadata={
                "harness_failure": True,
                **({"harness_session_id": session_id} if session_id is not None else {}),
            },
        )


__all__ = ["DeepSeekHarnessTaskExecutor"]

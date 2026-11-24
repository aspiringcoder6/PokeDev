"""Bounded operator views, separate from immutable loop input/evidence contracts.

Only kernel-owned IDs, relative paths, check outcomes and usage enter this view.
Prompts, source bytes, test output, provider messages and host paths stay private.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003 - Pydantic runtime field.

from pydantic import Field, field_validator

from langflow.adlc.coding_agent_loop_models import CodingAgentContractVerification
from langflow.adlc.contract_execution_models import JSON_VERIFIER, PATCH_VERIFIER, UNCHANGED_VERIFIER
from langflow.adlc.task_loop_live_models import LiveLoopSpec
from langflow.adlc.task_loop_models import Digest, LoopModel, TaskLoopSpec, validate_file_path
from langflow.adlc.task_loop_workspace import LiveLoopError

if TYPE_CHECKING:
    from langflow.adlc.models import TaskRequest, TaskResult
    from langflow.adlc.task_loop_store import LiveLoopAttempt, TaskLoopStore


class LoopCheckView(LoopModel):
    check_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=1024)
    kind: Literal["BEHAVIORAL", "CONTRACT", "MOCK"]
    passed: bool
    exit_code: int | None = None
    executed_tests: int | None = Field(default=None, ge=0)
    timed_out: bool | None = None


class LoopIterationView(LoopModel):
    iteration: int = Field(ge=1, le=100)
    attempt_id: UUID
    session_id: str | None = Field(default=None, max_length=512)
    phase: Literal["RESERVED", "AGENT_RUNNING", "CANDIDATE_CAPTURED", "VERIFIED", "FINISHED"]
    status: Literal["IN_PROGRESS", "PASSED", "CHECKS_FAILED", "FAILED", "CANCELLED"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    candidate_id: UUID | None = None
    candidate_digest: Digest | None = None
    parent_candidate_id: UUID | None = None
    changed_paths: tuple[str, ...] = Field(default=(), max_length=64)
    patch_artifact_id: UUID | None = None
    checks: tuple[LoopCheckView, ...] = Field(default=(), max_length=288)
    total_tokens: int | None = Field(default=None, ge=0)
    cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    stop_reason: str | None = Field(default=None, max_length=160)

    @field_validator("changed_paths")
    @classmethod
    def relative_paths(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        for path in paths:
            validate_file_path(path)
        return paths


class RunOperatorControls(LoopModel):
    workflow_run_id: UUID
    can_pause: bool
    can_resume: bool
    can_cancel: bool
    pause_requested: bool
    pause_reason: str | None = None


class LoopFailurePattern(LoopModel):
    check_id: str = Field(max_length=160)
    label: str = Field(max_length=1024)
    kind: Literal["BEHAVIORAL", "CONTRACT", "MOCK"]
    iterations: tuple[int, ...] = Field(max_length=100)


class TaskLoopInspection(LoopModel):
    schema_version: Literal["0.1"] = "0.1"
    workflow_run_id: UUID
    task_run_id: UUID
    mode: Literal["COMMAND", "MOCK"]
    history_source: Literal["CHECKPOINT", "MEMORY", "RUN_SNAPSHOT", "UNAVAILABLE", "NOT_STARTED"] = "UNAVAILABLE"
    history_complete: bool = False
    unavailable_reason: str | None = Field(default=None, max_length=160)
    spec_digest: Digest | None = None
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    max_duration_ms: int | None = Field(default=None, ge=1)
    max_total_tokens: int | None = Field(default=None, ge=1)
    max_total_cost: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    elapsed_ms: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    total_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    current_candidate_id: UUID | None = None
    current_candidate_digest: Digest | None = None
    stopped: bool = False
    stop_reason: str | None = Field(default=None, max_length=160)
    can_retry: bool = False
    recovery_available: bool = False
    iterations: tuple[LoopIterationView, ...] = Field(default=(), max_length=100)
    failure_patterns: tuple[LoopFailurePattern, ...] = Field(default=(), max_length=288)


def inspect_spec(request: TaskRequest) -> LiveLoopSpec | TaskLoopSpec:
    """Validate saved input without calling a provider, policy hook or workspace."""
    payload = request.input if isinstance(request.input, dict) else {}
    inputs = payload.get("namedInputs", {})
    spec = inputs.get("task_loop_spec") if isinstance(inputs, dict) else None
    model = TaskLoopSpec if request.executor.service == "agent-provider:task-loop-mock" else LiveLoopSpec
    return model.model_validate(spec)


def empty_inspection(request: TaskRequest) -> TaskLoopInspection:
    spec = inspect_spec(request)
    configured = (request.constraints or {}).get("max_attempts", spec.max_iterations)
    if not isinstance(configured, int) or isinstance(configured, bool) or configured < 1:
        code = "TASK_LOOP_INPUT_INVALID"
        raise LiveLoopError(code)
    return TaskLoopInspection(
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        mode="COMMAND" if isinstance(spec, LiveLoopSpec) else "MOCK",
        spec_digest=spec.content_digest,
        max_iterations=min(configured, spec.max_iterations),
        **(
            {
                "max_duration_ms": spec.max_duration_ms,
                "max_total_tokens": spec.max_total_tokens,
                "max_total_cost": spec.max_total_cost,
            }
            if isinstance(spec, LiveLoopSpec)
            else {}
        ),
    )


def result_reason(result: TaskResult | None) -> str | None:
    if result is None:
        return None
    info = result.metadata.get("task_loop", {})
    reason = info.get("stop_reason") if isinstance(info, dict) else None
    return reason if isinstance(reason, str) else result.error.code if result.error else None


def live_iteration(attempt: LiveLoopAttempt, spec: LiveLoopSpec) -> LoopIterationView:
    candidate, verification, result = attempt.candidate, attempt.verification, attempt.result
    checks: list[LoopCheckView] = []
    if verification is not None:
        if (
            candidate is None
            or verification.spec_digest != spec.content_digest
            or verification.candidate_id != candidate.candidate_id
            or verification.candidate_digest != candidate.content_digest
            or {item.check_id for item in verification.checks} != {item.check_id for item in spec.verification_commands}
        ):
            code = "TASK_LOOP_VERIFICATION_MISMATCH"
            raise LiveLoopError(code)
        for check in verification.checks:
            labels = [item.description for item in spec.acceptance_criteria if check.check_id in item.check_refs]
            checks.append(
                LoopCheckView(
                    check_id=check.check_id,
                    label="; ".join(labels)[:1024] or check.check_id,
                    kind="BEHAVIORAL",
                    passed=check.passed,
                    exit_code=check.exit_code,
                    executed_tests=check.executed_tests,
                    timed_out=check.timed_out,
                )
            )
    if attempt.additional_evidence:
        report = CodingAgentContractVerification.model_validate(attempt.additional_evidence)
        if (
            candidate is None
            or report.spec_digest != spec.content_digest
            or report.candidate_id != candidate.candidate_id
            or report.candidate_digest != candidate.content_digest
        ):
            code = "TASK_LOOP_VERIFICATION_MISMATCH"
            raise LiveLoopError(code)
        labels = {
            PATCH_VERIFIER: "Patch contains changes",
            UNCHANGED_VERIFIER: "Files unchanged",
            JSON_VERIFIER: "Changed JSON is valid",
        }
        checks.extend(
            LoopCheckView(
                check_id=f"{check.node_id}:{check.criterion_index}",
                label=labels.get(check.verifier_ref, check.verifier_ref),
                kind="CONTRACT",
                passed=check.passed,
            )
            for check in report.checks
        )
    reason = result_reason(result)
    status = (
        "IN_PROGRESS"
        if result is None
        else "PASSED"
        if result.status.value == "SUCCEEDED"
        else "CANCELLED"
        if result.status.value == "CANCELLED"
        else "CHECKS_FAILED"
        if checks and any(not check.passed for check in checks)
        else "FAILED"
    )
    return LoopIterationView(
        iteration=attempt.iteration,
        attempt_id=attempt.attempt_id,
        session_id=attempt.session_id,
        phase=attempt.phase,
        status=status,
        started_at=attempt.started_at,
        completed_at=result.completed_at if result else None,
        duration_ms=max(0, int((result.completed_at - attempt.started_at).total_seconds() * 1000)) if result else None,
        candidate_id=candidate.candidate_id if candidate else None,
        candidate_digest=candidate.content_digest if candidate else None,
        parent_candidate_id=candidate.parent_candidate_id if candidate else None,
        changed_paths=tuple(sorted(candidate.changes)) if candidate else (),
        patch_artifact_id=next((item.artifact_id for item in attempt.artifacts if item.kind == "SOURCE_PATCH"), None),
        checks=tuple(checks),
        total_tokens=(
            attempt.total_tokens
            if attempt.phase in {"CANDIDATE_CAPTURED", "VERIFIED", "FINISHED"}
            and not (
                attempt.runtime_checkpoint
                and attempt.runtime_checkpoint.schema_version == "0.2"
                and attempt.runtime_checkpoint.session is not None
                and attempt.runtime_checkpoint.usage is None
            )
            else None
        ),
        cost=attempt.cost if attempt.phase in {"CANDIDATE_CAPTURED", "VERIFIED", "FINISHED"} else None,
        stop_reason=reason,
    )


def failure_patterns(iterations: tuple[LoopIterationView, ...]) -> tuple[LoopFailurePattern, ...]:
    failed: dict[tuple[str, str], tuple[LoopCheckView, list[int]]] = {}
    for iteration in iterations:
        for check in iteration.checks:
            if not check.passed:
                entry = failed.setdefault((check.kind, check.check_id), (check, []))
                if iteration.iteration not in entry[1]:
                    entry[1].append(iteration.iteration)
    return tuple(
        LoopFailurePattern(check_id=check.check_id, label=check.label, kind=check.kind, iterations=tuple(numbers))
        for check, numbers in failed.values()
        if len(numbers) > 1
    )


def elapsed_ms(started_at: datetime, iterations: tuple[LoopIterationView, ...], *, stopped: bool) -> int:
    ended_at = iterations[-1].completed_at if stopped and iterations else None
    return max(0, int(((ended_at or datetime.now(timezone.utc)) - started_at).total_seconds() * 1000))


def inspect_live_loop(store: TaskLoopStore, request: TaskRequest) -> TaskLoopInspection:
    view = empty_inspection(request)
    spec = LiveLoopSpec.model_validate(inspect_spec(request))
    state, attempts = store.inspect(request)
    if state is None:
        return view.model_copy(update={"history_source": "CHECKPOINT", "history_complete": True})
    if state.spec_digest != spec.content_digest or state.max_iterations != view.max_iterations:
        code = "TASK_LOOP_CHECKPOINT_CORRUPT"
        raise LiveLoopError(code)
    iterations = tuple(live_iteration(attempt, spec) for attempt in attempts)
    candidate = next((attempt.candidate for attempt in reversed(attempts) if attempt.candidate), state.current)
    tokens = max(state.total_tokens, sum(item.total_tokens for item in attempts))
    cost = (
        max(state.total_cost, sum(item.cost for item in attempts))
        if state.total_cost is not None and all(item.cost is not None for item in attempts)
        else None
    )
    elapsed = elapsed_ms(state.started_at, iterations, stopped=state.stopped)
    reason = result_reason(attempts[-1].result) if attempts else None
    stopped = state.stopped
    if not stopped and attempts and attempts[-1].result is not None:
        # Between attempts, reflect the same guards that the kernel will enforce before dispatch.
        limit = (
            "TASK_LOOP_TIME_BUDGET_EXHAUSTED"
            if elapsed >= spec.max_duration_ms
            else "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"
            if spec.max_total_tokens is not None and tokens >= spec.max_total_tokens
            else "TASK_LOOP_COST_BUDGET_EXHAUSTED"
            if spec.max_total_cost is not None and (cost is None or cost >= spec.max_total_cost)
            else "TASK_LOOP_BUDGET_EXHAUSTED"
            if state.next_iteration > state.max_iterations
            else None
        )
        if limit:
            stopped, reason = True, limit
    return view.model_copy(
        update={
            "history_source": "CHECKPOINT",
            "history_complete": True,
            "iterations": iterations,
            "failure_patterns": failure_patterns(iterations),
            "current_candidate_id": candidate.candidate_id,
            "current_candidate_digest": candidate.content_digest,
            "stopped": stopped,
            "stop_reason": reason,
            "total_tokens": (
                None
                if any(
                    a.runtime_checkpoint
                    and a.runtime_checkpoint.schema_version == "0.2"
                    and a.runtime_checkpoint.session is not None
                    and a.runtime_checkpoint.usage is None
                    for a in attempts
                )
                else tokens
            ),
            "total_cost": cost,
            "elapsed_ms": elapsed,
        }
    )

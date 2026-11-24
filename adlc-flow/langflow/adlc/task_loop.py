"""One mock loop iteration per ADLC attempt; the coordinator owns repetition."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, NoReturn
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)
from langflow.adlc.task_loop_inspection import (
    LoopCheckView,
    LoopIterationView,
    empty_inspection,
    failure_patterns,
    inspect_spec,
    result_reason,
)
from langflow.adlc.task_loop_models import (
    MockTaskLoopConfiguration,
    MockTaskLoopStep,
    TaskLoopCandidate,
    TaskLoopCheck,
    TaskLoopIteration,
    TaskLoopPrompt,
    TaskLoopSpec,
    TaskLoopVerification,
)

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import StateChangeCallback
    from langflow.adlc.models import TaskRequest

TASK_LOOP_MOCK_ENABLED_ENV = "ADLC_TASK_LOOP_MOCK_ENABLED"
TASK_LOOP_MOCK_SERVICE = "agent-provider:task-loop-mock"


def task_loop_mock_enabled() -> bool:
    return os.getenv(TASK_LOOP_MOCK_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MockTaskLoopSession:
    session_id: UUID
    messages: tuple[str, ...]


class MockTaskLoopAgent:
    """Creates a new one-message session, then applies only this iteration's edit."""

    def __init__(self) -> None:
        self.sessions: list[MockTaskLoopSession] = []

    async def execute(self, prompt: TaskLoopPrompt, step: MockTaskLoopStep) -> tuple[UUID, dict[str, str]]:
        session = MockTaskLoopSession(session_id=uuid4(), messages=(prompt.model_dump_json(),))
        self.sessions.append(session)
        files = dict(prompt.candidate.files)
        for path, content in step.changes.items():
            if content is None:
                files.pop(path, None)
            else:
                files[path] = content
        return session.session_id, files


def verify_mock_candidate(spec: TaskLoopSpec, candidate: TaskLoopCandidate) -> TaskLoopVerification:
    """Exact file comparisons are mock evidence, never behavioral test claims."""
    return TaskLoopVerification(
        candidate_id=candidate.candidate_id,
        candidate_digest=candidate.content_digest,
        checks=tuple(
            TaskLoopCheck(
                criterion_id=criterion.criterion_id,
                passed=candidate.files.get(criterion.path) == criterion.expected_content,
                message=(
                    "Expected mock file content is present."
                    if candidate.files.get(criterion.path) == criterion.expected_content
                    else f"Mock file '{criterion.path}' does not match the acceptance criterion."
                ),
            )
            for criterion in spec.acceptance_criteria
        ),
    )


@dataclass
class _LoopState:
    spec_digest: str
    configuration_digest: str
    task_definition_id: UUID
    max_iterations: int
    current: TaskLoopCandidate
    iterations: list[TaskLoopIteration] = field(default_factory=list)
    stalled_iterations: int = 0
    stopped: bool = False


class _LoopError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reject(code: str) -> NoReturn:
    raise _LoopError(code)


class MockTaskLoopExecutor:
    """In-memory Delivery A executor. Only failed checks request another attempt."""

    service_name = TASK_LOOP_MOCK_SERVICE
    capabilities = ("task-loop:mock", "task-loop:fresh-session", "task-loop:candidate-snapshot")

    def __init__(self, *, agent: MockTaskLoopAgent | None = None) -> None:
        self.agent = agent or MockTaskLoopAgent()
        self._states: dict[tuple[UUID, UUID], _LoopState] = {}
        self._locks: dict[tuple[UUID, UUID], asyncio.Lock] = {}
        self._results: dict[str, tuple[str, TaskResult]] = {}
        self._attempt_keys: dict[UUID, str] = {}
        self._inspection_requests: dict[tuple[UUID, UUID], TaskRequest] = {}

    def history(self, workflow_run_id: UUID, task_run_id: UUID) -> tuple[TaskLoopIteration, ...]:
        state = self._states.get((workflow_run_id, task_run_id))
        return tuple(item.model_copy(deep=True) for item in state.iterations) if state else ()

    async def inspect_loop(self, request: TaskRequest):
        view = empty_inspection(request)
        state = self._states.get((request.workflow_run_id, request.task_run_id))
        if state is None:
            return view.model_copy(update={"history_source": "MEMORY", "history_complete": True})
        spec = inspect_spec(request)
        if state.spec_digest != spec.content_digest or state.task_definition_id != request.task_definition_id:
            _reject("TASK_LOOP_SPEC_CHANGED")
        iterations = []
        for item in state.iterations:
            key = self._attempt_keys.get(item.attempt_id)
            saved = self._results.get(key) if key else None
            result = saved[1] if saved else None
            initial = spec.initial_files
            iterations.append(
                LoopIterationView(
                    iteration=item.iteration,
                    attempt_id=item.attempt_id,
                    session_id=str(item.session_id),
                    phase="FINISHED" if result else "VERIFIED",
                    status="PASSED" if item.verification.passed else "CHECKS_FAILED",
                    started_at=result.started_at if result else None,
                    completed_at=result.completed_at if result else None,
                    duration_ms=result.metrics.duration_ms if result and result.metrics else None,
                    candidate_id=item.candidate.candidate_id,
                    candidate_digest=item.candidate.content_digest,
                    parent_candidate_id=item.candidate.parent_candidate_id,
                    changed_paths=tuple(
                        sorted(
                            path
                            for path in initial.keys() | item.candidate.files.keys()
                            if initial.get(path) != item.candidate.files.get(path)
                        )
                    ),
                    checks=tuple(
                        LoopCheckView(
                            check_id=check.criterion_id, label=check.message, kind="MOCK", passed=check.passed
                        )
                        for check in item.verification.checks
                    ),
                    stop_reason=result_reason(result),
                )
            )
        return view.model_copy(
            update={
                "history_source": "MEMORY",
                "history_complete": True,
                "iterations": tuple(iterations),
                "failure_patterns": failure_patterns(tuple(iterations)),
                "current_candidate_id": state.current.candidate_id,
                "current_candidate_digest": state.current.content_digest,
                "stopped": state.stopped,
                "stop_reason": iterations[-1].stop_reason if iterations else None,
            }
        )

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        key = (request.workflow_run_id, request.task_run_id)
        async with self._locks.setdefault(key, asyncio.Lock()):
            started_at = datetime.now(timezone.utc)
            await on_state_change(TaskRunStatus.RUNNING, None)
            fingerprint = sha256_digest(request.model_dump(mode="json"))
            cached = self._results.get(request.idempotency_key)
            attempt_key = self._attempt_keys.get(request.attempt_id)
            if cached is not None and cached[0] == fingerprint:
                result = cached[1].model_copy(deep=True)
            elif cached is not None or (attempt_key is not None and attempt_key != request.idempotency_key):
                result = self._failure(request, started_at, "IDEMPOTENCY_CONFLICT")
            else:
                self._inspection_requests[key] = request.model_copy(deep=True)
                try:
                    result = await self._iterate(request, started_at)
                except (ValidationError, _LoopError) as exc:
                    code = exc.code if isinstance(exc, _LoopError) else "TASK_LOOP_INPUT_INVALID"
                    result = self._failure(request, started_at, code)
                self._results[request.idempotency_key] = (fingerprint, result.model_copy(deep=True))
                self._attempt_keys[request.attempt_id] = request.idempotency_key
            status = TaskRunStatus(result.status.value)
            await on_state_change(status, result)
            return result

    async def get_loop_request(self, service, run_id, task_id, definition_id):
        request = self._inspection_requests.get((run_id, task_id))
        return (
            request.model_copy(deep=True)
            if service == self.service_name and request and request.task_definition_id == definition_id
            else None
        )

    async def _iterate(self, request: TaskRequest, started_at: datetime) -> TaskResult:
        input_payload = request.input if isinstance(request.input, dict) else {}
        inputs = input_payload.get("namedInputs", {})
        if not isinstance(inputs, dict):
            _reject("TASK_LOOP_INPUT_INVALID")
        spec = TaskLoopSpec.model_validate(inputs.get("task_loop_spec"))
        configuration = MockTaskLoopConfiguration.model_validate((request.metadata or {}).get("resolved_configuration"))
        configured_budget = (request.constraints or {}).get("max_attempts", spec.max_iterations)
        if not isinstance(configured_budget, int) or isinstance(configured_budget, bool) or configured_budget < 1:
            _reject("TASK_LOOP_INPUT_INVALID")
        max_iterations = min(spec.max_iterations, configured_budget)
        spec_digest = spec.content_digest
        configuration_digest = sha256_digest(configuration.model_dump(mode="json"))
        key = (request.workflow_run_id, request.task_run_id)
        state = self._states.get(key)
        expected_iteration = (request.context or {}).get("task_loop_iteration")
        if expected_iteration is not None and (
            not isinstance(expected_iteration, int) or isinstance(expected_iteration, bool) or expected_iteration < 1
        ):
            _reject("TASK_LOOP_INPUT_INVALID")
        if state is None:
            if expected_iteration is not None and expected_iteration != 1:
                _reject("TASK_LOOP_STATE_UNAVAILABLE")
            state = _LoopState(
                spec_digest=spec_digest,
                configuration_digest=configuration_digest,
                task_definition_id=request.task_definition_id,
                max_iterations=max_iterations,
                current=self._candidate(request.task_run_id, 0, dict(spec.initial_files), None),
            )
            self._states[key] = state
        if state.spec_digest != spec_digest or state.task_definition_id != request.task_definition_id:
            _reject("TASK_LOOP_SPEC_CHANGED")
        if state.configuration_digest != configuration_digest or state.max_iterations != max_iterations:
            _reject("TASK_LOOP_POLICY_CHANGED")
        if state.stopped:
            _reject("TASK_LOOP_STOPPED")

        iteration = len(state.iterations) + 1
        if expected_iteration is not None and expected_iteration != iteration:
            _reject("TASK_LOOP_ITERATION_CONFLICT")
        prompt = TaskLoopPrompt(
            spec_digest=spec_digest,
            specification=spec.model_copy(deep=True),
            candidate=state.current.model_copy(deep=True),
            previous_findings=(
                tuple(check for check in state.iterations[-1].verification.checks if not check.passed)
                if state.iterations
                else ()
            ),
        )
        if len(prompt.model_dump_json()) > spec.context_budget_chars:
            state.stopped = True
            _reject("TASK_LOOP_CONTEXT_BUDGET_EXCEEDED")
        step = (
            configuration.mock_steps[iteration - 1]
            if iteration <= len(configuration.mock_steps)
            else MockTaskLoopStep()
        )
        session_id, files = await self.agent.execute(prompt.model_copy(deep=True), step.model_copy(deep=True))
        candidate = self._candidate(request.task_run_id, iteration, files, state.current.candidate_id)
        verification = verify_mock_candidate(spec, candidate)
        state.stalled_iterations = (
            state.stalled_iterations + 1 if candidate.content_digest == state.current.content_digest else 0
        )
        record = TaskLoopIteration(
            iteration=iteration,
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            session_id=session_id,
            prompt=prompt,
            candidate=candidate,
            verification=verification,
            agent_note=step.note,
        )
        state.iterations.append(record)
        state.current = candidate
        stop_code = None
        if not verification.passed:
            if iteration >= max_iterations:
                stop_code = "TASK_LOOP_BUDGET_EXHAUSTED"
            elif state.stalled_iterations >= spec.max_stalled_iterations:
                stop_code = "TASK_LOOP_STALLED"
            else:
                stop_code = "TASK_LOOP_CHECKS_FAILED"
        state.stopped = verification.passed or stop_code != "TASK_LOOP_CHECKS_FAILED"
        metadata = {
            "mock": True,
            "task_loop": {
                "spec_digest": spec_digest,
                "iteration": iteration,
                "max_iterations": max_iterations,
                "fresh_context": True,
                "session_id": str(session_id),
                "candidate_id": str(candidate.candidate_id),
                "candidate_digest": candidate.content_digest,
                "verification_mode": "MOCK",
                "verification_passed": verification.passed,
                "stop_reason": stop_code or "CHECKS_PASSED",
                "history": [item.summary() for item in state.iterations],
            },
        }
        artifact = self._artifact(request, candidate, started_at)
        if stop_code is not None:
            return self._failure(
                request,
                started_at,
                stop_code,
                retryable=stop_code == "TASK_LOOP_CHECKS_FAILED",
                artifacts=[artifact],
                metadata=metadata,
            )
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output={
                "outputs": {
                    "candidate": candidate.model_dump(mode="json"),
                    "verification_report": verification.model_dump(mode="json"),
                }
            },
            artifacts=[artifact],
            error=None,
            metrics=TaskMetrics(duration_ms=0),
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    @staticmethod
    def _candidate(
        task_run_id: UUID, iteration: int, files: dict[str, str], parent_id: UUID | None
    ) -> TaskLoopCandidate:
        digest = sha256_digest(files)
        return TaskLoopCandidate(
            candidate_id=uuid5(task_run_id, f"task-loop:{iteration}:{digest}"),
            parent_candidate_id=parent_id,
            iteration=iteration,
            files=files,
            content_digest=digest,
        )

    @staticmethod
    def _artifact(request: TaskRequest, candidate: TaskLoopCandidate, created_at: datetime) -> Artifact:
        payload = candidate.model_dump_json().encode("utf-8")
        return Artifact(
            artifact_id=candidate.candidate_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            kind="DOCUMENT",
            name=f"task-loop-candidate-{candidate.iteration}.json",
            media_type="application/json",
            uri=f"task-loop-mock://candidates/{candidate.candidate_id}",
            size_bytes=len(payload),
            checksum=Checksum(value=hashlib.sha256(payload).hexdigest()),
            producer=TASK_LOOP_MOCK_SERVICE,
            created_at=created_at,
            metadata={"mock": True, "candidate_digest": candidate.content_digest},
        )

    @staticmethod
    def _failure(
        request: TaskRequest,
        started_at: datetime,
        code: str,
        *,
        retryable: bool = False,
        artifacts: list[Artifact] | None = None,
        metadata: dict | None = None,
    ) -> TaskResult:
        completed_at = datetime.now(timezone.utc)
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=artifacts or [],
            error=ServiceError(
                error_id=uuid4(),
                code=code,
                category="EXECUTION" if code.startswith("TASK_LOOP_") else "CONFLICT",
                message=code.replace("_", " ").capitalize() + ".",
                retryable=retryable,
                service=TASK_LOOP_MOCK_SERVICE,
                occurred_at=completed_at,
            ),
            metrics=TaskMetrics(duration_ms=max(0, int((completed_at - started_at).total_seconds() * 1000))),
            started_at=started_at,
            completed_at=completed_at,
            metadata=metadata or {"mock": True},
        )

"""One live, recoverable Ralph iteration per coordinator-owned ADLC attempt."""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Self
from uuid import uuid4, uuid5

from pydantic import ValidationError

from langflow.adlc.artifact_payload_store import (
    ArtifactPayloadStoreError,
    BoundedArtifactPayloadStore,
    SourcePatchSnapshot,
)
from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
    TokenUsage,
)
from langflow.adlc.task_loop_inspection import (
    inspect_live_loop,
    live_iteration,
)
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopSpec, LiveLoopState
from langflow.adlc.task_loop_opencode import TASK_LOOP_MODEL, OpenCodeTaskLoopRuntime, opencode_loop_binding
from langflow.adlc.task_loop_runtime import LoopRuntimeError
from langflow.adlc.task_loop_runtime_models import (
    LoopCandidateReference,
    LoopIterationOutcome,
    LoopRuntimeSession,
)
from langflow.adlc.task_loop_runtime_v2 import BINDING, PROTOCOL_V2, add_cost, runtime_models
from langflow.adlc.task_loop_store import LiveLoopAttempt, TaskLoopStore
from langflow.adlc.task_loop_verifier import TaskLoopVerifier
from langflow.adlc.task_loop_workspace import LiveLoopError, TaskLoopWorkspace

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import StateChangeCallback
    from langflow.adlc.models import TaskRequest
    from langflow.adlc.opencode_client import OpenCodeClient
    from langflow.adlc.task_loop_runtime import TaskLoopRuntime

TASK_LOOP_LIVE_SERVICE = "agent-provider:task-loop-opencode"
TASK_LOOP_LIVE_ENABLED_ENV = "ADLC_TASK_LOOP_OPENCODE_ENABLED"
__all__ = [
    "TASK_LOOP_LIVE_SERVICE",
    "TASK_LOOP_MODEL",
    "LiveTaskLoopExecutor",
    "TaskLoopExecutor",
    "create_live_task_loop_executor",
    "task_loop_live_enabled",
]
_SYSTEM = (
    "Perform exactly one implementation iteration of the supplied fixed specification. "
    "This is a fresh session: do not import conversation history or compact this context. "
    "The workspace already contains the previous candidate. Edit only writable_paths; "
    "leave all verification tests and repository configuration intact. "
    "Finish this iteration after your edits. The coordinator will run independent checks "
    "and decide whether another iteration or human approval is required."
)


def task_loop_live_enabled() -> bool:
    return os.getenv(TASK_LOOP_LIVE_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def create_live_task_loop_executor(*, artifact_payloads: BoundedArtifactPayloadStore | None = None):
    from langflow.adlc.opencode_client import OpenCodeHttpClient, OpenCodeServerSettings

    if not task_loop_live_enabled():
        return None
    source = os.getenv("ADLC_TASK_LOOP_SOURCE_REPOSITORY", "").strip()
    if not source:
        from langflow.adlc.local_projects import project_source_root

        source = str(project_source_root())
    state_root = Path(
        os.getenv("ADLC_TASK_LOOP_STATE_ROOT", str(Path(__file__).resolve().parents[2] / "data/task-loop"))
    ).resolve()
    worktree_root = Path(os.getenv("ADLC_TASK_LOOP_WORKTREE_ROOT", str(state_root / "worktrees"))).resolve()
    try:
        return LiveTaskLoopExecutor(
            workspace=TaskLoopWorkspace(Path(source), worktree_root),
            store=TaskLoopStore(state_root / "task-loop.sqlite3"),
            client=OpenCodeHttpClient(OpenCodeServerSettings.from_environment()),
            artifact_payloads=artifact_payloads,
            agent=OpenCodeServerSettings.from_environment().agent,
        )
    except (ValueError, LiveLoopError):
        return None


class TaskLoopExecutor:
    service_name = "agent-provider:task-loop"
    capabilities = (
        "task-loop:live",
        "task-loop:fresh-session",
        "task-loop:command-verification",
        "task-loop:durable-recovery",
    )

    def __init__(
        self,
        *,
        workspace: TaskLoopWorkspace,
        store: TaskLoopStore,
        client: OpenCodeClient | None = None,
        runtime: TaskLoopRuntime | None = None,
        artifact_payloads: BoundedArtifactPayloadStore | None = None,
        verifier: TaskLoopVerifier | None = None,
        agent: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.store = store
        if (client is None) == (runtime is None):
            msg = "Supply exactly one runtime adapter or legacy OpenCode client"
            raise ValueError(msg)
        self.client = client  # Compatibility for existing integrations; the kernel never calls this client.
        self.runtime = runtime if runtime is not None else OpenCodeTaskLoopRuntime(client, agent=agent)
        self.runtime_binding = BINDING.validate_python(self.runtime.binding.model_dump())
        self.verifier = verifier or TaskLoopVerifier(workspace)
        self.artifact_payloads = artifact_payloads or BoundedArtifactPayloadStore(database_path=store.path)
        self.agent = self.runtime_binding.agent

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        executor = self._project_executor(request)
        return await executor._dispatch(request, on_state_change, recovery=False)  # noqa: SLF001 - same class replica

    async def resume(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        executor = self._project_executor(request)
        return await executor._dispatch(request, on_state_change, recovery=True)  # noqa: SLF001 - same class replica

    def _project_executor(self, request: TaskRequest) -> Self:
        from copy import copy

        from langflow.adlc.local_projects import snapshot_path

        reference = (request.context or {}).get("adlc_local_project")
        if reference is None:
            return self
        replica = copy(self)
        replica.workspace = TaskLoopWorkspace(snapshot_path(reference), self.workspace.root)
        replica.verifier = TaskLoopVerifier(replica.workspace)
        return replica

    async def get_saved_result(self, request: TaskRequest) -> TaskResult | None:
        attempt = self.store.attempt(request)
        return attempt.result.model_copy(deep=True) if attempt and attempt.result else None

    async def inspect_loop(self, request: TaskRequest):
        return inspect_live_loop(self.store, request)

    async def inspect_loop_runtime(self, request: TaskRequest):
        from langflow.adlc.task_loop_runtime_inspection import inspect_runtime

        return inspect_runtime(self.store, request)

    async def get_loop_request(self, service, run_id, task_id, definition_id):
        request = self.store.latest_request(run_id, task_id, definition_id)
        return request if request and request.executor.service == service else None

    async def get_loop_artifact(self, request: TaskRequest, artifact_id):
        return self.store.artifact(request, artifact_id)

    async def _dispatch(
        self, request: TaskRequest, on_state_change: StateChangeCallback, *, recovery: bool
    ) -> TaskResult:
        started_at = datetime.now(timezone.utc)
        lease = self.store.lease(request)
        await on_state_change(TaskRunStatus.RUNNING, None)
        try:
            while not lease.acquire():  # noqa: ASYNC110 - a kernel lock can be released by another process.
                # The owning process may still be alive. Never abort it or dispatch twice.
                await asyncio.sleep(0.05)
            attempt = self.store.attempt(request)
            if attempt is not None and attempt.result is not None:
                # Artifact expiry cannot change an already committed result or create a new attempt.
                if all(
                    artifact.expires_at is None or artifact.expires_at > started_at for artifact in attempt.artifacts
                ):
                    self._retain(attempt)
                result = attempt.result.model_copy(deep=True)
            elif attempt is None and recovery:
                result = self._failure(request, started_at, "ADLC_RECOVERY_TASK_LOOP_MISSING")
            else:
                result = await self._run(request, attempt, started_at)
        except (ValidationError, LiveLoopError, ArtifactPayloadStoreError) as exc:
            code = exc.code if hasattr(exc, "code") else "TASK_LOOP_INPUT_INVALID"
            result = self._failure(request, started_at, code)
        except (OSError, sqlite3.Error):
            # No filesystem paths, subprocess output, or credentials enter an error response.
            result = self._failure(request, started_at, "TASK_LOOP_STORAGE_UNAVAILABLE")
        finally:
            lease.release()
        await on_state_change(TaskRunStatus(result.status.value), result)
        return result

    def _parse(self, request: TaskRequest) -> tuple[LiveLoopSpec, int, str]:
        payload = request.input if isinstance(request.input, dict) else {}
        named_inputs = payload.get("namedInputs", {})
        if not isinstance(named_inputs, dict):
            code = "TASK_LOOP_INPUT_INVALID"
            raise LiveLoopError(code)
        spec = LiveLoopSpec.model_validate(named_inputs.get("task_loop_spec"))
        reference = (request.context or {}).get("adlc_local_project")
        if reference is not None and spec.base_commit != reference.get("base_commit"):
            code = "TASK_LOOP_PROJECT_COMMIT_MISMATCH"
            raise LiveLoopError(code)
        configured = (request.constraints or {}).get("max_attempts", spec.max_iterations)
        if not isinstance(configured, int) or isinstance(configured, bool) or configured < 1:
            code = "TASK_LOOP_INPUT_INVALID"
            raise LiveLoopError(code)
        configuration = request.metadata.get("resolved_configuration", {})
        if configuration:
            from langflow.adlc.coding_agent import is_unified_coding_agent

            trace = request.metadata.get("plan_traceability", {})
            keys = {"approved_contract_ref", "task_loop_enabled", "submission_mode"}
            if trace.get("package_version") == "0.3.0":
                keys.add("loop_runtime")
            if not (
                isinstance(configuration, dict)
                and isinstance(trace, dict)
                and is_unified_coding_agent(trace.get("package_id"), trace.get("package_version"))
                and request.executor.operation == "coding-task-loop"
                and configuration.get("task_loop_enabled") is True
                and configuration.get("approved_contract_ref") is None
                and configuration.get("submission_mode") == "MANUAL"
                and set(configuration) == keys
                and (
                    "loop_runtime" not in configuration or configuration["loop_runtime"] == self.runtime_binding.family
                )
            ):
                code = "TASK_LOOP_CONFIGURATION_INVALID"
                raise LiveLoopError(code)
        policy_digest = sha256_digest(
            {
                "constraints": request.constraints or {},
                "model": f"{self.runtime_binding.provider_id}/{self.runtime_binding.model_id}",
                "agent": self.agent,
                "source": str(self.workspace.source),
                "workspace_root": str(self.workspace.root),
                **(
                    {"configuration": configuration, "requirement": named_inputs.get("requirement")}
                    if configuration
                    else {}
                ),
            }
        )
        return spec, min(spec.max_iterations, configured), policy_digest

    async def _run(self, request: TaskRequest, attempt: LiveLoopAttempt | None, started_at: datetime) -> TaskResult:
        if self.runtime.binding != self.runtime_binding:
            msg = "TASK_LOOP_RUNTIME_CHANGED"
            raise LiveLoopError(msg)
        if self._iteration_mode() not in self.runtime_binding.modes:
            msg = "TASK_LOOP_RUNTIME_CAPABILITY_UNSUPPORTED"
            raise LiveLoopError(msg)
        spec, maximum, policy_digest = self._parse(request)
        state = self.store.state(request)
        if state is None:
            digest = LiveLoopCandidate.digest(spec.base_commit, {})
            initial = LiveLoopCandidate(
                candidate_id=uuid5(request.task_run_id, f"live-loop:0:{digest}"),
                parent_candidate_id=None,
                iteration=0,
                base_commit=spec.base_commit,
                changes={},
                content_digest=digest,
            )
            state = LiveLoopState(
                spec_digest=spec.content_digest,
                policy_digest=policy_digest,
                task_definition_id=request.task_definition_id,
                max_iterations=maximum,
                current=initial,
                started_at=started_at,
                runtime_binding=self.runtime_binding.model_dump(mode="json"),
                total_cost=None if getattr(self.runtime_binding, "cost_reporting", None) == "UNAVAILABLE" else 0.0,
            )
        if state.runtime_binding is not None:
            if BINDING.validate_python(state.runtime_binding) != self.runtime_binding:
                msg = "TASK_LOOP_RUNTIME_CHANGED"
                raise LiveLoopError(msg)
        elif self.runtime_binding != opencode_loop_binding(self.agent):
            # Old checkpoints predate this protocol; only their original adapter can recover them.
            msg = "TASK_LOOP_LEGACY_RUNTIME_INCOMPATIBLE"
            raise LiveLoopError(msg)
        if state.spec_digest != spec.content_digest or state.task_definition_id != request.task_definition_id:
            code = "TASK_LOOP_SPEC_CHANGED"
            raise LiveLoopError(code)
        if state.policy_digest != policy_digest or state.max_iterations != maximum:
            code = "TASK_LOOP_POLICY_CHANGED"
            raise LiveLoopError(code)
        expected = (request.context or {}).get("task_loop_iteration", state.next_iteration)
        if not isinstance(expected, int) or isinstance(expected, bool) or expected != state.next_iteration:
            code = "TASK_LOOP_ITERATION_CONFLICT"
            raise LiveLoopError(code)
        if state.stopped or state.next_iteration > maximum:
            code = "TASK_LOOP_STOPPED"
            raise LiveLoopError(code)
        if attempt is None:
            if spec.max_total_tokens is not None and state.total_tokens >= spec.max_total_tokens:
                code = "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"
                raise LiveLoopError(code)
            if spec.max_total_cost is not None and (
                state.total_cost is None or state.total_cost >= spec.max_total_cost
            ):
                code = "TASK_LOOP_COST_BUDGET_EXHAUSTED"
                raise LiveLoopError(code)
            await self.workspace.validate_spec(spec)
            # Pin the original adapter for future attempts; old attempts/results are not rewritten.
            if state.runtime_binding is None:
                state = state.model_copy(update={"runtime_binding": self.runtime_binding.model_dump(mode="json")})
            attempt = self.store.reserve(request, state, started_at)
            fresh = True
        else:
            fresh = False
            self._validate_runtime_checkpoint(request, spec, state, attempt)
        try:
            if attempt.phase == "VERIFIED":
                return self._complete(request, spec, state, attempt)
            remaining = spec.max_duration_ms - int(
                (datetime.now(timezone.utc) - state.started_at).total_seconds() * 1000
            )
            if remaining <= 0:
                code = "TASK_LOOP_TIME_BUDGET_EXHAUSTED"
                raise LiveLoopError(code)
            timeout_ms = min(remaining, self._timeout(request))
            async with asyncio.timeout(timeout_ms / 1000):
                if fresh:
                    attempt = await self._agent_iteration(request, spec, state, attempt, timeout_ms)
                elif attempt.phase in {"RESERVED", "AGENT_RUNNING"}:
                    code = "ADLC_RECOVERY_TASK_LOOP_INTERRUPTED"
                    raise LiveLoopError(code)
                else:
                    await self._dispose(attempt, abort=True)
                    await self.workspace.remove(request.attempt_id, "verify")
                if attempt.candidate is None:
                    code = "TASK_LOOP_CHECKPOINT_CORRUPT"
                    raise LiveLoopError(code)
                if attempt.verification is None:
                    verification = await self.verifier.verify(request.attempt_id, spec, attempt.candidate)
                    additional_evidence = await self._verify_additional(request, spec, attempt.candidate)
                    attempt = attempt.model_copy(
                        update={
                            "phase": "VERIFIED",
                            "verification": verification,
                            "additional_evidence": additional_evidence,
                        }
                    )
                    self.store.checkpoint(attempt)
                return self._complete(request, spec, state, attempt)
        except asyncio.CancelledError:
            attempt = self.store.attempt(request) or attempt
            result = self._failure(
                request, attempt.started_at, "TASK_LOOP_CANCELLED", status=TaskResultStatus.CANCELLED
            )
            self.store.finish(attempt, self._advance_failure(state, attempt, stopped=False), result)
            raise
        except (
            LiveLoopError,
            LoopRuntimeError,
            TimeoutError,
            ArtifactPayloadStoreError,
            OSError,
            ValueError,
        ) as exc:
            code = (
                exc.code
                if hasattr(exc, "code")
                else "TASK_LOOP_DEADLINE_EXCEEDED"
                if isinstance(exc, TimeoutError)
                else "TASK_LOOP_EXECUTION_INVALID"
            )
            # Reload the latest checkpoint: an interrupted verifier must not lose a captured candidate.
            attempt = self.store.attempt(request) or attempt
            result = self._failure(
                request,
                attempt.started_at,
                code,
                artifacts=list(attempt.artifacts),
                metadata={
                    "task_loop": {
                        "iteration": attempt.iteration,
                        "session_id": attempt.session_id,
                        "candidate_digest": attempt.candidate.content_digest
                        if attempt.candidate
                        else state.current.content_digest,
                        "stop_reason": code,
                        "restart_recovery": not fresh,
                    },
                },
            )
            self._retain(attempt)
            unknown_unpriced_call = (
                self.runtime_binding.protocol_ref == PROTOCOL_V2
                and attempt.session_id is not None
                and attempt.candidate is None
                and (attempt.runtime_checkpoint is None or attempt.runtime_checkpoint.usage is None)
            )
            stopped = unknown_unpriced_call or not (
                code.startswith("ADLC_RECOVERY_")
                or isinstance(exc, TimeoutError)
                or (isinstance(exc, LoopRuntimeError) and exc.retryable)
            )
            self.store.finish(attempt, self._advance_failure(state, attempt, stopped=stopped), result)
            return result
        finally:
            # A persisted snapshot owns the bytes; no workspace name is used as a recovery heuristic.
            current = self.store.attempt(request) or attempt
            await self._dispose(current, abort=True)
            await self.workspace.remove(request.attempt_id, "agent")
            await self.workspace.remove(request.attempt_id, "verify")

    async def _agent_iteration(
        self, request: TaskRequest, spec: LiveLoopSpec, state: LiveLoopState, attempt: LiveLoopAttempt, timeout_ms: int
    ) -> LiveLoopAttempt:
        prompt = {
            "spec_digest": spec.content_digest,
            "specification": spec.model_dump(mode="json"),
            "candidate": state.current.model_dump(mode="json"),
            "previous_findings": [
                {
                    "check_id": check.check_id,
                    "exit_code": check.exit_code,
                    "timed_out": check.timed_out,
                    "executed_tests": check.executed_tests,
                    "stderr": check.stderr[-2048:],
                }
                for check in state.previous_findings
                if not check.passed
            ],
        }
        import json

        if request.executor.operation == "coding-task-loop":
            prompt["requirement"] = request.input.get("namedInputs", {}).get("requirement")

        text = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        if len(text) + len(_SYSTEM) > spec.context_budget_chars:
            code = "TASK_LOOP_CONTEXT_BUDGET_EXCEEDED"
            raise LiveLoopError(code)
        directory = await self.workspace.create(request.attempt_id, "agent", state.current)
        # Verify exact checkout bytes before spending model tokens or exposing the workspace.
        await self.workspace.validate_checkout(spec, state.current, directory)
        attempt, _ = await self._invoke_runtime(
            request,
            spec,
            state,
            attempt,
            timeout_ms,
            directory=directory,
            prompt=text,
            system=_SYSTEM,
            mode="WORKSPACE_EDIT",
        )
        await self._dispose(attempt, abort=False)
        candidate = await self.workspace.capture(request.task_run_id, attempt.iteration, spec, state.current, directory)
        artifact, payload = await self._patch_artifact(request, candidate, attempt.started_at)
        attempt = attempt.model_copy(
            update={
                "phase": "CANDIDATE_CAPTURED",
                "candidate": candidate,
                "artifacts": (artifact,),
                "payloads": {str(artifact.artifact_id): payload.decode("utf-8")},
            }
        )
        self.store.checkpoint(attempt)
        self._retain(attempt)
        return attempt

    async def _invoke_runtime(
        self, request, spec, state, attempt, timeout_ms, *, directory, prompt, system, mode
    ) -> tuple[LiveLoopAttempt, LoopIterationOutcome]:
        request_model, session_model, outcome_model, checkpoint_model, usage_model = runtime_models(
            self.runtime_binding
        )
        command = request_model(
            runtime=self.runtime_binding,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            iteration=attempt.iteration,
            policy_digest=state.policy_digest,
            specification=spec,
            parent_candidate=state.current,
            mode=mode,
            prompt=prompt,
            system=system,
            timeout_ms=timeout_ms,
        )
        header = checkpoint_model(
            runtime=self.runtime_binding,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            iteration=attempt.iteration,
            request_digest=command.content_digest,
            spec_digest=spec.content_digest,
            policy_digest=state.policy_digest,
            parent_candidate=LoopCandidateReference.of(state.current),
            mode=mode,
            phase="AGENT_RUNNING",
        )
        attempt = attempt.model_copy(update={"phase": "AGENT_RUNNING", "runtime_checkpoint": header})
        self.store.checkpoint(attempt)  # Durable intent before allocating any runtime session.
        session = session_model.model_validate(
            (await self.runtime.open_iteration(command, directory=directory)).model_dump()
        )
        if session.runtime != self.runtime_binding or session.request_digest != command.content_digest:
            msg = "TASK_LOOP_RUNTIME_SESSION_MISMATCH"
            raise LiveLoopError(msg)
        attempt = attempt.model_copy(
            update={
                "session_id": session.session_id,
                "runtime_checkpoint": header.model_copy(update={"session": session}),
            }
        )
        self.store.checkpoint(attempt)
        if not session.fresh_context:
            msg = "TASK_LOOP_SESSION_NOT_FRESH"
            raise LiveLoopError(msg)
        if mode == "FILE_PROPOSAL" and not session.tools_disabled:
            msg = "TASK_LOOP_RUNTIME_RESTRICTIONS_UNAVAILABLE"
            raise LiveLoopError(msg)
        try:
            returned = await self.runtime.run_iteration(command, session, directory=directory)
        except LoopRuntimeError as exc:
            if exc.usage is not None:
                usage = usage_model.model_validate(exc.usage.model_dump())
                self.store.checkpoint(
                    attempt.model_copy(
                        update={
                            **usage.model_dump(),
                            "runtime_checkpoint": attempt.runtime_checkpoint.model_copy(update={"usage": usage}),
                        }
                    )
                )
            raise
        outcome = outcome_model.model_validate(returned.model_dump())
        if (
            outcome.runtime != self.runtime_binding
            or outcome.request_digest != command.content_digest
            or outcome.session_id != session.session_id
            or outcome.mode != mode
        ):
            msg = "TASK_LOOP_RUNTIME_OUTCOME_MISMATCH"
            raise LiveLoopError(msg)
        if spec.max_total_tokens is not None and outcome.usage.total_tokens <= 0:
            msg = "TASK_LOOP_USAGE_UNAVAILABLE"
            raise LiveLoopError(msg)
        attempt = attempt.model_copy(
            update={
                **outcome.usage.model_dump(),
                "runtime_checkpoint": attempt.runtime_checkpoint.model_copy(
                    update={
                        "usage": outcome.usage,
                        "outcome_digest": sha256_digest(outcome.model_dump(mode="json")),
                    }
                ),
            }
        )
        self.store.checkpoint(attempt)
        return attempt, outcome

    def _validate_runtime_checkpoint(self, request, spec, state, attempt) -> None:
        header = attempt.runtime_checkpoint
        if header is None:
            if state.runtime_binding is not None and attempt.phase != "RESERVED":
                msg = "TASK_LOOP_CHECKPOINT_CORRUPT"
                raise LiveLoopError(msg)
            return  # Pre-protocol checkpoints remain recoverable only by their original adapter.
        proof_digest = (
            sha256_digest(
                {
                    "behavioral": attempt.verification.model_dump(mode="json"),
                    "additional": attempt.additional_evidence,
                }
            )
            if attempt.verification
            else None
        )
        if (
            header.runtime != self.runtime_binding
            or header.workflow_run_id != request.workflow_run_id
            or header.task_run_id != request.task_run_id
            or header.request_id != request.request_id
            or header.attempt_id != request.attempt_id
            or header.iteration != attempt.iteration
            or header.spec_digest != spec.content_digest
            or header.policy_digest != state.policy_digest
            or header.parent_candidate != LoopCandidateReference.of(state.current)
            or header.phase != attempt.phase
            or (header.session.session_id if header.session else None) != attempt.session_id
            or header.candidate != (LoopCandidateReference.of(attempt.candidate) if attempt.candidate else None)
            or header.verification_digest != proof_digest
            or (
                header.usage
                and header.usage.model_dump()
                != {
                    "input_tokens": attempt.input_tokens,
                    "output_tokens": attempt.output_tokens,
                    "total_tokens": attempt.total_tokens,
                    "cost": attempt.cost,
                }
            )
            or (
                attempt.candidate
                and (
                    header.session is None
                    or not header.session.fresh_context
                    or (header.mode == "FILE_PROPOSAL" and not header.session.tools_disabled)
                )
            )
        ):
            msg = "TASK_LOOP_CHECKPOINT_CORRUPT"
            raise LiveLoopError(msg)

    def _complete(
        self, request: TaskRequest, spec: LiveLoopSpec, state: LiveLoopState, attempt: LiveLoopAttempt
    ) -> TaskResult:
        candidate, verification = attempt.candidate, attempt.verification
        if (
            candidate is None
            or verification is None
            or verification.candidate_id != candidate.candidate_id
            or verification.candidate_digest != candidate.content_digest
            or verification.spec_digest != spec.content_digest
            or {check.check_id for check in verification.checks}
            != {check.check_id for check in spec.verification_commands}
            or candidate.base_commit != spec.base_commit
            or candidate.parent_candidate_id != state.current.candidate_id
            or candidate.iteration != attempt.iteration
            or set(candidate.changes) - set(spec.writable_paths)
        ):
            code = "TASK_LOOP_VERIFICATION_MISMATCH"
            raise LiveLoopError(code)
        stalled = state.stalled_iterations + 1 if candidate.content_digest == state.current.content_digest else 0
        additional_passed = self._additional_checks_passed(request, spec, attempt)
        passed = verification.passed and additional_passed
        total_tokens = state.total_tokens + attempt.total_tokens
        total_cost = add_cost(state.total_cost, attempt.cost)
        reason = None
        if (
            passed is False
            and int((datetime.now(timezone.utc) - state.started_at).total_seconds() * 1000) >= spec.max_duration_ms
        ):
            reason = "TASK_LOOP_TIME_BUDGET_EXHAUSTED"
        elif (spec.max_total_tokens is not None and total_tokens >= spec.max_total_tokens and not passed) or (
            spec.max_total_tokens is not None and total_tokens > spec.max_total_tokens
        ):
            reason = "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"
        elif (
            spec.max_total_cost is not None and (total_cost is None or total_cost >= spec.max_total_cost) and not passed
        ) or (spec.max_total_cost is not None and (total_cost is None or total_cost > spec.max_total_cost)):
            reason = "TASK_LOOP_COST_BUDGET_EXHAUSTED"
        elif not passed:
            reason = (
                "TASK_LOOP_BUDGET_EXHAUSTED"
                if attempt.iteration >= state.max_iterations
                else "TASK_LOOP_STALLED"
                if stalled >= spec.max_stalled_iterations
                else "TASK_LOOP_CHECKS_FAILED"
            )
        summary = {
            "iteration": attempt.iteration,
            "request_id": str(request.request_id),
            "attempt_id": str(request.attempt_id),
            "session_id": attempt.session_id,
            "candidate_id": str(candidate.candidate_id),
            "candidate_digest": candidate.content_digest,
            "parent_candidate_id": str(candidate.parent_candidate_id),
            "verification_passed": passed,
            **self._additional_summary(attempt),
            "check_results": [
                {
                    "check_id": check.check_id,
                    "passed": check.passed,
                    "exit_code": check.exit_code,
                    "executed_tests": check.executed_tests,
                }
                for check in verification.checks
            ],
        }
        next_state = state.model_copy(
            update={
                "current": candidate,
                "next_iteration": attempt.iteration + 1,
                "stalled_iterations": stalled,
                "stopped": reason != "TASK_LOOP_CHECKS_FAILED",
                "previous_findings": verification.checks,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "history": (*state.history, summary),
            }
        )
        metadata = {
            "task_loop": {
                "spec_digest": spec.content_digest,
                "iteration": attempt.iteration,
                "max_iterations": state.max_iterations,
                "fresh_context": True,
                "session_id": attempt.session_id,
                "candidate_id": str(candidate.candidate_id),
                "candidate_digest": candidate.content_digest,
                "verification_mode": "COMMAND",
                "verification_passed": passed,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "stop_reason": reason or "CHECKS_PASSED",
                "runtime": self.runtime_binding.model_dump(mode="json"),
                "runtime_protocol": self.runtime_binding.protocol_ref if attempt.runtime_checkpoint else None,
                "execution_unified_with_harness": False,
                "history": list(next_state.history),
            }
        }
        if reason:
            result = self._failure(
                request,
                attempt.started_at,
                reason,
                retryable=reason == "TASK_LOOP_CHECKS_FAILED",
                artifacts=list(attempt.artifacts),
                metadata=metadata,
            )
        else:
            result = TaskResult(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
                status=TaskResultStatus.SUCCEEDED,
                output={
                    "outputs": {
                        "candidate": candidate.model_dump(mode="json"),
                        "verification_report": verification.model_dump(mode="json"),
                        **(
                            {"source_patch": attempt.artifacts[0].uri}
                            if request.executor.operation == "coding-task-loop"
                            else {}
                        ),
                        **self._additional_outputs(attempt),
                    }
                },
                artifacts=list(attempt.artifacts),
                error=None,
                started_at=attempt.started_at,
                completed_at=datetime.now(timezone.utc),
                metadata=metadata,
            )
        result.metrics = TaskMetrics(
            duration_ms=int((result.completed_at - attempt.started_at).total_seconds() * 1000),
            token_usage=TokenUsage(
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                total_tokens=attempt.total_tokens,
            ),
            custom={"cost": attempt.cost},
        )
        inspection = live_iteration(
            attempt.model_copy(update={"phase": "FINISHED", "result": result}), spec
        ).model_dump(mode="json")
        # The ledger owns full history. Keep only this iteration in the result fallback,
        # rather than repeating every rich operator record in every completed attempt.
        result.metadata["task_loop"]["operator_history"] = [inspection]
        self._retain(attempt)
        self.store.finish(attempt, next_state, result)
        return result

    async def _verify_additional(
        self, _request: TaskRequest, _spec: LiveLoopSpec, _candidate: LiveLoopCandidate
    ) -> dict:
        return {}

    def _additional_checks_passed(self, _request: TaskRequest, _spec: LiveLoopSpec, _attempt: LiveLoopAttempt) -> bool:
        return True

    def _additional_outputs(self, _attempt: LiveLoopAttempt) -> dict:
        return {}

    def _additional_summary(self, _attempt: LiveLoopAttempt) -> dict:
        return {}

    async def _patch_artifact(
        self, request: TaskRequest, candidate: LiveLoopCandidate, started_at: datetime
    ) -> tuple[Artifact, bytes]:
        files = []
        for path, item in sorted(candidate.changes.items()):
            base = await self.workspace.baseline(candidate.base_commit, path)
            before, after = base.content if base else "", item.content if item else ""
            patch = f"diff --git a/{path} b/{path}\n"
            if base is None and item:
                patch += f"new file mode {item.mode}\n"
            elif item is None and base:
                patch += f"deleted file mode {base.mode}\n"
            elif base and item and base.mode != item.mode:
                patch += f"old mode {base.mode}\nnew mode {item.mode}\n"
            patch += "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile=f"a/{path}" if base else "/dev/null",
                    tofile=f"b/{path}" if item else "/dev/null",
                )
            )
            files.append(
                {
                    "file": path,
                    "patch": patch,
                    "additions": sum(
                        line.startswith("+") and not line.startswith("+++") for line in patch.splitlines()
                    ),
                    "deletions": sum(
                        line.startswith("-") and not line.startswith("---") for line in patch.splitlines()
                    ),
                    "status": "deleted" if item is None else "added" if base is None else "modified",
                }
            )
        snapshot = SourcePatchSnapshot(
            format="opencode-vcs-diff-v1",
            files=files,
            reported_files=sorted(candidate.changes),
            base_commit=candidate.base_commit,
        )
        payload = snapshot.model_dump_json().encode("utf-8")
        identity = uuid5(request.attempt_id, "task-loop-source-patch")
        artifact = Artifact(
            artifact_id=identity,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            kind="SOURCE_PATCH",
            name=f"task-loop-candidate-{candidate.iteration}.json",
            media_type="application/vnd.opencode.vcs-diff+json",
            uri=f"adlc://runs/{request.workflow_run_id}/artifacts/{identity}",
            size_bytes=len(payload),
            checksum=Checksum(value=hashlib.sha256(payload).hexdigest()),
            producer=self.service_name,
            created_at=started_at,
            expires_at=self.artifact_payloads.expires_at(started_at),
            metadata={
                "capture": "task-loop-candidate",
                "candidate_id": str(candidate.candidate_id),
                "candidate_digest": candidate.content_digest,
                "iteration": candidate.iteration,
                "payload_retained": True,
            },
        )
        return artifact, payload

    def _retain(self, attempt: LiveLoopAttempt) -> None:
        for artifact in attempt.artifacts:
            self.artifact_payloads.retain(artifact, attempt.payloads[str(artifact.artifact_id)].encode("utf-8"))

    async def _dispose(self, attempt: LiveLoopAttempt, *, abort: bool) -> None:
        if attempt.session_id is None:
            return
        mode = attempt.runtime_checkpoint.mode if attempt.runtime_checkpoint else self._iteration_mode()
        directory = self.workspace.path(attempt.attempt_id, "session" if mode == "FILE_PROPOSAL" else "agent")
        session = (
            attempt.runtime_checkpoint.session
            if attempt.runtime_checkpoint
            else LoopRuntimeSession(
                runtime=self.runtime_binding,
                request_digest=attempt.request_digest,
                session_id=attempt.session_id,
                fresh_context=False,
                tools_disabled=False,
            )
        )
        if session is None or session.runtime != self.runtime_binding:
            return
        with contextlib.suppress(LoopRuntimeError):
            await self.runtime.close_iteration(session, directory=directory, abort=abort)

    def _iteration_mode(self) -> str:
        return "WORKSPACE_EDIT"

    @staticmethod
    def _advance_failure(state: LiveLoopState, attempt: LiveLoopAttempt, *, stopped: bool) -> LiveLoopState:
        return state.model_copy(
            update={
                "next_iteration": attempt.iteration + 1,
                "current": attempt.candidate or state.current,
                "stopped": stopped,
                "total_tokens": state.total_tokens + attempt.total_tokens,
                "total_cost": add_cost(state.total_cost, attempt.cost),
            }
        )

    @staticmethod
    def _timeout(request: TaskRequest) -> int:
        value = (request.constraints or {}).get("timeout_ms", 120_000)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            code = "TASK_LOOP_INPUT_INVALID"
            raise LiveLoopError(code)
        return value

    @staticmethod
    def _failure(
        request: TaskRequest,
        started_at: datetime,
        code: str,
        *,
        retryable: bool = False,
        status: TaskResultStatus = TaskResultStatus.FAILED,
        artifacts: list[Artifact] | None = None,
        metadata: dict | None = None,
    ) -> TaskResult:
        now = datetime.now(timezone.utc)
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=status,
            output=None,
            artifacts=artifacts or [],
            error=ServiceError(
                error_id=uuid4(),
                code=code,
                category="CANCELLED" if status is TaskResultStatus.CANCELLED else "EXECUTION",
                message=code.replace("_", " ").capitalize() + ".",
                retryable=retryable,
                service=request.executor.service,
                occurred_at=now,
            ),
            started_at=started_at,
            completed_at=now,
            metadata=metadata or {},
            metrics=TaskMetrics(duration_ms=max(0, int((now - started_at).total_seconds() * 1000))),
        )


class LiveTaskLoopExecutor(TaskLoopExecutor):
    """Compatibility entry point for the published OpenCode service; no separate loop implementation."""

    service_name = TASK_LOOP_LIVE_SERVICE

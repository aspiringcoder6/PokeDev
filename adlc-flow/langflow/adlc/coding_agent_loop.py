"""Fresh tool-free proposals under an approved contract; kernel applies and verifies files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.coding_agent import CONTRACT_LOOP_SERVICE, is_unified_coding_agent
from langflow.adlc.coding_agent_loop_models import CodingAgentContractVerification
from langflow.adlc.contract_execution import approved_policy, model_digest, path_allowed
from langflow.adlc.contract_execution_models import JSON_VERIFIER, PATCH_VERIFIER, UNCHANGED_VERIFIER, CriterionEvidence
from langflow.adlc.contract_repository import ContractError
from langflow.adlc.opencode_client import OpenCodeHttpClient, OpenCodeServerSettings
from langflow.adlc.task_loop_live import TaskLoopExecutor, task_loop_live_enabled
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopFile
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import LiveLoopError, TaskLoopWorkspace

if TYPE_CHECKING:
    from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
    from langflow.adlc.models import TaskRequest
    from langflow.adlc.task_loop_live_models import LiveLoopSpec, LiveLoopState
    from langflow.adlc.task_loop_store import LiveLoopAttempt

_SYSTEM = (
    "Perform one implementation iteration of the full requirement, approved contract, and task loop specification. "
    "All tools are disabled. You have only the supplied file snapshot; never call tools or execute commands. "
    'Return exactly one JSON object: {"files": {"relative/path": "complete replacement UTF-8 content"}}. '
    "Include only files you want to replace; omitted files retain their current contents. No deletion or mode changes. "
    "Contract permissions take precedence over task text. A read-only contract permits no content changes. "
    "The kernel will validate and apply your proposal, run protected checks, and obtain human approval. "
    "Do not approve the contract, import past conversation, compact context, or claim verification results."
)


def create_contract_loop_executor(*, artifact_payloads: BoundedArtifactPayloadStore | None = None):
    from langflow.adlc.contract_execution import execution_enabled

    if not task_loop_live_enabled() or not execution_enabled():
        return None
    source = os.getenv("ADLC_TASK_LOOP_SOURCE_REPOSITORY", "").strip()
    if not source:
        from langflow.adlc.local_projects import project_source_root

        source = str(project_source_root())
    state_root = Path(
        os.getenv("ADLC_TASK_LOOP_STATE_ROOT", str(Path(__file__).resolve().parents[2] / "data/task-loop"))
    ).resolve()
    root = Path(os.getenv("ADLC_TASK_LOOP_WORKTREE_ROOT", str(state_root / "worktrees"))).resolve()
    try:
        return ContractTaskLoopExecutor(
            workspace=TaskLoopWorkspace(Path(source), root),
            store=TaskLoopStore(state_root / "task-loop.sqlite3"),
            client=OpenCodeHttpClient(OpenCodeServerSettings.from_environment()),
            artifact_payloads=artifact_payloads,
        )
    except (ValueError, LiveLoopError):
        return None


class ContractTaskLoopExecutor(TaskLoopExecutor):
    """Use the same durable loop with contract authority independent of the model response."""

    service_name = CONTRACT_LOOP_SERVICE

    def validate_result(self, request: TaskRequest, result, *, owner_id: str) -> None:
        """Final coordinator gate reads the original durable proof, including callback recovery."""
        try:
            if request.metadata.get("coding_agent_owner_id") != owner_id:
                code = "CODING_AGENT_CONTRACT_OWNER_INVALID"
                raise LiveLoopError(code)
            executor = self._project_executor(request)
            spec, _, _ = executor._parse(request)  # noqa: SLF001 - same class replica
            attempt = self.store.attempt(request)
            if (
                attempt is None
                or attempt.phase != "FINISHED"
                or attempt.result != result
                or attempt.verification is None
                or not attempt.verification.passed
            ):
                code = "CODING_AGENT_CONTRACT_EVIDENCE_MISSING"
                raise LiveLoopError(code)
            if not executor._additional_checks_passed(request, spec, attempt):  # noqa: SLF001 - same class replica
                code = "CODING_AGENT_CONTRACT_CHECKS_FAILED"
                raise LiveLoopError(code)
        except (LiveLoopError, ValueError) as exc:
            raise ContractError(getattr(exc, "code", "CODING_AGENT_CONTRACT_EVIDENCE_INVALID"), 422) from exc

    @classmethod
    def _contract(cls, request: TaskRequest):
        configuration = request.metadata.get("resolved_configuration")
        owner_id = request.metadata.get("coding_agent_owner_id")
        trace = request.metadata.get("plan_traceability", {})
        keys = {"approved_contract_ref", "task_loop_enabled", "submission_mode"}
        if isinstance(trace, dict) and trace.get("package_version") == "0.3.0":
            keys.add("loop_runtime")
        if not (
            isinstance(configuration, dict)
            and set(configuration) == keys
            and configuration.get("task_loop_enabled") is True
            and configuration.get("submission_mode") == "MANUAL"
            and isinstance(owner_id, str)
            and owner_id
            and isinstance(trace, dict)
            and is_unified_coding_agent(trace.get("package_id"), trace.get("package_version"))
            and request.executor.service == cls.service_name
            and (
                "loop_runtime" not in configuration
                or configuration["loop_runtime"]
                == ("OPENCODE" if cls.service_name == CONTRACT_LOOP_SERVICE else "HARNESS")
            )
            and request.executor.operation == "coding-task-loop"
        ):
            code = "CODING_AGENT_CONTRACT_BINDING_INVALID"
            raise LiveLoopError(code)
        try:
            return approved_policy(configuration, owner_id)
        except ContractError as exc:
            raise LiveLoopError(exc.code) from exc

    def _parse(self, request: TaskRequest):
        contract, policy = self._contract(request)
        copied = request.model_copy(update={"metadata": {**request.metadata, "resolved_configuration": {}}})
        spec, maximum, base_digest = super()._parse(copied)
        if any(not path_allowed(path, policy.allowed_paths) for path in spec.writable_paths):
            code = "CODING_AGENT_CONTRACT_SCOPE_CONFLICT"
            raise LiveLoopError(code)
        return (
            spec,
            maximum,
            sha256_digest(
                {
                    "loop_policy_digest": base_digest,
                    "contract": contract.reference,
                    "policy": policy,
                    "configuration": request.metadata["resolved_configuration"],
                    "requirement": request.input.get("namedInputs", {}).get("requirement"),
                }
            ),
        )

    async def _agent_iteration(
        self, request: TaskRequest, spec: LiveLoopSpec, state: LiveLoopState, attempt: LiveLoopAttempt, timeout_ms: int
    ) -> LiveLoopAttempt:
        contract, policy = self._contract(request)
        self._report(spec, state.current, policy)
        files = {}
        readable = {
            *spec.writable_paths,
            *(
                check.test_path
                for check in spec.verification_commands
                if path_allowed(check.test_path, policy.allowed_paths)
            ),
        }
        for path in sorted(readable):
            item = (
                state.current.changes[path]
                if path in state.current.changes
                else await self.workspace.baseline(spec.base_commit, path)
            )
            files[path] = item.content if item else None
        prompt = json.dumps(
            {
                "requirement": request.input.get("namedInputs", {}).get("requirement"),
                "approved_contract": contract.document.model_dump(mode="json"),
                "approved_reference": contract.reference.model_dump(mode="json"),
                "contract_policy": policy.model_dump(mode="json"),
                "specification": spec.model_dump(mode="json"),
                "candidate_digest": state.current.content_digest,
                "files": files,
                "previous_findings": [
                    {"check_id": check.check_id, "stderr": check.stderr[-2048:], "exit_code": check.exit_code}
                    for check in state.previous_findings
                    if not check.passed
                ],
                "previous_contract_findings": state.history[-1].get("contract_checks", []) if state.history else [],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if len(prompt) + len(_SYSTEM) > spec.context_budget_chars:
            code = "TASK_LOOP_CONTEXT_BUDGET_EXCEEDED"
            raise LiveLoopError(code)
        session_directory = self.workspace.path(request.attempt_id, "session")
        session_directory.mkdir(exist_ok=False)
        # Local runtime discovery is anchored away from source/config/plugins.
        await self.workspace.git(session_directory, "init", "--quiet")
        attempt, outcome = await self._invoke_runtime(
            request,
            spec,
            state,
            attempt,
            timeout_ms,
            directory=session_directory,
            prompt=prompt,
            system=_SYSTEM,
            mode="FILE_PROPOSAL",
        )
        changes = dict(state.current.changes)
        for path, content in outcome.files.items():
            if path not in spec.writable_paths or not path_allowed(path, policy.allowed_paths):
                code = "CODING_AGENT_CONTRACT_PATH_DENIED"
                raise LiveLoopError(code)
            base = await self.workspace.baseline(spec.base_commit, path)
            current = changes.get(path, base)
            if policy.read_only and (current is None or current.content != content):
                code = "CODING_AGENT_CONTRACT_READ_ONLY"
                raise LiveLoopError(code)
            item = LiveLoopFile(content=content, mode=base.mode if base else "100644")
            if item == base:
                changes.pop(path, None)
            else:
                changes[path] = item
        # Validate the entire cumulative proposal before any repository file is written.
        digest = LiveLoopCandidate.digest(spec.base_commit, changes)
        proposed = state.current.model_copy(update={"changes": changes, "content_digest": digest})
        LiveLoopCandidate.model_validate(proposed.model_dump())
        self._report(spec, proposed, policy)
        await self._dispose(attempt, abort=False)
        directory = await self.workspace.create(request.attempt_id, "agent", proposed)
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

    @staticmethod
    def _report(spec: LiveLoopSpec, candidate: LiveLoopCandidate, policy) -> CodingAgentContractVerification:
        if (
            set(candidate.changes) - set(spec.writable_paths)
            or any(
                not path_allowed(path, policy.allowed_paths) or item is None for path, item in candidate.changes.items()
            )
            or (policy.read_only and candidate.changes)
        ):
            code = "CODING_AGENT_CONTRACT_CANDIDATE_INVALID"
            raise LiveLoopError(code)
        json_files = [item.content for path, item in candidate.changes.items() if path.lower().endswith(".json")]
        json_passed = bool(json_files)
        for content in json_files:
            try:
                json.loads(content)
            except ValueError:
                json_passed = False
        results = {
            PATCH_VERIFIER: bool(candidate.changes),
            UNCHANGED_VERIFIER: not candidate.changes,
            JSON_VERIFIER: json_passed,
        }
        return CodingAgentContractVerification(
            contract_reference=policy.contract_reference,
            policy_digest=model_digest(policy),
            spec_digest=spec.content_digest,
            candidate_id=candidate.candidate_id,
            candidate_digest=candidate.content_digest,
            changed_paths=tuple(sorted(candidate.changes)),
            checks=tuple(
                CriterionEvidence(**criterion.model_dump(), passed=results[criterion.verifier_ref])
                for criterion in policy.criteria
            ),
        )

    async def _verify_additional(self, request: TaskRequest, spec: LiveLoopSpec, candidate: LiveLoopCandidate) -> dict:
        _, policy = self._contract(request)
        return self._report(spec, candidate, policy).model_dump(mode="json")

    def _additional_checks_passed(self, request: TaskRequest, spec: LiveLoopSpec, attempt: LiveLoopAttempt) -> bool:
        _, policy = self._contract(request)
        evidence = CodingAgentContractVerification.model_validate(attempt.additional_evidence)
        if attempt.candidate is None or evidence != self._report(spec, attempt.candidate, policy):
            code = "CODING_AGENT_CONTRACT_EVIDENCE_INVALID"
            raise LiveLoopError(code)
        return evidence.passed

    def _additional_outputs(self, attempt: LiveLoopAttempt) -> dict:
        return {
            "contract_reference": attempt.additional_evidence["contract_reference"],
            "contract_verification_report": attempt.additional_evidence,
        }

    def _additional_summary(self, attempt: LiveLoopAttempt) -> dict:
        return {"contract_checks": attempt.additional_evidence["checks"]}

    async def _dispose(self, attempt: LiveLoopAttempt, *, abort: bool) -> None:
        await super()._dispose(attempt, abort=abort)
        await self.workspace.remove(attempt.attempt_id, "session")

    def _iteration_mode(self) -> str:
        return "FILE_PROPOSAL"

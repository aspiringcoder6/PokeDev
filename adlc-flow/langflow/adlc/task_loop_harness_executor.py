"""Harness iteration composition over the same kernel and protected ADLC verifier."""

import json
import os
from pathlib import Path

from langflow.adlc.coding_agent_loop import ContractTaskLoopExecutor
from langflow.adlc.contract_execution import execution_enabled, safe_relative_path
from langflow.adlc.task_loop_harness import (
    HARNESS_CONTRACT_LOOP_SERVICE,
    HARNESS_LOOP_SERVICE,
    HarnessTaskLoopRuntime,
    harness_loop_enabled,
)
from langflow.adlc.task_loop_live import TaskLoopExecutor
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopFile
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import LiveLoopError, TaskLoopWorkspace

SYSTEM = (
    "Perform exactly one fresh implementation iteration using only the supplied scoped file snapshot. "
    "All tools are disabled; never request tools, ask for approval, import conversation history or compact context. "
    'Return only JSON: {"files":{"relative/path":"complete UTF-8 replacement content"}}. '
    "Omitted files retain their content. No deletions or mode changes. "
    "ADLC captures the cumulative candidate, runs protected tests and handles human review independently."
)


class HarnessProposalTaskLoopExecutor(TaskLoopExecutor):
    service_name = HARNESS_LOOP_SERVICE

    def _parse(self, request):
        from langflow.adlc.blueprints.canonicalization import sha256_digest
        from langflow.adlc.task_loop_harness_release import PLUGIN_DIGEST

        trace = request.metadata.get("plan_traceability", {})
        if (
            request.executor.service != self.service_name
            or trace.get("package_id") != "coding-agent"
            or trace.get("package_version") != "0.3.0"
            or request.metadata.get("resolved_configuration", {}).get("loop_runtime") != "HARNESS"
        ):
            msg = "HARNESS_ITERATION_BINDING_INVALID"
            raise LiveLoopError(msg)
        spec, maximum, policy = super()._parse(request)
        if spec.max_total_cost is not None:
            msg = "HARNESS_ITERATION_COST_BUDGET_UNSUPPORTED"
            raise LiveLoopError(msg)
        if any(
            not safe_relative_path(p)
            for p in (*spec.writable_paths, *(c.test_path for c in spec.verification_commands))
        ):
            msg = "HARNESS_ITERATION_PATH_DENIED"
            raise LiveLoopError(msg)
        return spec, maximum, sha256_digest({"kernel_policy": policy, "plugin_digest": PLUGIN_DIGEST})

    def _iteration_mode(self):
        return "FILE_PROPOSAL"

    async def _agent_iteration(self, request, spec, state, attempt, timeout_ms):
        snapshot = {}
        for path in sorted({*spec.writable_paths, *(c.test_path for c in spec.verification_commands)}):
            item = (
                state.current.changes[path]
                if path in state.current.changes
                else await self.workspace.baseline(spec.base_commit, path)
            )
            snapshot[path] = item.content if item else None
        prompt = json.dumps(
            {
                "requirement": request.input.get("namedInputs", {}).get("requirement"),
                "specification": spec.model_dump(mode="json"),
                "candidate_digest": state.current.content_digest,
                "files": snapshot,
                "previous_findings": [
                    {"check_id": c.check_id, "exit_code": c.exit_code, "stderr": c.stderr[-2048:]}
                    for c in state.previous_findings
                    if not c.passed
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        directory = self.workspace.path(request.attempt_id, "session")
        directory.mkdir(exist_ok=False)
        attempt, outcome = await self._invoke_runtime(
            request,
            spec,
            state,
            attempt,
            timeout_ms,
            directory=directory,
            prompt=prompt,
            system=SYSTEM,
            mode="FILE_PROPOSAL",
        )
        changes = dict(state.current.changes)
        for path, content in outcome.files.items():
            if path not in spec.writable_paths or not safe_relative_path(path):
                msg = "TASK_LOOP_WRITE_SCOPE_VIOLATION"
                raise LiveLoopError(msg)
            base = await self.workspace.baseline(spec.base_commit, path)
            item = LiveLoopFile(content=content, mode=base.mode if base else "100644")
            if item == base:
                changes.pop(path, None)
            else:
                changes[path] = item
        proposed = LiveLoopCandidate.model_validate(
            {
                **state.current.model_dump(),
                "changes": changes,
                "content_digest": LiveLoopCandidate.digest(spec.base_commit, changes),
            }
        )
        await self._dispose(attempt, abort=False)
        worktree = await self.workspace.create(request.attempt_id, "agent", proposed)
        candidate = await self.workspace.capture(request.task_run_id, attempt.iteration, spec, state.current, worktree)
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

    async def _dispose(self, attempt, *, abort):
        await super()._dispose(attempt, abort=abort)
        await self.workspace.remove(attempt.attempt_id, "session")


class HarnessContractTaskLoopExecutor(ContractTaskLoopExecutor):
    service_name = HARNESS_CONTRACT_LOOP_SERVICE

    def _parse(self, request):
        from langflow.adlc.blueprints.canonicalization import sha256_digest
        from langflow.adlc.task_loop_harness_release import PLUGIN_DIGEST

        trace = request.metadata.get("plan_traceability", {})
        if (
            trace.get("package_id") != "coding-agent"
            or trace.get("package_version") != "0.3.0"
            or request.metadata.get("resolved_configuration", {}).get("loop_runtime") != "HARNESS"
        ):
            msg = "HARNESS_ITERATION_BINDING_INVALID"
            raise LiveLoopError(msg)
        spec, maximum, policy = super()._parse(request)
        if spec.max_total_cost is not None:
            msg = "HARNESS_ITERATION_COST_BUDGET_UNSUPPORTED"
            raise LiveLoopError(msg)
        return spec, maximum, sha256_digest({"kernel_policy": policy, "plugin_digest": PLUGIN_DIGEST})


def create_harness_loop_executor(*, contract=False, artifact_payloads=None):
    if not harness_loop_enabled() or (contract and not execution_enabled()):
        return None
    from langflow.adlc.local_projects import project_source_root

    source = os.getenv("ADLC_TASK_LOOP_SOURCE_REPOSITORY", "").strip() or str(project_source_root())
    state_root = Path(
        os.getenv("ADLC_TASK_LOOP_STATE_ROOT", str(Path(__file__).resolve().parents[2] / "data/task-loop"))
    ).resolve()
    root = Path(os.getenv("ADLC_TASK_LOOP_WORKTREE_ROOT", str(state_root / "worktrees"))).resolve()
    cls = HarnessContractTaskLoopExecutor if contract else HarnessProposalTaskLoopExecutor
    try:
        return cls(
            workspace=TaskLoopWorkspace(Path(source), root),
            store=TaskLoopStore(state_root / "task-loop.sqlite3"),
            runtime=HarnessTaskLoopRuntime.from_environment(),
            artifact_payloads=artifact_payloads,
        )
    except (ValueError, LiveLoopError):
        return None

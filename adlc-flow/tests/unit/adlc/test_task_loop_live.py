# ruff: noqa: INP001, PLR2004, S101, S603, S607

"""Delivery B uses real Git and real subprocess checks; only the provider is stubbed."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from langflow.adlc.artifact_payload_store import SourcePatchSnapshot
from langflow.adlc.blueprints.models import PackageReference
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    TaskRequest,
    TaskResultStatus,
    WorkflowRunStatus,
)
from langflow.adlc.opencode_client import OpenCodePromptResult, OpenCodeSession, OpenCodeTokenUsage
from langflow.adlc.opencode_runtime import OpenCodeRuntimeSettings, create_default_task_executor
from langflow.adlc.packages.defaults import create_default_package_access_policy
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE, TASK_LOOP_MODEL, LiveTaskLoopExecutor
from langflow.adlc.task_loop_live_models import LiveLoopSpec
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from scripts.demo_adlc_task_loop_live import live_definitions

TESTS = """import unittest
from pathlib import Path
from math_utils import add

class Acceptance(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
    def test_documentation(self):
        self.assertIn("add(a, b)", Path("README.md").read_text())
    def test_deletion(self):
        self.assertFalse(Path("legacy.txt").exists())
"""
FIX = {"math_utils.py": "def add(a, b):\n    return a + b\n"}
FINISH = {"README.md": "Use add(a, b).\n", "legacy.txt": None}


def _git(source, *args):
    return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True).stdout.decode().strip()


@pytest.fixture
def repository(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Task Loop Test")
    _git(source, "config", "user.email", "task-loop@example.invalid")
    _git(source, "config", "core.autocrlf", "false")
    (source / "math_utils.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (source / "README.md").write_text("Pending.\n", encoding="utf-8")
    (source / "legacy.txt").write_text("Remove me.\n", encoding="utf-8")
    (source / "test_acceptance.py").write_text(TESTS, encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "Trusted baseline and acceptance checks")
    return source


def _spec(repository, **overrides):
    payload = {
        "spec_id": str(uuid4()),
        "specification": "Implement add(a, b), document it, and remove legacy.txt.",
        "base_commit": _git(repository, "rev-parse", "HEAD"),
        "writable_paths": ["math_utils.py", "README.md", "legacy.txt"],
        "acceptance_criteria": [
            {
                "criterion_id": "addition",
                "description": "Addition, documentation and deletion behave correctly.",
                "check_refs": ["acceptance"],
            }
        ],
        "verification_commands": [{"check_id": "acceptance", "test_path": "test_acceptance.py"}],
    }
    payload.update(overrides)
    return LiveLoopSpec.model_validate(payload)


def _request(spec, previous=None, **overrides):
    payload = {
        "request_id": uuid4(),
        "workflow_run_id": previous.workflow_run_id if previous else uuid4(),
        "task_run_id": previous.task_run_id if previous else uuid4(),
        "attempt_id": uuid4(),
        "task_definition_id": previous.task_definition_id if previous else uuid4(),
        "task_type": "IMPLEMENTATION",
        "name": "Live task loop",
        "executor": ExecutorTarget(service=TASK_LOOP_LIVE_SERVICE, operation="live-task-loop"),
        "input": {"namedInputs": {"task_loop_spec": spec.model_dump(mode="json")}},
        "context": {"conversation_history": ["OLD_TRANSCRIPT_DO_NOT_FORWARD"]},
        "dependency_task_run_ids": [],
        "constraints": {"max_attempts": spec.max_iterations, "timeout_ms": 30_000},
        "requested_at": datetime.now(timezone.utc),
        "metadata": {"resolved_configuration": {}},
        "idempotency_key": str(uuid4()),
    }
    payload.update(overrides)
    return TaskRequest(**payload)


class Client:
    def __init__(self, steps=(FIX, FINISH)):
        self.steps = steps
        self.sessions = []
        self.prompts = []
        self.aborted = []
        self.disposed = []
        self.entered = asyncio.Event()
        self.release = None

    async def create_session(self, *, directory, **_kwargs):
        session = OpenCodeSession(session_id=f"session-{uuid4()}", directory=directory)
        self.sessions.append(session)
        return session

    async def get_messages(self, session_id, **_kwargs):
        if not any(item[0] == session_id for item in self.prompts):
            return []
        return [
            {
                "info": {"id": "answer", "role": "assistant", "cost": 0.1, "tokens": {"input": 11, "output": 7}},
                "parts": [],
            }
        ]

    async def prompt(self, session_id, *, directory, prompt, **_kwargs):
        self.prompts.append((session_id, prompt))
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        step = self.steps[min(len(self.prompts) - 1, len(self.steps) - 1)]
        for relative, content in step.items():
            path = Path(directory) / relative
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="")
        provider, _, model = TASK_LOOP_MODEL.partition("/")
        return OpenCodePromptResult(
            message_id="answer",
            text="Everything passed. TRACE_ONLY_NOT_FEEDBACK",
            provider_id=provider,
            model_id=model,
            cost=0.1,
            token_usage=OpenCodeTokenUsage(input_tokens=11, output_tokens=7),
        )

    async def abort(self, session_id, **_kwargs):
        self.aborted.append(session_id)

    async def dispose_instance(self, *, directory, **_kwargs):
        self.disposed.append(directory)


def _executor(tmp_path, repository, client=None, verifier=None):
    workspace = TaskLoopWorkspace(repository, tmp_path / "worktrees")
    return LiveTaskLoopExecutor(
        workspace=workspace,
        store=TaskLoopStore(tmp_path / "state.sqlite3"),
        client=client or Client(),
        verifier=verifier,
    )


async def _ignore(*_args):
    pass


async def test_fresh_live_sessions_real_tests_and_cumulative_changes(repository, tmp_path):
    spec = _spec(repository)
    client = Client(steps=({**FIX, "legacy.txt": None}, {"README.md": "Use add(a, b).\n"}))
    first_executor = _executor(tmp_path, repository, client)
    first_request = _request(spec)
    first = await first_executor.execute(first_request, _ignore)
    assert first.status is TaskResultStatus.FAILED
    assert first.error.code == "TASK_LOOP_CHECKS_FAILED"
    assert first.error.retryable
    saved = first_executor.store.attempt(first_request)
    assert saved.verification.checks[0].exit_code == 1
    assert saved.verification.checks[0].executed_tests == 3
    assert "AssertionError" in saved.verification.checks[0].stderr
    assert saved.candidate.changes["legacy.txt"] is None
    second_request = _request(spec, first_request)
    # Recreate every executor/SQLite object between iterations.
    restarted = _executor(tmp_path, repository, client)
    second = await restarted.execute(second_request, _ignore)
    assert second.status is TaskResultStatus.SUCCEEDED
    candidate = second.output["outputs"]["candidate"]
    assert candidate["changes"]["math_utils.py"]["content"] == FIX["math_utils.py"]
    assert candidate["changes"]["legacy.txt"] is None
    assert candidate["parent_candidate_id"] == str(saved.candidate.candidate_id)
    proof = second.output["outputs"]["verification_report"]
    assert proof["candidate_digest"] == candidate["content_digest"]
    assert proof["checks"][0]["exit_code"] == 0
    assert proof["checks"][0]["executed_tests"] == 3
    assert len(client.sessions) == 2
    prompts = [json.loads(item[1]) for item in client.prompts]
    assert prompts[0]["specification"] == prompts[1]["specification"] == spec.model_dump(mode="json")
    assert prompts[1]["candidate"]["content_digest"] == saved.candidate.content_digest
    assert "AssertionError" in prompts[1]["previous_findings"][0]["stderr"]
    assert "OLD_TRANSCRIPT_DO_NOT_FORWARD" not in str(prompts)
    assert "TRACE_ONLY_NOT_FEEDBACK" not in str(prompts)
    assert _git(repository, "status", "--porcelain") == ""
    assert not list((tmp_path / "worktrees").glob("*-agent"))
    assert not list((tmp_path / "worktrees").glob("*-verify"))
    patch = SourcePatchSnapshot.model_validate_json(restarted.artifact_payloads.read(second.artifacts[0]))
    assert patch.base_commit == spec.base_commit
    assert {item.file for item in patch.files} == set(spec.writable_paths)
    assert (await restarted.resume(second_request, _ignore)) == second
    assert len(client.sessions) == 2


class SimulatedCrash(BaseException):
    pass


class CrashVerifier:
    async def verify(self, *_args):
        raise SimulatedCrash


async def test_recovery_verifies_checkpoint_without_reissuing_model_call(repository, tmp_path):
    client = Client(steps=({**FIX, **FINISH},))
    executor = _executor(tmp_path, repository, client, CrashVerifier())
    request = _request(_spec(repository))
    with pytest.raises(SimulatedCrash):
        await executor.execute(request, _ignore)
    assert executor.store.attempt(request).phase == "CANDIDATE_CAPTURED"
    saved_digest = executor.store.attempt(request).candidate.content_digest
    restarted = _executor(tmp_path, repository, client)
    result = await restarted.resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.output["outputs"]["candidate"]["content_digest"] == saved_digest
    assert len(client.sessions) == len(client.prompts) == 1


class CrashClient(Client):
    async def prompt(self, *_args, **_kwargs):
        raise SimulatedCrash


async def test_interrupted_model_requires_explicit_new_attempt(repository, tmp_path):
    crashed = CrashClient()
    original = _executor(tmp_path, repository, crashed)
    spec = _spec(repository)
    request = _request(spec)
    with pytest.raises(SimulatedCrash):
        await original.execute(request, _ignore)
    assert original.store.attempt(request).phase == "AGENT_RUNNING"
    replacement_client = Client(steps=({**FIX, **FINISH},))
    restarted = _executor(tmp_path, repository, replacement_client)
    interrupted = await restarted.resume(request, _ignore)
    assert interrupted.error.code == "ADLC_RECOVERY_TASK_LOOP_INTERRUPTED"
    assert interrupted.error.retryable is False
    assert replacement_client.sessions == []
    retry = await restarted.execute(_request(spec, request), _ignore)
    assert retry.status is TaskResultStatus.SUCCEEDED
    assert len(replacement_client.sessions) == 1


async def test_concurrent_duplicate_executors_make_one_provider_call(repository, tmp_path):
    client = Client(steps=({**FIX, **FINISH},))
    client.release = asyncio.Event()
    request = _request(_spec(repository))
    executor = _executor(tmp_path, repository, client)
    other = _executor(tmp_path, repository, client)
    first = asyncio.create_task(executor.execute(request, _ignore))
    await asyncio.wait_for(client.entered.wait(), 5)
    duplicate = asyncio.create_task(other.execute(request, _ignore))
    client.release.set()
    result, replay = await asyncio.gather(first, duplicate)
    assert result == replay
    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(client.sessions) == 1
    conflicting = await other.execute(request.model_copy(update={"name": "different"}), _ignore)
    assert conflicting.error.code == "TASK_LOOP_IDEMPOTENCY_CONFLICT"
    assert len(client.sessions) == 1


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"test_acceptance.py": "# Removed tests\n"}, "TASK_LOOP_WRITE_SCOPE_VIOLATION"),
        ({"outside.py": "# Out of scope\n"}, "TASK_LOOP_WRITE_SCOPE_VIOLATION"),
    ],
)
async def test_agent_cannot_weaken_checks_or_expand_write_scope(repository, tmp_path, change, expected):
    executor = _executor(tmp_path, repository, Client(steps=(change,)))
    result = await executor.execute(_request(_spec(repository)), _ignore)
    assert result.error.code == expected
    assert result.error.retryable is False
    assert _git(repository, "status", "--porcelain") == ""


async def test_cancellation_aborts_session_and_preserves_last_completed_candidate(repository, tmp_path):
    client = Client()
    client.release = asyncio.Event()
    executor = _executor(tmp_path, repository, client)
    request = _request(_spec(repository))
    pending = asyncio.create_task(executor.execute(request, _ignore))
    await asyncio.wait_for(client.entered.wait(), 5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert client.aborted == [client.sessions[0].session_id]
    assert executor.store.attempt(request).result.status is TaskResultStatus.CANCELLED
    assert executor.store.state(request).current.iteration == 0
    assert not list((tmp_path / "worktrees").glob("*-agent"))


async def test_spec_drift_and_corrupt_checkpoint_fail_without_model(repository, tmp_path):
    client = Client()
    executor = _executor(tmp_path, repository, client)
    spec = _spec(repository)
    first = _request(spec)
    await executor.execute(first, _ignore)
    changed = LiveLoopSpec.model_validate({**spec.model_dump(), "specification": "Different objective."})
    drift = await executor.execute(_request(changed, first), _ignore)
    assert drift.error.code == "TASK_LOOP_SPEC_CHANGED"
    with sqlite3.connect(executor.store.path) as connection:
        connection.execute("UPDATE task_loop_states SET digest='sha256:wrong'")
    corrupt = await executor.execute(_request(spec, first), _ignore)
    assert corrupt.error.code == "TASK_LOOP_CHECKPOINT_CORRUPT"
    assert len(client.sessions) == 1


@pytest.mark.parametrize(
    ("budget", "expected"),
    [
        ({"max_iterations": 1}, "TASK_LOOP_BUDGET_EXHAUSTED"),
        ({"max_total_tokens": 1}, "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"),
        ({"max_total_cost": 0.01}, "TASK_LOOP_COST_BUDGET_EXHAUSTED"),
    ],
)
async def test_resource_budgets_stop_repetition(repository, tmp_path, budget, expected):
    executor = _executor(tmp_path, repository)
    spec = _spec(repository, **budget)
    result = await executor.execute(_request(spec), _ignore)
    assert result.error.code == expected
    assert result.error.retryable is False


async def test_missing_checkpoint_never_restarts_an_original_request(repository, tmp_path):
    executor = _executor(tmp_path, repository)
    result = await executor.resume(_request(_spec(repository)), _ignore)
    assert result.error.code == "ADLC_RECOVERY_TASK_LOOP_MISSING"
    assert executor.client.sessions == []


def test_live_package_is_opt_in(monkeypatch, tmp_path, repository):
    reference = PackageReference(package_id="task-loop-opencode", version="0.1.0")
    monkeypatch.setenv("ADLC_TASK_LOOP_OPENCODE_ENABLED", "false")
    assert not create_default_package_access_policy().can_view_package("owner", reference)
    settings = OpenCodeRuntimeSettings(enabled=False, source_repository=None, worktree_root=None, base_ref="HEAD")
    assert TASK_LOOP_LIVE_SERVICE not in create_default_task_executor(settings).available_services
    monkeypatch.setenv("ADLC_TASK_LOOP_OPENCODE_ENABLED", "true")
    monkeypatch.setenv("ADLC_TASK_LOOP_SOURCE_REPOSITORY", str(repository))
    monkeypatch.setenv("ADLC_TASK_LOOP_STATE_ROOT", str(tmp_path / "runtime-state"))
    assert create_default_package_access_policy().can_view_package("owner", reference)
    assert TASK_LOOP_LIVE_SERVICE in create_default_task_executor(settings).available_services


async def _wait_status(service, run_id, status):
    async def wait():
        while True:
            run = await service.get_run(run_id, owner_id="owner")
            if run.status is status:
                return run
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(wait(), 30)


async def test_coordinator_approval_and_durable_pending_review(repository, tmp_path):
    client = Client()
    executor = _executor(tmp_path, repository, client)
    definitions = live_definitions(_spec(repository))[1]
    definitions[0].constraints["retry_backoff_ms"] = 0
    run_db = tmp_path / "runs.sqlite3"
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: executor}),
        repository=SqliteRunRepository(run_db),
        artifact_payloads=executor.artifact_payloads,
    )
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Live loop",
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    run = await _wait_status(service, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert len(run.tasks) == 1
    assert run.tasks[0].retry_count == 1
    assert len(client.sessions) == 2
    restarted_executor = _executor(tmp_path, repository, client)
    restarted = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: restarted_executor}),
        repository=SqliteRunRepository(run_db),
        artifact_payloads=restarted_executor.artifact_payloads,
    )
    restored = await restarted.get_run(run.id, owner_id="owner")
    assert restored.status is WorkflowRunStatus.WAITING_APPROVAL
    patch = await restarted.get_source_patch(run.id, restored.tasks[0].artifacts[0].artifact_id, owner_id="owner")
    assert patch.base_commit == _spec(repository).base_commit
    approved = await restarted.approve(
        restored.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment="Approve tested candidate.",
    )
    approved = await _wait_status(restarted, approved.id, WorkflowRunStatus.SUCCEEDED)
    assert approved.status is WorkflowRunStatus.SUCCEEDED
    assert len(client.sessions) == 2


@pytest.mark.parametrize(
    "tests",
    [
        "# no tests\n",
        "import unittest\n@unittest.skip('skip')\nclass Empty(unittest.TestCase):\n"
        "    def test_skip(self):\n        pass\n",
    ],
)
async def test_empty_or_all_skipped_suites_are_not_acceptance(repository, tmp_path, tests):
    (repository / "test_acceptance.py").write_text(tests, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Empty suite")
    executor = _executor(tmp_path, repository, Client(steps=({**FIX, **FINISH},)))
    request = _request(_spec(repository))
    result = await executor.execute(request, _ignore)
    assert result.status is TaskResultStatus.FAILED
    assert executor.store.attempt(request).verification.checks[0].executed_tests == 0


def test_spec_requires_tracked_protected_checks(repository):
    with pytest.raises(ValidationError):
        _spec(repository, writable_paths=["test_acceptance.py"])


async def test_test_timeout_is_a_real_failure_and_kills_the_runner(repository, tmp_path):
    content = (
        "import unittest, time\nclass Slow(unittest.TestCase):\n    def test_wait(self):\n        time.sleep(60)\n"
    )
    (repository / "test_acceptance.py").write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Slow acceptance test")
    spec = _spec(
        repository,
        verification_commands=[{"check_id": "acceptance", "test_path": "test_acceptance.py", "timeout_ms": 200}],
    )
    executor = _executor(tmp_path, repository, Client(steps=({**FIX, **FINISH},)))
    request = _request(spec)
    result = await asyncio.wait_for(executor.execute(request, _ignore), 10)
    assert result.status is TaskResultStatus.FAILED
    check = executor.store.attempt(request).verification.checks[0]
    assert check.timed_out
    assert not check.passed
    assert check.exit_code != 0


async def test_recovery_consumes_verified_proof_without_rerunning_tests(repository, tmp_path, monkeypatch):
    client = Client(steps=({**FIX, **FINISH},))
    executor = _executor(tmp_path, repository, client)
    request = _request(_spec(repository))

    def crash(*_args):
        raise SimulatedCrash

    monkeypatch.setattr(executor.store, "finish", crash)
    with pytest.raises(SimulatedCrash):
        await executor.execute(request, _ignore)
    assert executor.store.attempt(request).phase == "VERIFIED"
    restarted = _executor(tmp_path, repository, client, CrashVerifier())
    result = await restarted.resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(client.prompts) == 1


class ParkVerifier:
    def __init__(self):
        self.entered = asyncio.Event()

    async def verify(self, *_args):
        self.entered.set()
        await asyncio.Event().wait()


def _backup(source, target):
    with sqlite3.connect(source) as original, sqlite3.connect(target) as snapshot:
        original.backup(snapshot)


async def test_coordinator_restart_resumes_original_attempt_from_durable_snapshot(repository, tmp_path):
    client = Client(steps=({**FIX, **FINISH},))
    park = ParkVerifier()
    executor = _executor(tmp_path, repository, client, park)
    definitions = live_definitions(_spec(repository))[1]
    run_db = tmp_path / "runs.sqlite3"
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: executor}),
        repository=SqliteRunRepository(run_db),
        artifact_payloads=executor.artifact_payloads,
    )
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Crash recovery",
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    await asyncio.wait_for(park.entered.wait(), 5)
    # These are the two durable databases as they exist at the instant of a crash.
    restored_runs = tmp_path / "recovered-runs.sqlite3"
    restored_loops = tmp_path / "recovered-loops.sqlite3"
    _backup(run_db, restored_runs)
    _backup(executor.store.path, restored_loops)
    running = await service.get_run(run.id, owner_id="owner")
    original_request = running.tasks[0].request
    await service.cancel_run(run.id, owner_id="owner")
    await _wait_status(service, run.id, WorkflowRunStatus.CANCELLED)
    resumed_executor = LiveTaskLoopExecutor(
        workspace=executor.workspace, store=TaskLoopStore(restored_loops), client=client
    )
    recovered = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: resumed_executor}),
        repository=SqliteRunRepository(restored_runs),
        artifact_payloads=resumed_executor.artifact_payloads,
    )
    restored = await _wait_status(recovered, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert restored.tasks[0].current_attempt_id == original_request.attempt_id
    assert restored.tasks[0].request.request_id == original_request.request_id
    assert len(client.sessions) == len(client.prompts) == 1


async def test_pinned_commit_survives_source_head_movement(repository, tmp_path):
    spec = _spec(repository)
    (repository / "README.md").write_text("Unrelated later baseline.\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Advance source HEAD")
    executor = _executor(tmp_path, repository, Client(steps=({**FIX, **FINISH},)))
    result = await executor.execute(_request(spec), _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.output["outputs"]["candidate"]["base_commit"] == spec.base_commit
    assert (repository / "README.md").read_text() == "Unrelated later baseline.\n"


async def test_unchanged_candidates_stop_after_stall_budget(repository, tmp_path):
    client = Client(steps=({},))
    executor = _executor(tmp_path, repository, client)
    spec = _spec(repository)
    first = _request(spec)
    assert (await executor.execute(first, _ignore)).error.code == "TASK_LOOP_CHECKS_FAILED"
    result = await executor.execute(_request(spec, first), _ignore)
    assert result.error.code == "TASK_LOOP_STALLED"
    assert result.error.retryable is False
    assert len(client.sessions) == 2


async def test_verification_environment_excludes_provider_secrets(repository, tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_LOOP_TEST_SECRET", "test-only-value")
    content = (
        "import unittest, os\nclass Env(unittest.TestCase):\n    def test_env(self):\n"
        "        self.assertIsNone(os.getenv('TASK_LOOP_TEST_SECRET'))\n"
    )
    (repository / "test_acceptance.py").write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Check clean verification environment")
    executor = _executor(tmp_path, repository, Client(steps=({**FIX, **FINISH},)))
    result = await executor.execute(_request(_spec(repository)), _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED


@pytest.mark.parametrize("path", ["NUL", "src/CON.py", "trailing. ", "wildcard*.py"])
def test_portable_writable_paths_reject_windows_aliases(repository, path):
    with pytest.raises(ValidationError):
        _spec(repository, writable_paths=[path])


class LoseCallback:
    service_name = TASK_LOOP_LIVE_SERVICE
    capabilities = LiveTaskLoopExecutor.capabilities

    def __init__(self, executor):
        self.executor = executor

    async def execute(self, request, _callback):
        await self.executor.execute(request, _ignore)
        message = "Crash after immutable result commit"
        raise RuntimeError(message)

    async def get_saved_result(self, request):
        return await self.executor.get_saved_result(request)

    async def resume(self, request, callback):
        return await self.executor.resume(request, callback)


async def test_explicit_retry_adopts_saved_success_when_terminal_callback_was_lost(repository, tmp_path):
    client = Client(steps=({**FIX, **FINISH},))
    executor = _executor(tmp_path, repository, client)
    definitions = live_definitions(_spec(repository))[1]
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: LoseCallback(executor)}),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Lost callback",
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    failed = await _wait_status(service, run.id, WorkflowRunStatus.PAUSED)
    original_attempt = failed.tasks[0].current_attempt_id
    assert failed.tasks[0].result.error.code == "TASK_EXECUTION_CRASHED"
    await service.retry_task(failed.tasks[0].id, owner_id="owner")
    recovered = await _wait_status(service, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert recovered.tasks[0].current_attempt_id == original_attempt
    assert recovered.tasks[0].retry_count == 0
    assert len(client.sessions) == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows job ownership of descendants")
async def test_finished_test_runner_cannot_leave_a_child_holding_output_pipes(repository, tmp_path):
    content = (
        "import unittest, subprocess, sys\nclass Child(unittest.TestCase):\n"
        "    def test_child(self):\n"
        "        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "        print('CHILD_PID=' + str(process.pid))\n"
    )
    (repository / "test_acceptance.py").write_text(content, encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Descendant process cleanup")
    executor = _executor(tmp_path, repository, Client(steps=({**FIX, **FINISH},)))
    request = _request(_spec(repository))
    result = await asyncio.wait_for(executor.execute(request, _ignore), 10)
    assert result.status is TaskResultStatus.SUCCEEDED
    output = executor.store.attempt(request).verification.checks[0].stdout
    pid = next(line.partition("=")[2] for line in output.splitlines() if line.startswith("CHILD_PID="))
    # Query only this fixture's child, not Windows' machine-wide process inventory.
    # Access denied is an error, never evidence that the child has stopped.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    inherit_handle = False
    handle = kernel.OpenProcess(0x1000, inherit_handle, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION, read-only.
    if not handle:
        assert ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: this PID no longer exists.
    else:
        try:
            exit_code = wintypes.DWORD()
            assert kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            assert exit_code.value != 259  # STILL_ACTIVE.
        finally:
            kernel.CloseHandle(handle)


@pytest.mark.parametrize(
    ("budget", "code"),
    [
        ({"max_total_tokens": 18}, "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"),
        ({"max_total_cost": 0.1}, "TASK_LOOP_COST_BUDGET_EXHAUSTED"),
    ],
)
async def test_reported_usage_survives_interruption_and_blocks_an_over_budget_retry(
    repository, tmp_path, monkeypatch, budget, code
):
    client = Client(steps=({**FIX, **FINISH},))
    executor = _executor(tmp_path, repository, client)
    spec = _spec(repository, **budget)
    request = _request(spec)

    async def crash(*_args):
        raise SimulatedCrash

    monkeypatch.setattr(executor.workspace, "capture", crash)
    with pytest.raises(SimulatedCrash):
        await executor.execute(request, _ignore)
    assert executor.store.attempt(request).total_tokens == 18
    restarted = _executor(tmp_path, repository, client)
    assert (await restarted.resume(request, _ignore)).error.code == "ADLC_RECOVERY_TASK_LOOP_INTERRUPTED"
    result = await restarted.execute(_request(spec, request), _ignore)
    assert result.error.code == code
    assert result.error.retryable is False
    assert len(client.prompts) == 1

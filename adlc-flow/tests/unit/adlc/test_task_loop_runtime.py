"""Runtime substitution uses real capture/checks/checkpoints; no provider or Harness is contacted."""
# ruff: noqa: INP001, S101, PLR2004, PLC0414, F811

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.coding_agent_loop import ContractTaskLoopExecutor
from langflow.adlc.models import TaskResultStatus, WorkflowRunStatus
from langflow.adlc.run_service import AdlcRunNotFoundError
from langflow.adlc.task_loop_live import TaskLoopExecutor
from langflow.adlc.task_loop_opencode import OpenCodeTaskLoopRuntime
from langflow.adlc.task_loop_runtime_inspection import inspect_runtime
from langflow.adlc.task_loop_runtime_models import (
    LoopIterationOutcome,
    LoopIterationRequest,
    LoopRuntimeBinding,
    LoopRuntimeSession,
    LoopRuntimeUsage,
)
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from tests.unit.adlc.test_coding_agent import ProposalClient, contract_for, request_for
from tests.unit.adlc.test_coding_agent import contracts as contracts
from tests.unit.adlc.test_coding_agent import spec as spec
from tests.unit.adlc.test_task_loop_inspection import start_live
from tests.unit.adlc.test_task_loop_live import (
    FINISH,
    FIX,
    Client,
    SimulatedCrash,
    _git,
    _ignore,
    _request,
    _spec,
    _wait_status,
)
from tests.unit.adlc.test_task_loop_live import repository as repository


class FixtureRuntime:
    """Independent adapter: no OpenCode types/client; intentionally not a production Harness adapter."""

    def __init__(self, steps=(FIX, FINISH), **binding):
        self.binding = LoopRuntimeBinding(
            runtime_ref="runtime:offline-protocol-fixture/0.1.0",
            family="CUSTOM",
            provider_id="fixture",
            model_id="no-model",
            modes=("WORKSPACE_EDIT", "FILE_PROPOSAL"),
            **binding,
        )
        self.steps = steps
        self.commands = []
        self.opened = []
        self.closed = []
        self.entered = asyncio.Event()
        self.release = None
        self.session_change = {}
        self.outcome_change = {}
        self.crash = False

    async def open_iteration(self, command, *, directory):
        assert command.runtime == self.binding
        assert directory.is_dir()
        self.opened.append(command)
        # Return a fresh local opaque identity, not a provider session object/directory.
        return LoopRuntimeSession(
            runtime=self.binding,
            request_digest=command.content_digest,
            session_id=f"fixture-{uuid4()}",
            fresh_context=True,
            tools_disabled=command.mode == "FILE_PROPOSAL",
        ).model_copy(update=self.session_change)

    async def run_iteration(self, command, session, *, directory):
        self.commands.append(command)
        self.entered.set()
        if self.release:
            await self.release.wait()
        if self.crash:
            raise SimulatedCrash
        changes = self.steps[min(len(self.commands) - 1, len(self.steps) - 1)]
        if command.mode == "WORKSPACE_EDIT":
            for path, value in changes.items():
                target = directory / path
                if value is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(value, encoding="utf-8", newline="")
        outcome = LoopIterationOutcome(
            runtime=self.binding,
            request_digest=command.content_digest,
            session_id=session.session_id,
            mode=command.mode,
            usage=LoopRuntimeUsage(input_tokens=11, output_tokens=7, total_tokens=18, cost=0.1),
            tool_activity=False,
            files=changes if command.mode == "FILE_PROPOSAL" else None,
        )
        return SimpleNamespace(model_dump=lambda: {**outcome.model_dump(), **self.outcome_change})

    async def close_iteration(self, session, *, directory, abort):
        assert session.runtime == self.binding
        assert directory.is_absolute()
        self.closed.append((session.session_id, abort))


def executor(tmp_path, repository, runtime, *, contract=False):
    cls = ContractTaskLoopExecutor if contract else TaskLoopExecutor
    return cls(
        workspace=TaskLoopWorkspace(repository, tmp_path / "worktrees"),
        store=TaskLoopStore(tmp_path / "runtime.sqlite3"),
        runtime=runtime,
    )


@pytest.mark.parametrize("adapter", ["opencode", "independent"])
@pytest.mark.parametrize("combined", [False, True])
async def test_both_loop_modes_use_the_same_protocol_and_protected_verifier(
    contracts, spec, repository, tmp_path, adapter, combined
):
    loop_spec = spec if combined else _spec(repository)
    steps = (FIX, {"README.md": "Use add(a, b).\n"}) if combined else (FIX, FINISH)
    client = (ProposalClient if combined else Client)(steps=steps)
    runtime = OpenCodeTaskLoopRuntime(client) if adapter == "opencode" else FixtureRuntime(steps)
    kernel = executor(tmp_path, repository, runtime, contract=combined)
    contract = contract_for(contracts) if combined else None
    request = request_for(loop_spec, contract) if combined else _request(loop_spec)
    failed = await kernel.execute(request, _ignore)
    assert failed.error.code == "TASK_LOOP_CHECKS_FAILED"
    saved = kernel.store.attempt(request)
    header = saved.runtime_checkpoint
    assert header.runtime == runtime.binding
    assert header.phase == "FINISHED"
    assert header.session.fresh_context
    assert header.candidate.content_digest == saved.candidate.content_digest
    assert header.verification_digest
    second = request_for(loop_spec, contract, request) if combined else _request(loop_spec, request)
    restarted = executor(tmp_path, repository, runtime, contract=combined)
    result = await restarted.execute(second, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    proof = result.output["outputs"]["verification_report"]
    assert proof["candidate_digest"] == result.output["outputs"]["candidate"]["content_digest"]
    assert proof["checks"][0]["executed_tests"] == 2
    if combined:
        assert result.output["outputs"]["contract_verification_report"]["candidate_digest"] == proof["candidate_digest"]
    assert result.metadata["task_loop"]["runtime_protocol"] == runtime.binding.protocol_ref
    assert result.metadata["task_loop"]["execution_unified_with_harness"] is False
    assert await restarted.execute(second, _ignore) == result
    assert _git(repository, "status", "--porcelain") == ""
    if adapter == "independent":
        assert restarted.client is None
        assert len(runtime.commands) == 2
        assert runtime.commands[1].parent_candidate.candidate_id == saved.candidate.candidate_id
        assert all("OLD_TRANSCRIPT_DO_NOT_FORWARD" not in c.model_dump_json() for c in runtime.commands)


async def test_duplicate_delivery_has_one_neutral_runtime_call(repository, tmp_path):
    runtime = FixtureRuntime(({**FIX, **FINISH},))
    runtime.release = asyncio.Event()
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))
    first = asyncio.create_task(kernel.execute(request, _ignore))
    await asyncio.wait_for(runtime.entered.wait(), 5)
    duplicate = asyncio.create_task(executor(tmp_path, repository, runtime).execute(request, _ignore))
    runtime.release.set()
    results = await asyncio.gather(first, duplicate)
    assert results[0] == results[1]
    assert len(runtime.commands) == len(runtime.opened) == 1


@pytest.mark.parametrize("phase", ["CANDIDATE_CAPTURED", "VERIFIED"])
async def test_checkpoint_recovery_never_repeats_runtime_call(repository, tmp_path, monkeypatch, phase):
    runtime = FixtureRuntime(({**FIX, **FINISH},))
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))
    if phase == "CANDIDATE_CAPTURED":

        async def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.verifier, "verify", crash)
    else:

        def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.store, "finish", crash)
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    assert kernel.store.attempt(request).runtime_checkpoint.phase == phase
    restored = executor(tmp_path, repository, runtime)
    if phase == "VERIFIED":

        async def forbidden(*_args):
            pytest.fail("Completed proof must not execute checks again")

        monkeypatch.setattr(restored.verifier, "verify", forbidden)
    result = await restored.resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(runtime.commands) == 1


async def test_interrupted_session_uses_only_its_bound_adapter_for_abort(repository, tmp_path):
    runtime = FixtureRuntime()
    runtime.crash = True
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    saved = kernel.store.attempt(request)
    assert saved.runtime_checkpoint.phase == "AGENT_RUNNING"
    result = await executor(tmp_path, repository, runtime).resume(request, _ignore)
    assert result.error.code == "ADLC_RECOVERY_TASK_LOOP_INTERRUPTED"
    assert len(runtime.commands) == 1
    assert runtime.closed[-1] == (saved.session_id, True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_ref", "runtime:other/0.1.0"),
        ("model_id", "other-model"),
        ("family", "HARNESS"),
        ("agent", "other-agent"),
    ],
)
async def test_runtime_drift_requires_a_new_loop_not_checkpoint_reuse(repository, tmp_path, field, value):
    original = FixtureRuntime()
    kernel = executor(tmp_path, repository, original)
    spec = _spec(repository)
    request = _request(spec)
    await kernel.execute(request, _ignore)
    replacement = FixtureRuntime()
    replacement.binding = replacement.binding.model_copy(update={field: value})
    result = await executor(tmp_path, repository, replacement).execute(_request(spec, request), _ignore)
    assert result.error.code == "TASK_LOOP_RUNTIME_CHANGED"
    assert not replacement.opened
    assert kernel.store.state(request).next_iteration == 2


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"fresh_context": False}, "TASK_LOOP_SESSION_NOT_FRESH"),
        ({"request_digest": "sha256:" + "0" * 64}, "TASK_LOOP_RUNTIME_SESSION_MISMATCH"),
    ],
)
async def test_invalid_session_acknowledgement_fails_before_prompt(repository, tmp_path, change, code):
    runtime = FixtureRuntime()
    runtime.session_change = change
    result = await executor(tmp_path, repository, runtime).execute(_request(_spec(repository)), _ignore)
    assert result.error.code == code
    assert not runtime.commands


async def test_contract_runtime_must_acknowledge_tool_denial(contracts, spec, repository, tmp_path):
    runtime = FixtureRuntime()
    runtime.session_change = {"tools_disabled": False}
    result = await executor(tmp_path, repository, runtime, contract=True).execute(
        request_for(spec, contract_for(contracts)), _ignore
    )
    assert result.error.code == "TASK_LOOP_RUNTIME_RESTRICTIONS_UNAVAILABLE"
    assert not runtime.commands


async def test_unsupported_contract_mode_fails_without_a_runtime_session(contracts, spec, repository, tmp_path):
    runtime = FixtureRuntime()
    runtime.binding = runtime.binding.model_copy(update={"modes": ("WORKSPACE_EDIT",)})
    result = await executor(tmp_path, repository, runtime, contract=True).execute(
        request_for(spec, contract_for(contracts)), _ignore
    )
    assert result.error.code == "TASK_LOOP_RUNTIME_CAPABILITY_UNSUPPORTED"
    assert not runtime.opened


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"request_digest": "sha256:" + "0" * 64}, "TASK_LOOP_RUNTIME_OUTCOME_MISMATCH"),
        ({"session_id": "foreign-session"}, "TASK_LOOP_RUNTIME_OUTCOME_MISMATCH"),
        ({"context_compacted": True}, "TASK_LOOP_EXECUTION_INVALID"),
        ({"passed": True}, "TASK_LOOP_EXECUTION_INVALID"),
    ],
)
async def test_runtime_cannot_supply_foreign_results_compaction_or_pass(repository, tmp_path, change, code):
    runtime = FixtureRuntime(({**FIX, **FINISH},))
    runtime.outcome_change = change
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))
    result = await kernel.execute(request, _ignore)
    assert result.error.code == code
    assert kernel.store.attempt(request).candidate is None
    assert kernel.store.attempt(request).verification is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("spec_digest", "sha256:" + "0" * 64), ("task_run_id", None), ("verification_digest", "sha256:" + "0" * 64)],
)
async def test_rehashed_but_misbound_checkpoint_is_rejected_without_work(
    repository, tmp_path, monkeypatch, field, value
):
    runtime = FixtureRuntime(({**FIX, **FINISH},))
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))

    def crash(*_args):
        raise SimulatedCrash

    monkeypatch.setattr(kernel.store, "finish", crash)
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    with sqlite3.connect(kernel.store.path) as connection:
        row = connection.execute("SELECT payload FROM task_loop_attempts").fetchone()
        data = json.loads(row[0])
        data["runtime_checkpoint"][field] = value or str(uuid4())
        connection.execute("UPDATE task_loop_attempts SET payload=?,digest=?", (json.dumps(data), sha256_digest(data)))
    restored = executor(tmp_path, repository, runtime)
    result = await restored.resume(request, _ignore)
    assert result.error.code == "TASK_LOOP_CHECKPOINT_CORRUPT"
    assert len(runtime.commands) == 1


async def test_passive_runtime_view_survives_disabled_dispatch_and_enforces_owner(repository, tmp_path, monkeypatch):
    service, kernel, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    task = run.tasks[0]
    before = kernel.store.path.read_bytes()
    view = await service.get_task_loop_runtime(run.id, task.id, owner_id="owner")
    assert view.binding_source == "CHECKPOINT"
    assert view.runtime.family == "OPENCODE"
    assert view.execution_unified_with_harness is False
    assert not any(s in view.model_dump_json() for s in (str(repository), "prompt", "def add", "payloads", "stderr"))
    with pytest.raises(AdlcRunNotFoundError):
        await service.get_task_loop_runtime(run.id, task.id, owner_id="foreign")
    from langflow.adlc.executor_router import TaskExecutorRouter
    from langflow.adlc.mock_executor import MockExecutor
    from langflow.adlc.run_repository import SqliteRunRepository
    from langflow.adlc.run_service import AdlcRunService

    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor()), repository=SqliteRunRepository(tmp_path / "runs.sqlite3")
    )
    assert await restored.get_task_loop_runtime(run.id, task.id, owner_id="owner") == view
    assert kernel.store.path.read_bytes() == before
    assert len(kernel.client.sessions) == 2


@pytest.mark.parametrize("value", [True, -1, "1", 1.5])
def test_usage_counts_are_strict(value):
    with pytest.raises(ValidationError):
        LoopRuntimeUsage(input_tokens=value, output_tokens=0, total_tokens=10, cost=0.0)


def test_command_and_outcome_schema_roundtrip_has_no_opencode_types(repository):
    spec = _spec(repository)
    from langflow.adlc.task_loop_live_models import LiveLoopCandidate

    parent = LiveLoopCandidate(
        candidate_id=uuid4(),
        parent_candidate_id=None,
        iteration=0,
        base_commit=spec.base_commit,
        changes={},
        content_digest=LiveLoopCandidate.digest(spec.base_commit, {}),
    )
    runtime = FixtureRuntime()
    command = LoopIterationRequest(
        runtime=runtime.binding,
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        request_id=uuid4(),
        iteration=1,
        policy_digest="sha256:" + "1" * 64,
        specification=spec,
        parent_candidate=parent,
        mode="WORKSPACE_EDIT",
        prompt="Full input",
        system="One iteration",
        timeout_ms=1000,
    )
    assert LoopIterationRequest.model_validate_json(command.model_dump_json()) == command
    assert command.content_digest == sha256_digest(command.model_dump(mode="json"))
    assert "OpenCode" not in json.dumps(LoopIterationRequest.model_json_schema())
    with pytest.raises(ValidationError):
        LoopIterationRequest.model_validate({**command.model_dump(), "api_key": "not-allowed"})


def remove_protocol_sidecars(store):
    """Simulate pre-protocol private rows, without modifying their original execution policy."""
    with sqlite3.connect(store.path) as connection:
        for read_sql, write_sql, field in (
            (
                "SELECT rowid,payload FROM task_loop_states",
                "UPDATE task_loop_states SET payload=?,digest=? WHERE rowid=?",
                "runtime_binding",
            ),
            (
                "SELECT rowid,payload FROM task_loop_attempts",
                "UPDATE task_loop_attempts SET payload=?,digest=? WHERE rowid=?",
                "runtime_checkpoint",
            ),
        ):
            for rowid, payload in connection.execute(read_sql).fetchall():
                data = json.loads(payload)
                data.pop(field, None)
                connection.execute(
                    write_sql,
                    (json.dumps(data), sha256_digest(data), rowid),
                )


@pytest.mark.parametrize("phase", ["CANDIDATE_CAPTURED", "VERIFIED"])
async def test_legacy_checkpoint_recovers_original_proof_without_a_new_session(
    repository, tmp_path, monkeypatch, phase
):
    client = Client(steps=({**FIX, **FINISH},))
    runtime = OpenCodeTaskLoopRuntime(client)
    kernel = executor(tmp_path, repository, runtime)
    request = _request(_spec(repository))
    if phase == "VERIFIED":

        def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.store, "finish", crash)
    else:

        async def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.verifier, "verify", crash)
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    remove_protocol_sidecars(kernel.store)
    restored = executor(tmp_path, repository, OpenCodeTaskLoopRuntime(client))
    assert inspect_runtime(restored.store, request).binding_source == "LEGACY"
    result = await restored.resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.metadata["task_loop"]["runtime_protocol"] is None
    assert len(client.sessions) == 1


async def test_legacy_loop_can_pin_original_adapter_at_a_new_iteration_without_rewriting_old_attempt(
    repository, tmp_path
):
    client = Client()
    kernel = executor(tmp_path, repository, OpenCodeTaskLoopRuntime(client))
    spec = _spec(repository)
    first = _request(spec)
    await kernel.execute(first, _ignore)
    remove_protocol_sidecars(kernel.store)
    with sqlite3.connect(kernel.store.path) as connection:
        original = connection.execute("SELECT payload,digest FROM task_loop_attempts").fetchone()
    second = _request(spec, first)
    result = await executor(tmp_path, repository, OpenCodeTaskLoopRuntime(client)).execute(second, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert inspect_runtime(kernel.store, second).binding_source == "CHECKPOINT"
    with sqlite3.connect(kernel.store.path) as connection:
        preserved = connection.execute(
            "SELECT payload,digest FROM task_loop_attempts WHERE attempt_id=?", (str(first.attempt_id),)
        ).fetchone()
    assert preserved == original
    assert len(client.sessions) == 2


async def test_legacy_checkpoint_cannot_be_adopted_by_another_runtime(repository, tmp_path):
    kernel = executor(tmp_path, repository, OpenCodeTaskLoopRuntime(Client()))
    spec = _spec(repository)
    first = _request(spec)
    await kernel.execute(first, _ignore)
    remove_protocol_sidecars(kernel.store)
    fixture = FixtureRuntime()
    result = await executor(tmp_path, repository, fixture).execute(_request(spec, first), _ignore)
    assert result.error.code == "TASK_LOOP_LEGACY_RUNTIME_INCOMPATIBLE"
    assert not fixture.opened


async def test_runtime_endpoint_authorizes_owner_and_is_read_only(repository, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from langflow.api.v1 import adlc as adlc_api
    from langflow.services.auth.utils import get_current_active_user

    service, kernel, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="owner", username="owner")
    endpoint = f"/api/v1/adlc/runs/{run.id}/tasks/{run.tasks[0].id}/task-loop-runtime"
    before = kernel.store.path.read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        read = await client.get(endpoint)
        assert read.status_code == 200
        assert read.json()["runtime"]["family"] == "OPENCODE"
        assert read.json()["execution_unified_with_harness"] is False
        app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="foreign", username="foreign")
        assert (await client.get(endpoint)).status_code == 404
    assert kernel.store.path.read_bytes() == before
    assert len(kernel.client.sessions) == 2

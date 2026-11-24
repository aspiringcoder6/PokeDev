"""Slice C reads real checkpoints and exercises operator controls; providers are simulated."""
# ruff: noqa: INP001, PLR2004, S101, PLC0414, F811

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, CreateWorkflowRunRequest, WorkflowRunStatus
from langflow.adlc.opencode_client import OpenCodeClientError
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunService, AdlcRunStateError
from langflow.adlc.task_loop import TASK_LOOP_MOCK_SERVICE, MockTaskLoopExecutor
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE, LiveTaskLoopExecutor
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from scripts.demo_adlc_task_loop import demo_definitions
from scripts.demo_adlc_task_loop_live import live_definitions
from tests.unit.adlc.test_coding_agent import (
    ProposalClient,
    contract_for,
    executor_for,
    request_for,
)
from tests.unit.adlc.test_coding_agent import (
    contracts as contracts,
)
from tests.unit.adlc.test_coding_agent import (
    spec as spec,
)
from tests.unit.adlc.test_task_loop_live import (
    FIX,
    Client,
    LoseCallback,
    _ignore,
    _spec,
    _wait_status,
)
from tests.unit.adlc.test_task_loop_live import (
    repository as repository,
)


async def start_live(tmp_path, repository, monkeypatch, *, client=None, executor_wrapper=None, **policy):
    state_root = tmp_path / "loop-state"
    monkeypatch.setenv("ADLC_TASK_LOOP_STATE_ROOT", str(state_root))
    executor = LiveTaskLoopExecutor(
        workspace=TaskLoopWorkspace(repository, tmp_path / "worktrees"),
        store=TaskLoopStore(state_root / "task-loop.sqlite3"),
        client=client or Client(),
    )
    definitions = live_definitions(_spec(repository, **policy))[1]
    definitions[0].constraints["retry_backoff_ms"] = 0
    service = AdlcRunService(
        TaskExecutorRouter(
            MockExecutor(),
            routes={TASK_LOOP_LIVE_SERVICE: executor_wrapper(executor) if executor_wrapper else executor},
        ),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Operator timeline",
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    return service, executor, run


async def test_complete_timeline_and_earlier_patches_are_scoped_read_only(repository, tmp_path, monkeypatch):
    service, executor, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    task = run.tasks[0]
    before = executor.store.path.read_bytes()
    view = await service.get_task_loop(run.id, task.id, owner_id="owner")
    assert view.history_complete
    assert view.history_source == "CHECKPOINT"
    assert [item.status for item in view.iterations] == ["CHECKS_FAILED", "PASSED"]
    assert len({item.session_id for item in view.iterations}) == 2
    assert view.iterations[1].parent_candidate_id == view.iterations[0].candidate_id
    assert view.iterations[1].checks[0].executed_tests == 3
    assert view.current_candidate_digest == task.pending_result.metadata["task_loop"]["candidate_digest"]
    assert view.total_tokens == 36
    assert view.total_cost == pytest.approx(0.2)
    assert view.stopped
    assert not view.can_retry
    for item in view.iterations:
        patch = await service.get_source_patch(run.id, item.patch_artifact_id, owner_id="owner")
        assert patch.artifact.metadata["candidate_digest"] == item.candidate_digest
        assert patch.artifact.task_run_id == task.id
    assert executor.store.path.read_bytes() == before
    assert len(executor.client.prompts) == 2
    serialized = view.model_dump_json()
    for private in (str(repository), "def add", "TRACE_ONLY_NOT_FEEDBACK", "argv", "stderr", "payloads", "prompt"):
        assert private not in serialized
    reviewed = run.approval_requests[0].context.payload["reviewed_candidates"]
    assert reviewed[0]["candidate_id"] == str(view.current_candidate_id)
    assert reviewed[0]["artifact_id"] == str(view.iterations[-1].patch_artifact_id)


async def test_restart_and_disabled_provider_keep_the_full_timeline(repository, tmp_path, monkeypatch):
    service, executor, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    task = run.tasks[0]
    original = await service.get_task_loop(run.id, task.id, owner_id="owner")
    monkeypatch.setenv("ADLC_TASK_LOOP_OPENCODE_ENABLED", "false")
    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor()),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    view = await restored.get_task_loop(run.id, task.id, owner_id="owner")
    assert view == original
    assert len(executor.client.sessions) == 2
    older = await restored.get_source_patch(run.id, view.iterations[0].patch_artifact_id, owner_id="owner")
    assert older.artifact.metadata["candidate_id"] == str(view.iterations[0].candidate_id)
    controls = await restored.get_operator_controls(run.id, owner_id="owner")
    assert not controls.can_pause
    assert not controls.can_resume
    assert controls.can_cancel
    rejected = await restored.reject(
        run.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(id="owner", type="USER"),
        comment="Improve the tools in an explicit successor run.",
    )
    assert rejected.status is WorkflowRunStatus.FAILED
    assert rejected.tasks[0].artifacts == run.tasks[0].artifacts
    assert rejected.approval_requests[0].decision.comment == "Improve the tools in an explicit successor run."


async def test_stalled_loop_has_recurring_findings_and_cannot_retry_or_resume(repository, tmp_path, monkeypatch):
    client = Client(steps=({},))
    service, _, started = await start_live(tmp_path, repository, monkeypatch, client=client)
    run = await _wait_status(service, started.id, WorkflowRunStatus.PAUSED)
    task = run.tasks[0]
    view = await service.get_task_loop(run.id, task.id, owner_id="owner")
    assert view.stop_reason == "TASK_LOOP_STALLED"
    assert view.stopped
    assert not view.can_retry
    assert view.failure_patterns[0].iterations == (1, 2)
    assert view.failure_patterns[0].kind == "BEHAVIORAL"
    assert not (await service.get_operator_controls(run.id, owner_id="owner")).can_resume
    with pytest.raises(AdlcRunStateError, match="start a new run"):
        await service.retry_task(task.id, owner_id="owner")
    with pytest.raises(AdlcRunStateError, match="successor run"):
        await service.resume_run(run.id, owner_id="owner")
    assert len(client.prompts) == 2
    assert (await service.get_tasks(run.id, owner_id="owner"))[0].retry_count == task.retry_count


async def test_pause_finishes_one_iteration_and_resume_starts_a_fresh_session(repository, tmp_path, monkeypatch):
    client = Client()
    client.release = asyncio.Event()
    service, executor, started = await start_live(tmp_path, repository, monkeypatch, client=client)
    await asyncio.wait_for(client.entered.wait(), 10)
    running = await service.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert len(running.iterations) == 1
    assert running.iterations[0].phase == "AGENT_RUNNING"
    assert running.iterations[0].checks == ()
    assert running.iterations[0].candidate_id is None
    await service.pause_run(started.id, owner_id="owner", actor=Actor(id="owner", type="USER"))
    pending = await service.get_operator_controls(started.id, owner_id="owner")
    assert pending.pause_requested
    assert not pending.can_pause
    assert not pending.can_resume
    client.release.set()
    await _wait_status(service, started.id, WorkflowRunStatus.PAUSED)
    paused = await service.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert len(paused.iterations) == 1
    assert not paused.can_retry
    assert (await service.get_operator_controls(started.id, owner_id="owner")).can_resume
    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor()),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    historical = await restored.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert historical.history_complete
    assert len(historical.iterations) == 1
    assert len(client.sessions) == 1
    assert not (await restored.get_operator_controls(started.id, owner_id="owner")).can_resume
    await service.resume_run(started.id, owner_id="owner")
    await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert len(client.sessions) == 2


async def test_cancel_records_the_incomplete_iteration_without_dispatching_more_work(repository, tmp_path, monkeypatch):
    client = Client()
    client.release = asyncio.Event()
    service, executor, started = await start_live(tmp_path, repository, monkeypatch, client=client)
    await asyncio.wait_for(client.entered.wait(), 10)
    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: executor}),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    schedule = Mock(side_effect=AssertionError("Inspection must not schedule recovery"))
    monkeypatch.setattr(restored, "_start_background", schedule)
    observed = await restored.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert observed.iterations[0].phase == "AGENT_RUNNING"
    assert not schedule.called
    assert len(client.sessions) == 1
    assert client.aborted == []
    await service.cancel_run(started.id, owner_id="owner", actor=Actor(id="owner", type="USER"))
    view = await service.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert view.stopped
    assert view.stop_reason == "TASK_LOOP_CANCELLED"
    assert not view.can_retry
    assert view.iterations[0].status == "CANCELLED"
    assert view.iterations[0].checks == ()
    controls = await service.get_operator_controls(started.id, owner_id="owner")
    assert not controls.can_pause
    assert not controls.can_resume
    assert not controls.can_cancel
    assert len(client.sessions) == 1
    assert client.aborted


async def test_corrupt_history_is_explicitly_partial_and_never_enables_controls(repository, tmp_path, monkeypatch):
    service, executor, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    task = run.tasks[0]
    with sqlite3.connect(executor.store.path) as connection:
        connection.execute("DELETE FROM task_loop_attempts WHERE json_extract(payload, '$.iteration')=1")
    view = await service.get_task_loop(run.id, task.id, owner_id="owner")
    assert not view.history_complete
    assert not view.can_retry
    assert view.history_source == "RUN_SNAPSHOT"
    assert view.unavailable_reason
    assert len(view.iterations) == 1
    assert view.iterations[0].iteration == 2
    assert "def add" not in view.model_dump_json()


async def test_owner_and_run_task_pair_are_checked_before_any_checkpoint_read(repository, tmp_path, monkeypatch):
    service, executor, started = await start_live(tmp_path, repository, monkeypatch)
    run = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    read = AsyncMock(wraps=executor.inspect_loop)
    monkeypatch.setattr(executor, "inspect_loop", read)
    for owner, task_id in (("other-owner", run.tasks[0].id), ("owner", uuid4())):
        with pytest.raises(AdlcRunNotFoundError):
            await service.get_task_loop(run.id, task_id, owner_id=owner)
    assert read.await_count == 0
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="owner", username="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/adlc/runs/{run.id}/tasks/{run.tasks[0].id}/task-loop")
        assert response.status_code == 200
        assert response.json()["history_complete"]
        controls = await client.get(f"/api/v1/adlc/runs/{run.id}/controls")
        assert controls.status_code == 200
        assert controls.json()["can_cancel"]
        app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="outsider", username="outsider")
        hidden = await client.get(f"/api/v1/adlc/runs/{run.id}/tasks/{run.tasks[0].id}/task-loop")
        assert hidden.status_code == 404
        assert read.await_count == 1


async def test_mock_timeline_keeps_mock_evidence_and_unknown_usage():
    workflow, definitions = demo_definitions()
    definitions[0].constraints["retry_backoff_ms"] = 0
    executor = MockTaskLoopExecutor()
    service = AdlcRunService(TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_MOCK_SERVICE: executor}))
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name=workflow.name,
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    view = await service.get_task_loop(run.id, run.tasks[0].id, owner_id="owner")
    assert view.mode == "MOCK"
    assert view.history_source == "MEMORY"
    assert [item.status for item in view.iterations] == ["CHECKS_FAILED", "CHECKS_FAILED", "PASSED"]
    assert view.total_tokens is None
    assert view.total_cost is None
    assert all(check.kind == "MOCK" for item in view.iterations for check in item.checks)
    assert all(item.total_tokens is None and item.cost is None for item in view.iterations)


async def test_combined_contract_and_behavioral_checks_share_the_exact_candidate(
    contracts,
    spec,
    repository,
    tmp_path,
    monkeypatch,
):
    contract = contract_for(contracts)
    client = ProposalClient(steps=(FIX, {"README.md": "Use add(a, b).\n"}))
    executor = executor_for(tmp_path, repository, client)
    first = request_for(spec, contract)
    await executor.execute(first, _ignore)
    second = request_for(spec, contract, previous=first)
    result = await executor.execute(second, _ignore)
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    view = await executor.inspect_loop(second)
    assert view.stopped
    assert view.stop_reason == "CHECKS_PASSED"
    assert view.current_candidate_digest == result.output["outputs"]["contract_verification_report"]["candidate_digest"]
    assert {check.kind for check in view.iterations[-1].checks} == {"BEHAVIORAL", "CONTRACT"}
    assert all(check.passed for check in view.iterations[-1].checks)
    assert any(check.label == "Patch contains changes" for check in view.iterations[-1].checks)
    assert "PRIVATE_FILE_MUST_NOT_REACH_MODEL" not in view.model_dump_json()
    assert len(client.sessions) == 2


def test_missing_read_only_store_is_not_created(tmp_path):
    missing = tmp_path / "does-not-exist" / "loops.sqlite3"
    store = TaskLoopStore(missing, initialize=False)
    with pytest.raises(sqlite3.OperationalError):
        store.inspect(SimpleNamespace(workflow_run_id=uuid4(), task_run_id=uuid4()))
    assert not missing.exists()
    assert not missing.parent.exists()


async def test_disabled_runtime_keeps_failed_history_but_cannot_allocate_a_retry(repository, tmp_path, monkeypatch):
    client = Client()
    monkeypatch.setattr(
        client,
        "prompt",
        AsyncMock(
            side_effect=OpenCodeClientError(code="OPENCODE_SERVER_UNAVAILABLE", category="DEPENDENCY", retryable=True)
        ),
    )
    service, executor, started = await start_live(tmp_path, repository, monkeypatch, client=client)
    run = await _wait_status(service, started.id, WorkflowRunStatus.PAUSED)
    original = await service.get_task_loop(run.id, run.tasks[0].id, owner_id="owner")
    assert original.can_retry
    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor()),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    view = await restored.get_task_loop(run.id, run.tasks[0].id, owner_id="owner")
    assert view.history_complete
    assert not view.can_retry
    assert len(view.iterations) == 1
    with pytest.raises(AdlcRunStateError, match="runtime is unavailable"):
        await restored.retry_task(run.tasks[0].id, owner_id="owner")
    after = await restored.get_tasks(run.id, owner_id="owner")
    assert after[0].retry_count == run.tasks[0].retry_count
    assert after[0].current_attempt_id == run.tasks[0].current_attempt_id
    assert len(client.sessions) == 1


async def test_lost_callback_can_recover_the_recorded_candidate_without_another_session(
    repository, tmp_path, monkeypatch
):
    from tests.unit.adlc.test_task_loop_live import FINISH

    service, executor, started = await start_live(
        tmp_path,
        repository,
        monkeypatch,
        client=Client(steps=({**FIX, **FINISH},)),
        executor_wrapper=LoseCallback,
    )
    run = await _wait_status(service, started.id, WorkflowRunStatus.PAUSED)
    view = await service.get_task_loop(run.id, run.tasks[0].id, owner_id="owner")
    assert view.can_retry
    assert view.recovery_available
    assert view.iterations[-1].status == "PASSED"
    original = run.tasks[0].current_attempt_id
    await service.retry_task(run.tasks[0].id, owner_id="owner")
    recovered = await _wait_status(service, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert recovered.tasks[0].current_attempt_id == original
    assert len(executor.client.sessions) == 1


async def test_expired_wall_clock_budget_disables_resume_before_another_model_call(repository, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from langflow.adlc.task_loop_live_models import LiveLoopState

    client = Client()
    client.release = asyncio.Event()
    service, executor, started = await start_live(tmp_path, repository, monkeypatch, client=client)
    await asyncio.wait_for(client.entered.wait(), 10)
    await service.pause_run(started.id, owner_id="owner", actor=Actor(id="owner", type="USER"))
    client.release.set()
    await _wait_status(service, started.id, WorkflowRunStatus.PAUSED)
    with sqlite3.connect(executor.store.path) as connection:
        row = connection.execute("SELECT payload FROM task_loop_states").fetchone()
        state = LiveLoopState.model_validate_json(row[0]).model_copy(
            update={
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=610),
            }
        )
        connection.execute(
            "UPDATE task_loop_states SET payload=?, digest=?",
            (
                state.model_dump_json(),
                sha256_digest(state.model_dump(mode="json")),
            ),
        )
    view = await service.get_task_loop(started.id, started.tasks[0].id, owner_id="owner")
    assert view.stopped
    assert view.stop_reason == "TASK_LOOP_TIME_BUDGET_EXHAUSTED"
    assert not (await service.get_operator_controls(started.id, owner_id="owner")).can_resume
    with pytest.raises(AdlcRunStateError, match="successor run"):
        await service.resume_run(started.id, owner_id="owner")
    assert len(client.sessions) == 1

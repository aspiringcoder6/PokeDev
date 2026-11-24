# ruff: noqa: INP001, PLR2004, S101, S106

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langflow.adlc import harness_attempts, run_repository
from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore, SourcePatchSnapshot
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.harness_attempts import InMemoryTaskAttemptRepository, SqliteTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver, HarnessCallbackSettings, sign_harness_delivery
from langflow.adlc.harness_client import HarnessClientError
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.harness_models import (
    HarnessInteractionReceipt,
    HarnessInteractionRecord,
    HarnessInteractionStatus,
    HarnessResultDelivery,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionReceipt,
)
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    GateType,
    MockArtifactSpec,
    PlanTaskTraceability,
    TaskResultStatus,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.adlc.run_repository import (
    InMemoryRunRepository,
    RunRepositoryError,
    SqliteRunRepository,
    create_run_repository_from_environment,
)
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user


def _definition(*, harness=False, gate=False) -> AdlcTaskDefinition:
    return AdlcTaskDefinition(
        id=uuid4(),
        key="inspect",
        name="Read-only report",
        task_type="coding",
        dependencies=[],
        predetermined_output={"summary": "persisted report"},
        artifact=MockArtifactSpec(kind="DOCUMENT", name="report.md", media_type="text/markdown", content="report"),
        approval_gate=GateType.AFTER_TASK if gate else None,
        executor_target=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task")
        if harness
        else None,
        constraints={"timeout_ms": 30_000},
        request_metadata={"resolved_configuration": {"submission_mode": "MANUAL", "plugin_lock": []}},
    )


async def _start(service, *, owner="owner", definition=None, flow_id=None, plan_id=None):
    flow_id = flow_id or uuid4()
    return await service.start_run(
        flow_id=flow_id,
        flow_name="Recovery test",
        definitions=[definition or _definition()],
        request=CreateWorkflowRunRequest(
            flowId=flow_id, executionMode="EXECUTION_PLAN" if plan_id else "LEGACY_FLOW", delayMs=0
        ),
        owner_id=owner,
        execution_plan_id=plan_id,
    )


async def _until_status(service, run_id, expected):
    async def wait():
        while True:
            run = await service.get_run(run_id, owner_id="owner")
            if run.status is expected:
                return run
            await asyncio.sleep(0.005)

    return await asyncio.wait_for(wait(), timeout=5)


def _callbacks(tmp_path):
    return HarnessCallbackReceiver(
        HarnessCallbackSettings(secret="test-callback-secret"),
        attempts=SqliteTaskAttemptRepository(tmp_path / "attempts.sqlite3"),
        clock=lambda: 1_700_000_000,
    )


def _harness_service(tmp_path, callbacks, client=None):
    default = MockExecutor()
    routes = {}
    if client is not None:
        routes[DeepSeekHarnessTaskExecutor.service_name] = DeepSeekHarnessTaskExecutor(
            client, callbacks, status_poll_interval_seconds=0.01
        )
    return AdlcRunService(
        TaskExecutorRouter(default, routes=routes),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        harness_callbacks=callbacks,
    )


class _ManualClient:
    """No model/network calls: one remote session survives a coordinator restart."""

    def __init__(self, callbacks, *, kind="APPROVAL"):
        self.callbacks = callbacks
        self.request = None
        self.create_calls = 0
        self.get_calls = 0
        self.cancel_calls = 0
        self.submit_calls = 0
        self.response_calls = 0
        self.status = HarnessSessionStatus.WAITING_INTERACTION
        self.unavailable = False
        self.mismatched = False
        self.created_at = datetime.now(timezone.utc)
        self.interaction = HarnessInteractionRecord(
            interaction_id=uuid4(),
            kind=kind,
            status="PENDING",
            title="Confirm the report",
            prompt="Return the read-only report?",
            input_schema={"type": "object"},
            requested_at=self.created_at,
        )
        self.result = None
        self.delivery = None

    def session(self):
        correlation = self.request.correlation
        if self.mismatched:
            correlation = correlation.model_copy(update={"attempt_id": uuid4()})
        return HarnessSessionRead(
            session_id="existing-session",
            correlation=correlation,
            idempotency_key=self.request.idempotency_key,
            status=self.status,
            submission_mode="MANUAL",
            interactions=[self.interaction],
            result=self.result,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    async def create_session(self, request):
        self.create_calls += 1
        self.request = request
        return HarnessSessionAccepted(session=self.session())

    async def get_session(self, session_id):
        assert session_id == "existing-session"
        self.get_calls += 1
        if self.unavailable:
            code = "HARNESS_SESSION_NOT_FOUND"
            raise HarnessClientError(code)
        return self.session()

    async def respond_to_interaction(self, session_id, interaction_id, command):
        assert session_id == "existing-session"
        assert interaction_id == str(self.interaction.interaction_id)
        self.response_calls += 1
        self.interaction = self.interaction.model_copy(
            update={
                "status": HarnessInteractionStatus.SUBMITTED,
                "response": command.response,
                "resolved_at": datetime.now(timezone.utc),
            }
        )
        self.status = HarnessSessionStatus.READY_FOR_SUBMISSION
        self.result = self.make_result()
        return HarnessInteractionReceipt(session_id=session_id, interaction=self.interaction, status=self.status)

    def make_result(self):
        return HarnessSessionResult(
            session_id="existing-session",
            correlation=self.request.correlation,
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "Report survives restart", "outputs": {"files_changed": []}},
            artifacts=[],
            error=None,
            interaction_records=[self.interaction],
            metadata={"driver": {"provider": "my-codex", "model": "cx/gpt-5.6-luna"}},
            started_at=self.created_at,
            completed_at=datetime.now(timezone.utc),
        )

    async def deliver(self):
        self.result = self.result or self.make_result()
        self.status = HarnessSessionStatus.SUCCEEDED
        self.delivery = self.delivery or HarnessResultDelivery(
            delivery_id=uuid4(), callback_ref="adlc-primary", created_at=datetime.now(timezone.utc), result=self.result
        )
        body = self.delivery.model_dump_json().encode()
        return await self.callbacks.receive(
            body,
            delivery_id=str(self.delivery.delivery_id),
            timestamp="1700000000",
            signature=sign_harness_delivery("test-callback-secret", "1700000000", body),
        )

    async def submit_session(self, session_id):
        assert session_id == "existing-session"
        self.submit_calls += 1
        await self.deliver()
        return HarnessSubmissionReceipt(
            session_id=session_id,
            status=self.status,
            delivery_id=self.delivery.delivery_id,
            delivery_status="DELIVERED",
        )

    async def cancel_session(self, _session_id):
        self.cancel_calls += 1


async def test_completed_run_and_owner_scoped_history_survive_restart(tmp_path):
    path = tmp_path / "runs.sqlite3"
    service = AdlcRunService(repository=SqliteRunRepository(path))
    first = await _start(service)
    second = await _start(service)
    await _start(service, owner="other-owner")
    await service.shutdown()

    restored = AdlcRunService(repository=SqliteRunRepository(path))
    report = await restored.recover()
    assert report.inspected == 3
    assert report.reattached == 0
    assert (await restored.get_run(first.id, owner_id="owner")) == first
    assert (await restored.get_tasks(first.id, owner_id="owner")) == first.tasks
    assert (await restored.get_events(first.id, owner_id="owner")) == first.events
    page = await restored.list_runs(owner_id="owner", limit=1)
    assert page.total == 2
    assert page.runs[0].id == second.id
    assert page.runs[0].completed_task_count == 1
    assert page.runs[0].updated_at == second.events[-1].occurred_at
    assert "tasks" not in page.runs[0].model_dump()
    assert "owner_id" not in page.runs[0].model_dump()
    assert (await restored.list_runs(owner_id="owner", offset=1, limit=1)).runs[0].id == first.id
    assert (await restored.list_runs(owner_id="owner", status=WorkflowRunStatus.RUNNING)).total == 0
    assert (await restored.list_runs(owner_id="owner", flow_id=first.flow_id)).total == 1
    with pytest.raises(AdlcRunNotFoundError):
        await restored.get_run(first.id, owner_id="other-owner")
    await restored.shutdown()


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_lifecycle_approval_is_restored_and_decided_once(tmp_path, action):
    path = tmp_path / "runs.sqlite3"
    first_service = AdlcRunService(repository=SqliteRunRepository(path))
    original = await _start(first_service, definition=_definition(gate=True))
    approval = original.approval_requests[0]
    await first_service.shutdown()
    spy = MockExecutor()
    spy.execute = AsyncMock(side_effect=AssertionError("Recovery must not re-execute approved work."))
    restored = AdlcRunService(spy, repository=SqliteRunRepository(path))
    report = await restored.recover()
    assert report.restored_approvals == 1
    assert report.reattached == 0
    assert await restored.get_run(original.id, owner_id="owner") == original
    decided = await getattr(restored, action)(
        approval.approval_request_id, owner_id="owner", actor=Actor(type="USER", id="owner"), comment="Reviewed."
    )
    expected_status = WorkflowRunStatus.SUCCEEDED if action == "approve" else WorkflowRunStatus.FAILED
    assert decided.status is expected_status
    assert decided.tasks[0].current_attempt_id == original.tasks[0].current_attempt_id
    assert decided.approval_requests[0].decision.comment == "Reviewed."
    spy.execute.assert_not_awaited()
    await restored.shutdown()
    reopened = AdlcRunService(repository=SqliteRunRepository(path))
    await reopened.recover()
    assert await reopened.get_run(original.id, owner_id="owner") == decided
    assert [event.sequence for event in decided.events] == list(range(1, len(decided.events) + 1))
    event_type = "approval_request.approved" if action == "approve" else "approval_request.rejected"
    assert sum(event.event_type == event_type for event in decided.events) == 1
    await reopened.shutdown()


async def test_recovery_repairs_a_crash_between_task_approval_and_workflow_waiting(tmp_path):
    repository = SqliteRunRepository(tmp_path / "runs.sqlite3")
    original = await _start(AdlcRunService(repository=repository), definition=_definition(gate=True))
    snapshot = repository.load_all()[0]
    snapshot.run.status = WorkflowRunStatus.RUNNING
    repository.save(snapshot)
    restored = AdlcRunService(repository=SqliteRunRepository(repository.path))
    await restored.recover()
    run = await restored.get_run(original.id, owner_id="owner")
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert run.approval_requests == original.approval_requests
    decided = await restored.approve(
        run.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment=None,
    )
    assert decided.status is WorkflowRunStatus.SUCCEEDED
    await restored.shutdown()


async def test_source_patch_under_pending_review_survives_restart(tmp_path):
    path = tmp_path / "runs.sqlite3"
    definition = _definition(gate=True)
    source = SourcePatchSnapshot(
        format="opencode-vcs-diff-v1",
        files=[{"file": "README.md", "patch": "@@ -1 +1 @@\n-old\n+new", "additions": 1, "deletions": 1}],
        reported_files=["README.md"],
    )
    definition.artifact = MockArtifactSpec(
        kind="SOURCE_PATCH", name="patch.json", media_type="application/json", content=source.model_dump_json()
    )
    payloads = BoundedArtifactPayloadStore(database_path=path)
    first = AdlcRunService(repository=SqliteRunRepository(path), artifact_payloads=payloads)
    original = await _start(first, definition=definition)
    artifact = original.tasks[0].artifacts[0]
    payloads.retain(artifact, source.model_dump_json().encode())
    await first.shutdown()
    restored = AdlcRunService(
        repository=SqliteRunRepository(path), artifact_payloads=BoundedArtifactPayloadStore(database_path=path)
    )
    await restored.recover()
    read = await restored.get_source_patch(original.id, artifact.artifact_id, owner_id="owner")
    assert read.files == source.files
    assert read.artifact == artifact
    with pytest.raises(AdlcRunNotFoundError):
        await restored.get_source_patch(original.id, artifact.artifact_id, owner_id="someone-else")
    final = await restored.approve(
        original.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment=None,
    )
    assert final.status is WorkflowRunStatus.SUCCEEDED
    await restored.shutdown()


async def test_interrupted_nonresumable_executor_requires_explicit_retry(tmp_path):
    path = tmp_path / "runs.sqlite3"
    waiting = asyncio.Event()
    executor = MockExecutor()

    async def interrupted_execute(_request, on_state_change):
        await on_state_change(TaskRunStatus.RUNNING, None)
        waiting.set()
        await asyncio.Event().wait()

    executor.execute = interrupted_execute
    first = AdlcRunService(executor, repository=SqliteRunRepository(path))
    interrupted = asyncio.create_task(_start(first))
    await asyncio.wait_for(waiting.wait(), timeout=5)
    interrupted.cancel()
    await asyncio.gather(interrupted, return_exceptions=True)
    await first.shutdown()
    original = SqliteRunRepository(path).load_all()[0].run
    delegate = MockExecutor()
    execute = delegate.execute
    delegate.execute = AsyncMock(wraps=execute)
    restored = AdlcRunService(delegate, repository=SqliteRunRepository(path))
    await restored.recover()
    paused = await _until_status(restored, original.id, WorkflowRunStatus.PAUSED)
    assert paused.tasks[0].result.error.code == "ADLC_RECOVERY_REQUIRES_RETRY"
    delegate.execute.assert_not_awaited()
    await asyncio.gather(*restored._background_runs)  # noqa: SLF001 - finish recovery before the explicit command.
    final = await restored.retry_task(paused.tasks[0].id, owner_id="owner")
    assert final.status is WorkflowRunStatus.SUCCEEDED
    assert final.id == original.id
    assert final.tasks[0].current_attempt_id != original.tasks[0].current_attempt_id
    assert final.tasks[0].retry_count == 1
    delegate.execute.assert_awaited_once()
    await restored.shutdown()


@pytest.mark.parametrize("kind", ["FORM", "APPROVAL"])
async def test_restart_reattaches_same_interaction_then_manual_submit_via_adlc(tmp_path, kind):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks, kind=kind)
    first = _harness_service(tmp_path, callbacks, client)
    original = await _start(first, definition=_definition(harness=True))
    waiting = await _until_status(first, original.id, WorkflowRunStatus.WAITING_APPROVAL)
    request = waiting.tasks[0].request.model_copy(deep=True)
    await first.shutdown()
    assert client.cancel_calls == 0

    callbacks = _callbacks(tmp_path)
    client.callbacks = callbacks
    restored = _harness_service(tmp_path, callbacks, client)
    report = await restored.recover()
    assert report.reattached == 1
    assert (await restored.recover()).inspected == 0
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="owner")
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: restored
    app.dependency_overrides[adlc_api.get_harness_callback_receiver] = lambda: callbacks
    app.dependency_overrides[adlc_api.get_harness_client] = lambda: client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        sessions = await http.get(f"/api/v1/adlc/runs/{original.id}/harness-sessions")
        assert sessions.status_code == 200
        assert sessions.json()[0]["session"]["interactions"][0]["interaction_id"] == str(
            client.interaction.interaction_id
        )
        assert sessions.json()[0]["attempt_id"] == str(request.attempt_id)
        response_path = (
            f"/api/v1/adlc/runs/{original.id}/harness-sessions/existing-session"
            f"/interactions/{client.interaction.interaction_id}/responses"
        )
        response = await http.post(
            response_path,
            json={"schema_version": "0.1", "response": {"action": "approve", "confirm": True}},
        )
        assert response.status_code == 202
        assert client.submit_calls == 0  # MANUAL stays manual through restart.
        submission = await http.post(
            f"/api/v1/adlc/runs/{original.id}/harness-sessions/existing-session/submit", json={}
        )
        assert submission.status_code == 202
        final = await _until_status(restored, original.id, WorkflowRunStatus.SUCCEEDED)
        assert final.tasks[0].request == request
        assert final.tasks[0].current_attempt_id == request.attempt_id
        assert final.tasks[0].retry_count == 0
        assert client.create_calls == 1
        assert client.cancel_calls == 0
        archive = await http.get(f"/api/v1/adlc/runs/{original.id}/harness-results")
        assert archive.json()[0]["result"] == client.result.model_dump(mode="json")
    await restored.shutdown()


async def test_accepted_callback_during_downtime_finishes_run_offline_once(tmp_path):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks)
    first = _harness_service(tmp_path, callbacks, client)
    original = await _start(first, definition=_definition(harness=True, gate=True))
    await _until_status(first, original.id, WorkflowRunStatus.WAITING_APPROVAL)
    await first.shutdown()
    client.callbacks = _callbacks(tmp_path)
    await client.deliver()
    receipt = await client.deliver()
    assert receipt.duplicate is True
    restored = _harness_service(tmp_path, _callbacks(tmp_path))  # No Harness client/route configured.
    await restored.recover()

    async def wait_for_gate():
        while True:
            run = await restored.get_run(original.id, owner_id="owner")
            if run.approval_requests:
                return run
            await asyncio.sleep(0.005)

    waiting = await asyncio.wait_for(wait_for_gate(), timeout=5)
    assert len(waiting.approval_requests) == 1
    assert waiting.tasks[0].pending_result.output == client.result.output
    assert client.create_calls == 1
    assert client.submit_calls == 0
    # Let the recovery observer finish before deciding the lifecycle gate.
    await asyncio.gather(*restored._background_runs)  # noqa: SLF001 - settle observer before simulating user review.
    final = await restored.approve(
        waiting.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment=None,
    )
    final = await _until_status(restored, final.id, WorkflowRunStatus.SUCCEEDED)
    await restored.shutdown()
    reopened = _harness_service(tmp_path, _callbacks(tmp_path))
    report = await reopened.recover()
    assert report.reattached == 0
    assert (await reopened.get_run(final.id, owner_id="owner")) == final
    assert sum(event.event_type == "task_run.succeeded" for event in final.events) == 1
    assert len(final.approval_requests) == 1
    await reopened.shutdown()


async def test_blueprint_run_keeps_accepted_plan_traceability_without_planning_service(tmp_path):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks)
    first = _harness_service(tmp_path, callbacks, client)
    definition = _definition(harness=True)
    trace = PlanTaskTraceability(
        execution_plan_id=uuid4(),
        plan_task_id=uuid4(),
        source_workflow_stage_id=uuid4(),
        resolved_node_spec_id=uuid4(),
        package_id="coding-agent-deepseek-harness",
        package_version="0.2.0",
        package_content_digest="sha256:" + "a" * 64,
        resolved_node_digest="sha256:" + "b" * 64,
    )
    definition.plan_traceability = trace
    original = await _start(first, definition=definition, plan_id=trace.execution_plan_id)
    await _until_status(first, original.id, WorkflowRunStatus.WAITING_APPROVAL)
    await first.shutdown()
    client.callbacks = _callbacks(tmp_path)
    await client.deliver()
    restored = _harness_service(tmp_path, _callbacks(tmp_path))
    await restored.recover()
    final = await _until_status(restored, original.id, WorkflowRunStatus.SUCCEEDED)
    assert final.execution_plan_id == trace.execution_plan_id
    assert final.tasks[0].plan_traceability == trace
    assert final.tasks[0].request.metadata["plan_traceability"] == trace.model_dump(mode="json")
    assert final.tasks[0].result.metadata["plan_traceability"] == trace.model_dump(mode="json")
    assert (await restored.list_runs(owner_id="owner")).runs[0].execution_plan_id == trace.execution_plan_id
    assert client.create_calls == 1
    await restored.shutdown()


@pytest.mark.parametrize("action", ["restart", "retry"])
async def test_late_callback_after_recovery_failure_is_adopted_without_new_attempt(tmp_path, action):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks)
    first = _harness_service(tmp_path, callbacks, client)
    original = await _start(first, definition=_definition(harness=True))
    waiting = await _until_status(first, original.id, WorkflowRunStatus.WAITING_APPROVAL)
    await first.shutdown()
    callbacks = _callbacks(tmp_path)
    client.callbacks = callbacks
    client.unavailable = True
    restored = _harness_service(tmp_path, callbacks, client)
    await restored.recover()
    await _until_status(restored, original.id, WorkflowRunStatus.PAUSED)
    await asyncio.gather(*restored._background_runs)  # noqa: SLF001 - settle failed observer before the callback.
    await client.deliver()
    if action == "restart":
        await restored.shutdown()
        restored = _harness_service(tmp_path, _callbacks(tmp_path))
        await restored.recover()
    else:
        await restored.retry_task(waiting.tasks[0].id, owner_id="owner")
    final = await _until_status(restored, original.id, WorkflowRunStatus.SUCCEEDED)
    assert final.tasks[0].current_attempt_id == waiting.tasks[0].current_attempt_id
    assert final.tasks[0].request == waiting.tasks[0].request
    assert final.tasks[0].retry_count == 0
    assert client.create_calls == 1
    assert client.cancel_calls == 0
    assert sum(event.event_type == "task_run.succeeded" for event in final.events) == 1
    await restored.shutdown()


@pytest.mark.parametrize("failure", ["missing-session", "correlation", "missing-ledger"])
async def test_unavailable_restart_attempt_pauses_without_replacement_execution(tmp_path, failure):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks)
    first = _harness_service(tmp_path, callbacks, client)
    original = await _start(first, definition=_definition(harness=True))
    await _until_status(first, original.id, WorkflowRunStatus.WAITING_APPROVAL)
    await first.shutdown()
    callbacks = _callbacks(tmp_path)
    client.callbacks = callbacks
    client.unavailable = failure == "missing-session"
    client.mismatched = failure == "correlation"
    if failure == "missing-ledger":
        callbacks.attempts = InMemoryTaskAttemptRepository()
    restored = _harness_service(tmp_path, callbacks, client)
    await restored.recover()
    run = await _until_status(restored, original.id, WorkflowRunStatus.PAUSED)
    assert run.tasks[0].status is TaskRunStatus.FAILED
    assert run.tasks[0].result.error.code in {"HARNESS_RECOVERY_SESSION_UNAVAILABLE", "ADLC_RECOVERY_ATTEMPT_MISSING"}
    assert run.tasks[0].result.error.retryable is True
    assert "No replacement" in run.tasks[0].result.error.message
    assert client.create_calls == 1
    assert client.cancel_calls == 0
    assert client.submit_calls == 0
    await restored.shutdown()


async def test_request_snapshot_is_durable_before_executor_dispatch(tmp_path):
    repository = SqliteRunRepository(tmp_path / "runs.sqlite3")
    executor = MockExecutor()
    execute = executor.execute

    async def fenced_execute(request, on_state_change):
        snapshot = repository.load_all()[0]
        assert snapshot.run.tasks[0].request == request
        assert snapshot.run.tasks[0].current_attempt_id == request.attempt_id
        return await execute(request, on_state_change)

    executor.execute = fenced_execute
    service = AdlcRunService(executor, repository=repository)
    run = await _start(service)
    assert run.status is WorkflowRunStatus.SUCCEEDED
    await service.shutdown()


async def test_frozen_definition_is_detached_from_mutable_caller_configuration(tmp_path):
    callbacks = _callbacks(tmp_path)
    client = _ManualClient(callbacks)
    service = _harness_service(tmp_path, callbacks, client)
    definition = _definition(harness=True)
    run = await _start(service, definition=definition)
    definition.constraints["timeout_ms"] = 1
    definition.request_metadata["resolved_configuration"]["submission_mode"] = "AUTO"
    definition.executor_target.service = "agent-provider:unregistered"
    waiting = await _until_status(service, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    request = waiting.tasks[0].request
    assert request.constraints["timeout_ms"] == 30_000
    assert request.metadata["resolved_configuration"]["submission_mode"] == "MANUAL"
    assert request.executor.service == "agent-provider:deepseek-harness"
    assert client.create_calls == 1
    await service.shutdown()


async def test_snapshot_write_failure_prevents_model_dispatch(tmp_path):
    class FailingRepository(SqliteRunRepository):
        def save(self, record):
            if any(task.request is not None for task in record.run.tasks):
                code = "ADLC_RUN_STORE_UNAVAILABLE"
                raise RunRepositoryError(code)
            super().save(record)

    executor = MockExecutor()
    executor.execute = AsyncMock()
    service = AdlcRunService(executor, repository=FailingRepository(tmp_path / "runs.sqlite3"))
    with pytest.raises(RunRepositoryError, match="ADLC_RUN_STORE_UNAVAILABLE"):
        await _start(service)
    executor.execute.assert_not_awaited()
    await service.shutdown()


@pytest.mark.parametrize("durable", [False, True])
async def test_repository_revision_fence_prevents_stale_overwrites(tmp_path, durable):
    repository = SqliteRunRepository(tmp_path / "runs.sqlite3") if durable else InMemoryRunRepository()
    await _start(AdlcRunService(repository=repository))
    left, right = repository.load_all()[0], repository.load_all()[0]
    left.run.name = "Newer snapshot"
    repository.save(left)
    right.run.name = "Stale snapshot"
    with pytest.raises(RunRepositoryError, match="ADLC_RUN_REVISION_CONFLICT"):
        repository.save(right)
    assert repository.load_all()[0].run.name == "Newer snapshot"
    left.owner_id = "forged-owner"
    with pytest.raises(RunRepositoryError, match="ADLC_RUN_REVISION_CONFLICT"):
        repository.save(left)


def test_run_repository_factory_uses_explicit_test_memory_or_durable_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ADLC_RUN_DB_PATH", " ")
    assert create_run_repository_from_environment().is_durable is False
    monkeypatch.setenv("ADLC_RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))
    assert create_run_repository_from_environment().is_durable is True


def test_default_stores_are_durable_and_independent_of_launch_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("ADLC_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("ADLC_HARNESS_ATTEMPT_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    run_factory = []
    attempt_factory = []
    monkeypatch.setattr(run_repository, "SqliteRunRepository", lambda path: run_factory.append(path))
    monkeypatch.setattr(harness_attempts, "SqliteTaskAttemptRepository", lambda path: attempt_factory.append(path))
    run_repository.create_run_repository_from_environment()
    harness_attempts.create_task_attempt_repository_from_environment()
    assert run_factory[0].parent == attempt_factory[0].parent
    assert run_factory[0].is_absolute()
    assert run_factory[0].name == "adlc-runs.sqlite3"
    assert attempt_factory[0].name == "adlc-harness-attempts.sqlite3"


async def test_history_api_filters_and_authorizes_restored_runs(tmp_path):
    path = tmp_path / "runs.sqlite3"
    original = AdlcRunService(repository=SqliteRunRepository(path))
    run = await _start(original)
    await _start(original, owner="someone-else")
    await original.shutdown()
    restored = AdlcRunService(repository=SqliteRunRepository(path))
    await restored.recover()
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: restored
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="owner")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        response = await http.get("/api/v1/adlc/runs", params={"flow_id": str(run.flow_id), "status": "SUCCEEDED"})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["runs"][0]["id"] == str(run.id)
        assert "someone-else" not in response.text
        assert "outputs" not in response.text
        for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "INVALID"}, {"flow_id": "invalid"}):
            assert (await http.get("/api/v1/adlc/runs", params=params)).status_code == 422
        app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="someone-else")
        assert (await http.get(f"/api/v1/adlc/runs/{run.id}")).status_code == 404
    await restored.shutdown()


async def test_application_factory_preserves_existing_harness_history_and_callback_ledger(monkeypatch, tmp_path):
    repository = SqliteRunRepository(tmp_path / "runs.sqlite3")
    original = AdlcRunService(repository=repository)
    run = await _start(original)
    await original.shutdown()
    callbacks = _callbacks(tmp_path)
    monkeypatch.delenv("ADLC_RUN_DB_PATH", raising=False)
    monkeypatch.setattr(adlc_api, "create_run_repository_from_environment", lambda: repository)
    monkeypatch.setattr(adlc_api, "get_harness_callback_receiver", lambda: callbacks)
    monkeypatch.setattr(adlc_api, "get_harness_client", lambda: None)
    monkeypatch.setattr(adlc_api, "get_adlc_artifact_payload_store", BoundedArtifactPayloadStore)
    monkeypatch.setattr(adlc_api, "create_default_task_executor", lambda **_kwargs: MockExecutor())

    restored = adlc_api._build_adlc_run_service()
    await restored.recover()
    assert restored._harness_callbacks is callbacks
    assert (await restored.get_run(run.id, owner_id="owner")).status is WorkflowRunStatus.SUCCEEDED
    assert (await restored.list_runs(owner_id="owner")).total == 1
    await restored.shutdown()


@pytest.mark.parametrize("configuration", [None, "configured.sqlite3", ""])
async def test_application_factory_selects_sql_for_fresh_installs_and_honors_run_storage_configuration(
    monkeypatch, configuration
):
    repository = InMemoryRunRepository()
    sql_persistence = SimpleNamespace(save=AsyncMock(), load=AsyncMock(return_value=[]))
    if configuration is None:
        monkeypatch.delenv("ADLC_RUN_DB_PATH", raising=False)
    else:
        monkeypatch.setenv("ADLC_RUN_DB_PATH", configuration)
    monkeypatch.setattr(adlc_api, "create_run_repository_from_environment", lambda: repository)
    monkeypatch.setattr(adlc_api, "SqlAdlcRunPersistence", lambda _factory: sql_persistence)
    monkeypatch.setattr(adlc_api, "get_harness_callback_receiver", lambda: None)
    monkeypatch.setattr(adlc_api, "get_harness_client", lambda: None)
    monkeypatch.setattr(adlc_api, "get_adlc_artifact_payload_store", BoundedArtifactPayloadStore)
    monkeypatch.setattr(adlc_api, "create_default_task_executor", lambda **_kwargs: MockExecutor())

    service = adlc_api._build_adlc_run_service()
    await _start(service)
    if configuration is None:
        assert service._persistence is sql_persistence
        sql_persistence.save.assert_awaited()
        assert repository.load_all() == []
    else:
        sql_persistence.save.assert_not_awaited()
        assert len(repository.load_all()) == 1
    await service.shutdown()

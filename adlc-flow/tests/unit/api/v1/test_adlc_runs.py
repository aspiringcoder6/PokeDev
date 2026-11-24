# ruff: noqa: PLR2004, S101, S105, S106

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.harness_callbacks import (
    HarnessCallbackReceiver,
    HarnessCallbackSettings,
    sign_harness_delivery,
)
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessInteractionKind,
    HarnessInteractionReceipt,
    HarnessInteractionRecord,
    HarnessInteractionResponse,
    HarnessInteractionStatus,
    HarnessResultDelivery,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    HarnessSubmissionReceipt,
)
from langflow.adlc.models import (
    ApprovalComment,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    TaskRequest,
    TaskResultStatus,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)
from langflow.adlc.opencode_runtime import OpenCodeRuntimeReadiness
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from lfx.services.deps import injectable_session_scope


def _session():
    return SimpleNamespace(commit=AsyncMock())


class _NoDeliverySession:
    """Session stub whose delivery lookup finds no row (authority skips)."""

    commit = AsyncMock()

    async def exec(self, *_args, **_kwargs):
        return SimpleNamespace(first=lambda: None)


async def _allow_execute(*_args, **_kwargs):
    return None


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "plan", "type": "genericNode", "data": {"type": "Plan"}},
            {"id": "implement", "type": "genericNode", "data": {"type": "Implement"}},
            {
                "id": "approval",
                "type": "genericNode",
                "data": {"type": "Approval", "adlc": {"approvalGate": "AFTER_TASK"}},
            },
        ],
        "edges": [
            {"source": "plan", "target": "implement"},
            {"source": "implement", "target": "approval"},
        ],
    }


async def test_adlc_controller_reads_saved_flow_and_exposes_run_resources(monkeypatch) -> None:
    flow = SimpleNamespace(
        id=uuid4(),
        name="API Slice",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = AdlcRunService()

    async def authorized_flow(**kwargs):
        assert kwargs["flow_id"] == flow.id
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=_session(),
        service=service,
    )

    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert run.execution_mode is WorkflowExecutionMode.LEGACY_FLOW
    assert await adlc_api.get_adlc_run(run.id, current_user=user, service=service)
    assert await adlc_api.get_adlc_run_tasks(run.id, current_user=user, service=service)
    assert (await adlc_api.get_adlc_run_events(run.id, current_user=user, service=service)).events

    approval_id = run.approval_requests[0].approval_request_id
    resolved = await adlc_api.approve_adlc_run(
        approval_id,
        current_user=user,
        service=service,
        command=ApprovalComment(comment="Approved in API test."),
    )
    assert resolved.status is WorkflowRunStatus.SUCCEEDED


async def test_adlc_controller_returns_contract_validation_error(monkeypatch) -> None:
    flow = SimpleNamespace(
        id=uuid4(),
        name="Cyclic",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    flow.data["edges"].append({"source": "approval", "target": "plan"})

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    with pytest.raises(HTTPException) as exc:
        await adlc_api.create_adlc_run(
            CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
            current_user=SimpleNamespace(id=uuid4(), username="owner"),
            session=_session(),
            service=AdlcRunService(),
        )

    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert exc.value.detail["code"] == "INVALID_ADLC_DAG"
    assert "issues" in exc.value.detail["details"]


async def test_legacy_run_endpoint_rejects_a_different_explicit_mode() -> None:
    with pytest.raises(HTTPException) as exc:
        await adlc_api.create_adlc_run(
            CreateWorkflowRunRequest(flowId=uuid4(), executionMode="EXECUTION_PLAN", delayMs=0),
            current_user=SimpleNamespace(id=uuid4(), username="owner"),
            session=_session(),
            service=AdlcRunService(),
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["code"] == "EXECUTION_MODE_MISMATCH"
    assert exc.value.detail["details"] == {
        "expected": "LEGACY_FLOW",
        "received": "EXECUTION_PLAN",
    }


def test_required_adlc_routes_are_registered() -> None:
    # Included-router wrappers need not expose HTTP methods; all required routes here are direct registrations.
    registered = {
        (route.path, method)
        for route in adlc_api.router.routes
        for method in (getattr(route, "methods", None) or set())
    }
    expected = {
        ("/adlc/runs", "POST"),
        ("/adlc/runs", "GET"),
        ("/adlc/runs/{run_id}", "GET"),
        ("/adlc/runs/{run_id}/tasks", "GET"),
        ("/adlc/runs/{run_id}/tasks/{task_run_id}/task-loop-runtime", "GET"),
        ("/adlc/runs/{run_id}/harness-sessions", "GET"),
        ("/adlc/runs/{run_id}/harness-results", "GET"),
        (
            "/adlc/runs/{run_id}/harness-sessions/{session_id}/interactions/{interaction_id}/responses",
            "POST",
        ),
        ("/adlc/runs/{run_id}/harness-sessions/{session_id}/submit", "POST"),
        ("/adlc/runs/{run_id}/harness/reconcile", "POST"),
        ("/adlc/runs/{run_id}/events", "GET"),
        ("/adlc/tasks/{task_id}/retry", "POST"),
        ("/adlc/approvals/{approval_id}/approve", "POST"),
        ("/adlc/approvals/{approval_id}/reject", "POST"),
        ("/adlc/executors/opencode/readiness", "GET"),
        ("/adlc/executors/deepseek-harness/readiness", "GET"),
        ("/adlc/harness/callbacks/session-results", "POST"),
    }
    assert expected <= registered


async def test_opencode_readiness_endpoint_is_authenticated_and_secret_free() -> None:
    user = SimpleNamespace(id=uuid4(), username="owner")
    readiness = OpenCodeRuntimeReadiness(
        enabled=True,
        ready=True,
        server_ready=True,
        server_version="1.18.31",
        model_configured=True,
        model_ref="aigateway/MiniMax/MiniMax-M3",
        sandbox_ready=True,
    )
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[adlc_api.get_opencode_runtime_readiness] = lambda: readiness

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/adlc/executors/opencode/readiness")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["ready"] is True
    assert payload["model_ref"] == "aigateway/MiniMax/MiniMax-M3"
    assert "password" not in payload
    assert "api_key" not in payload


async def test_harness_callback_route_uses_hmac_not_end_user_auth() -> None:
    secret = "callback-secret"
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret=secret), clock=lambda: 1_700_000_000)
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    task_request = TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="coding",
        name="Harness callback",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
    )
    await callbacks.register_attempt(task_request)
    now = datetime.now(timezone.utc)
    delivery = HarnessResultDelivery(
        delivery_id=uuid4(),
        callback_ref="adlc-primary",
        created_at=now,
        result=HarnessSessionResult(
            session_id="session-api",
            correlation=HarnessCorrelation(
                request_id=task_request.request_id,
                workflow_run_id=workflow_run_id,
                task_run_id=task_run_id,
                attempt_id=attempt_id,
            ),
            status=TaskResultStatus.SUCCEEDED,
            output={"summary": "done"},
            artifacts=[],
            error=None,
            started_at=now,
            completed_at=now,
        ),
    )
    body = delivery.model_dump_json().encode()
    timestamp = "1700000000"
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[adlc_api.get_harness_callback_receiver] = lambda: callbacks

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/adlc/harness/callbacks/session-results",
            content=body,
            headers={
                "content-type": "application/json",
                "x-adlc-delivery-id": str(delivery.delivery_id),
                "x-adlc-timestamp": timestamp,
                "x-adlc-signature": sign_harness_delivery(secret, timestamp, body),
            },
        )

    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.json()["attempt_id"] == str(attempt_id)


async def test_harness_control_routes_are_owner_scoped_and_forward_exact_session(monkeypatch) -> None:
    flow = SimpleNamespace(
        id=uuid4(),
        name="Harness UI",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = AdlcRunService()

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=_session(),
        service=service,
    )
    task = run.tasks[1]
    attempt_id = uuid4()
    request_id = uuid4()
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    await callbacks.register_attempt(
        TaskRequest(
            request_id=request_id,
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
            task_definition_id=task.task_definition_id,
            task_type=task.task_type,
            name=task.name,
            executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
            input={},
            context={},
            dependency_task_run_ids=[],
            constraints={},
            idempotency_key=f"{run.id}:{task.id}:{attempt_id}",
            requested_at=datetime.now(timezone.utc),
        )
    )
    session_id = "session-ui"
    await callbacks.bind_session(attempt_id, session_id)
    now = datetime.now(timezone.utc)
    interaction_id = uuid4()
    interaction = HarnessInteractionRecord(
        interaction_id=interaction_id,
        kind=HarnessInteractionKind.APPROVAL,
        status=HarnessInteractionStatus.PENDING,
        title="Approve agent action",
        prompt="Continue?",
        input_schema={
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["approve", "reject"]}},
            "required": ["action"],
        },
        requested_at=now,
    )
    waiting_session = HarnessSessionRead(
        session_id=session_id,
        correlation=HarnessCorrelation(
            request_id=request_id,
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
        ),
        idempotency_key=f"{run.id}:{task.id}:{attempt_id}",
        status=HarnessSessionStatus.WAITING_INTERACTION,
        submission_mode=HarnessSubmissionMode.MANUAL,
        interactions=[interaction],
        created_at=now,
        updated_at=now,
    )
    resolved = interaction.model_copy(
        update={
            "status": HarnessInteractionStatus.SUBMITTED,
            "response": {"action": "approve"},
            "resolved_at": now,
        }
    )
    client = SimpleNamespace(
        get_session=AsyncMock(return_value=waiting_session),
        respond_to_interaction=AsyncMock(
            return_value=HarnessInteractionReceipt(
                session_id=session_id,
                interaction=resolved,
                status=HarnessSessionStatus.RUNNING,
            )
        ),
        submit_session=AsyncMock(
            return_value=HarnessSubmissionReceipt(
                session_id=session_id,
                status=HarnessSessionStatus.DELIVERING,
                delivery_id=uuid4(),
                delivery_status="PENDING",
            )
        ),
    )

    sessions = await adlc_api.get_adlc_run_harness_sessions(
        run.id,
        current_user=user,
        service=service,
        callbacks=callbacks,
        client=client,
    )
    receipt = await adlc_api.respond_to_adlc_harness_interaction(
        run.id,
        session_id,
        str(interaction_id),
        HarnessInteractionResponse(response={"action": "approve"}),
        current_user=user,
        service=service,
        callbacks=callbacks,
        client=client,
    )

    assert sessions[0].session.session_id == session_id
    assert receipt.interaction.response == {"action": "approve"}
    client.respond_to_interaction.assert_awaited_once_with(
        session_id,
        str(interaction_id),
        HarnessInteractionResponse(response={"action": "approve"}),
    )

    client.get_session.return_value = waiting_session.model_copy(
        update={"status": HarnessSessionStatus.READY_FOR_SUBMISSION, "interactions": [resolved]}
    )
    submission = await adlc_api.submit_adlc_harness_session(
        run.id,
        session_id,
        current_user=user,
        service=service,
        callbacks=callbacks,
        client=client,
    )
    assert submission.delivery_status.value == "PENDING"
    client.submit_session.assert_awaited_once_with(session_id)


async def test_saved_flow_slice_works_through_mounted_http_routes(monkeypatch) -> None:
    flow = SimpleNamespace(
        id=uuid4(),
        name="HTTP Slice",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = AdlcRunService()

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[injectable_session_scope] = _session
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        missing_mode = await client.post("/api/v1/adlc/runs", json={"flowId": str(flow.id), "delayMs": 0})
        started = await client.post(
            "/api/v1/adlc/runs",
            json={"flowId": str(flow.id), "executionMode": "LEGACY_FLOW", "delayMs": 0},
        )
        assert missing_mode.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert started.status_code == status.HTTP_201_CREATED
        run = started.json()
        assert run["execution_mode"] == "LEGACY_FLOW"

        snapshot = await client.get(f"/api/v1/adlc/runs/{run['id']}")
        tasks = await client.get(f"/api/v1/adlc/runs/{run['id']}/tasks")
        events = await client.get(f"/api/v1/adlc/runs/{run['id']}/events")
        assert snapshot.status_code == status.HTTP_200_OK
        assert len(tasks.json()) == 3
        assert events.json()["events"]

        approval_id = run["approval_requests"][0]["approval_request_id"]
        approved = await client.post(f"/api/v1/adlc/approvals/{approval_id}/approve", json={})
        assert approved.status_code == status.HTTP_200_OK
        assert approved.json()["status"] == "SUCCEEDED"


async def test_approval_refuses_artifact_changed_after_review(monkeypatch) -> None:
    """Human gate version pinning: a stale approval is refused with 409."""
    flow = SimpleNamespace(
        id=uuid4(),
        name="Digest Pinning",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    user = SimpleNamespace(id=uuid4(), username="owner")

    session = _NoDeliverySession()
    service = AdlcRunService()

    async def authorized_flow(**kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=session,
        service=service,
    )
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    approval_id = run.approval_requests[0].approval_request_id
    assert run.approval_requests[0].context.payload["artifact_digests"]

    # The reviewed revision changes after the human opened the approval.
    approval_request = run.approval_requests[0]
    pinned = approval_request.context.payload["artifact_digests"][0]
    record = service._runs[run.id]
    approval_task = next(task for task in record.run.tasks if task.id == approval_request.task_run_id)
    reviewed_artifact = next(
        artifact for artifact in approval_task.artifacts if str(artifact.artifact_id) == pinned["artifact_id"]
    )
    reviewed_artifact.checksum.value = "a" * 64

    with pytest.raises(HTTPException) as exc:
        await adlc_api.approve_adlc_run(
            approval_id,
            current_user=user,
            service=service,
            command=ApprovalComment(comment="Stale approval attempt."),
        )
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "APPROVAL_ARTIFACT_DIGEST_MISMATCH" in exc.value.detail["message"]
    assert run.approval_requests[0].status.value == "PENDING"

    # Re-reviewing the restored (pinned) revision completes the run.
    reviewed_artifact.checksum.value = pinned["digest"].removeprefix("sha256:")
    resolved = await adlc_api.approve_adlc_run(
        approval_id,
        current_user=user,
        service=service,
        command=ApprovalComment(comment="Approved the pinned revision."),
    )
    assert resolved.status is WorkflowRunStatus.SUCCEEDED


async def test_run_metadata_records_reflection_after_completion(monkeypatch) -> None:
    """A completed run carries the orchestrator's ReflectionReport in metadata."""
    flow = SimpleNamespace(
        id=uuid4(),
        name="Reflection",
        data=_graph(),
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    user = SimpleNamespace(id=uuid4(), username="owner")
    session = _NoDeliverySession()
    service = AdlcRunService()

    async def authorized_flow(**kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=session,
        service=service,
    )
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL

    resolved = await adlc_api.approve_adlc_run(
        run.approval_requests[0].approval_request_id,
        current_user=user,
        service=service,
        command=ApprovalComment(comment="Approved."),
    )

    assert resolved.status is WorkflowRunStatus.SUCCEEDED
    reflection = resolved.metadata["reflection"]
    assert reflection["plugin_id"] == "monarch"
    assert reflection["summary"]
    assert reflection["successes"]

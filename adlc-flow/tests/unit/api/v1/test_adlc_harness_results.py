# ruff: noqa: S101, S106

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.harness_attempts import InMemoryTaskAttemptRepository, SqliteTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver, HarnessCallbackSettings, sign_harness_delivery
from langflow.adlc.harness_models import HarnessCorrelation, HarnessResultDelivery, HarnessSessionResult
from langflow.adlc.models import CreateWorkflowRunRequest, ExecutorTarget, ServiceError, TaskRequest, TaskResultStatus
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user


@pytest.mark.parametrize(
    "result_status", [TaskResultStatus.SUCCEEDED, TaskResultStatus.FAILED, TaskResultStatus.CANCELLED]
)
async def test_archived_result_is_readable_after_harness_cleanup_and_receiver_restart(
    monkeypatch, tmp_path, result_status
) -> None:
    user = SimpleNamespace(id=uuid4(), username="owner")
    flow = SimpleNamespace(
        id=uuid4(),
        name="Archived result run",
        data={"nodes": [{"id": "plan", "type": "genericNode", "data": {"type": "Plan"}}], "edges": []},
        user_id=None,
        workspace_id=None,
        folder_id=None,
    )
    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", AsyncMock(return_value=flow))
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", AsyncMock())
    service = AdlcRunService()
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=SimpleNamespace(commit=AsyncMock()),
        service=service,
    )
    now = datetime.now(timezone.utc)
    request = TaskRequest(
        request_id=uuid4(),
        workflow_run_id=run.id,
        task_run_id=run.tasks[0].id,
        attempt_id=uuid4(),
        task_definition_id=run.tasks[0].task_definition_id,
        task_type="coding",
        name="Read-only Harness task",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=str(uuid4()),
        requested_at=now,
    )
    database = tmp_path / "harness-attempts.sqlite3"
    callbacks = HarnessCallbackReceiver(
        HarnessCallbackSettings(secret="callback-secret"),
        attempts=SqliteTaskAttemptRepository(database),
        clock=lambda: 1_700_000_000,
    )
    await callbacks.register_attempt(request)
    await callbacks.bind_session(request.attempt_id, "deleted-harness-session")
    succeeded = result_status is TaskResultStatus.SUCCEEDED
    result = HarnessSessionResult(
        session_id="deleted-harness-session",
        correlation=HarnessCorrelation(
            request_id=request.request_id,
            workflow_run_id=run.id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
        ),
        status=result_status,
        output={"summary": "Read-only result retained by ADLC.", "outputs": {"files_changed": [], "answer": "ready"}},
        artifacts=[],
        verification_reports=[
            {
                "verifier_ref": "plugin:vai-adlc-verify-structured/0.1.0",
                "status": "PASSED" if succeeded else "FAILED",
                "checks": [
                    {"check_id": "structured", "status": "PASSED" if succeeded else "FAILED", "summary": "Checked."}
                ],
                "started_at": now,
                "completed_at": now,
            }
        ],
        interaction_records=[
            {
                "interaction_id": uuid4(),
                "kind": "APPROVAL",
                "status": "SUBMITTED",
                "title": "Confirm read-only report",
                "prompt": "Return this report?",
                "requested_at": now,
                "resolved_at": now,
                "response": {"action": "approve"},
            }
        ],
        error=None
        if succeeded
        else ServiceError(
            error_id=uuid4(),
            code="HARNESS_EXECUTION_FAILED",
            category="DEPENDENCY",
            message="The execution did not succeed.",
            retryable=False,
            service="agent-provider:deepseek-harness",
            details={},
            correlation_id=str(run.id),
            occurred_at=now,
        ),
        trace_ref="harness://deleted-harness-session/events",
        metadata={"driver": {"provider": "my-codex", "model": "cx/gpt-5.6-luna"}},
        started_at=now,
        completed_at=now,
    )
    delivery = HarnessResultDelivery(delivery_id=uuid4(), callback_ref="adlc-primary", created_at=now, result=result)
    body = delivery.model_dump_json().encode()
    await callbacks.receive(
        body,
        delivery_id=str(delivery.delivery_id),
        timestamp="1700000000",
        signature=sign_harness_delivery("callback-secret", "1700000000", body),
    )

    # Reopen only ADLC's durable result store. No Harness client is configured,
    # and the deleted live session must never be queried to render an archive.
    reopened = HarnessCallbackReceiver(attempts=SqliteTaskAttemptRepository(database))
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[adlc_api.get_harness_callback_receiver] = lambda: reopened
    app.dependency_overrides[adlc_api.get_harness_client] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        archive = await client.get(f"/api/v1/adlc/runs/{run.id}/harness-results")
        sessions = await client.get(f"/api/v1/adlc/runs/{run.id}/harness-sessions")
        assert archive.status_code == status.HTTP_200_OK
        assert sessions.status_code == status.HTTP_200_OK
        assert sessions.json() == []
        assert archive.json()[0]["result"] == result.model_dump(mode="json")
        assert archive.json()[0]["attempt_id"] == str(request.attempt_id)
        assert archive.json()[0]["stored_at"]

        # Results inherit the same owner boundary as the run itself.
        app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
        denied = await client.get(f"/api/v1/adlc/runs/{run.id}/harness-results")
        assert denied.status_code == status.HTTP_404_NOT_FOUND
        assert "Read-only result" not in denied.text


async def test_unknown_run_does_not_query_the_result_store() -> None:
    callbacks = SimpleNamespace(attempts=SimpleNamespace(list_for_workflow_run=AsyncMock()))
    with pytest.raises(HTTPException) as exc:
        await adlc_api.get_adlc_run_harness_results(
            uuid4(),
            current_user=SimpleNamespace(id=uuid4()),
            service=AdlcRunService(),
            callbacks=callbacks,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    callbacks.attempts.list_for_workflow_run.assert_not_awaited()


async def test_unaccepted_manual_preview_is_not_in_the_adlc_archive() -> None:
    run_id = uuid4()
    request = TaskRequest(
        request_id=uuid4(),
        workflow_run_id=run_id,
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="coding",
        name="Not submitted",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=str(uuid4()),
        requested_at=datetime.now(timezone.utc),
    )
    callbacks = HarnessCallbackReceiver(attempts=InMemoryTaskAttemptRepository())
    await callbacks.register_attempt(request)
    await callbacks.bind_session(request.attempt_id, "pending-manual")
    results = await adlc_api.get_adlc_run_harness_results(
        run_id,
        current_user=SimpleNamespace(id=uuid4()),
        service=SimpleNamespace(get_run=AsyncMock()),
        callbacks=callbacks,
    )
    assert results == []

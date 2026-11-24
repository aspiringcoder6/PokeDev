from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.mock_workflow import MockWorkflowService
from langflow.adlc.models import (
    ApprovalDecisionCommand,
    StartMockWorkflowRequest,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)
from langflow.api.v1.adlc import (
    get_mock_workflow,
    get_mock_workflow_run,
    get_mock_workflow_run_events,
    get_mock_workflow_service,
    resolve_mock_workflow_approval,
    start_mock_workflow_run,
)
from langflow.api.v1.adlc import router as adlc_router
from langflow.services.auth.utils import get_current_active_user


def _user(user_id: str = "owner-1") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, username="mock-owner")


async def test_mock_api_controller_supports_run_read_events_and_approval() -> None:
    service = MockWorkflowService()
    definition = await get_mock_workflow(current_user=_user(), service=service)
    assert len(definition.tasks) == 5

    run = await start_mock_workflow_run(
        StartMockWorkflowRequest(delayMs=0),
        current_user=_user(),
        service=service,
    )
    assert run.execution_mode is WorkflowExecutionMode.MOCK_WORKFLOW
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL

    snapshot = await get_mock_workflow_run(run.id, current_user=_user(), service=service)
    events = await get_mock_workflow_run_events(run.id, current_user=_user(), service=service)
    assert snapshot.id == run.id
    assert events.workflow_run_id == run.id
    assert events.events

    resolved = await resolve_mock_workflow_approval(
        run.id,
        ApprovalDecisionCommand(action="APPROVE"),
        current_user=_user(),
        service=service,
    )
    assert resolved.status is WorkflowRunStatus.SUCCEEDED


async def test_mock_api_hides_runs_owned_by_another_user() -> None:
    service = MockWorkflowService()
    run = await service.start_run(StartMockWorkflowRequest(delayMs=0), owner_id="owner-1")

    with pytest.raises(HTTPException) as exc:
        await get_mock_workflow_run(run.id, current_user=_user("owner-2"), service=service)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail["code"] == "MOCK_RUN_NOT_FOUND"


async def test_mock_routes_are_mounted_and_preserve_required_contract_nulls() -> None:
    app = FastAPI()
    service = MockWorkflowService()
    app.include_router(adlc_router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = _user
    app.dependency_overrides[get_mock_workflow_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/v1/adlc/mock/runs", json={"delayMs": 0})

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert payload["status"] == "WAITING_APPROVAL"
    successful_result = next(task["result"] for task in payload["tasks"] if task["result"] is not None)
    assert "error" in successful_result
    assert successful_result["error"] is None
    workflow_event = next(event for event in payload["events"] if event["aggregate_type"] == "WORKFLOW_RUN")
    assert "task_run_id" not in workflow_event

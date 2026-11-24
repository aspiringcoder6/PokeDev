# ruff: noqa: PLR2004, S101

"""HTTP coverage for the Planner Agent proposal endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.proposals import (
    LLMPlannerAgent,
    MockPlannerAgent,
    ProposalService,
)
from langflow.adlc.planning.proposals.planner import PlannerOutput, ProposedTaskDraft
from langflow.adlc.planning.proposals.service import ProposalService
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from lfx.services.deps import injectable_session_scope

if TYPE_CHECKING:
    pass

STAGE_ID = UUID("22222222-2222-4222-8222-222222222222")


def _session():
    return SimpleNamespace(commit=AsyncMock())


async def _allow_execute(*_args, **_kwargs):
    return None


def _graph(flow_id: UUID) -> dict:
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(flow_id),
            "version": 1,
        },
        "nodes": [
            {
                "id": "req",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_STAGE",
                        "schema_version": "0.1",
                        "stage_id": str(STAGE_ID),
                        "stage_type": "REQUIREMENTS",
                        "name": "Requirements",
                        "objective": "Gather the requirements.",
                        "inputs": {"requirement": "Build the document system."},
                        "expected_outputs": ["source_patch"],
                        "package_ref": {"package_id": "coding-agent", "version": "0.1.0"},
                    }
                },
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _flow() -> SimpleNamespace:
    flow_id = uuid4()
    return SimpleNamespace(
        id=flow_id,
        name="Planner Blueprint",
        description="Planner API fixture.",
        data=_graph(flow_id),
        user_id=None,
        workspace_id=uuid4(),
        folder_id=None,
        updated_at=datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc),
    )


def _proposal_service(planner=None):
    registry = create_default_package_registry()
    resolver = create_default_package_resolver(registry, create_default_package_access_policy())
    plan_service = ExecutionPlanService(BlueprintCompiler(resolver))
    proposal_service = ProposalService(planner or MockPlannerAgent(), registry, plan_service)
    return proposal_service, plan_service


def _client(monkeypatch, flow, user, service, plan_service=None):
    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[injectable_session_scope] = _session
    app.dependency_overrides[adlc_api.get_proposal_service] = lambda: service
    app.dependency_overrides[adlc_api.get_node_package_registry] = create_default_package_registry
    app.dependency_overrides[adlc_api.get_package_access_policy] = create_default_package_access_policy
    if plan_service is not None:
        app.dependency_overrides[adlc_api.get_execution_plan_service] = lambda: plan_service
        app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: AdlcRunService()
        app.dependency_overrides[adlc_api.get_execution_plan_materializer] = lambda: ExecutionPlanMaterializer()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_generate_validate_approve_then_run_through_http(monkeypatch) -> None:
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    service, plan_service = _proposal_service()

    async with _client(monkeypatch, flow, user, service, plan_service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals",
            json={},
        )
        assert created.status_code == 201
        proposal = created.json()
        assert proposal["status"] == "GENERATED"
        assert proposal["planner_mode"] == "MOCK"
        assert len(proposal["tasks"]) >= 1

        fetched = await client.get(f"/api/v1/adlc/plan-proposals/{proposal['proposal_id']}")
        assert fetched.status_code == 200

        validated = await client.post(
            f"/api/v1/adlc/plan-proposals/{proposal['proposal_id']}/validate"
        )
        assert validated.status_code == 200
        assert validated.json()["status"] == "VALIDATED"

        approved = await client.post(
            f"/api/v1/adlc/plan-proposals/{proposal['proposal_id']}/approve", json={}
        )
        assert approved.status_code == 200
        body = approved.json()
        assert body["proposal"]["status"] == "APPROVED"
        assert body["proposal"]["materialized_plan_id"]
        assert body["execution_plan"]["status"] in {"VALIDATED", "APPROVED"}
        plan_id = body["proposal"]["materialized_plan_id"]

        started = await client.post(
            f"/api/v1/adlc/execution-plans/{plan_id}/runs",
            json={"idempotencyKey": "planner-http-run"},
        )
        assert started.status_code == 201
        assert started.json()["status"] in {"RUNNING", "SUCCEEDED", "WAITING_APPROVAL"}
        assert started.json()["execution_mode"] == "EXECUTION_PLAN"


async def test_proposal_lookup_does_not_leak_across_owners(monkeypatch) -> None:
    flow = _flow()
    owner = SimpleNamespace(id=uuid4(), username="owner")
    other = SimpleNamespace(id=uuid4(), username="other")
    service = _proposal_service()[0]

    async with _client(monkeypatch, flow, owner, service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals", json={}
        )
        proposal_id = created.json()["proposal_id"]

    other_client = _client(monkeypatch, flow, other, service)
    async with other_client as client:
        response = await client.get(f"/api/v1/adlc/plan-proposals/{proposal_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "PLANNER_PROPOSAL_NOT_FOUND"


async def test_invalid_proposal_validation_returns_revision_required(monkeypatch) -> None:
    class EmptyPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            return PlannerOutput(tasks=[])

    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = _proposal_service(EmptyPlanner())[0]

    async with _client(monkeypatch, flow, user, service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals", json={}
        )
        proposal_id = created.json()["proposal_id"]
        validated = await client.post(f"/api/v1/adlc/plan-proposals/{proposal_id}/validate")
        assert validated.status_code == 200
        body = validated.json()
        assert body["status"] == "REVISION_REQUIRED"
        assert any(issue["code"] == "EMPTY_PROPOSAL" for issue in body["validation_errors"])

        approved = await client.post(f"/api/v1/adlc/plan-proposals/{proposal_id}/approve", json={})
        assert approved.status_code == 409
        assert approved.json()["detail"]["code"] == "PLANNER_PROPOSAL_STATE_CONFLICT"

        successor = await client.post(
            f"/api/v1/adlc/plan-proposals/{proposal_id}/regenerate", json={}
        )
        assert successor.status_code == 201
        assert successor.json()["supersedes_proposal_id"] == proposal_id


async def test_planner_failure_maps_to_service_unavailable(monkeypatch) -> None:
    import httpx as httpx_module

    def handler(request):
        raise httpx_module.ConnectError("refused", request=request)

    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=httpx_module.MockTransport(handler),
    )
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = _proposal_service(planner)[0]

    async with _client(monkeypatch, flow, user, service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals", json={}
        )
        assert created.status_code == 503
        assert created.json()["detail"]["code"] == "PLANNER_UNAVAILABLE"


async def test_malformed_llm_output_maps_to_validation_error(monkeypatch) -> None:
    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "not-json"}}]}
            )
        ),
    )
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = _proposal_service(planner)[0]

    async with _client(monkeypatch, flow, user, service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals", json={}
        )
        assert created.status_code == 503
        assert created.json()["detail"]["code"] == "PLANNER_MALFORMED_OUTPUT"


async def test_generate_requires_marked_blueprint(monkeypatch) -> None:
    flow = _flow()
    flow.data = {"nodes": [], "edges": []}  # unmarked legacy flow
    user = SimpleNamespace(id=uuid4(), username="owner")
    service = _proposal_service()[0]

    async with _client(monkeypatch, flow, user, service) as client:
        created = await client.post(
            f"/api/v1/adlc/workflow-definitions/{flow.id}/plan-proposals", json={}
        )
        assert created.status_code == 422
        assert created.json()["detail"]["code"] in {"BLUEPRINT_INVALID", "BLUEPRINT_MARKER_MISSING"}


def test_proposal_routes_are_registered() -> None:
    registered = {
        (route.path, method)
        for route in adlc_api.router.routes
        for method in (getattr(route, "methods", None) or set())
    }
    expected = {
        ("/adlc/workflow-definitions/{workflow_id}/plan-proposals", "POST"),
        ("/adlc/plan-proposals/{proposal_id}", "GET"),
        ("/adlc/plan-proposals/{proposal_id}/validate", "POST"),
        ("/adlc/plan-proposals/{proposal_id}/approve", "POST"),
        ("/adlc/plan-proposals/{proposal_id}/regenerate", "POST"),
        ("/adlc/plan-proposals/{proposal_id}/reject", "POST"),
    }
    assert expected <= registered

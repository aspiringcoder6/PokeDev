# ruff: noqa: PLR2004, S101

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.models import (
    CreateWorkflowRunRequest,
    MaterializeExecutionPlanRequest,
    RegenerateExecutionPlanRequest,
)
from langflow.adlc.packages.defaults import (
    DEFAULT_PACKAGE_IDENTITIES,
    MOCK_REFERENCE_IDS,
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from lfx.services.deps import injectable_session_scope

if TYPE_CHECKING:
    from langflow.adlc.packages.access import PackageAccessPolicy

IMPLEMENT_STAGE_ID = UUID("22222222-2222-4222-8222-222222222222")
APPROVAL_STAGE_ID = UUID("33333333-3333-4333-8333-333333333333")


def _session():
    # These route tests exercise unbound, in-memory planner flows. Model the
    # empty SQL projections now consulted by Delivery guards; real bound-flow
    # isolation and durable archives are tested against SQLite in H8B tests.
    empty = SimpleNamespace(first=lambda: None, all=list, one=lambda: None)
    return SimpleNamespace(
        commit=AsyncMock(), exec=AsyncMock(return_value=empty), add=lambda _row: None, flush=AsyncMock()
    )


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
                "id": "implement",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_STAGE",
                        "schema_version": "0.1",
                        "stage_id": str(IMPLEMENT_STAGE_ID),
                        "stage_type": "IMPLEMENTATION",
                        "name": "Implement",
                        "objective": "Implement the scoped feature.",
                        "inputs": {"requirement": "Build the feature."},
                        "expected_outputs": ["source_patch"],
                        "package_ref": {"package_id": "coding-agent", "version": "0.1.0"},
                    }
                },
            },
            {
                "id": "approval",
                "type": "genericNode",
                "position": {"x": 300, "y": 0},
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_STAGE",
                        "schema_version": "0.1",
                        "stage_id": str(APPROVAL_STAGE_ID),
                        "stage_type": "APPROVAL",
                        "name": "Approval",
                        "objective": "Approve the implementation.",
                        "inputs": {"approval_context": "Review the source patch."},
                        "expected_outputs": ["approval_decision"],
                        "package_ref": {"package_id": "approval", "version": "0.1.0"},
                    }
                },
            },
        ],
        "edges": [{"source": "implement", "target": "approval"}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _flow() -> SimpleNamespace:
    flow_id = uuid4()
    return SimpleNamespace(
        id=flow_id,
        name="Blueprint API",
        description="Planning API fixture.",
        data=_graph(flow_id),
        user_id=None,
        workspace_id=uuid4(),
        folder_id=None,
        updated_at=datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc),
    )


def _planning_service(access_policy: PackageAccessPolicy | None = None) -> ExecutionPlanService:
    return ExecutionPlanService(BlueprintCompiler(create_default_package_resolver(access_policy=access_policy)))


async def test_package_catalogue_and_plan_lifecycle_are_read_only(monkeypatch) -> None:
    monkeypatch.delenv("ADLC_OPENCODE_ENABLED", raising=False)
    monkeypatch.setenv("ADLC_HARNESS_ENABLED", "false")
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    registry = create_default_package_registry()
    access_policy = create_default_package_access_policy()
    service = _planning_service(access_policy)

    async def authorized_flow(**kwargs):
        assert kwargs["flow_id"] == flow.id
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    packages = await adlc_api.list_node_packages(
        current_user=user,
        registry=registry,
        access_policy=access_policy,
    )
    coding_package = await adlc_api.get_node_package_version(
        "coding-agent",
        "0.1.0",
        current_user=user,
        registry=registry,
        access_policy=access_policy,
    )
    plan = await adlc_api.create_execution_plan(
        flow.id,
        current_user=user,
        session=_session(),
        service=service,
    )

    assert {package.package_id for package in packages} == {"approval", "coding-agent"}
    assert all(package.content_digest.startswith("sha256:") for package in packages)
    assert coding_package.package_id == "coding-agent"
    assert plan.status.value == "VALIDATED"
    assert len(plan.tasks) == 2
    assert await adlc_api.get_execution_plan(plan.execution_plan_id, current_user=user, service=service) == plan
    assert await adlc_api.validate_execution_plan(plan.execution_plan_id, current_user=user, service=service) == plan


async def test_plan_lookup_does_not_leak_across_owners(monkeypatch) -> None:
    flow = _flow()
    owner = SimpleNamespace(id=uuid4(), username="owner")
    other = SimpleNamespace(id=uuid4(), username="other")
    service = _planning_service()

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    plan = await adlc_api.create_execution_plan(
        flow.id,
        current_user=owner,
        session=_session(),
        service=service,
    )

    with pytest.raises(HTTPException) as exc:
        await adlc_api.get_execution_plan(plan.execution_plan_id, current_user=other, service=service)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail["code"] == "PLAN_NOT_FOUND"


async def test_legacy_run_endpoint_rejects_a_marked_blueprint(monkeypatch) -> None:
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    with pytest.raises(HTTPException) as exc:
        await adlc_api.create_adlc_run(
            CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
            current_user=user,
            session=_session(),
            service=AdlcRunService(),
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["code"] == "BLUEPRINT_REQUIRES_EXECUTION_PLAN"


def test_planning_routes_are_registered() -> None:
    app = FastAPI()
    app.include_router(adlc_api.router)
    registered = {
        (path, method.upper()) for path, operations in app.openapi()["paths"].items() for method in operations
    }
    expected = {
        ("/adlc/node-packages", "GET"),
        ("/adlc/node-packages/{package_id}/versions/{version}", "GET"),
        ("/adlc/workflow-definitions/{workflow_id}/plans", "POST"),
        ("/adlc/execution-plans/{plan_id}", "GET"),
        ("/adlc/execution-plans/{plan_id}/regenerate", "POST"),
        ("/adlc/execution-plans/{plan_id}/validate", "POST"),
        ("/adlc/execution-plans/{plan_id}/approve", "POST"),
        ("/adlc/execution-plans/{plan_id}/runs", "POST"),
    }
    assert expected <= registered


async def test_planning_slice_works_through_mounted_http_routes(monkeypatch) -> None:
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    registry = create_default_package_registry()
    access_policy = create_default_package_access_policy()
    service = _planning_service(access_policy)
    run_service = AdlcRunService()
    materializer = ExecutionPlanMaterializer()

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[injectable_session_scope] = _session
    app.dependency_overrides[adlc_api.get_node_package_registry] = lambda: registry
    app.dependency_overrides[adlc_api.get_package_access_policy] = lambda: access_policy
    app.dependency_overrides[adlc_api.get_execution_plan_service] = lambda: service
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: run_service
    app.dependency_overrides[adlc_api.get_execution_plan_materializer] = lambda: materializer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        packages = await client.get("/api/v1/adlc/node-packages")
        created = await client.post(f"/api/v1/adlc/workflow-definitions/{flow.id}/plans")
        assert packages.status_code == status.HTTP_200_OK
        assert all(package["lifecycle_status"] == "PUBLISHED" for package in packages.json())
        assert created.status_code == status.HTTP_201_CREATED
        plan = created.json()

        snapshot = await client.get(f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}")
        validated = await client.post(f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/validate")
        assert snapshot.status_code == status.HTTP_200_OK
        assert validated.status_code == status.HTTP_200_OK
        assert validated.json()["execution_plan_id"] == plan["execution_plan_id"]
        assert validated.json()["status"] == "VALIDATED"

        blocked = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/runs",
            json={"idempotencyKey": "http-plan-run"},
        )
        assert blocked.status_code == status.HTTP_409_CONFLICT
        assert blocked.json()["detail"]["code"] == "PLAN_NOT_ACCEPTED"

        approved = await client.post(f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/approve", json={})
        started = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/runs",
            json={"idempotencyKey": "http-plan-run"},
        )
        duplicate = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/runs",
            json={"idempotencyKey": "http-plan-run"},
        )
        assert approved.status_code == status.HTTP_200_OK
        assert approved.json()["status"] == "APPROVED"
        assert started.status_code == status.HTTP_201_CREATED
        assert started.json()["status"] == "WAITING_APPROVAL"
        assert started.json()["execution_mode"] == "EXECUTION_PLAN"
        assert started.json()["execution_plan_id"] == plan["execution_plan_id"]

        assert all(task["plan_traceability"] for task in started.json()["tasks"])
        assert duplicate.json()["id"] == started.json()["id"]

        regenerated = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/regenerate",
            json={"idempotencyKey": "http-regenerate-plan"},
        )
        regenerated_duplicate = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/regenerate",
            json={"idempotencyKey": "http-regenerate-plan"},
        )
        successor = regenerated.json()
        historical = await client.get(f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}")
        blocked_superseded = await client.post(
            f"/api/v1/adlc/execution-plans/{plan['execution_plan_id']}/runs",
            json={"idempotencyKey": "new-http-run"},
        )

        assert regenerated.status_code == status.HTTP_201_CREATED
        assert regenerated_duplicate.status_code == status.HTTP_201_CREATED
        assert regenerated_duplicate.json()["execution_plan_id"] == successor["execution_plan_id"]
        assert successor["plan_version"] == 2
        assert successor["supersedes_plan_id"] == plan["execution_plan_id"]
        assert successor["status"] == "VALIDATED"
        assert "approved_by" not in successor
        assert "approved_at" not in successor
        assert historical.json()["status"] == "SUPERSEDED"
        assert blocked_superseded.status_code == status.HTTP_409_CONFLICT
        assert blocked_superseded.json()["detail"]["code"] == "PLAN_NOT_ACCEPTED"


async def test_unified_catalogue_hides_replaced_entries_but_keeps_exact_legacy_access(monkeypatch) -> None:
    for name in (
        "ADLC_HARNESS_ENABLED",
        "ADLC_CONTRACTS_ENABLED",
        "ADLC_CONTRACT_EXECUTION_ENABLED",
        "ADLC_CONTRACT_RECOVERY_ENABLED",
        "ADLC_TASK_LOOP_OPENCODE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    registry = create_default_package_registry()
    policy = create_default_package_access_policy()
    user = SimpleNamespace(id=uuid4(), username="owner")
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[adlc_api.get_node_package_registry] = lambda: registry
    app.dependency_overrides[adlc_api.get_package_access_policy] = lambda: policy
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        public = await client.get("/api/v1/adlc/node-packages")
        legacy = await client.get("/api/v1/adlc/node-packages?include_legacy=true")
        assert public.status_code == legacy.status_code == status.HTTP_200_OK
        replaced = {"coding-agent-deepseek-harness", "coding-agent-contract-harness", "task-loop-opencode"}
        assert not any(item["package_id"] in replaced for item in public.json())
        assert {item["version"] for item in public.json() if item["package_id"] == "coding-agent"} == {"0.2.0", "0.2.1"}
        assert replaced <= {item["package_id"] for item in legacy.json()}
        for package_id, version in (
            ("coding-agent-deepseek-harness", "0.3.2"),
            ("coding-agent-contract-harness", "0.2.0"),
            ("task-loop-opencode", "0.1.0"),
        ):
            exact = await client.get(f"/api/v1/adlc/node-packages/{package_id}/versions/{version}")
            assert exact.status_code == status.HTTP_200_OK
            assert exact.json()["package_id"] == package_id


async def test_regeneration_requires_the_plan_owner(monkeypatch) -> None:
    flow = _flow()
    owner = SimpleNamespace(id=uuid4(), username="owner")
    other = SimpleNamespace(id=uuid4(), username="other")
    service = _planning_service()

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    plan = await adlc_api.create_execution_plan(
        flow.id,
        current_user=owner,
        session=_session(),
        service=service,
    )

    with pytest.raises(HTTPException) as exc:
        await adlc_api.regenerate_execution_plan(
            plan.execution_plan_id,
            RegenerateExecutionPlanRequest(idempotencyKey="other-owner"),
            current_user=other,
            session=_session(),
            service=service,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_package_catalogue_is_caller_filtered_and_projects_deprecation() -> None:
    user = SimpleNamespace(id=uuid4(), username="limited-owner")
    owner_id = str(user.id)
    registry = create_default_package_registry()
    access_policy = create_default_package_access_policy()
    access_policy.set_subject_grants(
        owner_id,
        visible_packages={("approval", "0.1.0")},
        authorized_references={"control:approval"},
    )
    access_policy.deprecate_package("approval", "0.1.0")

    packages = await adlc_api.list_node_packages(
        current_user=user,
        registry=registry,
        access_policy=access_policy,
    )

    assert [(package.package_id, package.lifecycle_status.value) for package in packages] == [
        ("approval", "DEPRECATED")
    ]
    assert packages[0].status.value == "PUBLISHED"
    with pytest.raises(HTTPException) as exc:
        await adlc_api.get_node_package_version(
            "coding-agent",
            "0.1.0",
            current_user=user,
            registry=registry,
            access_policy=access_policy,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail["code"] == "PACKAGE_NOT_VISIBLE"


async def test_new_run_http_boundary_rechecks_current_capability_grants(monkeypatch) -> None:
    flow = _flow()
    user = SimpleNamespace(id=uuid4(), username="owner")
    owner_id = str(user.id)
    access_policy = create_default_package_access_policy()
    plan_service = _planning_service(access_policy)

    async def authorized_flow(**_kwargs):
        return flow

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", _allow_execute)
    plan = await adlc_api.create_execution_plan(
        flow.id,
        current_user=user,
        session=_session(),
        service=plan_service,
    )
    plan_service.approve_plan(plan.execution_plan_id, owner_id=owner_id, approved_by=owner_id)
    access_policy.set_subject_grants(
        owner_id,
        visible_packages=DEFAULT_PACKAGE_IDENTITIES,
        authorized_references=MOCK_REFERENCE_IDS - {"tool:mock-artifact"},
    )

    with pytest.raises(HTTPException) as exc:
        await adlc_api.create_run_from_execution_plan(
            plan.execution_plan_id,
            MaterializeExecutionPlanRequest(idempotencyKey="denied-new-run"),
            current_user=user,
            session=_session(),
            plan_service=plan_service,
            run_service=AdlcRunService(),
            materializer=ExecutionPlanMaterializer(),
            access_policy=access_policy,
        )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail["code"] == "CAPABILITY_NOT_AUTHORIZED"

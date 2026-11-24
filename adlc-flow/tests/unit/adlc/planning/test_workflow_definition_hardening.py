# ruff: noqa: PLR2004, S101

"""Workflow definition hardening: orphan detection, conditional branches, early gate
rejection, plan archival hydration, and definition versioning."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from langflow.adlc.blueprints import (
    NodePackageDefinition,
    PackageReference,
    package_content_digest,
)
from langflow.adlc.blueprints.errors import (
    BLUEPRINT_EDGE_INVALID,
    STAGE_DEPENDENCY_MISSING,
    STAGE_GATE_UNSUPPORTED,
    STAGE_ID_DUPLICATE,
    STAGE_ISOLATED,
)
from langflow.adlc.blueprints.models import (
    ExecutionPlan,
    PlanStatus,
)
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    MockArtifactSpec,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.adlc.packages import RegisteredNodePackage, create_default_package_registry
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.planning.validator import workflow_structure_warnings
from langflow.adlc.run_service import AdlcRunService

if TYPE_CHECKING:
    from langflow.adlc.models import WorkflowRun

IMPLEMENT_STAGE_ID = UUID("22222222-2222-4222-8222-222222222222")
APPROVAL_STAGE_ID = UUID("33333333-3333-4333-8333-333333333333")
FALLBACK_STAGE_ID = UUID("44444444-4444-4444-8444-444444444444")
ORPHAN_STAGE_ID = UUID("55555555-5555-4555-8555-555555555555")
FIXED_TIME = datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc)


def _context(flow_id: UUID) -> BlueprintParseContext:
    return BlueprintParseContext(
        flow_id=flow_id,
        project_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        name="Conditional blueprint fixture",
        description="Conditional blueprint fixture.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def _stage(
    *,
    node_id: str,
    stage_id: UUID,
    package_id: str = "coding-agent",
    stage_type: str = "IMPLEMENTATION",
    name: str,
    inputs: dict | None = None,
    expected_outputs: list[str] | None = None,
    policy_overrides: dict | None = None,
    x: float = 0,
) -> dict:
    payload = {
        "document_type": "WORKFLOW_STAGE",
        "schema_version": "0.1",
        "stage_id": str(stage_id),
        "stage_type": stage_type,
        "name": name,
        "objective": f"Complete {name.lower()}.",
        "inputs": inputs or {},
        "expected_outputs": expected_outputs or [],
        "package_ref": {"package_id": package_id, "version": "0.1.0"},
    }
    if policy_overrides:
        payload["policy_overrides"] = policy_overrides
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": x, "y": 0},
        "data": {"adlc": payload},
    }


def _edge(source: str, target: str, *, condition: str = "ON_SUCCESS") -> dict:
    edge: dict = {"id": f"{source}->{target}", "source": source, "target": target}
    if condition != "ON_SUCCESS":
        edge["data"] = {"adlc": {"condition": condition}}
    return edge


def _conditional_graph(flow_id: UUID, *, with_orphan: bool = False) -> dict:
    nodes = [
        _stage(
            node_id="implement",
            stage_id=IMPLEMENT_STAGE_ID,
            name="Implement",
            inputs={"requirement": "Build it."},
            expected_outputs=["source_patch"],
        ),
        _stage(
            node_id="approval",
            stage_id=APPROVAL_STAGE_ID,
            package_id="approval",
            stage_type="APPROVAL",
            name="Approval",
            inputs={"approval_context": "Review it."},
            expected_outputs=["approval_decision"],
            x=300,
        ),
        _stage(
            node_id="fallback",
            stage_id=FALLBACK_STAGE_ID,
            name="Fallback",
            inputs={"requirement": "Handle the failure."},
            x=300,
        ),
    ]
    if with_orphan:
        nodes.append(
            _stage(
                node_id="orphan",
                stage_id=ORPHAN_STAGE_ID,
                name="Isolated",
                inputs={"requirement": "Work alone."},
                x=600,
            )
        )
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(flow_id),
            "version": 1,
        },
        "nodes": nodes,
        "edges": [
            _edge("implement", "fallback", condition="ON_FAILURE"),
            _edge("implement", "approval"),
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _compiler() -> BlueprintCompiler:
    return BlueprintCompiler(create_default_package_resolver())


# ---------------------------------------------------------------------------
# Isolated-stage detection
# ---------------------------------------------------------------------------


def test_isolated_stage_surfaces_as_a_structural_warning() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id, with_orphan=True), _context(flow_id))

    warnings = workflow_structure_warnings(workflow)

    assert [issue.code for issue in warnings] == [STAGE_ISOLATED]
    assert warnings[0].details["stage_id"] == str(ORPHAN_STAGE_ID)
    assert warnings[0].path == "/stages/3"


def test_isolated_stage_is_a_warning_on_an_otherwise_valid_plan() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id, with_orphan=True), _context(flow_id))
    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert plan.status is PlanStatus.VALIDATED
    assert [issue.code for issue in plan.warnings] == [STAGE_ISOLATED]
    assert plan.validation_errors == []


def test_connected_stages_produce_no_isolation_warnings() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id), _context(flow_id))

    assert workflow_structure_warnings(workflow) == ()


def test_a_single_stage_workflow_is_never_reported_isolated() -> None:
    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["nodes"] = [graph["nodes"][0]]
    graph["edges"] = []

    workflow = parse_blueprint_flow(graph, _context(flow_id))

    assert workflow_structure_warnings(workflow) == ()


# ---------------------------------------------------------------------------
# Conditional edges
# ---------------------------------------------------------------------------


def test_parser_accepts_failure_and_always_edge_conditions() -> None:
    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["edges"].append(_edge("fallback", "approval", condition="ALWAYS"))

    workflow = parse_blueprint_flow(graph, _context(flow_id))

    conditions = {(edge.source_stage_id, edge.target_stage_id): edge.condition for edge in workflow.edges}
    assert conditions[(IMPLEMENT_STAGE_ID, FALLBACK_STAGE_ID)] == "ON_FAILURE"
    assert conditions[(IMPLEMENT_STAGE_ID, APPROVAL_STAGE_ID)] == "ON_SUCCESS"
    assert conditions[(FALLBACK_STAGE_ID, APPROVAL_STAGE_ID)] == "ALWAYS"


def test_parser_rejects_unknown_edge_conditions() -> None:
    from langflow.adlc.planning.errors import BlueprintParseError

    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["edges"][0]["data"]["adlc"]["condition"] = "SOMETIMES"

    with pytest.raises(BlueprintParseError) as exc_info:
        parse_blueprint_flow(graph, _context(flow_id))
    assert BLUEPRINT_EDGE_INVALID in {issue.code for issue in exc_info.value.issues}


def test_parser_still_reports_missing_dependencies_and_duplicate_ids() -> None:
    from langflow.adlc.planning.errors import BlueprintParseError

    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["edges"].append({"id": "dangling", "source": "ghost", "target": "approval"})
    with pytest.raises(BlueprintParseError) as exc_info:
        parse_blueprint_flow(graph, _context(flow_id))
    assert STAGE_DEPENDENCY_MISSING in {issue.code for issue in exc_info.value.issues}

    duplicate = _conditional_graph(flow_id)
    duplicate["nodes"][0]["data"]["adlc"]["stage_id"] = duplicate["nodes"][2]["data"]["adlc"]["stage_id"]
    with pytest.raises(BlueprintParseError) as exc_info:
        parse_blueprint_flow(duplicate, _context(flow_id))
    assert STAGE_ID_DUPLICATE in {issue.code for issue in exc_info.value.issues}


def test_compiler_emits_condition_aligned_dependencies() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id), _context(flow_id))
    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert plan.status is PlanStatus.VALIDATED
    by_stage = {task.source_workflow_stage_id: task for task in plan.tasks}
    implement_id = by_stage[IMPLEMENT_STAGE_ID].plan_task_id
    assert by_stage[FALLBACK_STAGE_ID].dependency_task_ids == [implement_id]
    assert by_stage[FALLBACK_STAGE_ID].dependency_conditions == ["ON_FAILURE"]
    assert by_stage[APPROVAL_STAGE_ID].dependency_conditions == ["ON_SUCCESS"]


# ---------------------------------------------------------------------------
# Early approval-gate rejection
# ---------------------------------------------------------------------------


def _gateable_registry():
    return create_default_package_resolver()


def test_before_task_gate_fails_at_compile_time() -> None:
    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["policy_overrides"] = {"approval": {"gate_type": "BEFORE_TASK"}}

    workflow = parse_blueprint_flow(graph, _context(flow_id))
    plan = _compile_with_gateable_registry(workflow)

    assert plan.status is PlanStatus.INVALID
    assert STAGE_GATE_UNSUPPORTED in {issue.code for issue in plan.validation_errors}
    assert plan.tasks == []


def test_approval_stage_without_gate_fails_at_compile_time() -> None:
    flow_id = uuid4()
    graph = _conditional_graph(flow_id)
    graph["nodes"][1]["data"]["adlc"]["policy_overrides"] = {"approval": {"gate_type": None}}

    workflow = parse_blueprint_flow(graph, _context(flow_id))
    plan = _compile_with_gateable_registry(workflow)

    assert plan.status is PlanStatus.INVALID
    assert STAGE_GATE_UNSUPPORTED in {issue.code for issue in plan.validation_errors}


def _compile_with_gateable_registry(workflow) -> ExecutionPlan:
    base = create_default_package_registry().get(
        PackageReference(package_id="coding-agent", version="0.1.0")
    ).definition
    payload = base.model_dump(mode="python")
    payload["override_allowlist"] = [*payload["override_allowlist"], "/policies/approval/gate_type"]
    definition = NodePackageDefinition.model_validate(payload)
    gateable = RegisteredNodePackage(
        definition=definition,
        content_digest=package_content_digest(definition),
        source_path=Path("coding-agent-gateable.json"),
    )

    approval_base = create_default_package_registry().get(
        PackageReference(package_id="approval", version="0.1.0")
    ).definition
    approval_payload = approval_base.model_dump(mode="python")
    approval_payload["override_allowlist"] = [
        *approval_payload["override_allowlist"],
        "/policies/approval/gate_type",
    ]
    approval_definition = NodePackageDefinition.model_validate(approval_payload)
    gateable_approval = RegisteredNodePackage(
        definition=approval_definition,
        content_digest=package_content_digest(approval_definition),
        source_path=Path("approval-gateable.json"),
    )


    class _Registry:
        def __init__(self, packages) -> None:
            self._packages = {
                (package.definition.package_id, package.definition.version): package for package in packages
            }

        def get(self, package_ref):
            return self._packages[(package_ref.package_id, package_ref.version)]

        def list_packages(self):
            return tuple(self._packages.values())

    resolver = create_default_package_resolver(registry=_Registry([gateable, gateable_approval]))
    compiler = BlueprintCompiler(resolver)
    return compiler.compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)


# ---------------------------------------------------------------------------
# Conditional scheduling
# ---------------------------------------------------------------------------


def _definition(
    key: str,
    *,
    dependencies: list[str] | None = None,
    conditions: list[str] | None = None,
    **overrides,
) -> AdlcTaskDefinition:
    payload: dict = {
        "id": uuid4(),
        "key": key,
        "name": key.replace("-", " ").title(),
        "task_type": "IMPLEMENTATION",
        "dependencies": dependencies or [],
        "dependency_conditions": conditions or [],
        "predetermined_output": {"summary": f"Mock result for {key}."},
        "artifact": MockArtifactSpec(
            kind="DOCUMENT",
            name=f"{key}.txt",
            media_type="text/plain",
            content=f"Mock artifact for {key}.",
        ),
        "delay_ms": 0,
    }
    payload.update(overrides)
    return AdlcTaskDefinition(**payload)


async def _start_run(service: AdlcRunService, definitions: list[AdlcTaskDefinition]) -> WorkflowRun:
    return await service.start_run(
        flow_id=uuid4(),
        flow_name="Conditional fixture",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=uuid4(), executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )


async def test_on_failure_branch_runs_and_skips_the_success_path() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("implement", simulate_failure=True),
            _definition("fallback", dependencies=["implement"], conditions=["ON_FAILURE"]),
            _definition("celebrate", dependencies=["implement"], conditions=["ON_SUCCESS"]),
        ],
    )

    by_key = {task.key: task for task in run.tasks}
    assert run.status is WorkflowRunStatus.SUCCEEDED
    assert by_key["implement"].status is TaskRunStatus.FAILED
    assert by_key["fallback"].status is TaskRunStatus.SUCCEEDED
    assert by_key["celebrate"].status is TaskRunStatus.SKIPPED


async def test_on_failure_branch_is_skipped_when_the_source_succeeds() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("implement"),
            _definition("fallback", dependencies=["implement"], conditions=["ON_FAILURE"]),
        ],
    )

    by_key = {task.key: task for task in run.tasks}
    assert run.status is WorkflowRunStatus.SUCCEEDED
    assert by_key["implement"].status is TaskRunStatus.SUCCEEDED
    assert by_key["fallback"].status is TaskRunStatus.SKIPPED


async def test_always_condition_runs_after_a_failure() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("implement", simulate_failure=True),
            _definition("notify", dependencies=["implement"], conditions=["ALWAYS"]),
            _definition("fallback", dependencies=["implement"], conditions=["ON_FAILURE"]),
        ],
    )

    by_key = {task.key: task for task in run.tasks}
    assert run.status is WorkflowRunStatus.SUCCEEDED
    assert by_key["implement"].status is TaskRunStatus.FAILED
    assert by_key["notify"].status is TaskRunStatus.SUCCEEDED
    assert by_key["fallback"].status is TaskRunStatus.SUCCEEDED


async def test_unhandled_failure_still_pauses_for_retry() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("implement", simulate_failure=True),
            _definition("verify", dependencies=["implement"]),
        ],
    )

    by_key = {task.key: task for task in run.tasks}
    assert run.status is WorkflowRunStatus.PAUSED
    assert by_key["implement"].status is TaskRunStatus.FAILED
    assert by_key["verify"].status is TaskRunStatus.PENDING

    retried = await service.retry_task(by_key["implement"].id, owner_id="owner-1")
    retried_by_key = {task.key: task for task in retried.tasks}
    assert retried.status is WorkflowRunStatus.SUCCEEDED
    assert retried_by_key["implement"].status is TaskRunStatus.SUCCEEDED
    assert retried_by_key["verify"].status is TaskRunStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Plan archival hydration
# ---------------------------------------------------------------------------


def test_restored_plan_participates_in_version_lineage() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id), _context(flow_id))
    compiler = _compiler()

    service = ExecutionPlanService(compiler)
    plan = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")

    cold_service = ExecutionPlanService(compiler)
    with pytest.raises(LookupError):
        cold_service.get_plan(plan.execution_plan_id, owner_id="owner-1")

    cold_service.restore_plan(workflow=workflow, plan=plan, owner_id="owner-1")
    fetched = cold_service.get_plan(plan.execution_plan_id, owner_id="owner-1")
    assert fetched.execution_plan_id == plan.execution_plan_id

    successor = cold_service.create_plan(deepcopy(workflow), owner_id="owner-1", generated_by="owner-1")
    assert successor.plan_version == 2
    assert successor.supersedes_plan_id == plan.execution_plan_id


def test_restoring_does_not_let_a_stale_snapshot_regress_versions() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id), _context(flow_id))
    compiler = _compiler()

    service = ExecutionPlanService(compiler)
    first = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    second = service.create_plan(deepcopy(workflow), owner_id="owner-1", generated_by="owner-1")

    cold_service = ExecutionPlanService(compiler)
    cold_service.restore_plan(workflow=workflow, plan=first, owner_id="owner-1")
    cold_service.restore_plan(workflow=workflow, plan=second, owner_id="owner-1")

    successor = cold_service.regenerate_plan(
        deepcopy(workflow),
        owner_id="owner-1",
        generated_by="owner-1",
        supersedes_plan_id=second.execution_plan_id,
        idempotency_key="key-1",
    )
    assert successor.plan_version == 3
    with pytest.raises(Exception, match="Only the latest"):
        cold_service.regenerate_plan(
            deepcopy(workflow),
            owner_id="owner-1",
            generated_by="owner-1",
            supersedes_plan_id=second.execution_plan_id,
            idempotency_key="key-2",
        )


# ---------------------------------------------------------------------------
# Durable archive + definition versions (SQLite in-memory)
# ---------------------------------------------------------------------------


@pytest.fixture(name="archive_session")
async def archive_session_fixture():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    import langflow.services.database.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def test_execution_plan_archive_round_trip(archive_session) -> None:
    from langflow.services.database.models.adlc_execution_plan import (
        get_execution_plan_archive,
        save_execution_plan,
    )

    flow_id = uuid4()
    workflow = parse_blueprint_flow(_conditional_graph(flow_id), _context(flow_id))
    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    await save_execution_plan(
        archive_session,
        owner_id="owner-1",
        workflow_definition_id=plan.workflow_definition_id,
        workflow_definition_version=plan.workflow_definition_version,
        plan_version=plan.plan_version,
        status=plan.status.value,
        validation_status=plan.validation_status.value,
        supersedes_plan_id=plan.supersedes_plan_id,
        approval_required=plan.approval_required,
        generated_at=plan.generated_at,
        plan_payload=plan.model_dump(mode="json"),
        workflow_payload=workflow.model_dump(mode="json"),
        execution_plan_id=plan.execution_plan_id,
    )
    await archive_session.commit()

    row = await get_execution_plan_archive(archive_session, plan_id=plan.execution_plan_id, owner_id="owner-1")
    assert row is not None
    restored = ExecutionPlan.model_validate(row.plan_payload)
    assert restored == plan

    assert await get_execution_plan_archive(
        archive_session, plan_id=plan.execution_plan_id, owner_id="someone-else"
    ) is None


async def test_definition_version_publish_supersedes_previous(archive_session) -> None:
    from langflow.services.database.models.adlc_workflow_definition_version import (
        get_definition_version_row,
        get_definition_version_rows,
        get_next_definition_version_number,
        publish_definition_version,
    )

    flow_id = uuid4()
    graph = _conditional_graph(flow_id)

    await publish_definition_version(
        archive_session, flow_id=flow_id, version_number=1, created_by="owner-1", data=graph
    )
    await publish_definition_version(
        archive_session, flow_id=flow_id, version_number=2, created_by="owner-1", data=graph
    )

    rows = await get_definition_version_rows(archive_session, flow_id=flow_id, created_by="owner-1")
    assert {row.version_number: row.status for row in rows} == {1: "SUPERSEDED", 2: "PUBLISHED"}
    assert await get_next_definition_version_number(archive_session, flow_id) == 3

    fetched = await get_definition_version_row(
        archive_session, flow_id=flow_id, version_number=1, created_by="owner-1"
    )
    assert fetched is not None
    assert fetched.data == graph


async def test_definition_versions_are_owner_scoped(archive_session) -> None:
    from langflow.services.database.models.adlc_workflow_definition_version import (
        get_definition_version_rows,
        publish_definition_version,
    )

    flow_id = uuid4()
    await publish_definition_version(
        archive_session, flow_id=flow_id, version_number=1, created_by="owner-1", data={}
    )

    assert await get_definition_version_rows(archive_session, flow_id=flow_id, created_by="owner-2") == []

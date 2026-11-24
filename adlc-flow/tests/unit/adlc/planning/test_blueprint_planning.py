# ruff: noqa: PLR2004, S101

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from langflow.adlc.blueprints import NodePackageDefinition, PackageReference, package_content_digest
from langflow.adlc.blueprints.errors import (
    BLUEPRINT_MARKER_MISSING,
    CAPABILITY_NOT_AUTHORIZED,
    PACKAGE_NOT_FOUND,
    PACKAGE_NOT_VISIBLE,
    PACKAGE_OVERRIDE_FORBIDDEN,
    STAGE_BINDING_INCOMPATIBLE,
    STAGE_DEPENDENCY_CYCLE,
    STAGE_DEPENDENCY_MISSING,
    STAGE_ID_DUPLICATE,
    STAGE_INPUT_UNBOUND,
    WORKFLOW_HAS_NO_ROOT,
)
from langflow.adlc.blueprints.models import PlanStatus, PlanValidationStatus
from langflow.adlc.observability import (
    AdlcObservationOutcome,
    AdlcObservationType,
    InMemoryAdlcObservabilitySink,
)
from langflow.adlc.packages.defaults import (
    MOCK_REFERENCE_IDS,
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.packages.registry import RegisteredNodePackage
from langflow.adlc.packages.resolver import NodePackageResolver, StaticReferenceRegistry
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.errors import (
    PLAN_STATE_CONFLICT,
    BlueprintParseError,
    ExecutionPlanNotFoundError,
    ExecutionPlanStateError,
)
from langflow.adlc.planning.parser import (
    BlueprintParseContext,
    has_adlc_blueprint_marker,
    is_adlc_blueprint,
    parse_blueprint_flow,
)
from langflow.adlc.planning.service import ExecutionPlanService

if TYPE_CHECKING:
    from langflow.adlc.observability import AdlcObservabilitySink
    from langflow.adlc.packages.access import PackageAccessPolicy

IMPLEMENT_STAGE_ID = UUID("22222222-2222-4222-8222-222222222222")
APPROVAL_STAGE_ID = UUID("33333333-3333-4333-8333-333333333333")
FIXED_TIME = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)


def _context(flow_id: UUID) -> BlueprintParseContext:
    return BlueprintParseContext(
        flow_id=flow_id,
        project_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        name="Implementation and approval",
        description="A marked blueprint fixture.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def _stage(
    *,
    node_id: str,
    stage_id: UUID,
    package_id: str,
    stage_type: str,
    name: str,
    inputs: dict | None = None,
    expected_outputs: list[str] | None = None,
    x: float = 0,
) -> dict:
    return {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": x, "y": 0},
        "data": {
            "adlc": {
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
        },
    }


def _graph(flow_id: UUID) -> dict:
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(flow_id),
            "version": 1,
        },
        "nodes": [
            _stage(
                node_id="implement",
                stage_id=IMPLEMENT_STAGE_ID,
                package_id="coding-agent",
                stage_type="IMPLEMENTATION",
                name="Implement",
                inputs={"requirement": "Build the scoped feature."},
                expected_outputs=["source_patch"],
            ),
            _stage(
                node_id="approval",
                stage_id=APPROVAL_STAGE_ID,
                package_id="approval",
                stage_type="APPROVAL",
                name="Approval",
                inputs={"approval_context": "Review the implementation artifact."},
                expected_outputs=["approval_decision"],
                x=300,
            ),
            {"id": "note", "type": "noteNode", "position": {"x": 20, "y": 200}, "data": {}},
        ],
        "edges": [{"id": "dependency", "source": "implement", "target": "approval"}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _compiler(
    access_policy: PackageAccessPolicy | None = None,
    observability_sink: AdlcObservabilitySink | None = None,
) -> BlueprintCompiler:
    resolver = create_default_package_resolver(
        access_policy=access_policy,
        observability_sink=observability_sink,
    )
    return BlueprintCompiler(resolver, observability_sink=observability_sink)


def test_requirement_block_compiles_through_the_existing_plan_pipeline() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["inputs"] = {}
    graph["nodes"].append(
        {
            "id": "brief",
            "type": "adlcStageNode",
            "data": {
                "adlcDraft": {
                    "document_type": "ADLC_AUTHORING_BLOCK",
                    "schema_version": "0.1",
                    "block_id": str(uuid4()),
                    "kind": "REQUIREMENT",
                    "name": "Requirement",
                    "objective": "Implement user management.",
                    "requirement": "Add the user CRUD endpoints and verify the candidate.",
                }
            },
        }
    )
    graph["edges"].append(
        {
            "id": "brief-input",
            "source": "brief",
            "target": "implement",
            "data": {
                "adlc": {
                    "document_type": "WORKFLOW_EDGE",
                    "schema_version": "0.1",
                    "edge_id": str(uuid4()),
                    "condition": "ON_SUCCESS",
                    "bindings": [],
                    "metadata": {"authoring_input": "requirement"},
                }
            },
        }
    )
    source = deepcopy(graph)
    workflow = parse_blueprint_flow(graph, _context(flow_id))
    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)
    assert plan.status is PlanStatus.VALIDATED
    assert len(plan.tasks) == 2
    assert graph == source
    stage = next(stage for stage in workflow.stages if stage.stage_id == IMPLEMENT_STAGE_ID)
    assert stage.inputs["requirement"] == "Add the user CRUD endpoints and verify the candidate."
    assert stage.metadata["authoring_inputs"]["requirement"]["name"] == "Requirement"
    graph["nodes"][-1]["data"]["adlcDraft"]["kind"] = "PLANNED_PACKAGE"
    with pytest.raises(BlueprintParseError) as exc:
        parse_blueprint_flow(graph, _context(flow_id))
    assert exc.value.issues[0].code == "AUTHORING_PACKAGE_WIP"


def test_manual_orchestrator_migration_compiles_without_changing_the_source_fixture() -> None:
    fixture_root = Path(__file__).resolve().parents[3] / "fixtures" / "adlc-planning"
    source = json.loads((fixture_root / "orchestrator.json").read_text("utf-8"))
    migrated = json.loads((fixture_root / "orchestrator-blueprint.json").read_text("utf-8"))
    flow_id = UUID(migrated["id"])

    assert not has_adlc_blueprint_marker(source["data"])
    assert len(source["data"]["nodes"]) == 7
    assert has_adlc_blueprint_marker(migrated["data"])

    workflow = parse_blueprint_flow(migrated["data"], _context(flow_id))
    plan = _compiler().compile(
        workflow,
        plan_version=1,
        generated_by="owner-1",
        generated_at=FIXED_TIME,
    )

    assert plan.status is PlanStatus.VALIDATED
    assert len(plan.tasks) == 1
    assert plan.tasks[0].name == "Orchestrator"
    assert plan.resolved_node_specs[0].package_ref.package_id == "coding-agent"
    assert plan.resolved_node_specs[0].package_ref.version == "0.1.0"


class _StaticPackageRegistry:
    def __init__(self, packages: list[RegisteredNodePackage]) -> None:
        self._packages = {(package.definition.package_id, package.definition.version): package for package in packages}

    def get(self, package_ref: PackageReference) -> RegisteredNodePackage:
        return self._packages[(package_ref.package_id, package_ref.version)]

    def list_packages(self) -> tuple[RegisteredNodePackage, ...]:
        return tuple(self._packages[key] for key in sorted(self._packages))


def _package_with_interface(
    package_id: str,
    *,
    input_name: str,
    input_schema: str,
    output_name: str,
    output_schema: str,
) -> RegisteredNodePackage:
    base = (
        create_default_package_registry().get(PackageReference(package_id="coding-agent", version="0.1.0")).definition
    )
    payload = base.model_dump(mode="python")
    payload.update(
        {
            "package_id": package_id,
            "name": package_id,
            "interface": {
                "inputs": [
                    {
                        "name": input_name,
                        "schema_ref": input_schema,
                        "required": True,
                        "multiple": False,
                        "description": "Test input.",
                    }
                ],
                "outputs": [
                    {
                        "name": output_name,
                        "schema_ref": output_schema,
                        "required": True,
                        "multiple": False,
                        "description": "Test output.",
                    }
                ],
            },
        }
    )
    definition = NodePackageDefinition.model_validate(payload)
    return RegisteredNodePackage(
        definition=definition,
        content_digest=package_content_digest(definition),
        source_path=Path(f"{package_id}.json"),
    )


def _issue_codes(exc: BlueprintParseError) -> set[str]:
    return {issue.code for issue in exc.issues}


def test_saved_flow_data_example_parses_as_contract_v0_1() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    example_path = (
        repository_root / "adlc-contracts" / "workflow" / "v0.1" / "examples" / "langflow-blueprint-flow-data.json"
    )
    graph = json.loads(example_path.read_text(encoding="utf-8"))
    flow_id = UUID(graph["adlc"]["workflow_definition_id"])

    workflow = parse_blueprint_flow(graph, _context(flow_id))

    assert len(workflow.stages) == 2
    assert len(workflow.edges) == 1


def test_parser_requires_an_explicit_blueprint_marker() -> None:
    flow_id = uuid4()
    native_graph = {"nodes": [], "edges": []}

    assert not has_adlc_blueprint_marker(native_graph)
    assert not is_adlc_blueprint(native_graph)
    with pytest.raises(BlueprintParseError) as exc:
        parse_blueprint_flow(native_graph, _context(flow_id))

    assert _issue_codes(exc.value) == {BLUEPRINT_MARKER_MISSING}


def test_parser_normalizes_stages_edges_and_ignores_presentation_nodes() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)

    assert has_adlc_blueprint_marker(graph)
    assert is_adlc_blueprint(graph)
    workflow = parse_blueprint_flow(graph, _context(flow_id))

    assert workflow.workflow_definition_id == flow_id
    assert [stage.stage_id for stage in workflow.stages] == [IMPLEMENT_STAGE_ID, APPROVAL_STAGE_ID]
    assert workflow.stages[0].inputs == {"requirement": "Build the scoped feature."}
    assert len(workflow.edges) == 1
    assert workflow.edges[0].source_stage_id == IMPLEMENT_STAGE_ID
    assert workflow.edges[0].target_stage_id == APPROVAL_STAGE_ID


def test_parser_reports_no_root_and_cycle_with_stable_codes() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["edges"].append({"source": "approval", "target": "implement"})

    with pytest.raises(BlueprintParseError) as exc:
        parse_blueprint_flow(graph, _context(flow_id))

    assert {WORKFLOW_HAS_NO_ROOT, STAGE_DEPENDENCY_CYCLE} <= _issue_codes(exc.value)


def test_parser_reports_duplicate_stage_identity() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][1]["data"]["adlc"]["stage_id"] = str(IMPLEMENT_STAGE_ID)

    with pytest.raises(BlueprintParseError) as exc:
        parse_blueprint_flow(graph, _context(flow_id))

    assert STAGE_ID_DUPLICATE in _issue_codes(exc.value)


def test_parser_reports_an_edge_to_a_missing_stage_node() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["edges"][0]["target"] = "missing"

    with pytest.raises(BlueprintParseError) as exc:
        parse_blueprint_flow(graph, _context(flow_id))

    assert STAGE_DEPENDENCY_MISSING in _issue_codes(exc.value)


def test_compiler_builds_a_deterministic_traceable_plan() -> None:
    flow_id = uuid4()
    first_graph = _graph(flow_id)
    second_graph = deepcopy(first_graph)
    second_graph["nodes"].reverse()
    second_graph["nodes"][1]["position"] = {"x": 999, "y": 777}
    first = parse_blueprint_flow(first_graph, _context(flow_id))
    second = parse_blueprint_flow(second_graph, _context(flow_id))

    first_plan = _compiler().compile(first, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)
    second_plan = _compiler().compile(second, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert first_plan.status is PlanStatus.VALIDATED
    assert first_plan.validation_status is PlanValidationStatus.VALID
    assert first_plan.execution_plan_id == second_plan.execution_plan_id
    assert first_plan.metadata["workflow_digest"] == second_plan.metadata["workflow_digest"]
    assert [task.plan_task_id for task in first_plan.tasks] == [task.plan_task_id for task in second_plan.tasks]
    assert [task.source_workflow_stage_id for task in first_plan.tasks] == [
        IMPLEMENT_STAGE_ID,
        APPROVAL_STAGE_ID,
    ]
    assert first_plan.tasks[1].dependency_task_ids == [first_plan.tasks[0].plan_task_id]
    assert first_plan.approval_required
    assert all(spec.package_ref.content_digest for spec in first_plan.resolved_node_specs)


def test_compiler_returns_an_invalid_read_only_plan_for_unknown_package() -> None:
    flow_id = uuid4()
    sink = InMemoryAdlcObservabilitySink()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["package_ref"]["package_id"] = "missing-package"
    workflow = parse_blueprint_flow(graph, _context(flow_id))

    plan = _compiler(observability_sink=sink).compile(
        workflow,
        plan_version=1,
        generated_by="owner-1",
        generated_at=FIXED_TIME,
    )

    assert plan.status is PlanStatus.INVALID
    assert plan.validation_status is PlanValidationStatus.INVALID
    assert not plan.tasks
    assert PACKAGE_NOT_FOUND in {issue.code for issue in plan.validation_errors}
    resolution = next(
        observation for observation in sink.observations if observation.source_workflow_stage_id == IMPLEMENT_STAGE_ID
    )
    validation = sink.observations[-1]
    assert resolution.event_type is AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED
    assert resolution.outcome is AdlcObservationOutcome.FAILED
    assert resolution.error_code == PACKAGE_NOT_FOUND
    assert resolution.package_id is None
    assert validation.event_type is AdlcObservationType.PLAN_VALIDATION_COMPLETED
    assert validation.outcome is AdlcObservationOutcome.INVALID
    assert validation.execution_plan_id == plan.execution_plan_id
    assert validation.validation_issue_count == len(plan.validation_errors)
    assert PACKAGE_NOT_FOUND in validation.validation_issue_codes


def test_compiler_projects_forbidden_overrides_as_plan_validation_errors() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["configuration_overrides"] = {"temperature": 0.5}
    workflow = parse_blueprint_flow(graph, _context(flow_id))

    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert plan.status is PlanStatus.INVALID
    assert PACKAGE_OVERRIDE_FORBIDDEN in {issue.code for issue in plan.validation_errors}


def test_compiler_projects_hidden_package_as_a_stage_validation_error() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    access_policy = create_default_package_access_policy()
    access_policy.set_subject_grants(
        "owner-1",
        visible_packages={("approval", "0.1.0")},
        authorized_references=MOCK_REFERENCE_IDS,
    )

    plan = _compiler(access_policy).compile(
        workflow,
        plan_version=1,
        generated_by="owner-1",
        generated_at=FIXED_TIME,
    )

    assert plan.status is PlanStatus.INVALID
    hidden = next(issue for issue in plan.validation_errors if issue.code == PACKAGE_NOT_VISIBLE)
    assert hidden.details["stage_id"] == str(IMPLEMENT_STAGE_ID)


def test_compiler_projects_unauthorized_capability_as_a_stage_validation_error() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    access_policy = create_default_package_access_policy()
    access_policy.set_subject_grants(
        "owner-1",
        visible_packages={("approval", "0.1.0"), ("coding-agent", "0.1.0")},
        authorized_references=MOCK_REFERENCE_IDS - {"tool:mock-artifact"},
    )

    plan = _compiler(access_policy).compile(
        workflow,
        plan_version=1,
        generated_by="owner-1",
        generated_at=FIXED_TIME,
    )

    assert plan.status is PlanStatus.INVALID
    denied = next(issue for issue in plan.validation_errors if issue.code == CAPABILITY_NOT_AUTHORIZED)
    assert denied.details["reference"] == "tool:mock-artifact"
    assert denied.details["stage_id"] == str(IMPLEMENT_STAGE_ID)


def test_compiler_requires_a_value_or_binding_for_each_required_input() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    approval = graph["nodes"][1]
    approval["data"]["adlc"].update(
        {
            "package_ref": {"package_id": "coding-agent", "version": "0.1.0"},
            "inputs": {},
            "expected_outputs": ["source_patch"],
        }
    )
    workflow = parse_blueprint_flow(graph, _context(flow_id))

    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert plan.status is PlanStatus.INVALID
    assert STAGE_INPUT_UNBOUND in {issue.code for issue in plan.validation_errors}


def test_compiler_rejects_incompatible_edge_slot_bindings() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["edges"][0]["data"] = {
        "adlc": {
            "document_type": "WORKFLOW_EDGE",
            "schema_version": "0.1",
            "bindings": [{"source_output": "source_patch", "target_input": "approval_context"}],
        }
    }
    workflow = parse_blueprint_flow(graph, _context(flow_id))

    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)

    assert plan.status is PlanStatus.INVALID
    assert STAGE_BINDING_INCOMPATIBLE in {issue.code for issue in plan.validation_errors}


def test_compiler_materializes_a_compatible_named_slot_binding() -> None:
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["package_ref"]["package_id"] = "patch-producer"
    graph["nodes"][1]["data"]["adlc"].update(
        {
            "package_ref": {"package_id": "patch-consumer", "version": "0.1.0"},
            "stage_type": "IMPLEMENTATION",
            "inputs": {},
            "expected_outputs": ["review_result"],
        }
    )
    graph["edges"][0]["data"] = {
        "adlc": {
            "bindings": [{"source_output": "source_patch", "target_input": "source_patch"}],
        }
    }
    workflow = parse_blueprint_flow(graph, _context(flow_id))
    packages = [
        _package_with_interface(
            "patch-producer",
            input_name="requirement",
            input_schema="adlc://schemas/requirement/0.1",
            output_name="source_patch",
            output_schema="adlc://schemas/source-patch/0.1",
        ),
        _package_with_interface(
            "patch-consumer",
            input_name="source_patch",
            input_schema="adlc://schemas/source-patch/0.1",
            output_name="review_result",
            output_schema="adlc://schemas/review-result/0.1",
        ),
    ]
    resolver = NodePackageResolver(_StaticPackageRegistry(packages), StaticReferenceRegistry(MOCK_REFERENCE_IDS))

    plan = BlueprintCompiler(resolver).compile(
        workflow,
        plan_version=1,
        generated_by="owner-1",
        generated_at=FIXED_TIME,
    )

    assert plan.status is PlanStatus.VALIDATED
    assert plan.tasks[1].input_bindings[0].source_plan_task_id == plan.tasks[0].plan_task_id
    assert plan.tasks[1].input_bindings[0].target_input == "source_patch"


def test_plan_service_versions_snapshots_and_enforces_owner_scope() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    service = ExecutionPlanService(_compiler())

    first = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    approved = service.approve_plan(
        first.execution_plan_id,
        owner_id="owner-1",
        approved_by="owner-1",
        comment="Approve version one.",
    )
    second = service.regenerate_plan(
        workflow,
        owner_id="owner-1",
        generated_by="owner-1",
        supersedes_plan_id=approved.execution_plan_id,
        idempotency_key="regenerate-v2",
    )
    duplicate = service.regenerate_plan(
        workflow,
        owner_id="owner-1",
        generated_by="owner-1",
        supersedes_plan_id=approved.execution_plan_id,
        idempotency_key="regenerate-v2",
    )
    historical = service.get_plan(first.execution_plan_id, owner_id="owner-1")

    assert first.plan_version == 1
    assert second.plan_version == 2
    assert first.execution_plan_id != second.execution_plan_id
    assert second.supersedes_plan_id == first.execution_plan_id
    assert second.status is PlanStatus.VALIDATED
    assert second.approved_by is None
    assert second.approved_at is None
    assert duplicate == second
    assert historical.status is PlanStatus.SUPERSEDED
    assert historical.tasks == approved.tasks
    assert historical.resolved_node_specs == approved.resolved_node_specs
    assert historical.approved_by == approved.approved_by
    assert historical.approved_at == approved.approved_at
    with pytest.raises(ExecutionPlanStateError) as state_error:
        service.validate_plan(first.execution_plan_id, owner_id="owner-1")
    assert state_error.value.code == PLAN_STATE_CONFLICT
    with pytest.raises(ExecutionPlanStateError) as stale_regeneration:
        service.regenerate_plan(
            workflow,
            owner_id="owner-1",
            generated_by="owner-1",
            supersedes_plan_id=approved.execution_plan_id,
            idempotency_key="different-request",
        )
    assert stale_regeneration.value.code == PLAN_STATE_CONFLICT
    caller_copy = service.get_plan(second.execution_plan_id, owner_id="owner-1")
    caller_copy.metadata["caller_mutation"] = True
    assert "caller_mutation" not in service.get_plan(second.execution_plan_id, owner_id="owner-1").metadata
    third = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    assert third.plan_version == 3
    assert third.supersedes_plan_id == second.execution_plan_id
    assert service.get_plan(second.execution_plan_id, owner_id="owner-1").status is PlanStatus.SUPERSEDED
    with pytest.raises(ExecutionPlanNotFoundError):
        service.get_plan(first.execution_plan_id, owner_id="owner-2")


def test_corrected_plan_supersedes_an_invalid_predecessor() -> None:
    flow_id = uuid4()
    invalid_graph = _graph(flow_id)
    invalid_graph["nodes"][0]["data"]["adlc"]["inputs"] = {}
    invalid_workflow = parse_blueprint_flow(invalid_graph, _context(flow_id))
    corrected_workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    service = ExecutionPlanService(_compiler())

    invalid = service.create_plan(invalid_workflow, owner_id="owner-1", generated_by="owner-1")
    corrected = service.regenerate_plan(
        corrected_workflow,
        owner_id="owner-1",
        generated_by="owner-1",
        supersedes_plan_id=invalid.execution_plan_id,
        idempotency_key="correct-invalid-plan",
    )
    historical = service.get_plan(invalid.execution_plan_id, owner_id="owner-1")

    assert invalid.status is PlanStatus.INVALID
    assert corrected.status is PlanStatus.VALIDATED
    assert corrected.supersedes_plan_id == invalid.execution_plan_id
    assert historical.status is PlanStatus.SUPERSEDED
    assert historical.validation_status is PlanValidationStatus.INVALID
    assert historical.validation_errors == invalid.validation_errors
    assert historical.tasks == []

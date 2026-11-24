# ruff: noqa: PLR2004, S101

"""End-to-end pipeline invariants across the three identity spaces.

WorkflowDefinition (authored), ExecutionPlan (compiled snapshot), and
WorkflowRun (one execution) must stay distinct identity spaces that reference
each other explicitly instead of reusing identifiers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from langflow.adlc.blueprints.models import PlanStatus, PlanValidationStatus
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import TaskRunStatus, WorkflowExecutionMode, WorkflowRunStatus
from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService

FIXED_TIME = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
STAGE_IDS = [UUID(f"00000000-0000-4000-8000-{index:012d}") for index in range(1, 4)]


def _stage(index: int, *, name: str, package_id: str = "coding-agent") -> dict:
    approval = package_id == "approval"
    return {
        "id": f"stage-{index}",
        "type": "adlcStageNode",
        "position": {"x": index * 220, "y": 0},
        "data": {
            "adlc": {
                "document_type": "WORKFLOW_STAGE",
                "schema_version": "0.1",
                "stage_id": str(STAGE_IDS[index - 1]),
                "stage_type": "APPROVAL" if approval else "IMPLEMENTATION",
                "name": name,
                "objective": f"Complete {name.lower()}.",
                "inputs": (
                    {"approval_context": "Review the verified work."}
                    if approval
                    else {"requirement": f"Requirement for {name}."}
                ),
                "expected_outputs": ["approval_decision" if approval else "source_patch"],
                "package_ref": {"package_id": package_id, "version": "0.1.0"},
                "configuration_overrides": {} if approval else {"delay_ms": 0},
            }
        },
    }


def _graph(flow_id: UUID, *, include_approval: bool = True) -> dict:
    nodes = [_stage(1, name="Plan"), _stage(2, name="Implement")]
    edges = [{"source": "stage-1", "target": "stage-2"}]
    if include_approval:
        nodes.append(_stage(3, name="Approval", package_id="approval"))
        edges.append({"source": "stage-2", "target": "stage-3"})
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(flow_id),
            "version": 1,
        },
        "nodes": nodes,
        "edges": edges,
    }


def _context(flow_id: UUID) -> BlueprintParseContext:
    return BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Pipeline invariant fixture",
        description="Deterministic planning pipeline invariants.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def _plan_service(flow_id: UUID, *, include_approval: bool = True) -> tuple[ExecutionPlanService, object]:
    workflow = parse_blueprint_flow(
        _graph(flow_id, include_approval=include_approval),
        _context(flow_id),
    )
    service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    return service, plan


async def test_workflow_definition_execution_plan_and_run_stay_distinct_identity_spaces() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    assert workflow.workflow_definition_id == flow_id

    service, plan = _plan_service(flow_id)

    assert plan.workflow_definition_id == flow_id
    assert plan.execution_plan_id != flow_id
    assert plan.status is PlanStatus.VALIDATED
    assert plan.validation_status is PlanValidationStatus.VALID
    assert {stage.stage_id for stage in workflow.stages} == {
        task.source_workflow_stage_id for task in plan.tasks
    }
    assert {task.plan_task_id for task in plan.tasks}.isdisjoint({flow_id, plan.execution_plan_id})

    approved = service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    assert approved.status is PlanStatus.APPROVED
    assert approved.approved_at is not None
    assert approved.execution_plan_id == plan.execution_plan_id

    run = await ExecutionPlanMaterializer().materialize(
        approved.execution_plan_id,
        idempotency_key="identity-run-1",
        owner_id="owner-1",
        plan_service=service,
        run_service=AdlcRunService(MockExecutor()),
        access_policy=create_default_package_access_policy(),
    )

    assert run.id not in {flow_id, plan.execution_plan_id}
    assert run.flow_id == flow_id
    assert run.execution_plan_id == plan.execution_plan_id
    assert run.execution_mode is WorkflowExecutionMode.EXECUTION_PLAN
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL

    plan_task_ids = {task.plan_task_id for task in approved.tasks}
    for task in run.tasks:
        trace = task.plan_traceability
        assert trace is not None
        assert trace.plan_task_id in plan_task_ids
        assert task.id != task.task_definition_id
        assert task.task_definition_id == trace.plan_task_id
    assert {task.status for task in run.tasks} == {TaskRunStatus.SUCCEEDED, TaskRunStatus.WAITING_APPROVAL}
    assert service.get_plan(plan.execution_plan_id, owner_id="owner-1").status is PlanStatus.EXECUTING


async def test_one_accepted_plan_materializes_distinct_runs_per_idempotency_key() -> None:
    flow_id = uuid4()
    service, plan = _plan_service(flow_id, include_approval=False)
    assert plan.status is PlanStatus.VALIDATED
    assert not plan.approval_required

    materializer = ExecutionPlanMaterializer()
    run_service = AdlcRunService(MockExecutor())
    access_policy = create_default_package_access_policy()
    first = await materializer.materialize(
        plan.execution_plan_id,
        idempotency_key="replay-key-1",
        owner_id="owner-1",
        plan_service=service,
        run_service=run_service,
        access_policy=access_policy,
    )
    second = await materializer.materialize(
        plan.execution_plan_id,
        idempotency_key="replay-key-2",
        owner_id="owner-1",
        plan_service=service,
        run_service=run_service,
        access_policy=access_policy,
    )

    assert first.id != second.id
    assert first.execution_plan_id == second.execution_plan_id == plan.execution_plan_id
    assert first.status is second.status is WorkflowRunStatus.SUCCEEDED
    assert {task.key for task in first.tasks} == {task.key for task in second.tasks}
    assert {task.id for task in first.tasks}.isdisjoint({task.id for task in second.tasks})
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in [*first.tasks, *second.tasks])
    assert service.get_plan(plan.execution_plan_id, owner_id="owner-1").status is PlanStatus.EXECUTING

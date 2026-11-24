# ruff: noqa: PLR2004, S101

"""Deterministic end-to-end orchestration demo: "Implement User Feature".

The scenario walks the complete planning pipeline with the mock execution
plane: marked graph -> WorkflowDefinition -> ExecutionPlan -> WorkflowRun ->
scheduler -> parallel readiness (T3/T4) -> T4 attempt #1 FAILED -> authorized
retry -> attempt #2 SUCCEEDED -> Testing/Review evidence -> Quality Gate ->
WorkflowRun SUCCEEDED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from langflow.adlc.blueprints.models import PlanStatus, PlanValidationStatus
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import TaskRunStatus, WorkflowRunStatus
from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.quality_gate import (
    MockReviewService,
    QualityGateDecision,
    ReviewDecision,
    evaluate_quality_gate,
)
from langflow.adlc.run_service import AdlcRunService

OWNER = "demo-owner"
FIXED_TIME = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


def _stage(index: int, name: str, stage_type: str, *, override: dict | None = None) -> dict:
    return {
        "id": f"stage-{index}",
        "type": "adlcStageNode",
        "position": {"x": index * 220, "y": 0},
        "data": {
            "adlc": {
                "document_type": "WORKFLOW_STAGE",
                "schema_version": "0.1",
                "stage_id": str(UUID(f"11111111-1111-4111-8111-{index:012d}")),
                "stage_type": stage_type,
                "name": name,
                "objective": f"Complete {name.lower()} for the user feature.",
                "inputs": {"requirement": f"Implement the user feature: {name.lower()}."},
                "expected_outputs": ["source_patch"],
                "package_ref": {"package_id": "coding-agent", "version": "0.1.0"},
                "configuration_overrides": override or {"delay_ms": 0},
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
            _stage(1, "Analyze Requirements", "REQUIREMENTS"),
            _stage(2, "Create Design", "DESIGN"),
            _stage(3, "Implement Model", "IMPLEMENTATION"),
            _stage(
                4,
                "Implement API",
                "IMPLEMENTATION",
                override={"delay_ms": 0, "simulate_failure": True},
            ),
            _stage(5, "Integration", "IMPLEMENTATION"),
            _stage(6, "Testing", "TESTING"),
            _stage(7, "Review", "REVIEW"),
        ],
        "edges": [
            {"source": "stage-1", "target": "stage-2"},
            {"source": "stage-2", "target": "stage-3"},
            {"source": "stage-2", "target": "stage-4"},
            {"source": "stage-3", "target": "stage-5"},
            {"source": "stage-4", "target": "stage-5"},
            {"source": "stage-5", "target": "stage-6"},
            {"source": "stage-6", "target": "stage-7"},
        ],
    }


def _context(flow_id: UUID) -> BlueprintParseContext:
    return BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Implement User Feature",
        description="Deterministic end-to-end orchestration demo.",
        created_by=OWNER,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


async def test_implement_user_feature_e2e_with_parallel_readiness_retry_and_quality_gate() -> None:
    flow_id = uuid4()
    workflow = parse_blueprint_flow(_graph(flow_id), _context(flow_id))
    assert workflow.workflow_definition_id == flow_id

    plan_service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = plan_service.create_plan(workflow, owner_id=OWNER, generated_by=OWNER)
    assert plan.status is PlanStatus.VALIDATED
    assert plan.validation_status is PlanValidationStatus.VALID
    assert not plan.approval_required
    assert len(plan.tasks) == 7

    by_name = {task.name: task for task in plan.tasks}
    design = by_name["Create Design"]
    model = by_name["Implement Model"]
    api = by_name["Implement API"]
    integration = by_name["Integration"]
    assert model.dependency_task_ids == [design.plan_task_id]
    assert api.dependency_task_ids == [design.plan_task_id]
    assert set(integration.dependency_task_ids) == {model.plan_task_id, api.plan_task_id}
    assert by_name["Testing"].dependency_task_ids == [integration.plan_task_id]
    assert by_name["Review"].dependency_task_ids == [by_name["Testing"].plan_task_id]

    run_service = AdlcRunService(MockExecutor())
    run = await ExecutionPlanMaterializer().materialize(
        plan.execution_plan_id,
        idempotency_key="demo-run-1",
        owner_id=OWNER,
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    assert plan_service.get_plan(plan.execution_plan_id, owner_id=OWNER).status is PlanStatus.EXECUTING

    tasks = {task.name: task for task in run.tasks}
    assert run.status is WorkflowRunStatus.PAUSED
    assert tasks["Analyze Requirements"].status is TaskRunStatus.SUCCEEDED
    assert tasks["Create Design"].status is TaskRunStatus.SUCCEEDED
    assert tasks["Implement Model"].status is TaskRunStatus.SUCCEEDED
    assert tasks["Implement API"].status is TaskRunStatus.FAILED
    assert tasks["Integration"].status is TaskRunStatus.PENDING
    assert tasks["Testing"].status is TaskRunStatus.PENDING
    assert tasks["Review"].status is TaskRunStatus.PENDING

    def _first_event(event_type: str, task_run_id: UUID):
        return next(
            event
            for event in run.events
            if event.event_type == event_type and event.task_run_id == task_run_id
        )

    design_succeeded = _first_event("task_run.succeeded", tasks["Create Design"].id)
    model_ready = _first_event("task_run.ready", tasks["Implement Model"].id)
    api_ready = _first_event("task_run.ready", tasks["Implement API"].id)
    assert model_ready.sequence > design_succeeded.sequence
    assert api_ready.sequence > design_succeeded.sequence

    paused_verdict = evaluate_quality_gate(run)
    assert paused_verdict.decision is QualityGateDecision.RETRY
    assert any("retry budget" in reason for reason in paused_verdict.reasons)

    failed_task = tasks["Implement API"]
    first_attempt_id = failed_task.current_attempt_id
    first_request_id = failed_task.request.request_id

    resumed = await run_service.retry_task(failed_task.id, owner_id=OWNER)
    assert resumed.status is WorkflowRunStatus.SUCCEEDED
    api_after = next(task for task in resumed.tasks if task.name == "Implement API")
    assert api_after.status is TaskRunStatus.SUCCEEDED
    assert api_after.retry_count == 1
    assert api_after.id == failed_task.id
    assert api_after.workflow_run_id == failed_task.workflow_run_id
    assert api_after.task_definition_id == failed_task.task_definition_id
    assert api_after.current_attempt_id != first_attempt_id
    assert api_after.request.request_id != first_request_id
    assert api_after.request.attempt_id == api_after.current_attempt_id

    failed_events = [
        event
        for event in resumed.events
        if event.event_type == "task_run.failed" and event.task_run_id == failed_task.id
    ]
    assert len(failed_events) == 1
    assert failed_events[0].attempt_id == first_attempt_id

    assert api_after.result is not None
    assert api_after.result.error is None
    assert api_after.result.request_id == api_after.request.request_id
    assert api_after.result.attempt_id == api_after.current_attempt_id

    testing = next(task for task in resumed.tasks if task.name == "Testing")
    review = next(task for task in resumed.tasks if task.name == "Review")
    assert testing.status is TaskRunStatus.SUCCEEDED
    assert testing.result.metadata["testing"]["outcome"] == "PASSED"
    review_outcome = MockReviewService().review(resumed, review)
    assert review_outcome.decision is ReviewDecision.PASS

    verdict = evaluate_quality_gate(resumed)
    assert verdict.decision is QualityGateDecision.PASS
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in resumed.tasks)
    assert resumed.status is WorkflowRunStatus.SUCCEEDED

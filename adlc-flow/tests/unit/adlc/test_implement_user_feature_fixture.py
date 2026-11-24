# ruff: noqa: PLR2004, S101

"""Fixture validation for the "Implement User Feature" demo blueprint.

The JSON fixture in ``tests/data`` must be a valid input for the real
planning and orchestration pipeline: marked flow -> WorkflowDefinition ->
ExecutionPlan (diamond DAG) -> materialized WorkflowRun -> simulated
first-attempt failure on the Backend stage -> authorized retry -> run
SUCCEEDED. Attempt history is derived from run events, mirroring the
frontend (Option A).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
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
from langflow.adlc.run_service import AdlcRunService

OWNER = "fixture-demo-owner"
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "implement-user-feature-blueprint.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _context(flow_id: UUID) -> BlueprintParseContext:
    return BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Implement User Feature",
        description="Fixture demo blueprint for the control plane.",
        created_by=OWNER,
        created_at=datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc),
    )


def test_fixture_loads_and_compiles_into_diamond_dag() -> None:
    fixture = _load_fixture()
    marker = fixture["data"]["adlc"]
    flow_id = UUID(marker["workflow_definition_id"])

    workflow = parse_blueprint_flow(fixture["data"], _context(flow_id))

    assert workflow.workflow_definition_id == flow_id
    assert [stage.name for stage in workflow.stages] == [
        "Analyze Requirements",
        "Backend Implementation",
        "Frontend Implementation",
        "Testing",
        "Review",
    ]
    assert len(workflow.edges) == 5

    plan_service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = plan_service.create_plan(workflow, owner_id=OWNER, generated_by=OWNER)

    assert plan.status is PlanStatus.VALIDATED
    assert plan.validation_status is PlanValidationStatus.VALID
    assert not plan.approval_required
    assert len(plan.tasks) == 5

    by_name = {task.name: task for task in plan.tasks}
    analyze = by_name["Analyze Requirements"]
    backend = by_name["Backend Implementation"]
    frontend = by_name["Frontend Implementation"]
    testing = by_name["Testing"]
    review = by_name["Review"]

    assert analyze.dependency_task_ids == []
    assert backend.dependency_task_ids == [analyze.plan_task_id]
    assert frontend.dependency_task_ids == [analyze.plan_task_id]
    assert set(testing.dependency_task_ids) == {backend.plan_task_id, frontend.plan_task_id}
    assert review.dependency_task_ids == [testing.plan_task_id]

    for task in plan.tasks:
        assert task.effective_policies.retry.max_attempts == 2

    specs = {spec.resolved_node_spec_id: spec for spec in plan.resolved_node_specs}
    backend_spec = specs[backend.resolved_node_spec_id]
    assert backend_spec.configuration["simulate_failure"] is True
    other_specs = [
        specs[task.resolved_node_spec_id]
        for task in plan.tasks
        if task.name != "Backend Implementation"
    ]
    assert all(spec.configuration["simulate_failure"] is False for spec in other_specs)


async def test_fixture_run_demostrates_failure_retry_and_attempt_history() -> None:
    fixture = _load_fixture()
    flow_id = UUID(fixture["data"]["adlc"]["workflow_definition_id"])
    workflow = parse_blueprint_flow(fixture["data"], _context(flow_id))
    plan_service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = plan_service.create_plan(workflow, owner_id=OWNER, generated_by=OWNER)

    run_service = AdlcRunService(MockExecutor())
    run = await ExecutionPlanMaterializer().materialize(
        plan.execution_plan_id,
        idempotency_key="fixture-demo-run-1",
        owner_id=OWNER,
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )

    assert run.execution_plan_id == plan.execution_plan_id
    assert run.status is WorkflowRunStatus.PAUSED

    tasks = {task.name: task for task in run.tasks}
    backend = tasks["Backend Implementation"]
    assert tasks["Analyze Requirements"].status is TaskRunStatus.SUCCEEDED
    # The Frontend branch runs in parallel with Backend and must not be blocked
    # by the Backend failure: this only holds because the plan is a DAG.
    assert tasks["Frontend Implementation"].status is TaskRunStatus.SUCCEEDED
    assert backend.status is TaskRunStatus.FAILED
    assert backend.retry_count == 0
    assert tasks["Testing"].status is TaskRunStatus.PENDING
    assert tasks["Review"].status is TaskRunStatus.PENDING

    failed_attempt_id = backend.current_attempt_id
    assert failed_attempt_id is not None
    assert backend.plan_traceability is not None
    assert backend.plan_traceability.package_id == "coding-agent"

    resumed = await run_service.retry_task(backend.id, owner_id=OWNER)

    assert resumed.status is WorkflowRunStatus.SUCCEEDED
    resumed_tasks = {task.name: task for task in resumed.tasks}
    resumed_backend = resumed_tasks["Backend Implementation"]
    assert resumed_backend.status is TaskRunStatus.SUCCEEDED
    assert resumed_backend.retry_count == 1
    assert resumed_backend.current_attempt_id != failed_attempt_id
    assert resumed_tasks["Testing"].status is TaskRunStatus.SUCCEEDED
    assert resumed_tasks["Review"].status is TaskRunStatus.SUCCEEDED

    backend_events = [
        event
        for event in resumed.events
        if event.task_run_id == backend.id and event.attempt_id is not None
    ]
    attempt_ids: list[UUID] = []
    for event in backend_events:
        if event.attempt_id not in attempt_ids:
            attempt_ids.append(event.attempt_id)
    assert attempt_ids == [failed_attempt_id, resumed_backend.current_attempt_id]

    failed_event = next(
        event
        for event in backend_events
        if event.attempt_id == failed_attempt_id and event.event_type == "task_run.failed"
    )
    assert failed_event.payload["error_code"] == "MOCK_EXECUTION_FAILED"

    resumed_attempt_events = [
        event.event_type
        for event in backend_events
        if event.attempt_id == resumed_backend.current_attempt_id
    ]
    assert "task_run.started" in resumed_attempt_events
    assert "task_run.succeeded" in resumed_attempt_events

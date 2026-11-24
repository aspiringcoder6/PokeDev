# ruff: noqa: PLR2004, S101

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.blueprints.errors import (
    CAPABILITY_NOT_AUTHORIZED,
    PACKAGE_DEPRECATED,
    PackageAccessError,
)
from langflow.adlc.blueprints.models import PlanStatus
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_adapters import MockMemoryAdapter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, GateType, TaskRunStatus, WorkflowExecutionMode, WorkflowRunStatus
from langflow.adlc.observability import (
    AdlcObservationOutcome,
    AdlcObservationType,
    InMemoryAdlcObservabilitySink,
)
from langflow.adlc.packages.defaults import (
    DEFAULT_PACKAGE_IDENTITIES,
    MOCK_REFERENCE_IDS,
    create_default_package_access_policy,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.errors import (
    PLAN_INTEGRITY_MISMATCH,
    PLAN_NOT_ACCEPTED,
    ExecutionPlanStateError,
)
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer, materialize_task_definitions
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService

if TYPE_CHECKING:
    from langflow.adlc.observability import AdlcObservabilitySink
    from langflow.adlc.packages.access import PackageAccessPolicy

FIXED_TIME = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)


class _ResolutionGuard:
    """Resolver wrapper that detects any lookup after a plan is accepted."""

    def __init__(self) -> None:
        self._delegate = create_default_package_resolver()
        self.reject_resolutions = False

    def resolve(self, *args: Any, **kwargs: Any) -> Any:
        if self.reject_resolutions:
            message = "Accepted-plan materialization must not resolve the package registry again."
            raise AssertionError(message)
        return self._delegate.resolve(*args, **kwargs)


def _stage(index: int, *, name: str, package_id: str = "coding-agent") -> dict:
    stage_id = UUID(f"00000000-0000-4000-8000-{index:012d}")
    approval = package_id == "approval"
    return {
        "id": f"stage-{index}",
        "type": "adlcStageNode",
        "position": {"x": index * 220, "y": 0},
        "data": {
            "adlc": {
                "document_type": "WORKFLOW_STAGE",
                "schema_version": "0.1",
                "stage_id": str(stage_id),
                "stage_type": "APPROVAL" if approval else "IMPLEMENTATION",
                "name": name,
                "objective": f"Complete {name.lower()}.",
                "inputs": (
                    {"approval_context": "Review the verified mock work."}
                    if approval
                    else {"requirement": f"Mock requirement for {name}."}
                ),
                "expected_outputs": ["approval_decision" if approval else "source_patch"],
                "package_ref": {"package_id": package_id, "version": "0.1.0"},
                "configuration_overrides": ({"delay_ms": 0} if not approval else {}),
            }
        },
    }


def _graph(flow_id: UUID, *, include_approval: bool = True, fail_backend: bool = False) -> dict:
    nodes = [
        _stage(1, name="Plan"),
        _stage(2, name="Implement Backend"),
        _stage(3, name="Implement UI"),
        _stage(4, name="Verify"),
    ]
    if fail_backend:
        nodes[1]["data"]["adlc"]["configuration_overrides"]["simulate_failure"] = True
    edges = [
        {"source": "stage-1", "target": "stage-2"},
        {"source": "stage-1", "target": "stage-3"},
        {"source": "stage-2", "target": "stage-4"},
        {"source": "stage-3", "target": "stage-4"},
    ]
    if include_approval:
        nodes.append(_stage(5, name="Approval", package_id="approval"))
        edges.append({"source": "stage-4", "target": "stage-5"})
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


def _plan_service(
    flow_id: UUID,
    *,
    include_approval: bool = True,
    fail_backend: bool = False,
    access_policy: PackageAccessPolicy | None = None,
    observability_sink: AdlcObservabilitySink | None = None,
):
    context = BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Plan materialization fixture",
        description="Accepted plan runtime test.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    workflow = parse_blueprint_flow(
        _graph(flow_id, include_approval=include_approval, fail_backend=fail_backend),
        context,
    )
    resolver = create_default_package_resolver(
        access_policy=access_policy,
        observability_sink=observability_sink,
    )
    service = ExecutionPlanService(BlueprintCompiler(resolver, observability_sink=observability_sink))
    plan = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    return service, plan


async def test_accepted_plan_materializes_traceable_tasks_and_finishes_after_runtime_approval() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id)
    approved = plan_service.approve_plan(
        plan.execution_plan_id,
        owner_id="owner-1",
        approved_by="owner-1",
        comment="The plan shape is accepted.",
    )
    memory = MockMemoryAdapter()
    mock_executor = MockExecutor(memory=memory)
    run_service = AdlcRunService(TaskExecutorRouter(mock_executor, routes={"agent-provider:mock": mock_executor}))
    materializer = ExecutionPlanMaterializer()

    run = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="slice-4-run-1",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )

    assert run.execution_plan_id == plan.execution_plan_id
    assert run.execution_mode is WorkflowExecutionMode.EXECUTION_PLAN
    assert run.events[0].payload["execution_mode"] == "EXECUTION_PLAN"
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert [task.status for task in run.tasks] == [
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.WAITING_APPROVAL,
    ]
    assert all(task.plan_traceability is not None for task in run.tasks)
    assert {task.plan_traceability.plan_task_id for task in run.tasks if task.plan_traceability} == {
        task.plan_task_id for task in approved.tasks
    }
    backend = next(task for task in run.tasks if task.name == "Implement Backend")
    verify = next(task for task in run.tasks if task.name == "Verify")
    assert backend.request is not None
    assert backend.request.executor.service == "agent-provider:mock"
    assert backend.request.input["namedInputs"]["requirement"] == "Mock requirement for Implement Backend."
    assert backend.request.metadata["plan_traceability"]["package_id"] == "coding-agent"
    assert backend.request.metadata["resolved_configuration"] == {
        "artifact_name": "mock-source-patch.diff",
        "delay_ms": 0,
        "simulate_failure": False,
    }
    assert backend.request.trace_context["execution_plan_id"] == str(plan.execution_plan_id)
    assert backend.result is not None
    assert backend.result.metadata["plan_traceability"]["plan_task_id"] == str(backend.plan_traceability.plan_task_id)
    assert backend.artifacts[0].metadata["plan_traceability"]["resolved_node_digest"].startswith("sha256:")
    assert backend.current_attempt_id is not None
    assert memory.recorded_results[backend.current_attempt_id].metadata["plan_traceability"]["package_id"] == (
        "coding-agent"
    )
    assert verify.request is not None
    assert len(verify.request.context["upstream_results"]) == 2
    assert len(verify.request.context["artifact_refs"]) == 2
    assert any("plan_traceability" in event.payload for event in run.events if event.task_run_id)

    approval = run.approval_requests[0]
    approval_task = next(task for task in run.tasks if task.name == "Approval")
    assert approval_task.executor.service == "control:approval"
    assert "control:approval" in approval_task.executor.capabilities
    assert approval_task.pending_result is not None
    assert approval_task.pending_result.metadata["control_plane"] is True
    assert approval_task.artifacts == []
    assert approval_task.current_attempt_id not in memory.recorded_results
    assert approval.gate_type is GateType.ACTION
    assert approval.required_role == "reviewer"
    assert approval.context.summary == "Review the completed work before the workflow continues."
    assert len(approval.context.artifact_refs) == 1
    assert approval.context.artifact_refs[0]["artifact_id"] == str(verify.artifacts[0].artifact_id)
    assert plan_service.get_plan(plan.execution_plan_id, owner_id="owner-1").status is PlanStatus.EXECUTING

    duplicate = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="slice-4-run-1",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    assert duplicate.id == run.id

    _, workflow = plan_service.get_materialization_snapshot(approved.execution_plan_id, owner_id="owner-1")
    successor = plan_service.regenerate_plan(
        workflow,
        owner_id="owner-1",
        generated_by="owner-1",
        supersedes_plan_id=approved.execution_plan_id,
        idempotency_key="successor-after-run",
    )
    assert successor.plan_version == approved.plan_version + 1
    assert successor.supersedes_plan_id == approved.execution_plan_id
    assert plan_service.get_plan(approved.execution_plan_id, owner_id="owner-1").status is PlanStatus.SUPERSEDED

    historical_duplicate = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="slice-4-run-1",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    assert historical_duplicate.id == run.id
    with pytest.raises(ExecutionPlanStateError) as superseded_run:
        await materializer.materialize(
            approved.execution_plan_id,
            idempotency_key="new-run-from-superseded-plan",
            owner_id="owner-1",
            plan_service=plan_service,
            run_service=run_service,
            access_policy=create_default_package_access_policy(),
        )
    assert superseded_run.value.code == PLAN_NOT_ACCEPTED

    completed = await run_service.approve(
        approval.approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Verified.",
    )
    assert completed.status is WorkflowRunStatus.SUCCEEDED
    assert any(event.event_type == "task_run.resumed" for event in completed.events)
    resolved_approval = next(task for task in completed.tasks if task.name == "Approval")
    assert resolved_approval.result is not None
    assert resolved_approval.result.output["outputs"]["approval_decision"]["effect"] == "APPROVE"


async def test_routed_approval_rejection_fails_without_dispatching_control_service() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id)
    approved = plan_service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    mock_executor = MockExecutor()
    run_service = AdlcRunService(TaskExecutorRouter(mock_executor, routes={"agent-provider:mock": mock_executor}))

    run = await ExecutionPlanMaterializer().materialize(
        approved.execution_plan_id,
        idempotency_key="routed-approval-rejection",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )

    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    rejected = await run_service.reject(
        run.approval_requests[0].approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Not approved.",
    )

    assert rejected.status is WorkflowRunStatus.FAILED
    approval_task = next(task for task in rejected.tasks if task.name == "Approval")
    assert approval_task.status is TaskRunStatus.FAILED
    assert approval_task.result is not None
    assert approval_task.result.error is not None
    assert approval_task.result.error.code == "APPROVAL_REJECTED"
    assert approval_task.result.metadata["control_plane"] is True
    assert approval_task.result.metadata["mock"] is False


async def test_pipeline_observations_are_correlated_secret_safe_and_idempotent() -> None:
    flow_id = uuid4()
    sink = InMemoryAdlcObservabilitySink()
    plan_service, plan = _plan_service(flow_id, observability_sink=sink)
    approved = plan_service.approve_plan(
        plan.execution_plan_id,
        owner_id="owner-1",
        approved_by="owner-1",
    )
    run_service = AdlcRunService(observability_sink=sink)
    materializer = ExecutionPlanMaterializer(sink)

    run = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="observed-run",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )

    observations = sink.observations
    resolution = [item for item in observations if item.event_type is AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED]
    validation = [item for item in observations if item.event_type is AdlcObservationType.PLAN_VALIDATION_COMPLETED]
    dispatch = [item for item in observations if item.event_type is AdlcObservationType.TASK_DISPATCH_COMPLETED]
    materialization = [
        item for item in observations if item.event_type is AdlcObservationType.PLAN_MATERIALIZATION_COMPLETED
    ]

    assert len(resolution) == len(approved.resolved_node_specs)
    assert len(validation) == 1
    assert validation[0].outcome is AdlcObservationOutcome.SUCCEEDED
    assert validation[0].execution_plan_id == approved.execution_plan_id
    assert len(dispatch) == len(approved.tasks)
    assert {item.plan_task_id for item in dispatch} == {task.plan_task_id for task in approved.tasks}
    assert all(item.outcome is AdlcObservationOutcome.SUCCEEDED for item in dispatch)
    assert all(item.workflow_run_id == run.id for item in dispatch)
    assert all(item.package_content_digest and item.resolved_node_digest for item in dispatch)
    assert len(materialization) == 1
    assert materialization[0].workflow_run_id == run.id
    assert materialization[0].idempotent_replay is False

    serialized = json.dumps([item.model_dump(mode="json") for item in observations])
    assert "Mock requirement for" not in serialized
    assert "Review the verified mock work" not in serialized
    assert "secret_refs" not in serialized

    replay = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="observed-run",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    replay_observations = sink.observations

    assert replay.id == run.id
    assert len(
        [item for item in replay_observations if item.event_type is AdlcObservationType.TASK_DISPATCH_COMPLETED]
    ) == len(dispatch)
    assert replay_observations[-1].event_type is AdlcObservationType.PLAN_MATERIALIZATION_COMPLETED
    assert replay_observations[-1].idempotent_replay is True


async def test_plan_without_review_materializes_directly_from_validated_state() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id, include_approval=False)

    run = await ExecutionPlanMaterializer().materialize(
        plan.execution_plan_id,
        idempotency_key="no-approval-run",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=AdlcRunService(),
        access_policy=create_default_package_access_policy(),
    )

    assert plan.approval_required is False
    assert run.status is WorkflowRunStatus.SUCCEEDED
    assert plan_service.get_plan(plan.execution_plan_id, owner_id="owner-1").status is PlanStatus.EXECUTING


async def test_deprecation_preserves_an_accepted_plan_and_revocation_blocks_only_new_materialization() -> None:
    flow_id = uuid4()
    access_policy = create_default_package_access_policy()
    plan_service, plan = _plan_service(flow_id, access_policy=access_policy)
    approved = plan_service.approve_plan(
        plan.execution_plan_id,
        owner_id="owner-1",
        approved_by="owner-1",
    )
    accepted_snapshot = approved.model_copy(deep=True)
    access_policy.deprecate_package("coding-agent", "0.1.0")

    current_validation = plan_service.validate_plan(plan.execution_plan_id, owner_id="owner-1")

    assert current_validation.status is PlanStatus.INVALID
    assert PACKAGE_DEPRECATED in {issue.code for issue in current_validation.validation_errors}
    assert plan_service.get_plan(plan.execution_plan_id, owner_id="owner-1") == accepted_snapshot

    sink = InMemoryAdlcObservabilitySink()
    run_service = AdlcRunService()
    materializer = ExecutionPlanMaterializer(sink)
    run = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="accepted-before-deprecation",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=access_policy,
    )

    access_policy.set_subject_grants(
        "owner-1",
        visible_packages=DEFAULT_PACKAGE_IDENTITIES,
        authorized_references=MOCK_REFERENCE_IDS - {"tool:mock-artifact"},
    )
    historical_duplicate = await materializer.materialize(
        approved.execution_plan_id,
        idempotency_key="accepted-before-deprecation",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=access_policy,
    )

    assert historical_duplicate.id == run.id
    assert (await run_service.get_run(run.id, owner_id="owner-1")).id == run.id
    with pytest.raises(PackageAccessError) as denied:
        await materializer.materialize(
            approved.execution_plan_id,
            idempotency_key="new-run-after-revocation",
            owner_id="owner-1",
            plan_service=plan_service,
            run_service=run_service,
            access_policy=access_policy,
        )
    assert denied.value.code == CAPABILITY_NOT_AUTHORIZED
    denied_observation = sink.observations[-1]
    assert denied_observation.event_type is AdlcObservationType.PLAN_MATERIALIZATION_COMPLETED
    assert denied_observation.outcome is AdlcObservationOutcome.DENIED
    assert denied_observation.error_code == CAPABILITY_NOT_AUTHORIZED
    assert denied_observation.workflow_run_id is None


async def test_accepted_plan_and_historical_run_do_not_reresolve_changed_packages() -> None:
    flow_id = uuid4()
    context = BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Immutable package snapshot",
        description="Package changes after acceptance must not affect runtime.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    resolver = _ResolutionGuard()
    plan_service = ExecutionPlanService(BlueprintCompiler(resolver))
    workflow = parse_blueprint_flow(_graph(flow_id), context)
    plan = plan_service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    approved = plan_service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    accepted_digests = {
        spec.source_stage_id: (spec.package_ref.content_digest, spec.resolved_digest)
        for spec in approved.resolved_node_specs
    }
    resolver.reject_resolutions = True
    run_service = AdlcRunService()

    run = await ExecutionPlanMaterializer().materialize(
        approved.execution_plan_id,
        idempotency_key="immutable-snapshot-run",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    historical = await run_service.get_run(run.id, owner_id="owner-1")

    assert run.execution_mode is WorkflowExecutionMode.EXECUTION_PLAN
    assert {
        trace.source_workflow_stage_id: (trace.package_content_digest, trace.resolved_node_digest)
        for task in historical.tasks
        if (trace := task.plan_traceability) is not None
    } == accepted_digests


async def test_unapproved_required_plan_is_rejected_before_runtime_creation() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id)

    with pytest.raises(ExecutionPlanStateError) as exc:
        await ExecutionPlanMaterializer().materialize(
            plan.execution_plan_id,
            idempotency_key="must-not-run",
            owner_id="owner-1",
            plan_service=plan_service,
            run_service=AdlcRunService(),
            access_policy=create_default_package_access_policy(),
        )

    assert exc.value.code == PLAN_NOT_ACCEPTED


def test_materializer_rechecks_the_stored_resolved_digest() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id)
    approved = plan_service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    approved.resolved_node_specs[0].configuration["artifact_name"] = "tampered.diff"

    with pytest.raises(ExecutionPlanStateError) as exc:
        materialize_task_definitions(approved)

    assert exc.value.code == PLAN_INTEGRITY_MISMATCH


def test_materializer_revalidates_the_stored_plan_contract() -> None:
    flow_id = uuid4()
    plan_service, plan = _plan_service(flow_id)
    approved = plan_service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    approved.tasks[0].dependency_task_ids = [uuid4()]

    with pytest.raises(ExecutionPlanStateError) as exc:
        materialize_task_definitions(approved)

    assert exc.value.code == PLAN_INTEGRITY_MISMATCH


async def test_plan_configured_failure_preserves_retry_and_downstream_unlocking() -> None:
    flow_id = uuid4()
    sink = InMemoryAdlcObservabilitySink()
    plan_service, plan = _plan_service(flow_id, fail_backend=True)
    plan_service.approve_plan(plan.execution_plan_id, owner_id="owner-1", approved_by="owner-1")
    run_service = AdlcRunService(observability_sink=sink)
    run = await ExecutionPlanMaterializer().materialize(
        plan.execution_plan_id,
        idempotency_key="retry-plan-run",
        owner_id="owner-1",
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )

    failed = next(task for task in run.tasks if task.name == "Implement Backend")
    assert run.status is WorkflowRunStatus.PAUSED
    assert failed.status is TaskRunStatus.FAILED
    failed_dispatch = next(
        item
        for item in sink.observations
        if item.event_type is AdlcObservationType.TASK_DISPATCH_COMPLETED and item.task_run_id == failed.id
    )
    assert failed_dispatch.outcome is AdlcObservationOutcome.FAILED
    assert failed_dispatch.error_code == "MOCK_EXECUTION_FAILED"
    assert failed_dispatch.attempt_number == 1

    retried = await run_service.retry_task(failed.id, owner_id="owner-1")

    assert retried.status is WorkflowRunStatus.WAITING_APPROVAL
    retried_task = next(task for task in retried.tasks if task.id == failed.id)
    assert retried_task.retry_count == 1
    assert retried_task.plan_traceability == failed.plan_traceability
    retry_dispatches = [
        item
        for item in sink.observations
        if item.event_type is AdlcObservationType.TASK_DISPATCH_COMPLETED and item.task_run_id == failed.id
    ]
    assert [item.outcome for item in retry_dispatches] == [
        AdlcObservationOutcome.FAILED,
        AdlcObservationOutcome.SUCCEEDED,
    ]
    assert [item.attempt_number for item in retry_dispatches] == [1, 2]

"""Expand an approved proposal into a synthetic workflow for the existing compiler.

The expanded ``WorkflowDefinition`` reuses the original workflow identity and is
compiled by the **existing** ``BlueprintCompiler``. Nothing in the compiler,
materializer, scheduler, or execution plane changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from langflow.adlc.blueprints.models import (
    StagePosition,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowStage,
)
from langflow.adlc.coding_agent import is_unified_coding_agent

if TYPE_CHECKING:
    from langflow.adlc.planning.proposals.models import ProposedPlan


def proposal_stage_id(proposal_id: UUID, task_id: str) -> UUID:
    """Deterministic synthetic stage id for one proposed task."""
    return uuid5(NAMESPACE_URL, f"adlc:proposal-task:{proposal_id}:{task_id}")


def build_expanded_workflow(
    original: WorkflowDefinition,
    proposal: ProposedPlan,
) -> WorkflowDefinition:
    """Expand one validated proposal into executable stages for the compiler."""
    stage_by_id = {proposal_stage_id(proposal.proposal_id, task.task_id): task for task in proposal.tasks}
    stages: list[WorkflowStage] = []
    originals = {stage.stage_id: stage for stage in original.stages}
    for task in proposal.tasks:
        source = originals.get(task.source_stage_id)
        unified = source is not None and is_unified_coding_agent(
            source.package_ref.package_id, source.package_ref.version
        )
        stage_id = proposal_stage_id(proposal.proposal_id, task.task_id)
        stage_metadata = {
            "proposal_id": str(proposal.proposal_id),
            "proposal_task_id": task.task_id,
            "source_workflow_stage_id": str(task.source_stage_id),
            "planner_mode": proposal.planner_mode.value,
            "migration_mode": "PLANNER",
        }
        stage_metadata.update({key: value for key, value in task.metadata.items() if key not in stage_metadata})
        stages.append(
            WorkflowStage(
                stage_id=stage_id,
                stage_type=task.metadata.get("stage_type", "IMPLEMENTATION"),
                name=task.name,
                objective=task.objective,
                inputs=dict(task.inputs),
                expected_outputs=list(task.expected_outputs),
                package_ref=task.assigned_package,
                configuration_overrides=dict(
                    source.configuration_overrides if unified else task.metadata.get("configuration_overrides", {})
                ),
                execution_profile_overrides={},
                policy_overrides=dict(source.policy_overrides) if unified else {},
                secret_refs=dict(source.secret_refs) if unified else {},
                position=StagePosition(x=0.0, y=float(len(stages)) * 160.0),
                metadata=stage_metadata,
            )
        )

    edges: list[WorkflowEdge] = []
    for task in proposal.tasks:
        target_stage_id = proposal_stage_id(proposal.proposal_id, task.task_id)
        for dependency in task.dependency_task_ids:
            source_stage_id = proposal_stage_id(proposal.proposal_id, dependency)
            if source_stage_id not in stage_by_id:
                continue
            edges.append(
                WorkflowEdge(
                    edge_id=uuid5(
                        NAMESPACE_URL,
                        (f"adlc:proposal-edge:{proposal.proposal_id}:{dependency}->{task.task_id}"),
                    ),
                    source_stage_id=source_stage_id,
                    target_stage_id=target_stage_id,
                    condition="ON_SUCCESS",
                    bindings=[],
                    metadata={"proposal_id": str(proposal.proposal_id)},
                )
            )

    return WorkflowDefinition(
        schema_version=original.schema_version,
        workflow_definition_id=original.workflow_definition_id,
        project_id=original.project_id,
        name=original.name,
        description=original.description,
        version=original.version,
        status=original.status,
        stages=stages,
        edges=edges,
        default_policies=original.default_policies,
        created_by=original.created_by,
        created_at=original.created_at,
        updated_at=original.updated_at,
        metadata={
            **original.metadata,
            "planner_proposal_id": str(proposal.proposal_id),
            "planner_mode": proposal.planner_mode.value,
            "planner_expanded": True,
        },
    )

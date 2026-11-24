"""Compile validated workflow definitions into deterministic execution plans."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.errors import PackageResolutionError
from langflow.adlc.blueprints.models import (
    AUTHORING_CONTRACT_VERSION,
    ExecutionPlan,
    NodePackageKind,
    PlanStatus,
    PlanTask,
    PlanValidationIssue,
    PlanValidationStatus,
    ResolvedInputBinding,
    ResolvedNodeSpec,
    WorkflowDefinition,
)
from langflow.adlc.observability import (
    NOOP_ADLC_OBSERVABILITY_SINK,
    AdlcObservabilitySink,
    AdlcObservationOutcome,
    AdlcObservationType,
    elapsed_milliseconds,
    observation_error_code,
    observation_outcome_for_exception,
    record_observation_safely,
)
from langflow.adlc.planning.validator import BlueprintValidator, workflow_structure_warnings

if TYPE_CHECKING:
    from langflow.adlc.packages.resolver import NodePackageResolver


class BlueprintCompiler:
    """Pure planning service: package resolution and validation, never execution."""

    def __init__(
        self,
        resolver: NodePackageResolver,
        validator: BlueprintValidator | None = None,
        *,
        observability_sink: AdlcObservabilitySink | None = None,
    ) -> None:
        self._resolver = resolver
        self._validator = validator or BlueprintValidator()
        self._observability = observability_sink if observability_sink is not None else NOOP_ADLC_OBSERVABILITY_SINK

    def compile(
        self,
        workflow: WorkflowDefinition,
        *,
        plan_version: int,
        generated_by: str,
        generated_at: datetime | None = None,
        supersedes_plan_id: UUID | None = None,
        authorization_subject: str | None = None,
    ) -> ExecutionPlan:
        """Create a VALIDATED or INVALID immutable plan projection."""
        started_at_ns = perf_counter_ns()
        try:
            plan = self._compile(
                workflow,
                plan_version=plan_version,
                generated_by=generated_by,
                generated_at=generated_at,
                supersedes_plan_id=supersedes_plan_id,
                authorization_subject=authorization_subject,
            )
        except Exception as exc:
            record_observation_safely(
                self._observability,
                event_type=AdlcObservationType.PLAN_VALIDATION_COMPLETED,
                outcome=observation_outcome_for_exception(exc),
                duration_ms=elapsed_milliseconds(started_at_ns),
                error_code=observation_error_code(exc, "PLAN_VALIDATION_FAILED"),
                workflow_definition_id=workflow.workflow_definition_id,
                workflow_definition_version=workflow.version,
            )
            raise

        valid = plan.validation_status is PlanValidationStatus.VALID
        record_observation_safely(
            self._observability,
            event_type=AdlcObservationType.PLAN_VALIDATION_COMPLETED,
            outcome=AdlcObservationOutcome.SUCCEEDED if valid else AdlcObservationOutcome.INVALID,
            duration_ms=elapsed_milliseconds(started_at_ns),
            workflow_definition_id=plan.workflow_definition_id,
            workflow_definition_version=plan.workflow_definition_version,
            execution_plan_id=plan.execution_plan_id,
            task_count=len(plan.tasks),
            resolved_node_count=len(plan.resolved_node_specs),
            validation_issue_count=len(plan.validation_errors),
            validation_issue_codes=tuple(sorted({issue.code for issue in plan.validation_errors})),
        )
        return plan

    def _compile(
        self,
        workflow: WorkflowDefinition,
        *,
        plan_version: int,
        generated_by: str,
        generated_at: datetime | None = None,
        supersedes_plan_id: UUID | None = None,
        authorization_subject: str | None = None,
    ) -> ExecutionPlan:
        timestamp = generated_at or datetime.now(timezone.utc)
        if timestamp.utcoffset() is None:
            message = "generated_at must include a timezone"
            raise ValueError(message)
        if plan_version < 1:
            message = "plan_version must be positive"
            raise ValueError(message)

        stage_indexes = {stage.stage_id: index for index, stage in enumerate(workflow.stages)}
        resolved_specs: dict[UUID, ResolvedNodeSpec] = {}
        issues: list[PlanValidationIssue] = []
        for stage in sorted(workflow.stages, key=lambda item: str(item.stage_id)):
            try:
                resolved_specs[stage.stage_id] = self._resolver.resolve(
                    stage,
                    workflow_definition_id=workflow.workflow_definition_id,
                    workflow_definition_version=workflow.version,
                    workflow_policy_overrides=workflow.default_policies,
                    resolved_at=timestamp,
                    access_subject=authorization_subject or generated_by,
                )
            except PackageResolutionError as exc:
                base_path = f"/stages/{stage_indexes[stage.stage_id]}"
                issue_path = f"{base_path}{exc.path}" if exc.path else base_path
                details = dict(exc.details)
                details["stage_id"] = str(stage.stage_id)
                issues.append(
                    PlanValidationIssue(
                        code=exc.code,
                        message=exc.message,
                        path=issue_path,
                        details=details,
                    )
                )

        issues.extend(self._validator.validate(workflow, resolved_specs))
        issues = sorted(issues, key=lambda issue: (issue.path or "", issue.code, issue.message))
        warnings = list(workflow_structure_warnings(workflow))
        workflow_digest = sha256_digest(_semantic_workflow(workflow))
        resolution_digest = sha256_digest(
            {
                "workflow_digest": workflow_digest,
                "resolved_specs": [
                    {
                        "stage_id": stage_id,
                        "resolved_digest": spec.resolved_digest,
                    }
                    for stage_id, spec in sorted(resolved_specs.items(), key=lambda item: str(item[0]))
                ],
                "validation_errors": issues,
            }
        )
        plan_id = uuid5(
            NAMESPACE_URL,
            (
                f"adlc:execution-plan:{workflow.workflow_definition_id}:{workflow.version}:"
                f"{plan_version}:{resolution_digest}"
            ),
        )
        approval_required = any(
            spec.kind is NodePackageKind.APPROVAL or spec.policies.approval.gate_type is not None
            for spec in resolved_specs.values()
        )
        is_valid = not issues and len(resolved_specs) == len(workflow.stages)
        tasks = _build_plan_tasks(workflow, resolved_specs, plan_id) if is_valid else []
        ordered_specs = [
            resolved_specs[stage_id] for stage_id in _topological_stage_ids(workflow) if stage_id in resolved_specs
        ]
        status = PlanStatus.VALIDATED if is_valid else PlanStatus.INVALID
        validation_status = PlanValidationStatus.VALID if is_valid else PlanValidationStatus.INVALID
        max_concurrency = workflow.default_policies.get("max_concurrency")

        return ExecutionPlan(
            schema_version=AUTHORING_CONTRACT_VERSION,
            execution_plan_id=plan_id,
            workflow_definition_id=workflow.workflow_definition_id,
            workflow_definition_version=workflow.version,
            plan_version=plan_version,
            status=status,
            validation_status=validation_status,
            validation_errors=issues,
            warnings=warnings,
            assumptions=[],
            approval_required=approval_required,
            tasks=tasks,
            resolved_node_specs=ordered_specs,
            generated_by=generated_by,
            generated_at=timestamp,
            supersedes_plan_id=supersedes_plan_id,
            metadata={
                "workflow_digest": workflow_digest,
                "resolution_digest": resolution_digest,
                "max_concurrency": max_concurrency if isinstance(max_concurrency, int) else None,
                **({"adlc_local_project": workflow.metadata["adlc_local_project"]}
                   if "adlc_local_project" in workflow.metadata else {}),
            },
        )


def _build_plan_tasks(
    workflow: WorkflowDefinition,
    specs: dict[UUID, ResolvedNodeSpec],
    plan_id: UUID,
) -> list[PlanTask]:
    stage_by_id = {stage.stage_id: stage for stage in workflow.stages}
    task_ids = {stage_id: uuid5(plan_id, f"task:{stage_id}") for stage_id in stage_by_id}
    dependency_conditions: dict[UUID, dict[UUID, str]] = defaultdict(dict)
    bindings_by_stage: dict[UUID, list[ResolvedInputBinding]] = defaultdict(list)
    for edge in workflow.edges:
        dependency_conditions[edge.target_stage_id][edge.source_stage_id] = edge.condition
        for binding in edge.bindings:
            bindings_by_stage[edge.target_stage_id].append(
                ResolvedInputBinding(
                    source_plan_task_id=task_ids[edge.source_stage_id],
                    source_output=binding.source_output,
                    target_input=binding.target_input,
                )
            )

    tasks: list[PlanTask] = []
    for stage_id in _topological_stage_ids(workflow):
        stage = stage_by_id[stage_id]
        spec = specs[stage_id]
        profile = spec.execution_profile
        ordered_dependencies = sorted(dependency_conditions[stage_id], key=str)
        tasks.append(
            PlanTask(
                plan_task_id=task_ids[stage_id],
                source_workflow_stage_id=stage_id,
                resolved_node_spec_id=spec.resolved_node_spec_id,
                resolved_node_digest=spec.resolved_digest,
                name=stage.name,
                objective=stage.objective,
                task_type=stage.stage_type,
                dependency_task_ids=[task_ids[dependency] for dependency in ordered_dependencies],
                dependency_conditions=[
                    dependency_conditions[stage_id][dependency] for dependency in ordered_dependencies
                ],
                input_bindings=sorted(
                    bindings_by_stage[stage_id],
                    key=lambda binding: (
                        str(binding.source_plan_task_id),
                        binding.source_output,
                        binding.target_input,
                    ),
                ),
                inputs=stage.inputs,
                expected_artifacts=list(stage.expected_outputs),
                assigned_capability=(profile.provider_ref if profile is not None else spec.implementation.adapter_ref),
                required_environment=profile.sandbox_policy_ref if profile is not None else None,
                effective_policies=spec.policies,
                planning_rationale=(
                    f"Compiled from stage {stage.stage_id} using "
                    f"{spec.package_ref.package_id}@{spec.package_ref.version}."
                ),
                priority=50,
                metadata={
                    "package_id": spec.package_ref.package_id,
                    "package_version": spec.package_ref.version,
                },
            )
        )
    return tasks


def _topological_stage_ids(workflow: WorkflowDefinition) -> list[UUID]:
    stage_ids = {stage.stage_id for stage in workflow.stages}
    dependencies: dict[UUID, set[UUID]] = {stage_id: set() for stage_id in stage_ids}
    dependents: dict[UUID, set[UUID]] = {stage_id: set() for stage_id in stage_ids}
    for edge in workflow.edges:
        dependencies[edge.target_stage_id].add(edge.source_stage_id)
        dependents[edge.source_stage_id].add(edge.target_stage_id)
    ready = sorted((stage_id for stage_id in stage_ids if not dependencies[stage_id]), key=str)
    ordered: list[UUID] = []
    while ready:
        stage_id = ready.pop(0)
        ordered.append(stage_id)
        for dependent in sorted(dependents[stage_id], key=str):
            dependencies[dependent].discard(stage_id)
            if not dependencies[dependent] and dependent not in ready and dependent not in ordered:
                ready.append(dependent)
        ready.sort(key=str)
    return ordered


def _semantic_workflow(workflow: WorkflowDefinition) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    for stage in sorted(workflow.stages, key=lambda item: str(item.stage_id)):
        payload = stage.model_dump(mode="json", exclude_none=False)
        payload.pop("position", None)
        stages.append(payload)
    edges = [
        edge.model_dump(mode="json", exclude_none=False)
        for edge in sorted(
            workflow.edges,
            key=lambda item: (str(item.source_stage_id), str(item.target_stage_id), str(item.edge_id)),
        )
    ]
    return {
        "schema_version": workflow.schema_version,
        "workflow_definition_id": workflow.workflow_definition_id,
        "project_id": workflow.project_id,
        "name": workflow.name,
        "description": workflow.description,
        "version": workflow.version,
        "status": workflow.status,
        "stages": stages,
        "edges": edges,
        "default_policies": workflow.default_policies,
        "metadata": workflow.metadata,
    }

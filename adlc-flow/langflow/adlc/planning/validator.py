"""Deterministic logical-slot validation for resolved ADLC blueprints."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from langflow.adlc.blueprints.errors import (
    RAW_SECRET_FORBIDDEN,
    STAGE_BINDING_INCOMPATIBLE,
    STAGE_GATE_UNSUPPORTED,
    STAGE_INPUT_AMBIGUOUS,
    STAGE_INPUT_UNBOUND,
    STAGE_INPUT_UNKNOWN,
    STAGE_ISOLATED,
    STAGE_OUTPUT_UNKNOWN,
)
from langflow.adlc.blueprints.models import (
    NodePackageKind,
    PlanValidationIssue,
)
from langflow.adlc.blueprints.security import find_raw_secret_path

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.blueprints.models import ResolvedNodeSpec, WorkflowDefinition

_BEFORE_TASK_GATE = "BEFORE_TASK"


def workflow_structure_warnings(workflow: WorkflowDefinition) -> tuple[PlanValidationIssue, ...]:
    """Return non-fatal structural findings, currently isolated-stage detection."""
    if len(workflow.stages) < 2:
        return ()
    connected: set[UUID] = set()
    for edge in workflow.edges:
        connected.add(edge.source_stage_id)
        connected.add(edge.target_stage_id)
    stage_indexes = {stage.stage_id: index for index, stage in enumerate(workflow.stages)}
    warnings = [
        PlanValidationIssue(
            code=STAGE_ISOLATED,
            message=f"Stage '{stage.name}' is not connected to any workflow edge.",
            path=f"/stages/{stage_indexes[stage.stage_id]}",
            details={"stage_id": str(stage.stage_id)},
        )
        for stage in workflow.stages
        if stage.stage_id not in connected
    ]
    return tuple(sorted(warnings, key=lambda issue: issue.path or ""))


class BlueprintValidator:
    """Validate stage inputs, expected outputs, and edge bindings after resolution."""

    def validate(
        self,
        workflow: WorkflowDefinition,
        resolved_specs: dict[UUID, ResolvedNodeSpec],
    ) -> tuple[PlanValidationIssue, ...]:
        issues: list[PlanValidationIssue] = []
        stage_indexes = {stage.stage_id: index for index, stage in enumerate(workflow.stages)}
        edge_indexes = {edge.edge_id: index for index, edge in enumerate(workflow.edges)}
        inbound_bindings: dict[tuple[UUID, str], list[UUID]] = defaultdict(list)

        workflow_secret_path = find_raw_secret_path(workflow.metadata)
        if workflow_secret_path is not None:
            issues.append(
                PlanValidationIssue(
                    code=RAW_SECRET_FORBIDDEN,
                    message="Raw secret-like fields are forbidden in workflow metadata.",
                    path=f"/metadata{workflow_secret_path}",
                    details={},
                )
            )

        for stage in workflow.stages:
            spec = resolved_specs.get(stage.stage_id)
            if spec is None:
                continue
            inputs = {slot.name: slot for slot in spec.interface.inputs}
            outputs = {slot.name: slot for slot in spec.interface.outputs}
            stage_path = f"/stages/{stage_indexes[stage.stage_id]}"
            input_secret_path = find_raw_secret_path(stage.inputs)
            if input_secret_path is not None:
                issues.append(
                    PlanValidationIssue(
                        code=RAW_SECRET_FORBIDDEN,
                        message="Raw secret-like fields are forbidden in stage inputs.",
                        path=f"{stage_path}/inputs{input_secret_path}",
                        details={"stage_id": str(stage.stage_id)},
                    )
                )
            issues.extend(
                PlanValidationIssue(
                    code=STAGE_INPUT_UNKNOWN,
                    message=f"Stage input '{input_name}' is not declared by its package.",
                    path=f"{stage_path}/inputs/{input_name}",
                    details={"stage_id": str(stage.stage_id)},
                )
                for input_name in sorted(stage.inputs)
                if input_name not in inputs
            )
            issues.extend(
                PlanValidationIssue(
                    code=STAGE_OUTPUT_UNKNOWN,
                    message=f"Expected output '{output_name}' is not declared by its package.",
                    path=f"{stage_path}/expected_outputs",
                    details={"stage_id": str(stage.stage_id)},
                )
                for output_name in stage.expected_outputs
                if output_name not in outputs
            )
            gate_error = _unsupported_gate_issue(spec, stage_path)
            if gate_error is not None:
                issues.append(gate_error)

        for edge in workflow.edges:
            source_spec = resolved_specs.get(edge.source_stage_id)
            target_spec = resolved_specs.get(edge.target_stage_id)
            if source_spec is None or target_spec is None:
                continue
            source_slots = {slot.name: slot for slot in source_spec.interface.outputs}
            target_slots = {slot.name: slot for slot in target_spec.interface.inputs}
            edge_path = f"/edges/{edge_indexes[edge.edge_id]}"
            for binding_index, binding in enumerate(edge.bindings):
                binding_path = f"{edge_path}/bindings/{binding_index}"
                source_slot = source_slots.get(binding.source_output)
                target_slot = target_slots.get(binding.target_input)
                if source_slot is None:
                    issues.append(
                        PlanValidationIssue(
                            code=STAGE_OUTPUT_UNKNOWN,
                            message=f"Binding source output '{binding.source_output}' is not declared.",
                            path=f"{binding_path}/source_output",
                            details={"stage_id": str(edge.source_stage_id)},
                        )
                    )
                if target_slot is None:
                    issues.append(
                        PlanValidationIssue(
                            code=STAGE_INPUT_UNKNOWN,
                            message=f"Binding target input '{binding.target_input}' is not declared.",
                            path=f"{binding_path}/target_input",
                            details={"stage_id": str(edge.target_stage_id)},
                        )
                    )
                if source_slot is None or target_slot is None:
                    continue
                if source_slot.schema_ref != target_slot.schema_ref:
                    issues.append(
                        PlanValidationIssue(
                            code=STAGE_BINDING_INCOMPATIBLE,
                            message="Binding source and target schemas must match in contract v0.1.",
                            path=binding_path,
                            details={
                                "source_schema_ref": source_slot.schema_ref,
                                "target_schema_ref": target_slot.schema_ref,
                            },
                        )
                    )
                    continue
                inbound_bindings[(edge.target_stage_id, binding.target_input)].append(edge.edge_id)

        for stage in workflow.stages:
            spec = resolved_specs.get(stage.stage_id)
            if spec is None:
                continue
            stage_path = f"/stages/{stage_indexes[stage.stage_id]}"
            for slot in spec.interface.inputs:
                supplied_directly = slot.name in stage.inputs
                bound_edges = inbound_bindings[(stage.stage_id, slot.name)]
                supplied_count = int(supplied_directly) + len(bound_edges)
                if slot.required and supplied_count == 0:
                    issues.append(
                        PlanValidationIssue(
                            code=STAGE_INPUT_UNBOUND,
                            message=f"Required input '{slot.name}' has no value or compatible edge binding.",
                            path=f"{stage_path}/inputs/{slot.name}",
                            details={"stage_id": str(stage.stage_id)},
                        )
                    )
                if not slot.multiple and supplied_count > 1:
                    issues.append(
                        PlanValidationIssue(
                            code=STAGE_INPUT_AMBIGUOUS,
                            message=f"Non-multiple input '{slot.name}' has more than one source.",
                            path=f"{stage_path}/inputs/{slot.name}",
                            details={
                                "stage_id": str(stage.stage_id),
                                "supplied_directly": supplied_directly,
                                "binding_edge_ids": [str(edge_id) for edge_id in bound_edges],
                            },
                        )
                    )

        return tuple(sorted(issues, key=lambda issue: (issue.path or "", issue.code, issue.message)))


def _unsupported_gate_issue(spec: ResolvedNodeSpec, stage_path: str) -> PlanValidationIssue | None:
    """Reject approval-gate shapes the v0.1 runtime cannot honor, before compilation succeeds."""
    gate_value = spec.policies.approval.gate_type
    if spec.kind is NodePackageKind.APPROVAL and gate_value is None:
        return PlanValidationIssue(
            code=STAGE_GATE_UNSUPPORTED,
            message="An APPROVAL stage requires an explicit approval gate.",
            path=f"{stage_path}/policies/approval/gate_type",
            details={"stage_id": str(spec.source_stage_id)},
        )
    if gate_value == _BEFORE_TASK_GATE:
        return PlanValidationIssue(
            code=STAGE_GATE_UNSUPPORTED,
            message="BEFORE_TASK approval gates are not supported by the v0.1 runtime.",
            path=f"{stage_path}/policies/approval/gate_type",
            details={"stage_id": str(spec.source_stage_id), "gate_type": gate_value},
        )
    return None

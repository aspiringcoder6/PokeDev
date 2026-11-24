"""Parse explicitly marked Langflow graphs into ADLC workflow definitions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from langflow.adlc.blueprints.errors import (
    BLUEPRINT_EDGE_INVALID,
    BLUEPRINT_INVALID,
    BLUEPRINT_MARKER_INVALID,
    BLUEPRINT_MARKER_MISSING,
    BLUEPRINT_NODE_INVALID,
    STAGE_DEPENDENCY_CYCLE,
    STAGE_DEPENDENCY_MISSING,
    STAGE_ID_DUPLICATE,
    WORKFLOW_HAS_NO_ROOT,
)
from langflow.adlc.blueprints.models import (
    AUTHORING_CONTRACT_VERSION,
    PlanValidationIssue,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowStage,
)
from langflow.adlc.planning.authoring import prepare_authoring_graph
from langflow.adlc.planning.errors import BlueprintParseError

if TYPE_CHECKING:
    from datetime import datetime

BLUEPRINT_DOCUMENT_TYPE = "WORKFLOW_DEFINITION"
STAGE_DOCUMENT_TYPE = "WORKFLOW_STAGE"
EDGE_DOCUMENT_TYPE = "WORKFLOW_EDGE"

_MARKER_FIELDS = {
    "document_type",
    "schema_version",
    "workflow_definition_id",
    "version",
    "status",
    "default_policies",
    "metadata",
}
_EDGE_FIELDS = {"document_type", "schema_version", "edge_id", "condition", "bindings", "metadata"}
_PRESENTATION_NODE_TYPES = {"group", "groupnode", "note", "notenode"}


@dataclass(frozen=True, slots=True)
class BlueprintParseContext:
    """Database-owned values that are intentionally absent from canvas JSON."""

    flow_id: UUID
    project_id: UUID
    name: str
    description: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    local_project: dict | None = None


def has_adlc_blueprint_marker(graph: object) -> bool:
    """Return whether a graph declares intent to use the blueprint planning path."""
    if not isinstance(graph, dict):
        return False
    marker = graph.get("adlc")
    return isinstance(marker, dict) and marker.get("document_type") == BLUEPRINT_DOCUMENT_TYPE


def is_adlc_blueprint(graph: object) -> bool:
    """Return whether a graph carries the exact supported v0.1 marker."""
    if not has_adlc_blueprint_marker(graph):
        return False
    marker = graph["adlc"]
    return marker.get("schema_version") == AUTHORING_CONTRACT_VERSION


def parse_blueprint_flow(graph: object, context: BlueprintParseContext) -> WorkflowDefinition:
    """Normalize one marked ReactFlow document without invoking runtime services."""
    issues: list[PlanValidationIssue] = []
    if not isinstance(graph, dict):
        _raise_single(BLUEPRINT_INVALID, "The flow data must be an object.", path="/")

    graph = prepare_authoring_graph(graph)
    marker = graph.get("adlc")
    if not isinstance(marker, dict) or marker.get("document_type") != BLUEPRINT_DOCUMENT_TYPE:
        _raise_single(
            BLUEPRINT_MARKER_MISSING,
            "The flow does not declare document_type=WORKFLOW_DEFINITION.",
            path="/adlc",
        )
    if marker.get("schema_version") != AUTHORING_CONTRACT_VERSION:
        _raise_single(
            BLUEPRINT_MARKER_INVALID,
            "The blueprint marker must use schema_version=0.1.",
            path="/adlc/schema_version",
        )
    unknown_marker_fields = sorted(set(marker) - _MARKER_FIELDS)
    if unknown_marker_fields:
        issues.append(
            _issue(
                BLUEPRINT_MARKER_INVALID,
                "The blueprint marker contains unsupported fields.",
                path="/adlc",
                details={"fields": unknown_marker_fields},
            )
        )

    workflow_definition_id = _parse_workflow_id(marker, issues)
    version = marker.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        issues.append(
            _issue(
                BLUEPRINT_MARKER_INVALID,
                "The blueprint version must be a positive integer.",
                path="/adlc/version",
            )
        )
    if workflow_definition_id is not None and workflow_definition_id != context.flow_id:
        issues.append(
            _issue(
                BLUEPRINT_MARKER_INVALID,
                "workflow_definition_id must match the saved Langflow flow ID.",
                path="/adlc/workflow_definition_id",
                details={"flow_id": str(context.flow_id)},
            )
        )

    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list):
        issues.append(_issue(BLUEPRINT_INVALID, "The blueprint must contain a nodes array.", path="/nodes"))
        raw_nodes = []
    if not isinstance(raw_edges, list):
        issues.append(_issue(BLUEPRINT_INVALID, "The blueprint must contain an edges array.", path="/edges"))
        raw_edges = []

    stages_by_node_id, ignored_node_ids = _parse_stages(raw_nodes, issues)
    if context.local_project is not None and any(
        stage.package_ref.package_id in {"coding-agent-deepseek-harness", "coding-agent-contract-harness"}
        or (stage.package_ref.package_id == "coding-agent" and stage.package_ref.version == "0.2.0")
        for stage in stages_by_node_id.values()
    ):
        issues.append(
            _issue(
                "LOCAL_PROJECT_RELEASE_REQUIRED",
                "Update the coding stage to Coding Agent 0.2.1 to run in the selected local project.",
                path="/nodes",
            )
        )
    if context.local_project is None and any(
        stage.package_ref.package_id == "coding-agent" and stage.package_ref.version in {"0.2.1", "0.3.0"}
        for stage in stages_by_node_id.values()
    ):
        issues.append(
            _issue(
                "LOCAL_PROJECT_REQUIRED",
                "Choose a local project before reviewing a Coding Agent plan.",
                path="/adlc/metadata/adlc_local_project",
            )
        )
    if not stages_by_node_id:
        issues.append(
            _issue(
                BLUEPRINT_NODE_INVALID,
                "The blueprint must contain at least one workflow stage.",
                path="/nodes",
            )
        )

    edges: list[WorkflowEdge] = []
    if workflow_definition_id is not None:
        edges = _parse_edges(
            raw_edges,
            stages_by_node_id,
            ignored_node_ids,
            workflow_definition_id,
            issues,
        )
        issues.extend(_dependency_issues(tuple(stages_by_node_id.values()), edges))

    if issues or workflow_definition_id is None or not isinstance(version, int) or isinstance(version, bool):
        raise BlueprintParseError(issues)

    try:
        return WorkflowDefinition(
            schema_version=AUTHORING_CONTRACT_VERSION,
            workflow_definition_id=workflow_definition_id,
            project_id=context.project_id,
            name=context.name,
            description=context.description,
            version=version,
            status=marker.get("status", "DRAFT"),
            stages=list(stages_by_node_id.values()),
            edges=edges,
            default_policies=marker.get("default_policies", {}),
            created_by=context.created_by,
            created_at=context.created_at,
            updated_at=context.updated_at,
            metadata={
                **{k: v for k, v in marker.get("metadata", {}).items() if k != "adlc_local_project"},
                **({"adlc_local_project": context.local_project} if context.local_project is not None else {}),
            }
            if isinstance(marker.get("metadata", {}), dict)
            else marker.get("metadata"),
        )
    except ValidationError as exc:
        issue = _issue(
            BLUEPRINT_INVALID,
            "The normalized workflow definition violates contract v0.1.",
            path="/",
            details={"errors": _safe_validation_errors(exc)},
        )
        raise BlueprintParseError([issue]) from exc


def _parse_workflow_id(marker: dict[str, Any], issues: list[PlanValidationIssue]) -> UUID | None:
    try:
        return UUID(str(marker.get("workflow_definition_id")))
    except (TypeError, ValueError, AttributeError):
        issues.append(
            _issue(
                BLUEPRINT_MARKER_INVALID,
                "workflow_definition_id must be a UUID.",
                path="/adlc/workflow_definition_id",
            )
        )
        return None


def _parse_stages(
    raw_nodes: list[object],
    issues: list[PlanValidationIssue],
) -> tuple[dict[str, WorkflowStage], set[str]]:
    stages: dict[str, WorkflowStage] = {}
    stage_ids: set[UUID] = set()
    ignored_node_ids: set[str] = set()
    seen_node_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        path = f"/nodes/{index}"
        if not isinstance(raw_node, dict):
            issues.append(_issue(BLUEPRINT_NODE_INVALID, "A blueprint node must be an object.", path=path))
            continue
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id:
            issues.append(_issue(BLUEPRINT_NODE_INVALID, "A blueprint node requires an ID.", path=f"{path}/id"))
            continue
        if node_id in seen_node_ids:
            issues.append(
                _issue(
                    BLUEPRINT_NODE_INVALID,
                    f"ReactFlow node ID '{node_id}' is duplicated.",
                    path=f"{path}/id",
                )
            )
            continue
        seen_node_ids.add(node_id)

        adlc = _node_adlc(raw_node)
        if adlc is None:
            if _is_presentation_node(raw_node):
                ignored_node_ids.add(node_id)
                continue
            issues.append(
                _issue(
                    BLUEPRINT_NODE_INVALID,
                    "Every non-presentation node in a marked blueprint must declare a WORKFLOW_STAGE.",
                    path=f"{path}/data/adlc",
                )
            )
            continue
        if adlc.get("document_type") != STAGE_DOCUMENT_TYPE:
            issues.append(
                _issue(
                    BLUEPRINT_NODE_INVALID,
                    "Stage metadata must declare document_type=WORKFLOW_STAGE.",
                    path=f"{path}/data/adlc/document_type",
                )
            )
            continue
        if adlc.get("schema_version") != AUTHORING_CONTRACT_VERSION:
            issues.append(
                _issue(
                    BLUEPRINT_NODE_INVALID,
                    "Stage metadata must use schema_version=0.1.",
                    path=f"{path}/data/adlc/schema_version",
                )
            )
            continue

        payload = {key: value for key, value in adlc.items() if key not in {"document_type", "schema_version"}}
        payload.setdefault("inputs", {})
        payload.setdefault("expected_outputs", [])
        payload.setdefault("configuration_overrides", {})
        payload.setdefault("execution_profile_overrides", {})
        payload.setdefault("policy_overrides", {})
        payload.setdefault("secret_refs", {})
        payload.setdefault("metadata", {})
        payload["position"] = raw_node.get("position")
        try:
            stage = WorkflowStage.model_validate(payload)
        except ValidationError as exc:
            issues.append(
                _issue(
                    BLUEPRINT_NODE_INVALID,
                    "Stage metadata violates the WorkflowStage contract.",
                    path=f"{path}/data/adlc",
                    details={"errors": _safe_validation_errors(exc)},
                )
            )
            continue
        if stage.stage_id in stage_ids:
            issues.append(
                _issue(
                    STAGE_ID_DUPLICATE,
                    f"Workflow stage ID '{stage.stage_id}' is duplicated.",
                    path=f"{path}/data/adlc/stage_id",
                )
            )
            continue
        stage_ids.add(stage.stage_id)
        stages[node_id] = stage
    return stages, ignored_node_ids


def _parse_edges(
    raw_edges: list[object],
    stages_by_node_id: dict[str, WorkflowStage],
    ignored_node_ids: set[str],
    workflow_definition_id: UUID,
    issues: list[PlanValidationIssue],
) -> list[WorkflowEdge]:
    edges: list[WorkflowEdge] = []
    edge_ids: set[UUID] = set()
    dependency_pairs: set[tuple[UUID, UUID]] = set()
    for index, raw_edge in enumerate(raw_edges):
        path = f"/edges/{index}"
        if not isinstance(raw_edge, dict):
            issues.append(_issue(BLUEPRINT_EDGE_INVALID, "A blueprint edge must be an object.", path=path))
            continue
        source_node_id = str(raw_edge.get("source") or "").strip()
        target_node_id = str(raw_edge.get("target") or "").strip()
        if source_node_id in ignored_node_ids or target_node_id in ignored_node_ids:
            continue
        source = stages_by_node_id.get(source_node_id)
        target = stages_by_node_id.get(target_node_id)
        if source is None or target is None:
            missing = source_node_id if source is None else target_node_id
            issues.append(
                _issue(
                    STAGE_DEPENDENCY_MISSING,
                    f"Edge references unknown workflow-stage node '{missing}'.",
                    path=path,
                )
            )
            continue
        pair = (source.stage_id, target.stage_id)
        if pair in dependency_pairs:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    "A workflow dependency pair may appear only once.",
                    path=path,
                )
            )
            continue

        adlc = _edge_adlc(raw_edge)
        unknown_edge_fields = sorted(set(adlc) - _EDGE_FIELDS)
        if unknown_edge_fields:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    "Edge metadata contains unsupported fields.",
                    path=f"{path}/data/adlc",
                    details={"fields": unknown_edge_fields},
                )
            )
            continue
        if adlc.get("document_type") not in {None, EDGE_DOCUMENT_TYPE}:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    "Edge metadata document_type must be WORKFLOW_EDGE when present.",
                    path=f"{path}/data/adlc/document_type",
                )
            )
            continue
        if adlc.get("schema_version") not in {None, AUTHORING_CONTRACT_VERSION}:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    "Edge metadata must use schema_version=0.1 when present.",
                    path=f"{path}/data/adlc/schema_version",
                )
            )
            continue
        edge_id = adlc.get("edge_id") or uuid5(
            workflow_definition_id,
            f"edge:{source.stage_id}:{target.stage_id}",
        )
        payload = {
            "edge_id": edge_id,
            "source_stage_id": source.stage_id,
            "target_stage_id": target.stage_id,
            "condition": adlc.get("condition", "ON_SUCCESS"),
            "bindings": adlc.get("bindings", []),
            "metadata": adlc.get("metadata", {}),
        }
        try:
            edge = WorkflowEdge.model_validate(payload)
        except ValidationError as exc:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    "Edge metadata violates the WorkflowEdge contract.",
                    path=f"{path}/data/adlc",
                    details={"errors": _safe_validation_errors(exc)},
                )
            )
            continue
        if edge.edge_id in edge_ids:
            issues.append(
                _issue(
                    BLUEPRINT_EDGE_INVALID,
                    f"Workflow edge ID '{edge.edge_id}' is duplicated.",
                    path=f"{path}/data/adlc/edge_id",
                )
            )
            continue
        edge_ids.add(edge.edge_id)
        dependency_pairs.add(pair)
        edges.append(edge)
    return edges


def _dependency_issues(stages: tuple[WorkflowStage, ...], edges: list[WorkflowEdge]) -> list[PlanValidationIssue]:
    if not stages:
        return []
    stage_ids = {stage.stage_id for stage in stages}
    dependencies: dict[UUID, set[UUID]] = {stage_id: set() for stage_id in stage_ids}
    dependents: dict[UUID, set[UUID]] = {stage_id: set() for stage_id in stage_ids}
    for edge in edges:
        dependencies[edge.target_stage_id].add(edge.source_stage_id)
        dependents[edge.source_stage_id].add(edge.target_stage_id)
    roots = sorted((stage_id for stage_id, values in dependencies.items() if not values), key=str)
    issues: list[PlanValidationIssue] = []
    if not roots:
        issues.append(
            _issue(WORKFLOW_HAS_NO_ROOT, "The workflow must contain at least one starting stage.", path="/edges")
        )

    indegree = {stage_id: len(values) for stage_id, values in dependencies.items()}
    queue = deque(roots)
    visited = 0
    while queue:
        stage_id = queue.popleft()
        visited += 1
        for dependent in sorted(dependents[stage_id], key=str):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if visited != len(stage_ids):
        issues.append(
            _issue(STAGE_DEPENDENCY_CYCLE, "The workflow-stage dependency graph contains a cycle.", path="/edges")
        )
    return issues


def _node_adlc(node: dict[str, Any]) -> dict[str, Any] | None:
    direct = node.get("adlc")
    data = node.get("data")
    nested = data.get("adlc") if isinstance(data, dict) else None
    if isinstance(direct, dict) and isinstance(nested, dict):
        return direct | nested
    if isinstance(nested, dict):
        return nested
    return direct if isinstance(direct, dict) else None


def _edge_adlc(edge: dict[str, Any]) -> dict[str, Any]:
    direct = edge.get("adlc")
    data = edge.get("data")
    nested = data.get("adlc") if isinstance(data, dict) else None
    direct_mapping = direct if isinstance(direct, dict) else {}
    nested_mapping = nested if isinstance(nested, dict) else {}
    return direct_mapping | nested_mapping


def _is_presentation_node(node: dict[str, Any]) -> bool:
    data = node.get("data")
    data_type = data.get("type") if isinstance(data, dict) else None
    node_type = str(node.get("type") or data_type or "").lower()
    return node_type in _PRESENTATION_NODE_TYPES


def _safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    return exc.errors(include_url=False, include_input=False)


def _issue(
    code: str,
    message: str,
    *,
    path: str,
    details: dict[str, Any] | None = None,
) -> PlanValidationIssue:
    return PlanValidationIssue(code=code, message=message, path=path, details=details or {})


def _raise_single(code: str, message: str, *, path: str) -> None:
    raise BlueprintParseError([_issue(code, message, path=path)])

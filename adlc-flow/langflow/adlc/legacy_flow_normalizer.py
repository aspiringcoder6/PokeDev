"""Normalize explicitly selected legacy ADLC canvas graphs into mock tasks."""

from __future__ import annotations

import re
from collections import deque
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langflow.adlc.models import AdlcTaskDefinition, GateType, MockArtifactSpec


class FlowDagValidationError(ValueError):
    """The saved legacy flow cannot be normalized into an executable ADLC DAG."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("Invalid ADLC DAG: " + "; ".join(issues))


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _template_value(template: dict[str, Any], key: str) -> Any:
    field = template.get(key)
    if isinstance(field, dict) and "value" in field:
        return field["value"]
    return field


def _node_metadata(node: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = _mapping(node.get("data"))
    component = _mapping(data.get("node"))
    template = _mapping(component.get("template"))
    adlc = _mapping(node.get("adlc")) | _mapping(data.get("adlc"))
    template_adlc = _template_value(template, "adlc")
    if isinstance(template_adlc, dict):
        adlc |= template_adlc
    return data, component, adlc


def _is_task_node(node: dict[str, Any]) -> bool:
    data, _, adlc = _node_metadata(node)
    if adlc.get("enabled") is False:
        return False
    node_type = str(node.get("type") or data.get("type") or "").lower()
    return node_type not in {"note", "notenode", "group", "groupnode"}


def _node_name(node: dict[str, Any]) -> str:
    data, component, adlc = _node_metadata(node)
    return str(
        adlc.get("name")
        or component.get("display_name")
        or data.get("display_name")
        or data.get("label")
        or data.get("type")
        or node.get("id")
    )


def _explicit_approval_gate(node: dict[str, Any]) -> GateType | None:
    """Read only ADLC-owned gate metadata; names and component types are presentation data."""
    _, _, adlc = _node_metadata(node)
    gate_value = adlc.get("approvalGate", adlc.get("approval_gate"))
    if gate_value is not None:
        try:
            return GateType(str(gate_value).upper())
        except ValueError as exc:
            node_id = str(node.get("id") or "<unknown>")
            supported = ", ".join(gate.value for gate in GateType)
            raise FlowDagValidationError(
                [f"Task '{node_id}' has unsupported approval gate '{gate_value}'; expected one of {supported}."]
            ) from exc
    if adlc.get("approval") is True or str(adlc.get("kind", "")).lower() in {"approval", "approval_gate"}:
        return GateType.AFTER_TASK
    return None


def _definition(flow_id: UUID, node: dict[str, Any], dependencies: list[str]) -> AdlcTaskDefinition:
    node_id = str(node["id"])
    _, component, adlc = _node_metadata(node)
    template = _mapping(component.get("template"))
    name = _node_name(node)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "task"

    output = adlc.get("predeterminedOutput") or adlc.get("predetermined_output")
    if not isinstance(output, dict):
        output = {"summary": f"Mock task '{name}' completed.", "node_id": node_id}

    artifact_data = _mapping(adlc.get("artifact"))
    artifact = MockArtifactSpec(
        kind=str(artifact_data.get("kind") or "DOCUMENT"),
        name=str(artifact_data.get("name") or f"{slug}-result.txt"),
        media_type=str(artifact_data.get("mediaType") or artifact_data.get("media_type") or "text/plain"),
        content=str(artifact_data.get("content") or f"Mock artifact produced by {name}."),
    )
    task_type = str(
        adlc.get("taskType") or adlc.get("task_type") or _template_value(template, "task_type") or f"mock.{slug}"
    )
    return AdlcTaskDefinition(
        id=uuid5(NAMESPACE_URL, f"adlc:flow:{flow_id}:node:{node_id}"),
        key=node_id,
        name=name,
        task_type=task_type,
        dependencies=dependencies,
        predetermined_output=output,
        artifact=artifact,
        approval_gate=_explicit_approval_gate(node),
    )


def normalize_legacy_flow_graph(flow_id: UUID, graph: dict[str, Any]) -> list[AdlcTaskDefinition]:
    """Normalize a graph selected through ``LEGACY_FLOW`` mode and validate its DAG.

    Every non-presentation node remains a mock task for compatibility. A node may
    opt out with ``data.adlc.enabled=false``. Approval is enabled only by explicit
    ADLC metadata (``approval``, ``kind``, or ``approvalGate``); a display name or
    component type such as ``Approval`` has no execution semantics.
    """
    issues: list[str] = []
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list):
        issues.append("The flow graph must contain a nodes array.")
        raw_nodes = []
    if not isinstance(raw_edges, list):
        issues.append("The flow graph must contain an edges array.")
        raw_edges = []

    task_nodes: dict[str, dict[str, Any]] = {}
    ignored_ids: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            issues.append(f"Node at index {index} must be an object.")
            continue
        raw_id = raw_node.get("id")
        if raw_id is None or not str(raw_id).strip():
            issues.append(f"Task node at index {index} must have a non-empty id.")
            continue
        node_id = str(raw_id)
        if not _is_task_node(raw_node):
            ignored_ids.add(node_id)
            continue
        if node_id in task_nodes:
            issues.append(f"Task id '{node_id}' is duplicated.")
            continue
        task_nodes[node_id] = raw_node

    if not task_nodes:
        issues.append("The flow must contain at least one ADLC task node.")

    dependencies: dict[str, list[str]] = {node_id: [] for node_id in task_nodes}
    for index, raw_edge in enumerate(raw_edges):
        if not isinstance(raw_edge, dict):
            issues.append(f"Edge at index {index} must be an object.")
            continue
        source = str(raw_edge.get("source") or "")
        target = str(raw_edge.get("target") or "")
        if source in ignored_ids or target in ignored_ids:
            continue
        if not source or not target:
            issues.append(f"Edge at index {index} must have source and target task ids.")
            continue
        if source not in task_nodes:
            issues.append(f"Dependency task '{source}' referenced by '{target}' does not exist.")
            continue
        if target not in task_nodes:
            issues.append(f"Dependent task '{target}' referenced by '{source}' does not exist.")
            continue
        if source not in dependencies[target]:
            dependencies[target].append(source)

    roots = [node_id for node_id, task_dependencies in dependencies.items() if not task_dependencies]
    if task_nodes and not roots:
        issues.append("The DAG must contain at least one starting task.")

    indegree = {node_id: len(task_dependencies) for node_id, task_dependencies in dependencies.items()}
    dependents: dict[str, list[str]] = {node_id: [] for node_id in task_nodes}
    for node_id, task_dependencies in dependencies.items():
        for dependency in task_dependencies:
            dependents[dependency].append(node_id)
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for dependent in dependents[node_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if task_nodes and visited != len(task_nodes):
        issues.append("The ADLC task graph contains a cycle.")

    if issues:
        raise FlowDagValidationError(issues)
    return [_definition(flow_id, node, dependencies[node_id]) for node_id, node in task_nodes.items()]


__all__ = ["FlowDagValidationError", "normalize_legacy_flow_graph"]

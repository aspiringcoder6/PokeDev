"""Resolve design-only input blocks without extending frozen package contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from langflow.adlc.blueprints.models import PlanValidationIssue
from langflow.adlc.planning.errors import BlueprintParseError

MAX_INPUT_NAME_LENGTH = 128


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _reject(message: str, path: str, code: str = "AUTHORING_BLOCK_INVALID") -> None:
    raise BlueprintParseError([PlanValidationIssue(code=code, message=message, path=path, details={})])


def prepare_authoring_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Bind explicit literal requirement inputs; WIP blocks can only be saved.

    The persisted canvas is never mutated. Executable stages still pass the
    ordinary parser, package resolver, IO validation, and approval pipeline.
    """
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not any(
        isinstance(n, dict) and isinstance(n.get("data"), dict) and "adlcDraft" in n["data"] for n in nodes
    ):
        return graph
    graph = deepcopy(graph)
    by_id: dict[str, dict] = {}
    inputs: dict[str, dict] = {}
    block_ids: set[UUID] = set()
    for index, node in enumerate(graph["nodes"]):
        if not isinstance(node, dict):
            continue  # The ordinary parser supplies its existing diagnostic.
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id or node_id in by_id:
            _reject("Every design block needs a unique canvas ID.", f"/nodes/{index}/id")
        by_id[node_id] = node
        data = node.get("data")
        if not isinstance(data, dict) or "adlcDraft" not in data:
            continue
        draft = data["adlcDraft"]
        path = f"/nodes/{index}/data/adlcDraft"
        if not isinstance(draft, dict) or data.get("adlc") is not None:
            _reject("Design blocks cannot also declare an executable stage.", path)
        if draft.get("document_type") != "ADLC_AUTHORING_BLOCK" or draft.get("schema_version") != "0.1":
            _reject("Unsupported authoring block version.", path)
        if draft.get("kind") == "PLANNED_PACKAGE":
            _reject("Remove or replace WIP packages before reviewing an execution plan.", path, "AUTHORING_PACKAGE_WIP")
        if draft.get("kind") != "REQUIREMENT":
            _reject("Unsupported authoring block kind.", path)
        if set(draft) - {"document_type", "schema_version", "block_id", "kind", "name", "objective", "requirement"}:
            _reject("Requirement blocks contain unsupported fields.", path)
        for field, limit in (("block_id", 128), ("name", 256), ("objective", 2000), ("requirement", 20000)):
            value = draft.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                _reject(f"Requirement {field} must be non-empty text of at most {limit} characters.", f"{path}/{field}")
        inputs[node_id] = draft
        try:
            block_id = UUID(draft["block_id"])
        except ValueError:
            _reject("A requirement block needs a UUID identity.", f"{path}/block_id")
        if block_id in block_ids:
            _reject("Requirement block identities must be unique.", f"{path}/block_id")
        block_ids.add(block_id)

    edges = graph.get("edges")
    if not isinstance(edges, list):
        return graph
    consumed: set[str] = set()
    bound: set[tuple[str, str]] = set()
    retained: list[object] = []
    pairs: set[tuple[str, str]] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            retained.append(edge)
            continue
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            _reject("Connections require string source and target IDs.", f"/edges/{index}")
        if target in inputs:
            _reject("A requirement is a workflow input and cannot depend on another stage.", f"/edges/{index}")
        if source not in inputs:
            retained.append(edge)
            continue
        if target not in by_id or (source, target) in pairs:
            _reject("Requirement connections must target an existing stage exactly once.", f"/edges/{index}")
        pairs.add((source, target))
        metadata = _mapping(edge.get("data")).get("adlc")
        if (
            not isinstance(metadata, dict)
            or metadata.get("document_type") != "WORKFLOW_EDGE"
            or metadata.get("schema_version") != "0.1"
        ):
            _reject("Requirement connections need versioned edge metadata.", f"/edges/{index}")
        try:
            UUID(str(metadata.get("edge_id")))
        except ValueError:
            _reject("Requirement connections need a UUID edge identity.", f"/edges/{index}")
        if set(metadata) - {"document_type", "schema_version", "edge_id", "condition", "bindings", "metadata"}:
            _reject("Requirement connections contain unsupported fields.", f"/edges/{index}")
        if metadata.get("condition") != "ON_SUCCESS" or metadata.get("bindings") != []:
            _reject(
                "Requirement connections supply a named literal input, without routing or artifact transforms.",
                f"/edges/{index}",
            )
        slot = _mapping(metadata.get("metadata")).get("authoring_input")
        if not isinstance(slot, str) or not slot.strip() or len(slot) > MAX_INPUT_NAME_LENGTH:
            _reject(
                "Choose the named stage input for this requirement.",
                f"/edges/{index}/data/adlc/metadata/authoring_input",
            )
        stage = _mapping(by_id[target].get("data")).get("adlc")
        if not isinstance(stage, dict) or stage.get("document_type") != "WORKFLOW_STAGE":
            _reject("Requirement values must bind to a published workflow stage.", f"/edges/{index}")
        if (target, slot) in bound:
            _reject("Two requirement blocks cannot supply the same stage input.", f"/edges/{index}")
        bound.add((target, slot))
        stage_inputs = stage.setdefault("inputs", {})
        if not isinstance(stage_inputs, dict):
            _reject("Stage inputs must be an object.", f"/edges/{index}")
        if slot in stage_inputs:
            _reject("Clear the direct input before binding a requirement block to that slot.", f"/edges/{index}")
        draft = inputs[source]
        stage_inputs[slot] = draft["requirement"]
        stage_meta = stage.setdefault("metadata", {})
        if not isinstance(stage_meta, dict):
            _reject("Stage metadata must be an object.", f"/edges/{index}")
        sources = stage_meta.setdefault("authoring_inputs", {})
        if not isinstance(sources, dict):
            _reject("Authoring input provenance must be an object.", f"/edges/{index}")
        sources[slot] = {
            "block_id": draft["block_id"],
            "name": draft["name"],
            "objective": draft["objective"],
            "edge_id": metadata["edge_id"],
        }
        consumed.add(source)
    if set(inputs) != consumed:
        _reject("Connect each requirement to a named stage input before reviewing a plan.", "/edges")
    graph["nodes"] = [node for node in graph["nodes"] if not isinstance(node, dict) or node.get("id") not in inputs]
    graph["edges"] = retained
    return graph

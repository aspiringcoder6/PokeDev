"""Semantic skilltree checks, independent of layout and execution outcomes."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from langflow.adlc.contract_models import (
    MAX_DOCUMENT_BYTES,
    ContractCheck,
    ContractValidation,
    SkilltreeDocument,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


def document_bytes(document: SkilltreeDocument) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no whitespace, no NaN or pixel data."""
    return json.dumps(
        document.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def content_digest(document: SkilltreeDocument) -> str:
    return "sha256:" + hashlib.sha256(document_bytes(document)).hexdigest()


def structural_issues(document: SkilltreeDocument) -> list[str]:
    issues: list[str] = []
    node_ids = {node.node_id for node in document.nodes}
    if len(node_ids) != len(document.nodes):
        issues.append("CONTRACT_DUPLICATE_NODE")
    edges = {(edge.source_id, edge.target_id, edge.relation) for edge in document.dependencies}
    if len(edges) != len(document.dependencies):
        issues.append("CONTRACT_DUPLICATE_DEPENDENCY")
    graph = {node_id: set() for node_id in node_ids}
    parents: set[UUID] = set()
    kinds = {node.node_id: node.kind for node in document.nodes}
    for edge in document.dependencies:
        if edge.source_id not in node_ids or edge.target_id not in node_ids:
            issues.append("CONTRACT_DEPENDENCY_NODE_MISSING")
            continue
        if edge.relation == "CONTAINS":
            if edge.target_id in parents or kinds[edge.source_id] != "MILESTONE":
                issues.append("CONTRACT_CONTAINMENT_INVALID")
            parents.add(edge.target_id)
        graph[edge.source_id].add(edge.target_id)
    visited: set[UUID] = set()
    visiting: set[UUID] = set()

    def visit(node_id: UUID) -> bool:
        if node_id in visiting:
            return False
        if node_id in visited:
            return True
        visiting.add(node_id)
        if any(not visit(child) for child in graph[node_id]):
            return False
        visiting.remove(node_id)
        visited.add(node_id)
        return True

    if any(not visit(node_id) for node_id in graph):
        issues.append("CONTRACT_DEPENDENCY_CYCLE")
    if len(document_bytes(document)) > MAX_DOCUMENT_BYTES:
        issues.append("CONTRACT_DOCUMENT_TOO_LARGE")
    return list(dict.fromkeys(issues))


def validate_document(document: SkilltreeDocument, now: datetime) -> ContractValidation:
    structural = structural_issues(document)
    tasks = [node for node in document.nodes if node.kind == "TASK"]
    missing_criteria = any(not node.acceptance_criteria for node in tasks)
    missing_verifier = any(
        criterion.verification != "HUMAN" and not criterion.verifier_ref
        for node in document.nodes
        for criterion in node.acceptance_criteria
    )
    checks = [
        ContractCheck(
            check_id="structure",
            passed=not structural,
            summary="Graph identities, dependencies and bounds are valid." if not structural else ", ".join(structural),
        ),
        ContractCheck(
            check_id="task-presence", passed=bool(tasks), summary="At least one executable task is required."
        ),
        ContractCheck(
            check_id="acceptance-criteria",
            passed=not missing_criteria,
            summary="Every task must declare its acceptance criteria.",
        ),
        ContractCheck(
            check_id="verifier-declarations",
            passed=not missing_verifier,
            summary="TEST/ARTIFACT criteria must name a verifier; no criterion was executed.",
        ),
    ]
    return ContractValidation(
        content_digest=content_digest(document),
        passed=all(check.passed for check in checks),
        checks=checks,
        checked_at=now,
    )

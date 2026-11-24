"""Generated human-readable views; never a second editable contract authority."""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langflow.adlc.contract_models import ContractRead


def _text(value: str) -> str:
    # Plain data, not executable HTML or Markdown links. Preserve complete wording.
    return re.sub(r"([\\`*_\[\]{}()#!|>])", r"\\\1", html.escape(value)).replace("\r", "").replace("\n", " ")


def contract_markdown(contract: ContractRead) -> str:
    document = contract.document
    lines = [
        f"# {_text(document.title)}",
        "",
        f"Status: {contract.status}",
        f"Contract: {document.contract_id} · revision {document.revision}",
        f"Digest: `{contract.reference.content_digest}`",
        "",
        "Validation checks declarations only; acceptance criteria have NOT been executed.",
        "",
        "## Objective",
        "",
        _text(document.scope.objective),
        "",
        "## Scope",
        "",
        "In scope:",
        "",
        *[f"- {_text(item)}" for item in document.scope.in_scope],
        "",
        "Out of scope:",
        "",
        *[f"- {_text(item)}" for item in document.scope.out_of_scope],
        "",
        "## Declared constraints",
        "",
        f"Read-only: {document.constraints.read_only}",
        f"Allowed paths: {_text(', '.join(document.constraints.allowed_paths))}",
        f"Forbidden actions: {_text(', '.join(document.constraints.forbidden_actions))}",
        "",
        "Execution permission enforcement is a separate H5C boundary.",
        "",
        "## Nodes",
        "",
    ]
    for node in document.nodes:
        lines.extend([f"### {_text(node.title)} ({node.kind})", "", f"ID: {node.node_id}", ""])
        if node.description:
            lines.extend([_text(node.description), ""])
        lines.extend(f"- [{item.verification}] {_text(item.description)}" for item in node.acceptance_criteria)
        lines.append("")
    lines.extend(["## Dependencies", ""])
    lines.extend(f"- {edge.source_id} → {edge.target_id} ({edge.relation})" for edge in document.dependencies)
    if contract.approval:
        lines.extend(
            [
                "",
                "## Human approval",
                "",
                f"Approved by: {_text(contract.approval.approved_by)}",
                f"Approved at: {contract.approval.approved_at.isoformat()}",
            ]
        )
    return "\n".join(lines) + "\n"

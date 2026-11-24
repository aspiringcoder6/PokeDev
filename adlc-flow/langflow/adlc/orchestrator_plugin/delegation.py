"""Delegation contracts — Monarch hands work to specialists as contracts (G4).

The orchestrator system prompt used to carry a free-form 6-section
markdown template for every specialist delegation (TASK / EXPECTED
OUTCOME / REQUIRED TOOLS / MUST DO / MUST NOT DO / CONTEXT). Prose
templates cannot be verified, so this module turns that template into a
schema-bound :class:`DelegatedTask` that materializes directly into the
existing contract system
(:mod:`langflow.adlc.contract_models` — a skilltree ``TASK`` node plus
the document-level roadmap constraints).

Field mapping (old template → contract):

======================  =====================================================
``task_name``           ``SkilltreeNodeSpec.title`` (kind ``TASK``)
``objective``           ``SkilltreeNodeSpec.description``
``expected_files``      checklist inside the node description
``acceptance_criteria`` ``SkilltreeNodeSpec.acceptance_criteria`` (HUMAN)
``scope_paths``         ``RoadmapConstraints.allowed_paths``
``must_not_do``         ``RoadmapConstraints.forbidden_actions`` /
                        ``RoadmapScope.out_of_scope``
======================  =====================================================
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from langflow.adlc.contract_models import (
    AcceptanceCriterion,
    RoadmapConstraints,
    RoadmapScope,
    SkilltreeDependency,
    SkilltreeDocument,
    SkilltreeNode,
    SkilltreeNodeSpec,
)

# Structured-output schema (AgentComponent output_schema TableInput rows)
# for one delegation. The six fields replace the old 6-section markdown
# template; lists are expressed with ``multiple=True``.
DELEGATION_OUTPUT_SCHEMA: tuple[dict[str, Any], ...] = (
    {
        "name": "task_name",
        "type": "str",
        "description": "1. TASK — the exact deliverable, obsessively specific.",
        "multiple": False,
    },
    {
        "name": "objective",
        "type": "str",
        "description": (
            "2/4. EXPECTED OUTCOME + MUST DO — what must be true when the "
            "attempt ends, including which existing patterns to follow."
        ),
        "multiple": False,
    },
    {
        "name": "expected_files",
        "type": "str",
        "description": "2. EXPECTED OUTCOME — exact repository-relative paths created or modified.",
        "multiple": True,
    },
    {
        "name": "scope_paths",
        "type": "str",
        "description": (
            "2/5. Scope — repository-relative directories or files the "
            "specialist may touch (contract allowed_paths)."
        ),
        "multiple": True,
    },
    {
        "name": "must_not_do",
        "type": "str",
        "description": (
            "5. MUST NOT DO — explicit prohibitions, each at most 200 "
            "characters (contract forbidden_actions)."
        ),
        "multiple": True,
    },
    {
        "name": "acceptance_criteria",
        "type": "str",
        "description": "2/3. Verification — outcomes a reviewer can check (commands, behaviors).",
        "multiple": True,
    },
)


class DelegatedTask(BaseModel):
    """One specialist delegation, expressed as a contract-shaped object."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    task_name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    expected_files: list[str] = Field(default_factory=list, max_length=32)
    scope_paths: list[str] = Field(default_factory=list, max_length=32)
    must_not_do: list[str] = Field(default_factory=list, max_length=32)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("task_name", "objective", mode="before")
    @classmethod
    def _strip_required_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("expected_files", "scope_paths", "must_not_do", "acceptance_criteria", mode="before")
    @classmethod
    def _clean_string_lists(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return value


def parse_delegated_task(data: dict[str, Any]) -> DelegatedTask:
    """Parse one structured delegation payload (resilient to extra keys)."""
    if not isinstance(data, dict):
        msg = f"Delegation payload must be an object, got {type(data).__name__}."
        raise ValueError(msg)
    return DelegatedTask.model_validate(data)


def delegation_schema_example() -> str:
    """Compact JSON example of the delegation schema, for prompts."""
    return (
        '{"task_name": "Implement payment retry service", '
        '"objective": "Add idempotent retry to the payment service following '
        'the pattern in services/notify.py.", '
        '"expected_files": ["src/services/payment_retry.py", '
        '"tests/unit/test_payment_retry.py"], '
        '"scope_paths": ["src/services", "tests/unit"], '
        '"must_not_do": ["Do not modify the payment API schema", '
        '"Do not add dependencies"], '
        '"acceptance_criteria": ["pytest tests/unit/test_payment_retry.py passes", '
        '"Retries are idempotent per payment id"]}'
    )


def to_skilltree_node_spec(task: DelegatedTask) -> SkilltreeNodeSpec:
    """Materialize one delegation as a contract ``TASK`` node."""
    description = task.objective
    if task.expected_files:
        listing = "\n".join(f"- {path}" for path in task.expected_files)
        description = f"{description}\n\nExpected files:\n{listing}"
    return SkilltreeNodeSpec(
        kind="TASK",
        title=task.task_name,
        description=description,
        acceptance_criteria=[
            AcceptanceCriterion(description=criterion, verification="HUMAN")
            for criterion in task.acceptance_criteria
        ],
    )


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def to_roadmap_constraints(tasks: Sequence[DelegatedTask]) -> RoadmapConstraints:
    """Document-level constraints from the delegations' scope and prohibitions."""
    scope_paths = _unique(path for task in tasks for path in task.scope_paths)
    must_not_do = _unique(rule for task in tasks for rule in task.must_not_do)
    return RoadmapConstraints(
        allowed_paths=scope_paths or ["*"],
        forbidden_actions=must_not_do or ["commit", "push"],
    )


def build_skilltree_document(
    *,
    title: str,
    objective: str,
    tasks: Sequence[DelegatedTask],
    contract_id: UUID,
    revision: int = 1,
    dependencies: Mapping[str, Sequence[str]] | None = None,
) -> SkilltreeDocument:
    """Materialize a delegation batch into a contract skilltree document.

    Node IDs are derived deterministically (``uuid5`` over the contract
    ID and task name) so re-materializing the same delegation batch
    yields the same contract. ``dependencies`` maps a task name to the
    task names it requires; unknown names raise ``ValueError`` instead
    of being dropped silently.
    """
    names = [task.task_name for task in tasks]
    if len(set(names)) != len(names):
        duplicated = sorted({name for name in names if names.count(name) > 1})
        msg = f"Duplicate task names in delegation batch: {duplicated}"
        raise ValueError(msg)

    node_ids = {name: uuid5(contract_id, name) for name in names}
    nodes = [
        SkilltreeNode(node_id=node_ids[task.task_name], **to_skilltree_node_spec(task).model_dump())
        for task in tasks
    ]

    edges: list[SkilltreeDependency] = []
    for task_name, required in (dependencies or {}).items():
        if task_name not in node_ids:
            msg = f"Dependency map references unknown task {task_name!r}."
            raise ValueError(msg)
        for required_name in required:
            if required_name not in node_ids:
                msg = f"Task {task_name!r} requires unknown task {required_name!r}."
                raise ValueError(msg)
            if required_name == task_name:
                continue
            edges.append(
                SkilltreeDependency(
                    source_id=node_ids[task_name],
                    target_id=node_ids[required_name],
                    relation="REQUIRES",
                )
            )

    scope_paths = _unique(path for task in tasks for path in task.scope_paths)
    must_not_do = _unique(rule for task in tasks for rule in task.must_not_do)
    return SkilltreeDocument(
        contract_id=contract_id,
        revision=revision,
        title=title,
        scope=RoadmapScope(
            objective=objective,
            in_scope=scope_paths,
            out_of_scope=must_not_do,
        ),
        constraints=to_roadmap_constraints(tasks),
        nodes=nodes,
        dependencies=edges,
    )


__all__ = [
    "DELEGATION_OUTPUT_SCHEMA",
    "DelegatedTask",
    "build_skilltree_document",
    "delegation_schema_example",
    "parse_delegated_task",
    "to_roadmap_constraints",
    "to_skilltree_node_spec",
]

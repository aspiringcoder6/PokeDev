"""Validation for :class:`PlanSpec` execution graphs.

The validator enforces structural invariants that Pydantic cannot express
on its own:

* Every dependency ID resolves to a known node (task or subtask).
* The combined task + subtask graph is acyclic.
* Every node is reachable from at least one root (no orphans).
* Subtask granularity is within sensible bounds (warns, not errors).

Validation is split into two phases:

1. :func:`validate_plan` — raises :class:`PlanValidationError` on any
   structural problem. Call this before dispatching any work.
2. :func:`lint_plan` — returns a list of :class:`PlanLintWarning` for
   soft issues (e.g. a subtask with a very short objective). Call this
   to surface quality issues without blocking execution.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langflow.adlc.plan_models import PlanSpec


# Soft bounds for subtask granularity. These are heuristics, not hard
# limits — the validator only warns when they are violated.
_MIN_OBJECTIVE_CHARS = 50
_MAX_OBJECTIVE_CHARS = 8_000
_MAX_SUBTASKS_PER_TASK = 12
_MAX_PARALLEL_BRANCHING = 8


class PlanValidationError(ValueError):
    """Raised when a plan has a structural problem that blocks execution."""


@dataclass(frozen=True, slots=True)
class PlanLintWarning:
    """A non-fatal quality issue in a plan."""

    code: str
    message: str
    node_id: str | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        prefix = f"[{self.node_id}] " if self.node_id else ""
        return f"{prefix}{self.code}: {self.message}"


def _build_node_index(plan: PlanSpec) -> dict[str, str]:
    """Map every node id to its kind: ``"task"`` or ``"subtask:<task_id>"``."""
    index: dict[str, str] = {}
    for task in plan.tasks:
        index[task.id] = "task"
        for subtask in task.subtasks:
            index[subtask.id] = f"subtask:{task.id}"
    return index


def _build_edges(plan: PlanSpec) -> dict[str, list[str]]:
    """Build the combined adjacency list (task deps + subtask deps)."""
    edges: dict[str, list[str]] = defaultdict(list)
    for task in plan.tasks:
        for dep in task.dependencies:
            edges[task.id].append(dep)
        for subtask in task.subtasks:
            for dep in subtask.dependencies:
                edges[subtask.id].append(dep)
    return edges


def _check_dependencies_resolve(
    plan: PlanSpec,
    index: dict[str, str],
) -> None:
    """Every dependency ID must point to a known node."""
    for task in plan.tasks:
        for dep in task.dependencies:
            if dep not in index:
                msg = (
                    f"Task {task.id!r} depends on unknown node {dep!r}. "
                    f"Known nodes: {sorted(index)}."
                )
                raise PlanValidationError(msg)
        for subtask in task.subtasks:
            for dep in subtask.dependencies:
                if dep not in index:
                    msg = (
                        f"Subtask {subtask.id!r} depends on unknown node {dep!r}. "
                        f"Known nodes: {sorted(index)}."
                    )
                    raise PlanValidationError(msg)


def _check_no_cycles(plan: PlanSpec, edges: dict[str, list[str]]) -> None:
    """Detect cycles via Kahn's algorithm. Raises on any cycle."""
    # Compute in-degree for every node.
    in_degree: dict[str, int] = defaultdict(int)
    for node in _all_nodes(plan):
        in_degree[node] = 0
    for src, targets in edges.items():
        for _ in targets:
            in_degree[src] = in_degree[src]  # ensure key exists
        # edges go from dep -> dependent, so increment in-degree of dependent
    # Rebuild edges as dep -> dependent for Kahn's.
    forward: dict[str, list[str]] = defaultdict(list)
    for dependent, deps in edges.items():
        for dep in deps:
            forward[dep].append(dependent)
            in_degree[dependent] += 1

    queue: deque[str] = deque(
        node for node, degree in in_degree.items() if degree == 0
    )
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for neighbor in forward[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(in_degree):
        # Find one cycle for the error message.
        remaining = {n for n, d in in_degree.items() if d > 0}
        cycle_hint = _find_cycle_hint(forward, remaining)
        msg = (
            f"Plan contains a cycle involving nodes: {sorted(remaining)}. "
            f"{cycle_hint}"
        )
        raise PlanValidationError(msg)


def _find_cycle_hint(
    forward: dict[str, list[str]],
    remaining: set[str],
) -> str:
    """Best-effort: return a textual hint about where the cycle is."""
    if not remaining:
        return ""
    start = next(iter(remaining))
    path = [start]
    seen = {start}
    current = start
    while True:
        neighbors = [n for n in forward.get(current, []) if n in remaining]
        if not neighbors:
            break
        current = neighbors[0]
        if current in seen:
            path.append(current)
            break
        path.append(current)
        seen.add(current)
    return f"Cycle path: {' -> '.join(path)}."


def _check_reachability(plan: PlanSpec, edges: dict[str, list[str]]) -> None:
    """Every node must be reachable from at least one root.

    A root is a node with no dependencies (not a key in ``edges``).
    """
    all_nodes = set(_all_nodes(plan))
    # Roots = nodes that have no dependencies of their own.
    roots = all_nodes - set(edges.keys())
    if not roots:
        msg = "Plan has no root nodes (every node has at least one dependency)."
        raise PlanValidationError(msg)

    # Build forward edges: dep -> [dependents].
    forward: dict[str, list[str]] = defaultdict(list)
    for dependent, deps in edges.items():
        for dep in deps:
            forward[dep].append(dependent)

    # BFS from roots following forward edges.
    reachable: set[str] = set()
    queue: deque[str] = deque(roots)
    while queue:
        node = queue.popleft()
        if node in reachable:
            continue
        reachable.add(node)
        for neighbor in forward.get(node, []):
            queue.append(neighbor)
    unreachable = all_nodes - reachable
    if unreachable:
        msg = (
            f"Plan has unreachable nodes (no path from any root): "
            f"{sorted(unreachable)}."
        )
        raise PlanValidationError(msg)


def _all_nodes(plan: PlanSpec) -> list[str]:
    nodes: list[str] = []
    for task in plan.tasks:
        nodes.append(task.id)
        nodes.extend(s.id for s in task.subtasks)
    return nodes


def validate_plan(plan: PlanSpec) -> None:
    """Validate a plan's structure. Raises :class:`PlanValidationError` on failure.

    Checks performed:

    1. All dependency IDs resolve to known nodes.
    2. The combined task + subtask graph is acyclic.
    3. Every node is reachable from at least one root.
    """
    index = _build_node_index(plan)
    _check_dependencies_resolve(plan, index)
    edges = _build_edges(plan)
    _check_no_cycles(plan, edges)
    _check_reachability(plan, edges)


def lint_plan(plan: PlanSpec) -> list[PlanLintWarning]:
    """Return non-fatal quality warnings about a plan.

    Checks performed:

    * Subtask objective is suspiciously short or long.
    * Task has too many subtasks (likely over-decomposed).
    * A node has too many direct dependents (likely a bottleneck).
    """
    warnings: list[PlanLintWarning] = []
    edges = _build_edges(plan)

    for task in plan.tasks:
        if len(task.subtasks) > _MAX_SUBTASKS_PER_TASK:
            warnings.append(
                PlanLintWarning(
                    code="too_many_subtasks",
                    message=(
                        f"Task has {len(task.subtasks)} subtasks "
                        f"(>{_MAX_SUBTASKS_PER_TASK}). Consider grouping."
                    ),
                    node_id=task.id,
                )
            )
        for subtask in task.subtasks:
            length = len(subtask.objective)
            if length < _MIN_OBJECTIVE_CHARS:
                warnings.append(
                    PlanLintWarning(
                        code="subtask_too_small",
                        message=(
                            f"Subtask objective is only {length} chars "
                            f"(<{_MIN_OBJECTIVE_CHARS}). Likely over-decomposed."
                        ),
                        node_id=subtask.id,
                    )
                )
            elif length > _MAX_OBJECTIVE_CHARS:
                warnings.append(
                    PlanLintWarning(
                        code="subtask_too_large",
                        message=(
                            f"Subtask objective is {length} chars "
                            f"(>{_MAX_OBJECTIVE_CHARS}). Consider splitting."
                        ),
                        node_id=subtask.id,
                    )
                )

    # Branching factor: how many nodes directly depend on each node?
    dependents: dict[str, int] = defaultdict(int)
    for dependent, deps in edges.items():
        for dep in deps:
            dependents[dep] += 1
    for node, count in dependents.items():
        if count > _MAX_PARALLEL_BRANCHING:
            warnings.append(
                PlanLintWarning(
                    code="high_branching",
                    message=(
                        f"Node has {count} direct dependents "
                        f"(>{_MAX_PARALLEL_BRANCHING}). May serialize execution."
                    ),
                    node_id=node,
                )
            )

    return warnings


__all__ = [
    "PlanLintWarning",
    "PlanValidationError",
    "lint_plan",
    "validate_plan",
]

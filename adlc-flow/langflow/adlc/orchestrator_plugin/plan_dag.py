"""Plan DAG parsing, validation and quality linting for LLM-generated plans.

When a plugin plans with a live LLM, the raw structured output must be
parsed into step drafts and proven safe before it may become an
:class:`~langflow.adlc.orchestrator_plugin.interface.ExecutionPlan`:

* **Hard problems** — an unknown capability value, an unresolved
  ``depends_on`` reference, or a cycle — raise
  :class:`PlanGenerationError` immediately. The plan is never patched
  blindly (the control-plane contract: an invalid DAG is surfaced, not
  repaired).
* **Quality problems** — a step mixing capability groups (e.g. code
  generation + security scan, which the router must assign to different
  executors) or a fully serial plan whose step descriptions look
  independent — are returned by :func:`plan_quality_issues` so the
  plugin can regenerate with feedback instead of shipping a bad DAG.

Decomposition rule (control-plane parallelism unit): one step = one
deliverable = one agent = one attempt. The DAG carries the parallelism;
agents never spawn subagents at execution time.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langflow.adlc.orchestrator_plugin.interface import PlanStep
from langflow.adlc.resource_manager import AgentCapability

_MAX_STEPS = 64
_MAX_STEP_NAME = 256
_MAX_STEP_DESCRIPTION = 4096
_MAX_LIST_ITEMS = 32

# Serial-chain linting only fires when the chain is long enough that the
# missing parallelism is a real plan smell, not a two-step pipeline.
_MIN_CHAIN_LENGTH_FOR_LINT = 3

# Words too generic to count as evidence that two step descriptions
# describe related work. Kept small on purpose: the lint is a heuristic
# regeneration signal, never a verdict.
_STOPWORD_TOKENS = frozenset(
    {
        # English
        "the", "and", "for", "with", "that", "this", "from", "into",
        "onto", "each", "all", "any", "are", "was", "were", "have",
        "has", "will", "must", "should", "then", "when", "after",
        "before", "step", "stage", "task", "plan", "using", "based",
        "make", "sure", "ensure", "update", "create", "implement",
        # Vietnamese
        "và", "cho", "các", "được", "trong", "một", "những", "theo",
        "tới", "trên", "dưới", "sau", "trước", "khi", "của",
    }
)

_MIN_MEANINGFUL_TOKEN = 4


class PlanGenerationError(RuntimeError):
    """Raised when a plugin-generated plan cannot be accepted.

    ``issues`` lists every concrete problem found. This error is
    intentionally terminal: callers regenerate with feedback (quality
    issues) or surface the failure (hard issues) — the DAG is never
    silently rewritten.
    """

    def __init__(self, issues: list[str] | str) -> None:
        self.issues = [issues] if isinstance(issues, str) else list(issues)
        super().__init__("; ".join(self.issues))


@dataclass(frozen=True, slots=True)
class StepDraft:
    """One parsed step from a planner's structured output.

    ``depends_on`` still uses step *names* (what the LLM emits); the
    UUID resolution happens in :func:`build_plan_steps` after validation.
    """

    name: str
    description: str
    required_capabilities: tuple[AgentCapability, ...]
    depends_on: tuple[str, ...]
    expected_outputs: tuple[str, ...]


# Capability groups used by the decomposition rule: a step that mixes
# groups would need one executor to both produce and verify artifacts,
# which breaks capability-based routing. Same-group combinations (e.g.
# code generation + content writing for a doc-plus-code deliverable)
# stay acceptable.
PRODUCE_GROUP = "produce"
VERIFY_GROUP = "verify"
THINK_GROUP = "think"

CAPABILITY_GROUP: dict[AgentCapability, str] = {
    AgentCapability.CODE_GENERATION: PRODUCE_GROUP,
    AgentCapability.CONTENT_WRITING: PRODUCE_GROUP,
    AgentCapability.TEST_RUNNER: VERIFY_GROUP,
    AgentCapability.SECURITY_SCAN: VERIFY_GROUP,
    AgentCapability.CODE_REVIEW: VERIFY_GROUP,
    AgentCapability.PLANNING: THINK_GROUP,
    AgentCapability.REFLECTION: THINK_GROUP,
    AgentCapability.ORCHESTRATION: THINK_GROUP,
}


def _fail(issues: list[str]) -> None:
    raise PlanGenerationError(issues)


def _as_name_list(value: Any, *, field: str, step: str) -> list[str]:
    """Normalize an optional list-of-strings step field."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _fail([f"Step {step!r}: field {field!r} must be a list of strings."])
    items = []
    for item in value:
        cleaned = item.strip()
        if not cleaned:
            _fail([f"Step {step!r}: field {field!r} contains a blank entry."])
        items.append(cleaned)
    if len(items) > _MAX_LIST_ITEMS:
        _fail([f"Step {step!r}: field {field!r} has more than {_MAX_LIST_ITEMS} entries."])
    return items


def parse_step_drafts(raw_steps: Any) -> tuple[StepDraft, ...]:
    """Parse a planner's ``steps`` payload into validated step drafts.

    Raises :class:`PlanGenerationError` on any schema violation: the
    payload must be a list of dicts and every step must carry a name, a
    non-empty description and at least one capability drawn from the
    ``AgentCapability`` enum.
    """
    if not isinstance(raw_steps, list) or not raw_steps:
        _fail(["Planner output must contain a non-empty 'steps' list."])
    if len(raw_steps) > _MAX_STEPS:
        _fail([f"Plan has {len(raw_steps)} steps (>{_MAX_STEPS}); split or merge work."])

    drafts: list[StepDraft] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            _fail([f"Step #{index}: each step must be an object."])
        name = str(raw.get("name", "")).strip()
        if not name:
            _fail([f"Step #{index}: 'name' is required and cannot be blank."])
        if len(name) > _MAX_STEP_NAME:
            _fail([f"Step {name!r}: 'name' exceeds {_MAX_STEP_NAME} characters."])
        if name in seen:
            _fail([f"Duplicate step name {name!r}; step names must be unique."])
        seen.add(name)

        description = str(raw.get("description", "")).strip()
        if not description:
            _fail([f"Step {name!r}: 'description' must be a self-contained goal."])
        if len(description) > _MAX_STEP_DESCRIPTION:
            _fail([f"Step {name!r}: 'description' exceeds {_MAX_STEP_DESCRIPTION} characters."])

        raw_capabilities = raw.get("required_capabilities")
        if raw_capabilities is None:
            raw_capabilities = []
        if not isinstance(raw_capabilities, list) or not raw_capabilities:
            _fail([f"Step {name!r}: 'required_capabilities' must list at least one capability."])
        capabilities: list[AgentCapability] = []
        for item in raw_capabilities:
            if not isinstance(item, str):
                _fail([f"Step {name!r}: capability {item!r} must be a string."])
            try:
                capability = AgentCapability(item.strip().lower())
            except ValueError:
                valid = sorted(c.value for c in AgentCapability)
                _fail(
                    [
                        f"Step {name!r}: unknown capability {item.strip()!r}. "
                        f"Valid capabilities: {valid}."
                    ]
                )
            if capability not in capabilities:
                capabilities.append(capability)

        depends_on = _as_name_list(raw.get("depends_on"), field="depends_on", step=name)
        expected_outputs = _as_name_list(raw.get("expected_outputs"), field="expected_outputs", step=name)

        drafts.append(
            StepDraft(
                name=name,
                description=description,
                required_capabilities=tuple(capabilities),
                depends_on=tuple(depends_on),
                expected_outputs=tuple(expected_outputs),
            )
        )
    return tuple(drafts)


def validate_step_dag(drafts: tuple[StepDraft, ...]) -> None:
    """Check the name-based step graph. Raises :class:`PlanGenerationError`.

    Checks (mirrors ``plan_validator``): every ``depends_on`` reference
    resolves to a known step, and the graph is acyclic (Kahn's
    algorithm, same pattern as ``langflow.adlc.plan_validator``).
    Capability non-emptiness is already enforced by the parser and by
    the ``PlanStep`` model itself.
    """
    names = {draft.name for draft in drafts}
    for draft in drafts:
        for dependency in draft.depends_on:
            if dependency not in names:
                _fail(
                    [
                        f"Step {draft.name!r} depends on unknown step {dependency!r}. "
                        f"Known steps: {sorted(names)}."
                    ]
                )

    # Kahn's algorithm over dep -> dependents edges.
    in_degree = {draft.name: 0 for draft in drafts}
    forward: dict[str, list[str]] = defaultdict(list)
    for draft in drafts:
        for dependency in draft.depends_on:
            forward[dependency].append(draft.name)
            in_degree[draft.name] += 1

    queue: deque[str] = deque(name for name, degree in in_degree.items() if degree == 0)
    visited = 0
    while queue:
        name = queue.popleft()
        visited += 1
        for dependent in forward[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if visited != len(in_degree):
        remaining = sorted(name for name, degree in in_degree.items() if degree > 0)
        _fail([f"Plan contains a dependency cycle involving steps: {remaining}."])


def _description_tokens(text: str) -> set[str]:
    """Lowercased significant words of a step description."""
    tokens = re.split(r"[^a-z0-9àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]+", text.lower())
    return {token for token in tokens if len(token) >= _MIN_MEANINGFUL_TOKEN} - _STOPWORD_TOKENS


def _steps_look_independent(left: StepDraft, right: StepDraft) -> bool:
    """Heuristic: two consecutive steps whose descriptions share no
    significant vocabulary probably describe unrelated deliverables."""
    overlap = _description_tokens(left.description) & _description_tokens(right.description)
    mentions_output = any(token in _description_tokens(right.description) for token in _description_tokens(left.name))
    return not overlap and not mentions_output


def plan_quality_issues(drafts: tuple[StepDraft, ...]) -> tuple[str, ...]:
    """Return decomposition-rule violations that warrant regeneration.

    These are signals, not verdicts: the caller feeds them back to the
    planner for a new attempt. Returned strings are human-readable so
    they can double as the regeneration critique.
    """
    issues: list[str] = []

    for draft in drafts:
        groups = sorted({CAPABILITY_GROUP[capability] for capability in draft.required_capabilities})
        if len(groups) > 1:
            capability_values = ", ".join(sorted(capability.value for capability in draft.required_capabilities))
            issues.append(
                f"Step {draft.name!r} mixes capability groups {groups} "
                f"({capability_values}); split it into separate steps, one per "
                "capability group, so the router can assign different executors."
            )

    if _is_single_serial_chain(drafts) and len(drafts) >= _MIN_CHAIN_LENGTH_FOR_LINT:
        suspicious_pairs = sum(
            1
            for previous, current in zip(drafts, drafts[1:])
            if _steps_look_independent(previous, current)
        )
        if suspicious_pairs >= 2:
            issues.append(
                "The plan is one straight chain (every step depends only on the "
                "previous one) while several consecutive steps describe "
                "independent deliverables; declare independent work as separate "
                "steps without depends_on."
            )

    return tuple(issues)


def capability_value_list(draft: StepDraft) -> str:
    return ", ".join(sorted(capability.value for capability in draft.required_capabilities))


def _is_single_serial_chain(drafts: tuple[StepDraft, ...]) -> bool:
    """True when every step after the first depends only on its immediate
    predecessor (a single path with no branching and no extra roots)."""
    if len(drafts) < 2:
        return False
    if drafts[0].depends_on:
        return False
    for previous, current in zip(drafts, drafts[1:]):
        if current.depends_on != (previous.name,):
            return False
    return True


def build_plan_steps(drafts: tuple[StepDraft, ...]) -> tuple[PlanStep, ...]:
    """Materialize validated drafts into :class:`PlanStep` models.

    ``depends_on`` names are resolved to the generated step IDs, so the
    plan handed to the control plane is a real UUID DAG.
    """
    ids = {draft.name: uuid4() for draft in drafts}
    return tuple(
        PlanStep(
            step_id=ids[draft.name],
            name=draft.name,
            description=draft.description,
            required_capabilities=frozenset(draft.required_capabilities),
            depends_on=tuple(ids[dependency] for dependency in draft.depends_on),
            expected_outputs=tuple(draft.expected_outputs),
        )
        for draft in drafts
    )


__all__ = [
    "CAPABILITY_GROUP",
    "PlanGenerationError",
    "StepDraft",
    "build_plan_steps",
    "parse_step_drafts",
    "plan_quality_issues",
    "validate_step_dag",
]

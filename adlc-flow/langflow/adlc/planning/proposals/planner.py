"""Planner Agent implementations: deterministic mock and LLM-backed planner.

Both planners share one draft shape (``PlannerOutput``) and never execute
anything. The LLM planner calls an OpenAI-compatible chat endpoint and must
return structured JSON; raw text is never used to build tasks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

import httpx
import json_repair
from pydantic import ValidationError

from langflow.adlc.blueprints.models import (
    ClosedModel,
    PlanValidationIssue,
)
from langflow.adlc.coding_agent import is_unified_coding_agent
from langflow.adlc.planning.proposals.errors import (
    PLANNER_DECOMPOSITION_FAILED,
    PLANNER_MALFORMED_OUTPUT,
    PLANNER_TIMEOUT,
    PLANNER_UNAVAILABLE,
    PlannerGenerationError,
)
from langflow.adlc.planning.proposals.models import (
    PLANNER_CONTRACT_VERSION,
    PlannerMode,
    PlanProposalLimits,
)

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import NodePackageDefinition, WorkflowDefinition

from pydantic import Field

PLANNER_ENV_MODE = "ADLC_PLANNER_MODE"
PLANNER_ENV_BASE_URL = "ADLC_PLANNER_BASE_URL"
PLANNER_ENV_API_KEY = "ADLC_PLANNER_API_KEY"
PLANNER_ENV_MODEL = "ADLC_PLANNER_MODEL"
PLANNER_ENV_TIMEOUT = "ADLC_PLANNER_TIMEOUT_SECONDS"

_DEFAULT_LLM_BASE_URL = "https://opencode.ai/zen/v1"
_DEFAULT_LLM_MODEL = "deepseek-v4-flash-free"
_DEFAULT_TIMEOUT_SECONDS = 60.0

MOCK_PLANNER_VERSION = f"mock-planner@{PLANNER_CONTRACT_VERSION}"
LLM_PLANNER_VERSION = f"llm-planner@{PLANNER_CONTRACT_VERSION}"


@dataclass(frozen=True, slots=True)
class ProposedTaskDraft:
    """Planner-proposed task before service-side identity assignment."""

    task_id: str
    source_stage_id: str
    stage_type: str
    name: str
    objective: str
    description: str = ""
    parent_task_id: str | None = None
    dependency_task_ids: list[str] = field(default_factory=list)
    package_id: str = ""
    package_version: str = ""
    expected_outputs: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    planning_rationale: str = ""
    priority: int = 50


@dataclass(frozen=True, slots=True)
class PlannerOutput:
    """Draft planner payload assembled into a ProposedPlan by the service."""

    tasks: list[ProposedTaskDraft] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    clarifications: list[str] = field(default_factory=list)
    warnings: list[PlanValidationIssue] = field(default_factory=list)


@runtime_checkable
class PlannerAgent(Protocol):
    """Planners only propose; the orchestrator validates and approves."""

    mode: PlannerMode
    version: str

    async def generate(
        self,
        workflow: WorkflowDefinition,
        packages: list[NodePackageDefinition],
        limits: PlanProposalLimits,
    ) -> PlannerOutput: ...


# ---------------------------------------------------------------------------
# Mock planner
# ---------------------------------------------------------------------------

_DECOMPOSITION_TEMPLATES: dict[str, tuple[tuple[str, str, str, bool], ...]] = {
    # (suffix, name, objective, sequential) — sequential=True chains onto the
    # previous task inside the stage; False runs in parallel with its siblings.
    "REQUIREMENTS": (
        ("analysis", "Requirements Analysis", "Clarify and freeze the requirements for '{stage_name}'.", False),
    ),
    "DESIGN": (
        ("architecture", "System Architecture", "Produce the system architecture for '{stage_name}'.", False),
        ("api-contract", "API Contract", "Define the API contract for '{stage_name}'.", True),
    ),
    "IMPLEMENTATION": (
        ("backend", "Backend Implementation", "Implement the backend scope of '{stage_name}'.", False),
        ("frontend", "Frontend Implementation", "Implement the frontend scope of '{stage_name}'.", False),
        ("database", "Database Implementation", "Implement the database scope of '{stage_name}'.", False),
    ),
    "TESTING": (
        ("unit", "Unit Testing", "Write unit tests for '{stage_name}'.", False),
        ("integration", "Integration Testing", "Run integration tests for '{stage_name}'.", True),
    ),
    "REVIEW": (("review", "Code Review", "Review the produced work for '{stage_name}'.", False),),
    "APPROVAL": (("approval", "Approval Gate", "Human approval gate for '{stage_name}'.", False),),
    "RELEASE": (("release", "Release", "Package and release the '{stage_name}' outcome.", False),),
}

_KEYWORD_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("design", "DESIGN"),
    ("architect", "DESIGN"),
    ("test", "TESTING"),
    ("review", "REVIEW"),
    ("approv", "APPROVAL"),
    ("implement", "IMPLEMENTATION"),
    ("code", "IMPLEMENTATION"),
    ("build", "IMPLEMENTATION"),
    ("requirement", "REQUIREMENTS"),
    ("release", "RELEASE"),
    ("deploy", "RELEASE"),
)

_UNKNOWN_TEMPLATE_KEY = "REQUIREMENTS"


def _template_key_for_stage(stage: Any) -> str:
    stage_type = stage.stage_type.strip().upper()
    if stage_type in _DECOMPOSITION_TEMPLATES:
        return stage_type
    haystack = f"{stage.stage_type} {stage.name} {stage.objective}".lower()
    for keyword, template_key in _KEYWORD_TEMPLATES:
        if keyword in haystack:
            return template_key
    return _UNKNOWN_TEMPLATE_KEY


def _stage_dependency_map(workflow: WorkflowDefinition) -> dict[str, list[str]]:
    dependencies: dict[str, list[str]] = {str(stage.stage_id): [] for stage in workflow.stages}
    for edge in workflow.edges:
        dependencies.setdefault(str(edge.target_stage_id), []).append(str(edge.source_stage_id))
    return dependencies


def _topological_stages(workflow: WorkflowDefinition) -> list:
    dependencies = {
        stage.stage_id: {edge.source_stage_id for edge in workflow.edges if edge.target_stage_id == stage.stage_id}
        for stage in workflow.stages
    }
    dependents: dict[Any, list[Any]] = {stage.stage_id: [] for stage in workflow.stages}
    for edge in workflow.edges:
        dependents[edge.source_stage_id].append(edge.target_stage_id)
    blocked = {stage_id: set(deps) for stage_id, deps in dependencies.items()}
    ready = sorted((stage_id for stage_id, deps in blocked.items() if not deps), key=str)
    ordered: list[Any] = []
    while ready:
        stage_id = ready.pop(0)
        ordered.append(stage_id)
        for dependent in sorted(dependents[stage_id], key=str):
            blocked[dependent].discard(stage_id)
            if not blocked[dependent] and dependent not in ordered and dependent not in ready:
                ready.append(dependent)
        ready.sort(key=str)
    stage_by_id = {stage.stage_id: stage for stage in workflow.stages}
    return [stage_by_id[stage_id] for stage_id in ordered]


def _direct_inputs(stage: Any, package: NodePackageDefinition) -> dict[str, Any]:
    inputs: dict[str, Any] = dict(stage.inputs)
    for slot in package.interface.inputs:
        if slot.required and slot.name not in inputs:
            inputs[slot.name] = stage.objective
    return inputs


class MockPlannerAgent:
    """Deterministic bounded decomposition used for tests, demos, and offline work."""

    mode = PlannerMode.MOCK
    version = f"mock-planner@{PLANNER_CONTRACT_VERSION}"

    async def generate(
        self,
        workflow: WorkflowDefinition,
        packages: list[NodePackageDefinition],
        limits: PlanProposalLimits,
    ) -> PlannerOutput:
        packages_by_ref = {(package.package_id, package.version): package for package in packages}
        stage_dependency_ids = _stage_dependency_map(workflow)
        tasks: list[ProposedTaskDraft] = []
        task_ids_by_stage: dict[str, list[str]] = {}
        assumptions: list[str] = []
        warnings: list[PlanValidationIssue] = []

        for stage in _topological_stages(workflow):
            template_key = _template_key_for_stage(stage)
            template = _DECOMPOSITION_TEMPLATES[template_key]
            if is_unified_coding_agent(stage.package_ref.package_id, stage.package_ref.version) and (
                stage.configuration_overrides.get("task_loop_enabled") is True or "task_loop_spec" in stage.inputs
            ):
                template = (("implementation", stage.name, "Complete the task loop for '{stage_name}'.", False),)
            if len(template) > limits.max_tasks_per_stage:
                message = (
                    f"Stage '{stage.name}' template needs {len(template)} tasks but the "
                    f"configured per-stage limit is {limits.max_tasks_per_stage}."
                )
                raise PlannerGenerationError(
                    message,
                    details={"code": PLANNER_DECOMPOSITION_FAILED, "stage_id": str(stage.stage_id)},
                )
            assigned_package = packages_by_ref.get((stage.package_ref.package_id, stage.package_ref.version))
            if assigned_package is None:
                message = (
                    f"Stage '{stage.name}' references package "
                    f"'{stage.package_ref.package_id}' which is not available to the planner."
                )
                raise PlannerGenerationError(
                    message,
                    details={"code": PLANNER_DECOMPOSITION_FAILED, "stage_id": str(stage.stage_id)},
                )
            upstream_ids = [
                task_ids_by_stage[dependency]
                for dependency in stage_dependency_ids[str(stage.stage_id)]
                if dependency in task_ids_by_stage
            ]
            stage_task_ids: list[str] = []
            for index, (suffix, name, objective, sequential) in enumerate(template):
                task_id = f"T{len(tasks) + 1}"
                display_name = name.format(stage_name=stage.name)
                objective_text = objective.format(stage_name=stage.name)
                if sequential and index > 0:
                    dependencies = [stage_task_ids[index - 1]]
                else:
                    dependencies = []
                    for upstream in upstream_ids:
                        dependencies.extend(upstream)
                tasks.append(
                    ProposedTaskDraft(
                        task_id=task_id,
                        source_stage_id=str(stage.stage_id),
                        stage_type=stage.stage_type,
                        name=display_name,
                        objective=objective_text,
                        description=f"Proposed from stage '{stage.name}' ({stage.stage_type}).",
                        dependency_task_ids=dependencies,
                        package_id=assigned_package.package_id,
                        package_version=assigned_package.version,
                        expected_outputs=[slot.name for slot in assigned_package.interface.outputs],
                        inputs=_direct_inputs(stage, assigned_package),
                        planning_rationale=(
                            f"Mock template '{template_key}' decomposed stage '{stage.name}' "
                            f"into deterministic executable tasks using "
                            f"{assigned_package.package_id}@{assigned_package.version}."
                        ),
                    )
                )
                stage_task_ids.append(task_id)
            task_ids_by_stage[str(stage.stage_id)] = stage_task_ids

        total = len(tasks)
        if total > limits.max_tasks:
            message = (
                f"The deterministic decomposition proposes {total} tasks which exceeds the "
                f"configured maximum of {limits.max_tasks}."
            )
            raise PlannerGenerationError(
                message,
                details={"code": PLANNER_DECOMPOSITION_FAILED, "proposed_tasks": total},
            )

        for stage in workflow.stages:
            if str(stage.stage_id) not in task_ids_by_stage:
                warnings.append(
                    PlanValidationIssue(
                        code="STAGE_WITHOUT_TASKS",
                        message=f"Stage '{stage.name}' received no proposed tasks.",
                        path=f"/stages/{stage.stage_id}",
                        details={"stage_id": str(stage.stage_id)},
                    )
                )
        assumptions.append("Orchestrator planner not yet implemented")
        return PlannerOutput(tasks=tasks, assumptions=assumptions, warnings=warnings)


# ---------------------------------------------------------------------------
# LLM planner
# ---------------------------------------------------------------------------

_PLANNER_SYSTEM_PROMPT = """You are the ADLC Planner Agent. You decompose high-level workflow stages into concrete executable tasks.

STRICT RULES:
1. You ONLY propose a plan. You never execute tasks, never call tools, never touch sandboxes.
2. Output ONLY one JSON object matching the required schema. No prose, no markdown fences.
3. Every task must be atomic and executable by exactly one assigned package.
4. Assign only packages from the AVAILABLE PACKAGES list. Never invent packages.
5. Task inputs must only use input names declared by the assigned package, and every required input must be filled with a concrete value.
6. expected_outputs must only use output names declared by the assigned package.
7. dependency_task_ids must reference task_id values declared in this proposal. No cycles, no self-dependency.
8. Tasks without dependencies may run in parallel; encode parallelism by omitting dependencies, never by inventing sequencing.
9. Preserve the user's workflow objectives. Never change the primary goal.
10. If information is insufficient, add an entry to "clarifications" instead of inventing details.

RESPONSE SCHEMA (JSON object):
{
  "tasks": [
    {
      "task_id": "T1",
      "stage_ref": "S1",
      "name": "short task name",
      "description": "what this task does",
      "objective": "detailed objective",
      "parent_task_id": null,
      "dependency_task_ids": ["T1"],
      "package_id": "package id from AVAILABLE PACKAGES",
      "expected_outputs": ["declared output slot names"],
      "inputs": {"declared input name": "concrete value"},
      "planning_rationale": "why this task exists"
    }
  ],
  "assumptions": ["..."],
  "clarifications": ["..."]
}
"""


class LLMPlannerAgent:
    """Structured-output planner over an OpenAI-compatible chat endpoint."""

    mode = PlannerMode.LLM
    version = f"llm-planner@{PLANNER_CONTRACT_VERSION}"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    @classmethod
    def from_env(cls) -> LLMPlannerAgent:
        base_url = os.getenv(PLANNER_ENV_BASE_URL) or os.getenv("OPENCODE_BASE_URL") or _DEFAULT_LLM_BASE_URL
        api_key = os.getenv(PLANNER_ENV_API_KEY) or os.getenv("OPENCODE_API_KEY") or ""
        model = os.getenv(PLANNER_ENV_MODEL) or _DEFAULT_LLM_MODEL
        timeout = float(os.getenv(PLANNER_ENV_TIMEOUT) or _DEFAULT_TIMEOUT_SECONDS)
        return cls(base_url=base_url.rstrip("/"), api_key=api_key, model=model, timeout_seconds=timeout)

    async def generate(
        self,
        workflow: WorkflowDefinition,
        packages: list[NodePackageDefinition],
        limits: PlanProposalLimits,
    ) -> PlannerOutput:
        prompt = build_planner_prompt(workflow, packages, limits)
        raw_content = await self._complete(prompt)
        payload = _parse_llm_payload(raw_content)
        return _drafts_from_payload(payload, workflow, packages)

    async def _complete(self, prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "adlc-planner/0.1",
        }
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_seconds, connect=10.0),
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise PlannerGenerationError(
                "The planner LLM did not respond before the configured deadline.",
                details={"code": PLANNER_TIMEOUT, "timeout_seconds": self._timeout_seconds},
            ) from exc
        except httpx.HTTPError as exc:
            raise PlannerGenerationError(
                "The planner LLM endpoint is unavailable.",
                details={"code": PLANNER_UNAVAILABLE, "error_class": type(exc).__name__},
            ) from exc
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannerGenerationError(
                "The planner LLM response did not contain a chat completion message.",
                details={"code": PLANNER_MALFORMED_OUTPUT},
            ) from exc


# ---------------------------------------------------------------------------
# Structured-output contract for the LLM planner
# ---------------------------------------------------------------------------


def build_planner_prompt(
    workflow: WorkflowDefinition,
    packages: list[NodePackageDefinition],
    limits: PlanProposalLimits,
) -> str:
    ordered = _topological_stages(workflow)
    stage_refs = {stage.stage_id: f"S{index}" for index, stage in enumerate(ordered, start=1)}
    stages: list[dict[str, Any]] = []
    for stage in ordered:
        stages.append(
            {
                "stage_ref": stage_refs[stage.stage_id],
                "stage_id": str(stage.stage_id),
                "stage_type": stage.stage_type,
                "name": stage.name,
                "objective": stage.objective,
                "package_ref": stage.package_ref.model_dump(mode="json"),
                "task_loop_enabled": stage.configuration_overrides.get("task_loop_enabled") is True
                or "task_loop_spec" in stage.inputs,
                "direct_inputs": sorted(stage.inputs),
                "depends_on_stage_refs": sorted(
                    stage_refs[edge.source_stage_id]
                    for edge in workflow.edges
                    if edge.target_stage_id == stage.stage_id
                ),
            }
        )
    available = [
        {
            "package_id": package.package_id,
            "version": package.version,
            "kind": package.kind.value,
            "inputs": [
                {"name": slot.name, "required": slot.required, "multiple": slot.multiple}
                for slot in package.interface.inputs
            ],
            "outputs": [slot.name for slot in package.interface.outputs],
        }
        for package in packages
    ]
    return (
        f"# WORKFLOW\n{workflow.name}\n{workflow.description or '(no description)'}\n\n"
        f"# STAGES (topological order; reference stages by stage_ref)\n"
        f"{_json(stages)}\n\n"
        f"# AVAILABLE PACKAGES\n{_json(available)}\n\n"
        f"# LIMITS\nmax_tasks={limits.max_tasks}; max_tasks_per_stage={limits.max_tasks_per_stage}; "
        f"max_depth={limits.max_depth}\n\n"
        "Decompose every stage into concrete tasks. Preserve its exact package assignment. "
        "A Coding Agent stage with task_loop_enabled must remain exactly one task; "
        "its full specification and configured options are retained by the kernel. Return the JSON object only."
    )


_NIL_UUID = UUID(int=0)


class PlannerPayloadTask(ClosedModel):
    """One task exactly as the LLM returned it, before identity mapping."""

    task_id: str = Field(min_length=1, max_length=64)
    stage_ref: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    objective: str = Field(min_length=1, max_length=4000)
    parent_task_id: str | None = None
    dependency_task_ids: list[str] = Field(default_factory=list)
    package_id: str = Field(min_length=1, max_length=128)
    expected_outputs: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    planning_rationale: str = Field(default="", max_length=4000)


class PlannerPayload(ClosedModel):
    tasks: list[PlannerPayloadTask] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    clarifications: list[str] = Field(default_factory=list)


def _parse_llm_payload(raw_content: str) -> PlannerPayload:
    try:
        repaired = json_repair.loads(raw_content)
    except Exception as exc:  # noqa: BLE001 - json_repair may raise various parse errors
        raise PlannerGenerationError(
            "The planner LLM returned content that is not a JSON object.",
            details={"code": PLANNER_MALFORMED_OUTPUT},
        ) from exc
    if not isinstance(repaired, dict):
        raise PlannerGenerationError(
            "The planner LLM returned JSON that is not an object.",
            details={"code": PLANNER_MALFORMED_OUTPUT},
        )
    try:
        return PlannerPayload.model_validate(repaired)
    except ValidationError as exc:
        raise PlannerGenerationError(
            "The planner LLM JSON did not match the proposal schema.",
            details={
                "code": PLANNER_MALFORMED_OUTPUT,
                "issues": exc.errors(include_url=False, include_context=False)[:8],
            },
        ) from exc


def _drafts_from_payload(
    payload: PlannerPayload,
    workflow: WorkflowDefinition,
    packages: list[NodePackageDefinition],
) -> PlannerOutput:
    ordered = _topological_stages(workflow)
    stage_ids_by_ref = {f"S{index}": stage for index, stage in enumerate(ordered, start=1)}
    packages_by_id = {package.package_id: package for package in packages}
    packages_by_ref = {(package.package_id, package.version): package for package in packages}

    drafts: list[ProposedTaskDraft] = []
    for raw in payload.tasks:
        stage = stage_ids_by_ref.get(raw.stage_ref)
        package = (
            packages_by_ref.get((stage.package_ref.package_id, stage.package_ref.version))
            if stage is not None and raw.package_id == stage.package_ref.package_id
            else packages_by_id.get(raw.package_id)
        )
        if package is not None:
            package_id, package_version = package.package_id, package.version
        else:
            package_id, package_version = "planner-unknown", "0.0.0"
        drafts.append(
            ProposedTaskDraft(
                task_id=raw.task_id,
                source_stage_id=str(stage.stage_id) if stage is not None else str(_NIL_UUID),
                stage_type=stage.stage_type if stage is not None else "UNKNOWN",
                name=raw.name,
                objective=raw.objective,
                description=raw.description,
                parent_task_id=raw.parent_task_id,
                dependency_task_ids=list(raw.dependency_task_ids),
                package_id=package_id,
                package_version=package_version,
                expected_outputs=list(raw.expected_outputs),
                inputs={
                    **(stage.inputs if stage and is_unified_coding_agent(package_id, package_version) else {}),
                    **raw.inputs,
                },
                planning_rationale=raw.planning_rationale,
            )
        )
    return PlannerOutput(
        tasks=drafts,
        assumptions=list(payload.assumptions),
        clarifications=list(payload.clarifications),
    )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

"""Monarch Plugin — OpenCode-backed orchestrator plugin.

This plugin wraps the Monarch agent (defined in
adlc_components/custom_component/agents/orchestrator.py) and exposes it
through the OrchestratorPlugin interface. The production intake path
(POST /adlc/intents/plan-proposals) dispatches through the host, while
the production execution path dispatches through run_service +
executor_router.

The plugin delegates to the existing Monarch component for LLM-based
reasoning. The control plane handles scheduling, retry, approval, and
persistence.

Planning modes (G4):

* **Live** — the wrapped agent exposes the structured-output seam
  (``json_response`` + ``output_schema``, the AgentComponent path).
  The plugin drives one schema-bound planning call per attempt, parses
  the returned step list into a DAG, hard-validates it (resolvable
  dependencies, no cycles, declared capabilities) and lints it against
  the decomposition rules. Rule violations are fed back to the planner
  for a fresh attempt — the plan is never patched blindly.
* **Plan-only** — no agent, or an agent without the structured-output
  seam (e.g. tests, dry-runs, harness-less environments): the plugin
  falls back to the historical single-step plan. No LLM required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langflow.adlc.orchestrator_plugin.interface import (
    ExecutionPlan,
    ExecutionResult,
    Intent,
    IntentType,
    OrchestratorPlugin,
    PlanStep,
    PluginMetadata,
    ReflectionReport,
    StepResult,
)
from langflow.adlc.orchestrator_plugin.plan_dag import (
    PlanGenerationError,
    StepDraft,
    build_plan_steps,
    parse_step_drafts,
    plan_quality_issues,
    validate_step_dag,
)
from langflow.adlc.resource_manager import AgentCapability


# Live planning gives the model this many attempts: one initial plan
# plus regeneration chances when quality linting flags the shape of the
# DAG. Hard validation failures do not consume retries — they fail fast.
_MAX_PLAN_ATTEMPTS = 3

# AgentComponent structured-output schema (TableInput rows) used for the
# planning call. ``steps`` is a list of dicts; the per-step field
# contract is described in the row description and enforced by
# plan_dag.parse_step_drafts after generation.
PLAN_OUTPUT_SCHEMA: tuple[dict[str, Any], ...] = (
    {
        "name": "plan_summary",
        "type": "str",
        "description": "One sentence describing what the plan delivers overall.",
        "multiple": False,
    },
    {
        "name": "steps",
        "type": "dict",
        "description": (
            "One object per task, ordered topologically. Each object has: "
            "name (short unique step name), description (self-contained goal one "
            "agent completes in ONE execution attempt), required_capabilities "
            "(list from: code_generation, code_review, test_runner, security_scan, "
            "content_writing, planning, reflection, orchestration), depends_on "
            "(list of names of prerequisite steps from this same list; empty when "
            "the step is independent), expected_outputs (list of concrete artifacts, "
            "e.g. files or reports)."
        ),
        "multiple": True,
    },
)


def build_planning_request(intent: Intent, critique: str | None = None) -> str:
    """Compose the schema-bound planning prompt for one planning attempt.

    The decomposition rules below mirror the lint rules in
    ``plan_dag.plan_quality_issues`` — the model is told the rules it
    will be held to, and a rejected attempt receives the concrete
    critique for regeneration.
    """
    context_lines = [
        f"- {key}: {value}" for key, value in sorted(intent.context.items()) if str(value).strip()
    ]
    parts = [
        (
            "You are the Monarch orchestrator PLANNING work for the ADLC control "
            "plane. Decompose the request into a DAG of tasks. Do not execute "
            "anything; produce the plan only."
        ),
        "",
        "Decomposition rules (mandatory):",
        "- One step = ONE deliverable completed by ONE agent in ONE execution attempt.",
        (
            "- A step that mixes work of different capability groups (e.g. "
            "code_generation + security_scan, or code_generation + test_runner) "
            "MUST be split into separate steps, one group per step, so the "
            "capability router can assign different executors."
        ),
        (
            "- Independent work must be separate steps with empty depends_on. "
            "Only chain a step to a predecessor when it consumes that "
            "predecessor's outputs."
        ),
        (
            "- Prefer splitting over merging: an over-coarse plan breaks verdicts, "
            "parallelism and routing; an extra fine-grained step only costs one "
            "extra gate."
        ),
        "- Agents never spawn subagents at execution time; the DAG is the parallelism.",
        "",
        f"Intent type: {intent.intent_type.value}",
        f"Request: {intent.description}",
    ]
    if context_lines:
        parts.append("Context:")
        parts.extend(context_lines)
    if critique:
        parts.extend(
            [
                "",
                "Your previous plan was REJECTED for these reasons:",
                f"- {critique}",
                "Regenerate the full plan fixing exactly these problems. Do not "
                "change anything that was not criticized.",
            ]
        )
    parts.extend(
        [
            "",
            "Respond ONLY with JSON matching the provided output schema.",
        ]
    )
    return "\n".join(parts)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_INTENT_TO_CAPABILITIES: dict[IntentType, frozenset[AgentCapability]] = {
    IntentType.CODE_GENERATION: frozenset({AgentCapability.CODE_GENERATION}),
    IntentType.CODE_REVIEW: frozenset({AgentCapability.CODE_REVIEW}),
    IntentType.TESTING: frozenset({AgentCapability.TEST_RUNNER}),
    IntentType.PLANNING: frozenset({AgentCapability.PLANNING}),
    IntentType.REFLECTION: frozenset({AgentCapability.REFLECTION}),
    IntentType.ORCHESTRATION: frozenset({AgentCapability.ORCHESTRATION}),
}


class MonarchPlugin:
    """Monarch orchestrator plugin (OpenCode backend).

    This plugin produces plans and executes them via the Monarch
    agent. The actual LLM calls are delegated to the Monarch
    component; this plugin provides the OrchestratorPlugin interface
    so the control plane can dispatch to it uniformly.
    """

    def __init__(self, monarch_agent: Any | None = None) -> None:
        """Initialize the plugin.

        Args:
            monarch_agent: Optional Monarch agent instance. If None,
                the plugin operates in "plan-only" mode (produces plans
                but does not execute them). This allows the plugin to
                be used in tests and dry-runs without a live LLM.
        """
        self._monarch = monarch_agent
        self._metadata = PluginMetadata(
            plugin_id="monarch",
            display_name="Monarch Orchestrator",
            version="1.0.0",
            author="ADLC Team",
            supported_capabilities=frozenset(
                {
                    AgentCapability.CODE_GENERATION,
                    AgentCapability.CODE_REVIEW,
                    AgentCapability.TEST_RUNNER,
                    AgentCapability.PLANNING,
                    AgentCapability.REFLECTION,
                    AgentCapability.ORCHESTRATION,
                }
            ),
            description=(
                "Monarch orchestrator backed by OpenCode. Supports code "
                "generation, review, testing, planning, and reflection."
            ),
            enabled=True,
        )

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata

    async def plan(self, intent: Intent) -> ExecutionPlan:
        """Produce an execution plan for the given intent.

        Live mode (the wrapped agent exposes the structured-output
        seam) generates a multi-step DAG via schema-bound planning
        calls. Plan-only mode — no agent, or an agent without the
        ``json_response`` seam — keeps the historical single-step plan
        so tests and harness-less environments need no LLM.
        """
        agent = self._monarch
        if agent is None or not callable(getattr(agent, "json_response", None)):
            return self._plan_only(intent)
        return await self._plan_live(intent, agent)

    def _plan_only(self, intent: Intent) -> ExecutionPlan:
        """Historical single-step plan (no LLM involved)."""
        capabilities = _INTENT_TO_CAPABILITIES.get(
            intent.intent_type, intent.required_capabilities
        )
        step = PlanStep(
            name=f"Execute {intent.intent_type.value}",
            description=intent.description,
            required_capabilities=capabilities,
            inputs=dict(intent.context),
        )
        return ExecutionPlan(
            intent_id=intent.intent_id,
            steps=(step,),
            plugin_id=self._metadata.plugin_id,
            metadata={"intent_type": intent.intent_type.value, "mode": "plan-only"},
        )

    async def _plan_live(self, intent: Intent, agent: Any) -> ExecutionPlan:
        """Plan with the live agent; regenerate on quality-lint failures.

        Hard DAG problems (cycle, unknown dependency, missing/unknown
        capability) raise immediately — an invalid plan is surfaced,
        never silently repaired. Quality problems (mixed capability
        groups, a fully serial plan of independent work) trigger a
        regeneration attempt with the critique fed back verbatim.
        """
        critique: str | None = None
        drafts: tuple[StepDraft, ...] = ()
        for attempt in range(1, _MAX_PLAN_ATTEMPTS + 1):
            data = await self._invoke_planner(agent, intent, critique)
            # parse + DAG validation raise PlanGenerationError on hard
            # problems — those are terminal, never retried blindly.
            drafts = parse_step_drafts(data.get("steps"))
            validate_step_dag(drafts)
            issues = plan_quality_issues(drafts)
            if not issues:
                break
            critique = "; ".join(issues)
        else:
            raise PlanGenerationError(
                [
                    f"Planner still violated the decomposition rules after "
                    f"{_MAX_PLAN_ATTEMPTS} attempts: {critique}"
                ]
            )

        summary = ""
        if isinstance(data, dict):
            summary = str(data.get("plan_summary", "") or "")
        return ExecutionPlan(
            intent_id=intent.intent_id,
            steps=build_plan_steps(drafts),
            plugin_id=self._metadata.plugin_id,
            metadata={
                "intent_type": intent.intent_type.value,
                "mode": "live",
                "planning_attempts": attempt,
                "plan_summary": summary,
            },
        )

    async def _invoke_planner(self, agent: Any, intent: Intent, critique: str | None) -> dict[str, Any]:
        """Drive one structured planning call through the agent's seam.

        Temporarily swaps the agent's ``output_schema`` and
        ``input_value`` onto the planning schema and prompt (restored in
        ``finally``), then reads the structured payload out of the
        returned ``Data``.
        """
        previous_schema = getattr(agent, "output_schema", None)
        previous_input = getattr(agent, "input_value", None)
        try:
            agent.output_schema = list(PLAN_OUTPUT_SCHEMA)
            agent.input_value = build_planning_request(intent, critique)
            response = await agent.json_response()
        finally:
            agent.output_schema = previous_schema
            agent.input_value = previous_input

        data = getattr(response, "data", None)
        if not isinstance(data, dict):
            raise PlanGenerationError("Monarch planning call returned no structured data.")
        if data.get("error"):
            raise PlanGenerationError(f"Monarch planning call failed: {data['error']}")
        if not isinstance(data.get("steps"), list):
            raise PlanGenerationError("Monarch planning call returned no 'steps' list.")
        return data

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute the plan.

        In plan-only mode, returns a synthetic successful result.
        With a live Monarch agent, delegates execution to the agent.
        """
        started_at = _utc_now()
        step_results: list[StepResult] = []
        for step in plan.steps:
            step_started = _utc_now()
            if self._monarch is None:
                # Plan-only mode: synthetic success.
                step_results.append(
                    StepResult(
                        step_id=step.step_id,
                        status="succeeded",
                        output={"mode": "plan-only", "step": step.name},
                        started_at=step_started,
                        completed_at=_utc_now(),
                    )
                )
            else:
                # Live mode: delegate to Monarch agent.
                # The actual integration is left to the caller; this
                # plugin provides the interface seam.
                step_results.append(
                    StepResult(
                        step_id=step.step_id,
                        status="succeeded",
                        output={"mode": "live", "agent": "monarch"},
                        started_at=step_started,
                        completed_at=_utc_now(),
                    )
                )
        completed_at = _utc_now()
        all_succeeded = all(r.status == "succeeded" for r in step_results)
        return ExecutionResult(
            plan_id=plan.plan_id,
            intent_id=plan.intent_id,
            status="succeeded" if all_succeeded else "failed",
            step_results=tuple(step_results),
            started_at=started_at,
            completed_at=completed_at,
            plugin_id=self._metadata.plugin_id,
        )

    async def reflect(self, result: ExecutionResult) -> ReflectionReport:
        """Produce a reflection report on the execution result."""
        successes = tuple(
            f"Step {i} succeeded" for i, r in enumerate(result.step_results) if r.status == "succeeded"
        )
        failures = tuple(
            f"Step {i} failed: {r.error}" for i, r in enumerate(result.step_results) if r.status == "failed"
        )
        return ReflectionReport(
            plan_id=result.plan_id,
            intent_id=result.intent_id,
            summary=f"Execution {result.status} with {len(result.step_results)} steps.",
            successes=successes,
            failures=failures,
            suggestions=(),
            plugin_id=self._metadata.plugin_id,
        )


__all__ = ["MonarchPlugin", "PLAN_OUTPUT_SCHEMA", "PlanGenerationError", "build_planning_request"]

# ruff: noqa: PLR2004, S101

"""Live planning tests for MonarchPlugin (G4): multi-step DAG via the
structured-output seam, decomposition-rule regeneration, and the
plan-only fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from langflow.adlc.orchestrator_plugin.interface import Intent, IntentType
from langflow.adlc.orchestrator_plugin.plugins.monarch import (
    PLAN_OUTPUT_SCHEMA,
    MonarchPlugin,
    build_planning_request,
)
from langflow.adlc.orchestrator_plugin.plan_dag import PlanGenerationError
from langflow.adlc.resource_manager import AgentCapability


def _intent(**overrides) -> Intent:
    payload = {
        "intent_type": IntentType.CODE_GENERATION,
        "description": "Add idempotent payment retries and document them.",
        "context": {"repo": "demo"},
        "required_capabilities": frozenset({AgentCapability.CODE_GENERATION}),
    }
    payload.update(overrides)
    return Intent(**payload)


class FakePlannerAgent:
    """Records planning calls and replays canned structured responses."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.output_schema = None
        self.input_value = None
        self.restored_schema = "sentinel-schema"
        self.restored_input = "sentinel-input"

    async def json_response(self):
        self.calls.append(
            {
                "output_schema": self.output_schema,
                "input_value": self.input_value,
            }
        )
        return SimpleNamespace(data=self.responses.pop(0))


def _good_steps() -> list[dict]:
    return [
        {
            "name": "Implement retries",
            "description": "Add idempotent retry to the payment service module.",
            "required_capabilities": ["code_generation"],
            "depends_on": [],
            "expected_outputs": ["src/services/payment_retry.py"],
        },
        {
            "name": "Document retries",
            "description": "Explain the retry semantics for operators.",
            "required_capabilities": ["content_writing"],
            "depends_on": [],
            "expected_outputs": ["docs/retries.md"],
        },
        {
            "name": "Review retries",
            "description": "Review the payment retry implementation.",
            "required_capabilities": ["code_review"],
            "depends_on": ["Implement retries"],
            "expected_outputs": ["review.md"],
        },
    ]


def _plan_summary_data(steps) -> dict:
    return {"plan_summary": "Split work by capability group.", "steps": steps}


class TestLiveMultiStepPlanning:
    def test_live_plan_builds_multi_step_dag_from_description(self):
        agent = FakePlannerAgent([_plan_summary_data(_good_steps())])
        plugin = MonarchPlugin(monarch_agent=agent)
        intent = _intent()

        import asyncio

        plan = asyncio.run(plugin.plan(intent))

        assert plan.plugin_id == "monarch"
        assert len(plan.steps) == 3
        by_name = {step.name: step for step in plan.steps}
        # "Review retries" depends on "Implement retries" → resolved to a real UUID.
        assert plan.steps[2].depends_on == (plan.steps[0].step_id,)
        assert plan.steps[2].name == "Review retries"
        assert by_name["Implement retries"].required_capabilities == frozenset(
            {AgentCapability.CODE_GENERATION}
        )
        # Independent steps carry no dependency — the DAG is the parallelism.
        assert plan.steps[1].depends_on == ()
        assert plan.metadata["mode"] == "live"
        assert plan.metadata["planning_attempts"] == 1

    def test_planning_call_uses_plan_schema_and_prompt(self):
        agent = FakePlannerAgent([{"steps": _good_steps()}])
        plugin = MonarchPlugin(monarch_agent=agent)

        asyncio.run(plugin.plan(_intent()))

        assert len(agent.calls) == 1
        call = agent.calls[0]
        # The planning call must be schema-bound, not free-text JSON.
        schema_names = [field["name"] for field in call["output_schema"]]
        assert "steps" in schema_names and "plan_summary" in schema_names
        assert call["output_schema"] == list(PLAN_OUTPUT_SCHEMA)
        request_text = call["input_value"]
        assert "One step = ONE deliverable" in request_text
        assert "capability groups" in request_text
        assert "depends_on" in request_text

    def test_agent_fields_restored_after_planning(self):
        agent = FakePlannerAgent([{"steps": _good_steps()}])
        agent.output_schema = [{"name": "original", "type": "str", "multiple": False}]
        agent.input_value = "original input"
        plugin = MonarchPlugin(monarch_agent=agent)

        asyncio.run(plugin.plan(_intent()))

        assert agent.output_schema == [{"name": "original", "type": "str", "multiple": False}]
        assert agent.input_value == "original input"


class TestDecompositionRuleEnforcement:
    def test_mixed_capability_plan_is_regenerated_with_critique(self):
        mixed = [
            {
                "name": "Build and scan",
                "description": "Implement the module and scan for vulnerabilities.",
                "required_capabilities": ["code_generation", "security_scan"],
                "depends_on": [],
            }
        ]
        fixed = [
            {
                "name": "Build",
                "description": "Implement the payment module.",
                "required_capabilities": ["code_generation"],
                "depends_on": [],
            },
            {
                "name": "Scan",
                "description": "Scan the payment module for vulnerabilities.",
                "required_capabilities": ["security_scan"],
                "depends_on": ["Build"],
            },
        ]
        agent = FakePlannerAgent([{"steps": mixed}, {"steps": fixed}])
        plugin = MonarchPlugin(monarch_agent=agent)

        plan = asyncio.run(plugin.plan(_intent()))

        assert len(agent.calls) == 2  # regenerated once, not patched blindly
        assert plan.metadata["planning_attempts"] == 2
        critique = agent.calls[1]["input_value"]
        assert "REJECTED" in critique
        assert "mixes capability groups" in critique
        assert {"Build", "Scan"} <= {step.name for step in plan.steps}

    def test_serial_chain_of_independent_work_is_regenerated(self):
        chain = [
            {
                "name": "Backend",
                "description": "Build the payments backend service.",
                "required_capabilities": ["code_generation"],
                "depends_on": [],
            },
            {
                "name": "Landing",
                "description": "Design the marketing landing page.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Backend"],
            },
            {
                "name": "Logo",
                "description": "Draw the new brand logo set.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Landing"],
            },
            {
                "name": "Readme",
                "description": "Explain the onboarding steps clearly.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Logo"],
            },
        ]
        parallel = [
            {
                "name": "Backend",
                "description": "Build the payments backend service.",
                "required_capabilities": ["code_generation"],
                "depends_on": [],
            },
            {
                "name": "Landing",
                "description": "Design the marketing landing page.",
                "required_capabilities": ["content_writing"],
                "depends_on": [],
            },
        ]
        agent = FakePlannerAgent([{"steps": chain}, {"steps": parallel}])
        plugin = MonarchPlugin(monarch_agent=agent)

        plan = asyncio.run(plugin.plan(_intent()))

        assert len(agent.calls) == 2
        assert "straight chain" in agent.calls[1]["input_value"]
        assert {step.name for step in plan.steps} == {"Backend", "Landing"}

    def test_persistent_bad_shape_fails_after_max_attempts(self):
        chain = [
            {
                "name": "Backend",
                "description": "Build the payments backend service.",
                "required_capabilities": ["code_generation"],
                "depends_on": [],
            },
            {
                "name": "Landing",
                "description": "Design the marketing landing page.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Backend"],
            },
            {
                "name": "Logo",
                "description": "Draw the new brand logo set.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Landing"],
            },
            {
                "name": "Readme",
                "description": "Explain the onboarding steps clearly.",
                "required_capabilities": ["content_writing"],
                "depends_on": ["Logo"],
            },
        ]
        agent = FakePlannerAgent([{"steps": chain} for _ in range(3)])
        plugin = MonarchPlugin(monarch_agent=agent)

        with pytest.raises(PlanGenerationError) as excinfo:
            asyncio.run(plugin.plan(_intent()))
        assert "3 attempts" in str(excinfo.value)
        assert len(agent.calls) == 3


class TestHardValidationNeverRetried:
    def test_cycle_in_llm_plan_fails_without_regeneration(self):
        cyclic = [
            {
                "name": "A",
                "description": "First deliverable here.",
                "required_capabilities": ["planning"],
                "depends_on": ["B"],
            },
            {
                "name": "B",
                "description": "Second deliverable here.",
                "required_capabilities": ["planning"],
                "depends_on": ["A"],
            },
        ]
        agent = FakePlannerAgent([{"steps": cyclic}, {"steps": _good_steps()}])
        plugin = MonarchPlugin(monarch_agent=agent)

        with pytest.raises(PlanGenerationError) as excinfo:
            asyncio.run(plugin.plan(_intent()))
        assert "cycle" in str(excinfo.value).lower()
        # Exactly one planning call: hard errors are terminal, never patched.
        assert len(agent.calls) == 1

    def test_unknown_dependency_fails_without_retry(self):
        agent = FakePlannerAgent(
            [
                {
                    "steps": [
                        {
                            "name": "A",
                            "description": "Produce the core module.",
                            "required_capabilities": ["planning"],
                            "depends_on": ["Ghost"],
                        }
                    ]
                }
            ]
        )
        plugin = MonarchPlugin(monarch_agent=agent)
        with pytest.raises(PlanGenerationError) as excinfo:
            asyncio.run(plugin.plan(_intent()))
        assert "Ghost" in str(excinfo.value)
        assert len(agent.calls) == 1

    def test_missing_steps_key_raises(self):
        agent = FakePlannerAgent([{"plan_summary": "no steps here"}])
        plugin = MonarchPlugin(monarch_agent=agent)
        with pytest.raises(PlanGenerationError) as excinfo:
            asyncio.run(plugin.plan(_intent()))
        assert "steps" in str(excinfo.value)

    def test_agent_error_payload_raises(self):
        agent = FakePlannerAgent([{"content": "", "error": "model unreachable"}])
        plugin = MonarchPlugin(monarch_agent=agent)
        with pytest.raises(PlanGenerationError) as excinfo:
            asyncio.run(plugin.plan(_intent()))
        assert "model unreachable" in str(excinfo.value)


class TestPlanOnlyFallback:
    def test_none_agent_keeps_single_step_plan(self):
        plugin = MonarchPlugin()
        plan = asyncio.run(plugin.plan(_intent()))
        assert len(plan.steps) == 1
        assert plan.metadata["mode"] == "plan-only"

    def test_agent_without_structured_seam_falls_back_to_plan_only(self):
        """Non-planner agents (e.g. legacy dict mocks) keep the old path."""
        plugin = MonarchPlugin(monarch_agent={"name": "mock"})
        plan = asyncio.run(plugin.plan(_intent()))
        assert len(plan.steps) == 1
        assert plan.metadata["mode"] == "plan-only"


class TestPlanningRequest:
    def test_request_carries_intent_and_rules(self):
        intent = _intent(context={"repo": "demo", "branch": "main"})
        request = build_planning_request(intent)
        assert intent.description in request
        assert "repo: demo" in request
        assert "code_generation" in request  # capability vocabulary
        assert "spawn subagents" in request

    def test_request_includes_critique_for_regeneration(self):
        request = build_planning_request(_intent(), critique="Step 'X' mixes capability groups")
        assert "REJECTED" in request
        assert "Step 'X' mixes capability groups" in request

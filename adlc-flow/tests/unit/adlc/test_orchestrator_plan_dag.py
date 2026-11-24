# ruff: noqa: PLR2004, S101

"""Unit tests for LLM plan-DAG parsing, validation and quality linting (G4)."""

from __future__ import annotations

import pytest

from langflow.adlc.orchestrator_plugin.plan_dag import (
    PlanGenerationError,
    build_plan_steps,
    parse_step_drafts,
    plan_quality_issues,
    validate_step_dag,
)
from langflow.adlc.resource_manager import AgentCapability


def _step(name, description, capabilities, depends_on=None, outputs=None):
    return {
        "name": name,
        "description": description,
        "required_capabilities": capabilities,
        "depends_on": depends_on or [],
        "expected_outputs": outputs or [],
    }


class TestParseStepDrafts:
    def test_parses_names_capabilities_and_lists(self):
        drafts = parse_step_drafts(
            [
                {
                    "name": " Implement service ",
                    "description": "Build the billing service module.  ",
                    "required_capabilities": ["code_generation", "code_generation"],
                    "depends_on": [],
                    "expected_outputs": ["services/billing.py"],
                }
            ]
        )
        assert len(drafts) == 1
        assert drafts[0].name == "Implement service"
        assert drafts[0].description == "Build the billing service module."
        assert drafts[0].required_capabilities == (AgentCapability.CODE_GENERATION,)

    def test_missing_steps_list_raises(self):
        with pytest.raises(PlanGenerationError):
            parse_step_drafts(None)
        with pytest.raises(PlanGenerationError):
            parse_step_drafts([])

    def test_step_missing_name_raises(self):
        with pytest.raises(PlanGenerationError):
            parse_step_drafts([{"description": "Something concrete.", "required_capabilities": ["planning"]}])

    def test_blank_description_raises(self):
        with pytest.raises(PlanGenerationError):
            parse_step_drafts([{"name": "A", "description": "   ", "required_capabilities": ["planning"]}])

    def test_step_without_capabilities_raises(self):
        with pytest.raises(PlanGenerationError):
            parse_step_drafts([{"name": "A", "description": "Something concrete.", "required_capabilities": []}])

    def test_unknown_capability_raises_with_valid_values(self):
        with pytest.raises(PlanGenerationError) as excinfo:
            parse_step_drafts(
                [{"name": "A", "description": "Something concrete.", "required_capabilities": ["quantum_leap"]}]
            )
        assert "quantum_leap" in str(excinfo.value)
        assert "code_generation" in str(excinfo.value)

    def test_duplicate_names_raise(self):
        with pytest.raises(PlanGenerationError):
            parse_step_drafts(
                [
                    {"name": "A", "description": "First concrete deliverable.", "required_capabilities": ["planning"]},
                    {"name": "A", "description": "Second concrete deliverable.", "required_capabilities": ["planning"]},
                ]
            )


class TestValidateStepDag:
    def test_valid_dag_passes(self):
        drafts = parse_step_drafts(
            [
                {"name": "A", "description": "Produce the core module.", "required_capabilities": ["code_generation"], "depends_on": []},
                {"name": "B", "description": "Check the core module.", "required_capabilities": ["code_review"], "depends_on": ["A"]},
            ]
        )
        validate_step_dag(drafts)  # no raise

    def test_unknown_dependency_raises(self):
        drafts = parse_step_drafts(
            [{"name": "A", "description": "Produce the core module.", "required_capabilities": ["planning"], "depends_on": ["Ghost"]}]
        )
        with pytest.raises(PlanGenerationError) as excinfo:
            validate_step_dag(drafts)
        assert "Ghost" in str(excinfo.value)

    def test_cycle_raises(self):
        drafts = parse_step_drafts(
            [
                {"name": "A", "description": "First deliverable here.", "required_capabilities": ["planning"], "depends_on": ["B"]},
                {"name": "B", "description": "Second deliverable here.", "required_capabilities": ["planning"], "depends_on": ["A"]},
            ]
        )
        with pytest.raises(PlanGenerationError) as excinfo:
            validate_step_dag(drafts)
        assert "cycle" in str(excinfo.value).lower()


class TestPlanQualityIssues:
    def test_clean_parallel_plan_has_no_issues(self):
        drafts = parse_step_drafts(
            [
                {"name": "Backend", "description": "Build the payments backend service.", "required_capabilities": ["code_generation"], "depends_on": []},
                {"name": "Review", "description": "Review the payments backend service.", "required_capabilities": ["code_review"], "depends_on": ["Backend"]},
                {"name": "Docs", "description": "Document the deployment runbook.", "required_capabilities": ["content_writing"], "depends_on": []},
            ]
        )
        assert plan_quality_issues(drafts) == ()

    def test_mixed_capability_groups_flagged(self):
        drafts = parse_step_drafts(
            [
                {
                    "name": "Build and scan",
                    "description": "Implement the module and scan it.",
                    "required_capabilities": ["code_generation", "security_scan"],
                }
            ]
        )
        issues = plan_quality_issues(drafts)
        assert len(issues) == 1
        assert "mixes capability groups" in issues[0]
        assert "code_generation" in issues[0] and "security_scan" in issues[0]

    def test_same_group_capabilities_are_allowed(self):
        drafts = parse_step_drafts(
            [
                {
                    "name": "Doc plus code",
                    "description": "Write the module and its usage docs.",
                    "required_capabilities": ["code_generation", "content_writing"],
                }
            ]
        )
        assert plan_quality_issues(drafts) == ()

    def test_serial_chain_of_independent_work_flagged(self):
        drafts = parse_step_drafts(
            [
                {"name": "Backend", "description": "Build the payments backend service.", "required_capabilities": ["code_generation"], "depends_on": []},
                {"name": "Landing", "description": "Design the marketing landing page.", "required_capabilities": ["content_writing"], "depends_on": ["Backend"]},
                {"name": "Logo", "description": "Draw the new brand logo set.", "required_capabilities": ["content_writing"], "depends_on": ["Landing"]},
                {"name": "Readme", "description": "Explain the onboarding steps clearly.", "required_capabilities": ["content_writing"], "depends_on": ["Logo"]},
            ]
        )
        issues = plan_quality_issues(drafts)
        assert any("straight chain" in issue for issue in issues)

    def test_short_legitimate_chain_not_flagged(self):
        drafts = parse_step_drafts(
            [
                {"name": "A", "description": "Produce the core module first.", "required_capabilities": ["code_generation"], "depends_on": []},
                {"name": "B", "description": "Produce the core module tests after.", "required_capabilities": ["test_runner"], "depends_on": ["A"]},
            ]
        )
        assert plan_quality_issues(drafts) == ()


class TestBuildPlanSteps:
    def test_depends_on_resolved_to_uuids(self):
        drafts = parse_step_drafts(
            [
                {"name": "A", "description": "Produce the core module.", "required_capabilities": ["code_generation"], "depends_on": []},
                {"name": "B", "description": "Verify the core module.", "required_capabilities": ["test_runner"], "depends_on": ["A"], "expected_outputs": ["report.xml"]},
            ]
        )
        steps = build_plan_steps(drafts)
        assert steps[1].depends_on == (steps[0].step_id,)
        assert steps[1].expected_outputs == ("report.xml",)
        assert steps[0].required_capabilities == frozenset({AgentCapability.CODE_GENERATION})

# ruff: noqa: PLR2004, S101

"""Compile-only validation for the "Live Demo" fixture.

The live-demo blueprint adds per-stage mock ``delay_ms`` so the UI shows task
state transitions while it polls. The full run/retry behavior is covered by
the base fixture test; here we only verify the fixture still parses and
compiles through the real planning pipeline with the delays preserved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from langflow.adlc.blueprints.models import PlanStatus, PlanValidationStatus
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService

OWNER = "fixture-demo-owner"
FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "implement-user-feature-live-demo-blueprint.json"
)

EXPECTED_DELAYS = {
    "Analyze Requirements": 3500,
    "Backend Implementation": 4500,
    "Frontend Implementation": 4500,
    "Testing": 3000,
    "Review": 2000,
}


def test_live_demo_fixture_compiles_with_visible_delays() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    flow_id = UUID(fixture["data"]["adlc"]["workflow_definition_id"])
    context = BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name=fixture["name"],
        description=fixture["description"],
        created_by=OWNER,
        created_at=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc),
    )

    workflow = parse_blueprint_flow(fixture["data"], context)
    plan_service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = plan_service.create_plan(workflow, owner_id=OWNER, generated_by=OWNER)

    assert plan.status is PlanStatus.VALIDATED
    assert plan.validation_status is PlanValidationStatus.VALID
    assert len(plan.tasks) == 5

    by_name = {task.name: task for task in plan.tasks}
    specs = {spec.resolved_node_spec_id: spec for spec in plan.resolved_node_specs}
    for name, delay in EXPECTED_DELAYS.items():
        spec = specs[by_name[name].resolved_node_spec_id]
        assert spec.configuration["delay_ms"] == delay
    backend_spec = specs[by_name["Backend Implementation"].resolved_node_spec_id]
    assert backend_spec.configuration["simulate_failure"] is True

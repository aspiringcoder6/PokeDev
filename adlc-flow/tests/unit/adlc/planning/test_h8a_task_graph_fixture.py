# ruff: noqa: PLR2004, S101
"""The UI's branching fixture is a real compiled plan, not invented graph nodes."""

import json
from pathlib import Path
from uuid import UUID

from langflow.adlc.blueprints.models import ExecutionPlan, PlanValidationStatus
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow


def test_h8a_branching_fixture_compiles_and_preserves_both_join_dependencies():
    root = Path(__file__).resolve().parents[4]
    payload = json.loads(
        (root / "frontend/tests/delivery-workspace-preview/task-graph-plan.json").read_text(encoding="utf-8")
    )
    saved = ExecutionPlan.model_validate(payload["plan"])
    context = BlueprintParseContext(
        flow_id=saved.workflow_definition_id,
        project_id=saved.workflow_definition_id,
        name="H8A branching graph fixture",
        description="Compiler-validated UI fixture only; never executed.",
        created_by="fixture",
        created_at=saved.generated_at,
        updated_at=saved.generated_at,
    )
    workflow = parse_blueprint_flow(payload["workflow"], context)
    compiled = BlueprintCompiler(create_default_package_resolver()).compile(
        workflow, plan_version=1, generated_by="fixture", generated_at=saved.generated_at
    )
    assert compiled.validation_status is PlanValidationStatus.VALID
    assert compiled.model_dump(mode="json") == saved.model_dump(mode="json")
    assert len(compiled.tasks) == 4
    assert sum(len(task.dependency_task_ids) for task in compiled.tasks) == 4
    by_stage = {task.source_workflow_stage_id: task for task in compiled.tasks}
    branches = {by_stage[UUID(f"00000000-0000-4000-8000-{index:012d}")].plan_task_id for index in (2, 3)}
    join = by_stage[UUID("00000000-0000-4000-8000-000000000004")]
    assert set(join.dependency_task_ids) == branches

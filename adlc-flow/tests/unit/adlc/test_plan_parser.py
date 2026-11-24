# ruff: noqa: INP001, S101, S106

"""Unit tests for :mod:`langflow.adlc.plan_parser`."""

from __future__ import annotations

import pytest

from langflow.adlc.plan_models import (
    AggregationStrategy,
    PlanSpec,
    SubtaskTrigger,
)
from langflow.adlc.plan_parser import (
    PlanParseError,
    find_task_for_subtask,
    parse_plan_response,
    plan_to_subtask_specs,
)
from langflow.adlc.plan_validator import PlanValidationError


def _valid_plan_json() -> str:
    return """
    ```json
    {
      "schema_version": "0.1",
      "objective": "Build a thing",
      "tasks": [
        {
          "id": "task-1",
          "name": "Research",
          "description": "Read the codebase",
          "objective": "Understand the existing structure of the project.",
          "subtasks": [
            {
              "id": "task-1.sub-1",
              "name": "Read models",
              "objective": "Read all model files and summarize the schema.",
              "dependencies": [],
              "trigger": "on_success"
            },
            {
              "id": "task-1.sub-2",
              "name": "Identify patterns",
              "objective": "Identify common patterns used across the codebase.",
              "dependencies": ["task-1.sub-1"],
              "trigger": "on_success"
            }
          ],
          "dependencies": []
        },
        {
          "id": "task-2",
          "name": "Implement",
          "description": "Write the new code",
          "objective": "Implement the feature based on the research findings.",
          "subtasks": [
            {
              "id": "task-2.sub-1",
              "name": "Write code",
              "objective": "Write the implementation following the identified patterns.",
              "dependencies": ["task-1.sub-2"],
              "trigger": "on_success"
            }
          ],
          "dependencies": ["task-1"]
        }
      ]
    }
    ```
    """


def test_parse_extracts_json_from_fenced_block() -> None:
    plan = parse_plan_response(_valid_plan_json())
    assert isinstance(plan, PlanSpec)
    assert len(plan.tasks) == 2
    assert plan.tasks[0].subtasks[0].trigger is SubtaskTrigger.ON_SUCCESS


def test_parse_extracts_bare_json() -> None:
    raw = '{"schema_version": "0.1", "objective": "x", "tasks": [{"id": "t1", "name": "T", "objective": "Do the thing end to end.", "subtasks": [{"id": "t1.s1", "name": "S", "objective": "Do the subtask end to end."}]}]}'
    plan = parse_plan_response(raw)
    assert len(plan.tasks) == 1


def test_parse_rejects_reply_without_json() -> None:
    with pytest.raises(PlanParseError, match="did not contain a JSON object"):
        parse_plan_response("Here is the plan: I will do X, then Y, then Z.")


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(PlanParseError, match="invalid JSON"):
        parse_plan_response("```json\n{not valid json}\n```")


def test_parse_rejects_non_object_json() -> None:
    # A bare array is valid JSON but not a plan object.
    with pytest.raises(PlanParseError, match="did not contain a JSON object"):
        parse_plan_response("[1, 2, 3]")


def test_parse_normalizes_legacy_linear_plan() -> None:
    raw = """
    ```json
    {
      "objective": "Build a thing",
      "tasks": [
        {
          "id": "task-1",
          "name": "Research",
          "objective": "Understand the existing structure of the project.",
          "dependencies": []
        },
        {
          "id": "task-2",
          "name": "Implement",
          "objective": "Implement the feature based on the research findings.",
          "dependencies": ["task-1"]
        }
      ]
    }
    ```
    """
    plan = parse_plan_response(raw)
    assert len(plan.tasks) == 2
    # Each legacy task should have been wrapped in a single subtask.
    assert len(plan.tasks[0].subtasks) == 1
    assert plan.tasks[0].subtasks[0].id == "task-1.only"
    assert plan.tasks[1].subtasks[0].dependencies == ["task-1"]


def test_parse_injects_schema_version_when_missing() -> None:
    raw = '{"objective": "x", "tasks": [{"id": "t1", "name": "T", "objective": "Do the thing end to end.", "subtasks": [{"id": "t1.s1", "name": "S", "objective": "Do the subtask end to end."}]}]}'
    plan = parse_plan_response(raw)
    assert plan.schema_version == "0.1"


def test_parse_runs_validation_by_default() -> None:
    # Cycle: task-1 depends on task-2, task-2 depends on task-1.
    raw = """
    ```json
    {
      "schema_version": "0.1",
      "objective": "Build a thing",
      "tasks": [
        {
          "id": "task-1",
          "name": "A",
          "objective": "Do the first thing end to end.",
          "subtasks": [{"id": "task-1.sub-1", "name": "S", "objective": "Do the subtask end to end."}],
          "dependencies": ["task-2"]
        },
        {
          "id": "task-2",
          "name": "B",
          "objective": "Do the second thing end to end.",
          "subtasks": [{"id": "task-2.sub-1", "name": "S", "objective": "Do the subtask end to end."}],
          "dependencies": ["task-1"]
        }
      ]
    }
    ```
    """
    with pytest.raises(PlanValidationError, match="cycle"):
        parse_plan_response(raw)


def test_parse_can_skip_validation() -> None:
    raw = _valid_plan_json()
    plan = parse_plan_response(raw, validate=False)
    assert len(plan.tasks) == 2


def test_plan_to_subtask_specs_flattens() -> None:
    plan = parse_plan_response(_valid_plan_json())
    subtasks = plan_to_subtask_specs(plan)
    assert len(subtasks) == 3
    ids = {s.id for s in subtasks}
    assert ids == {"task-1.sub-1", "task-1.sub-2", "task-2.sub-1"}


def test_find_task_for_subtask_returns_owner() -> None:
    plan = parse_plan_response(_valid_plan_json())
    task = find_task_for_subtask(plan, "task-1.sub-2")
    assert task is not None
    assert task.id == "task-1"


def test_find_task_for_subtask_returns_none_for_unknown() -> None:
    plan = parse_plan_response(_valid_plan_json())
    assert find_task_for_subtask(plan, "task-99.sub-1") is None

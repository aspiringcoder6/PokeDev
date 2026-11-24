"""Tests for the on-demand subtask generator."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from langflow.adlc.models import Artifact, TaskResult, TaskResultStatus
from langflow.adlc.subtask_generator import SubtaskGenerator
from langflow.adlc.subtask_prompt import render_subtask_prompt


def _make_task_result(text: str, status: TaskResultStatus = TaskResultStatus.SUCCEEDED) -> TaskResult:
    now = datetime.now(timezone.utc)
    return TaskResult(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        status=status,
        output={"final_text": text},
        artifacts=[],
        error=None,
        started_at=now,
        completed_at=now,
    )


def _make_executor(result: TaskResult | None = None, error: Exception | None = None) -> MagicMock:
    executor = MagicMock()
    if error:
        executor.execute = AsyncMock(side_effect=error)
    elif result:
        executor.execute = AsyncMock(return_value=result)
    else:
        executor.execute = AsyncMock(return_value=_make_task_result(""))
    return executor


class TestRenderSubtaskPrompt:
    def test_renders_task_id(self):
        prompt = render_subtask_prompt(
            task_id="task-1",
            task_name="Research X",
            task_type="research",
            task_description="Find docs",
            task_objective="Research X thoroughly",
        )
        assert "task-1" in prompt
        assert "Research X" in prompt
        assert "research" in prompt.lower()

    def test_includes_workflow_context(self):
        prompt = render_subtask_prompt(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
            workflow_context="This is part of a larger workflow",
        )
        assert "larger workflow" in prompt

    def test_prompt_specifies_2_to_5_subtasks(self):
        """The prompt must ask for 2-5 subtasks, not 1-8."""
        prompt = render_subtask_prompt(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )
        assert "2 to 5" in prompt or "2–5" in prompt
        # Should NOT say 1-8 anymore.
        assert "1 and 8" not in prompt

    def test_prompt_emphasizes_parallelism(self):
        """The prompt must tell the LLM to maximize parallelism."""
        prompt = render_subtask_prompt(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )
        assert "parallel" in prompt.lower()
        assert "dependencies" in prompt.lower()

    def test_prompt_warns_against_single_subtask(self):
        """The prompt must discourage a single subtask unless atomic."""
        prompt = render_subtask_prompt(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )
        assert "atomic" in prompt.lower()
        assert "single subtask" in prompt.lower() or "1 subtask" in prompt.lower()


class TestSubtaskGeneratorFallback:
    @pytest.mark.asyncio
    async def test_fallback_when_executor_fails(self):
        executor = _make_executor(error=Exception("DSH unavailable"))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Research X",
            task_type="research",
            task_description="Find docs",
            task_objective="Research X",
        )

        assert len(subtasks) == 1
        assert subtasks[0].id == "task-1.sub-1"
        assert subtasks[0].name == "Research X"

    @pytest.mark.asyncio
    async def test_fallback_when_result_not_succeeded(self):
        executor = _make_executor(
            result=_make_task_result("", status=TaskResultStatus.FAILED)
        )
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )

        assert len(subtasks) == 1
        assert subtasks[0].id == "task-1.sub-1"

    @pytest.mark.asyncio
    async def test_fallback_when_no_text_output(self):
        executor = _make_executor(result=_make_task_result(""))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )

        assert len(subtasks) == 1


class TestSubtaskGeneratorSuccess:
    @pytest.mark.asyncio
    async def test_parses_valid_subtask_response(self):
        response_text = """
        ```json
        {
          "schema_version": "0.1",
          "task_id": "task-1",
          "subtasks": [
            {
              "id": "task-1.sub-1",
              "name": "Search docs",
              "description": "Find relevant docs",
              "objective": "Search for documentation",
              "dependencies": [],
              "trigger": "on_success"
            },
            {
              "id": "task-1.sub-2",
              "name": "Read code",
              "description": "Read source code",
              "objective": "Read the source",
              "dependencies": ["task-1.sub-1"],
              "trigger": "on_success"
            }
          ]
        }
        ```
        """
        executor = _make_executor(result=_make_task_result(response_text))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Research X",
            task_type="research",
            task_description="Find docs",
            task_objective="Research X",
        )

        assert len(subtasks) == 2
        assert subtasks[0].id == "task-1.sub-1"
        assert subtasks[0].name == "Search docs"
        assert subtasks[1].dependencies == ["task-1.sub-1"]

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        executor = _make_executor(result=_make_task_result("not valid json"))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )

        assert len(subtasks) == 1
        assert subtasks[0].id == "task-1.sub-1"

    @pytest.mark.asyncio
    async def test_fallback_on_empty_subtasks(self):
        response_text = '{"subtasks": []}'
        executor = _make_executor(result=_make_task_result(response_text))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Test",
            task_type="test",
            task_description="",
            task_objective="",
        )

        assert len(subtasks) == 1

    @pytest.mark.asyncio
    async def test_parses_2_to_5_subtasks(self):
        """The planner should produce 2-5 subtasks for a normal task."""
        response_text = """
        ```json
        {
          "schema_version": "0.1",
          "task_id": "task-1",
          "subtasks": [
            {
              "id": "task-1.sub-1",
              "name": "Design schema",
              "description": "Design the database schema",
              "objective": "Design the database schema for the new feature",
              "dependencies": [],
              "trigger": "on_success"
            },
            {
              "id": "task-1.sub-2",
              "name": "Implement API",
              "description": "Implement the REST API endpoints",
              "objective": "Implement the REST API endpoints for the new feature",
              "dependencies": [],
              "trigger": "on_success"
            },
            {
              "id": "task-1.sub-3",
              "name": "Write tests",
              "description": "Write unit and integration tests",
              "objective": "Write unit and integration tests for the new feature",
              "dependencies": ["task-1.sub-1", "task-1.sub-2"],
              "trigger": "on_success"
            }
          ]
        }
        ```
        """
        executor = _make_executor(result=_make_task_result(response_text))
        generator = SubtaskGenerator(executor)

        subtasks = await generator.generate_subtasks(
            task_id="task-1",
            task_name="Build feature",
            task_type="backend",
            task_description="Build a new feature",
            task_objective="Build a new feature end-to-end",
        )

        assert len(subtasks) == 3
        # First two should be parallel (no dependencies).
        assert subtasks[0].dependencies == []
        assert subtasks[1].dependencies == []
        # Third depends on both.
        assert set(subtasks[2].dependencies) == {"task-1.sub-1", "task-1.sub-2"}

    @pytest.mark.asyncio
    async def test_warns_on_single_subtask(self, caplog):
        """A single subtask should trigger a warning (acceptable only for atomic work)."""
        import logging

        response_text = """
        ```json
        {
          "schema_version": "0.1",
          "task_id": "task-1",
          "subtasks": [
            {
              "id": "task-1.sub-1",
              "name": "Do everything",
              "description": "Do the whole task",
              "objective": "Do the whole task in one go because it is atomic",
              "dependencies": [],
              "trigger": "on_success"
            }
          ]
        }
        ```
        """
        executor = _make_executor(result=_make_task_result(response_text))
        generator = SubtaskGenerator(executor)

        with caplog.at_level(logging.WARNING, logger="langflow.adlc.plan_parser"):
            subtasks = await generator.generate_subtasks(
                task_id="task-1",
                task_name="Atomic task",
                task_type="misc",
                task_description="",
                task_objective="",
            )

        assert len(subtasks) == 1
        assert any("only 1 subtask" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_warns_on_too_many_subtasks(self, caplog):
        """More than 5 subtasks should trigger an over-decomposition warning."""
        import logging

        # Build 7 subtasks.
        subtask_entries = []
        for i in range(1, 8):
            subtask_entries.append(
                f"""
                {{
                  "id": "task-1.sub-{i}",
                  "name": "Subtask {i}",
                  "description": "Do thing {i}",
                  "objective": "Do thing {i} as part of the larger task",
                  "dependencies": [],
                  "trigger": "on_success"
                }}
                """
            )
        response_text = (
            '```json\n{"schema_version": "0.1", "task_id": "task-1", "subtasks": ['
            + ",".join(subtask_entries)
            + "]}\n```"
        )
        executor = _make_executor(result=_make_task_result(response_text))
        generator = SubtaskGenerator(executor)

        with caplog.at_level(logging.WARNING, logger="langflow.adlc.plan_parser"):
            subtasks = await generator.generate_subtasks(
                task_id="task-1",
                task_name="Big task",
                task_type="backend",
                task_description="",
                task_objective="",
            )

        assert len(subtasks) == 7
        assert any("over-decomposed" in record.message for record in caplog.records)

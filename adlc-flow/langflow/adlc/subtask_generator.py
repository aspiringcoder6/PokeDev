"""On-demand subtask generator.

After the user accepts a high-level plan, this module SDKs to DSH for
each task and asks "how would you divide this task into parallel
subtasks?". The response is parsed into a list of :class:`SubtaskSpec`
objects that can be executed by :class:`PlanExecutor`.

This is different from the upfront plan generation in
:mod:`plan_orchestrator`: subtasks are generated per-task, on-demand,
so each task's subtask structure is tailored to its specific content.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.models import TaskRequest, TaskResult, TaskResultStatus
from langflow.adlc.plan_models import SubtaskSpec
from langflow.adlc.plan_parser import PlanParseError, parse_subtask_response
from langflow.adlc.subtask_prompt import render_subtask_prompt

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import StateChangeCallback

logger = logging.getLogger(__name__)


class SubtaskGenerator:
    """Generate subtasks for a single task by SDKing to DSH.

    The generator wraps a :class:`DeepSeekHarnessTaskExecutor` and uses
    it to run a short planner session that asks the DSH LLM how to
    divide the task into subtasks.
    """

    def __init__(self, task_executor: DeepSeekHarnessTaskExecutor) -> None:
        self._task_executor = task_executor

    async def generate_subtasks(
        self,
        task_id: str,
        task_name: str,
        task_type: str,
        task_description: str,
        task_objective: str,
        workflow_context: str = "",
        on_state_change: "StateChangeCallback | None" = None,
    ) -> list[SubtaskSpec]:
        """SDK to DSH and return a list of subtasks for the given task.

        Falls back to a single subtask (the task itself) if the planner
        session fails or returns unparseable output.
        """
        prompt = render_subtask_prompt(
            task_id=task_id,
            task_name=task_name,
            task_type=task_type,
            task_description=task_description,
            task_objective=task_objective,
            workflow_context=workflow_context,
        )

        planner_request = self._build_planner_request(
            task_id=task_id,
            task_name=task_name,
            prompt=prompt,
        )

        try:
            result = await self._task_executor.execute(
                planner_request,
                on_state_change or _noop_state_change,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Subtask planner session failed for task %s: %s. "
                "Falling back to single subtask.",
                task_id,
                exc,
            )
            return _fallback_subtasks(task_id, task_name, task_objective)

        if result.status is not TaskResultStatus.SUCCEEDED:
            logger.warning(
                "Subtask planner session did not succeed for task %s: %s. "
                "Falling back to single subtask.",
                task_id,
                result.status,
            )
            return _fallback_subtasks(task_id, task_name, task_objective)

        # Extract the planner's text output.
        planner_output = _extract_final_text(result)
        if not planner_output:
            logger.warning(
                "Subtask planner returned no text output for task %s. "
                "Falling back to single subtask.",
                task_id,
            )
            return _fallback_subtasks(task_id, task_name, task_objective)

        # Parse the JSON response.
        try:
            subtasks = parse_subtask_response(planner_output, task_id=task_id)
        except PlanParseError as exc:
            logger.warning(
                "Failed to parse subtask planner output for task %s: %s. "
                "Falling back to single subtask.",
                task_id,
                exc,
            )
            return _fallback_subtasks(task_id, task_name, task_objective)

        if not subtasks:
            return _fallback_subtasks(task_id, task_name, task_objective)

        logger.info(
            "Generated %d subtasks for task %s via DSH planner.",
            len(subtasks),
            task_id,
        )
        return subtasks

    def _build_planner_request(
        self,
        task_id: str,
        task_name: str,
        prompt: str,
    ) -> TaskRequest:
        """Build a TaskRequest that asks the LLM to divide a task into subtasks."""
        from langflow.adlc.models import ExecutorTarget

        return TaskRequest(
            request_id=uuid4(),
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
            attempt_id=uuid4(),
            task_definition_id=uuid4(),
            task_type="subtask_planner",
            name=f"Subtask plan: {task_name}",
            executor=ExecutorTarget(
                service="agent-provider:deepseek-harness",
                operation="execute",
            ),
            input={
                "objective": prompt,
                "is_subtask_planner": True,
                "parent_task_id": task_id,
            },
            dependency_task_run_ids=[],
            constraints={"timeout_ms": 180_000},  # 3 min for subtask planning
            idempotency_key=f"subtask-planner:{task_id}",
            requested_at=datetime.now(timezone.utc),
            metadata={
                "is_subtask_planner": True,
                "parent_task_id": task_id,
            },
        )


async def _noop_state_change(status, payload) -> None:
    """Default no-op state change callback."""


def _extract_final_text(result: TaskResult) -> str:
    """Pull the LLM's final text out of a TaskResult."""
    if isinstance(result.output, dict):
        for key in ("final_text", "summary", "output", "text"):
            value = result.output.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if isinstance(result.output, str):
        return result.output
    return ""


def _fallback_subtasks(
    task_id: str,
    task_name: str,
    task_objective: str,
) -> list[SubtaskSpec]:
    """Return a single subtask that wraps the entire task."""
    return [
        SubtaskSpec(
            id=f"{task_id}.sub-1",
            name=task_name,
            description=f"Execute task: {task_name}",
            objective=task_objective or f"Complete task: {task_name}",
            dependencies=[],
            trigger="on_success",
            timeout_seconds=600,
            expected_outputs=["summary"],
        )
    ]


__all__ = ["SubtaskGenerator"]

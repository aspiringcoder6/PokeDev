# ruff: noqa: INP001, S101, S105, S106

"""Unit tests for :mod:`langflow.adlc.plan_orchestrator`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.adapter_interfaces import StateChangeCallback
from langflow.adlc.models import (
    ExecutorTarget,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRunStatus,
)
from langflow.adlc.plan_orchestrator import PlanOrchestratingExecutor


# ----------------------------------------------------------------------
# Fake executor that returns scripted results based on the request
# ----------------------------------------------------------------------


@dataclass
class _ScriptedExecutor:
    """Returns results based on the request's input content."""

    responses: list[TaskResult] = field(default_factory=list)
    call_index: int = 0
    calls: list[TaskRequest] = field(default_factory=list)

    async def execute(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> TaskResult:
        self.calls.append(request)
        if self.call_index < len(self.responses):
            response = self.responses[self.call_index]
            self.call_index += 1
            return response
        # Default: succeed with empty output.
        return _make_result(request, status=TaskResultStatus.SUCCEEDED, output={})

    async def resume(
        self,
        request: TaskRequest,
        on_state_change: StateChangeCallback,
    ) -> TaskResult:
        return await self.execute(request, on_state_change)


def _make_result(
    request: TaskRequest,
    *,
    status: TaskResultStatus,
    output: Any = None,
    error: ServiceError | None = None,
) -> TaskResult:
    now = datetime.now(timezone.utc)
    return TaskResult(
        schema_version="0.1",
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
        status=status,
        output=output or {},
        artifacts=[],
        error=error,
        started_at=now,
        completed_at=now,
    )


def _service_error(code: str = "TEST_ERROR") -> ServiceError:
    return ServiceError(
        schema_version="0.1",
        error_id=uuid4(),
        code=code,
        category="EXECUTION",
        message="test failure",
        retryable=False,
        service="test",
        occurred_at=datetime.now(timezone.utc),
    )


def _request(objective: str = "Build a thing") -> TaskRequest:
    return TaskRequest(
        schema_version="0.1",
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="plan_orchestrator",
        name="Test task",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="execute"),
        input={"objective": objective},
        dependency_task_run_ids=[],
        idempotency_key="test",
        requested_at=datetime.now(timezone.utc),
    )


def _valid_plan_text() -> str:
    return """
    ```json
    {
      "schema_version": "0.1",
      "objective": "Build a thing",
      "tasks": [
        {
          "id": "task-1",
          "name": "Research",
          "objective": "Understand the existing structure of the project.",
          "subtasks": [
            {
              "id": "task-1.sub-1",
              "name": "Read models",
              "objective": "Read all model files and summarize the schema.",
              "dependencies": []
            },
            {
              "id": "task-1.sub-2",
              "name": "Identify patterns",
              "objective": "Identify common patterns used across the codebase.",
              "dependencies": ["task-1.sub-1"]
            }
          ]
        }
      ]
    }
    ```
    """


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


async def test_orchestrator_generates_plan_and_executes_subtasks() -> None:
    """Happy path: planner returns a plan, subtasks run, result is aggregated."""
    fake = _ScriptedExecutor(
        responses=[
            # First call: planner returns a plan.
            _make_result(
                _request(),
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": _valid_plan_text()},
            ),
            # Subsequent calls: subtasks succeed.
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "sub-1 done"}),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "sub-2 done"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert result.output["total_subtasks"] == 2
    assert result.output["succeeded"] == 2
    assert result.output["failed"] == 0
    # 1 planner call + 2 subtask calls = 3 total.
    assert len(fake.calls) == 3


async def test_orchestrator_falls_back_when_planner_returns_prose() -> None:
    """If the planner returns non-JSON, fall back to single-task execution."""
    fake = _ScriptedExecutor(
        responses=[
            # Planner returns prose (not JSON).
            _make_result(
                _request(),
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": "I will do X, then Y, then Z."},
            ),
            # Fallback execution succeeds.
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "done"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    assert result.status is TaskResultStatus.SUCCEEDED
    # 1 planner call + 1 fallback call = 2 total.
    assert len(fake.calls) == 2


async def test_orchestrator_falls_back_when_planner_fails() -> None:
    """If the planner session fails, fall back to single-task execution."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(_request(), status=TaskResultStatus.FAILED, error=_service_error()),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "done"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(fake.calls) == 2


async def test_orchestrator_propagates_subtask_failure() -> None:
    """If a subtask fails, the overall task fails with that error."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(
                _request(),
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": _valid_plan_text()},
            ),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "sub-1 done"}),
            _make_result(_request(), status=TaskResultStatus.FAILED, error=_service_error("SUBTASK_FAILED")),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    assert result.status is TaskResultStatus.FAILED
    assert result.error is not None
    assert result.error.code == "SUBTASK_FAILED"


async def test_orchestrator_disabled_runs_single_task() -> None:
    """When planning is disabled, the orchestrator delegates directly."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "done"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, enable_planning=False)  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    assert result.status is TaskResultStatus.SUCCEEDED
    # Only 1 call (no planner).
    assert len(fake.calls) == 1


async def test_orchestrator_extracts_objective_from_input() -> None:
    """The orchestrator pulls the objective from request.input."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(
                _request(),
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": _valid_plan_text()},
            ),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={}),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    await orchestrator.execute(_request("My custom objective"), _noop_callback)

    # The planner call should have the plan-generation prompt.
    planner_call = fake.calls[0]
    assert "My custom objective" in planner_call.input["objective"]


async def test_orchestrator_aggregates_subtask_results() -> None:
    """The output contains per-subtask results."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(
                _request(),
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": _valid_plan_text()},
            ),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"detail": "sub-1 result"}),
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"detail": "sub-2 result"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.execute(_request(), _noop_callback)

    task_results = result.output["task_results"]
    assert "task-1" in task_results
    assert task_results["task-1"]["succeeded"] == 2
    assert task_results["task-1"]["failed"] == 0


async def test_orchestrator_resume_delegates_to_underlying() -> None:
    """Resume is not supported for plan orchestration; delegate to underlying."""
    fake = _ScriptedExecutor(
        responses=[
            _make_result(_request(), status=TaskResultStatus.SUCCEEDED, output={"summary": "resumed"}),
        ]
    )
    orchestrator = PlanOrchestratingExecutor(fake, planning_mode="llm")  # type: ignore[arg-type]

    result = await orchestrator.resume(_request(), _noop_callback)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert len(fake.calls) == 1


async def test_orchestrator_service_name_matches_harness_executor() -> None:
    """The orchestrator uses the same service name as DeepSeekHarnessTaskExecutor."""
    from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor

    assert PlanOrchestratingExecutor.service_name == DeepSeekHarnessTaskExecutor.service_name


async def _noop_callback(_status: TaskRunStatus, _result: TaskResult | None) -> None:
    return None

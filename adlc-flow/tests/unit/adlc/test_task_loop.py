# ruff: noqa: INP001, PLR2004, S101

"""Delivery A proves fresh context, cumulative artifacts, and coordinator-owned repetition."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.models import PackageReference
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    TaskRequest,
    TaskResultStatus,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.adlc.opencode_runtime import OpenCodeRuntimeSettings, create_default_task_executor
from langflow.adlc.packages.defaults import create_default_package_access_policy
from langflow.adlc.run_repository import InMemoryRunRepository
from langflow.adlc.run_service import AdlcRunService, AdlcRunStateError
from langflow.adlc.task_loop import TASK_LOOP_MOCK_SERVICE, MockTaskLoopExecutor
from langflow.adlc.task_loop_models import TaskLoopCandidate, TaskLoopSpec
from scripts.demo_adlc_task_loop import demo_definitions
from scripts.generate_adlc_task_loop_schemas import MODELS, OUTPUT

ROOT = Path(__file__).resolve().parents[4]


def _spec(**overrides) -> TaskLoopSpec:
    payload = json.loads(
        (ROOT / "adlc-contracts/task-loop/v0.1/examples/task-loop-spec.json").read_text(encoding="utf-8")
    )
    payload.update(overrides)
    return TaskLoopSpec.model_validate(payload)


def _request(spec: TaskLoopSpec | None = None, **overrides) -> TaskRequest:
    specification = spec or _spec()
    package = json.loads((ROOT / "adlc_components/packages/task-loop/0.1.0/package.json").read_text(encoding="utf-8"))
    payload = {
        "request_id": uuid4(),
        "workflow_run_id": uuid4(),
        "task_run_id": uuid4(),
        "attempt_id": uuid4(),
        "task_definition_id": uuid4(),
        "task_type": "IMPLEMENTATION",
        "name": "Task Loop (Mock)",
        "executor": ExecutorTarget(service=TASK_LOOP_MOCK_SERVICE, operation="mock-task-loop"),
        "input": {"namedInputs": {"task_loop_spec": specification.model_dump(mode="json")}},
        "context": {"conversation_history": ["OLD_TRANSCRIPT_MUST_NOT_BE_FORWARDED"]},
        "dependency_task_run_ids": [],
        "constraints": {"max_attempts": specification.max_iterations},
        "requested_at": datetime.now(timezone.utc),
        "metadata": {"resolved_configuration": package["defaults"]},
        "idempotency_key": str(uuid4()),
    }
    payload.update(overrides)
    return TaskRequest(**payload)


def _next_attempt(request: TaskRequest, **overrides) -> TaskRequest:
    return _request(
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        task_definition_id=request.task_definition_id,
        input=request.input,
        metadata=request.metadata,
        constraints=request.constraints,
        **overrides,
    )


async def _ignore_state(*_args) -> None:
    return None


async def test_coordinator_repeats_one_task_until_checks_pass_then_waits_for_approval() -> None:
    workflow, definitions = demo_definitions()
    definitions[0].constraints["retry_backoff_ms"] = 0
    executor = MockTaskLoopExecutor()
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_MOCK_SERVICE: executor}),
        repository=InMemoryRunRepository(),
    )
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name=workflow.name,
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )

    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert len(run.tasks) == 1
    assert run.tasks[0].retry_count == 2
    assert run.tasks[0].status is TaskRunStatus.WAITING_APPROVAL
    history = executor.history(run.id, run.tasks[0].id)
    assert [record.verification.passed for record in history] == [False, False, True]
    assert [sum(check.passed for check in record.verification.checks) for record in history] == [1, 2, 3]
    assert len({record.request_id for record in history}) == 3
    assert len({record.attempt_id for record in history}) == 3
    assert len({record.session_id for record in history}) == 3
    assert {record.prompt.spec_digest for record in history} == {_spec().content_digest}
    assert all(record.prompt.specification == _spec() for record in history)
    assert all(len(session.messages) == 1 for session in executor.agent.sessions)
    assert "OLD_TRANSCRIPT_MUST_NOT_BE_FORWARDED" not in "".join(
        session.messages[0] for session in executor.agent.sessions
    )
    assert "TRACE_ONLY_ITERATION_ONE" not in executor.agent.sessions[1].messages[0]
    assert "TRACE_ONLY_ITERATION_TWO" not in executor.agent.sessions[2].messages[0]
    assert history[1].prompt.candidate == history[0].candidate
    assert history[2].prompt.candidate == history[1].candidate
    assert history[1].candidate.files["math_utils.py"] == history[0].candidate.files["math_utils.py"]
    assert history[2].candidate.files["settings.json"] == history[1].candidate.files["settings.json"]
    assert "legacy.txt" in history[1].candidate.files
    assert "legacy.txt" not in history[2].candidate.files
    assert len(history[1].prompt.previous_findings) == 2
    assert len(history[2].prompt.previous_findings) == 1
    assert sum(event.event_type == "task_run.retry_scheduled" for event in run.events) == 2
    assert run.tasks[0].pending_result.metadata["task_loop"]["verification_mode"] == "MOCK"

    approved = await service.approve(
        run.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment="Approve the exact mock candidate.",
    )
    assert approved.status is WorkflowRunStatus.SUCCEEDED
    assert (
        approved.tasks[0].result.output["outputs"]["candidate"]["content_digest"] == history[2].candidate.content_digest
    )
    assert len(executor.agent.sessions) == 3


async def test_exhausted_budget_stops_after_two_iterations() -> None:
    workflow, definitions = demo_definitions(_spec(max_iterations=2))
    definitions[0].constraints["retry_backoff_ms"] = 0
    executor = MockTaskLoopExecutor()
    service = AdlcRunService(executor, repository=InMemoryRunRepository())
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name=workflow.name,
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    assert run.status is WorkflowRunStatus.PAUSED
    assert run.tasks[0].status is TaskRunStatus.FAILED
    assert run.tasks[0].result.error.code == "TASK_LOOP_BUDGET_EXHAUSTED"
    assert run.tasks[0].result.error.retryable is False
    assert len(executor.agent.sessions) == 2
    assert run.approval_requests == []
    with pytest.raises(AdlcRunStateError):
        await service.retry_task(run.tasks[0].id, owner_id="owner")


async def test_duplicate_concurrent_delivery_replays_without_starting_another_session() -> None:
    executor = MockTaskLoopExecutor()
    request = _request()
    first, replay = await asyncio.gather(
        executor.execute(request, _ignore_state), executor.execute(request, _ignore_state)
    )
    assert first == replay
    assert first.error.code == "TASK_LOOP_CHECKS_FAILED"
    assert len(executor.agent.sessions) == 1
    assert len(executor.history(request.workflow_run_id, request.task_run_id)) == 1


async def test_conflicting_idempotency_key_or_attempt_id_never_runs_again() -> None:
    executor = MockTaskLoopExecutor()
    request = _request()
    await executor.execute(request, _ignore_state)
    for conflicting in (
        request.model_copy(update={"name": "Changed request"}),
        request.model_copy(update={"idempotency_key": "different-key"}),
    ):
        result = await executor.execute(conflicting, _ignore_state)
        assert result.error.code == "IDEMPOTENCY_CONFLICT"
        assert result.error.retryable is False
    assert len(executor.agent.sessions) == 1


async def test_changed_specification_and_script_are_rejected_between_iterations() -> None:
    executor = MockTaskLoopExecutor()
    request = _request()
    await executor.execute(request, _ignore_state)
    spec_changed = _next_attempt(request).model_copy(
        update={
            "input": {
                "namedInputs": {"task_loop_spec": _spec(specification="Changed objective").model_dump(mode="json")}
            }
        }
    )
    result = await executor.execute(spec_changed, _ignore_state)
    assert result.error.code == "TASK_LOOP_SPEC_CHANGED"
    script_changed = _next_attempt(request).model_copy(
        update={"metadata": {"resolved_configuration": {"mock_steps": [{"changes": {}}]}}}
    )
    result = await executor.execute(script_changed, _ignore_state)
    assert result.error.code == "TASK_LOOP_POLICY_CHANGED"
    assert len(executor.agent.sessions) == 1


async def test_stalled_candidate_stops_and_cannot_be_restarted_with_a_new_attempt() -> None:
    executor = MockTaskLoopExecutor()
    request = _request(metadata={"resolved_configuration": {"mock_steps": [{"changes": {}}]}})
    first = await executor.execute(request, _ignore_state)
    assert first.error.code == "TASK_LOOP_CHECKS_FAILED"
    second = await executor.execute(_next_attempt(request), _ignore_state)
    assert second.error.code == "TASK_LOOP_STALLED"
    assert second.error.retryable is False
    stopped = await executor.execute(_next_attempt(request), _ignore_state)
    assert stopped.error.code == "TASK_LOOP_STOPPED"
    assert len(executor.agent.sessions) == 2


async def test_complete_spec_is_never_truncated_to_fit_context_budget() -> None:
    executor = MockTaskLoopExecutor()
    request = _request(_spec(specification="Full specification " * 100, context_budget_chars=1024))
    result = await executor.execute(request, _ignore_state)
    assert result.error.code == "TASK_LOOP_CONTEXT_BUDGET_EXCEEDED"
    assert result.error.retryable is False
    assert executor.agent.sessions == []


async def test_history_reads_cannot_mutate_the_next_candidate() -> None:
    executor = MockTaskLoopExecutor()
    request = _request()
    await executor.execute(request, _ignore_state)
    history = executor.history(request.workflow_run_id, request.task_run_id)
    history[0].candidate.files["math_utils.py"] = "tampered"
    await executor.execute(_next_attempt(request), _ignore_state)
    current = executor.history(request.workflow_run_id, request.task_run_id)
    assert current[1].candidate.files["math_utils.py"] == "def add(a, b):\n    return a + b\n"
    assert current[1].candidate.parent_candidate_id == current[0].candidate.candidate_id


async def test_prior_transcripts_and_agent_notes_are_excluded_from_new_sessions() -> None:
    executor = MockTaskLoopExecutor()
    request = _request()
    await executor.execute(request, _ignore_state)
    await executor.execute(_next_attempt(request), _ignore_state)
    messages = [session.messages[0] for session in executor.agent.sessions]
    assert all("OLD_TRANSCRIPT_MUST_NOT_BE_FORWARDED" not in message for message in messages)
    assert all("TRACE_ONLY_ITERATION_ONE" not in message for message in messages)
    assert all(_spec().specification in json.loads(message)["specification"]["specification"] for message in messages)


async def test_missing_in_memory_checkpoint_never_silently_restarts_iteration_two() -> None:
    executor = MockTaskLoopExecutor()
    request = _request(context={"task_loop_iteration": 2})
    result = await executor.execute(request, _ignore_state)
    assert result.error.code == "TASK_LOOP_STATE_UNAVAILABLE"
    assert result.error.retryable is False
    assert executor.agent.sessions == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"acceptance_criteria": []},
        {"max_iterations": True},
        {"unexpected": "field"},
        {"initial_files": {"../outside": "bad"}},
    ],
)
async def test_invalid_spec_fails_before_starting_an_agent(overrides) -> None:
    payload = _spec().model_dump(mode="json")
    payload.update(overrides)
    executor = MockTaskLoopExecutor()
    result = await executor.execute(_request(input={"namedInputs": {"task_loop_spec": payload}}), _ignore_state)
    assert result.status is TaskResultStatus.FAILED
    assert result.error.code == "TASK_LOOP_INPUT_INVALID"
    assert executor.agent.sessions == []


def test_candidate_digest_is_checked() -> None:
    with pytest.raises(ValidationError, match="digest"):
        TaskLoopCandidate(
            candidate_id=uuid4(),
            parent_candidate_id=None,
            iteration=0,
            files={"a.txt": "changed"},
            content_digest=sha256_digest({"a.txt": "original"}),
        )


def test_separate_schemas_match_models_and_validate_the_fixture() -> None:
    for filename, model in MODELS.items():
        schema = json.loads((OUTPUT / filename).read_text(encoding="utf-8"))
        expected = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/task-loop/v0.1/{filename}",
            **model.model_json_schema(mode="validation"),
        }
        assert schema == expected
        Draft202012Validator.check_schema(schema)
    schema = json.loads((OUTPUT / "task-loop-spec.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(_spec().model_dump(mode="json"))


def test_mock_package_visibility_and_executor_route_require_opt_in(monkeypatch) -> None:
    settings = OpenCodeRuntimeSettings(enabled=False, source_repository=None, worktree_root=None, base_ref="HEAD")
    monkeypatch.setenv("ADLC_TASK_LOOP_MOCK_ENABLED", "false")
    reference = PackageReference(package_id="task-loop", version="0.1.0")
    assert TASK_LOOP_MOCK_SERVICE not in create_default_task_executor(settings).available_services
    assert not create_default_package_access_policy().can_view_package("owner", reference)
    monkeypatch.setenv("ADLC_TASK_LOOP_MOCK_ENABLED", "true")
    assert TASK_LOOP_MOCK_SERVICE in create_default_task_executor(settings).available_services
    assert create_default_package_access_policy().can_view_package("owner", reference)

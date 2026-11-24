from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from langflow.adlc.mock_adapters import MockAgentAdapter
from langflow.adlc.mock_workflow import (
    TASK_TRANSITIONS,
    WORKFLOW_TRANSITIONS,
    MockRunStateError,
    MockWorkflowService,
    mock_workflow_definition,
)
from langflow.adlc.models import (
    Actor,
    ApprovalDecisionCommand,
    ApprovalStatus,
    MockTaskKey,
    StartMockWorkflowRequest,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)


def _task(run, key: MockTaskKey):
    return next(task for task in run.tasks if task.key is key)


def _repository_root() -> Path:
    return Path(__file__).parents[4]


def _contract_validator(name: str) -> Draft202012Validator:
    schema = json.loads(
        (_repository_root() / "adlc-contracts" / "v0.1" / "execution-contract.schema.json").read_text(encoding="utf-8")
    )
    wrapped_schema = {
        "$schema": schema["$schema"],
        "$ref": f"#/$defs/{name}",
        "$defs": schema["$defs"],
    }
    return Draft202012Validator(wrapped_schema, format_checker=FormatChecker())


def test_runtime_transition_tables_match_the_frozen_v0_1_contract() -> None:
    machine = json.loads(
        (_repository_root() / "adlc-contracts" / "v0.1" / "state-machines.json").read_text(encoding="utf-8")
    )
    workflow_runtime = {
        source.value: {target.value for target in targets} for source, targets in WORKFLOW_TRANSITIONS.items()
    }
    task_runtime = {source.value: {target.value for target in targets} for source, targets in TASK_TRANSITIONS.items()}

    assert workflow_runtime == {
        source: set(targets) for source, targets in machine["workflow_run"]["transitions"].items()
    }
    assert task_runtime == {source: set(targets) for source, targets in machine["task_run"]["transitions"].items()}


def test_mock_workflow_definition_freezes_the_requested_dag() -> None:
    definition = mock_workflow_definition()
    dependencies = {task.key: task.dependencies for task in definition.tasks}

    assert [task.key for task in definition.tasks] == [
        MockTaskKey.PLAN,
        MockTaskKey.IMPLEMENT_BACKEND,
        MockTaskKey.IMPLEMENT_UI,
        MockTaskKey.VERIFY,
        MockTaskKey.APPROVAL,
    ]
    assert dependencies == {
        MockTaskKey.PLAN: [],
        MockTaskKey.IMPLEMENT_BACKEND: [MockTaskKey.PLAN],
        MockTaskKey.IMPLEMENT_UI: [MockTaskKey.PLAN],
        MockTaskKey.VERIFY: [MockTaskKey.IMPLEMENT_BACKEND, MockTaskKey.IMPLEMENT_UI],
        MockTaskKey.APPROVAL: [MockTaskKey.VERIFY],
    }
    assert all(task.executor == "mock" for task in definition.tasks)


async def test_successful_run_waits_for_approval_then_succeeds() -> None:
    service = MockWorkflowService()
    run = await service.start_run(StartMockWorkflowRequest(delayMs=0), owner_id="owner-1")

    assert run.execution_mode is WorkflowExecutionMode.MOCK_WORKFLOW
    assert run.events[0].payload["execution_mode"] == "MOCK_WORKFLOW"
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert [_task(run, key).status for key in MockTaskKey] == [
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.WAITING_APPROVAL,
    ]
    assert len(run.approval_requests) == 1
    assert run.approval_requests[0].status is ApprovalStatus.PENDING
    assert all(task.artifacts for task in run.tasks)
    assert all(task.executor.service == MockAgentAdapter.service_name for task in run.tasks)

    event_types = [event.event_type for event in run.events]
    backend_started = event_types.index("task_run.started", event_types.index("task_run.started") + 1)
    ui_started = event_types.index("task_run.started", backend_started + 1)
    first_branch_completed = min(
        index
        for index, event in enumerate(run.events)
        if event.event_type == "task_run.succeeded"
        and event.task_run_id
        in {
            _task(run, MockTaskKey.IMPLEMENT_BACKEND).id,
            _task(run, MockTaskKey.IMPLEMENT_UI).id,
        }
    )
    assert backend_started < first_branch_completed
    assert ui_started < first_branch_completed

    resolved = await service.resolve_approval(
        run.id,
        ApprovalDecisionCommand(action="APPROVE", comment="Mock output accepted."),
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1", display_name="Owner One"),
    )

    assert resolved.status is WorkflowRunStatus.SUCCEEDED
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in resolved.tasks)
    assert resolved.approval_requests[0].status is ApprovalStatus.APPROVED
    assert resolved.events[-1].event_type == "workflow_run.succeeded"
    assert [event.sequence for event in resolved.events] == list(range(1, len(resolved.events) + 1))
    assert len({event.event_id for event in resolved.events}) == len(resolved.events)

    with pytest.raises(MockRunStateError, match="not waiting for approval"):
        await service.resolve_approval(
            run.id,
            ApprovalDecisionCommand(action="APPROVE"),
            owner_id="owner-1",
            actor=Actor(type="USER", id="owner-1"),
        )


async def test_simulated_branch_failure_skips_dependents_and_fails_workflow() -> None:
    request = StartMockWorkflowRequest(
        simulateFailure=True,
        failureTask=MockTaskKey.IMPLEMENT_BACKEND,
        delayMs=0,
    )
    run = await MockWorkflowService().start_run(request, owner_id="owner-1")

    assert run.status is WorkflowRunStatus.FAILED
    assert _task(run, MockTaskKey.PLAN).status is TaskRunStatus.SUCCEEDED
    assert _task(run, MockTaskKey.IMPLEMENT_BACKEND).status is TaskRunStatus.FAILED
    assert _task(run, MockTaskKey.IMPLEMENT_UI).status is TaskRunStatus.SUCCEEDED
    assert _task(run, MockTaskKey.VERIFY).status is TaskRunStatus.SKIPPED
    assert _task(run, MockTaskKey.APPROVAL).status is TaskRunStatus.SKIPPED
    assert not run.approval_requests

    failure = _task(run, MockTaskKey.IMPLEMENT_BACKEND).result
    assert failure is not None
    assert failure.error is not None
    assert failure.error.code == "MOCK_EXECUTION_FAILED"
    assert failure.artifacts
    assert run.events[-1].event_type == "workflow_run.failed"


async def test_rejecting_approval_produces_contract_error_and_failed_run() -> None:
    service = MockWorkflowService()
    run = await service.start_run(StartMockWorkflowRequest(delayMs=0), owner_id="owner-1")

    rejected = await service.resolve_approval(
        run.id,
        ApprovalDecisionCommand(action="REJECT", comment="Needs revision."),
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
    )

    approval_task = _task(rejected, MockTaskKey.APPROVAL)
    assert rejected.status is WorkflowRunStatus.FAILED
    assert approval_task.status is TaskRunStatus.FAILED
    assert approval_task.result is not None
    assert approval_task.result.error is not None
    assert approval_task.result.error.code == "APPROVAL_REJECTED"
    assert rejected.approval_requests[0].status is ApprovalStatus.REJECTED
    assert rejected.events[-1].event_type == "workflow_run.failed"


async def test_emitted_contract_payloads_validate_against_v0_1() -> None:
    service = MockWorkflowService()
    run = await service.start_run(StartMockWorkflowRequest(delayMs=0), owner_id="owner-1")

    validators = {
        name: _contract_validator(name)
        for name in ("TaskRequest", "TaskResult", "RunEvent", "Artifact", "ApprovalRequest")
    }
    for task in run.tasks:
        assert task.request is not None
        validators["TaskRequest"].validate(task.request.model_dump(mode="json"))
        result = task.result or task.pending_result
        assert result is not None
        validators["TaskResult"].validate(result.model_dump(mode="json"))
        for artifact in task.artifacts:
            validators["Artifact"].validate(artifact.model_dump(mode="json"))
    for event in run.events:
        validators["RunEvent"].validate(event.model_dump(mode="json"))
    for approval in run.approval_requests:
        validators["ApprovalRequest"].validate(approval.model_dump(mode="json"))

    resolved = await service.resolve_approval(
        run.id,
        ApprovalDecisionCommand(action="APPROVE"),
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
    )
    validators["ApprovalRequest"].validate(resolved.approval_requests[0].model_dump(mode="json"))
    for event in resolved.events:
        validators["RunEvent"].validate(event.model_dump(mode="json"))

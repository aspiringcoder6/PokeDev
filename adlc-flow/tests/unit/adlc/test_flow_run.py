# ruff: noqa: INP001, S101

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.legacy_flow_normalizer import FlowDagValidationError, normalize_legacy_flow_graph
from langflow.adlc.mock_adapters import MockAgentAdapter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    AdlcTaskDefinition,
    ApprovalStatus,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    GateType,
    MockArtifactSpec,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)
from langflow.adlc.run_service import AdlcRunService, AdlcRunStateError


class _BlockingHarnessExecutor:
    service_name = "agent-provider:deepseek-harness"
    capabilities = ("harness:session",)

    def __init__(self) -> None:
        self.waiting = asyncio.Event()
        self.resume = asyncio.Event()
        self._delegate = MockExecutor()

    async def execute(self, request, on_state_change):
        await on_state_change(TaskRunStatus.RUNNING, None)
        await on_state_change(TaskRunStatus.WAITING_APPROVAL, None)
        self.waiting.set()
        await self.resume.wait()
        return await self._delegate.execute(request, on_state_change)


def _graph() -> dict:
    names = ["Plan", "Implement Backend", "Implement UI", "Verify", "Approval"]
    nodes = [
        {
            "id": name.lower().replace(" ", "_"),
            "type": "genericNode",
            "data": {
                "type": name.replace(" ", ""),
                "node": {"display_name": name},
                **({"adlc": {"kind": "approval"}} if name == "Approval" else {}),
            },
        }
        for name in names
    ]
    return {
        "nodes": nodes,
        "edges": [
            {"source": "plan", "target": "implement_backend"},
            {"source": "plan", "target": "implement_ui"},
            {"source": "implement_backend", "target": "verify"},
            {"source": "implement_ui", "target": "verify"},
            {"source": "verify", "target": "approval"},
        ],
    }


def test_saved_flow_graph_is_normalized_into_the_requested_dag() -> None:
    definitions = normalize_legacy_flow_graph(uuid4(), _graph())

    assert [definition.key for definition in definitions] == [
        "plan",
        "implement_backend",
        "implement_ui",
        "verify",
        "approval",
    ]
    assert {definition.key: definition.dependencies for definition in definitions} == {
        "plan": [],
        "implement_backend": ["plan"],
        "implement_ui": ["plan"],
        "verify": ["implement_backend", "implement_ui"],
        "approval": ["verify"],
    }
    assert definitions[-1].approval_gate is not None


def test_approval_name_and_component_type_do_not_create_a_gate() -> None:
    graph = _graph()
    graph["nodes"][-1]["data"].pop("adlc")

    definitions = normalize_legacy_flow_graph(uuid4(), graph)

    assert definitions[-1].name == "Approval"
    assert definitions[-1].approval_gate is None


@pytest.mark.parametrize(
    ("mode", "plan_id_marker", "message"),
    [
        ("EXECUTION_PLAN", None, "requires an execution plan id"),
        ("LEGACY_FLOW", "present", "Only EXECUTION_PLAN"),
        ("MOCK_WORKFLOW", None, "belongs to MockWorkflowService"),
    ],
)
async def test_run_service_rejects_mode_origin_mismatches(
    mode: str,
    plan_id_marker: str | None,
    message: str,
) -> None:
    flow_id = uuid4()
    with pytest.raises(AdlcRunStateError, match=message):
        await AdlcRunService().start_run(
            flow_id=flow_id,
            flow_name="Invalid mode origin",
            definitions=normalize_legacy_flow_graph(flow_id, _graph()),
            request=CreateWorkflowRunRequest(flowId=flow_id, executionMode=mode, delayMs=0),
            owner_id="owner-1",
            execution_plan_id=uuid4() if plan_id_marker else None,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda graph: graph["nodes"].append(graph["nodes"][0]), "duplicated"),
        (
            lambda graph: graph["edges"].append({"source": "missing", "target": "plan"}),
            "does not exist",
        ),
        (
            lambda graph: graph["edges"].append({"source": "approval", "target": "plan"}),
            "cycle",
        ),
    ],
)
def test_invalid_saved_flow_dags_are_rejected(mutate, message: str) -> None:
    graph = _graph()
    mutate(graph)

    with pytest.raises(FlowDagValidationError, match=message):
        normalize_legacy_flow_graph(uuid4(), graph)


async def test_flow_run_executes_parallel_tasks_and_finishes_after_approval() -> None:
    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Vertical Slice",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    assert run.flow_id == flow_id
    assert run.execution_mode is WorkflowExecutionMode.LEGACY_FLOW
    assert run.events[0].payload["execution_mode"] == "LEGACY_FLOW"
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert [task.status for task in run.tasks] == [
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.WAITING_APPROVAL,
    ]
    assert all(task.artifacts for task in run.tasks)
    assert all(task.executor.service == MockAgentAdapter.service_name for task in run.tasks)
    assert [event.sequence for event in run.events] == list(range(1, len(run.events) + 1))

    approval = run.approval_requests[0]
    resolved = await service.approve(
        approval.approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Ship it.",
    )

    assert resolved.status is WorkflowRunStatus.SUCCEEDED
    assert resolved.approval_requests[0].status is ApprovalStatus.APPROVED
    assert all(task.status is TaskRunStatus.SUCCEEDED for task in resolved.tasks)
    assert resolved.events[-1].event_type == "workflow_run.succeeded"


async def test_opencode_routed_task_can_reach_human_approval_without_a_control_executor() -> None:
    flow_id = uuid4()
    mock_agent = MockExecutor()
    router = TaskExecutorRouter(mock_agent, routes={"agent-provider:opencode": mock_agent})
    artifact = MockArtifactSpec(kind="SOURCE_PATCH", name="review.patch", media_type="text/plain", content="patch")
    definitions = [
        AdlcTaskDefinition(
            id=uuid4(),
            key="coding",
            name="Coding Agent (OpenCode)",
            task_type="IMPLEMENTATION",
            dependencies=[],
            predetermined_output={"summary": "Mocked OpenCode result"},
            artifact=artifact,
            executor_target=ExecutorTarget(service="agent-provider:opencode", operation="coding-task"),
        ),
        AdlcTaskDefinition(
            id=uuid4(),
            key="approval",
            name="Human Approval",
            task_type="APPROVAL",
            dependencies=["coding"],
            predetermined_output={},
            artifact=artifact,
            executor_target=ExecutorTarget(service="control:approval", operation="after-task"),
            approval_gate=GateType.ACTION,
        ),
    ]
    service = AdlcRunService(router)

    run = await service.start_run(
        flow_id=flow_id,
        flow_name="OpenCode approval regression",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    assert "control:approval" not in router.available_services
    assert run.status is WorkflowRunStatus.WAITING_APPROVAL
    assert [task.status for task in run.tasks] == [TaskRunStatus.SUCCEEDED, TaskRunStatus.WAITING_APPROVAL]
    assert run.approval_requests[0].context.artifact_refs[0]["artifact_id"] == str(
        run.tasks[0].artifacts[0].artifact_id
    )

    approved = await service.approve(
        run.approval_requests[0].approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Reviewed.",
    )

    assert approved.status is WorkflowRunStatus.SUCCEEDED


async def test_harness_run_starts_in_background_and_resumes_after_agent_interaction() -> None:
    flow_id = uuid4()
    executor = _BlockingHarnessExecutor()
    service = AdlcRunService(executor)
    definition = AdlcTaskDefinition(
        id=uuid4(),
        key="coding",
        name="Coding Agent (DeepSeek Harness)",
        task_type="IMPLEMENTATION",
        dependencies=[],
        predetermined_output={"summary": "Harness result"},
        artifact=MockArtifactSpec(
            kind="SOURCE_PATCH",
            name="harness.patch",
            media_type="text/plain",
            content="patch",
        ),
        executor_target=ExecutorTarget(
            service="agent-provider:deepseek-harness",
            operation="coding-task",
        ),
    )

    started = await service.start_run(
        flow_id=flow_id,
        flow_name="Harness HITL regression",
        definitions=[definition],
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    assert started.status is WorkflowRunStatus.RUNNING
    await asyncio.wait_for(executor.waiting.wait(), timeout=1)
    waiting = await service.get_run(started.id, owner_id="owner-1")
    assert waiting.status is WorkflowRunStatus.WAITING_APPROVAL
    assert waiting.tasks[0].status is TaskRunStatus.WAITING_APPROVAL
    assert waiting.approval_requests == []

    executor.resume.set()
    for _ in range(100):
        completed = await service.get_run(started.id, owner_id="owner-1")
        if completed.status is WorkflowRunStatus.SUCCEEDED:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("The background Harness run did not resume to completion.")

    assert completed.tasks[0].status is TaskRunStatus.SUCCEEDED
    await service.clear()


async def test_failed_mock_task_pauses_then_retry_unlocks_the_dag() -> None:
    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Retry Slice",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(
            flowId=flow_id,
            executionMode="LEGACY_FLOW",
            simulateFailure=True,
            failureTaskId="implement_backend",
            delayMs=0,
        ),
        owner_id="owner-1",
    )

    failed = next(task for task in run.tasks if task.key == "implement_backend")
    verify = next(task for task in run.tasks if task.key == "verify")
    assert run.status is WorkflowRunStatus.PAUSED
    assert failed.status is TaskRunStatus.FAILED
    assert verify.status is TaskRunStatus.PENDING

    retried = await service.retry_task(failed.id, owner_id="owner-1")

    retried_task = next(task for task in retried.tasks if task.id == failed.id)
    assert retried.status is WorkflowRunStatus.WAITING_APPROVAL
    assert retried_task.status is TaskRunStatus.SUCCEEDED
    assert retried_task.retry_count == 1
    assert any(event.event_type == "task_run.retry_requested" for event in retried.events)
    assert await service.get_tasks(retried.id, owner_id="owner-1")
    assert await service.get_events(retried.id, owner_id="owner-1")


async def test_rejecting_saved_flow_approval_fails_the_run() -> None:
    flow_id = uuid4()
    service = AdlcRunService()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Reject Slice",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )

    rejected = await service.reject(
        run.approval_requests[0].approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Needs changes.",
    )

    approval_task = rejected.tasks[-1]
    assert rejected.status is WorkflowRunStatus.FAILED
    assert rejected.approval_requests[0].status is ApprovalStatus.REJECTED
    assert approval_task.status is TaskRunStatus.FAILED
    assert approval_task.result is not None
    assert approval_task.result.error is not None
    assert approval_task.result.error.code == "APPROVAL_REJECTED"


async def test_list_runs_returns_owner_scoped_summaries_newest_first() -> None:
    flow_id = uuid4()
    other_flow_id = uuid4()
    service = AdlcRunService()
    first = await service.start_run(
        flow_id=flow_id,
        flow_name="History Slice One",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    second = await service.start_run(
        flow_id=flow_id,
        flow_name="History Slice Two",
        definitions=normalize_legacy_flow_graph(flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )
    await service.start_run(
        flow_id=other_flow_id,
        flow_name="Other Owner Slice",
        definitions=normalize_legacy_flow_graph(other_flow_id, _graph()),
        request=CreateWorkflowRunRequest(flowId=other_flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-2",
    )

    runs = await service.list_run_summaries(owner_id="owner-1")
    assert {run.id for run in runs} == {first.id, second.id}
    assert all(runs[index].created_at >= runs[index + 1].created_at for index in range(len(runs) - 1))
    for summary in runs:
        assert summary.name in {"History Slice One", "History Slice Two"}
        assert summary.status is WorkflowRunStatus.WAITING_APPROVAL
        assert summary.execution_mode is WorkflowExecutionMode.LEGACY_FLOW
        assert summary.flow_id == flow_id
        assert summary.task_total == 5
        assert summary.task_succeeded == 4
        assert summary.task_failed == 0
        assert summary.pending_approval is True

    other_owner_runs = await service.list_run_summaries(owner_id="owner-2")
    assert [run.name for run in other_owner_runs] == ["Other Owner Slice"]

    assert await service.list_run_summaries(owner_id="owner-1", flow_id=other_flow_id) == []
    assert await service.list_run_summaries(owner_id="owner-1", execution_plan_id=uuid4()) == []

    approved = await service.approve(
        first.approval_requests[0].approval_request_id,
        owner_id="owner-1",
        actor=Actor(type="USER", id="owner-1"),
        comment="Ship it.",
    )
    summaries = await service.list_run_summaries(owner_id="owner-1")
    approved_summary = next(run for run in summaries if run.id == approved.id)
    assert approved_summary.status is WorkflowRunStatus.SUCCEEDED
    assert approved_summary.completed_at is not None
    assert approved_summary.pending_approval is False
    assert approved_summary.task_succeeded == 5

"""In-memory coordinator for the first ADLC mock workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    ApprovalAction,
    ApprovalContext,
    ApprovalDecision,
    ApprovalDecisionCommand,
    ApprovalRequest,
    ApprovalStatus,
    ExecutorTarget,
    GateType,
    MockArtifactSpec,
    MockTaskDefinition,
    MockTaskKey,
    MockWorkflowDefinition,
    RunEvent,
    ServiceError,
    StartMockWorkflowRequest,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunStatus,
)

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import TaskExecutor

WORKFLOW_TRANSITIONS: dict[WorkflowRunStatus, frozenset[WorkflowRunStatus]] = {
    WorkflowRunStatus.CREATED: frozenset(
        {WorkflowRunStatus.QUEUED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
    ),
    WorkflowRunStatus.QUEUED: frozenset(
        {
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        }
    ),
    WorkflowRunStatus.RUNNING: frozenset(
        {
            WorkflowRunStatus.PAUSED,
            WorkflowRunStatus.WAITING_APPROVAL,
            WorkflowRunStatus.SUCCEEDED,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.CANCELLED,
        }
    ),
    WorkflowRunStatus.PAUSED: frozenset(
        {WorkflowRunStatus.QUEUED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
    ),
    WorkflowRunStatus.WAITING_APPROVAL: frozenset(
        {WorkflowRunStatus.QUEUED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
    ),
    WorkflowRunStatus.SUCCEEDED: frozenset(),
    WorkflowRunStatus.FAILED: frozenset(),
    WorkflowRunStatus.CANCELLED: frozenset(),
}

TASK_TRANSITIONS: dict[TaskRunStatus, frozenset[TaskRunStatus]] = {
    TaskRunStatus.PENDING: frozenset(
        {TaskRunStatus.READY, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED, TaskRunStatus.SKIPPED}
    ),
    TaskRunStatus.READY: frozenset(
        {TaskRunStatus.RUNNING, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED, TaskRunStatus.SKIPPED}
    ),
    TaskRunStatus.RUNNING: frozenset(
        {
            TaskRunStatus.READY,
            TaskRunStatus.WAITING_APPROVAL,
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }
    ),
    TaskRunStatus.WAITING_APPROVAL: frozenset(
        {
            TaskRunStatus.READY,
            TaskRunStatus.RUNNING,
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }
    ),
    TaskRunStatus.SUCCEEDED: frozenset(),
    TaskRunStatus.FAILED: frozenset({TaskRunStatus.READY}),
    TaskRunStatus.CANCELLED: frozenset(),
    TaskRunStatus.SKIPPED: frozenset(),
}

WORKFLOW_EVENT_TYPES = {
    WorkflowRunStatus.CREATED: "workflow_run.created",
    WorkflowRunStatus.QUEUED: "workflow_run.queued",
    WorkflowRunStatus.RUNNING: "workflow_run.started",
    WorkflowRunStatus.PAUSED: "workflow_run.paused",
    WorkflowRunStatus.WAITING_APPROVAL: "workflow_run.waiting_approval",
    WorkflowRunStatus.SUCCEEDED: "workflow_run.succeeded",
    WorkflowRunStatus.FAILED: "workflow_run.failed",
    WorkflowRunStatus.CANCELLED: "workflow_run.cancelled",
}

TASK_EVENT_TYPES = {
    TaskRunStatus.PENDING: "task_run.created",
    TaskRunStatus.READY: "task_run.ready",
    TaskRunStatus.RUNNING: "task_run.started",
    TaskRunStatus.WAITING_APPROVAL: "task_run.waiting_approval",
    TaskRunStatus.SUCCEEDED: "task_run.succeeded",
    TaskRunStatus.FAILED: "task_run.failed",
    TaskRunStatus.CANCELLED: "task_run.cancelled",
    TaskRunStatus.SKIPPED: "task_run.skipped",
}

SYSTEM_ACTOR = Actor(type="SYSTEM", id="mock-run-coordinator", display_name="Mock Run Coordinator")


class MockRunNotFoundError(LookupError):
    """The requested mock run is absent or belongs to another user."""


class MockRunStateError(RuntimeError):
    """The command does not apply to the run's current state."""


@dataclass
class _StoredRun:
    owner_id: str
    run: WorkflowRun


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def mock_workflow_definition() -> MockWorkflowDefinition:
    """Return the frozen five-task mock graph used by the vertical slice."""

    def definition_id(key: MockTaskKey) -> UUID:
        return uuid5(NAMESPACE_URL, f"adlc:mock-workflow:v0.1:{key.value}")

    return MockWorkflowDefinition(
        tasks=[
            MockTaskDefinition(
                id=definition_id(MockTaskKey.PLAN),
                key=MockTaskKey.PLAN,
                name="Plan",
                task_type="mock.plan",
                dependencies=[],
                predetermined_output={
                    "summary": "Implementation plan prepared.",
                    "workstreams": ["backend", "ui"],
                },
                artifact=MockArtifactSpec(
                    kind="DOCUMENT",
                    name="implementation-plan.md",
                    media_type="text/markdown",
                    content="# Mock implementation plan\n\nImplement backend and UI in parallel.",
                ),
            ),
            MockTaskDefinition(
                id=definition_id(MockTaskKey.IMPLEMENT_BACKEND),
                key=MockTaskKey.IMPLEMENT_BACKEND,
                name="Implement Backend",
                task_type="mock.implement_backend",
                dependencies=[MockTaskKey.PLAN],
                predetermined_output={"summary": "Mock backend implementation completed.", "files_changed": 3},
                artifact=MockArtifactSpec(
                    kind="SOURCE_PATCH",
                    name="backend.patch",
                    media_type="text/x-diff",
                    content="diff --git a/backend.py b/backend.py\n+mock backend implementation\n",
                ),
            ),
            MockTaskDefinition(
                id=definition_id(MockTaskKey.IMPLEMENT_UI),
                key=MockTaskKey.IMPLEMENT_UI,
                name="Implement UI",
                task_type="mock.implement_ui",
                dependencies=[MockTaskKey.PLAN],
                predetermined_output={"summary": "Mock UI implementation completed.", "files_changed": 4},
                artifact=MockArtifactSpec(
                    kind="SOURCE_PATCH",
                    name="ui.patch",
                    media_type="text/x-diff",
                    content="diff --git a/RunBoard.tsx b/RunBoard.tsx\n+mock UI implementation\n",
                ),
            ),
            MockTaskDefinition(
                id=definition_id(MockTaskKey.VERIFY),
                key=MockTaskKey.VERIFY,
                name="Verify",
                task_type="mock.verify",
                dependencies=[MockTaskKey.IMPLEMENT_BACKEND, MockTaskKey.IMPLEMENT_UI],
                predetermined_output={
                    "summary": "Mock verification passed.",
                    "checks": {"backend": True, "ui": True},
                },
                artifact=MockArtifactSpec(
                    kind="TEST_REPORT",
                    name="verification-report.json",
                    media_type="application/json",
                    content='{"backend": "passed", "ui": "passed"}',
                ),
            ),
            MockTaskDefinition(
                id=definition_id(MockTaskKey.APPROVAL),
                key=MockTaskKey.APPROVAL,
                name="Approval",
                task_type="mock.approval",
                dependencies=[MockTaskKey.VERIFY],
                predetermined_output={"summary": "Mock release candidate is ready for approval."},
                artifact=MockArtifactSpec(
                    kind="DOCUMENT",
                    name="approval-summary.md",
                    media_type="text/markdown",
                    content="# Approval summary\n\nThe mock release candidate passed verification.",
                ),
                approval_gate=GateType.AFTER_TASK,
            ),
        ]
    )


class MockWorkflowService:
    """Run the mock DAG and retain snapshots in process memory.

    This repository is intentionally ephemeral. Its API mirrors the future
    coordinator boundary while database persistence remains a separate task.
    """

    def __init__(self, executor: TaskExecutor | None = None) -> None:
        self._executor = executor or MockExecutor()
        self._runs: dict[UUID, _StoredRun] = {}
        self._mutation_lock = asyncio.Lock()

    def get_definition(self) -> MockWorkflowDefinition:
        return mock_workflow_definition()

    async def start_run(self, request: StartMockWorkflowRequest, *, owner_id: str) -> WorkflowRun:
        run, definitions = self._create_run(request)
        async with self._mutation_lock:
            self._runs[run.id] = _StoredRun(owner_id=owner_id, run=run)

        self._transition_workflow(run, WorkflowRunStatus.QUEUED)
        self._transition_workflow(run, WorkflowRunStatus.RUNNING)
        await self._schedule(run, definitions, delay_ms=request.delay_ms)
        return run.model_copy(deep=True)

    async def get_run(self, run_id: UUID, *, owner_id: str) -> WorkflowRun:
        record = self._owned_run(run_id, owner_id)
        return record.run.model_copy(deep=True)

    async def get_events(self, run_id: UUID, *, owner_id: str) -> list[RunEvent]:
        record = self._owned_run(run_id, owner_id)
        return [event.model_copy(deep=True) for event in record.run.events]

    async def resolve_approval(
        self,
        run_id: UUID,
        command: ApprovalDecisionCommand,
        *,
        owner_id: str,
        actor: Actor,
    ) -> WorkflowRun:
        async with self._mutation_lock:
            record = self._owned_run(run_id, owner_id)
            run = record.run
            if run.status is not WorkflowRunStatus.WAITING_APPROVAL:
                raise MockRunStateError("The workflow run is not waiting for approval.")

            approval = next(
                (item for item in run.approval_requests if item.status is ApprovalStatus.PENDING),
                None,
            )
            if approval is None:
                raise MockRunStateError("The workflow run has no pending approval request.")

            task = self._task_by_id(run, approval.task_run_id)
            if task.status is not TaskRunStatus.WAITING_APPROVAL or task.pending_result is None:
                raise MockRunStateError("The approval task has no pending result to resolve.")

            if command.action == "APPROVE":
                self._approve(run, task, approval, command, actor)
            else:
                self._reject(run, task, approval, command, actor)
            return run.model_copy(deep=True)

    async def clear(self) -> None:
        """Reset ephemeral state; intended for tests and local demos."""
        async with self._mutation_lock:
            self._runs.clear()

    def _create_run(
        self,
        request: StartMockWorkflowRequest,
    ) -> tuple[WorkflowRun, dict[MockTaskKey, MockTaskDefinition]]:
        now = utc_now()
        run_id = uuid4()
        definition = mock_workflow_definition()
        definitions = {task.key: task for task in definition.tasks}
        task_ids = {key: uuid4() for key in definitions}
        tasks = [
            TaskRun(
                id=task_ids[item.key],
                workflow_run_id=run_id,
                task_definition_id=item.id,
                key=item.key,
                name=item.name,
                task_type=item.task_type,
                status=TaskRunStatus.PENDING,
                dependency_task_run_ids=[task_ids[key] for key in item.dependencies],
                executor=ExecutorTarget(
                    service=self._executor.service_name,
                    operation=item.key.value,
                    capabilities=list(self._executor.capabilities),
                ),
                simulate_failure=request.simulate_failure and request.failure_task is item.key,
            )
            for item in definition.tasks
        ]
        run = WorkflowRun(
            id=run_id,
            workflow_key=definition.key,
            execution_mode=WorkflowExecutionMode.MOCK_WORKFLOW,
            name=definition.name,
            status=WorkflowRunStatus.CREATED,
            tasks=tasks,
            created_at=now,
        )
        self._emit_workflow_event(
            run,
            previous_status=None,
            payload={"mock": True, "execution_mode": WorkflowExecutionMode.MOCK_WORKFLOW.value},
        )
        for task in run.tasks:
            self._emit_task_event(run, task, previous_status=None, payload={"task_key": task.key.value})
        return run, definitions

    async def _schedule(
        self,
        run: WorkflowRun,
        definitions: dict[MockTaskKey, MockTaskDefinition],
        *,
        delay_ms: int,
    ) -> None:
        while True:
            self._skip_blocked_tasks(run)
            ready = [task for task in run.tasks if self._is_ready(run, task)]
            if not ready:
                break

            for task in ready:
                self._transition_task(run, task, TaskRunStatus.READY)
            await asyncio.gather(
                *(self._execute_task(run, task, definitions[task.key], delay_ms=delay_ms) for task in ready)
            )

        if any(task.status is TaskRunStatus.FAILED for task in run.tasks):
            failed_keys = [task.key.value for task in run.tasks if task.status is TaskRunStatus.FAILED]
            self._transition_workflow(run, WorkflowRunStatus.FAILED, payload={"failed_tasks": failed_keys})
        elif any(task.status is TaskRunStatus.WAITING_APPROVAL for task in run.tasks):
            self._transition_workflow(run, WorkflowRunStatus.WAITING_APPROVAL)
        elif all(task.status in {TaskRunStatus.SUCCEEDED, TaskRunStatus.SKIPPED} for task in run.tasks):
            self._transition_workflow(run, WorkflowRunStatus.SUCCEEDED)
        else:
            raise MockRunStateError("The mock scheduler reached a non-terminal deadlock.")

    def _skip_blocked_tasks(self, run: WorkflowRun) -> None:
        blocking_states = {TaskRunStatus.FAILED, TaskRunStatus.CANCELLED, TaskRunStatus.SKIPPED}
        for task in run.tasks:
            if task.status is not TaskRunStatus.PENDING:
                continue
            dependencies = [self._task_by_id(run, dependency_id) for dependency_id in task.dependency_task_run_ids]
            blocked_by = [dependency for dependency in dependencies if dependency.status in blocking_states]
            if blocked_by:
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.SKIPPED,
                    payload={"blocked_by": [item.key.value for item in blocked_by]},
                )

    def _is_ready(self, run: WorkflowRun, task: TaskRun) -> bool:
        if task.status is not TaskRunStatus.PENDING:
            return False
        dependencies = [self._task_by_id(run, dependency_id) for dependency_id in task.dependency_task_run_ids]
        return all(dependency.status is TaskRunStatus.SUCCEEDED for dependency in dependencies)

    async def _execute_task(
        self,
        run: WorkflowRun,
        task: TaskRun,
        definition: MockTaskDefinition,
        *,
        delay_ms: int,
    ) -> None:
        attempt_id = uuid4()
        task.current_attempt_id = attempt_id
        request = TaskRequest(
            request_id=uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
            task_definition_id=task.task_definition_id,
            task_type=task.task_type,
            name=task.name,
            executor=task.executor,
            input={
                "taskKey": task.key.value,
                "simulateFailure": task.simulate_failure,
                "delayMs": delay_ms,
                "predeterminedResult": definition.predetermined_output,
                "artifact": {
                    "kind": definition.artifact.kind,
                    "name": definition.artifact.name,
                    "mediaType": definition.artifact.media_type,
                    "content": definition.artifact.content,
                },
            },
            context={
                "artifact_refs": [],
                "memory_refs": [],
                "variables": {"mock": True},
            },
            dependency_task_run_ids=task.dependency_task_run_ids,
            constraints={"timeout_ms": max(1000, delay_ms + 500), "priority": 50, "max_attempts": 1},
            idempotency_key=f"{run.id}:{task.id}:{attempt_id}",
            requested_at=utc_now(),
            trace_context={},
            metadata={"mock": True},
        )
        task.request = request

        async def on_state_change(status: TaskRunStatus, result: TaskResult | None) -> None:
            self._on_executor_state(run, task, definition, status, result)

        await self._executor.execute(request, on_state_change)

    def _on_executor_state(
        self,
        run: WorkflowRun,
        task: TaskRun,
        definition: MockTaskDefinition,
        status: TaskRunStatus,
        result: TaskResult | None,
    ) -> None:
        if status is TaskRunStatus.RUNNING:
            self._transition_task(run, task, status)
            return
        if result is None:
            raise MockRunStateError(f"The executor emitted {status.value} without a TaskResult.")

        task.artifacts = [artifact.model_copy(deep=True) for artifact in result.artifacts]
        if status is TaskRunStatus.SUCCEEDED and definition.approval_gate is GateType.AFTER_TASK:
            task.pending_result = result
            approval = self._create_approval(run, task)
            self._transition_task(
                run,
                task,
                TaskRunStatus.WAITING_APPROVAL,
                payload={"approval_request_id": str(approval.approval_request_id)},
            )
            return

        task.result = result
        self._transition_task(
            run,
            task,
            status,
            payload={
                "request_id": str(result.request_id),
                "artifact_ids": [str(artifact.artifact_id) for artifact in result.artifacts],
                **({"error_code": result.error.code} if result.error else {}),
            },
        )

    def _create_approval(self, run: WorkflowRun, task: TaskRun) -> ApprovalRequest:
        if task.current_attempt_id is None:
            raise MockRunStateError("Cannot create approval without a task attempt.")
        if any(item.status is ApprovalStatus.PENDING for item in run.approval_requests):
            raise MockRunStateError("Only one pending blocking approval is allowed per mock run.")

        approval = ApprovalRequest(
            approval_request_id=uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id,
            gate_type=GateType.AFTER_TASK,
            status=ApprovalStatus.PENDING,
            title="Approve the mock workflow result",
            requested_by=SYSTEM_ACTOR,
            required_role="maintainer",
            reviewer_ids=[],
            actions=[
                ApprovalAction(
                    action_id="approve",
                    label="Approve workflow",
                    effect="APPROVE",
                    comment_required=False,
                ),
                ApprovalAction(
                    action_id="reject",
                    label="Reject workflow",
                    effect="REJECT",
                    comment_required=True,
                ),
            ],
            context=ApprovalContext(
                summary="Plan, backend, UI, and verification mock tasks completed successfully.",
                risk="This is deterministic mock data and does not represent a real deployment.",
                requested_action="Approve or reject the mock workflow outcome.",
                artifact_refs=[
                    {
                        "artifact_id": str(artifact.artifact_id),
                        "name": artifact.name,
                        "media_type": artifact.media_type,
                        "uri": artifact.uri,
                    }
                    for artifact in task.artifacts
                ],
                payload={"task_key": task.key.value},
            ),
            decision=None,
            created_at=utc_now(),
            metadata={"mock": True},
        )
        run.approval_requests.append(approval)
        self._emit_approval_event(run, approval, previous_status=None, event_type="approval_request.created")
        return approval

    def _approve(
        self,
        run: WorkflowRun,
        task: TaskRun,
        approval: ApprovalRequest,
        command: ApprovalDecisionCommand,
        actor: Actor,
    ) -> None:
        now = utc_now()
        approval.status = ApprovalStatus.APPROVED
        approval.decision = ApprovalDecision(
            action_id="approve",
            effect="APPROVE",
            decided_by=actor,
            comment=command.comment,
            decided_at=now,
        )
        self._emit_approval_event(
            run,
            approval,
            previous_status=ApprovalStatus.PENDING,
            event_type="approval_request.approved",
            actor=actor,
        )
        task.result = task.pending_result
        task.pending_result = None
        self._transition_task(
            run,
            task,
            TaskRunStatus.SUCCEEDED,
            payload={"approval_request_id": str(approval.approval_request_id)},
        )
        self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload={"reason": "approval_resolved"})
        self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload={"reason": "approval_reconciled"})
        self._transition_workflow(run, WorkflowRunStatus.SUCCEEDED)

    def _reject(
        self,
        run: WorkflowRun,
        task: TaskRun,
        approval: ApprovalRequest,
        command: ApprovalDecisionCommand,
        actor: Actor,
    ) -> None:
        now = utc_now()
        approval.status = ApprovalStatus.REJECTED
        approval.decision = ApprovalDecision(
            action_id="reject",
            effect="REJECT",
            decided_by=actor,
            comment=command.comment,
            decided_at=now,
        )
        self._emit_approval_event(
            run,
            approval,
            previous_status=ApprovalStatus.PENDING,
            event_type="approval_request.rejected",
            actor=actor,
        )

        pending_result = task.pending_result
        if pending_result is None:
            raise MockRunStateError("Cannot reject an approval without a pending task result.")
        error = ServiceError(
            error_id=uuid4(),
            code="APPROVAL_REJECTED",
            category="AUTHORIZATION",
            message="The reviewer rejected the mock workflow result.",
            retryable=False,
            service="mock-run-coordinator",
            details={"approval_request_id": str(approval.approval_request_id)},
            correlation_id=f"run-{run.id}/task-{task.id}",
            occurred_at=now,
        )
        task.result = TaskResult(
            request_id=pending_result.request_id,
            workflow_run_id=pending_result.workflow_run_id,
            task_run_id=pending_result.task_run_id,
            attempt_id=pending_result.attempt_id,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=pending_result.artifacts,
            error=error,
            metrics=pending_result.metrics,
            started_at=pending_result.started_at,
            completed_at=now,
            metadata={"mock": True, "approval_rejected": True},
        )
        task.pending_result = None
        self._transition_task(
            run,
            task,
            TaskRunStatus.FAILED,
            payload={
                "approval_request_id": str(approval.approval_request_id),
                "error_code": error.code,
            },
        )
        self._transition_workflow(
            run,
            WorkflowRunStatus.FAILED,
            payload={"approval_request_id": str(approval.approval_request_id)},
        )

    def _transition_workflow(
        self,
        run: WorkflowRun,
        status: WorkflowRunStatus,
        *,
        payload: dict | None = None,
    ) -> None:
        previous_status = run.status
        if status not in WORKFLOW_TRANSITIONS[previous_status]:
            raise MockRunStateError(f"Invalid WorkflowRun transition: {previous_status.value} -> {status.value}")
        run.status = status
        if status in {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}:
            run.completed_at = utc_now()
        self._emit_workflow_event(run, previous_status=previous_status, payload=payload or {})

    def _transition_task(
        self,
        run: WorkflowRun,
        task: TaskRun,
        status: TaskRunStatus,
        *,
        payload: dict | None = None,
    ) -> None:
        previous_status = task.status
        if status not in TASK_TRANSITIONS[previous_status]:
            raise MockRunStateError(f"Invalid TaskRun transition: {previous_status.value} -> {status.value}")
        task.status = status
        if status is TaskRunStatus.RUNNING and task.started_at is None:
            task.started_at = utc_now()
        if status in {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
            TaskRunStatus.SKIPPED,
        }:
            task.completed_at = utc_now()
        self._emit_task_event(run, task, previous_status=previous_status, payload=payload or {})

    def _emit_workflow_event(
        self,
        run: WorkflowRun,
        *,
        previous_status: WorkflowRunStatus | None,
        payload: dict,
    ) -> None:
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=WORKFLOW_EVENT_TYPES[run.status],
                workflow_run_id=run.id,
                aggregate_type="WORKFLOW_RUN",
                aggregate_id=run.id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=run.status.value,
                actor=SYSTEM_ACTOR,
                correlation_id=f"run-{run.id}",
                occurred_at=utc_now(),
                producer="mock-run-coordinator",
                payload=payload,
            )
        )

    def _emit_task_event(
        self,
        run: WorkflowRun,
        task: TaskRun,
        *,
        previous_status: TaskRunStatus | None,
        payload: dict,
    ) -> None:
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=TASK_EVENT_TYPES[task.status],
                workflow_run_id=run.id,
                task_run_id=task.id,
                attempt_id=task.current_attempt_id,
                aggregate_type="TASK_RUN",
                aggregate_id=task.id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=task.status.value,
                actor=SYSTEM_ACTOR,
                correlation_id=f"run-{run.id}/task-{task.id}",
                occurred_at=utc_now(),
                producer="mock-run-coordinator",
                payload=payload,
            )
        )

    def _emit_approval_event(
        self,
        run: WorkflowRun,
        approval: ApprovalRequest,
        *,
        previous_status: ApprovalStatus | None,
        event_type: str,
        actor: Actor = SYSTEM_ACTOR,
    ) -> None:
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=event_type,
                workflow_run_id=run.id,
                task_run_id=approval.task_run_id,
                attempt_id=approval.attempt_id,
                approval_request_id=approval.approval_request_id,
                aggregate_type="APPROVAL_REQUEST",
                aggregate_id=approval.approval_request_id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=approval.status.value,
                actor=actor,
                correlation_id=f"run-{run.id}/approval-{approval.approval_request_id}",
                occurred_at=utc_now(),
                producer="mock-run-coordinator",
                payload={"gate_type": approval.gate_type.value},
            )
        )

    def _owned_run(self, run_id: UUID, owner_id: str) -> _StoredRun:
        record = self._runs.get(run_id)
        if record is None or record.owner_id != owner_id:
            raise MockRunNotFoundError(f"Mock workflow run {run_id} was not found.")
        return record

    @staticmethod
    def _task_by_id(run: WorkflowRun, task_id: UUID) -> TaskRun:
        task = next((item for item in run.tasks if item.id == task_id), None)
        if task is None:
            raise MockRunStateError(f"Task run {task_id} does not belong to workflow run {run.id}.")
        return task

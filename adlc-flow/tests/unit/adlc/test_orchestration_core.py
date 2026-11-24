# ruff: noqa: PLR2004, S101

"""Task orchestration core: dependency resolution, retry identity, attempt history, quality gate."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    AdlcTaskDefinition,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    Checksum,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    MockArtifactSpec,
    ServiceError,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunStatus,
)
from langflow.adlc.quality_gate import (
    MockReviewService,
    QualityGateDecision,
    QualityGatePolicy,
    ReviewDecision,
    ReviewOutcome,
    evaluate_quality_gate,
)
from langflow.adlc.run_service import AdlcRunService, AdlcRunStateError, _StoredRun

FIXED_TIME = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Runtime fixtures (real coordinator + mock executor)
# ---------------------------------------------------------------------------


def _definition(key: str, *, dependencies: list[str] | None = None, **overrides) -> AdlcTaskDefinition:
    payload: dict = {
        "id": uuid4(),
        "key": key,
        "name": key.replace("-", " ").title(),
        "task_type": "IMPLEMENTATION",
        "dependencies": dependencies or [],
        "predetermined_output": {"summary": f"Mock result for {key}."},
        "artifact": MockArtifactSpec(
            kind="DOCUMENT",
            name=f"{key}.txt",
            media_type="text/plain",
            content=f"Mock artifact for {key}.",
        ),
        "delay_ms": 0,
    }
    payload.update(overrides)
    return AdlcTaskDefinition(**payload)


async def _start_run(service: AdlcRunService, definitions: list[AdlcTaskDefinition]) -> WorkflowRun:
    return await service.start_run(
        flow_id=uuid4(),
        flow_name="Orchestration core fixture",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=uuid4(), executionMode="LEGACY_FLOW", delayMs=0),
        owner_id="owner-1",
    )


async def test_retry_preserves_identity_and_creates_new_attempt_and_request() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("analyze"),
            _definition("implement", dependencies=["analyze"], simulate_failure=True),
        ],
    )
    assert run.status is WorkflowRunStatus.PAUSED
    failed = next(item for item in run.tasks if item.key == "implement")
    analyze_before = next(item for item in run.tasks if item.key == "analyze")
    first_attempt_id = failed.current_attempt_id
    first_request_id = failed.request.request_id
    assert failed.retry_count == 0

    retried = await service.retry_task(failed.id, owner_id="owner-1")
    assert retried.status is WorkflowRunStatus.SUCCEEDED
    task = next(item for item in retried.tasks if item.key == "implement")
    analyze_after = next(item for item in retried.tasks if item.key == "analyze")

    assert task.status is TaskRunStatus.SUCCEEDED
    assert task.retry_count == 1
    assert task.id == failed.id
    assert task.workflow_run_id == failed.workflow_run_id
    assert task.task_definition_id == failed.task_definition_id
    assert task.current_attempt_id != first_attempt_id
    assert task.request.request_id != first_request_id
    assert task.request.attempt_id == task.current_attempt_id
    assert task.request.task_run_id == failed.id
    assert analyze_after.id == analyze_before.id
    assert analyze_after.status is TaskRunStatus.SUCCEEDED


async def test_retry_limit_exhausted_keeps_task_failed() -> None:
    service = AdlcRunService(MockExecutor())
    run = await _start_run(
        service,
        [
            _definition("analyze"),
            _definition(
                "implement",
                dependencies=["analyze"],
                simulate_failure=True,
                constraints={"max_attempts": 1},
            ),
        ],
    )
    task = next(item for item in run.tasks if item.key == "implement")
    assert task.status is TaskRunStatus.FAILED
    assert run.status is WorkflowRunStatus.PAUSED

    with pytest.raises(AdlcRunStateError, match="exhausted"):
        await service.retry_task(task.id, owner_id="owner-1")

    after = await service.get_run(run.id, owner_id="owner-1")
    assert next(item for item in after.tasks if item.key == "implement").status is TaskRunStatus.FAILED
    assert after.status is WorkflowRunStatus.PAUSED


def test_ready_requires_satisfied_dependency_conditions() -> None:
    service = AdlcRunService(MockExecutor())
    run_id = uuid4()
    upstream_id = uuid4()
    downstream = TaskRun(
        id=uuid4(),
        workflow_run_id=run_id,
        task_definition_id=uuid4(),
        key="downstream",
        name="Downstream",
        task_type="IMPLEMENTATION",
        status=TaskRunStatus.PENDING,
        dependency_task_run_ids=[upstream_id],
        executor=ExecutorTarget(service="mock", operation="downstream"),
    )
    upstream = TaskRun(
        id=upstream_id,
        workflow_run_id=run_id,
        task_definition_id=uuid4(),
        key="upstream",
        name="Upstream",
        task_type="IMPLEMENTATION",
        status=TaskRunStatus.SUCCEEDED,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service="mock", operation="upstream"),
    )

    def _run(tasks: list[TaskRun]) -> WorkflowRun:
        return WorkflowRun(
            id=run_id,
            workflow_key="ready-fixture",
            execution_mode=WorkflowExecutionMode.LEGACY_FLOW,
            flow_id=uuid4(),
            name="Ready fixture",
            status=WorkflowRunStatus.RUNNING,
            tasks=tasks,
            approval_requests=[],
            created_at=FIXED_TIME,
        )

    def _ready(tasks: list[TaskRun], task: TaskRun) -> bool:
        run = _run(tasks)
        record = _StoredRun(owner_id="owner-1", run=run, definitions={}, delay_ms=0)
        return service._is_ready(record, run, task)

    assert _ready([upstream, downstream], downstream)

    running_task = downstream.model_copy(update={"status": TaskRunStatus.RUNNING})
    assert not _ready([upstream, running_task], running_task)

    failed_upstream = upstream.model_copy(update={"status": TaskRunStatus.FAILED})
    assert not _ready([failed_upstream, downstream], downstream)


# ---------------------------------------------------------------------------
# Quality gate fixtures (synthetic terminal evidence)
# ---------------------------------------------------------------------------


def _artifact(task: TaskRun) -> Artifact:
    content = f"Artifact for {task.key}".encode("utf-8")
    return Artifact(
        artifact_id=uuid4(),
        workflow_run_id=task.workflow_run_id,
        task_run_id=task.id,
        attempt_id=task.current_attempt_id or uuid4(),
        kind="TEST_REPORT",
        name=f"{task.key}-report.txt",
        media_type="text/plain",
        uri=f"mock://artifacts/{task.key}",
        size_bytes=len(content),
        checksum=Checksum(value=hashlib.sha256(content).hexdigest()),
        producer="mock-agent-adapter",
        created_at=FIXED_TIME,
        metadata={},
    )


def _task(*, task_type: str, status: TaskRunStatus, retry_count: int = 0) -> TaskRun:
    return TaskRun(
        id=uuid4(),
        workflow_run_id=uuid4(),
        task_definition_id=uuid4(),
        key=task_type.lower(),
        name=task_type.title(),
        task_type=task_type,
        status=status,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service="mock", operation=task_type.lower()),
        retry_count=retry_count,
        artifacts=[],
    )


def _completed(task: TaskRun, *, result: TaskResult | None = None, with_artifact: bool = True) -> TaskRun:
    completed = task.model_copy(
        update={
            "status": TaskRunStatus.SUCCEEDED,
            "result": result,
            "completed_at": FIXED_TIME,
        }
    )
    if with_artifact:
        completed = completed.model_copy(update={"artifacts": [_artifact(completed)]})
    return completed


def _succeeded_result(
    task: TaskRun,
    *,
    output: dict | None = None,
    testing: str | None = "PASSED",
) -> TaskResult:
    metadata = {"testing": {"adapter": "mock-testing-adapter", "outcome": testing}} if testing else {}
    return TaskResult(
        request_id=uuid4(),
        workflow_run_id=task.workflow_run_id,
        task_run_id=task.id,
        attempt_id=task.current_attempt_id or uuid4(),
        status=TaskResultStatus.SUCCEEDED,
        output=output if output is not None else {"outputs": {"source_patch": "mock://patch"}},
        artifacts=[],
        error=None,
        started_at=FIXED_TIME,
        completed_at=FIXED_TIME,
        metadata=metadata,
    )


def _failed_result(task: TaskRun) -> TaskResult:
    return TaskResult(
        request_id=uuid4(),
        workflow_run_id=task.workflow_run_id,
        task_run_id=task.id,
        attempt_id=task.current_attempt_id or uuid4(),
        status=TaskResultStatus.FAILED,
        output=None,
        artifacts=[],
        error=ServiceError(
            error_id=uuid4(),
            code="TASK_EXECUTION_FAILED",
            category="EXECUTION",
            message="Mock failure.",
            retryable=True,
            service="mock",
            occurred_at=FIXED_TIME,
        ),
        started_at=FIXED_TIME,
        completed_at=FIXED_TIME,
        metadata={},
    )


def _run(*tasks: TaskRun) -> WorkflowRun:
    return WorkflowRun(
        id=uuid4(),
        workflow_key="quality-gate-fixture",
        execution_mode=WorkflowExecutionMode.LEGACY_FLOW,
        flow_id=uuid4(),
        name="Quality gate fixture",
        status=WorkflowRunStatus.RUNNING,
        tasks=list(tasks),
        created_at=FIXED_TIME,
    )


def test_quality_gate_passes_when_testing_and_review_evidence_pass() -> None:
    testing = _completed(_task(task_type="TESTING", status=TaskRunStatus.PENDING))
    testing = testing.model_copy(
        update={"result": _succeeded_result(testing), "current_attempt_id": testing.current_attempt_id}
    )
    review = _completed(_task(task_type="REVIEW", status=TaskRunStatus.PENDING))
    verdict = evaluate_quality_gate(_run(testing, review))
    assert verdict.decision is QualityGateDecision.PASS
    assert verdict.reasons == []


def test_quality_gate_maps_failed_tasks_onto_retry_then_fail() -> None:
    failing = _task(task_type="IMPLEMENTATION", status=TaskRunStatus.FAILED)
    failing = failing.model_copy(
        update={
            "result": _failed_result(failing),
            "request": TaskRequest.model_construct(constraints={"max_attempts": 2}),
        }
    )
    assert evaluate_quality_gate(_run(failing)).decision is QualityGateDecision.RETRY

    exhausted = failing.model_copy(update={"retry_count": 1})
    assert evaluate_quality_gate(_run(exhausted)).decision is QualityGateDecision.FAIL

    cancelled = _task(task_type="IMPLEMENTATION", status=TaskRunStatus.CANCELLED)
    assert evaluate_quality_gate(_run(cancelled)).decision is QualityGateDecision.FAIL


def test_quality_gate_requires_testing_and_review_evidence() -> None:
    testing_without_evidence = _completed(
        _task(task_type="TESTING", status=TaskRunStatus.PENDING),
        result=_succeeded_result(_task(task_type="TESTING", status=TaskRunStatus.PENDING), testing=None),
    )
    review = _completed(_task(task_type="REVIEW", status=TaskRunStatus.PENDING))
    verdict = evaluate_quality_gate(_run(testing_without_evidence, review))
    assert verdict.decision is QualityGateDecision.REVISION
    assert any("testing evidence" in reason for reason in verdict.reasons)

    review_without_artifacts = _completed(
        _task(task_type="REVIEW", status=TaskRunStatus.PENDING), with_artifact=False
    )
    verdict = evaluate_quality_gate(_run(review_without_artifacts))
    assert verdict.decision is QualityGateDecision.REVISION
    assert any("revision" in reason.lower() for reason in verdict.reasons)


def test_quality_gate_enforces_minimum_coverage() -> None:
    low_coverage = _completed(
        _task(task_type="TESTING", status=TaskRunStatus.PENDING),
        result=_succeeded_result(
            _task(task_type="TESTING", status=TaskRunStatus.PENDING),
            output={"passed": 5, "failed": 0, "coverage": 41.0},
        ),
    )
    verdict = evaluate_quality_gate(_run(low_coverage), policy=QualityGatePolicy(min_coverage=80.0))
    assert verdict.decision is QualityGateDecision.REVISION
    assert any("coverage" in reason for reason in verdict.reasons)

    passing = low_coverage.model_copy(
        update={"result": _succeeded_result(low_coverage, output={"passed": 9, "failed": 0, "coverage": 87.5})}
    )
    verdict = evaluate_quality_gate(_run(passing), policy=QualityGatePolicy(min_coverage=80.0))
    assert verdict.decision is QualityGateDecision.PASS


def test_quality_gate_review_fail_and_needs_revision_branches() -> None:
    class _FixedReview(MockReviewService):
        def __init__(self, decision: ReviewDecision) -> None:
            self._decision = decision

        def review(self, run: WorkflowRun, task: TaskRun) -> ReviewOutcome:
            return ReviewOutcome(decision=self._decision, score=0.4, findings=[], task_run_id=task.id)

    review = _completed(_task(task_type="REVIEW", status=TaskRunStatus.PENDING))
    assert (
        evaluate_quality_gate(_run(review), review_service=_FixedReview(ReviewDecision.FAIL)).decision
        is QualityGateDecision.FAIL
    )
    assert (
        evaluate_quality_gate(_run(review), review_service=_FixedReview(ReviewDecision.NEEDS_REVISION)).decision
        is QualityGateDecision.REVISION
    )


def test_quality_gate_ignores_evidence_rules_when_policy_disables_them() -> None:
    testing_without_evidence = _completed(
        _task(task_type="TESTING", status=TaskRunStatus.PENDING),
        result=_succeeded_result(_task(task_type="TESTING", status=TaskRunStatus.PENDING), testing=None),
    )
    review_without_artifacts = _completed(
        _task(task_type="REVIEW", status=TaskRunStatus.PENDING), with_artifact=False
    )
    policy = QualityGatePolicy(require_testing_passed=False, require_review_pass=False)
    verdict = evaluate_quality_gate(_run(testing_without_evidence, review_without_artifacts), policy=policy)
    assert verdict.decision is QualityGateDecision.PASS

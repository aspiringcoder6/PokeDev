# ruff: noqa: INP001, PLR2004, S101, SLF001

"""G6 quality gate: independent verdict, human-gate digest pinning, reflection.

Proves the presentation's three dimensions on the run state machine:

1. execution state — existing TaskRunStatus/WorkflowRunStatus only;
2. verdict per criteria — ``evaluate_task_quality`` scores EVIDENCE
   (artifacts, Evidence Plane items, testing-adapter outcome), never the
   executor's self-report;
3. acceptance decision — gate PASS is required before DONE; verdict
   failure follows the retry policy and escalates via the existing
   PAUSED state; the human gate pins artifact digests and refuses
   approvals of changed revisions; reflection fires for terminal runs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from langflow.adlc.evidence_plane import Evidence, EvidenceType
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    Actor,
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    GateType,
    MockArtifactSpec,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from langflow.adlc.quality_gate import (
    QualityGateDecision,
    TaskCriterion,
    evaluate_task_quality,
)
from langflow.adlc.quality_gate_policy import (
    QUALITY_GATE_ENV,
    QualityGateRunPolicy,
    load_quality_gate_policy,
)
from langflow.adlc.run_reflection import reflection_metadata
from langflow.adlc.run_repository import InMemoryRunRepository
from langflow.adlc.run_service import AdlcRunStateError, AdlcRunService

_OWNER = "g6-test"
_GATE_ON_FOR_MOCK = QualityGateRunPolicy(exempt_mock_execution=False)


def _definition(
    key: str,
    *,
    dependencies: list[str] | None = None,
    approval_gate: GateType | None = None,
    criteria: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> AdlcTaskDefinition:
    constraints: dict[str, Any] = {}
    if criteria is not None:
        constraints["acceptance_criteria"] = criteria
    payload: dict[str, Any] = {
        "id": uuid4(),
        "key": key,
        "name": key.replace("_", " ").title(),
        "task_type": "IMPLEMENTATION",
        "dependencies": dependencies or [],
        "predetermined_output": {"summary": f"Result for {key}."},
        "artifact": MockArtifactSpec(kind="DOCUMENT", name=f"{key}.txt", media_type="text/plain", content=key),
        "delay_ms": 0,
        "approval_gate": approval_gate,
        "constraints": constraints,
    }
    payload.update(overrides)
    return AdlcTaskDefinition(**payload)


def _service(**kwargs: Any) -> AdlcRunService:
    """Service with the gate active even for mock execution (env-independent)."""
    kwargs.setdefault("quality_gate_policy", _GATE_ON_FOR_MOCK)
    return AdlcRunService(MockExecutor(), repository=InMemoryRunRepository(), **kwargs)


def _default_service(**kwargs: Any) -> AdlcRunService:
    """Service with the environment-loaded default policy (mock exempt)."""
    return AdlcRunService(MockExecutor(), repository=InMemoryRunRepository(), **kwargs)


def _run_flow(
    service: AdlcRunService,
    definitions: list[AdlcTaskDefinition],
) -> WorkflowRun:
    flow_id = uuid4()
    return asyncio.run(
        service.start_run(
            flow_id=flow_id,
            flow_name="G6 quality gate",
            definitions=definitions,
            request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
            owner_id=_OWNER,
        )
    )


def _approve(service: AdlcRunService, run: WorkflowRun, comment: str | None = "ok") -> WorkflowRun:
    return asyncio.run(
        service.approve(
            run.approval_requests[0].approval_request_id,
            owner_id=_OWNER,
            actor=Actor(type="USER", display_name="Maintainer"),
            comment=comment,
        )
    )


def _reject(service: AdlcRunService, run: WorkflowRun) -> WorkflowRun:
    return asyncio.run(
        service.reject(
            run.approval_requests[0].approval_request_id,
            owner_id=_OWNER,
            actor=Actor(type="USER", display_name="Maintainer"),
            comment="no",
        )
    )


def _stub_run() -> WorkflowRun:
    return WorkflowRun(
        id=uuid4(),
        workflow_key="g6",
        execution_mode="LEGACY_FLOW",
        name="G6 verdict",
        status=WorkflowRunStatus.RUNNING,
        tasks=[],
        created_at=datetime.now(timezone.utc),
    )


def _stub_task(
    *,
    testing: dict[str, Any] | None = None,
    artifact_count: int = 0,
) -> TaskRun:
    task_run_id = uuid4()
    attempt_id = uuid4()
    now = datetime.now(timezone.utc)
    result = TaskResult(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        status=TaskResultStatus.SUCCEEDED,
        output={"summary": "executor claims everything is done"},
        artifacts=[],
        error=None,
        metrics=None,
        started_at=now,
        completed_at=now,
        metadata={"testing": testing} if testing is not None else {},
    )
    return TaskRun(
        id=task_run_id,
        workflow_run_id=result.workflow_run_id,
        task_definition_id=uuid4(),
        key="unit-test",
        name="Unit test",
        task_type="TESTING",
        status=TaskRunStatus.SUCCEEDED,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service="mock-agent-adapter", operation="mock"),
        result=result,
        artifacts=list(result.artifacts),
        current_attempt_id=attempt_id,
    )


class TestEvaluateTaskQuality:
    def test_summary_claim_never_satisfies_test_criterion(self) -> None:
        criteria = [TaskCriterion(description="unit tests pass", verification="TEST")]

        missing = evaluate_task_quality(_stub_run(), _stub_task(), criteria=criteria)
        assert missing.decision is QualityGateDecision.FAIL
        assert missing.criteria[0].status == "FAIL"
        assert missing.criteria[0].evidence_refs == []

        claimed = evaluate_task_quality(
            _stub_run(),
            _stub_task(testing={"outcome": "FAILED", "note": "trust me"}),
            criteria=criteria,
        )
        assert claimed.decision is QualityGateDecision.FAIL

        passed = evaluate_task_quality(
            _stub_run(),
            _stub_task(testing={"outcome": "PASSED"}),
            criteria=criteria,
        )
        assert passed.decision is QualityGateDecision.PASS
        assert passed.criteria[0].status == "PASS"
        assert passed.criteria[0].evidence_refs == ["result:metadata:testing"]
        assert passed.evaluator == "adlc-quality-gate"

    def test_evidence_plane_test_result_counts(self) -> None:
        task = _stub_task()
        now = datetime.now(timezone.utc)
        evidence = Evidence(
            evidence_type=EvidenceType.TEST_RESULT,
            producer="testing-adapter",
            submitted_at=now,
            payload={"outcome": "PASSED"},
            workflow_run_id=task.workflow_run_id,
            task_run_id=task.id,
        )
        verdict = evaluate_task_quality(
            _stub_run(),
            task,
            criteria=[TaskCriterion(description="tests pass", verification="TEST")],
            evidence=[evidence],
        )
        assert verdict.decision is QualityGateDecision.PASS
        assert verdict.criteria[0].evidence_refs == [f"evidence:{evidence.evidence_id}"]
        assert verdict.evidence_sources == ["evidence_plane", "task_result_artifacts"]

    def test_artifact_criterion_requires_work_evidence(self) -> None:
        verdict = evaluate_task_quality(
            _stub_run(),
            _stub_task(),
            criteria=[TaskCriterion(description="patch delivered", verification="ARTIFACT")],
        )
        assert verdict.decision is QualityGateDecision.FAIL

        bookkeeping = Evidence(
            evidence_type=EvidenceType.METRIC,
            producer="coordinator",
            submitted_at=datetime.now(timezone.utc),
            payload={"event": "task_completed"},
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
        )
        metric_only = evaluate_task_quality(
            _stub_run(),
            _stub_task(),
            criteria=[TaskCriterion(description="patch delivered", verification="ARTIFACT")],
            evidence=[bookkeeping],
        )
        assert metric_only.decision is QualityGateDecision.FAIL

    def test_human_criterion_routes_through_approval_gate(self) -> None:
        criteria = [TaskCriterion(description="maintainer sign-off", verification="HUMAN")]

        without_gate = evaluate_task_quality(_stub_run(), _stub_task(), criteria=criteria)
        assert without_gate.decision is QualityGateDecision.FAIL
        assert "no approval gate" in without_gate.reasons[0]

        with_gate = evaluate_task_quality(_stub_run(), _stub_task(), criteria=criteria, human_gate_required=True)
        assert with_gate.decision is QualityGateDecision.PASS
        assert with_gate.criteria[0].status == "HUMAN_REQUIRED"


class TestGateInScheduler:
    def test_verdict_fail_retries_then_escalates_without_new_states(self) -> None:
        """Succeeded + verdict fail: retry within budget, then PAUSED escalation.

        A HUMAN criterion without a declared approval gate can never be
        satisfied from evidence, so the verdict fails deterministically.
        """
        service = _service()
        definitions = [
            _definition(
                "deliver",
                criteria=[
                    {"description": "maintainer sign-off", "verification": "HUMAN"},
                ],
            )
        ]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.PAUSED  # existing escalation, no new state
        task = run.tasks[0]
        assert task.status.value == "FAILED"
        assert task.retry_count == 1  # policy retry consumed one attempt
        assert task.result.error.code == "QUALITY_GATE_FAILED"
        assert task.result.error.retryable is False
        assert task.result.output is None
        verdict = task.result.metadata["quality_gate"]
        assert verdict["decision"] == "FAIL"
        assert verdict["criteria"][0]["status"] == "FAIL"
        assert verdict["evaluator"] == "adlc-quality-gate"

    def test_test_criterion_passes_with_testing_adapter_evidence(self) -> None:
        """The mock testing adapter's PASSED mirror is accepted evidence."""
        service = _service()
        definitions = [
            _definition(
                "deliver",
                task_type="TESTING",
                criteria=[{"description": "tests pass", "verification": "TEST"}],
            )
        ]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.SUCCEEDED
        verdict = run.tasks[0].result.metadata["quality_gate"]
        assert verdict["decision"] == "PASS"
        assert verdict["criteria"][0]["evidence_refs"] == ["result:metadata:testing"]

    def test_verdict_pass_reaches_succeeded_with_verdict_stored(self) -> None:
        service = _service()
        definitions = [
            _definition("deliver", criteria=[{"description": "artifact delivered", "verification": "ARTIFACT"}])
        ]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.SUCCEEDED
        task = run.tasks[0]
        assert task.status.value == "SUCCEEDED"
        verdict = task.result.metadata["quality_gate"]
        assert verdict["decision"] == "PASS"
        assert verdict["criteria"][0]["status"] == "PASS"
        assert verdict["criteria"][0]["evidence_refs"] == [f"artifact:{task.artifacts[0].artifact_id}"]

    def test_no_criteria_declared_keeps_legacy_behavior(self) -> None:
        service = _service()
        run = _run_flow(service, [_definition("deliver")])

        assert run.status is WorkflowRunStatus.SUCCEEDED
        assert "quality_gate" not in run.tasks[0].result.metadata

    def test_gate_disabled_by_policy_keeps_legacy_behavior(self) -> None:
        service = _service(quality_gate_policy=QualityGateRunPolicy(enabled=False))
        definitions = [_definition("deliver", criteria=[{"description": "unit tests pass", "verification": "TEST"}])]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.SUCCEEDED
        assert "quality_gate" not in run.tasks[0].result.metadata

    def test_gate_exempt_task_type_via_policy(self) -> None:
        policy = QualityGateRunPolicy(exempt_task_types={"CODE_GENERATION"})
        service = _service(quality_gate_policy=policy)
        definitions = [
            _definition(
                "deliver",
                task_type="CODE_GENERATION",
                criteria=[{"description": "unit tests pass", "verification": "TEST"}],
            )
        ]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.SUCCEEDED
        assert "quality_gate" not in run.tasks[0].result.metadata

    def test_gate_exempt_mock_execution_by_default(self) -> None:
        service = _default_service()
        definitions = [
            _definition(
                "deliver",
                criteria=[{"description": "unit tests pass", "verification": "TEST"}],
                request_metadata={"mock": True},
            )
        ]

        run = _run_flow(service, definitions)

        assert run.status is WorkflowRunStatus.SUCCEEDED
        assert "quality_gate" not in run.tasks[0].result.metadata

    def test_env_flag_disables_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(QUALITY_GATE_ENV, "0")
        assert load_quality_gate_policy().enabled is False

        monkeypatch.setenv(QUALITY_GATE_ENV, "true")
        assert load_quality_gate_policy().enabled is True


class TestHumanGateDigestPinning:
    def _waiting_run(self, service: AdlcRunService) -> WorkflowRun:
        definitions = [_definition("deliver", approval_gate=GateType.AFTER_TASK)]
        run = _run_flow(service, definitions)
        assert run.status is WorkflowRunStatus.WAITING_APPROVAL
        return run

    def test_approval_pins_artifact_revisions(self) -> None:
        service = _service()
        run = self._waiting_run(service)
        approval = run.approval_requests[0]

        pinned = approval.context.payload["artifact_digests"]
        assert len(pinned) == 1
        digest = pinned[0]["digest"]
        assert digest.startswith("sha256:")
        assert digest == f"sha256:{service._runs[run.id].run.tasks[0].artifacts[0].checksum.value}"

    def test_correct_digest_approval_completes_run(self) -> None:
        service = _service()
        run = self._waiting_run(service)

        approved = _approve(service, run)

        assert approved.status is WorkflowRunStatus.SUCCEEDED
        assert approved.tasks[0].status.value == "SUCCEEDED"

    def test_changed_artifact_after_review_is_refused(self) -> None:
        service = _service()
        run = self._waiting_run(service)
        approval = run.approval_requests[0]

        # The reviewed revision is replaced after the human opened it.
        task = service._runs[run.id].run.tasks[0]
        task.artifacts[0].checksum.value = "f" * 64

        with pytest.raises(AdlcRunStateError, match="APPROVAL_ARTIFACT_DIGEST_MISMATCH"):
            _approve(service, run)

        assert approval.status.value == "PENDING"
        assert run.status is WorkflowRunStatus.WAITING_APPROVAL

        # The unchanged dependency set still approves after re-review.
        task.artifacts[0].checksum.value = run.approval_requests[0].context.payload["artifact_digests"][0][
            "digest"
        ].removeprefix("sha256:")
        approved = _approve(service, run)
        assert approved.status is WorkflowRunStatus.SUCCEEDED


class TestReflectionAfterRun:
    @staticmethod
    def _dispatcher(reports: list[str]) -> Any:
        from langflow.adlc.orchestrator_plugin.interface import ReflectionReport

        async def dispatcher(run: WorkflowRun, outcome: str) -> ReflectionReport:
            reports.append(outcome)
            return ReflectionReport(
                plan_id=run.id,
                intent_id=run.id,
                summary=f"Reflection for {outcome} run.",
                successes=("step one",) if outcome == "succeeded" else (),
                failures=() if outcome == "succeeded" else ("approval rejected",),
                suggestions=("split the step",),
                plugin_id="test-plugin",
            )

        return dispatcher

    def test_reflection_recorded_for_succeeded_run(self) -> None:
        reports: list[str] = []
        service = _service(reflection_dispatcher=self._dispatcher(reports))

        run = _run_flow(service, [_definition("deliver", approval_gate=GateType.AFTER_TASK)])
        approved = _approve(service, run)

        assert approved.status is WorkflowRunStatus.SUCCEEDED
        assert reports == ["succeeded"]
        reflection = approved.metadata["reflection"]
        assert reflection["summary"] == "Reflection for succeeded run."
        assert reflection["successes"] == ["step one"]
        assert reflection["failures"] == []
        assert reflection["plugin_id"] == "test-plugin"

    def test_reflection_recorded_for_failed_run(self) -> None:
        reports: list[str] = []
        service = _service(reflection_dispatcher=self._dispatcher(reports))
        run = _run_flow(service, [_definition("deliver", approval_gate=GateType.AFTER_TASK)])

        rejected = _reject(service, run)

        assert rejected.status is WorkflowRunStatus.FAILED
        assert reports == ["failed"]
        reflection = rejected.metadata["reflection"]
        assert reflection["failures"] == ["approval rejected"]
        assert reflection["suggestions"] == ["split the step"]

    def test_reflection_failure_never_breaks_the_run(self) -> None:
        async def broken_dispatcher(run: WorkflowRun, outcome: str) -> None:
            msg = "plugin exploded"
            raise RuntimeError(msg)

        service = _service(reflection_dispatcher=broken_dispatcher)
        run = _run_flow(service, [_definition("deliver", approval_gate=GateType.AFTER_TASK)])
        approved = _approve(service, run)

        assert approved.status is WorkflowRunStatus.SUCCEEDED
        assert "reflection" not in approved.metadata

    def test_reflection_can_be_disabled(self) -> None:
        async def disabled_dispatcher(run: WorkflowRun, outcome: str) -> None:
            return None

        service = _service(reflection_dispatcher=disabled_dispatcher)
        run = _run_flow(service, [_definition("deliver", approval_gate=GateType.AFTER_TASK)])
        approved = _approve(service, run)

        assert approved.status is WorkflowRunStatus.SUCCEEDED
        assert "reflection" not in approved.metadata

    def test_default_dispatcher_uses_production_host(self) -> None:
        """Without an injected dispatcher the production Monarch plugin reflects."""
        service = _service()
        run = _run_flow(service, [_definition("deliver", approval_gate=GateType.AFTER_TASK)])
        approved = _approve(service, run)

        assert approved.status is WorkflowRunStatus.SUCCEEDED
        reflection = approved.metadata["reflection"]
        assert reflection["plugin_id"] == "monarch"
        assert reflection["summary"].startswith("Execution succeeded")

    def test_reflection_metadata_projection(self) -> None:
        from langflow.adlc.orchestrator_plugin.interface import ReflectionReport

        now = datetime.now(timezone.utc)
        report = ReflectionReport(
            plan_id=uuid4(),
            intent_id=uuid4(),
            summary="s",
            successes=("a",),
            failures=("b",),
            suggestions=("c",),
            plugin_id="monarch",
            created_at=now,
        )
        projected = reflection_metadata(report)
        assert projected["successes"] == ["a"]
        assert projected["created_at"] == now.isoformat()

"""Orchestrator quality gate: policy decisions over testing and review evidence.

Testing provides evidence and Review provides evaluation; the quality gate is
the orchestrator's policy decision (MVP v0.1). The gate never executes tasks,
never transitions run state, and never bypasses approvals — it only maps the
evidence carried by terminal TaskResults onto PASS / RETRY / REVISION / FAIL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import Field

from langflow.adlc.blueprints.models import ClosedModel, NonEmptyString
from langflow.adlc.evidence_plane.models import Evidence, EvidenceType
from langflow.adlc.models import Artifact, TaskResult, TaskRun, TaskRunStatus, WorkflowRun

_DEFAULT_MAX_ATTEMPTS = 2


class QualityGateDecision(str, Enum):
    """Orchestration decision produced by the gate (v0.1 MVP subset)."""

    PASS = "PASS"
    RETRY = "RETRY"
    REVISION = "REVISION"
    FAIL = "FAIL"


_DECISION_PRECEDENCE: dict[QualityGateDecision, int] = {
    QualityGateDecision.PASS: 0,
    QualityGateDecision.REVISION: 1,
    QualityGateDecision.RETRY: 2,
    QualityGateDecision.FAIL: 3,
}


class QualityGatePolicy(ClosedModel):
    """Declared gate conditions; defaults require passing testing and review."""

    require_testing_passed: bool = True
    min_coverage: float | None = Field(default=None, ge=0.0, le=100.0)
    require_review_pass: bool = True


class QualityGateVerdict(ClosedModel):
    """Decision plus the human-readable reasons behind it."""

    decision: QualityGateDecision
    reasons: list[NonEmptyString] = Field(default_factory=list)


class ReviewDecision(str, Enum):
    """Review service evaluation (DRAFT/MOCK contract)."""

    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_REVISION = "NEEDS_REVISION"


class ReviewFinding(ClosedModel):
    severity: NonEmptyString
    category: NonEmptyString
    message: NonEmptyString


class ReviewOutcome(ClosedModel):
    """Result of one review evaluation; the review never mutates run state."""

    decision: ReviewDecision
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    findings: list[ReviewFinding] = Field(default_factory=list)
    task_run_id: UUID
    attempt_id: UUID | None = None


class MockReviewService:
    """Deterministic review domain mock: succeeded work with artifacts passes."""

    service_name = "mock-review-service"

    def review(self, run: WorkflowRun, task: TaskRun) -> ReviewOutcome:  # noqa: ARG002 - run kept for contract parity
        if task.status is TaskRunStatus.SUCCEEDED and task.artifacts:
            return ReviewOutcome(decision=ReviewDecision.PASS, score=1.0, findings=[], task_run_id=task.id)
        return ReviewOutcome(
            decision=ReviewDecision.NEEDS_REVISION,
            score=0.0,
            findings=[
                ReviewFinding(
                    severity="HIGH",
                    category="REVIEW_INCOMPLETE",
                    message=(
                        f"Task '{task.name}' is {task.status.value} without reviewable artifacts."
                        if task.status is not TaskRunStatus.SUCCEEDED
                        else f"Task '{task.name}' produced no reviewable artifacts."
                    ),
                )
            ],
            task_run_id=task.id,
            attempt_id=task.current_attempt_id,
        )


def _is_testing_task(task: TaskRun) -> bool:
    return task.task_type.upper().startswith("TESTING")


def _is_review_task(task: TaskRun) -> bool:
    return task.task_type.upper().startswith("REVIEW")


def _max_attempts(task: TaskRun) -> int:
    configured = task.request.constraints.get("max_attempts") if task.request is not None else None
    if isinstance(configured, int) and not isinstance(configured, bool) and configured >= 1:
        return configured
    return _DEFAULT_MAX_ATTEMPTS


def _escalate(decision: QualityGateDecision, candidate: QualityGateDecision) -> QualityGateDecision:
    return candidate if _DECISION_PRECEDENCE[candidate] > _DECISION_PRECEDENCE[decision] else decision


def evaluate_quality_gate(
    run: WorkflowRun,
    *,
    policy: QualityGatePolicy | None = None,
    review_service: MockReviewService | None = None,
) -> QualityGateVerdict:
    """Map the run's terminal evidence onto one orchestration decision."""
    policy = policy or QualityGatePolicy()
    review = review_service if review_service is not None else MockReviewService()
    decision = QualityGateDecision.PASS
    reasons: list[str] = []

    def escalate(candidate: QualityGateDecision, reason: str) -> None:
        nonlocal decision
        decision = _escalate(decision, candidate)
        reasons.append(reason)

    for task in run.tasks:
        label = f"task '{task.name}'"
        if task.status is TaskRunStatus.FAILED:
            max_attempts = _max_attempts(task)
            if task.retry_count + 1 < max_attempts:
                escalate(
                    QualityGateDecision.RETRY,
                    f"{label} failed but its retry budget allows another attempt "
                    f"({task.retry_count + 1}/{max_attempts}).",
                )
            else:
                escalate(
                    QualityGateDecision.FAIL,
                    f"{label} failed and its retry budget is exhausted ({max_attempts} attempt(s)).",
                )
        elif task.status is TaskRunStatus.CANCELLED:
            escalate(QualityGateDecision.FAIL, f"{label} was cancelled.")

        if policy.require_testing_passed and _is_testing_task(task):
            evidence = task.result.metadata.get("testing") if task.result is not None else None
            outcome = evidence.get("outcome") if isinstance(evidence, dict) else None
            if outcome != "PASSED":
                escalate(
                    QualityGateDecision.REVISION,
                    f"{label} lacks passing testing evidence (outcome: {outcome or 'missing'}).",
                )
            if (
                policy.min_coverage is not None
                and task.result is not None
                and isinstance(task.result.output, dict)
            ):
                coverage = task.result.output.get("coverage")
                if isinstance(coverage, (int, float)) and not isinstance(coverage, bool):
                    if float(coverage) < policy.min_coverage:
                        escalate(
                            QualityGateDecision.REVISION,
                            f"{label} coverage {coverage} is below the required {policy.min_coverage}.",
                        )

        if policy.require_review_pass and _is_review_task(task):
            outcome = review.review(run, task)
            if outcome.decision is ReviewDecision.FAIL:
                escalate(QualityGateDecision.FAIL, f"{label} was rejected by review.")
            elif outcome.decision is ReviewDecision.NEEDS_REVISION:
                escalate(
                    QualityGateDecision.REVISION,
                    f"{label} needs revision: {outcome.findings[0].message if outcome.findings else 'review declined'}.",
                )

    return QualityGateVerdict(decision=decision, reasons=reasons)


class TaskCriterion(ClosedModel):
    """One acceptance criterion declared on a task definition (v0.1)."""

    description: NonEmptyString
    verification: Literal["HUMAN", "TEST", "ARTIFACT"] = "HUMAN"


class CriterionVerdict(ClosedModel):
    """Evidence-backed outcome for one acceptance criterion."""

    description: NonEmptyString
    verification: Literal["HUMAN", "TEST", "ARTIFACT"]
    status: Literal["PASS", "FAIL", "HUMAN_REQUIRED"]
    evidence_refs: list[NonEmptyString] = Field(default_factory=list)


class TaskQualityVerdict(ClosedModel):
    """Independent per-task verdict produced from evidence only.

    The verdict is generated by the quality gate module — never from the
    executor's self-reported summary or the orchestrator's opinion — and
    is stored on the ``TaskResult`` metadata under ``quality_gate``.
    """

    task_run_id: UUID
    attempt_id: UUID | None = None
    decision: QualityGateDecision
    criteria: list[CriterionVerdict] = Field(default_factory=list)
    reasons: list[NonEmptyString] = Field(default_factory=list)
    evidence_sources: list[NonEmptyString] = Field(default_factory=list)
    evaluator: str = "adlc-quality-gate"
    evaluated_at: datetime


def _testing_evidence_pass(result: TaskResult | None, evidence: list[Evidence]) -> tuple[bool, list[str]]:
    """Return whether passing test evidence exists and the refs backing it."""
    refs: list[str] = []
    for item in evidence:
        if item.evidence_type is not EvidenceType.TEST_RESULT:
            continue
        outcome = item.payload.get("outcome")
        if outcome == "PASSED":
            refs.append(f"evidence:{item.evidence_id}")
    if result is not None:
        testing = result.metadata.get("testing")
        if isinstance(testing, dict) and testing.get("outcome") == "PASSED":
            refs.append("result:metadata:testing")
    return (bool(refs), refs)


def _artifact_evidence_pass(
    artifacts: list[Artifact],
    evidence: list[Evidence],
) -> tuple[bool, list[str]]:
    refs = [f"artifact:{artifact.artifact_id}" for artifact in artifacts]
    # Observability metrics ("task_completed") are not work evidence.
    refs.extend(
        f"evidence:{item.evidence_id}" for item in evidence if item.evidence_type is not EvidenceType.METRIC
    )
    return (bool(refs), refs)


def evaluate_task_quality(
    run: WorkflowRun,
    task: TaskRun,
    *,
    criteria: list[TaskCriterion],
    result: TaskResult | None = None,
    evidence: list[Evidence] | None = None,
    human_gate_required: bool = False,
    evaluated_at: datetime | None = None,
) -> TaskQualityVerdict:
    """Score one succeeded task against its declared acceptance criteria.

    The evaluation reads EVIDENCE only: artifacts and the testing
    adapter's outcome carried by ``result`` (the attempt under judgment;
    falls back to the task projection), plus items stored in the
    Evidence Plane. It never consults the executor's summary text or any
    orchestrator opinion, so the verdict stays independent of whoever
    produced the work.
    """
    evidence = evidence or []
    if result is None:
        result = task.result
    artifacts = list(result.artifacts) if result is not None else []
    now = evaluated_at or datetime.now(timezone.utc)
    criteria_verdicts: list[CriterionVerdict] = []
    reasons: list[str] = []
    evidence_sources = {"evidence_plane", "task_result_artifacts"}

    decision = QualityGateDecision.PASS

    def fail(reason: str) -> None:
        nonlocal decision
        decision = QualityGateDecision.FAIL
        reasons.append(reason)

    for criterion in criteria:
        if criterion.verification == "TEST":
            passed, refs = _testing_evidence_pass(result, evidence)
            if passed:
                criteria_verdicts.append(
                    CriterionVerdict(
                        description=criterion.description,
                        verification="TEST",
                        status="PASS",
                        evidence_refs=refs,
                    )
                )
            else:
                criteria_verdicts.append(
                    CriterionVerdict(description=criterion.description, verification="TEST", status="FAIL")
                )
                fail(f"Criterion '{criterion.description}' lacks passing test evidence.")
        elif criterion.verification == "ARTIFACT":
            passed, refs = _artifact_evidence_pass(artifacts, evidence)
            if passed:
                criteria_verdicts.append(
                    CriterionVerdict(
                        description=criterion.description,
                        verification="ARTIFACT",
                        status="PASS",
                        evidence_refs=refs,
                    )
                )
            else:
                criteria_verdicts.append(
                    CriterionVerdict(description=criterion.description, verification="ARTIFACT", status="FAIL")
                )
                fail(f"Criterion '{criterion.description}' has no artifact evidence.")
        else:  # HUMAN
            if human_gate_required:
                criteria_verdicts.append(
                    CriterionVerdict(description=criterion.description, verification="HUMAN", status="HUMAN_REQUIRED")
                )
                reasons.append(
                    f"Criterion '{criterion.description}' awaits human acceptance via the approval gate."
                )
            else:
                criteria_verdicts.append(
                    CriterionVerdict(description=criterion.description, verification="HUMAN", status="FAIL")
                )
                fail(f"Criterion '{criterion.description}' needs human acceptance but no approval gate is declared.")

    if decision is QualityGateDecision.PASS and not criteria:
        reasons.append("No acceptance criteria were declared; nothing to judge.")

    return TaskQualityVerdict(
        task_run_id=task.id,
        attempt_id=task.current_attempt_id,
        decision=decision,
        criteria=criteria_verdicts,
        reasons=reasons,
        evidence_sources=sorted(evidence_sources),
        evaluated_at=now,
    )


__all__ = [
    "CriterionVerdict",
    "MockReviewService",
    "QualityGateDecision",
    "QualityGatePolicy",
    "QualityGateVerdict",
    "ReviewDecision",
    "ReviewFinding",
    "ReviewOutcome",
    "TaskCriterion",
    "TaskQualityVerdict",
    "evaluate_quality_gate",
    "evaluate_task_quality",
]

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from langflow.adlc.source_access.models import Closed, Evidence, SourceRef


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class PipelineConfig(Closed):
    max_context_rounds: int = Field(default=3, strict=True, ge=1, le=20)
    max_tool_calls: int = Field(default=24, strict=True, ge=1, le=200)
    max_context_bytes: int = Field(default=500000, strict=True, ge=1, le=2000000)


class NormalizedInput(Closed):
    request_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    source_refs: tuple[SourceRef, ...] = ()


class ContextSnapshot(Closed):
    request: NormalizedInput
    evidence: tuple[Evidence, ...]
    digest: str

    @classmethod
    def from_input(cls, request, evidence):
        ordered = tuple(sorted(evidence, key=lambda item: item.id))
        payload = {"request": request.model_dump(mode="json"),
                   "evidence": [item.model_dump(mode="json") for item in ordered]}
        return cls(request=request, evidence=ordered, digest=canonical_digest(payload))

    @model_validator(mode="after")
    def validate_digest(self):
        payload = {"request": self.request.model_dump(mode="json"),
                   "evidence": [item.model_dump(mode="json") for item in sorted(self.evidence, key=lambda e: e.id)]}
        if canonical_digest(payload) != self.digest:
            raise ValueError("READINESS_SNAPSHOT_INVALID")
        return self


class CollectionResult(Closed):
    read_requests: tuple[SourceRef, ...]
    rationale: str


class ContextVerdict(Closed):
    sufficient: bool = Field(strict=True)
    missing_refs: tuple[SourceRef, ...] = ()
    reasons: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class Finding(Closed):
    requirement: str
    issue: str
    blocking: bool = Field(strict=True)
    evidence: tuple[str, ...] = ()
    resolution: Literal["retrieve_context", "human_decision", "agent_update"]
    question: str | None = None
    suggested_role: str | None = None


class ReviewResult(Closed):
    reviewer_id: Literal["a", "b"]
    snapshot_digest: str
    route: Literal["spec-kit", "openspec", "unresolved"]
    status: Literal["ready_for_spec", "spec_ready", "needs_context", "needs_clarification",
                    "awaiting_authorization", "blocked"]
    route_reason: str
    evidence: tuple[str, ...] = ()
    native_steps: tuple[dict, ...] = ()
    artifacts: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    retrieve_refs: tuple[SourceRef, ...] = ()


class HumanQuestion(Closed):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1)
    body: str = Field(min_length=1, max_length=16000)
    recommendation: str


class HumanRound(Closed):
    id: str
    snapshot_digest: str
    kind: Literal["frontier", "confirmation", "authorization"]
    questions: tuple[HumanQuestion, ...] = ()
    answers: dict[str, str] = Field(default_factory=dict)
    confirmed: bool = False
    answered: bool = False


class OperationState(str, Enum):
    INTENT = "INTENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    UNCONFIRMED = "UNCONFIRMED"


class ImpactReport(Closed):
    analyst: Literal["code", "requirements"]
    snapshot_digest: str
    status: Literal["complete", "incomplete"]
    body: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    affected_items: tuple[str, ...]
    blocking_findings: tuple[str, ...]
    material_uncertainties: tuple[str, ...]
    requires_authorization: bool = Field(strict=True)


class Option(Closed):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    approach: str = Field(min_length=1)
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    risks: tuple[str, ...]
    prerequisites: tuple[str, ...]


class Assessment(Closed):
    snapshot_digest: str
    report_digests: dict[str, str]
    body: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    affected_systems: tuple[str, ...]
    complexity: Literal["small", "medium", "large"]
    related_work: tuple[str, ...]
    concerns: tuple[str, ...]
    questions: tuple[str, ...]
    risks: tuple[str, ...]
    options: tuple[Option, ...] = Field(min_length=2, max_length=3)
    recommended_option_id: str
    recommendation_reason: str = Field(min_length=1)
    material_disagreement: bool = Field(strict=True)

    @model_validator(mode="after")
    def choices(self):
        if (len({o.id for o in self.options}) != len(self.options)
                or len({o.approach.strip().casefold() for o in self.options}) != len(self.options)):
            raise ValueError("READINESS_OPTIONS_NOT_DISTINCT")
        if self.recommended_option_id not in {o.id for o in self.options}:
            raise ValueError("READINESS_RECOMMENDATION_INVALID")
        return self


class HumanGatePolicy(Closed):
    mode: Literal["auto", "required"] = "required"
    revision: str = Field(default="default-required-v1", min_length=1)


class OptionDecision(Closed):
    mode: Literal["auto", "required"]
    snapshot_digest: str
    assessment_digest: str
    policy_revision: str
    selected_option_id: str
    selected_by: str
    reason: str


Status = Literal["created", "collecting", "verifying_context", "context_ready", "reviewing",
                 "requirements_ready", "impact_analyzing", "assessing", "waiting_option", "waiting_human",
                 "needs_context", "needs_clarification", "awaiting_authorization", "blocked", "ready",
                 "cancelled", "failed"]


class ReadinessRun(Closed):
    id: str
    principal_id: str
    request: NormalizedInput
    config: PipelineConfig
    revision: int = 0
    status: Status = "created"
    round_count: int = 0
    tool_calls: int = 0
    context_bytes: int = 0
    evidence: tuple[Evidence, ...] = ()
    missing_refs: tuple[SourceRef, ...] = ()
    snapshot: ContextSnapshot | None = None
    round_snapshot: ContextSnapshot | None = None
    read_operations: dict[str, dict] = Field(default_factory=dict)
    pinned_revisions: dict[str, str] = Field(default_factory=dict)
    reviews: tuple[ReviewResult, ...] = ()
    human_rounds: tuple[HumanRound, ...] = ()
    confirmed_requirement: str | None = None
    result: dict | None = None
    error_code: str | None = None
    readiness_kind: Literal["ready_for_spec", "spec_ready"] | None = None
    runtime_manifest_digest: str = ""
    impacts: tuple[ImpactReport, ...] = ()
    assessment: Assessment | None = None
    policy_revision: str | None = None
    decision: OptionDecision | None = None
    pending_selection: dict | None = None
    selection_commands: dict = Field(default_factory=dict)
    verdict: ContextVerdict | None = None


class ReadinessPackage(Closed):
    handoff_id: str
    status: Literal["ready"] = "ready"
    readiness_kind: Literal["ready_for_spec", "spec_ready"]
    snapshot: ContextSnapshot
    route: str
    reviews: tuple[ReviewResult, ReviewResult]
    confirmed_answers: tuple[HumanRound, ...]
    native_artifacts: tuple[str, ...]
    impacts: tuple[ImpactReport, ImpactReport]
    assessment: Assessment
    decision: OptionDecision

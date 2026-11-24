"""H6A closed, separately versioned reproduction/evidence contracts.

This profile verifies predicates on one frozen JSON file, not application code.
Human approval, execution, comparison and publication are separate operations.
"""

from __future__ import annotations

# ruff: noqa: EM101, TRY003 - fixed public validation messages, never supplied secrets.
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from langflow.adlc.contract_models import ContractReference, Digest

PROFILE = "verification-profile:json-fixture/0.1.0"
RUNNER = "runner:adlc-json-fixture/0.1.0"
MAX_CANDIDATE_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 128 * 1024
Scalar = Annotated[str, Field(max_length=4096)] | StrictBool | StrictInt | StrictFloat | None
CaseId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")]


def canonical(value) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


class VerificationError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationCase(Closed):
    case_id: CaseId
    pointer: Annotated[str, Field(max_length=512, pattern=r"^(?:|/(?:[^~]|~[01])*)$")]
    expected: Scalar
    criterion_node_id: UUID
    criterion_index: Annotated[int, Field(strict=True, ge=0, le=15)]

    @field_validator("expected")
    @classmethod
    def finite_scalar(cls, value):
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and (not math.isfinite(value) or abs(value) > 2**53 - 1)
        ):
            raise ValueError("Expected numbers must be finite and interoperable JSON scalars.")
        return value


class CandidateReference(Closed):
    source_task_id: UUID
    source_attempt_id: UUID
    source_session_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,255}$")]
    artifact_id: UUID
    artifact_digest: Digest
    base_commit: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    project_id: UUID
    source_ref: str
    file: Annotated[str, Field(min_length=1, max_length=255)]
    content_digest: Digest
    encoding: Literal["canonical-json"] = "canonical-json"


class VerificationPlan(Closed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["verification-profile:json-fixture/0.1.0"] = PROFILE
    plan_id: UUID
    revision: Literal[1] = 1
    workflow_run_id: UUID
    contract_reference: ContractReference
    candidate: CandidateReference
    cases: list[VerificationCase] = Field(min_length=1, max_length=16)
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 15

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Case identities must be unique.")
        if len({(case.criterion_node_id, case.criterion_index) for case in self.cases}) != len(self.cases):
            raise ValueError("Each declared criterion can be mapped only once.")
        return self


class CreateVerificationPlan(Closed):
    source_task_id: UUID
    artifact_id: UUID
    contract_reference: ContractReference
    file: Annotated[str, Field(min_length=1, max_length=255)]
    cases: list[VerificationCase] = Field(min_length=1, max_length=16)
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 15
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")]


class ExactVerificationCommand(Closed):
    plan_digest: Digest


class Observation(Closed):
    case_id: CaseId
    pointer: str
    found: StrictBool
    observed: Scalar

    @field_validator("observed")
    @classmethod
    def finite(cls, value):
        return VerificationCase.finite_scalar(value)


class ExecutionReceipt(Closed):
    schema_version: Literal["0.1"] = "0.1"
    execution_id: UUID
    plan_digest: Digest
    candidate_digest: Digest
    runner_ref: Literal["runner:adlc-json-fixture/0.1.0"] = RUNNER
    runner_digest: Digest
    provider: Literal["local-fixture", "sandbox-kit"]
    sandbox_session_id: str | None = None
    image_ref: str | None = None
    tests_run: Annotated[int, Field(strict=True, ge=0, le=16)]
    completion_mode: Literal["process-exit", "durable-checkpoint"] = "process-exit"
    exit_code: Annotated[int, Field(strict=True)] | None
    observations: list[Observation] = Field(max_length=16)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def timestamps(self):
        if not self.started_at.tzinfo or not self.completed_at.tzinfo or self.completed_at < self.started_at:
            raise ValueError("Execution timestamps must be ordered and timezone-aware.")
        if self.provider == "sandbox-kit" and (not self.sandbox_session_id or not self.image_ref):
            raise ValueError("Sandbox receipts require session and image identity.")
        if self.provider == "sandbox-kit" and (
            self.sandbox_session_id != f"adlc-verify-{self.execution_id}"
            or not re.fullmatch(r".+@sha256:[0-9a-f]{64}", self.image_ref or "")
        ):
            raise ValueError("Sandbox receipts require a run-scoped session and pinned image.")
        if self.provider == "local-fixture" and (self.sandbox_session_id or self.image_ref):
            raise ValueError("Local fixture execution is not a sandbox attestation.")
        return self


class Comparison(Closed):
    case_id: str
    pointer: str
    expected: Scalar
    observed: Scalar
    found: StrictBool
    passed: StrictBool


class VerificationReport(Closed):
    schema_version: Literal["0.1"] = "0.1"
    plan_digest: Digest
    receipt_digest: Digest
    candidate_digest: Digest
    verdict: Literal["PASS", "FAIL"]
    comparator_ref: Literal["validator:json-fixture/0.1.0"] = "validator:json-fixture/0.1.0"
    natural_language_enforced: Literal[False] = False
    contract_fully_verified: Literal[False] = False
    checks: list[Comparison] = Field(min_length=1, max_length=16)


class VerificationRead(Closed):
    plan: VerificationPlan
    plan_digest: Digest
    state: Literal[
        "DRAFT", "APPROVED", "RUNNING", "DISPATCH_UNCERTAIN", "READY_FOR_SUBMISSION", "SUBMITTED", "NOT_VERIFIED"
    ]
    approved_by: str | None = None
    approved_at: datetime | None = None
    execution_id: UUID | None = None
    receipt: ExecutionReceipt | None = None
    report: VerificationReport | None = None
    error_code: str | None = None
    evidence_digest: Digest | None = None
    created_at: datetime
    submitted_at: datetime | None = None


class VerificationCapabilities(Closed):
    enabled: bool
    human_actions_configured: bool
    worker_ready: bool
    profile_ref: str = PROFILE
    scope_description: str = (
        "One frozen JSON file and explicitly approved scalar equality predicates; no application code is executed."
    )
    provider: str | None = None


def compare(plan: VerificationPlan, receipt: ExecutionReceipt, runner_digest: str) -> VerificationReport:
    if (
        receipt.plan_digest != digest(plan)
        or receipt.candidate_digest != plan.candidate.content_digest
        or receipt.runner_digest != runner_digest
        or (receipt.exit_code != 0 if receipt.completion_mode == "process-exit" else receipt.exit_code is not None)
        or receipt.tests_run != len(plan.cases)
        or len(receipt.observations) != len(plan.cases)
    ):
        raise VerificationError("VERIFICATION_EVIDENCE_MISMATCH")
    checks = []
    for case, observation in zip(plan.cases, receipt.observations, strict=True):
        if case.case_id != observation.case_id or case.pointer != observation.pointer:
            raise VerificationError("VERIFICATION_CASE_COVERAGE_MISMATCH")
        # Preserve JSON scalar types: Python's True == 1 is not a passing comparison.
        numeric = isinstance(case.expected, (int, float)) and not isinstance(case.expected, bool)
        actual_numeric = isinstance(observation.observed, (int, float)) and not isinstance(observation.observed, bool)
        passed = observation.found and (
            (case.expected == observation.observed)
            if numeric and actual_numeric
            else canonical(observation.observed) == canonical(case.expected)
        )
        checks.append(
            Comparison(
                case_id=case.case_id,
                pointer=case.pointer,
                expected=case.expected,
                observed=observation.observed,
                found=observation.found,
                passed=passed,
            )
        )
    return VerificationReport(
        plan_digest=digest(plan),
        receipt_digest=digest(receipt),
        candidate_digest=plan.candidate.content_digest,
        verdict="PASS" if all(check.passed for check in checks) else "FAIL",
        checks=checks,
    )

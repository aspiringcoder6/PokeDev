"""H6B frozen HTTP-JSON fixture replay. This is not a TestForge/app attestation.

The v0.1 H6A contracts stay unchanged. Only this closed read-only fixture profile
is executable until a real TestForge backend has a reviewed integration contract.
"""

# ruff: noqa: EM101, TRY003 - fixed public validation messages only.
import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from defusedxml import ElementTree as DefusedElementTree
from defusedxml.common import DefusedXmlException
from pydantic import Field, StrictBool, field_validator, model_validator

from langflow.adlc.contract_models import ContractReference, Digest
from langflow.adlc.verification_models import (
    CandidateReference,
    Closed,
    Observation,
    Scalar,
    VerificationCase,
    VerificationError,
    canonical,
    digest,
)

PROFILE = "verification-profile:http-json-replay/0.1.0"
RUNNER = "runner:adlc-http-json-replay/0.1.0"
TARGET = "target-profile:disposable-http-json/0.1.0"
CREDENTIAL = "credential-profile:ephemeral-fixture/0.1.0"
MAX_JUNIT_BYTES = 32 * 1024
MAX_PORT = 65535
MAX_REPLAY_EVIDENCE_BYTES = 256 * 1024
TARGET_CONFIG = {
    "target_profile_ref": TARGET,
    "credential_ref": CREDENTIAL,
    "risk_class": "read-only-non-production",
    "method": "GET",
    "path": "/fixture",
    "heal": False,
    "models": False,
    "skip_policy": "no-required-skips",
    "cleanup": "owned-process-and-socket-only",
}
CONFIG_DIGEST = digest(TARGET_CONFIG)


class ReplayCase(VerificationCase):
    method: Literal["GET"] = "GET"
    path: Literal["/fixture"] = "/fixture"
    expected_status: Annotated[int, Field(strict=True, ge=100, le=599)] = 200


def suite_bytes(cases):
    return canonical({"schema_version": "0.1", "cases": [c.model_dump(mode="json") for c in cases]})


class ReplayPlan(Closed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["verification-profile:http-json-replay/0.1.0"] = PROFILE
    plan_id: UUID
    revision: Literal[1] = 1
    workflow_run_id: UUID
    contract_reference: ContractReference
    candidate: CandidateReference
    cases: list[ReplayCase] = Field(min_length=1, max_length=16)
    suite_digest: Digest
    config_digest: Digest = CONFIG_DIGEST
    target_profile_ref: Literal["target-profile:disposable-http-json/0.1.0"] = TARGET
    credential_ref: Literal["credential-profile:ephemeral-fixture/0.1.0"] = CREDENTIAL
    risk_class: Literal["read-only-non-production"] = "read-only-non-production"
    heal: Literal[False] = False
    models: Literal[False] = False
    skip_policy: Literal["no-required-skips"] = "no-required-skips"
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 15

    @model_validator(mode="after")
    def frozen_suite(self):
        if (
            len({c.case_id for c in self.cases}) != len(self.cases)
            or len({(c.criterion_node_id, c.criterion_index) for c in self.cases}) != len(self.cases)
            or self.suite_digest != "sha256:" + hashlib.sha256(suite_bytes(self.cases)).hexdigest()
            or self.config_digest != CONFIG_DIGEST
        ):
            raise ValueError("Frozen suite/config or unique case/criterion identities do not match.")
        return self


class CreateReplayPlan(Closed):
    source_task_id: UUID
    artifact_id: UUID
    contract_reference: ContractReference
    file: Annotated[str, Field(min_length=1, max_length=255)]
    cases: list[ReplayCase] = Field(min_length=1, max_length=16)
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=60)] = 15
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:-]+$")]


class ReplayObservation(Observation):
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)]
    response_digest: Digest
    outcome: Literal["PASS", "FAIL"]


class ReplayReceipt(Closed):
    schema_version: Literal["0.1"]
    execution_id: UUID
    plan_digest: Digest
    candidate_digest: Digest
    suite_digest: Digest
    config_digest: Digest
    runner_ref: Literal["runner:adlc-http-json-replay/0.1.0"]
    runner_digest: Digest
    provider: Literal["local-http-fixture"]
    target_profile_ref: Literal["target-profile:disposable-http-json/0.1.0"]
    credential_ref: Literal["credential-profile:ephemeral-fixture/0.1.0"]
    target_instance_id: UUID
    target_origin: Annotated[str, Field(pattern=r"^http://127\.0\.0\.1:[1-9][0-9]{0,4}$")]
    target_released: Literal[True]
    heal: Literal[False]
    models_used: Literal[False]
    tests_run: Annotated[int, Field(strict=True, ge=0, le=16)]
    completion_mode: Literal["process-exit", "durable-checkpoint"]
    exit_code: Annotated[int, Field(strict=True)] | None
    observations: list[ReplayObservation] = Field(max_length=16)
    junit_xml: Annotated[str, Field(max_length=MAX_JUNIT_BYTES)]
    junit_digest: Digest
    started_at: datetime
    completed_at: datetime

    @field_validator("junit_xml")
    @classmethod
    def xml_size(cls, value):
        if len(value.encode("utf-8")) > MAX_JUNIT_BYTES:
            raise ValueError("JUnit exceeds the evidence limit.")
        return value

    @model_validator(mode="after")
    def bindings(self):
        if (
            not self.started_at.tzinfo
            or not self.completed_at.tzinfo
            or self.completed_at < self.started_at
            or self.target_instance_id != self.execution_id
            or int(self.target_origin.rsplit(":", 1)[-1]) > MAX_PORT
        ):
            raise ValueError("Receipt target and ordered timezone-aware timestamps must match.")
        return self


class ReplayComparison(Closed):
    case_id: str
    pointer: str
    expected: Scalar
    observed: Scalar
    found: StrictBool
    expected_status: int
    observed_status: int
    passed: StrictBool


class ReplayReport(Closed):
    schema_version: Literal["0.1"] = "0.1"
    plan_digest: Digest
    receipt_digest: Digest
    candidate_digest: Digest
    suite_digest: Digest
    config_digest: Digest
    junit_digest: Digest
    verdict: Literal["PASS", "FAIL"]
    comparator_ref: Literal["validator:http-json-replay/0.1.0"] = "validator:http-json-replay/0.1.0"
    natural_language_enforced: Literal[False] = False
    contract_fully_verified: Literal[False] = False
    application_verified: Literal[False] = False
    required_cases: int
    completed_cases: int
    checks: list[ReplayComparison] = Field(min_length=1, max_length=16)


class ReplayRead(Closed):
    plan: ReplayPlan
    plan_digest: Digest
    state: Literal[
        "DRAFT",
        "APPROVED",
        "RUNNING",
        "DISPATCH_UNCERTAIN",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "READY_FOR_SUBMISSION",
        "SUBMITTED",
        "NOT_VERIFIED",
    ]
    approved_by: str | None = None
    approved_at: datetime | None = None
    execution_id: UUID | None = None
    receipt: ReplayReceipt | None = None
    report: ReplayReport | None = None
    error_code: str | None = None
    evidence_digest: Digest | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    cancel_requested_by: str | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None


class ReplayCapabilities(Closed):
    enabled: bool
    human_actions_configured: bool
    worker_ready: bool
    profile_ref: str = PROFILE
    provider: str | None = None
    testforge_ready: Literal[False] = False
    testforge_blockers: list[str] = Field(
        default_factory=lambda: [
            "BACKEND_SOURCE_AND_REVISION_REQUIRED",
            "BROKER_REACHABILITY_UNCONFIRMED",
            "TYPED_MATERIALIZATION_EVIDENCE_IDEMPOTENCY_CANCEL_REQUIRED",
            "NO_MODEL_NO_HEAL_ROUTING_UNREVIEWED",
        ]
    )
    scope_description: str = (
        "Frozen GET /fixture assertions against a disposable authenticated loopback JSON target. "
        "No project application, browser automation, TestForge backend, model or production account is executed."
    )


def validate_junit(receipt, cases, passed):
    """Strict bounded JUnit dialect of our pinned runner, not arbitrary runner HTML/logs."""
    raw = receipt.junit_xml.encode("utf-8")
    if len(raw) > MAX_JUNIT_BYTES or "sha256:" + hashlib.sha256(raw).hexdigest() != receipt.junit_digest:
        raise VerificationError("REPLAY_JUNIT_MISMATCH")
    try:
        root = DefusedElementTree.fromstring(raw, forbid_dtd=True)
        if (
            root.tag != "testsuite"
            or root.attrib
            != {
                "name": "adlc-http-json-replay",
                "tests": str(len(cases)),
                "failures": str(sum(not p for p in passed)),
                "errors": "0",
                "skipped": "0",
            }
            or len(root) != len(cases)
        ):
            raise ValueError
        for item, case, success in zip(root, cases, passed, strict=True):
            if item.tag != "testcase" or item.attrib != {"classname": "http-json-fixture", "name": case.case_id}:
                raise ValueError
            if success:
                if len(item):
                    raise ValueError
            elif (
                len(item) != 1
                or item[0].tag != "failure"
                or item[0].attrib != {"type": "AssertionError"}
                or len(item[0])
            ):
                raise ValueError
    except (DefusedXmlException, DefusedElementTree.ParseError, ValueError, TypeError, RecursionError):
        raise VerificationError("REPLAY_JUNIT_COVERAGE_INVALID") from None


def compare_replay(plan: ReplayPlan, receipt: ReplayReceipt, runner_digest: str) -> ReplayReport:
    # Revalidate even if an internal caller supplied model_copy/construct.
    try:
        plan = ReplayPlan.model_validate(plan.model_dump(mode="json"))
        receipt = ReplayReceipt.model_validate(receipt.model_dump(mode="json"))
    except ValueError:
        raise VerificationError("REPLAY_EVIDENCE_INVALID") from None
    if (
        receipt.plan_digest != digest(plan)
        or receipt.candidate_digest != plan.candidate.content_digest
        or receipt.runner_digest != runner_digest
        or receipt.suite_digest != plan.suite_digest
        or receipt.config_digest != plan.config_digest
        or receipt.tests_run != len(plan.cases)
        or len(receipt.observations) != len(plan.cases)
    ):
        raise VerificationError("REPLAY_EVIDENCE_MISMATCH")
    checks = []
    for case, observation in zip(plan.cases, receipt.observations, strict=True):
        if (
            case.case_id != observation.case_id
            or case.pointer != observation.pointer
            or observation.response_digest != plan.candidate.content_digest
            or (not observation.found and observation.observed is not None)
        ):
            raise VerificationError("REPLAY_CASE_COVERAGE_MISMATCH")
        numeric = isinstance(case.expected, (int, float)) and not isinstance(case.expected, bool)
        actual_numeric = isinstance(observation.observed, (int, float)) and not isinstance(observation.observed, bool)
        passed = (
            observation.http_status == case.expected_status
            and observation.found
            and (
                case.expected == observation.observed
                if numeric and actual_numeric
                else canonical(case.expected) == canonical(observation.observed)
            )
        )
        if observation.outcome != ("PASS" if passed else "FAIL"):
            raise VerificationError("REPLAY_ASSERTION_MISMATCH")
        checks.append(
            ReplayComparison(
                case_id=case.case_id,
                pointer=case.pointer,
                expected=case.expected,
                observed=observation.observed,
                found=observation.found,
                expected_status=case.expected_status,
                observed_status=observation.http_status,
                passed=passed,
            )
        )
    validate_junit(receipt, plan.cases, [c.passed for c in checks])
    failed = any(not c.passed for c in checks)
    if (
        receipt.exit_code != (1 if failed else 0)
        if receipt.completion_mode == "process-exit"
        else receipt.exit_code is not None
    ):
        raise VerificationError("REPLAY_EXIT_STATUS_MISMATCH")
    return ReplayReport(
        plan_digest=digest(plan),
        receipt_digest=digest(receipt),
        candidate_digest=plan.candidate.content_digest,
        suite_digest=plan.suite_digest,
        config_digest=plan.config_digest,
        junit_digest=receipt.junit_digest,
        verdict="FAIL" if failed else "PASS",
        required_cases=len(plan.cases),
        completed_cases=len(checks),
        checks=checks,
    )

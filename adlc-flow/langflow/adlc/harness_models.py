"""Versioned contracts for the ADLC-to-Harness execution boundary."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from langflow.adlc.models import Artifact, ServiceError, TaskMetrics, TaskResultStatus

HARNESS_CONTRACT_VERSION = "0.1"

NonEmptyString = Annotated[str, Field(min_length=1)]
SemanticVersion = Annotated[
    str,
    Field(
        min_length=5,
        max_length=128,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ClosedHarnessModel(BaseModel):
    """Reject unknown fields on every public Harness payload."""

    model_config = ConfigDict(extra="forbid")


class HarnessSessionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    WAITING_INTERACTION = "WAITING_INTERACTION"
    VERIFYING = "VERIFYING"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    DELIVERING = "DELIVERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HarnessSubmissionMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class HarnessVerificationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class HarnessInteractionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class HarnessInteractionKind(str, Enum):
    APPROVAL = "APPROVAL"
    FORM = "FORM"


class HarnessDeliveryStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    DEAD_LETTER = "DEAD_LETTER"


class HarnessPluginIntegrityStatus(str, Enum):
    EXACT = "EXACT"
    MISSING = "MISSING"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    LOCK_INVALID = "LOCK_INVALID"
    UNREADABLE = "UNREADABLE"


class TaskAttemptStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    WAITING_INTERACTION = "WAITING_INTERACTION"
    VERIFYING = "VERIFYING"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    RESULT_RECEIVED = "RESULT_RECEIVED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HarnessCorrelation(ClosedHarnessModel):
    request_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID


class HarnessPluginLockEntry(ClosedHarnessModel):
    plugin_id: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9@][A-Za-z0-9@._/-]*$")]
    version: SemanticVersion
    content_digest: Sha256Digest
    required: bool = True


class HarnessPluginIntegrityEntry(ClosedHarnessModel):
    plugin_id: NonEmptyString
    required: bool
    expected_version: str
    expected_digest: str
    installed_version: str | None = None
    installed_digest: str | None = None
    status: HarnessPluginIntegrityStatus


class HarnessPluginInventory(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    ready: bool
    checked_at: datetime
    error_code: str | None = None
    plugins: list[HarnessPluginIntegrityEntry] = Field(default_factory=list)


class HarnessExecutionSpec(ClosedHarnessModel):
    profile_ref: NonEmptyString
    operation: NonEmptyString
    plugin_lock: list[HarnessPluginLockEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_plugins(self) -> HarnessExecutionSpec:
        plugin_ids = [entry.plugin_id for entry in self.plugin_lock]
        if len(plugin_ids) != len(set(plugin_ids)):
            msg = "plugin_lock plugin_id values must be unique"
            raise ValueError(msg)
        return self


class HarnessSessionRequest(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    correlation: HarnessCorrelation
    idempotency_key: Annotated[str, Field(min_length=1, max_length=255)]
    objective: NonEmptyString
    input: Any
    context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    execution: HarnessExecutionSpec
    result_schema_ref: NonEmptyString
    submission_mode: HarnessSubmissionMode = HarnessSubmissionMode.AUTO
    callback_ref: NonEmptyString = "adlc-primary"
    metadata: dict[str, Any] = Field(default_factory=dict)


class HarnessVerificationCheck(ClosedHarnessModel):
    check_id: NonEmptyString
    status: HarnessVerificationStatus
    summary: NonEmptyString
    evidence_artifact_refs: list[dict[str, Any]] = Field(default_factory=list)


class HarnessVerificationReport(ClosedHarnessModel):
    verifier_ref: NonEmptyString
    status: HarnessVerificationStatus
    checks: list[HarnessVerificationCheck] = Field(default_factory=list)
    evidence_artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> HarnessVerificationReport:
        if self.completed_at < self.started_at:
            msg = "verification completed_at must not precede started_at"
            raise ValueError(msg)
        return self


class HarnessInteractionRecord(ClosedHarnessModel):
    interaction_id: UUID
    kind: HarnessInteractionKind
    status: HarnessInteractionStatus
    title: NonEmptyString
    prompt: NonEmptyString
    schema_ref: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    resolved_at: datetime | None = None
    response: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HarnessInteractionResponse(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    response: dict[str, Any]


class HarnessInteractionReceipt(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session_id: NonEmptyString
    interaction: HarnessInteractionRecord
    status: HarnessSessionStatus
    replayed: bool = False


class HarnessSessionResult(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session_id: NonEmptyString
    correlation: HarnessCorrelation
    status: TaskResultStatus
    output: Any
    artifacts: list[Artifact]
    verification_reports: list[HarnessVerificationReport] = Field(default_factory=list)
    interaction_records: list[HarnessInteractionRecord] = Field(default_factory=list)
    plugin_lock: list[HarnessPluginLockEntry] = Field(default_factory=list)
    metrics: TaskMetrics | None = None
    trace_ref: str | None = None
    error: ServiceError | None
    started_at: datetime
    completed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_terminal_result(self) -> HarnessSessionResult:
        if self.completed_at < self.started_at:
            msg = "completed_at must not precede started_at"
            raise ValueError(msg)
        if self.status is TaskResultStatus.SUCCEEDED and self.error is not None:
            msg = "a successful Harness result cannot contain an error"
            raise ValueError(msg)
        if self.status in {TaskResultStatus.FAILED, TaskResultStatus.CANCELLED} and self.error is None:
            msg = "a failed or cancelled Harness result requires an error"
            raise ValueError(msg)
        return self


class HarnessArtifactRead(ClosedHarnessModel):
    """Authenticated, out-of-band bytes for one prepared source-patch artifact."""

    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session_id: NonEmptyString
    correlation: HarnessCorrelation
    artifact: Artifact
    payload_base64: Annotated[str, Field(min_length=1, max_length=699_052)]


class HarnessSessionEvent(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    event_id: UUID
    session_id: NonEmptyString
    sequence: Annotated[int, Field(ge=1)]
    event_type: NonEmptyString
    previous_status: HarnessSessionStatus | None = None
    status: HarnessSessionStatus
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class HarnessSessionRead(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session_id: NonEmptyString
    correlation: HarnessCorrelation
    idempotency_key: NonEmptyString
    status: HarnessSessionStatus
    submission_mode: HarnessSubmissionMode
    events: list[HarnessSessionEvent] = Field(default_factory=list)
    interactions: list[HarnessInteractionRecord] = Field(default_factory=list)
    result: HarnessSessionResult | None = None
    delivery_id: UUID | None = None
    delivery_status: HarnessDeliveryStatus | None = None
    created_at: datetime
    updated_at: datetime


class HarnessSessionAccepted(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session: HarnessSessionRead
    replayed: bool = False


class HarnessSubmissionReceipt(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    session_id: NonEmptyString
    status: HarnessSessionStatus
    delivery_id: UUID
    delivery_status: HarnessDeliveryStatus
    replayed: bool = False


class HarnessResultDelivery(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    delivery_id: UUID
    callback_ref: NonEmptyString
    created_at: datetime
    result: HarnessSessionResult


class HarnessCallbackReceipt(ClosedHarnessModel):
    schema_version: Literal["0.1"] = HARNESS_CONTRACT_VERSION
    delivery_id: UUID
    attempt_id: UUID
    accepted: bool = True
    duplicate: bool = False


class TaskAttemptRecord(ClosedHarnessModel):
    """Coordinator-side projection for one external Harness execution attempt."""

    attempt_id: UUID
    request_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    idempotency_key: NonEmptyString
    status: TaskAttemptStatus
    external_session_id: str | None = None
    result: HarnessSessionResult | None = None
    created_at: datetime
    updated_at: datetime


class HarnessRunSessionProjection(ClosedHarnessModel):
    attempt_id: UUID
    task_run_id: UUID
    attempt_status: TaskAttemptStatus
    session: HarnessSessionRead


class HarnessRunResultProjection(ClosedHarnessModel):
    """Accepted result retained by ADLC, independent of the live Harness session."""

    attempt_id: UUID
    task_run_id: UUID
    attempt_status: TaskAttemptStatus
    result: HarnessSessionResult
    stored_at: datetime


class HarnessReconciliationReport(ClosedHarnessModel):
    inspected: Annotated[int, Field(ge=0)] = 0
    recovered_results: Annotated[int, Field(ge=0)] = 0
    submitted_sessions: Annotated[int, Field(ge=0)] = 0
    unavailable_sessions: Annotated[int, Field(ge=0)] = 0

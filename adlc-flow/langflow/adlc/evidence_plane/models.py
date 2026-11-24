"""Evidence Plane data models.

The Evidence Plane is the single source of truth for execution evidence
(patches, logs, test results, screenshots, callbacks). It extends the
existing Artifact concept with validation status, retention policy, and
a queryable schema.

This module is additive: existing Artifact usage in models.py and
artifact_payload_store.py continues to work unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from langflow.adlc.models import Artifact, Checksum, CONTRACT_VERSION


class EvidenceType(str, Enum):
    """Stable taxonomy of evidence kinds accepted by the Evidence Plane."""

    PATCH = "patch"
    LOG = "log"
    TEST_RESULT = "test_result"
    SCREENSHOT = "screenshot"
    CALLBACK = "callback"
    METRIC = "metric"


class ValidationStatus(str, Enum):
    """Lifecycle of an evidence item's validation."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"


class RetentionPolicy(str, Enum):
    """How long an evidence item should be retained."""

    TRANSIENT = "transient"  # in-memory only, lost on restart
    TASK = "task"  # retained until task run completes
    RUN = "run"  # retained until workflow run completes
    PERMANENT = "permanent"  # retained indefinitely


# Default retention durations for each policy.
_RETENTION_DEFAULTS: dict[RetentionPolicy, timedelta | None] = {
    RetentionPolicy.TRANSIENT: timedelta(hours=1),
    RetentionPolicy.TASK: timedelta(hours=24),
    RetentionPolicy.RUN: timedelta(days=7),
    RetentionPolicy.PERMANENT: None,
}


def default_retention_for(policy: RetentionPolicy) -> timedelta | None:
    """Return the default retention duration for a policy."""
    return _RETENTION_DEFAULTS[policy]


class Evidence(BaseModel):
    """A single piece of execution evidence stored in the Evidence Plane.

    Extends Artifact with validation status, retention policy, and a
    stable evidence_type discriminator. Backward compatible: every
    Evidence can be projected to an Artifact via ``to_artifact()``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.1"] = CONTRACT_VERSION
    evidence_id: UUID = Field(default_factory=uuid4)
    evidence_type: EvidenceType
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_errors: tuple[str, ...] = Field(default=(), max_length=64)
    retention_policy: RetentionPolicy = RetentionPolicy.RUN
    producer: str  # agent_id or service_name that produced this evidence
    submitted_at: datetime
    expires_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    # Linkage to the run/task that produced this evidence.
    workflow_run_id: UUID | None = None
    task_run_id: UUID | None = None
    attempt_id: UUID | None = None

    @field_validator("submitted_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "submitted_at must include a timezone"
            raise ValueError(msg)
        return value

    def to_artifact(self) -> Artifact:
        """Project this Evidence to the legacy Artifact shape.

        Preserves backward compatibility with code that still consumes
        Artifact directly (e.g. quality_gate.py, run_service.py).
        """
        return Artifact(
            schema_version=CONTRACT_VERSION,
            artifact_id=self.evidence_id,
            workflow_run_id=self.workflow_run_id or uuid4(),
            task_run_id=self.task_run_id or uuid4(),
            attempt_id=self.attempt_id or uuid4(),
            kind=self.evidence_type.value,
            name=self.producer,
            media_type="application/json",
            uri=f"evidence://{self.evidence_id}",
            size_bytes=0,
            checksum=Checksum(algorithm="SHA256", value="0" * 64),  # placeholder; real checksum computed by store
            producer=self.producer,
            created_at=self.submitted_at,
            expires_at=self.expires_at,
            metadata={
                "validation_status": self.validation_status.value,
                "validation_errors": list(self.validation_errors),
                "retention_policy": self.retention_policy.value,
                **self.payload,
            },
        )


class EvidenceQuery(BaseModel):
    """Filter for querying the Evidence Plane.

    All fields are optional; an empty query returns all evidence.
    """

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: UUID | None = None
    task_run_id: UUID | None = None
    attempt_id: UUID | None = None
    evidence_types: tuple[EvidenceType, ...] = Field(default=(), max_length=16)
    validation_statuses: tuple[ValidationStatus, ...] = Field(default=(), max_length=16)
    producers: tuple[str, ...] = Field(default=(), max_length=64)
    submitted_after: datetime | None = None
    submitted_before: datetime | None = None
    include_expired: bool = False
    limit: int = Field(default=1000, ge=1, le=10000)


class EvidenceReceipt(BaseModel):
    """Returned by EvidenceStore.submit() to confirm acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    accepted: bool
    validation_status: ValidationStatus
    validation_errors: tuple[str, ...] = Field(default=(), max_length=64)
    stored_at: datetime


class EvidenceValidationResult(BaseModel):
    """Outcome of running an EvidenceValidator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    is_valid: bool
    status: ValidationStatus
    errors: tuple[str, ...] = Field(default=(), max_length=64)
    validated_at: datetime


class EvidenceSummary(BaseModel):
    """Aggregate counts for a workflow run's evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_run_id: UUID
    total_count: int
    by_type: dict[str, int]
    by_validation_status: dict[str, int]
    has_invalid: bool


__all__ = [
    "Evidence",
    "EvidenceQuery",
    "EvidenceReceipt",
    "EvidenceSummary",
    "EvidenceType",
    "EvidenceValidationResult",
    "RetentionPolicy",
    "ValidationStatus",
    "default_retention_for",
]

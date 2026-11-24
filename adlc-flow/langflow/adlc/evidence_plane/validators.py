"""Evidence Plane validators.

Each validator checks one aspect of an Evidence item and returns a
EvidenceValidationResult. Validators are composable: the EvidencePlaneService
runs all registered validators and aggregates results.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from langflow.adlc.evidence_plane.models import (
    Evidence,
    EvidenceType,
    EvidenceValidationResult,
    ValidationStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@runtime_checkable
class EvidenceValidator(Protocol):
    """Validator port for the Evidence Plane."""

    @property
    def validator_id(self) -> str:
        """Stable identifier for this validator (e.g. 'patch-format-v1')."""
        ...

    def supports(self, evidence: Evidence) -> bool:
        """Return whether this validator applies to the given evidence."""
        ...

    def validate(self, evidence: Evidence) -> EvidenceValidationResult:
        """Validate the evidence and return the result."""
        ...


# Stable error codes used by validators.
ERR_PATCH_MISSING_FILES = "EVIDENCE_PATCH_MISSING_FILES"
ERR_PATCH_INVALID_DIFF = "EVIDENCE_PATCH_INVALID_DIFF"
ERR_TEST_RESULT_MISSING_OUTCOME = "EVIDENCE_TEST_RESULT_MISSING_OUTCOME"
ERR_TEST_RESULT_INVALID_OUTCOME = "EVIDENCE_TEST_RESULT_INVALID_OUTCOME"
ERR_LOG_CONTAINS_SECRET = "EVIDENCE_LOG_CONTAINS_SECRET"
ERR_LOG_EMPTY = "EVIDENCE_LOG_EMPTY"
ERR_PAYLOAD_MISSING_REQUIRED = "EVIDENCE_PAYLOAD_MISSING_REQUIRED"
ERR_PAYLOAD_TYPE_MISMATCH = "EVIDENCE_PAYLOAD_TYPE_MISMATCH"


# Patterns that indicate a secret in a log payload.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)password\s*[=:]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)secret\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style keys
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub PAT
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
)


class PatchFormatValidator:
    """Validates that a patch evidence item has well-formed diff data."""

    @property
    def validator_id(self) -> str:
        return "patch-format-v1"

    def supports(self, evidence: Evidence) -> bool:
        return evidence.evidence_type is EvidenceType.PATCH

    def validate(self, evidence: Evidence) -> EvidenceValidationResult:
        errors: list[str] = []
        files = evidence.payload.get("files")
        if not files or not isinstance(files, list):
            errors.append(ERR_PATCH_MISSING_FILES)
        elif not all(isinstance(f, dict) and "patch" in f for f in files):
            errors.append(ERR_PATCH_INVALID_DIFF)
        return EvidenceValidationResult(
            evidence_id=evidence.evidence_id,
            is_valid=not errors,
            status=ValidationStatus.VALID if not errors else ValidationStatus.INVALID,
            errors=tuple(errors),
            validated_at=_utc_now(),
        )


class TestResultValidator:
    """Validates that a test_result evidence item has a recognized outcome."""

    _VALID_OUTCOMES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR"})

    @property
    def validator_id(self) -> str:
        return "test-result-v1"

    def supports(self, evidence: Evidence) -> bool:
        return evidence.evidence_type is EvidenceType.TEST_RESULT

    def validate(self, evidence: Evidence) -> EvidenceValidationResult:
        errors: list[str] = []
        outcome = evidence.payload.get("outcome")
        if outcome is None:
            errors.append(ERR_TEST_RESULT_MISSING_OUTCOME)
        elif outcome not in self._VALID_OUTCOMES:
            errors.append(ERR_TEST_RESULT_INVALID_OUTCOME)
        return EvidenceValidationResult(
            evidence_id=evidence.evidence_id,
            is_valid=not errors,
            status=ValidationStatus.VALID if not errors else ValidationStatus.INVALID,
            errors=tuple(errors),
            validated_at=_utc_now(),
        )


class LogSecretValidator:
    """Validates that a log evidence item does not contain secrets."""

    @property
    def validator_id(self) -> str:
        return "log-secret-v1"

    def supports(self, evidence: Evidence) -> bool:
        return evidence.evidence_type is EvidenceType.LOG

    def validate(self, evidence: Evidence) -> EvidenceValidationResult:
        errors: list[str] = []
        content = evidence.payload.get("content", "")
        if not content:
            errors.append(ERR_LOG_EMPTY)
        else:
            for pattern in _SECRET_PATTERNS:
                if pattern.search(str(content)):
                    errors.append(ERR_LOG_CONTAINS_SECRET)
                    break
        return EvidenceValidationResult(
            evidence_id=evidence.evidence_id,
            is_valid=not errors,
            status=ValidationStatus.VALID if not errors else ValidationStatus.INVALID,
            errors=tuple(errors),
            validated_at=_utc_now(),
        )


class PayloadSchemaValidator:
    """Validates that an evidence payload contains required keys with correct types."""

    def __init__(self, required_keys: dict[EvidenceType, dict[str, type]]) -> None:
        self._required_keys = required_keys

    @property
    def validator_id(self) -> str:
        return "payload-schema-v1"

    def supports(self, evidence: Evidence) -> bool:
        return evidence.evidence_type in self._required_keys

    def validate(self, evidence: Evidence) -> EvidenceValidationResult:
        errors: list[str] = []
        required = self._required_keys.get(evidence.evidence_type, {})
        for key, expected_type in required.items():
            if key not in evidence.payload:
                errors.append(f"{ERR_PAYLOAD_MISSING_REQUIRED}:{key}")
                continue
            value = evidence.payload[key]
            # bool is a subclass of int; exclude it explicitly.
            if expected_type is int and isinstance(value, bool):
                errors.append(f"{ERR_PAYLOAD_TYPE_MISMATCH}:{key}")
                continue
            if not isinstance(value, expected_type):
                errors.append(f"{ERR_PAYLOAD_TYPE_MISMATCH}:{key}")
        return EvidenceValidationResult(
            evidence_id=evidence.evidence_id,
            is_valid=not errors,
            status=ValidationStatus.VALID if not errors else ValidationStatus.INVALID,
            errors=tuple(errors),
            validated_at=_utc_now(),
        )


# Default validator set used by EvidencePlaneService.
DEFAULT_VALIDATORS: tuple[EvidenceValidator, ...] = (
    PatchFormatValidator(),
    TestResultValidator(),
    LogSecretValidator(),
)


__all__ = [
    "DEFAULT_VALIDATORS",
    "ERR_LOG_CONTAINS_SECRET",
    "ERR_LOG_EMPTY",
    "ERR_PATCH_INVALID_DIFF",
    "ERR_PATCH_MISSING_FILES",
    "ERR_PAYLOAD_MISSING_REQUIRED",
    "ERR_PAYLOAD_TYPE_MISMATCH",
    "ERR_TEST_RESULT_INVALID_OUTCOME",
    "ERR_TEST_RESULT_MISSING_OUTCOME",
    "EvidenceValidator",
    "LogSecretValidator",
    "PatchFormatValidator",
    "PayloadSchemaValidator",
    "TestResultValidator",
]

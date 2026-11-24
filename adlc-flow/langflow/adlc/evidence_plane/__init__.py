"""Evidence Plane — single source of truth for execution evidence.

The Evidence Plane separates evidence storage, validation, and querying
from the execution path. It is additive: existing Artifact usage in
models.py and artifact_payload_store.py continues to work unchanged.

Public API:
- Evidence, EvidenceQuery, EvidenceReceipt, EvidenceSummary, EvidenceValidationResult
- EvidenceType, ValidationStatus, RetentionPolicy
- EvidenceStore (Protocol), InMemoryEvidenceStore, SQLEvidenceStore
- EvidenceValidator (Protocol), DEFAULT_VALIDATORS, built-in validators
- EvidencePlaneService, get_default_evidence_plane
"""

from langflow.adlc.evidence_plane.models import (
    Evidence,
    EvidenceQuery,
    EvidenceReceipt,
    EvidenceSummary,
    EvidenceType,
    EvidenceValidationResult,
    RetentionPolicy,
    ValidationStatus,
    default_retention_for,
)
from langflow.adlc.evidence_plane.service import (
    EvidencePlaneService,
    get_default_evidence_plane,
    reset_default_evidence_plane,
)
from langflow.adlc.evidence_plane.store import (
    EvidenceStore,
    InMemoryEvidenceStore,
    SQLEvidenceStore,
)
from langflow.adlc.evidence_plane.validators import (
    DEFAULT_VALIDATORS,
    ERR_LOG_CONTAINS_SECRET,
    ERR_LOG_EMPTY,
    ERR_PATCH_INVALID_DIFF,
    ERR_PATCH_MISSING_FILES,
    ERR_PAYLOAD_MISSING_REQUIRED,
    ERR_PAYLOAD_TYPE_MISMATCH,
    ERR_TEST_RESULT_INVALID_OUTCOME,
    ERR_TEST_RESULT_MISSING_OUTCOME,
    EvidenceValidator,
    LogSecretValidator,
    PatchFormatValidator,
    PayloadSchemaValidator,
    TestResultValidator,
)

__all__ = [
    # Models
    "Evidence",
    "EvidenceQuery",
    "EvidenceReceipt",
    "EvidenceSummary",
    "EvidenceType",
    "EvidenceValidationResult",
    "RetentionPolicy",
    "ValidationStatus",
    "default_retention_for",
    # Store
    "EvidenceStore",
    "InMemoryEvidenceStore",
    "SQLEvidenceStore",
    # Validators
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
    # Service
    "EvidencePlaneService",
    "get_default_evidence_plane",
    "reset_default_evidence_plane",
]

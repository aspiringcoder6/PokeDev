"""Evidence Plane high-level service.

Provides a single entry point for submitting, validating, and querying
evidence. Composes a store with a set of validators and exposes a
summary API for orchestrator decisions.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID

from langflow.adlc.evidence_plane.models import (
    Evidence,
    EvidenceQuery,
    EvidenceReceipt,
    EvidenceSummary,
    EvidenceValidationResult,
    EvidenceType,
    ValidationStatus,
)
from langflow.adlc.evidence_plane.store import EvidenceStore, InMemoryEvidenceStore
from langflow.adlc.evidence_plane.validators import (
    DEFAULT_VALIDATORS,
    EvidenceValidator,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidencePlaneService:
    """High-level facade for the Evidence Plane.

    Composes an EvidenceStore with a set of EvidenceValidators. The
    submit_evidence() method runs all applicable validators and stores
    the result with the final validation status.
    """

    def __init__(
        self,
        store: EvidenceStore | None = None,
        validators: Iterable[EvidenceValidator] | None = None,
    ) -> None:
        self._store: EvidenceStore = store or InMemoryEvidenceStore()
        self._validators: tuple[EvidenceValidator, ...] = tuple(
            validators if validators is not None else DEFAULT_VALIDATORS
        )

    @property
    def store(self) -> EvidenceStore:
        return self._store

    def submit_evidence(self, evidence: Evidence) -> EvidenceReceipt:
        """Validate and store an evidence item.

        Runs all applicable validators, aggregates results, and stores
        the evidence with the final validation status. If any validator
        marks the evidence INVALID, the stored status is INVALID.
        """
        result = self._run_validators(evidence)
        final_status = result.status
        final_errors = result.errors
        stored = evidence.model_copy(
            update={
                "validation_status": final_status,
                "validation_errors": final_errors,
            }
        )
        receipt = self._store.submit(stored)
        return receipt

    def query_evidence(self, query: EvidenceQuery) -> list[Evidence]:
        """Return evidence matching the query."""
        return self._store.query(query)

    def query_evidence_by_type(
        self, evidence_type: EvidenceType, *, workflow_run_id: UUID | None = None
    ) -> list[Evidence]:
        """Convenience: return all evidence of a given type.

        Args:
            evidence_type: The type to filter by.
            workflow_run_id: Optional run ID to scope the query.
        """
        return self._store.query(
            EvidenceQuery(
                evidence_types=(evidence_type,),
                workflow_run_id=workflow_run_id,
            )
        )

    def get_evidence(self, evidence_id: UUID | str) -> Evidence | None:
        """Return one evidence item by ID."""
        return self._store.get(str(evidence_id))

    def get_validated_evidence(self, workflow_run_id: UUID) -> list[Evidence]:
        """Return all VALID evidence for a workflow run."""
        return self._store.query(
            EvidenceQuery(
                workflow_run_id=workflow_run_id,
                validation_statuses=(ValidationStatus.VALID,),
            )
        )

    def evidence_summary(self, workflow_run_id: UUID) -> EvidenceSummary:
        """Return aggregate counts for a workflow run's evidence."""
        all_evidence = self._store.query(
            EvidenceQuery(workflow_run_id=workflow_run_id, include_expired=True)
        )
        by_type = Counter(e.evidence_type.value for e in all_evidence)
        by_status = Counter(e.validation_status.value for e in all_evidence)
        return EvidenceSummary(
            workflow_run_id=workflow_run_id,
            total_count=len(all_evidence),
            by_type=dict(by_type),
            by_validation_status=dict(by_status),
            has_invalid=by_status.get(ValidationStatus.INVALID.value, 0) > 0,
        )

    def revalidate(self, evidence_id: UUID | str) -> EvidenceValidationResult:
        """Re-run validators on an existing evidence item."""
        evidence = self._store.get(str(evidence_id))
        if evidence is None:
            msg = f"Evidence {evidence_id} not found"
            raise KeyError(msg)
        result = self._run_validators(evidence)
        self._store.mark_validated(
            str(evidence_id), result.status, result.errors
        )
        return result

    def _run_validators(self, evidence: Evidence) -> EvidenceValidationResult:
        """Run all applicable validators and aggregate results."""
        all_errors: list[str] = []
        any_invalid = False
        for validator in self._validators:
            if not validator.supports(evidence):
                continue
            result = validator.validate(evidence)
            all_errors.extend(result.errors)
            if not result.is_valid:
                any_invalid = True
        return EvidenceValidationResult(
            evidence_id=evidence.evidence_id,
            is_valid=not any_invalid,
            status=ValidationStatus.INVALID if any_invalid else ValidationStatus.VALID,
            errors=tuple(all_errors),
            validated_at=_utc_now(),
        )


# Module-level default service for convenience.
_default_service: EvidencePlaneService | None = None


def get_default_evidence_plane() -> EvidencePlaneService:
    """Return a process-wide default EvidencePlaneService instance."""
    global _default_service
    if _default_service is None:
        _default_service = EvidencePlaneService()
    return _default_service


def reset_default_evidence_plane() -> None:
    """Reset the process-wide default service (for tests)."""
    global _default_service
    _default_service = None


__all__ = [
    "EvidencePlaneService",
    "get_default_evidence_plane",
    "reset_default_evidence_plane",
]

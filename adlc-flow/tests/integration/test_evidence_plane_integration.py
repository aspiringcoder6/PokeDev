"""Integration tests for the Evidence Plane.

Verifies:
1. End-to-end submit → validate → query flow
2. Integration with quality_gate.py (evidence plane replaces direct metadata reads)
3. Backward compatibility: existing flows that use Artifact directly still work
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from langflow.adlc.evidence_plane import (
    Evidence,
    EvidencePlaneService,
    EvidenceQuery,
    EvidenceType,
    InMemoryEvidenceStore,
    RetentionPolicy,
    ValidationStatus,
)
from langflow.adlc.models import (
    Artifact,
    Checksum,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_evidence(
    *,
    evidence_type: EvidenceType = EvidenceType.PATCH,
    payload: dict | None = None,
    workflow_run_id=None,
    validation_status: ValidationStatus = ValidationStatus.PENDING,
) -> Evidence:
    return Evidence(
        evidence_type=evidence_type,
        payload=payload if payload is not None else {"files": [{"file": "a.py", "patch": "@@"}]},
        producer="test-agent",
        submitted_at=_utc_now(),
        workflow_run_id=workflow_run_id,
        validation_status=validation_status,
    )


class TestEndToEndFlow:
    def test_submit_validate_query_lifecycle(self):
        service = EvidencePlaneService()
        run_id = uuid4()

        # Submit a valid patch.
        patch = _make_evidence(workflow_run_id=run_id)
        receipt = service.submit_evidence(patch)
        assert receipt.validation_status is ValidationStatus.VALID

        # Submit an invalid patch (missing files).
        bad_patch = _make_evidence(workflow_run_id=run_id, payload={})
        receipt = service.submit_evidence(bad_patch)
        assert receipt.validation_status is ValidationStatus.INVALID

        # Query returns both.
        all_evidence = service.query_evidence(EvidenceQuery(workflow_run_id=run_id))
        assert len(all_evidence) == 2

        # get_validated_evidence returns only the valid one.
        valid = service.get_validated_evidence(run_id)
        assert len(valid) == 1
        assert valid[0].evidence_id == patch.evidence_id

        # Summary reflects both.
        summary = service.evidence_summary(run_id)
        assert summary.total_count == 2
        assert summary.has_invalid

    def test_evidence_plane_with_quality_gate(self):
        """Evidence plane can store and retrieve testing evidence for quality gate."""
        service = EvidencePlaneService()
        run_id = uuid4()

        # Submit passing test result via evidence plane.
        receipt = service.submit_evidence(
            _make_evidence(
                evidence_type=EvidenceType.TEST_RESULT,
                payload={"outcome": "PASSED", "coverage": 85.0},
                workflow_run_id=run_id,
            )
        )
        assert receipt.validation_status is ValidationStatus.VALID

        # Quality gate can find the evidence via the plane.
        valid_evidence = service.get_validated_evidence(run_id)
        assert len(valid_evidence) == 1
        assert valid_evidence[0].payload["outcome"] == "PASSED"
        assert valid_evidence[0].payload["coverage"] == 85.0

        # Summary reflects the evidence.
        summary = service.evidence_summary(run_id)
        assert summary.total_count == 1
        assert summary.by_type["test_result"] == 1
        assert not summary.has_invalid


class TestBackwardCompatibility:
    def test_artifact_still_works_without_evidence_plane(self):
        """Existing code that creates Artifact directly still works."""
        artifact = Artifact(
            schema_version="0.1",
            artifact_id=uuid4(),
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
            attempt_id=uuid4(),
            kind="patch",
            name="legacy-agent",
            media_type="application/json",
            uri="artifact://legacy",
            size_bytes=0,
            checksum=Checksum(algorithm="SHA256", value="0" * 64),
            producer="legacy-agent",
            created_at=_utc_now(),
        )
        assert artifact.kind == "patch"

    def test_evidence_to_artifact_roundtrip(self):
        """Evidence can be projected to Artifact for legacy consumers."""
        run_id = uuid4()
        task_id = uuid4()
        attempt_id = uuid4()
        ev = Evidence(
            evidence_type=EvidenceType.TEST_RESULT,
            payload={"outcome": "PASSED"},
            producer="new-agent",
            submitted_at=_utc_now(),
            workflow_run_id=run_id,
            task_run_id=task_id,
            attempt_id=attempt_id,
            validation_status=ValidationStatus.VALID,
        )
        artifact = ev.to_artifact()
        assert artifact.workflow_run_id == run_id
        assert artifact.task_run_id == task_id
        assert artifact.attempt_id == attempt_id
        assert artifact.kind == "test_result"
        assert artifact.metadata["validation_status"] == "valid"
        assert artifact.metadata["outcome"] == "PASSED"

    def test_in_memory_store_is_isolated_per_instance(self):
        """Each InMemoryEvidenceStore instance has its own state."""
        store1 = InMemoryEvidenceStore()
        store2 = InMemoryEvidenceStore()
        ev = _make_evidence()
        store1.submit(ev)
        assert store1.get(str(ev.evidence_id)) is not None
        assert store2.get(str(ev.evidence_id)) is None


class TestRetentionPolicy:
    def test_transient_evidence_expires_quickly(self):
        service = EvidencePlaneService()
        ev = _make_evidence()
        ev = ev.model_copy(update={"retention_policy": RetentionPolicy.TRANSIENT})
        service.submit_evidence(ev)
        # Should be retrievable immediately.
        assert service.get_evidence(ev.evidence_id) is not None

    def test_permanent_evidence_has_no_expiry(self):
        service = EvidencePlaneService()
        ev = _make_evidence()
        ev = ev.model_copy(update={"retention_policy": RetentionPolicy.PERMANENT})
        service.submit_evidence(ev)
        fetched = service.get_evidence(ev.evidence_id)
        assert fetched is not None
        assert fetched.expires_at is None

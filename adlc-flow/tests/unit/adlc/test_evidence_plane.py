"""Unit tests for the Evidence Plane module."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.evidence_plane import (
    DEFAULT_VALIDATORS,
    ERR_LOG_CONTAINS_SECRET,
    ERR_LOG_EMPTY,
    ERR_PATCH_MISSING_FILES,
    ERR_TEST_RESULT_INVALID_OUTCOME,
    ERR_TEST_RESULT_MISSING_OUTCOME,
    Evidence,
    EvidencePlaneService,
    EvidenceQuery,
    EvidenceType,
    InMemoryEvidenceStore,
    LogSecretValidator,
    PatchFormatValidator,
    PayloadSchemaValidator,
    RetentionPolicy,
    SQLEvidenceStore,
    TestResultValidator,
    ValidationStatus,
    default_retention_for,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_evidence(
    *,
    evidence_type: EvidenceType = EvidenceType.PATCH,
    payload: dict | None = None,
    producer: str = "test-agent",
    workflow_run_id=None,
    task_run_id=None,
    attempt_id=None,
    retention_policy: RetentionPolicy = RetentionPolicy.RUN,
    validation_status: ValidationStatus = ValidationStatus.PENDING,
) -> Evidence:
    return Evidence(
        evidence_type=evidence_type,
        payload=payload if payload is not None else {"files": [{"file": "a.py", "patch": "@@"}]},
        producer=producer,
        submitted_at=_utc_now(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        retention_policy=retention_policy,
        validation_status=validation_status,
    )


class TestEvidenceModels:
    def test_evidence_requires_timezone(self):
        with pytest.raises(ValueError, match="timezone"):
            Evidence(
                evidence_type=EvidenceType.PATCH,
                producer="x",
                submitted_at=datetime.now(),  # naive
            )

    def test_evidence_to_artifact_preserves_fields(self):
        run_id = uuid4()
        task_id = uuid4()
        attempt_id = uuid4()
        ev = _make_evidence(
            workflow_run_id=run_id,
            task_run_id=task_id,
            attempt_id=attempt_id,
        )
        artifact = ev.to_artifact()
        assert artifact.artifact_id == ev.evidence_id
        assert artifact.workflow_run_id == run_id
        assert artifact.task_run_id == task_id
        assert artifact.attempt_id == attempt_id
        assert artifact.kind == "patch"
        assert artifact.metadata["validation_status"] == "pending"

    def test_default_retention_for(self):
        assert default_retention_for(RetentionPolicy.TRANSIENT) == timedelta(hours=1)
        assert default_retention_for(RetentionPolicy.PERMANENT) is None

    def test_evidence_query_rejects_extra_fields(self):
        with pytest.raises(ValueError):
            EvidenceQuery(unknown_field="x")  # type: ignore[call-arg]


class TestInMemoryEvidenceStore:
    def test_submit_and_get(self):
        store = InMemoryEvidenceStore()
        ev = _make_evidence()
        receipt = store.submit(ev)
        assert receipt.accepted
        assert receipt.evidence_id == ev.evidence_id
        fetched = store.get(str(ev.evidence_id))
        assert fetched is not None
        assert fetched.evidence_id == ev.evidence_id

    def test_get_returns_none_for_missing(self):
        store = InMemoryEvidenceStore()
        assert store.get(str(uuid4())) is None

    def test_get_returns_none_for_expired(self):
        store = InMemoryEvidenceStore()
        ev = _make_evidence()
        ev = ev.model_copy(update={"expires_at": _utc_now() - timedelta(seconds=1)})
        store.submit(ev)
        assert store.get(str(ev.evidence_id)) is None

    def test_query_filters_by_workflow_run(self):
        store = InMemoryEvidenceStore()
        run_a, run_b = uuid4(), uuid4()
        store.submit(_make_evidence(workflow_run_id=run_a))
        store.submit(_make_evidence(workflow_run_id=run_b))
        results = store.query(EvidenceQuery(workflow_run_id=run_a))
        assert len(results) == 1
        assert results[0].workflow_run_id == run_a

    def test_query_filters_by_evidence_type(self):
        store = InMemoryEvidenceStore()
        store.submit(_make_evidence(evidence_type=EvidenceType.PATCH))
        store.submit(_make_evidence(evidence_type=EvidenceType.LOG, payload={"content": "ok"}))
        results = store.query(EvidenceQuery(evidence_types=(EvidenceType.LOG,)))
        assert len(results) == 1
        assert results[0].evidence_type is EvidenceType.LOG

    def test_query_respects_limit(self):
        store = InMemoryEvidenceStore()
        for _ in range(5):
            store.submit(_make_evidence())
        results = store.query(EvidenceQuery(limit=2))
        assert len(results) == 2

    def test_mark_validated_updates_status(self):
        store = InMemoryEvidenceStore()
        ev = _make_evidence()
        store.submit(ev)
        store.mark_validated(str(ev.evidence_id), ValidationStatus.VALID)
        fetched = store.get(str(ev.evidence_id))
        assert fetched is not None
        assert fetched.validation_status is ValidationStatus.VALID

    def test_mark_validated_raises_for_missing(self):
        store = InMemoryEvidenceStore()
        with pytest.raises(KeyError):
            store.mark_validated(str(uuid4()), ValidationStatus.VALID)

    def test_count(self):
        store = InMemoryEvidenceStore()
        run_id = uuid4()
        store.submit(_make_evidence(workflow_run_id=run_id))
        store.submit(_make_evidence(workflow_run_id=run_id))
        store.submit(_make_evidence(workflow_run_id=uuid4()))
        assert store.count() == 3
        assert store.count(str(run_id)) == 2


class TestSQLEvidenceStore:
    def test_submit_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLEvidenceStore(Path(tmp) / "evidence.db")
            ev = _make_evidence()
            receipt = store.submit(ev)
            assert receipt.accepted
            fetched = store.get(str(ev.evidence_id))
            assert fetched is not None
            assert fetched.evidence_id == ev.evidence_id

    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "evidence.db"
            store1 = SQLEvidenceStore(db_path)
            ev = _make_evidence()
            store1.submit(ev)
            # New instance reads from same DB.
            store2 = SQLEvidenceStore(db_path)
            fetched = store2.get(str(ev.evidence_id))
            assert fetched is not None

    def test_query_with_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLEvidenceStore(Path(tmp) / "evidence.db")
            run_id = uuid4()
            store.submit(_make_evidence(workflow_run_id=run_id))
            store.submit(_make_evidence(workflow_run_id=uuid4()))
            results = store.query(EvidenceQuery(workflow_run_id=run_id))
            assert len(results) == 1


class TestValidators:
    def test_patch_validator_accepts_well_formed(self):
        v = PatchFormatValidator()
        ev = _make_evidence(payload={"files": [{"file": "a.py", "patch": "@@"}]})
        result = v.validate(ev)
        assert result.is_valid
        assert result.status is ValidationStatus.VALID

    def test_patch_validator_rejects_missing_files(self):
        v = PatchFormatValidator()
        ev = _make_evidence(payload={})
        result = v.validate(ev)
        assert not result.is_valid
        assert ERR_PATCH_MISSING_FILES in result.errors

    def test_test_result_validator_accepts_passed(self):
        v = TestResultValidator()
        ev = _make_evidence(
            evidence_type=EvidenceType.TEST_RESULT,
            payload={"outcome": "PASSED"},
        )
        result = v.validate(ev)
        assert result.is_valid

    def test_test_result_validator_rejects_missing_outcome(self):
        v = TestResultValidator()
        ev = _make_evidence(evidence_type=EvidenceType.TEST_RESULT, payload={})
        result = v.validate(ev)
        assert not result.is_valid
        assert ERR_TEST_RESULT_MISSING_OUTCOME in result.errors

    def test_test_result_validator_rejects_invalid_outcome(self):
        v = TestResultValidator()
        ev = _make_evidence(
            evidence_type=EvidenceType.TEST_RESULT,
            payload={"outcome": "MAYBE"},
        )
        result = v.validate(ev)
        assert not result.is_valid
        assert ERR_TEST_RESULT_INVALID_OUTCOME in result.errors

    def test_log_validator_detects_secret(self):
        v = LogSecretValidator()
        ev = _make_evidence(
            evidence_type=EvidenceType.LOG,
            payload={"content": "api_key=sk-abcdefghijklmnopqrstuvwxyz123456"},
        )
        result = v.validate(ev)
        assert not result.is_valid
        assert ERR_LOG_CONTAINS_SECRET in result.errors

    def test_log_validator_accepts_clean_log(self):
        v = LogSecretValidator()
        ev = _make_evidence(
            evidence_type=EvidenceType.LOG,
            payload={"content": "Build succeeded in 3.2s"},
        )
        result = v.validate(ev)
        assert result.is_valid

    def test_log_validator_rejects_empty(self):
        v = LogSecretValidator()
        ev = _make_evidence(evidence_type=EvidenceType.LOG, payload={})
        result = v.validate(ev)
        assert not result.is_valid
        assert ERR_LOG_EMPTY in result.errors

    def test_payload_schema_validator(self):
        v = PayloadSchemaValidator(
            required_keys={EvidenceType.METRIC: {"value": float, "name": str}}
        )
        ev = _make_evidence(
            evidence_type=EvidenceType.METRIC,
            payload={"value": 1.5, "name": "latency"},
        )
        assert v.validate(ev).is_valid

        ev_bad = _make_evidence(
            evidence_type=EvidenceType.METRIC,
            payload={"value": "not-a-number"},
        )
        assert not v.validate(ev_bad).is_valid

    def test_default_validators_skip_unsupported_types(self):
        ev = _make_evidence(evidence_type=EvidenceType.SCREENSHOT, payload={})
        for v in DEFAULT_VALIDATORS:
            assert not v.supports(ev)


class TestEvidencePlaneService:
    def test_submit_runs_validators(self):
        service = EvidencePlaneService()
        ev = _make_evidence(payload={"files": [{"file": "a.py", "patch": "@@"}]})
        receipt = service.submit_evidence(ev)
        assert receipt.accepted
        assert receipt.validation_status is ValidationStatus.VALID

    def test_submit_marks_invalid_on_validation_failure(self):
        service = EvidencePlaneService()
        ev = _make_evidence(payload={})  # missing files
        receipt = service.submit_evidence(ev)
        assert receipt.validation_status is ValidationStatus.INVALID
        assert ERR_PATCH_MISSING_FILES in receipt.validation_errors

    def test_query_evidence(self):
        service = EvidencePlaneService()
        run_id = uuid4()
        service.submit_evidence(_make_evidence(workflow_run_id=run_id))
        results = service.query_evidence(EvidenceQuery(workflow_run_id=run_id))
        assert len(results) == 1

    def test_get_validated_evidence_filters_invalid(self):
        service = EvidencePlaneService()
        run_id = uuid4()
        service.submit_evidence(
            _make_evidence(workflow_run_id=run_id, payload={"files": [{"file": "a.py", "patch": "@@"}]})
        )
        service.submit_evidence(_make_evidence(workflow_run_id=run_id, payload={}))
        valid = service.get_validated_evidence(run_id)
        assert len(valid) == 1
        assert valid[0].validation_status is ValidationStatus.VALID

    def test_evidence_summary(self):
        service = EvidencePlaneService()
        run_id = uuid4()
        service.submit_evidence(
            _make_evidence(workflow_run_id=run_id, payload={"files": [{"file": "a.py", "patch": "@@"}]})
        )
        service.submit_evidence(_make_evidence(workflow_run_id=run_id, payload={}))
        summary = service.evidence_summary(run_id)
        assert summary.total_count == 2
        assert summary.by_type["patch"] == 2
        assert summary.by_validation_status["valid"] == 1
        assert summary.by_validation_status["invalid"] == 1
        assert summary.has_invalid

    def test_revalidate_updates_status(self):
        service = EvidencePlaneService()
        ev = _make_evidence(payload={})
        service.submit_evidence(ev)
        assert service.get_evidence(ev.evidence_id).validation_status is ValidationStatus.INVALID
        # Patch the payload directly in the store, then revalidate.
        service._store._items[str(ev.evidence_id)] = ev.model_copy(
            update={"payload": {"files": [{"file": "a.py", "patch": "@@"}]}}
        )
        result = service.revalidate(ev.evidence_id)
        assert result.is_valid
        assert service.get_evidence(ev.evidence_id).validation_status is ValidationStatus.VALID

    def test_revalidate_raises_for_missing(self):
        service = EvidencePlaneService()
        with pytest.raises(KeyError):
            service.revalidate(uuid4())

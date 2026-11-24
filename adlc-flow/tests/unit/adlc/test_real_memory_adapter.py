"""Unit tests for the SQLiteMemoryAdapter."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapters.real_memory import (
    SQLiteMemoryAdapter,
    SQLiteMemoryConfig,
)
from langflow.adlc.evidence_plane import (
    EvidencePlaneService,
    InMemoryEvidenceStore,
    reset_default_evidence_plane,
)
from langflow.adlc.models import (
    ExecutorTarget,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_request(
    *,
    workflow_run_id: uuid4 | None = None,
    task_run_id: uuid4 | None = None,
    attempt_id: uuid4 | None = None,
    memory_refs: list[str] | None = None,
    variables: dict | None = None,
) -> TaskRequest:
    context: dict = {}
    if memory_refs is not None:
        context["memory_refs"] = memory_refs
    if variables is not None:
        context["variables"] = variables
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id or uuid4(),
        task_run_id=task_run_id or uuid4(),
        attempt_id=attempt_id or uuid4(),
        task_definition_id=uuid4(),
        task_type="MEMORY_TEST",
        name="memory-test",
        executor=ExecutorTarget(service="memory", operation="test"),
        input={},
        context=context,
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"mem-{uuid4()}",
        requested_at=_utc_now(),
    )


def _make_result(
    *,
    request_id: uuid4 | None = None,
    workflow_run_id: uuid4 | None = None,
    task_run_id: uuid4 | None = None,
    attempt_id: uuid4 | None = None,
) -> TaskResult:
    return TaskResult(
        request_id=request_id or uuid4(),
        workflow_run_id=workflow_run_id or uuid4(),
        task_run_id=task_run_id or uuid4(),
        attempt_id=attempt_id or uuid4(),
        status=TaskResultStatus.SUCCEEDED,
        output={"result": "ok"},
        artifacts=[],
        error=None,
        metrics=TaskMetrics(duration_ms=100),
        started_at=_utc_now(),
        completed_at=_utc_now(),
    )


@pytest.fixture
def evidence_plane():
    reset_default_evidence_plane()
    return EvidencePlaneService(store=InMemoryEvidenceStore())


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "memory.db"


class TestSQLiteMemoryConfig:
    def test_default_config(self):
        config = SQLiteMemoryConfig()
        assert config.db_path is None
        assert config.ttl_seconds is None
        assert config.cleanup_interval_seconds == 3600
        assert config.max_records is None

    def test_custom_config(self):
        config = SQLiteMemoryConfig(
            ttl_seconds=60,
            max_records=100,
        )
        assert config.ttl_seconds == 60
        assert config.max_records == 100


class TestSQLiteMemoryAdapter:
    def test_creates_in_memory_db_by_default(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)
        assert adapter.count_records() == 0

    def test_creates_file_db(self, evidence_plane, temp_db):
        adapter = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(db_path=temp_db),
            evidence_plane=evidence_plane,
        )
        assert adapter.count_records() == 0
        assert temp_db.exists()

    def test_record_and_retrieve(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)
        request = _make_request()
        result = _make_result(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
        )
        asyncio.run(adapter.record_result(request, result))

        record = adapter.get_record(request.attempt_id)
        assert record is not None
        assert record["attempt_id"] == str(request.attempt_id)
        assert record["workflow_run_id"] == str(request.workflow_run_id)

    def test_load_context_with_no_memory_refs(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)
        request = _make_request()
        context = asyncio.run(adapter.load_context(request))
        assert context.memory_refs == ()
        assert context.metadata["adapter"] == "memory:sqlite"

    def test_load_context_with_memory_refs(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        # Record a result first.
        attempt_id = uuid4()
        request1 = _make_request(attempt_id=attempt_id, variables={"key1": "value1"})
        result1 = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter.record_result(request1, result1))

        # Load context with memory_refs pointing to that attempt.
        request2 = _make_request(memory_refs=[str(attempt_id)])
        context = asyncio.run(adapter.load_context(request2))
        assert context.memory_refs == (str(attempt_id),)
        assert context.variables.get("key1") == "value1"

    def test_load_context_falls_back_to_workflow_run(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        # Record a result for a specific workflow.
        workflow_id = uuid4()
        attempt_id = uuid4()
        request1 = _make_request(
            workflow_run_id=workflow_id,
            attempt_id=attempt_id,
            variables={"shared": "data"},
        )
        result1 = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter.record_result(request1, result1))

        # Load context for a new attempt in the same workflow.
        request2 = _make_request(workflow_run_id=workflow_id)
        context = asyncio.run(adapter.load_context(request2))
        assert context.variables.get("shared") == "data"
        assert "previous_run" in context.metadata

    def test_load_context_merges_request_variables(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        # Record a result with some variables.
        attempt_id = uuid4()
        request1 = _make_request(attempt_id=attempt_id, variables={"a": 1, "b": 2})
        result1 = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter.record_result(request1, result1))

        # Load context with overlapping variables.
        request2 = _make_request(
            memory_refs=[str(attempt_id)],
            variables={"b": 20, "c": 30},
        )
        context = asyncio.run(adapter.load_context(request2))
        # Request variables should override stored ones.
        assert context.variables.get("a") == 1
        assert context.variables.get("b") == 20
        assert context.variables.get("c") == 30

    def test_list_records_by_workflow(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        workflow_id = uuid4()
        for _ in range(3):
            request = _make_request(workflow_run_id=workflow_id)
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        records = adapter.list_records(workflow_run_id=workflow_id)
        assert len(records) == 3

    def test_list_records_by_task(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        task_id = uuid4()
        for _ in range(2):
            request = _make_request(task_run_id=task_id)
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        records = adapter.list_records(task_run_id=task_id)
        assert len(records) == 2

    def test_list_records_respects_limit(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        for _ in range(5):
            request = _make_request()
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        records = adapter.list_records(limit=2)
        assert len(records) == 2

    def test_record_updates_existing(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        attempt_id = uuid4()
        request = _make_request(attempt_id=attempt_id)
        result1 = _make_result(attempt_id=attempt_id)
        result2 = _make_result(attempt_id=attempt_id)

        asyncio.run(adapter.record_result(request, result1))
        asyncio.run(adapter.record_result(request, result2))

        assert adapter.count_records() == 1

    def test_ttl_cleanup(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(ttl_seconds=1),
            evidence_plane=evidence_plane,
        )

        request = _make_request()
        result = _make_result(attempt_id=request.attempt_id)
        asyncio.run(adapter.record_result(request, result))

        assert adapter.count_records() == 1

        # Manually set the expires_at to a past time to simulate TTL expiration.
        with adapter._lock:
            with adapter._connect() as conn:
                past = (_utc_now() - timedelta(hours=1)).isoformat()
                conn.execute(
                    "UPDATE memory_records SET expires_at = ?",
                    (past,),
                )
                conn.commit()

        # Manually trigger cleanup.
        deleted = adapter.cleanup_expired()
        assert deleted == 1
        assert adapter.count_records() == 0

    def test_max_records_enforced(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(max_records=3),
            evidence_plane=evidence_plane,
        )

        for _ in range(5):
            request = _make_request()
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        assert adapter.count_records() == 3

    def test_persistence_across_instances(self, evidence_plane, temp_db):
        # First instance: record a result.
        adapter1 = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(db_path=temp_db),
            evidence_plane=evidence_plane,
        )
        attempt_id = uuid4()
        request = _make_request(attempt_id=attempt_id)
        result = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter1.record_result(request, result))

        # Second instance: should see the record.
        adapter2 = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(db_path=temp_db),
            evidence_plane=evidence_plane,
        )
        record = adapter2.get_record(attempt_id)
        assert record is not None

    def test_submits_evidence(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        request = _make_request()
        result = _make_result(attempt_id=request.attempt_id)
        asyncio.run(adapter.record_result(request, result))

        from langflow.adlc.evidence_plane import EvidenceType

        evidence_list = evidence_plane.query_evidence_by_type(EvidenceType.METRIC)
        assert len(evidence_list) >= 1
        assert evidence_list[0].payload["metric"] == "memory_record"

    def test_get_nonexistent_record(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)
        record = adapter.get_record(uuid4())
        assert record is None

    def test_load_context_handles_invalid_json(self, evidence_plane):
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        # Manually insert invalid JSON.
        attempt_id = uuid4()
        with adapter._lock:
            with adapter._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_records (
                        attempt_id, workflow_run_id, task_run_id,
                        memory_refs, variables, metadata,
                        result_json, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(attempt_id),
                        str(uuid4()),
                        str(uuid4()),
                        "not valid json",
                        "not valid json",
                        "not valid json",
                        None,
                        _utc_now().isoformat(),
                        None,
                    ),
                )
                conn.commit()

        # Should not raise, just return empty context.
        request = _make_request(memory_refs=[str(attempt_id)])
        context = asyncio.run(adapter.load_context(request))
        assert context is not None

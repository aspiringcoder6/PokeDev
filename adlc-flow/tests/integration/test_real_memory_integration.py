"""Integration tests for the SQLiteMemoryAdapter.

These tests verify the adapter works end-to-end with the Evidence Plane
and persists data across instances.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapters.real_memory import (
    SQLiteMemoryAdapter,
    SQLiteMemoryConfig,
)
from langflow.adlc.evidence_plane import (
    EvidencePlaneService,
    EvidenceType,
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
        task_type="INTEGRATION_TEST",
        name="integration-memory-test",
        executor=ExecutorTarget(service="memory", operation="integration"),
        input={},
        context=context,
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"int-{uuid4()}",
        requested_at=_utc_now(),
    )


def _make_result(
    *,
    request_id: uuid4 | None = None,
    workflow_run_id: uuid4 | None = None,
    task_run_id: uuid4 | None = None,
    attempt_id: uuid4 | None = None,
    status: TaskResultStatus = TaskResultStatus.SUCCEEDED,
) -> TaskResult:
    return TaskResult(
        request_id=request_id or uuid4(),
        workflow_run_id=workflow_run_id or uuid4(),
        task_run_id=task_run_id or uuid4(),
        attempt_id=attempt_id or uuid4(),
        status=status,
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


class TestSQLiteMemoryIntegration:
    """End-to-end integration tests."""

    def test_full_workflow_record_and_load(self, evidence_plane):
        """Record a result and load it back via memory_refs."""
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        # Step 1: Record a result.
        attempt_id = uuid4()
        request = _make_request(
            attempt_id=attempt_id,
            variables={"step": 1, "data": "initial"},
        )
        result = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter.record_result(request, result))

        # Step 2: Load context for a new attempt referencing the first.
        new_request = _make_request(memory_refs=[str(attempt_id)])
        context = asyncio.run(adapter.load_context(new_request))

        assert context.variables["step"] == 1
        assert context.variables["data"] == "initial"

    def test_multi_step_workflow(self, evidence_plane):
        """Simulate a multi-step workflow where each step builds on the previous."""
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        workflow_id = uuid4()
        previous_attempt = None

        for step in range(1, 4):
            attempt_id = uuid4()
            request = _make_request(
                workflow_run_id=workflow_id,
                attempt_id=attempt_id,
                memory_refs=[str(previous_attempt)] if previous_attempt else None,
                variables={"step": step, "accumulated": list(range(step))},
            )
            result = _make_result(attempt_id=attempt_id)
            asyncio.run(adapter.record_result(request, result))
            previous_attempt = attempt_id

        # Final step should have access to all previous data.
        final_request = _make_request(
            workflow_run_id=workflow_id,
            memory_refs=[str(previous_attempt)],
        )
        context = asyncio.run(adapter.load_context(final_request))
        assert context.variables["step"] == 3
        assert context.variables["accumulated"] == [0, 1, 2]

    def test_persistence_across_instances(self, evidence_plane, temp_db):
        """Data persists across adapter instances."""
        # First instance: record data.
        adapter1 = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(db_path=temp_db),
            evidence_plane=evidence_plane,
        )
        attempt_id = uuid4()
        request = _make_request(attempt_id=attempt_id, variables={"persistent": True})
        result = _make_result(attempt_id=attempt_id)
        asyncio.run(adapter1.record_result(request, result))

        # Second instance: should see the data.
        adapter2 = SQLiteMemoryAdapter(
            config=SQLiteMemoryConfig(db_path=temp_db),
            evidence_plane=evidence_plane,
        )
        record = adapter2.get_record(attempt_id)
        assert record is not None

        # Load context should work too.
        new_request = _make_request(memory_refs=[str(attempt_id)])
        context = asyncio.run(adapter2.load_context(new_request))
        assert context.variables["persistent"] is True

    def test_evidence_plane_integration(self, evidence_plane):
        """Verify evidence is submitted for each record_result call."""
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        for _ in range(3):
            request = _make_request()
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        evidence_list = evidence_plane.query_evidence_by_type(EvidenceType.METRIC)
        assert len(evidence_list) == 3
        for ev in evidence_list:
            assert ev.payload["metric"] == "memory_record"
            assert ev.producer == "memory:sqlite"

    def test_concurrent_access(self, evidence_plane):
        """Verify thread-safe concurrent access."""
        import concurrent.futures

        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        def record_one():
            request = _make_request()
            result = _make_result(attempt_id=request.attempt_id)
            asyncio.run(adapter.record_result(request, result))

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(record_one) for _ in range(10)]
            concurrent.futures.wait(futures)

        assert adapter.count_records() == 10

    def test_workflow_isolation(self, evidence_plane):
        """Records from different workflows are isolated."""
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        workflow_a = uuid4()
        workflow_b = uuid4()

        # Record in workflow A.
        request_a = _make_request(
            workflow_run_id=workflow_a,
            variables={"workflow": "A"},
        )
        result_a = _make_result(attempt_id=request_a.attempt_id)
        asyncio.run(adapter.record_result(request_a, result_a))

        # Record in workflow B.
        request_b = _make_request(
            workflow_run_id=workflow_b,
            variables={"workflow": "B"},
        )
        result_b = _make_result(attempt_id=request_b.attempt_id)
        asyncio.run(adapter.record_result(request_b, result_b))

        # List records for each workflow.
        records_a = adapter.list_records(workflow_run_id=workflow_a)
        records_b = adapter.list_records(workflow_run_id=workflow_b)

        assert len(records_a) == 1
        assert len(records_b) == 1

    def test_result_json_preserved(self, evidence_plane):
        """Verify the full TaskResult is preserved in the database."""
        adapter = SQLiteMemoryAdapter(evidence_plane=evidence_plane)

        attempt_id = uuid4()
        request = _make_request(attempt_id=attempt_id)
        result = _make_result(
            attempt_id=attempt_id,
            status=TaskResultStatus.SUCCEEDED,
        )
        result.output = {"custom": "data", "nested": {"key": "value"}}
        asyncio.run(adapter.record_result(request, result))

        record = adapter.get_record(attempt_id)
        assert record is not None
        result_json = record["result_json"]
        assert "custom" in result_json
        assert "nested" in result_json

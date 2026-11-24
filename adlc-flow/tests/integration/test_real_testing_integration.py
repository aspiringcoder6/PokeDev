"""Integration tests for the PytestTestingAdapter.

These tests verify the adapter works end-to-end with real pytest
execution and the Evidence Plane.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapters.real_testing import (
    PytestConfig,
    PytestTestingAdapter,
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


def _make_request(workspace: Path) -> TaskRequest:
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="TESTING",
        name="integration-test",
        executor=ExecutorTarget(service="testing", operation="pytest"),
        input={},
        context={"workspace": str(workspace)},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"integration-{uuid4()}",
        requested_at=_utc_now(),
    )


def _make_result() -> TaskResult:
    return TaskResult(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        status=TaskResultStatus.SUCCEEDED,
        output=None,
        artifacts=[],
        error=None,
        metrics=TaskMetrics(duration_ms=0),
        started_at=_utc_now(),
        completed_at=_utc_now(),
    )


@pytest.fixture
def evidence_plane():
    reset_default_evidence_plane()
    return EvidencePlaneService(store=InMemoryEvidenceStore())


class TestPytestIntegration:
    """End-to-end integration tests."""

    def test_full_workflow_passing_tests(self, evidence_plane):
        """Run a real pytest suite with multiple passing tests."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_math.py").write_text(
                "def test_add():\n    assert 1 + 1 == 2\n"
                "\n"
                "def test_sub():\n    assert 5 - 3 == 2\n"
                "\n"
                "def test_mul():\n    assert 3 * 4 == 12\n"
            )
            # Create a conftest.py that prevents pytest from collecting
            # tests from parent directories.
            (workspace / "conftest.py").write_text("")
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_math.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))

            testing = enriched.metadata["testing"]
            assert testing["outcome"] == "PASSED"
            assert testing["passed"] == 3
            assert testing["failed"] == 0
            assert testing["total"] == 3
            assert testing["duration_seconds"] >= 0

            # Evidence should be submitted.
            evidence_list = evidence_plane.query_evidence_by_type(
                EvidenceType.TEST_RESULT
            )
            assert len(evidence_list) == 1
            assert evidence_list[0].payload["passed"] == 3

    def test_full_workflow_mixed_results(self, evidence_plane):
        """Run a real pytest suite with passing and failing tests."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_mixed.py").write_text(
                "def test_pass():\n    assert True\n"
                "\n"
                "def test_fail():\n    assert False\n"
            )
            # Create a conftest.py that prevents pytest from collecting
            # tests from parent directories.
            (workspace / "conftest.py").write_text("")
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_mixed.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))

            testing = enriched.metadata["testing"]
            assert testing["outcome"] == "FAILED"
            assert testing["passed"] == 1
            assert testing["failed"] == 1
            # failure_messages may be empty when using stdout parser
            # (only JSON report parser extracts them)

    def test_evidence_plane_integration(self, evidence_plane):
        """Verify evidence is properly submitted with all fields."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_x.py").write_text("def test_x(): assert True\n")
            (workspace / "conftest.py").write_text("")
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_x.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace)
            result = _make_result()
            asyncio.run(adapter.evaluate(request, result))

            evidence_list = evidence_plane.query_evidence_by_type(
                EvidenceType.TEST_RESULT
            )
            assert len(evidence_list) == 1
            ev = evidence_list[0]
            assert ev.producer == "testing:pytest"
            assert ev.workflow_run_id == request.workflow_run_id
            assert ev.task_run_id == request.task_run_id
            assert ev.attempt_id == request.attempt_id
            assert "outcome" in ev.payload
            assert "passed" in ev.payload
            assert "failed" in ev.payload

    def test_result_metadata_preserved(self, evidence_plane):
        """Verify original result metadata is preserved."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_x.py").write_text("def test_x(): assert True\n")
            (workspace / "conftest.py").write_text("")
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_x.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace)
            result = _make_result()
            result.metadata["custom_key"] = "custom_value"
            enriched = asyncio.run(adapter.evaluate(request, result))

            assert enriched.metadata["custom_key"] == "custom_value"
            assert "testing" in enriched.metadata

    def test_no_workspace_returns_skipped(self, evidence_plane):
        """Verify graceful handling when no workspace is available."""
        adapter = PytestTestingAdapter(
            config=PytestConfig(
                coverage_enabled=False,
                python_executable=sys.executable,
            ),
            evidence_plane=evidence_plane,
        )
        request = _make_request(Path("/nonexistent"))
        result = _make_result()
        enriched = asyncio.run(adapter.evaluate(request, result))

        assert enriched.metadata["testing"]["outcome"] == "SKIPPED"

    def test_timeout_handling(self, evidence_plane):
        """Verify timeout is enforced."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_slow.py").write_text(
                "import time\n"
                "def test_slow():\n"
                "    time.sleep(5)\n"
                "    assert True\n"
            )
            (workspace / "conftest.py").write_text("")
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    timeout_seconds=1,
                    pytest_args=("test_slow.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))

            testing = enriched.metadata["testing"]
            assert testing["outcome"] == "ERROR"
            assert "timed out" in testing["failure_messages"][0].lower()

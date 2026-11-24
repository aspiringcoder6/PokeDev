"""Unit tests for the PytestTestingAdapter."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapters.real_testing import (
    PytestConfig,
    PytestTestingAdapter,
    TestOutcome,
)
from langflow.adlc.evidence_plane import (
    EvidencePlaneService,
    InMemoryEvidenceStore,
    reset_default_evidence_plane,
)
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ExecutorTarget,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_request(workspace: Path | None = None) -> TaskRequest:
    context = {"workspace": str(workspace)} if workspace else {}
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="TESTING",
        name="test-task",
        executor=ExecutorTarget(service="testing", operation="test", agent_id="test-agent"),
        input={},
        context=context,
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"test-{uuid4()}",
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
    """Provide a fresh in-memory evidence plane for each test."""
    reset_default_evidence_plane()
    return EvidencePlaneService(store=InMemoryEvidenceStore())


class TestPytestConfig:
    def test_default_config(self):
        config = PytestConfig()
        assert config.timeout_seconds == 300
        assert config.coverage_enabled is True
        assert config.max_failures == 50

    def test_custom_config(self):
        config = PytestConfig(timeout_seconds=60, coverage_enabled=False)
        assert config.timeout_seconds == 60
        assert config.coverage_enabled is False


class TestPytestTestingAdapter:
    def test_evaluate_skips_when_no_workspace(self, evidence_plane):
        adapter = PytestTestingAdapter(evidence_plane=evidence_plane)
        request = _make_request(workspace=None)
        result = _make_result()
        enriched = asyncio.run(adapter.evaluate(request, result))
        assert enriched.metadata["testing"]["outcome"] == "SKIPPED"
        assert "no workspace" in enriched.metadata["testing"]["reason"]

    def test_evaluate_runs_pytest_on_passing_tests(self, evidence_plane):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            # Create a simple passing test.
            (workspace / "test_sample.py").write_text(
                "def test_pass():\n    assert 1 + 1 == 2\n"
            )
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_sample.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace=workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))
            testing = enriched.metadata["testing"]
            assert testing["outcome"] in ("PASSED", "MIXED")
            assert testing["passed"] >= 1
            assert testing["failed"] == 0

    def test_evaluate_runs_pytest_on_failing_tests(self, evidence_plane):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_failing.py").write_text(
                "def test_fail():\n    assert 1 + 1 == 3\n"
            )
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_failing.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace=workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))
            testing = enriched.metadata["testing"]
            assert testing["outcome"] == "FAILED"
            assert testing["failed"] >= 1

    def test_evaluate_handles_pytest_not_found(self, evidence_plane):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    python_executable="definitely-not-a-real-python-xyz",
                    coverage_enabled=False,
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace=workspace)
            result = _make_result()
            enriched = asyncio.run(adapter.evaluate(request, result))
            testing = enriched.metadata["testing"]
            assert testing["outcome"] == "ERROR"

    def test_evaluate_submits_evidence(self, evidence_plane):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "test_sample.py").write_text(
                "def test_pass():\n    assert True\n"
            )
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    coverage_enabled=False,
                    python_executable=sys.executable,
                    pytest_args=("test_sample.py",),
                ),
                evidence_plane=evidence_plane,
            )
            request = _make_request(workspace=workspace)
            result = _make_result()
            asyncio.run(adapter.evaluate(request, result))

            # Check that evidence was submitted.
            from langflow.adlc.evidence_plane import EvidenceType

            evidence_list = evidence_plane.query_evidence_by_type(
                EvidenceType.TEST_RESULT
            )
            assert len(evidence_list) >= 1
            assert evidence_list[0].payload["outcome"] in (
                "PASSED", "FAILED", "ERROR", "MIXED"
            )


class TestTestOutcome:
    def test_outcome_is_frozen(self):
        outcome = TestOutcome(
            outcome="PASSED",
            total=1,
            passed=1,
            failed=0,
            errors=0,
            skipped=0,
            duration_seconds=0.1,
            coverage_percent=None,
            failure_messages=(),
        )
        with pytest.raises(Exception):
            outcome.outcome = "FAILED"  # type: ignore[misc]


class TestParseStdout:
    """Direct tests for the _parse_stdout method."""

    def _make_adapter(self) -> PytestTestingAdapter:
        return PytestTestingAdapter(
            config=PytestConfig(python_executable=sys.executable)
        )

    def test_parses_single_passed(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("1 passed in 0.01s")
        assert outcome.outcome == "PASSED"
        assert outcome.passed == 1
        assert outcome.failed == 0

    def test_parses_single_failed(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("1 failed in 0.01s")
        assert outcome.outcome == "FAILED"
        assert outcome.failed == 1
        assert outcome.passed == 0

    def test_parses_mixed_results(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("3 passed, 1 failed, 1 error in 2.5s")
        assert outcome.outcome == "ERROR"
        assert outcome.passed == 3
        assert outcome.failed == 1
        assert outcome.errors == 1
        assert outcome.duration_seconds == 2.5

    def test_parses_with_skipped(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("2 passed, 1 skipped in 0.5s")
        assert outcome.outcome == "PASSED"
        assert outcome.passed == 2
        assert outcome.skipped == 1

    def test_handles_no_tests_collected(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("no tests collected in 0.01s")
        assert outcome.outcome == "MIXED"
        assert outcome.total == 0

    def test_handles_unparseable_output(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("garbage output")
        assert outcome.outcome == "ERROR"
        assert outcome.errors == 1

    def test_searches_stderr(self):
        adapter = self._make_adapter()
        outcome = adapter._parse_stdout("", "1 failed in 0.01s")
        assert outcome.outcome == "FAILED"
        assert outcome.failed == 1


class TestParseJsonReport:
    """Direct tests for the _parse_json_report method."""

    def _make_adapter(self) -> PytestTestingAdapter:
        return PytestTestingAdapter(
            config=PytestConfig(python_executable=sys.executable)
        )

    def test_parses_passing_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            report = {
                "summary": {"total": 2, "passed": 2, "failed": 0, "error": 0, "skipped": 0},
                "duration": 0.5,
                "tests": [],
            }
            report_path = workspace / ".report.json"
            report_path.write_text(json.dumps(report))
            adapter = self._make_adapter()
            outcome = adapter._parse_json_report(report_path, "")
            assert outcome.outcome == "PASSED"
            assert outcome.passed == 2
            assert outcome.duration_seconds == 0.5

    def test_parses_failing_report_with_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            report = {
                "summary": {"total": 1, "passed": 0, "failed": 1, "error": 0, "skipped": 0},
                "duration": 0.1,
                "tests": [
                    {
                        "nodeid": "test_x.py::test_fail",
                        "outcome": "failed",
                        "call": {"longrepr": "AssertionError: 1 != 2"},
                    }
                ],
            }
            report_path = workspace / ".report.json"
            report_path.write_text(json.dumps(report))
            adapter = self._make_adapter()
            outcome = adapter._parse_json_report(report_path, "")
            assert outcome.outcome == "FAILED"
            assert outcome.failed == 1
            assert len(outcome.failure_messages) == 1
            assert "test_x.py::test_fail" in outcome.failure_messages[0]

    def test_parses_error_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            report = {
                "summary": {"total": 1, "passed": 0, "failed": 0, "error": 1, "skipped": 0},
                "duration": 0.1,
                "tests": [],
            }
            report_path = workspace / ".report.json"
            report_path.write_text(json.dumps(report))
            adapter = self._make_adapter()
            outcome = adapter._parse_json_report(report_path, "")
            assert outcome.outcome == "ERROR"
            assert outcome.errors == 1

    def test_parses_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            report = {
                "summary": {"total": 1, "passed": 1, "failed": 0, "error": 0, "skipped": 0},
                "duration": 0.1,
                "tests": [],
            }
            report_path = workspace / ".report.json"
            report_path.write_text(json.dumps(report))
            cov_path = workspace / "coverage.json"
            cov_path.write_text(json.dumps({"totals": {"percent_covered": 85.5}}))
            adapter = self._make_adapter()
            outcome = adapter._parse_json_report(report_path, "")
            assert outcome.coverage_percent == 85.5

    def test_handles_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            report_path = workspace / ".report.json"
            report_path.write_text("not valid json")
            adapter = self._make_adapter()
            with pytest.raises(json.JSONDecodeError):
                adapter._parse_json_report(report_path, "")


class TestResolveWorkspace:
    """Tests for workspace resolution from request context."""

    def test_resolves_from_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            adapter = PytestTestingAdapter(
                config=PytestConfig(python_executable=sys.executable)
            )
            request = _make_request(workspace=workspace)
            resolved = adapter._resolve_workspace(request, _make_result())
            assert resolved == workspace.resolve()

    def test_falls_back_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            adapter = PytestTestingAdapter(
                config=PytestConfig(
                    python_executable=sys.executable,
                    working_directory=workspace,
                )
            )
            request = _make_request(workspace=None)
            resolved = adapter._resolve_workspace(request, _make_result())
            assert resolved == workspace

    def test_returns_none_when_no_workspace(self):
        adapter = PytestTestingAdapter(
            config=PytestConfig(python_executable=sys.executable)
        )
        request = _make_request(workspace=None)
        resolved = adapter._resolve_workspace(request, _make_result())
        assert resolved is None

    def test_returns_none_for_nonexistent_path(self):
        adapter = PytestTestingAdapter(
            config=PytestConfig(python_executable=sys.executable)
        )
        request = _make_request(workspace=Path("/nonexistent/path/xyz"))
        resolved = adapter._resolve_workspace(request, _make_result())
        assert resolved is None

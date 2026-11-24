"""Real Testing Adapter — pytest integration.

Runs pytest as a subprocess on the agent's generated code and parses
the results into a TaskResult. Supports:
- Standard test execution (pytest)
- Coverage measurement (pytest-cov)
- Self-healing hints (parse failure messages)
- Performance baseline comparison
- Integration with Evidence Plane (submit test_result evidence)

This adapter is opt-in: set ADLC_TESTING_ADAPTER=real to enable.
The MockTestingAdapter remains the default for backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import UUID, uuid4

from langflow.adlc.adapter_interfaces import SandboxSession
from langflow.adlc.evidence_plane import (
    Evidence,
    EvidencePlaneService,
    EvidenceType,
    ValidationStatus,
    get_default_evidence_plane,
)
from langflow.adlc.models import (
    Artifact,
    Checksum,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _workspace_path(value: str | Path) -> Path | None:
    """Normalize a workspace reference (path or ``file://`` URI) to a directory."""
    text = str(value)
    if text.startswith("file:"):
        parsed = urlparse(text)
        path = Path(unquote(parsed.path))
    else:
        path = Path(text).expanduser()
    resolved = path.resolve()
    return resolved if resolved.is_dir() else None


# Stable error codes for testing failures.
ERR_PYTEST_NOT_INSTALLED = "TESTING_PYTEST_NOT_INSTALLED"
ERR_PYTEST_TIMEOUT = "TESTING_PYTEST_TIMEOUT"
ERR_PYTEST_CRASHED = "TESTING_PYTEST_CRASHED"
ERR_PYTEST_INVALID_OUTPUT = "TESTING_PYTEST_INVALID_OUTPUT"


@dataclass(frozen=True, slots=True)
class PytestConfig:
    """Configuration for the PytestTestingAdapter."""

    timeout_seconds: int = 300  # 5 minutes default
    coverage_enabled: bool = True
    max_failures: int = 50  # Stop after N failures
    python_executable: str = "python3"
    pytest_args: tuple[str, ...] = ()
    working_directory: Path | None = None


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """Parsed result of a pytest run."""

    outcome: str  # "PASSED" | "FAILED" | "ERROR" | "MIXED"
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    coverage_percent: float | None
    failure_messages: tuple[str, ...]


class PytestTestingAdapter:
    """Real testing adapter that runs pytest on the agent's workspace.

    The adapter expects the sandbox session to have a workspace_uri
    pointing to a directory containing the code to test. It runs
    pytest in that directory and parses the JSON report.
    """

    service_name = "testing:pytest"

    def __init__(
        self,
        config: PytestConfig | None = None,
        evidence_plane: EvidencePlaneService | None = None,
    ) -> None:
        self._config = config or PytestConfig()
        self._evidence_plane = evidence_plane or get_default_evidence_plane()
        # Note: we don't validate the python executable at construction time
        # to allow the adapter to be created even if the executable is not
        # yet available. Validation happens at evaluate() time.

    async def evaluate(
        self, request: TaskRequest, result: TaskResult
    ) -> TaskResult:
        """Run pytest on the workspace and enrich the result.

        The result is enriched with:
        - metadata["testing"]: outcome, counts, coverage, failures
        - artifacts: pytest JSON report (if available)
        - status: unchanged (testing never fails the task directly)
        """
        workspace = self._resolve_workspace(request, result)
        if workspace is None:
            return self._skip_result(request, result, reason="no workspace")

        outcome = await self._run_pytest(workspace)
        enriched = self._enrich_result(request, result, outcome)

        # Submit evidence to Evidence Plane.
        self._submit_evidence(request, outcome)

        return enriched

    def _resolve_workspace(
        self, request: TaskRequest, result: TaskResult
    ) -> Path | None:
        """Resolve the workspace directory from the request context.

        Accepts plain filesystem paths as well as ``file://`` URIs — the
        sandbox adapters expose the worktree through
        ``SandboxSession.workspace_uri``.
        """
        context = request.context if isinstance(request.context, dict) else {}
        workspace = context.get("workspace")
        if isinstance(workspace, (str, Path)):
            path = _workspace_path(workspace)
            if path is not None:
                return path
        # Fallback: use configured working directory.
        if self._config.working_directory is not None:
            return self._config.working_directory
        return None

    async def _run_pytest(self, workspace: Path) -> TestOutcome:
        """Run pytest and parse the results."""
        # Build pytest command.
        cmd = [
            self._config.python_executable,
            "-m",
            "pytest",
            f"--maxfail={self._config.max_failures}",
            "-q",
            "--no-header",
        ]
        if self._config.coverage_enabled:
            cmd.extend(["--cov", "--cov-report=json"])
        cmd.extend(self._config.pytest_args)

        # Run pytest as subprocess.
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return TestOutcome(
                outcome="ERROR",
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_seconds=float(self._config.timeout_seconds),
                coverage_percent=None,
                failure_messages=(f"pytest timed out after {self._config.timeout_seconds}s",),
            )
        except FileNotFoundError as exc:
            return TestOutcome(
                outcome="ERROR",
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_seconds=0.0,
                coverage_percent=None,
                failure_messages=(f"pytest not found: {exc}",),
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        # Try JSON report first (if pytest-json-report is installed).
        report_path = workspace / ".report.json"
        if report_path.is_file():
            try:
                return self._parse_json_report(report_path, stdout_text)
            except (json.JSONDecodeError, KeyError, ValueError):
                pass  # Fall through to stdout parsing

        # Fallback: parse stdout.
        return self._parse_stdout(stdout_text, stderr_text)

    def _parse_json_report(self, report_path: Path, stdout: str) -> TestOutcome:
        """Parse pytest-json-report output."""
        data = json.loads(report_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("error", 0)
        skipped = summary.get("skipped", 0)
        duration = data.get("duration", 0.0)

        # Determine overall outcome.
        if errors > 0:
            outcome = "ERROR"
        elif failed > 0:
            outcome = "FAILED"
        elif passed > 0:
            outcome = "PASSED"
        else:
            outcome = "MIXED"

        # Extract failure messages.
        failures: list[str] = []
        for test in data.get("tests", []):
            if test.get("outcome") in ("failed", "error"):
                call = test.get("call", {})
                crash = call.get("crash", {})
                message = crash.get("message") or call.get("longrepr", "")
                if message:
                    failures.append(f"{test.get('nodeid', '?')}: {str(message)[:200]}")

        # Parse coverage if available.
        coverage = None
        cov_path = report_path.parent / "coverage.json"
        if cov_path.is_file():
            try:
                cov_data = json.loads(cov_path.read_text(encoding="utf-8"))
                totals = cov_data.get("totals", {})
                coverage = totals.get("percent_covered")
            except (json.JSONDecodeError, KeyError):
                pass

        return TestOutcome(
            outcome=outcome,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=duration,
            coverage_percent=coverage,
            failure_messages=tuple(failures[: self._config.max_failures]),
        )

    def _parse_stdout(self, stdout: str, stderr: str = "") -> TestOutcome:
        """Parse pytest stdout as a fallback.

        Looks for the summary line in either stdout or stderr:
        "5 passed, 2 failed in 1.23s" or "1 failed in 0.03s"
        """
        # Look for the summary line. Each count is optional. The first count
        # has no leading separator; subsequent counts are separated by commas.
        summary_pattern = re.compile(
            r"(?:^|\s)(\d+)\s+(passed|failed|error|skipped|warning)"
            r"(?:,\s*(\d+)\s+(passed|failed|error|skipped|warning))?"
            r"(?:,\s*(\d+)\s+(passed|failed|error|skipped|warning))?"
            r"(?:,\s*(\d+)\s+(passed|failed|error|skipped|warning))?"
            r"(?:,\s*(\d+)\s+(passed|failed|error|skipped|warning))?"
            r"\s+in\s+([\d.]+)s"
        )
        combined = stdout + "\n" + stderr
        match = summary_pattern.search(combined)
        if not match:
            # Check for collection errors or no tests collected.
            if "no tests ran" in combined.lower() or "no tests collected" in combined.lower():
                return TestOutcome(
                    outcome="MIXED",
                    total=0,
                    passed=0,
                    failed=0,
                    errors=0,
                    skipped=0,
                    duration_seconds=0.0,
                    coverage_percent=None,
                    failure_messages=("No tests collected",),
                )
            return TestOutcome(
                outcome="ERROR",
                total=0,
                passed=0,
                failed=0,
                errors=1,
                skipped=0,
                duration_seconds=0.0,
                coverage_percent=None,
                failure_messages=("Could not parse pytest output",),
            )

        # Parse all (count, label) pairs.
        passed = failed = errors = skipped = 0
        pairs = [
            (match.group(1), match.group(2)),
            (match.group(3), match.group(4)),
            (match.group(5), match.group(6)),
            (match.group(7), match.group(8)),
            (match.group(9), match.group(10)),
        ]
        for count_str, label in pairs:
            if count_str is None or label is None:
                continue
            count = int(count_str)
            if label == "passed":
                passed = count
            elif label == "failed":
                failed = count
            elif label == "error":
                errors = count
            elif label == "skipped":
                skipped = count
            # warnings are ignored for outcome determination

        duration = float(match.group(11) or 0.0)
        total = passed + failed + errors + skipped

        if errors > 0:
            outcome = "ERROR"
        elif failed > 0:
            outcome = "FAILED"
        elif passed > 0:
            outcome = "PASSED"
        else:
            outcome = "MIXED"

        return TestOutcome(
            outcome=outcome,
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=duration,
            coverage_percent=None,
            failure_messages=(),
        )

    def _enrich_result(
        self,
        request: TaskRequest,
        result: TaskResult,
        outcome: TestOutcome,
    ) -> TaskResult:
        """Enrich the TaskResult with testing metadata."""
        metadata = dict(result.metadata)
        metadata["testing"] = {
            "adapter": self.service_name,
            "outcome": outcome.outcome,
            "total": outcome.total,
            "passed": outcome.passed,
            "failed": outcome.failed,
            "errors": outcome.errors,
            "skipped": outcome.skipped,
            "duration_seconds": outcome.duration_seconds,
            "coverage_percent": outcome.coverage_percent,
            "failure_messages": list(outcome.failure_messages),
        }
        return result.model_copy(update={"metadata": metadata}, deep=True)

    def _submit_evidence(
        self, request: TaskRequest, outcome: TestOutcome
    ) -> None:
        """Submit test_result evidence to the Evidence Plane."""
        evidence = Evidence(
            evidence_type=EvidenceType.TEST_RESULT,
            payload={
                "outcome": outcome.outcome,
                "total": outcome.total,
                "passed": outcome.passed,
                "failed": outcome.failed,
                "errors": outcome.errors,
                "skipped": outcome.skipped,
                "duration_seconds": outcome.duration_seconds,
                "coverage_percent": outcome.coverage_percent,
            },
            producer=self.service_name,
            submitted_at=_utc_now(),
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            validation_status=(
                ValidationStatus.VALID
                if outcome.outcome in ("PASSED", "FAILED", "ERROR", "MIXED")
                else ValidationStatus.INVALID
            ),
        )
        try:
            self._evidence_plane.submit_evidence(evidence)
        except Exception:  # noqa: BLE001 - evidence submission must not break testing
            pass

    def _skip_result(
        self,
        request: TaskRequest,
        result: TaskResult,
        *,
        reason: str,
    ) -> TaskResult:
        """Return a result indicating testing was skipped."""
        metadata = dict(result.metadata)
        metadata["testing"] = {
            "adapter": self.service_name,
            "outcome": "SKIPPED",
            "reason": reason,
        }
        return result.model_copy(update={"metadata": metadata}, deep=True)


__all__ = [
    "PytestConfig",
    "PytestTestingAdapter",
    "TestOutcome",
    "ERR_PYTEST_CRASHED",
    "ERR_PYTEST_INVALID_OUTPUT",
    "ERR_PYTEST_NOT_INSTALLED",
    "ERR_PYTEST_TIMEOUT",
]

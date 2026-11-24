# ruff: noqa: S101, S603, S607

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from langflow.adlc.adapter_interfaces import AdapterBundle
from langflow.adlc.adapter_runtime import AdapterTaskExecutor
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.local_worktree_sandbox import LocalWorktreeSandboxAdapter
from langflow.adlc.mock_adapters import MockMemoryAdapter, MockTestingAdapter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus
from langflow.adlc.opencode_adapter import OpenCodeAgentAdapter

if TYPE_CHECKING:
    from pathlib import Path

_LIVE_TEST_ENABLED = os.getenv("ADLC_RUN_OPENCODE_LIVE_TEST", "").strip().lower() in {"1", "true", "yes", "on"}


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _create_repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.name", "ADLC Live Test")
    _git(path, "config", "user.email", "adlc-live-test@example.invalid")
    (path / "README.md").write_text("temporary source checkout\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    return path.resolve()


def _request() -> TaskRequest:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="coding",
        name="OpenCode disposable-worktree smoke test",
        executor=ExecutorTarget(
            service="agent-provider:opencode",
            operation="coding-task",
            capabilities=["code_edit", "diff_artifact"],
        ),
        input={
            "objective": (
                "Replace the contents of the existing README.md with exactly "
                "'ADLC OpenCode worktree smoke test.' followed by a newline. Do not modify any other file, and do "
                "not perform additional verification after writing it."
            ),
            "namedInputs": {"requirement": "Apply the requested one-file README change."},
        },
        context={"memory_refs": [], "variables": {"mock": False}},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 180_000, "max_attempts": 1},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
        metadata={"mock": False, "live_smoke_test": True},
    )


@pytest.mark.integration
@pytest.mark.skipif(not _LIVE_TEST_ENABLED, reason="Set ADLC_RUN_OPENCODE_LIVE_TEST=true to run the live smoke test.")
async def test_live_opencode_task_is_isolated_and_cleaned_up(tmp_path: Path) -> None:
    repository = _create_repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    source_status_before = _git(repository, "status", "--short")
    sandbox = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    agent = OpenCodeAgentAdapter.from_environment()
    live_executor = AdapterTaskExecutor(
        AdapterBundle(
            sandbox=sandbox,
            memory=MockMemoryAdapter(),
            testing=MockTestingAdapter(),
            agent=agent,
        )
    )
    router = TaskExecutorRouter(
        MockExecutor(),
        routes={"agent-provider:opencode": live_executor},
    )
    transitions: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        transitions.append(status)

    result = await router.execute(_request(), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED, result.error
    assert transitions == [TaskRunStatus.RUNNING, TaskRunStatus.SUCCEEDED]
    assert result.artifacts
    assert result.artifacts[0].uri.startswith(f"adlc://runs/{result.workflow_run_id}/artifacts/")
    assert result.artifacts[0].kind == "SOURCE_PATCH"
    assert result.artifacts[0].media_type == "application/vnd.opencode.vcs-diff+json"
    assert result.artifacts[0].metadata["capture"] == "workspace-vcs-diff"
    assert result.artifacts[0].metadata["diff_file_count"] == 1
    assert result.artifacts[0].metadata["payload_retained"] is True
    assert b"README.md" in agent.artifact_payloads.read(result.artifacts[0])
    changed_files = result.output["outputs"]["source_patch"]["changed_files"]
    assert "README.md" in changed_files
    assert (repository / "README.md").read_text(encoding="utf-8") == "temporary source checkout\n"
    assert _git(repository, "status", "--short") == source_status_before
    assert not sandbox.open_sessions
    assert not workspace_root.exists() or not list(workspace_root.iterdir())

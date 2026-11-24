# ruff: noqa: INP001, S101, S603, S607

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapter_interfaces import AdapterBundle, MemoryContext, SandboxSession
from langflow.adlc.adapter_runtime import AdapterTaskExecutor
from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.local_worktree_sandbox import LocalWorktreeSandboxAdapter
from langflow.adlc.mock_adapters import MockMemoryAdapter, MockTestingAdapter
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResult, TaskResultStatus, TaskRunStatus
from langflow.adlc.opencode_adapter import OpenCodeAgentAdapter
from langflow.adlc.opencode_client import OpenCodeFileDiff, OpenCodePromptResult, OpenCodeSession


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _repository(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--initial-branch=main")
    _git(path, "config", "user.name", "ADLC Test")
    _git(path, "config", "user.email", "adlc-test@example.invalid")
    (path / "README.md").write_text("main checkout\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    return path.resolve()


def _request(service: str = "agent-provider:opencode", *, context: dict | None = None) -> TaskRequest:
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
        name="Worktree task",
        executor=ExecutorTarget(service=service, operation="coding-task"),
        input={"objective": "Update the isolated workspace."},
        context=context or {},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
    )


async def test_local_worktree_is_isolated_and_removed_on_close(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    request = _request()
    before_status = _git(repository, "status", "--short")

    await adapter.check_readiness()
    session = await adapter.open_session(request)
    workspace = Path(session.metadata["opencode_directory"])
    (workspace / "README.md").write_text("isolated change\n", encoding="utf-8")
    (workspace / "new-file.txt").write_text("new\n", encoding="utf-8")

    assert workspace.is_dir()
    assert session.metadata["mock"] is False
    assert session.metadata["disposable"] is True
    assert (repository / "README.md").read_text(encoding="utf-8") == "main checkout\n"
    assert _git(repository, "status", "--short") == before_status

    await adapter.close_session(request, session)

    assert not workspace.exists()
    assert not adapter.open_sessions
    assert (repository / "README.md").read_text(encoding="utf-8") == "main checkout\n"
    assert _git(repository, "status", "--short") == before_status
    assert str(workspace) not in _git(repository, "worktree", "list", "--porcelain")


async def test_worktree_git_commands_enable_long_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arguments_seen: list[str] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def fake_subprocess(*arguments: str, **_kwargs: object) -> FakeProcess:
        arguments_seen.extend(arguments)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    repository = tmp_path / "source"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=tmp_path / "worktrees")

    await adapter._run_git("worktree", "prune", error_code="LOCAL_WORKTREE_PRUNE_FAILED")  # noqa: SLF001

    assert arguments_seen == [
        "git",
        "-c",
        "core.longpaths=true",
        "-C",
        str(repository.resolve()),
        "worktree",
        "prune",
    ]


async def test_source_patch_remains_reviewable_after_worktree_cleanup(tmp_path: Path) -> None:
    class FakeOpenCodeClient:
        async def create_session(self, *, directory: str, title: str, timeout_ms: int) -> OpenCodeSession:  # noqa: ARG002
            return OpenCodeSession(session_id="ses_test", directory=directory)

        async def prompt(
            self,
            session_id: str,  # noqa: ARG002
            *,
            directory: str,
            prompt: str,  # noqa: ARG002
            system: str,  # noqa: ARG002
            model: object,  # noqa: ARG002
            agent: str | None,  # noqa: ARG002
            timeout_ms: int,  # noqa: ARG002
        ) -> OpenCodePromptResult:
            Path(directory, "README.md").write_text("isolated change\n", encoding="utf-8")
            return OpenCodePromptResult(message_id="msg_test", text="Done", changed_files=("README.md",))

        async def get_workspace_diff(self, *, directory: str, timeout_ms: int) -> tuple[OpenCodeFileDiff, ...]:  # noqa: ARG002
            return (
                OpenCodeFileDiff(
                    file="README.md",
                    patch=_git(Path(directory), "diff", "--", "README.md"),
                    additions=1,
                    deletions=1,
                    status="modified",
                ),
            )

        async def dispose_instance(self, *, directory: str, timeout_ms: int = 5000) -> None:  # noqa: ARG002
            return None

    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    sandbox = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    payloads = BoundedArtifactPayloadStore()
    agent = OpenCodeAgentAdapter(FakeOpenCodeClient(), artifact_payloads=payloads)
    executor = AdapterTaskExecutor(
        AdapterBundle(sandbox=sandbox, memory=MockMemoryAdapter(), testing=MockTestingAdapter(), agent=agent)
    )

    async def on_state_change(_status: TaskRunStatus, _result: TaskResult | None) -> None:
        return None

    result = await executor.execute(_request(), on_state_change)

    assert result.status is TaskResultStatus.SUCCEEDED
    assert not sandbox.open_sessions
    assert not list(workspace_root.iterdir())
    assert _git(repository, "status", "--short") == ""
    assert (repository / "README.md").read_text(encoding="utf-8") == "main checkout\n"
    payload = json.loads(payloads.read(result.artifacts[0]))
    assert payload["files"][0]["file"] == "README.md"
    assert "+isolated change" in payload["files"][0]["patch"]


async def test_executor_cancellation_still_removes_worktree(tmp_path: Path) -> None:
    class BlockingAgent:
        service_name = "agent-provider:opencode"
        capabilities = ("code_edit",)

        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def execute(
            self,
            request: TaskRequest,  # noqa: ARG002
            *,
            sandbox: SandboxSession,
            memory: MemoryContext,  # noqa: ARG002
        ) -> TaskResult:
            Path(sandbox.metadata["opencode_directory"], "partial.txt").write_text("partial\n", encoding="utf-8")
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError

    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    sandbox = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    agent = BlockingAgent()
    executor = AdapterTaskExecutor(
        AdapterBundle(
            sandbox=sandbox,
            memory=MockMemoryAdapter(),
            testing=MockTestingAdapter(),
            agent=agent,
        )
    )
    statuses: list[TaskRunStatus] = []

    async def on_state_change(status: TaskRunStatus, _result: TaskResult | None) -> None:
        statuses.append(status)

    task = asyncio.create_task(executor.execute(_request(), on_state_change))
    await agent.started.wait()
    allocated = tuple(sandbox.open_sessions.values())
    assert len(allocated) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert statuses == [TaskRunStatus.RUNNING]
    assert not sandbox.open_sessions
    assert not allocated[0].exists()
    assert not list(workspace_root.iterdir())
    assert _git(repository, "status", "--short") == ""


async def test_dirty_worktree_is_preserved_under_run_label(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    request = _request(context={"workflow_name": "My Workflow", "workflow_run_number": 3})

    session = await adapter.open_session(request)
    workspace = Path(session.metadata["opencode_directory"])
    (workspace / "new-file.txt").write_text("finished work\n", encoding="utf-8")

    await adapter.close_session(request, session)

    preserved = workspace_root / "My-Workflow-run-3" / "Worktree-task"
    assert preserved.is_dir()
    assert (preserved / "new-file.txt").read_text(encoding="utf-8") == "finished work\n"
    assert (preserved / "README.md").read_text(encoding="utf-8") == "main checkout\n"
    assert not (preserved / ".git").exists()
    assert not workspace.exists()
    assert not adapter.open_sessions


async def test_clean_worktree_is_not_preserved(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    request = _request(context={"workflow_name": "My Workflow", "workflow_run_number": 1})

    session = await adapter.open_session(request)
    await adapter.close_session(request, session)

    assert not (workspace_root / "My-Workflow-run-1").exists()
    assert not adapter.open_sessions


async def test_preserved_target_collision_gets_numeric_suffix(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    context = {"workflow_name": "flow", "workflow_run_number": 2}

    for index in range(2):
        request = _request(context=context)
        session = await adapter.open_session(request)
        workspace = Path(session.metadata["opencode_directory"])
        (workspace / f"artifact-{index}.txt").write_text(f"run {index}\n", encoding="utf-8")
        await adapter.close_session(request, session)

    first = workspace_root / "flow-run-2" / "Worktree-task" / "artifact-0.txt"
    second = workspace_root / "flow-run-2" / "Worktree-task-2" / "artifact-1.txt"
    assert first.exists()
    assert second.exists()


async def test_retried_task_resumes_from_latest_preserved_snapshot(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")
    workspace_root = tmp_path / "worktrees"
    adapter = LocalWorktreeSandboxAdapter(repository, workspace_root=workspace_root)
    context = {"workflow_name": "flow", "workflow_run_number": 5}

    async def one_attempt(index: int) -> tuple[Path, str | None]:
        request = _request(context=context)
        session = await adapter.open_session(request)
        workspace = Path(session.metadata["opencode_directory"])
        (workspace / f"partial-{index}.txt").write_text(f"attempt {index}\n", encoding="utf-8")
        resumed = session.metadata.get("resumed_from")
        await adapter.close_session(request, session)
        return workspace, resumed

    first_workspace, first_resume = await one_attempt(0)
    second_workspace, second_resume = await one_attempt(1)

    assert first_resume is None
    assert second_resume is not None
    assert Path(second_resume).name == "Worktree-task"
    second_snapshot = workspace_root / "flow-run-5" / "Worktree-task-2"
    assert (second_snapshot / "partial-0.txt").read_text(encoding="utf-8") == "attempt 0\n"
    assert (second_snapshot / "partial-1.txt").read_text(encoding="utf-8") == "attempt 1\n"
    assert not second_workspace.exists()
    assert not first_workspace.exists()


def test_local_worktree_rejects_a_root_inside_the_source_repository(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "source")

    with pytest.raises(ValueError, match="outside"):
        LocalWorktreeSandboxAdapter(repository, workspace_root=repository / ".adlc-worktrees")

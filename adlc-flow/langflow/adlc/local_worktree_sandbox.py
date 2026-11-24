"""Disposable local Git worktrees for explicitly enabled OpenCode execution.

Each task attempt runs in a detached worktree removed after the task ends.
When the workspace actually changed, its final state is copied to a durable
result folder ``{workflow-name}-run-{n}/{task-slug}`` so finished projects
survive cleanup and separate runs stay distinguishable.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from shutil import copytree, ignore_patterns
from typing import TYPE_CHECKING

from langflow.adlc.adapter_interfaces import SandboxSession

if TYPE_CHECKING:
    from langflow.adlc.models import TaskRequest

_SOURCE_NOT_FOUND = "LOCAL_WORKTREE_SOURCE_NOT_FOUND"
_SOURCE_INVALID = "LOCAL_WORKTREE_SOURCE_INVALID"
_SOURCE_NOT_ROOT = "LOCAL_WORKTREE_SOURCE_NOT_ROOT"
_ALREADY_EXISTS = "LOCAL_WORKTREE_ALREADY_EXISTS"
_ROOT_UNAVAILABLE = "LOCAL_WORKTREE_ROOT_UNAVAILABLE"
_CREATE_FAILED = "LOCAL_WORKTREE_CREATE_FAILED"
_PATH_REJECTED = "LOCAL_WORKTREE_PATH_REJECTED"
_REMOVE_FAILED = "LOCAL_WORKTREE_REMOVE_FAILED"
_GIT_UNAVAILABLE = "LOCAL_WORKTREE_GIT_UNAVAILABLE"

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_name(value: str) -> str:
    cleaned = _UNSAFE_NAME.sub("-", value.strip()).strip("-.")
    return cleaned[:80]


class LocalWorktreeSandboxError(RuntimeError):
    """Secret-safe failure raised by the local worktree boundary."""

    def __init__(self, code: str, *, operation: str) -> None:
        super().__init__(code)
        self.code = code
        self.operation = operation


class LocalWorktreeSandboxAdapter:
    """Create one detached, disposable Git worktree for each task attempt."""

    service_name = "sandbox:local-git-worktree"

    def __init__(
        self,
        source_repository: str | Path,
        *,
        workspace_root: str | Path | None = None,
        base_ref: str = "HEAD",
        git_executable: str = "git",
    ) -> None:
        self.source_repository = Path(source_repository).expanduser().resolve()
        configured_root = workspace_root or (Path(tempfile.gettempdir()) / "adlc-worktrees")
        self.workspace_root = Path(configured_root).expanduser().resolve()
        self.base_ref = base_ref.strip()
        self.git_executable = git_executable
        self._open_sessions: dict[str, Path] = {}
        self._mutation_lock = asyncio.Lock()
        self._validate_configuration()

    @property
    def open_sessions(self) -> dict[str, Path]:
        """Return a caller-owned snapshot of worktrees currently managed by this adapter."""
        return dict(self._open_sessions)

    async def check_readiness(self) -> None:
        """Verify the source repository, Git executable, and configured base revision."""
        if not self.source_repository.is_dir():
            raise LocalWorktreeSandboxError(_SOURCE_NOT_FOUND, operation="readiness")
        repository_root = await self._run_git(
            "rev-parse",
            "--show-toplevel",
            error_code="LOCAL_WORKTREE_SOURCE_INVALID",
        )
        try:
            resolved_root = Path(repository_root.strip()).resolve()
        except OSError as exc:
            raise LocalWorktreeSandboxError(
                _SOURCE_INVALID,
                operation="readiness",
            ) from exc
        if resolved_root != self.source_repository:
            raise LocalWorktreeSandboxError(_SOURCE_NOT_ROOT, operation="readiness")
        await self._run_git(
            "rev-parse",
            "--verify",
            f"{self.base_ref}^{{commit}}",
            error_code="LOCAL_WORKTREE_BASE_REF_INVALID",
        )

    async def open_session(self, request: TaskRequest) -> SandboxSession:
        """Create a detached worktree rooted at the configured immutable base revision."""
        await self.check_readiness()
        session_id = f"worktree-{request.attempt_id}"
        workspace = (self.workspace_root / session_id).resolve()
        self._assert_managed_path(workspace)

        async with self._mutation_lock:
            if session_id in self._open_sessions or workspace.exists():
                raise LocalWorktreeSandboxError(_ALREADY_EXISTS, operation="open")
            try:
                self.workspace_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LocalWorktreeSandboxError(_ROOT_UNAVAILABLE, operation="open") from exc

            try:
                await self._run_git(
                    "worktree",
                    "add",
                    "--detach",
                    str(workspace),
                    self.base_ref,
                    error_code="LOCAL_WORKTREE_CREATE_FAILED",
                )
            except (Exception, asyncio.CancelledError):
                await asyncio.shield(self._remove_managed_worktree(workspace, registered=False))
                raise

            if not workspace.is_dir():
                await asyncio.shield(self._remove_managed_worktree(workspace, registered=False))
                raise LocalWorktreeSandboxError(_CREATE_FAILED, operation="open")
            self._open_sessions[session_id] = workspace

        run_label, task_slug = self._result_labels(request)
        resumed_from = await self._resume_latest_snapshot(run_label, task_slug, workspace)
        return SandboxSession(
            session_id=session_id,
            workspace_uri=workspace.as_uri(),
            metadata={
                "adapter": self.service_name,
                "base_ref": self.base_ref,
                "disposable": True,
                "mock": False,
                "opencode_directory": str(workspace),
                "result_run_label": run_label,
                "result_task_slug": task_slug,
                "resumed_from": str(resumed_from) if resumed_from is not None else None,
            },
        )

    async def close_session(self, request: TaskRequest, session: SandboxSession) -> None:  # noqa: ARG002
        """Preserve a changed workspace under its run label, then remove the worktree."""
        preserved: Path | None = None
        if session.metadata.get("mock") is not True:
            preserved = await self._preserve_changed_workspace(session)
        async with self._mutation_lock:
            workspace = self._open_sessions.pop(session.session_id, None)
            if workspace is None:
                return
            self._assert_managed_path(workspace)
            await self._remove_managed_worktree(workspace, registered=True)

    # ---- durable result preservation -----------------------------------

    @staticmethod
    def _result_labels(request: TaskRequest) -> tuple[str | None, str | None]:
        context = request.context if isinstance(request.context, dict) else {}
        name = context.get("workflow_name")
        number = context.get("workflow_run_number")
        if not isinstance(name, str) or not name.strip() or not isinstance(number, int) or number <= 0:
            return None, None
        run_label = _sanitize_name(f"{name}-run-{number}")
        task_slug = _sanitize_name(request.name) or "task"
        return run_label, task_slug

    async def _preserve_changed_workspace(self, session: SandboxSession) -> Path | None:
        """Copy a workspace with real changes into its durable per-run folder."""
        run_label = session.metadata.get("result_run_label")
        task_slug = session.metadata.get("result_task_slug")
        if not isinstance(run_label, str) or not isinstance(task_slug, str):
            return None
        workspace = self._open_sessions.get(session.session_id)
        if workspace is None or not workspace.is_dir():
            return None
        try:
            status = await self._run_git_in(
                workspace,
                "status",
                "--porcelain",
                error_code="LOCAL_WORKTREE_STATUS_FAILED",
            )
        except LocalWorktreeSandboxError:
            return None
        if not status.strip():
            return None
        run_root = self.workspace_root / run_label
        target = run_root / task_slug
        suffix = 2
        while target.exists():
            target = run_root / f"{task_slug}-{suffix}"
            suffix += 1
        try:
            run_root.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                copytree,
                workspace,
                target,
                ignore=ignore_patterns(".git"),
            )
        except OSError:
            with suppress(OSError):
                shutil.rmtree(target, ignore_errors=True)
            return None
        return target

    async def _resume_latest_snapshot(self, run_label: str | None, task_slug: str | None, workspace: Path) -> Path | None:
        """Prefill a fresh worktree with the newest preserved snapshot of the same task.

        Failed or timed-out attempts keep their partial output under
        ``{run_label}/{task_slug}`` (with ``-2``/``-3`` suffixes on later
        attempts). Restoring the latest snapshot lets a retry continue the
        previous work instead of repeating it from zero.
        """
        if not run_label or not task_slug:
            return None
        run_root = self.workspace_root / run_label
        if not run_root.is_dir():
            return None
        numbered: list[tuple[int, Path]] = []
        for candidate in run_root.glob(f"{task_slug}-[0-9]*"):
            stem = candidate.name[len(task_slug) + 1 :]
            if stem.isdigit():
                numbered.append((int(stem), candidate))
        latest_numbered = max(numbered, default=(0, None))[1]
        base = run_root / task_slug
        if latest_numbered is not None:
            snapshot = latest_numbered
        elif base.is_dir():
            snapshot = base
        else:
            return None
        try:
            await asyncio.to_thread(
                copytree,
                snapshot,
                workspace,
                dirs_exist_ok=True,
                ignore=ignore_patterns(".git"),
            )
        except OSError:
            return None
        return snapshot

    def _validate_configuration(self) -> None:
        invalid_base_ref = (
            not self.base_ref
            or self.base_ref.startswith("-")
            or any(character.isspace() for character in self.base_ref)
        )
        if invalid_base_ref:
            msg = "Local worktree base ref must be a non-option Git revision without whitespace."
            raise ValueError(msg)
        if not self.git_executable.strip():
            msg = "Local worktree Git executable cannot be empty."
            raise ValueError(msg)
        if self.workspace_root == self.source_repository:
            msg = "Local worktree root must differ from the source repository."
            raise ValueError(msg)
        if self.workspace_root.is_relative_to(self.source_repository):
            msg = "Local worktree root must be outside the source repository."
            raise ValueError(msg)
        if self.source_repository.is_relative_to(self.workspace_root):
            msg = "Local worktree root cannot contain the source repository."
            raise ValueError(msg)

    def _assert_managed_path(self, path: Path) -> None:
        if path == self.workspace_root or not path.is_relative_to(self.workspace_root):
            raise LocalWorktreeSandboxError(_PATH_REJECTED, operation="cleanup")

    async def _remove_managed_worktree(self, workspace: Path, *, registered: bool) -> None:
        self._assert_managed_path(workspace)
        if registered or workspace.exists():
            # Git can lose registration state after a partial failure. The exact
            # managed path is still safe to remove and prune below.
            with suppress(LocalWorktreeSandboxError):
                await self._run_git(
                    "worktree",
                    "remove",
                    "--force",
                    str(workspace),
                    error_code=_REMOVE_FAILED,
                )
        if workspace.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, workspace)
            except OSError as exc:
                raise LocalWorktreeSandboxError(_REMOVE_FAILED, operation="cleanup") from exc
        await self._run_git(
            "worktree",
            "prune",
            error_code="LOCAL_WORKTREE_PRUNE_FAILED",
        )
        if workspace.exists():
            raise LocalWorktreeSandboxError(_REMOVE_FAILED, operation="cleanup")

    async def _run_git(self, *arguments: str, error_code: str) -> str:
        return await self._run_git_in(self.source_repository, *arguments, error_code=error_code)

    async def _run_git_in(self, working_directory: Path, *arguments: str, error_code: str) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                self.git_executable,
                # Keep Windows long-path support local to adapter Git subprocesses.
                "-c",
                "core.longpaths=true",
                "-C",
                str(working_directory),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise LocalWorktreeSandboxError(_GIT_UNAVAILABLE, operation=arguments[0]) from exc
        try:
            stdout, _stderr = await process.communicate()
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise
        if process.returncode != 0:
            raise LocalWorktreeSandboxError(error_code, operation=arguments[0])
        return stdout.decode("utf-8", errors="replace")


__all__ = ["LocalWorktreeSandboxAdapter", "LocalWorktreeSandboxError"]

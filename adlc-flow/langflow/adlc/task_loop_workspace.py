"""Exact-identity detached worktrees and capture/restore of bounded text candidates."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopFile, LiveLoopSpec
from langflow.adlc.task_loop_models import MAX_FILE_BYTES, validate_file_path

if TYPE_CHECKING:
    from pathlib import Path


class LiveLoopError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class TaskLoopWorkspace:
    """Filesystem isolation for trusted local development, not a security container."""

    def __init__(self, source_repository: Path, root: Path) -> None:
        self.source = source_repository.resolve()
        self.root = root.resolve()
        if self.root == self.source or self.root.is_relative_to(self.source) or self.source.is_relative_to(self.root):
            code = "TASK_LOOP_WORKSPACE_CONFIGURATION_INVALID"
            raise LiveLoopError(code)
        self.root.mkdir(parents=True, exist_ok=True)

    async def git(self, directory: Path, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.eol=lf",
            "-c",
            "core.longpaths=true",
            "-c",
            f"core.hooksPath={self.root / 'disabled-hooks'}",
            "-c",
            "submodule.recurse=false",
            "-C",
            str(directory),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode != 0:
            code = "TASK_LOOP_GIT_FAILED"
            raise LiveLoopError(code)
        return stdout

    def path(self, attempt_id: UUID, purpose: str) -> Path:
        if purpose not in {"agent", "verify", "session"}:
            code = "TASK_LOOP_WORKSPACE_IDENTITY_INVALID"
            raise LiveLoopError(code)
        target = self.root / f"{attempt_id.hex}-{purpose}"
        self._validate_target(target)
        return target

    def _validate_target(self, target: Path) -> None:
        resolved = target.resolve()
        if target.is_symlink() or resolved.parent != self.root or resolved == self.source:
            code = "TASK_LOOP_WORKSPACE_IDENTITY_INVALID"
            raise LiveLoopError(code)

    @staticmethod
    def file_path(directory: Path, relative: str) -> Path:
        validate_file_path(relative)
        target = directory.joinpath(*relative.split("/"))
        cursor = target
        while cursor != directory:
            if cursor.is_symlink() or cursor.is_junction():
                code = "TASK_LOOP_SYMLINK_REJECTED"
                raise LiveLoopError(code)
            cursor = cursor.parent
        if not target.resolve().is_relative_to(directory.resolve()):
            code = "TASK_LOOP_PATH_REJECTED"
            raise LiveLoopError(code)
        return target

    async def baseline(self, commit: str, path: str) -> LiveLoopFile | None:
        entries = await self.git(self.source, "ls-tree", "-z", commit, "--", path)
        if not entries:
            return None
        header, actual = entries.rstrip(b"\0").split(b"\t", 1)
        mode, kind, object_id = header.split(b" ")
        if actual.decode("utf-8") != path or kind != b"blob" or mode not in {b"100644", b"100755"}:
            code = "TASK_LOOP_SOURCE_FILE_INVALID"
            raise LiveLoopError(code)
        content = await self.git(self.source, "cat-file", "blob", object_id.decode("ascii"))
        try:
            return LiveLoopFile(content=content.decode("utf-8"), mode=mode.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            code = "TASK_LOOP_TEXT_BOUND_EXCEEDED"
            raise LiveLoopError(code) from exc

    async def validate_spec(self, spec: LiveLoopSpec) -> None:
        actual = (
            (await self.git(self.source, "rev-parse", "--verify", f"{spec.base_commit}^{{commit}}")).decode().strip()
        )
        if actual != spec.base_commit:
            code = "TASK_LOOP_BASE_COMMIT_INVALID"
            raise LiveLoopError(code)
        for path in (*spec.writable_paths, *(check.test_path for check in spec.verification_commands)):
            baseline = await self.baseline(spec.base_commit, path)
            if path not in spec.writable_paths and baseline is None:
                code = "TASK_LOOP_TEST_NOT_TRACKED"
                raise LiveLoopError(code)

    async def create(self, attempt_id: UUID, purpose: str, candidate: LiveLoopCandidate) -> Path:
        target = self.path(attempt_id, purpose)
        if target.exists():
            code = "TASK_LOOP_WORKSPACE_ALREADY_EXISTS"
            raise LiveLoopError(code)
        await self.git(self.source, "worktree", "add", "--detach", str(target), candidate.base_commit)
        for relative, item in candidate.changes.items():
            path = self.file_path(target, relative)
            if item is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.content.encode("utf-8"))
                if os.name != "nt":
                    path.chmod(0o755 if item.mode == "100755" else 0o644)
        return target

    async def capture(
        self, task_id: UUID, iteration: int, spec: LiveLoopSpec, parent: LiveLoopCandidate, directory: Path
    ) -> LiveLoopCandidate:
        changed = await self.git(directory, "diff", "--name-only", "-z", spec.base_commit, "--")
        untracked = await self.git(directory, "ls-files", "--others", "--exclude-standard", "-z")
        paths = {path.decode("utf-8") for path in (changed + untracked).split(b"\0") if path}
        if paths - set(spec.writable_paths):
            code = "TASK_LOOP_WRITE_SCOPE_VIOLATION"
            raise LiveLoopError(code)
        await self.validate_protected_tests(spec, directory)
        changes: dict[str, LiveLoopFile | None] = {}
        total_bytes = 0
        for relative in spec.writable_paths:
            path = self.file_path(directory, relative)
            baseline = await self.baseline(spec.base_commit, relative)
            item = None
            if path.exists():
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    code = "TASK_LOOP_TEXT_BOUND_EXCEEDED"
                    raise LiveLoopError(code)
                content = path.read_bytes()
                total_bytes += len(content)
                mode = baseline.mode if os.name == "nt" and baseline else "100644"
                if os.name != "nt" and path.stat().st_mode & stat.S_IXUSR:
                    mode = "100755"
                try:
                    item = LiveLoopFile(content=content.decode("utf-8"), mode=mode)
                except (UnicodeDecodeError, ValueError) as exc:
                    code = "TASK_LOOP_TEXT_BOUND_EXCEEDED"
                    raise LiveLoopError(code) from exc
            if item != baseline:
                changes[relative] = item
        if total_bytes > MAX_FILE_BYTES:
            code = "TASK_LOOP_TEXT_BOUND_EXCEEDED"
            raise LiveLoopError(code)
        digest = LiveLoopCandidate.digest(spec.base_commit, changes)
        return LiveLoopCandidate(
            candidate_id=uuid5(task_id, f"live-loop:{iteration}:{digest}"),
            parent_candidate_id=parent.candidate_id,
            iteration=iteration,
            base_commit=spec.base_commit,
            changes=changes,
            content_digest=digest,
        )

    async def validate_protected_tests(self, spec: LiveLoopSpec, directory: Path) -> None:
        # Directly inspect protected tests even if an agent changes index flags.
        for check in spec.verification_commands:
            baseline = await self.baseline(spec.base_commit, check.test_path)
            path = self.file_path(directory, check.test_path)
            if baseline is None or not path.is_file() or path.read_bytes() != baseline.content.encode("utf-8"):
                code = "TASK_LOOP_PROTECTED_TEST_CHANGED"
                raise LiveLoopError(code)

    async def validate_checkout(self, spec: LiveLoopSpec, candidate: LiveLoopCandidate, directory: Path) -> None:
        await self.validate_protected_tests(spec, directory)
        for relative in spec.writable_paths:
            path = self.file_path(directory, relative)
            expected = (
                candidate.changes[relative]
                if relative in candidate.changes
                else await self.baseline(spec.base_commit, relative)
            )
            if expected is None:
                exact = not path.exists()
            else:
                exact = path.is_file() and path.read_bytes() == expected.content.encode("utf-8")
                if exact and os.name != "nt":
                    mode = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
                    exact = mode == expected.mode
            if not exact:
                code = "TASK_LOOP_CHECKOUT_NOT_EXACT"
                raise LiveLoopError(code)

    async def remove(self, attempt_id: UUID, purpose: str) -> None:
        target = self.path(attempt_id, purpose)
        # Only remove the two deterministic directories owned by this durable attempt.
        try:
            await self.git(self.source, "worktree", "remove", "--force", str(target))
        except LiveLoopError:
            if target.exists():
                self._validate_target(target)
                shutil.rmtree(target)

"""Local folder discovery and immutable, committed source snapshots."""

# ruff: noqa: EM101 - domain exceptions pair a stable error code with a user-facing message.

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from shutil import which
from uuid import UUID, uuid4

from pydantic import BaseModel

APP_ROOT = Path(__file__).resolve().parents[2]
LOCAL_PROJECT_KEY = "adlc_local_project"
MAX_FOLDER_PATH = 4096
MAX_FOLDERS = 200


class LocalProjectError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code, self.status_code = code, status_code


class LocalFolder(BaseModel):
    name: str
    path: str


class LocalFolderListing(BaseModel):
    path: str | None
    parent: str | None
    roots: list[LocalFolder]
    folders: list[LocalFolder]
    truncated: bool = False


class LocalProjectRead(BaseModel):
    project_id: UUID
    name: str
    source_path: str
    ready: bool
    base_commit: str | None = None
    uncommitted_changes: bool = False
    message: str | None = None


def local_roots() -> list[Path]:
    configured = os.getenv("ADLC_LOCAL_PROJECT_ROOTS", "").strip()
    if configured:
        paths = configured.split(";")
    elif os.name == "nt":
        paths = [f"{letter}:/" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    else:
        paths = [str(APP_ROOT.parent.parent), str(Path.home())]
    return list(dict.fromkeys(Path(p).expanduser().resolve() for p in paths if p and Path(p).expanduser().is_dir()))


def checked_folder(value: str) -> Path:
    if not value or len(value) > MAX_FOLDER_PATH or "\0" in value:
        raise LocalProjectError("LOCAL_FOLDER_INVALID", "Choose an existing folder.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise LocalProjectError("LOCAL_FOLDER_INVALID", "Use the full folder path.")
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LocalProjectError("LOCAL_FOLDER_UNAVAILABLE", "The folder is unavailable on this computer.") from exc
    if not path.is_dir() or not any(path == root or path.is_relative_to(root) for root in local_roots()):
        raise LocalProjectError(
            "LOCAL_FOLDER_NOT_ALLOWED", "Choose a folder inside an available project location.", 403
        )
    return path


def list_local_folders(value: str | None = None) -> LocalFolderListing:
    roots = [LocalFolder(name=p.name or str(p), path=str(p)) for p in local_roots()]
    if not value:
        return LocalFolderListing(path=None, parent=None, roots=roots, folders=roots)
    path = checked_folder(value)
    try:
        folders = sorted(
            (p for p in path.iterdir() if not p.name.startswith(".") and p.is_dir() and not p.is_symlink()),
            key=lambda p: p.name.casefold(),
        )
    except OSError as exc:
        raise LocalProjectError("LOCAL_FOLDER_UNAVAILABLE", "This folder cannot be opened.", 403) from exc
    parent = str(path.parent) if any(path.parent == r or path.parent.is_relative_to(r) for r in local_roots()) else None
    return LocalFolderListing(
        path=str(path),
        parent=parent,
        roots=roots,
        folders=[LocalFolder(name=p.name, path=str(p)) for p in folders[:MAX_FOLDERS]],
        truncated=len(folders) > MAX_FOLDERS,
    )


def git_at(path: Path, *args: str, timeout: int = 90) -> str:
    executable = which("git")
    if executable is None:
        raise LocalProjectError("LOCAL_PROJECT_GIT_UNAVAILABLE", "Git is unavailable on this computer.")
    env = {
        k: os.environ[k]
        for k in ("PATH", "Path", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "PATHEXT")
        if k in os.environ
    }
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(  # noqa: S603 - fixed Git executable and argument array, no shell
            [
                executable,
                "--no-replace-objects",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.longpaths=true",
                "-c",
                "protocol.ext.allow=never",
                "-C",
                str(path),
                *args,
            ],
            capture_output=True,
            check=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LocalProjectError(
            "LOCAL_PROJECT_GIT_UNAVAILABLE", "The project's committed source could not be read."
        ) from exc
    return result.stdout.decode("utf-8", errors="strict").strip()


def inspect_local_project(project_id: UUID, name: str, source_path: str) -> LocalProjectRead:
    try:
        source = checked_folder(source_path)
        top = Path(git_at(source, "rev-parse", "--show-toplevel")).resolve()
        if top != source:
            raise LocalProjectError("LOCAL_PROJECT_ROOT_REQUIRED", "Choose the repository's root folder.")
        commit = git_at(source, "rev-parse", "--verify", "HEAD^{commit}")
        dirty = bool(git_at(source, "status", "--porcelain", "--untracked-files=normal"))
        return LocalProjectRead(
            project_id=project_id,
            name=name,
            source_path=str(source),
            ready=True,
            base_commit=commit,
            uncommitted_changes=dirty,
            message="Runs use committed files; uncommitted changes stay in your folder." if dirty else None,
        )
    except LocalProjectError as exc:
        return LocalProjectRead(
            project_id=project_id,
            name=name,
            source_path=source_path,
            ready=False,
            message=str(exc)
            if exc.code != "LOCAL_PROJECT_GIT_UNAVAILABLE"
            else "Make an initial Git commit in this folder to enable live coding.",
        )


def project_source_root() -> Path:
    return (
        Path(os.getenv("ADLC_LOCAL_PROJECT_SOURCE_ROOT", str(APP_ROOT / "data" / "project-sources")))
        .expanduser()
        .resolve()
    )


def snapshot_path(reference: dict) -> Path:
    import re

    try:
        project_id = str(UUID(reference["project_id"]))
        commit = reference["base_commit"]
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise ValueError
        if reference.get("source_ref") != f"{project_id}/{commit}":
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LocalProjectError(
            "LOCAL_PROJECT_REFERENCE_INVALID", "The saved project source reference is invalid."
        ) from exc
    root = project_source_root()
    path = (root / project_id / commit).resolve()
    if not path.is_relative_to(root):
        raise LocalProjectError("LOCAL_PROJECT_REFERENCE_INVALID", "The project snapshot is outside its source store.")
    return path


def prepare_project_source(project_id: UUID, name: str, source_path: str) -> dict:
    read = inspect_local_project(project_id, name, source_path)
    if not read.ready:
        raise LocalProjectError("LOCAL_PROJECT_NOT_READY", read.message or "The local project is not ready.")
    reference = {
        "project_id": str(project_id),
        "name": name,
        "base_commit": read.base_commit,
        "source_ref": f"{project_id}/{read.base_commit}",
    }
    destination = snapshot_path(reference)
    if destination.exists():
        if git_at(destination, "rev-parse", "--verify", "HEAD^{commit}") != read.base_commit:
            raise LocalProjectError(
                "LOCAL_PROJECT_SNAPSHOT_INVALID", "The saved source snapshot does not match the reviewed commit."
            )
        return reference
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".preparing-{uuid4()}"
    git_at(
        destination.parent,
        "clone",
        "--no-local",
        "--no-checkout",
        "--",
        str(checked_folder(source_path)),
        str(temporary),
    )
    git_at(temporary, "checkout", "--detach", read.base_commit)
    git_at(temporary, "remote", "remove", "origin")
    try:
        temporary.rename(destination)
    except FileExistsError:
        # A concurrent compiler may already have published this same snapshot.
        if git_at(destination, "rev-parse", "HEAD") != read.base_commit:
            raise LocalProjectError("LOCAL_PROJECT_SNAPSHOT_INVALID", "The project source snapshot changed.") from None
    return reference

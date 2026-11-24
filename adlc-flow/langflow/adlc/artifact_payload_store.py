"""Bounded, optionally durable payload retention for reviewable ADLC artifacts."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from langflow.adlc.models import Artifact

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 32 * 1024 * 1024
DEFAULT_RETENTION = timedelta(hours=24)


class ArtifactPayloadStoreError(RuntimeError):
    """Secret-safe write failure at the bounded artifact boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ArtifactPayloadUnavailableError(LookupError):
    """A known artifact's retained payload is absent or expired."""


class SourcePatchFile(BaseModel):
    file: str
    patch: str
    additions: int
    deletions: int
    status: str | None = None


class SourcePatchSnapshot(BaseModel):
    format: Literal["opencode-vcs-diff-v1", "harness-git-diff-v1"]
    files: list[SourcePatchFile]
    reported_files: list[str]
    base_commit: str | None = Field(default=None, exclude_if=lambda value: value is None)


class SourcePatchRead(SourcePatchSnapshot):
    artifact: Artifact


@dataclass(frozen=True, slots=True)
class _Entry:
    artifact_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    checksum: str
    payload: bytes
    expires_at: datetime


class BoundedArtifactPayloadStore:
    """Keep small immutable payloads until expiry, without evicting active reviews."""

    def __init__(
        self,
        *,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        retention: timedelta = DEFAULT_RETENTION,
        now: Callable[[], datetime] | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        if max_artifact_bytes <= 0 or max_total_bytes < max_artifact_bytes or retention <= timedelta(0):
            msg = "Artifact payload limits and retention must be positive and internally consistent."
            raise ValueError(msg)
        self.max_artifact_bytes = max_artifact_bytes
        self.max_total_bytes = max_total_bytes
        self.retention = retention
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._entries: dict[UUID, _Entry] = {}
        self._total_bytes = 0
        self._lock = RLock()
        self._database_path = Path(database_path).resolve() if database_path is not None else None
        if self._database_path is not None:
            self._restore_payloads()

    def _restore_payloads(self) -> None:
        if self._database_path is None:
            return
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._database_path)) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS adlc_artifact_payloads (
                artifact_id TEXT PRIMARY KEY, workflow_run_id TEXT NOT NULL,
                task_run_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                checksum TEXT NOT NULL, payload BLOB NOT NULL, expires_at TEXT NOT NULL
            )""")
            connection.commit()
            rows = connection.execute("SELECT * FROM adlc_artifact_payloads").fetchall()
        for artifact_id, run_id, task_id, attempt_id, checksum, payload, expiry in rows:
            expires_at = datetime.fromisoformat(expiry)
            if expires_at <= self._now():
                continue
            if len(payload) > self.max_artifact_bytes or hashlib.sha256(payload).hexdigest() != checksum:
                code = "ARTIFACT_PAYLOAD_STORE_INVALID"
                raise ArtifactPayloadStoreError(code)
            entry = _Entry(
                UUID(artifact_id), UUID(run_id), UUID(task_id), UUID(attempt_id), checksum, bytes(payload), expires_at
            )
            self._entries[entry.artifact_id] = entry
            self._total_bytes += len(payload)
        if self._total_bytes > self.max_total_bytes:
            code = "ARTIFACT_PAYLOAD_STORE_FULL"
            raise ArtifactPayloadStoreError(code)
        self._prune_expired()

    def _persist_entry(self, entry: _Entry) -> None:
        if self._database_path is None:
            return
        with closing(sqlite3.connect(self._database_path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT workflow_run_id, task_run_id, attempt_id, checksum, payload "
                "FROM adlc_artifact_payloads WHERE artifact_id=?",
                (str(entry.artifact_id),),
            ).fetchone()
            if existing is not None:
                expected = (
                    str(entry.workflow_run_id),
                    str(entry.task_run_id),
                    str(entry.attempt_id),
                    entry.checksum,
                    entry.payload,
                )
                if existing != expected:
                    code = "ARTIFACT_PAYLOAD_ID_CONFLICT"
                    raise ArtifactPayloadStoreError(code)
                connection.commit()
                return
            retained_bytes = connection.execute(
                "SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM adlc_artifact_payloads"
            ).fetchone()[0]
            if retained_bytes + len(entry.payload) > self.max_total_bytes:
                code = "ARTIFACT_PAYLOAD_STORE_FULL"
                raise ArtifactPayloadStoreError(code)
            connection.execute(
                """INSERT INTO adlc_artifact_payloads
                (artifact_id, workflow_run_id, task_run_id, attempt_id, checksum, payload, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(entry.artifact_id),
                    str(entry.workflow_run_id),
                    str(entry.task_run_id),
                    str(entry.attempt_id),
                    entry.checksum,
                    entry.payload,
                    entry.expires_at.astimezone(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    @property
    def total_bytes(self) -> int:
        with self._lock:
            self._prune_expired()
            return self._total_bytes

    def expires_at(self, created_at: datetime) -> datetime:
        return created_at + self.retention

    def retain(self, artifact: Artifact, payload: bytes) -> None:
        """Accept only a checksummed, bounded payload before its worktree disappears."""
        if len(payload) > self.max_artifact_bytes:
            code = "ARTIFACT_PAYLOAD_TOO_LARGE"
            raise ArtifactPayloadStoreError(code)
        if artifact.size_bytes != len(payload) or artifact.checksum.value != hashlib.sha256(payload).hexdigest():
            code = "ARTIFACT_PAYLOAD_CHECKSUM_MISMATCH"
            raise ArtifactPayloadStoreError(code)
        now = self._now()
        expires_at = min(artifact.expires_at or self.expires_at(now), self.expires_at(now))
        if expires_at <= now:
            code = "ARTIFACT_PAYLOAD_ALREADY_EXPIRED"
            raise ArtifactPayloadStoreError(code)
        entry = _Entry(
            artifact_id=artifact.artifact_id,
            workflow_run_id=artifact.workflow_run_id,
            task_run_id=artifact.task_run_id,
            attempt_id=artifact.attempt_id,
            checksum=artifact.checksum.value,
            payload=bytes(payload),
            expires_at=expires_at,
        )
        with self._lock:
            self._prune_expired()
            existing = self._entries.get(artifact.artifact_id)
            if existing is not None:
                if (
                    existing.workflow_run_id != entry.workflow_run_id
                    or existing.task_run_id != entry.task_run_id
                    or existing.attempt_id != entry.attempt_id
                    or existing.checksum != entry.checksum
                    or existing.payload != entry.payload
                ):
                    code = "ARTIFACT_PAYLOAD_ID_CONFLICT"
                    raise ArtifactPayloadStoreError(code)
                return
            if self._total_bytes + len(payload) > self.max_total_bytes:
                code = "ARTIFACT_PAYLOAD_STORE_FULL"
                raise ArtifactPayloadStoreError(code)
            self._persist_entry(entry)
            self._entries[artifact.artifact_id] = entry
            self._total_bytes += len(payload)

    def read(self, artifact: Artifact) -> bytes:
        """Read only the exact run/task/attempt/checksum captured at write time."""
        with self._lock:
            self._prune_expired()
            entry = self._entries.get(artifact.artifact_id)
            if (
                entry is None
                or entry.workflow_run_id != artifact.workflow_run_id
                or entry.task_run_id != artifact.task_run_id
                or entry.attempt_id != artifact.attempt_id
                or entry.checksum != artifact.checksum.value
            ):
                code = "ARTIFACT_PAYLOAD_UNAVAILABLE"
                raise ArtifactPayloadUnavailableError(code)
            return entry.payload

    def _prune_expired(self) -> None:
        now = self._now()
        expired_ids = [artifact_id for artifact_id, entry in self._entries.items() if entry.expires_at <= now]
        for artifact_id in expired_ids:
            self._total_bytes -= len(self._entries.pop(artifact_id).payload)
        if self._database_path is not None:
            with closing(sqlite3.connect(self._database_path)) as connection:
                connection.execute(
                    "DELETE FROM adlc_artifact_payloads WHERE expires_at <= ?",
                    (now.astimezone(timezone.utc).isoformat(),),
                )
                connection.commit()


__all__ = [
    "ArtifactPayloadStoreError",
    "ArtifactPayloadUnavailableError",
    "BoundedArtifactPayloadStore",
    "SourcePatchFile",
    "SourcePatchRead",
    "SourcePatchSnapshot",
]

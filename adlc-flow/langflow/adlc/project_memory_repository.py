"""Owner/run-scoped retained context, separate from official ADLC evidence.

Intent is durable before a gateway read. A lost read is not silently reissued;
the human/agent can deliberately ask again with a new command key. No remote
ingestion or delete operation exists in this repository.
"""

# ruff: noqa: EM101, TRY300 - validated transaction returns; fixed diagnostics only.
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from uuid import UUID, uuid4

from langflow.adlc.project_memory_models import (
    MAX_ARCHIVE_BYTES,
    MAX_RECORDS,
    MemoryBinding,
    MemoryQuery,
    MemoryRead,
    MemoryRecord,
    ProjectMemoryError,
    scope_names,
)
from langflow.adlc.verification_models import canonical, digest

MAX_PAGE_SIZE = 100


class MemoryRepository:
    def __init__(self, path: Path | None):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS adlc_memory_context (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL,
            command_key TEXT NOT NULL, command_digest TEXT NOT NULL, binding TEXT NOT NULL,
            state TEXT NOT NULL, body TEXT, content_digest TEXT, error_code TEXT,
            UNIQUE(owner, run_id, command_key))""")
        self.db.commit()

    def close(self):
        self.db.close()

    def _read(self, row):
        try:
            record = MemoryRecord.model_validate_json(row["body"])
            tenant, dataset = scope_names(row["owner"], record.binding.project_id)
            if (
                record.record_id != UUID(row["id"])
                or str(record.binding.workflow_run_id) != row["run_id"]
                or canonical(record.binding).decode() != row["binding"]
                or record.tenant_id != tenant
                or record.dataset != dataset
                or digest(record) != row["content_digest"]
            ):
                raise ValueError
            return MemoryRead(record=record, content_digest=row["content_digest"])
        except (ValueError, TypeError, RecursionError):
            raise ProjectMemoryError("MEMORY_ARCHIVE_INVALID", 503) from None

    def begin(self, *, owner: str, binding: MemoryBinding, command: MemoryQuery):
        scope = canonical(binding).decode()
        request_digest = digest(
            {"binding": binding.model_dump(mode="json"), "command": command.model_dump(mode="json")}
        )
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute(
                    "SELECT * FROM adlc_memory_context WHERE owner=? AND run_id=? AND command_key=?",
                    (owner, str(binding.workflow_run_id), command.idempotency_key),
                ).fetchone()
                if row:
                    if row["command_digest"] != request_digest:
                        raise ProjectMemoryError("MEMORY_QUERY_CONFLICT")
                    if row["state"] == "COMPLETE":
                        return self._read(row)
                    raise ProjectMemoryError(row["error_code"] or "MEMORY_QUERY_UNCONFIRMED")
                count, size = self.db.execute(
                    "SELECT count(*), coalesce(sum(length(CAST(body AS BLOB))),0) FROM adlc_memory_context"
                ).fetchone()
                if count >= MAX_RECORDS or size >= MAX_ARCHIVE_BYTES:
                    raise ProjectMemoryError("MEMORY_ARCHIVE_FULL", 503)
                record_id = uuid4()
                self.db.execute(
                    "INSERT INTO adlc_memory_context(id,owner,run_id,command_key,command_digest,binding,state) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (
                        str(record_id),
                        owner,
                        str(binding.workflow_run_id),
                        command.idempotency_key,
                        request_digest,
                        scope,
                        "PENDING",
                    ),
                )
                self.db.commit()
                return record_id
            except sqlite3.Error:
                raise ProjectMemoryError("MEMORY_ARCHIVE_UNAVAILABLE", 503) from None
            finally:
                if self.db.in_transaction:
                    self.db.rollback()

    def complete(self, record: MemoryRecord, *, owner: str):
        body = canonical(record).decode()
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute(
                    "SELECT * FROM adlc_memory_context WHERE id=? AND owner=?", (str(record.record_id), owner)
                ).fetchone()
                if not row or row["state"] != "PENDING" or row["binding"] != canonical(record.binding).decode():
                    raise ProjectMemoryError("MEMORY_QUERY_CONFLICT")
                tenant, dataset = scope_names(owner, record.binding.project_id)
                if record.tenant_id != tenant or record.dataset != dataset:
                    raise ProjectMemoryError("MEMORY_SCOPE_MISMATCH", 502)
                size = self.db.execute(
                    "SELECT coalesce(sum(length(CAST(body AS BLOB))),0) FROM adlc_memory_context"
                ).fetchone()[0]
                if size + len(body.encode()) > MAX_ARCHIVE_BYTES:
                    raise ProjectMemoryError("MEMORY_ARCHIVE_FULL", 503)
                self.db.execute(
                    "UPDATE adlc_memory_context SET state='COMPLETE',body=?,content_digest=? WHERE id=?",
                    (body, digest(record), str(record.record_id)),
                )
                saved = self.db.execute(
                    "SELECT * FROM adlc_memory_context WHERE id=?", (str(record.record_id),)
                ).fetchone()
                result = self._read(saved)
                self.db.commit()
                return result
            except sqlite3.Error:
                raise ProjectMemoryError("MEMORY_ARCHIVE_UNAVAILABLE", 503) from None
            finally:
                if self.db.in_transaction:
                    self.db.rollback()

    def fail(self, record_id, *, owner, code):
        with self.lock:
            try:
                self.db.execute(
                    "UPDATE adlc_memory_context SET state='FAILED',error_code=? "
                    "WHERE id=? AND owner=? AND state='PENDING'",
                    (code, str(record_id), owner),
                )
                self.db.commit()
            except sqlite3.Error:
                raise ProjectMemoryError("MEMORY_ARCHIVE_UNAVAILABLE", 503) from None

    def list(self, *, owner, run_id, session_id=None, project_id=None, limit=100, offset=0):
        if not (1 <= limit <= MAX_PAGE_SIZE and 0 <= offset <= MAX_RECORDS):
            raise ProjectMemoryError("MEMORY_QUERY_INVALID", 422)
        with self.lock:
            try:
                rows = self.db.execute(
                    "SELECT * FROM adlc_memory_context WHERE owner=? AND run_id=? AND state='COMPLETE' "
                    "ORDER BY rowid DESC",
                    (owner, str(run_id)),
                ).fetchall()
                # Check binding before content parsing: never expose an unrelated session.
                if session_id is not None:
                    scoped = []
                    for row in rows:
                        binding = json.loads(row["binding"])
                        if binding.get("source_session_id") == session_id or (
                            binding.get("source_session_id") is None
                            and project_id is not None
                            and binding.get("project_id") == str(project_id)
                        ):
                            scoped.append(row)
                    rows = scoped
                return [self._read(r) for r in rows[offset : offset + limit]]
            except (sqlite3.Error, ValueError, RecursionError):
                raise ProjectMemoryError("MEMORY_ARCHIVE_INVALID", 503) from None


_repositories = {}


def get_memory_repository():
    default = str(Path(__file__).resolve().parents[2] / "data" / "adlc-memory-context.sqlite3")
    value = os.getenv("ADLC_MEMORY_DB_PATH", default)
    if value not in _repositories:
        _repositories[value] = MemoryRepository(Path(value).resolve() if value else None)
    return _repositories[value]

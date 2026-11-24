"""Real Memory Adapter — SQLite-based persistent memory.

Stores task context and results in a SQLite database for retrieval
across workflow runs. Supports:
- Persistent storage (survives process restart)
- Query by memory_refs, workflow_run_id, task_run_id
- TTL-based cleanup of old records
- Thread-safe access via SQLite's built-in locking
- Integration with Evidence Plane (submit memory_record evidence)

This adapter is opt-in: set ADLC_MEMORY_ADAPTER=real to enable.
The MockMemoryAdapter remains the default for backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from langflow.adlc.adapter_interfaces import MemoryContext
from langflow.adlc.evidence_plane import (
    Evidence,
    EvidencePlaneService,
    EvidenceType,
    ValidationStatus,
    get_default_evidence_plane,
)
from langflow.adlc.models import TaskRequest, TaskResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_to_str(value: UUID | str | None) -> str | None:
    """Convert UUID to string for SQLite storage."""
    if value is None:
        return None
    return str(value)


def _str_to_uuid(value: str | None) -> UUID | None:
    """Convert string back to UUID."""
    if value is None:
        return None
    return UUID(value)


@dataclass(frozen=True, slots=True)
class SQLiteMemoryConfig:
    """Configuration for the SQLiteMemoryAdapter."""

    db_path: Path | None = None  # None = in-memory database
    ttl_seconds: int | None = None  # None = no expiration
    cleanup_interval_seconds: int = 3600  # 1 hour
    max_records: int | None = None  # None = unlimited


class SQLiteMemoryAdapter:
    """Real memory adapter backed by SQLite.

    Stores task context (memory_refs, variables) and results in a
    SQLite database. Supports querying by various keys and TTL-based
    cleanup.
    """

    service_name = "memory:sqlite"

    def __init__(
        self,
        config: SQLiteMemoryConfig | None = None,
        evidence_plane: EvidencePlaneService | None = None,
    ) -> None:
        self._config = config or SQLiteMemoryConfig()
        self._evidence_plane = evidence_plane or get_default_evidence_plane()
        self._lock = threading.Lock()
        self._last_cleanup = _utc_now()
        # If no db_path is specified, use a temporary file so the database
        # persists across connections (in-memory databases are per-connection).
        if self._config.db_path is None:
            import tempfile

            tmp_dir = tempfile.mkdtemp(prefix="adlc_memory_")
            self._config = SQLiteMemoryConfig(
                db_path=Path(tmp_dir) / "memory.db",
                ttl_seconds=self._config.ttl_seconds,
                cleanup_interval_seconds=self._config.cleanup_interval_seconds,
                max_records=self._config.max_records,
            )
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id TEXT NOT NULL UNIQUE,
                    workflow_run_id TEXT NOT NULL,
                    task_run_id TEXT NOT NULL,
                    memory_refs TEXT NOT NULL,
                    variables TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_workflow_run_id
                    ON memory_records(workflow_run_id);
                CREATE INDEX IF NOT EXISTS idx_task_run_id
                    ON memory_records(task_run_id);
                CREATE INDEX IF NOT EXISTS idx_expires_at
                    ON memory_records(expires_at);
                """
            )
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with proper configuration."""
        if self._config.db_path is None:
            conn = sqlite3.connect(":memory:")
        else:
            self._config.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._config.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    async def load_context(self, request: TaskRequest) -> MemoryContext:
        """Load memory context for a task attempt.

        Queries the database for records matching the memory_refs
        in the request context, or falls back to the most recent
        record for the same workflow_run_id.
        """
        # Periodic cleanup
        self._maybe_cleanup()

        context = request.context if isinstance(request.context, dict) else {}
        raw_refs = context.get("memory_refs", [])
        memory_refs = tuple(str(value) for value in raw_refs) if isinstance(raw_refs, list) else ()

        with self._lock:
            with self._connect() as conn:
                # Try to find records by memory_refs first.
                variables: dict[str, Any] = {}
                metadata: dict[str, Any] = {"adapter": self.service_name}

                if memory_refs:
                    placeholders = ",".join("?" * len(memory_refs))
                    cursor = conn.execute(
                        f"SELECT variables, metadata FROM memory_records "
                        f"WHERE attempt_id IN ({placeholders}) "
                        f"ORDER BY created_at DESC LIMIT 10",
                        memory_refs,
                    )
                    for row in cursor:
                        try:
                            vars_data = json.loads(row["variables"])
                            if isinstance(vars_data, dict):
                                variables.update(vars_data)
                            meta_data = json.loads(row["metadata"])
                            if isinstance(meta_data, dict):
                                metadata.update(meta_data)
                        except (json.JSONDecodeError, TypeError):
                            pass

                # If no memory_refs match, try the most recent record
                # for the same workflow_run_id.
                if not variables and request.workflow_run_id:
                    cursor = conn.execute(
                        "SELECT variables, metadata FROM memory_records "
                        "WHERE workflow_run_id = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (_uuid_to_str(request.workflow_run_id),),
                    )
                    row = cursor.fetchone()
                    if row:
                        try:
                            vars_data = json.loads(row["variables"])
                            if isinstance(vars_data, dict):
                                variables.update(vars_data)
                            meta_data = json.loads(row["metadata"])
                            if isinstance(meta_data, dict):
                                metadata["previous_run"] = meta_data
                        except (json.JSONDecodeError, TypeError):
                            pass

                # Merge with request variables (request takes precedence).
                raw_variables = context.get("variables", {})
                if isinstance(raw_variables, dict):
                    variables.update(raw_variables)

                metadata["loaded_at"] = _utc_now().isoformat()
                metadata["record_count"] = len(memory_refs)

                return MemoryContext(
                    memory_refs=memory_refs,
                    variables=variables,
                    metadata=metadata,
                )

    async def record_result(self, request: TaskRequest, result: TaskResult) -> None:
        """Record a task result in the database.

        Stores the result as JSON along with the attempt context.
        If a record already exists for this attempt_id, it is updated.
        """
        with self._lock:
            with self._connect() as conn:
                now = _utc_now()
                expires_at = None
                if self._config.ttl_seconds is not None:
                    expires_at = (now + timedelta(seconds=self._config.ttl_seconds)).isoformat()

                # Extract variables and metadata from request context.
                context = request.context if isinstance(request.context, dict) else {}
                raw_variables = context.get("variables", {})
                variables = dict(raw_variables) if isinstance(raw_variables, dict) else {}

                raw_refs = context.get("memory_refs", [])
                memory_refs = list(raw_refs) if isinstance(raw_refs, list) else []

                metadata = {
                    "task_type": request.task_type,
                    "recorded_at": now.isoformat(),
                }

                # Serialize the result.
                result_json = result.model_dump_json()

                # Upsert the record.
                conn.execute(
                    """
                    INSERT INTO memory_records (
                        attempt_id, workflow_run_id, task_run_id,
                        memory_refs, variables, metadata,
                        result_json, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(attempt_id) DO UPDATE SET
                        result_json = excluded.result_json,
                        variables = excluded.variables,
                        metadata = excluded.metadata
                    """,
                    (
                        _uuid_to_str(request.attempt_id),
                        _uuid_to_str(request.workflow_run_id),
                        _uuid_to_str(request.task_run_id),
                        json.dumps(memory_refs),
                        json.dumps(variables),
                        json.dumps(metadata),
                        result_json,
                        now.isoformat(),
                        expires_at,
                    ),
                )
                conn.commit()

                # Enforce max_records limit.
                if self._config.max_records is not None:
                    conn.execute(
                        """
                        DELETE FROM memory_records
                        WHERE id IN (
                            SELECT id FROM memory_records
                            ORDER BY created_at DESC
                            LIMIT -1 OFFSET ?
                        )
                        """,
                        (self._config.max_records,),
                    )
                    conn.commit()

        # Submit evidence to Evidence Plane.
        self._submit_evidence(request, result)

    def _submit_evidence(self, request: TaskRequest, result: TaskResult) -> None:
        """Submit memory_record evidence to the Evidence Plane."""
        evidence = Evidence(
            evidence_type=EvidenceType.METRIC,
            payload={
                "metric": "memory_record",
                "attempt_id": str(request.attempt_id),
                "workflow_run_id": str(request.workflow_run_id),
                "task_run_id": str(request.task_run_id),
                "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            },
            producer=self.service_name,
            submitted_at=_utc_now(),
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            validation_status=ValidationStatus.VALID,
        )
        try:
            self._evidence_plane.submit_evidence(evidence)
        except Exception:  # noqa: BLE001 - evidence submission must not break memory
            pass

    def _maybe_cleanup(self) -> None:
        """Periodically clean up expired records."""
        now = _utc_now()
        if (now - self._last_cleanup).total_seconds() < self._config.cleanup_interval_seconds:
            return

        with self._lock:
            with self._connect() as conn:
                if self._config.ttl_seconds is not None:
                    conn.execute(
                        "DELETE FROM memory_records WHERE expires_at IS NOT NULL AND expires_at < ?",
                        (_utc_now().isoformat(),),
                    )
                    conn.commit()
            self._last_cleanup = now

    def cleanup_expired(self) -> int:
        """Manually trigger cleanup of expired records. Returns count deleted."""
        with self._lock:
            with self._connect() as conn:
                if self._config.ttl_seconds is None:
                    return 0
                cursor = conn.execute(
                    "DELETE FROM memory_records WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (_utc_now().isoformat(),),
                )
                conn.commit()
                return cursor.rowcount

    def get_record(self, attempt_id: UUID) -> dict[str, Any] | None:
        """Retrieve a specific record by attempt_id."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT * FROM memory_records WHERE attempt_id = ?",
                    (_uuid_to_str(attempt_id),),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return dict(row)

    def list_records(
        self,
        *,
        workflow_run_id: UUID | None = None,
        task_run_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List records, optionally filtered by workflow or task run ID."""
        with self._lock:
            with self._connect() as conn:
                query = "SELECT * FROM memory_records WHERE 1=1"
                params: list[Any] = []
                if workflow_run_id is not None:
                    query += " AND workflow_run_id = ?"
                    params.append(_uuid_to_str(workflow_run_id))
                if task_run_id is not None:
                    query += " AND task_run_id = ?"
                    params.append(_uuid_to_str(task_run_id))
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor]

    def count_records(self) -> int:
        """Return total number of records."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute("SELECT COUNT(*) as cnt FROM memory_records")
                row = cursor.fetchone()
                return row["cnt"] if row else 0


__all__ = [
    "SQLiteMemoryAdapter",
    "SQLiteMemoryConfig",
]

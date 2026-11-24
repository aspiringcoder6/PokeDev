"""Task-attempt repository used by asynchronous Harness result delivery."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from langflow.adlc.harness_models import HarnessSessionResult, TaskAttemptRecord, TaskAttemptStatus
from langflow.adlc.models import TaskRequest, TaskResultStatus

ATTEMPT_IDEMPOTENCY_CONFLICT = "HARNESS_ATTEMPT_IDEMPOTENCY_CONFLICT"
ATTEMPT_NOT_FOUND = "HARNESS_ATTEMPT_NOT_FOUND"
ATTEMPT_STATE_CONFLICT = "HARNESS_ATTEMPT_STATE_CONFLICT"
RESULT_CONFLICT = "HARNESS_RESULT_CONFLICT"
RESULT_CORRELATION_MISMATCH = "HARNESS_RESULT_CORRELATION_MISMATCH"
RESULT_SESSION_MISMATCH = "HARNESS_RESULT_SESSION_MISMATCH"
SESSION_ID_CONFLICT = "HARNESS_SESSION_ID_CONFLICT"
SESSION_ID_INVALID = "HARNESS_SESSION_ID_INVALID"
DELIVERY_CONFLICT = "HARNESS_DELIVERY_CONFLICT"
HARNESS_ATTEMPT_DB_PATH_ENV = "ADLC_HARNESS_ATTEMPT_DB_PATH"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HarnessAttemptError(RuntimeError):
    """Stable failure raised by the external-attempt boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@runtime_checkable
class TaskAttemptRepository(Protocol):
    is_durable: bool

    async def create(self, request: TaskRequest) -> TaskAttemptRecord:
        """Create or replay an attempt for the exact idempotent request."""
        ...

    async def bind_session(self, attempt_id: UUID, session_id: str) -> TaskAttemptRecord:
        """Attach the immutable external Harness session identity."""
        ...

    async def update_status(self, attempt_id: UUID, status: TaskAttemptStatus) -> TaskAttemptRecord:
        """Advance an attempt through a valid non-terminal state."""
        ...

    async def accept_result(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        """Accept one immutable terminal result or replay the same result."""
        ...

    async def accept_delivery(
        self,
        delivery_id: UUID,
        result: HarnessSessionResult,
    ) -> tuple[TaskAttemptRecord, bool]:
        """Atomically deduplicate a delivery and accept its terminal result."""
        ...

    async def get(self, attempt_id: UUID) -> TaskAttemptRecord:
        """Read one attempt projection."""
        ...

    async def find_by_session(self, session_id: str) -> TaskAttemptRecord:
        """Read the attempt bound to one external session."""
        ...

    async def list_for_workflow_run(self, workflow_run_id: UUID) -> list[TaskAttemptRecord]:
        """List attempts for an authorized workflow-run projection."""
        ...

    async def list_unfinished(self, *, limit: int = 100) -> list[TaskAttemptRecord]:
        """List non-terminal attempts for bounded reconciliation."""
        ...


_TRANSITIONS: dict[TaskAttemptStatus, frozenset[TaskAttemptStatus]] = {
    TaskAttemptStatus.CREATED: frozenset(
        {
            TaskAttemptStatus.DISPATCHED,
            TaskAttemptStatus.RESULT_RECEIVED,
            TaskAttemptStatus.FAILED,
            TaskAttemptStatus.CANCELLED,
        }
    ),
    TaskAttemptStatus.DISPATCHED: frozenset(
        {
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.RESULT_RECEIVED,
            TaskAttemptStatus.FAILED,
            TaskAttemptStatus.CANCELLED,
        }
    ),
    TaskAttemptStatus.RUNNING: frozenset(
        {
            TaskAttemptStatus.WAITING_INTERACTION,
            TaskAttemptStatus.VERIFYING,
            TaskAttemptStatus.READY_TO_SUBMIT,
            TaskAttemptStatus.RESULT_RECEIVED,
            TaskAttemptStatus.FAILED,
            TaskAttemptStatus.CANCELLED,
        }
    ),
    TaskAttemptStatus.WAITING_INTERACTION: frozenset(
        {
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.RESULT_RECEIVED,
            TaskAttemptStatus.FAILED,
            TaskAttemptStatus.CANCELLED,
        }
    ),
    TaskAttemptStatus.VERIFYING: frozenset(
        {
            TaskAttemptStatus.READY_TO_SUBMIT,
            TaskAttemptStatus.RESULT_RECEIVED,
            TaskAttemptStatus.FAILED,
            TaskAttemptStatus.CANCELLED,
        }
    ),
    TaskAttemptStatus.READY_TO_SUBMIT: frozenset(
        {TaskAttemptStatus.RESULT_RECEIVED, TaskAttemptStatus.FAILED, TaskAttemptStatus.CANCELLED}
    ),
    TaskAttemptStatus.RESULT_RECEIVED: frozenset(
        {TaskAttemptStatus.SUCCEEDED, TaskAttemptStatus.FAILED, TaskAttemptStatus.CANCELLED}
    ),
    TaskAttemptStatus.SUCCEEDED: frozenset(),
    TaskAttemptStatus.FAILED: frozenset(),
    TaskAttemptStatus.CANCELLED: frozenset(),
}

_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {TaskAttemptStatus.SUCCEEDED, TaskAttemptStatus.FAILED, TaskAttemptStatus.CANCELLED}
)


def _result_digest(result: HarnessSessionResult) -> str:
    return hashlib.sha256(result.model_dump_json().encode()).hexdigest()


def _transition_attempt(record: TaskAttemptRecord, status: TaskAttemptStatus) -> TaskAttemptRecord:
    if record.status is status:
        return record
    if status not in _TRANSITIONS[record.status]:
        raise HarnessAttemptError(
            ATTEMPT_STATE_CONFLICT,
            f"Cannot transition a Harness attempt from {record.status.value} to {status.value}.",
        )
    return record.model_copy(update={"status": status, "updated_at": utc_now()}, deep=True)


def _accept_result_record(record: TaskAttemptRecord, result: HarnessSessionResult) -> TaskAttemptRecord:
    if (
        record.request_id != result.correlation.request_id
        or record.workflow_run_id != result.correlation.workflow_run_id
        or record.task_run_id != result.correlation.task_run_id
    ):
        raise HarnessAttemptError(
            RESULT_CORRELATION_MISMATCH,
            "The Harness result does not match the registered task attempt.",
        )
    if record.external_session_id is not None and record.external_session_id != result.session_id:
        raise HarnessAttemptError(
            RESULT_SESSION_MISMATCH,
            "The Harness result came from a different external session.",
        )
    if record.result is not None:
        if record.result != result:
            raise HarnessAttemptError(
                RESULT_CONFLICT,
                "A different terminal result was already accepted for this attempt.",
            )
        return record

    received = _transition_attempt(
        record.model_copy(
            update={"external_session_id": record.external_session_id or result.session_id},
            deep=True,
        ),
        TaskAttemptStatus.RESULT_RECEIVED,
    )
    terminal_status = {
        TaskResultStatus.SUCCEEDED: TaskAttemptStatus.SUCCEEDED,
        TaskResultStatus.FAILED: TaskAttemptStatus.FAILED,
        TaskResultStatus.CANCELLED: TaskAttemptStatus.CANCELLED,
    }[result.status]
    return _transition_attempt(received.model_copy(update={"result": result}, deep=True), terminal_status)


def validate_harness_result_for_attempt(record: TaskAttemptRecord, result: HarnessSessionResult) -> None:
    """Check correlation, immutable replay and lifecycle without mutating the ledger."""
    _accept_result_record(record, result)


class InMemoryTaskAttemptRepository:
    """Deterministic first-slice repository behind a durable-ready protocol."""

    is_durable = False

    def __init__(self) -> None:
        self._records: dict[UUID, TaskAttemptRecord] = {}
        self._deliveries: dict[UUID, tuple[UUID, str]] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: TaskRequest) -> TaskAttemptRecord:
        async with self._lock:
            existing = self._records.get(request.attempt_id)
            if existing is not None:
                if (
                    existing.request_id != request.request_id
                    or existing.workflow_run_id != request.workflow_run_id
                    or existing.task_run_id != request.task_run_id
                    or existing.idempotency_key != request.idempotency_key
                ):
                    raise HarnessAttemptError(
                        ATTEMPT_IDEMPOTENCY_CONFLICT,
                        "The attempt identity is already bound to a different request.",
                    )
                return existing.model_copy(deep=True)

            now = utc_now()
            record = TaskAttemptRecord(
                attempt_id=request.attempt_id,
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                idempotency_key=request.idempotency_key,
                status=TaskAttemptStatus.CREATED,
                created_at=now,
                updated_at=now,
            )
            self._records[record.attempt_id] = record
            return record.model_copy(deep=True)

    async def bind_session(self, attempt_id: UUID, session_id: str) -> TaskAttemptRecord:
        if not session_id.strip():
            raise HarnessAttemptError(SESSION_ID_INVALID, "The Harness session id cannot be empty.")
        async with self._lock:
            record = self._required(attempt_id)
            if record.external_session_id is not None and record.external_session_id != session_id:
                raise HarnessAttemptError(
                    SESSION_ID_CONFLICT,
                    "The attempt is already bound to a different Harness session.",
                )
            with_session = record.model_copy(update={"external_session_id": session_id})
            updated = (
                with_session
                if record.status in _TERMINAL_ATTEMPT_STATUSES
                else self._transition(with_session, TaskAttemptStatus.DISPATCHED)
            )
            self._records[attempt_id] = updated
            return updated.model_copy(deep=True)

    async def update_status(self, attempt_id: UUID, status: TaskAttemptStatus) -> TaskAttemptRecord:
        async with self._lock:
            record = self._required(attempt_id)
            updated = self._transition(record, status)
            self._records[attempt_id] = updated
            return updated.model_copy(deep=True)

    async def accept_result(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        async with self._lock:
            return self._accept_result_unlocked(result).model_copy(deep=True)

    async def accept_delivery(
        self,
        delivery_id: UUID,
        result: HarnessSessionResult,
    ) -> tuple[TaskAttemptRecord, bool]:
        async with self._lock:
            digest = _result_digest(result)
            previous = self._deliveries.get(delivery_id)
            if previous is not None:
                if previous != (result.correlation.attempt_id, digest):
                    raise HarnessAttemptError(
                        DELIVERY_CONFLICT,
                        "The delivery id is already associated with different result bytes.",
                    )
                return self._required(result.correlation.attempt_id).model_copy(deep=True), True
            accepted = self._accept_result_unlocked(result)
            self._deliveries[delivery_id] = (accepted.attempt_id, digest)
            return accepted.model_copy(deep=True), False

    async def get(self, attempt_id: UUID) -> TaskAttemptRecord:
        async with self._lock:
            return self._required(attempt_id).model_copy(deep=True)

    async def find_by_session(self, session_id: str) -> TaskAttemptRecord:
        async with self._lock:
            record = next((item for item in self._records.values() if item.external_session_id == session_id), None)
            if record is None:
                raise HarnessAttemptError(ATTEMPT_NOT_FOUND, "The Harness task attempt was not found.")
            return record.model_copy(deep=True)

    async def find_latest_by_task_run_id(self, task_run_id: UUID) -> TaskAttemptRecord | None:
        """Find the most recent attempt for a given task run.

        Used as a fallback when ``current_attempt_id`` on the task is
        stale or not yet set (e.g. the task just started and the
        activity panel is polled before the attempt is registered).
        """
        async with self._lock:
            matching = [
                record for record in self._records.values()
                if record.task_run_id == task_run_id
            ]
            if not matching:
                return None
            # Return the most recently created attempt.
            return max(matching, key=lambda r: r.created_at).model_copy(deep=True)

    async def list_for_workflow_run(self, workflow_run_id: UUID) -> list[TaskAttemptRecord]:
        async with self._lock:
            return [
                record.model_copy(deep=True)
                for record in sorted(self._records.values(), key=lambda item: item.created_at)
                if record.workflow_run_id == workflow_run_id
            ]

    async def list_unfinished(self, *, limit: int = 100) -> list[TaskAttemptRecord]:
        async with self._lock:
            records = [record for record in self._records.values() if record.status not in _TERMINAL_ATTEMPT_STATUSES]
            ordered = sorted(records, key=lambda item: item.created_at)[:limit]
            return [record.model_copy(deep=True) for record in ordered]

    def _required(self, attempt_id: UUID) -> TaskAttemptRecord:
        record = self._records.get(attempt_id)
        if record is None:
            raise HarnessAttemptError(ATTEMPT_NOT_FOUND, "The Harness task attempt was not found.")
        return record

    def _accept_result_unlocked(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        record = self._required(result.correlation.attempt_id)
        completed = _accept_result_record(record, result)
        self._records[record.attempt_id] = completed
        return completed

    @staticmethod
    def _transition(record: TaskAttemptRecord, status: TaskAttemptStatus) -> TaskAttemptRecord:
        return _transition_attempt(record, status)


class SqliteTaskAttemptRepository:
    """SQLite-backed attempt and delivery ledger used across process restarts."""

    is_durable = True

    def __init__(self, path: str | Path) -> None:
        raw_path = str(path).strip()
        if not raw_path or raw_path == ":memory:":
            msg = "A file-backed SQLite path is required for Harness attempt persistence."
            raise ValueError(msg)
        self.path = Path(raw_path).expanduser().resolve()
        self._lock = asyncio.Lock()
        self._initialized = False

    async def create(self, request: TaskRequest) -> TaskAttemptRecord:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._create_sync, request)

    async def bind_session(self, attempt_id: UUID, session_id: str) -> TaskAttemptRecord:
        if not session_id.strip():
            raise HarnessAttemptError(SESSION_ID_INVALID, "The Harness session id cannot be empty.")
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._bind_session_sync, attempt_id, session_id)

    async def update_status(self, attempt_id: UUID, status: TaskAttemptStatus) -> TaskAttemptRecord:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._update_status_sync, attempt_id, status)

    async def accept_result(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._accept_result_sync, result)

    async def accept_delivery(
        self,
        delivery_id: UUID,
        result: HarnessSessionResult,
    ) -> tuple[TaskAttemptRecord, bool]:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._accept_delivery_sync, delivery_id, result)

    async def get(self, attempt_id: UUID) -> TaskAttemptRecord:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._get_sync, attempt_id)

    async def find_by_session(self, session_id: str) -> TaskAttemptRecord:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._find_by_session_sync, session_id)

    async def find_latest_by_task_run_id(self, task_run_id: UUID) -> TaskAttemptRecord | None:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._find_latest_by_task_run_id_sync, task_run_id)

    async def list_for_workflow_run(self, workflow_run_id: UUID) -> list[TaskAttemptRecord]:
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._list_for_workflow_run_sync, workflow_run_id)

    async def list_unfinished(self, *, limit: int = 100) -> list[TaskAttemptRecord]:
        if limit <= 0:
            return []
        async with self._lock:
            await self._initialize()
            return await asyncio.to_thread(self._list_unfinished_sync, limit)

    async def _initialize(self) -> None:
        if self._initialized:
            return
        await asyncio.to_thread(self._initialize_sync)
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS harness_task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    workflow_run_id TEXT NOT NULL,
                    task_run_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    external_session_id TEXT UNIQUE,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_harness_attempt_workflow
                    ON harness_task_attempts(workflow_run_id, created_at);
                CREATE INDEX IF NOT EXISTS ix_harness_attempt_status
                    ON harness_task_attempts(status, updated_at);
                CREATE TABLE IF NOT EXISTS harness_result_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    result_digest TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    FOREIGN KEY(attempt_id) REFERENCES harness_task_attempts(attempt_id)
                );
                """
            )

    def _create_sync(self, request: TaskRequest) -> TaskAttemptRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM harness_task_attempts WHERE attempt_id = ? OR idempotency_key = ?",
                (str(request.attempt_id), request.idempotency_key),
            ).fetchone()
            if row is not None:
                record = self._record(row)
                if not self._matches_request(record, request):
                    connection.rollback()
                    raise HarnessAttemptError(
                        ATTEMPT_IDEMPOTENCY_CONFLICT,
                        "The attempt identity or idempotency key is already bound to a different request.",
                    )
                connection.commit()
                return record
            now = utc_now()
            record = TaskAttemptRecord(
                attempt_id=request.attempt_id,
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                idempotency_key=request.idempotency_key,
                status=TaskAttemptStatus.CREATED,
                created_at=now,
                updated_at=now,
            )
            connection.execute(
                """INSERT INTO harness_task_attempts (
                    attempt_id, request_id, workflow_run_id, task_run_id, idempotency_key,
                    status, external_session_id, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                (
                    str(record.attempt_id),
                    str(record.request_id),
                    str(record.workflow_run_id),
                    str(record.task_run_id),
                    record.idempotency_key,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            connection.commit()
            return record

    def _bind_session_sync(self, attempt_id: UUID, session_id: str) -> TaskAttemptRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self._required_row(connection, attempt_id)
            if record.external_session_id is not None and record.external_session_id != session_id:
                connection.rollback()
                raise HarnessAttemptError(
                    SESSION_ID_CONFLICT,
                    "The attempt is already bound to a different Harness session.",
                )
            updated = record.model_copy(
                update={"external_session_id": session_id, "updated_at": utc_now()},
                deep=True,
            )
            if record.status not in _TERMINAL_ATTEMPT_STATUSES:
                updated = _transition_attempt(updated, TaskAttemptStatus.DISPATCHED)
            self._write_record(connection, updated)
            connection.commit()
            return updated

    def _update_status_sync(self, attempt_id: UUID, status: TaskAttemptStatus) -> TaskAttemptRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = _transition_attempt(self._required_row(connection, attempt_id), status)
            self._write_record(connection, updated)
            connection.commit()
            return updated

    def _accept_result_sync(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            accepted = _accept_result_record(
                self._required_row(connection, result.correlation.attempt_id),
                result,
            )
            self._write_record(connection, accepted)
            connection.commit()
            return accepted

    def _accept_delivery_sync(
        self,
        delivery_id: UUID,
        result: HarnessSessionResult,
    ) -> tuple[TaskAttemptRecord, bool]:
        digest = _result_digest(result)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT attempt_id, result_digest FROM harness_result_deliveries WHERE delivery_id = ?",
                (str(delivery_id),),
            ).fetchone()
            if previous is not None:
                if previous["attempt_id"] != str(result.correlation.attempt_id) or previous["result_digest"] != digest:
                    connection.rollback()
                    raise HarnessAttemptError(
                        DELIVERY_CONFLICT,
                        "The delivery id is already associated with different result bytes.",
                    )
                record = self._required_row(connection, result.correlation.attempt_id)
                connection.commit()
                return record, True
            accepted = _accept_result_record(
                self._required_row(connection, result.correlation.attempt_id),
                result,
            )
            self._write_record(connection, accepted)
            connection.execute(
                """INSERT INTO harness_result_deliveries
                (delivery_id, attempt_id, result_digest, accepted_at) VALUES (?, ?, ?, ?)""",
                (str(delivery_id), str(accepted.attempt_id), digest, utc_now().isoformat()),
            )
            connection.commit()
            return accepted, False

    def _get_sync(self, attempt_id: UUID) -> TaskAttemptRecord:
        with self._connect() as connection:
            return self._required_row(connection, attempt_id)

    def _find_by_session_sync(self, session_id: str) -> TaskAttemptRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_task_attempts WHERE external_session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                raise HarnessAttemptError(ATTEMPT_NOT_FOUND, "The Harness task attempt was not found.")
            return self._record(row)

    def _find_latest_by_task_run_id_sync(self, task_run_id: UUID) -> TaskAttemptRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_task_attempts WHERE task_run_id = ? "
                "ORDER BY created_at DESC, attempt_id DESC LIMIT 1",
                (str(task_run_id),),
            ).fetchone()
            if row is None:
                return None
            return self._record(row)

    def _list_for_workflow_run_sync(self, workflow_run_id: UUID) -> list[TaskAttemptRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM harness_task_attempts WHERE workflow_run_id = ? ORDER BY created_at, attempt_id",
                (str(workflow_run_id),),
            ).fetchall()
            return [self._record(row) for row in rows]

    def _list_unfinished_sync(self, limit: int) -> list[TaskAttemptRecord]:
        terminal = tuple(status.value for status in _TERMINAL_ATTEMPT_STATUSES)
        placeholders = ", ".join("?" for _ in terminal)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM harness_task_attempts WHERE status NOT IN ({placeholders}) "  # noqa: S608
                "ORDER BY updated_at, attempt_id LIMIT ?",
                (*terminal, limit),
            ).fetchall()
            return [self._record(row) for row in rows]

    @staticmethod
    def _matches_request(record: TaskAttemptRecord, request: TaskRequest) -> bool:
        return (
            record.attempt_id == request.attempt_id
            and record.request_id == request.request_id
            and record.workflow_run_id == request.workflow_run_id
            and record.task_run_id == request.task_run_id
            and record.idempotency_key == request.idempotency_key
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> TaskAttemptRecord:
        result = HarnessSessionResult.model_validate_json(row["result_json"]) if row["result_json"] else None
        return TaskAttemptRecord(
            attempt_id=UUID(row["attempt_id"]),
            request_id=UUID(row["request_id"]),
            workflow_run_id=UUID(row["workflow_run_id"]),
            task_run_id=UUID(row["task_run_id"]),
            idempotency_key=row["idempotency_key"],
            status=TaskAttemptStatus(row["status"]),
            external_session_id=row["external_session_id"],
            result=result,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @classmethod
    def _required_row(cls, connection: sqlite3.Connection, attempt_id: UUID) -> TaskAttemptRecord:
        row = connection.execute(
            "SELECT * FROM harness_task_attempts WHERE attempt_id = ?",
            (str(attempt_id),),
        ).fetchone()
        if row is None:
            raise HarnessAttemptError(ATTEMPT_NOT_FOUND, "The Harness task attempt was not found.")
        return cls._record(row)

    @staticmethod
    def _write_record(connection: sqlite3.Connection, record: TaskAttemptRecord) -> None:
        connection.execute(
            """UPDATE harness_task_attempts
            SET status = ?, external_session_id = ?, result_json = ?, updated_at = ?
            WHERE attempt_id = ?""",
            (
                record.status.value,
                record.external_session_id,
                record.result.model_dump_json() if record.result is not None else None,
                record.updated_at.isoformat(),
                str(record.attempt_id),
            ),
        )


def create_task_attempt_repository_from_environment() -> TaskAttemptRepository:
    configured = os.getenv(HARNESS_ATTEMPT_DB_PATH_ENV)
    if configured is not None and not configured.strip():
        return InMemoryTaskAttemptRepository()
    default_path = Path(__file__).resolve().parents[2] / "data" / "adlc-harness-attempts.sqlite3"
    return SqliteTaskAttemptRepository(configured.strip() if configured is not None else default_path)


__all__ = [
    "HARNESS_ATTEMPT_DB_PATH_ENV",
    "HarnessAttemptError",
    "InMemoryTaskAttemptRepository",
    "SqliteTaskAttemptRepository",
    "TaskAttemptRepository",
    "create_task_attempt_repository_from_environment",
]

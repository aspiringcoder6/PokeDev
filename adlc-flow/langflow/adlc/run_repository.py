"""Atomic run snapshots behind a replaceable, single-coordinator repository port."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from langflow.adlc.models import AdlcTaskDefinition, WorkflowRun

RUN_DB_PATH_ENV = "ADLC_RUN_DB_PATH"
REVISION_CONFLICT = "ADLC_RUN_REVISION_CONFLICT"
RECORD_INVALID = "ADLC_RUN_RECORD_INVALID"
STORE_UNAVAILABLE = "ADLC_RUN_STORE_UNAVAILABLE"


class RunRepositoryError(RuntimeError):
    """Fail closed on an unavailable store or stale coordinator snapshot."""


class StoredAdlcRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_id: str
    run: WorkflowRun
    definitions: dict[str, AdlcTaskDefinition]
    delay_ms: int
    revision: int = Field(default=0, ge=0)


class RunRepository(Protocol):
    is_durable: bool

    def load_all(self) -> list[StoredAdlcRun]: ...

    def save(self, record: StoredAdlcRun) -> None: ...


class InMemoryRunRepository:
    is_durable = False

    def __init__(self) -> None:
        self._records: dict[str, StoredAdlcRun] = {}

    def load_all(self) -> list[StoredAdlcRun]:
        return [record.model_copy(deep=True) for record in self._records.values()]

    def save(self, record: StoredAdlcRun) -> None:
        key = str(record.run.id)
        existing = self._records.get(key)
        if (existing is None and record.revision != 0) or (
            existing is not None and (existing.revision != record.revision or existing.owner_id != record.owner_id)
        ):
            raise RunRepositoryError(REVISION_CONFLICT)
        record.revision += 1
        self._records[key] = record.model_copy(deep=True)


class SqliteRunRepository:
    """Persist ownership, definitions, tasks, approvals, and ordered events together."""

    is_durable = True

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS adlc_workflow_runs (
                run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL, record_json TEXT NOT NULL
            )""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS adlc_runs_owner_created ON adlc_workflow_runs(owner_id, created_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise RunRepositoryError(STORE_UNAVAILABLE) from exc
        else:
            return connection

    def load_all(self) -> list[StoredAdlcRun]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM adlc_workflow_runs ORDER BY created_at, run_id").fetchall()
        records = []
        for row in rows:
            try:
                record = StoredAdlcRun.model_validate_json(row["record_json"])
            except ValidationError:
                # Validation errors can embed persisted user inputs/results.
                raise RunRepositoryError(RECORD_INVALID) from None
            if (
                str(record.run.id) != row["run_id"]
                or record.owner_id != row["owner_id"]
                or record.revision != row["revision"]
            ):
                raise RunRepositoryError(RECORD_INVALID)
            records.append(record)
        return records

    def save(self, record: StoredAdlcRun) -> None:
        expected = record.revision
        updated = record.model_copy(update={"revision": expected + 1})
        updated_at = record.run.events[-1].occurred_at if record.run.events else record.run.created_at
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if expected == 0:
                    connection.execute(
                        """INSERT INTO adlc_workflow_runs
                        (run_id, owner_id, created_at, updated_at, revision, record_json) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            str(record.run.id),
                            record.owner_id,
                            record.run.created_at.isoformat(),
                            updated_at.isoformat(),
                            1,
                            updated.model_dump_json(),
                        ),
                    )
                else:
                    cursor = connection.execute(
                        """UPDATE adlc_workflow_runs SET updated_at=?, revision=?, record_json=?
                        WHERE run_id=? AND owner_id=? AND revision=?""",
                        (
                            updated_at.isoformat(),
                            expected + 1,
                            updated.model_dump_json(),
                            str(record.run.id),
                            record.owner_id,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise RunRepositoryError(REVISION_CONFLICT)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise RunRepositoryError(REVISION_CONFLICT) from exc
            except sqlite3.Error as exc:
                connection.rollback()
                raise RunRepositoryError(STORE_UNAVAILABLE) from exc
            except Exception:
                connection.rollback()
                raise
        record.revision = expected + 1


def create_run_repository_from_environment() -> RunRepository:
    configured = os.getenv(RUN_DB_PATH_ENV)
    if configured is not None and not configured.strip():
        return InMemoryRunRepository()
    default_path = Path(__file__).resolve().parents[2] / "data" / "adlc-runs.sqlite3"
    return SqliteRunRepository(configured.strip() if configured is not None else default_path)

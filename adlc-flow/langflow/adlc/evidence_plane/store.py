"""Evidence Plane storage backends.

Defines the EvidenceStore Protocol and two implementations:
- InMemoryEvidenceStore: thread-safe, for tests and ephemeral use
- SQLEvidenceStore: durable, for production (SQLite-backed)

Both implementations honor retention policies and validation status.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

from langflow.adlc.evidence_plane.models import (
    Evidence,
    EvidenceQuery,
    EvidenceReceipt,
    EvidenceType,
    RetentionPolicy,
    ValidationStatus,
    default_retention_for,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@runtime_checkable
class EvidenceStore(Protocol):
    """Storage port for the Evidence Plane.

    Implementations must be thread-safe and honor retention policies.
    """

    def submit(self, evidence: Evidence) -> EvidenceReceipt:
        """Store an evidence item and return a receipt."""
        ...

    def query(self, query: EvidenceQuery) -> list[Evidence]:
        """Return evidence matching the query, ordered by submitted_at."""
        ...

    def get(self, evidence_id: str) -> Evidence | None:
        """Return one evidence item by ID, or None if absent/expired."""
        ...

    def mark_validated(
        self,
        evidence_id: str,
        status: ValidationStatus,
        errors: tuple[str, ...] = (),
    ) -> None:
        """Update the validation status of an evidence item."""
        ...

    def count(self, workflow_run_id: str | None = None) -> int:
        """Return the number of evidence items, optionally filtered by run."""
        ...


class InMemoryEvidenceStore:
    """Thread-safe in-memory evidence store for tests and ephemeral use."""

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._lock = RLock()

    def submit(self, evidence: Evidence) -> EvidenceReceipt:
        with self._lock:
            # Apply default retention if expires_at is unset.
            if evidence.expires_at is None:
                retention = default_retention_for(evidence.retention_policy)
                if retention is not None:
                    evidence = evidence.model_copy(
                        update={"expires_at": evidence.submitted_at + retention}
                    )
            self._items[str(evidence.evidence_id)] = evidence
            return EvidenceReceipt(
                evidence_id=evidence.evidence_id,
                accepted=True,
                validation_status=evidence.validation_status,
                validation_errors=evidence.validation_errors,
                stored_at=_utc_now(),
            )

    def query(self, query: EvidenceQuery) -> list[Evidence]:
        with self._lock:
            now = _utc_now()
            results: list[Evidence] = []
            for item in self._items.values():
                if not self._matches(item, query, now):
                    continue
                results.append(item)
            results.sort(key=lambda e: e.submitted_at)
            return results[: query.limit]

    def get(self, evidence_id: str) -> Evidence | None:
        with self._lock:
            item = self._items.get(evidence_id)
            if item is None:
                return None
            if item.expires_at is not None and item.expires_at <= _utc_now():
                return None
            return item

    def mark_validated(
        self,
        evidence_id: str,
        status: ValidationStatus,
        errors: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            item = self._items.get(evidence_id)
            if item is None:
                msg = f"Evidence {evidence_id} not found"
                raise KeyError(msg)
            self._items[evidence_id] = item.model_copy(
                update={"validation_status": status, "validation_errors": errors}
            )

    def count(self, workflow_run_id: str | None = None) -> int:
        with self._lock:
            if workflow_run_id is None:
                return len(self._items)
            return sum(
                1
                for item in self._items.values()
                if item.workflow_run_id is not None
                and str(item.workflow_run_id) == workflow_run_id
            )

    @staticmethod
    def _matches(item: Evidence, query: EvidenceQuery, now: datetime) -> bool:
        if query.workflow_run_id is not None and item.workflow_run_id != query.workflow_run_id:
            return False
        if query.task_run_id is not None and item.task_run_id != query.task_run_id:
            return False
        if query.attempt_id is not None and item.attempt_id != query.attempt_id:
            return False
        if query.evidence_types and item.evidence_type not in query.evidence_types:
            return False
        if query.validation_statuses and item.validation_status not in query.validation_statuses:
            return False
        if query.producers and item.producer not in query.producers:
            return False
        if query.submitted_after is not None and item.submitted_at < query.submitted_after:
            return False
        if query.submitted_before is not None and item.submitted_at > query.submitted_before:
            return False
        if not query.include_expired and item.expires_at is not None and item.expires_at <= now:
            return False
        return True


class SQLEvidenceStore:
    """SQLite-backed durable evidence store.

    Schema is intentionally simple: one table with indexed columns for
    the common query patterns. Suitable for single-process deployments;
    for multi-process, swap with a PostgreSQL-backed implementation.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS adlc_evidence (
        evidence_id TEXT PRIMARY KEY,
        evidence_type TEXT NOT NULL,
        validation_status TEXT NOT NULL,
        validation_errors TEXT NOT NULL DEFAULT '[]',
        retention_policy TEXT NOT NULL,
        producer TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        expires_at TEXT,
        payload TEXT NOT NULL DEFAULT '{}',
        workflow_run_id TEXT,
        task_run_id TEXT,
        attempt_id TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_adlc_evidence_run
        ON adlc_evidence(workflow_run_id);
    CREATE INDEX IF NOT EXISTS idx_adlc_evidence_task
        ON adlc_evidence(task_run_id);
    CREATE INDEX IF NOT EXISTS idx_adlc_evidence_type
        ON adlc_evidence(evidence_type);
    CREATE INDEX IF NOT EXISTS idx_adlc_evidence_status
        ON adlc_evidence(validation_status);
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with closing(sqlite3.connect(self._database_path)) as conn:
            conn.executescript(self._SCHEMA)
            conn.commit()

    def submit(self, evidence: Evidence) -> EvidenceReceipt:
        with self._lock:
            if evidence.expires_at is None:
                retention = default_retention_for(evidence.retention_policy)
                if retention is not None:
                    evidence = evidence.model_copy(
                        update={"expires_at": evidence.submitted_at + retention}
                    )
            import json

            with closing(sqlite3.connect(self._database_path)) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO adlc_evidence (
                        evidence_id, evidence_type, validation_status,
                        validation_errors, retention_policy, producer,
                        submitted_at, expires_at, payload,
                        workflow_run_id, task_run_id, attempt_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(evidence.evidence_id),
                        evidence.evidence_type.value,
                        evidence.validation_status.value,
                        json.dumps(list(evidence.validation_errors)),
                        evidence.retention_policy.value,
                        evidence.producer,
                        evidence.submitted_at.isoformat(),
                        evidence.expires_at.isoformat() if evidence.expires_at else None,
                        json.dumps(evidence.payload),
                        str(evidence.workflow_run_id) if evidence.workflow_run_id else None,
                        str(evidence.task_run_id) if evidence.task_run_id else None,
                        str(evidence.attempt_id) if evidence.attempt_id else None,
                    ),
                )
                conn.commit()
            return EvidenceReceipt(
                evidence_id=evidence.evidence_id,
                accepted=True,
                validation_status=evidence.validation_status,
                validation_errors=evidence.validation_errors,
                stored_at=_utc_now(),
            )

    def query(self, query: EvidenceQuery) -> list[Evidence]:
        import json

        clauses: list[str] = []
        params: list[object] = []
        if query.workflow_run_id is not None:
            clauses.append("workflow_run_id = ?")
            params.append(str(query.workflow_run_id))
        if query.task_run_id is not None:
            clauses.append("task_run_id = ?")
            params.append(str(query.task_run_id))
        if query.attempt_id is not None:
            clauses.append("attempt_id = ?")
            params.append(str(query.attempt_id))
        if query.evidence_types:
            placeholders = ",".join("?" for _ in query.evidence_types)
            clauses.append(f"evidence_type IN ({placeholders})")
            params.extend(t.value for t in query.evidence_types)
        if query.validation_statuses:
            placeholders = ",".join("?" for _ in query.validation_statuses)
            clauses.append(f"validation_status IN ({placeholders})")
            params.extend(s.value for s in query.validation_statuses)
        if query.producers:
            placeholders = ",".join("?" for _ in query.producers)
            clauses.append(f"producer IN ({placeholders})")
            params.extend(query.producers)
        if query.submitted_after is not None:
            clauses.append("submitted_at >= ?")
            params.append(query.submitted_after.isoformat())
        if query.submitted_before is not None:
            clauses.append("submitted_at <= ?")
            params.append(query.submitted_before.isoformat())
        if not query.include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(_utc_now().isoformat())

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT evidence_id, evidence_type, validation_status, "
            f"validation_errors, retention_policy, producer, submitted_at, "
            f"expires_at, payload, workflow_run_id, task_run_id, attempt_id "
            f"FROM adlc_evidence {where} ORDER BY submitted_at LIMIT ?"
        )
        params.append(query.limit)

        with self._lock, closing(sqlite3.connect(self._database_path)) as conn:
            rows = conn.execute(sql, params).fetchall()

        results: list[Evidence] = []
        for row in rows:
            results.append(
                Evidence(
                    evidence_id=row[0],
                    evidence_type=EvidenceType(row[1]),
                    validation_status=ValidationStatus(row[2]),
                    validation_errors=tuple(json.loads(row[3])),
                    retention_policy=RetentionPolicy(row[4]),
                    producer=row[5],
                    submitted_at=datetime.fromisoformat(row[6]),
                    expires_at=datetime.fromisoformat(row[7]) if row[7] else None,
                    payload=json.loads(row[8]),
                    workflow_run_id=__import__("uuid").UUID(row[9]) if row[9] else None,
                    task_run_id=__import__("uuid").UUID(row[10]) if row[10] else None,
                    attempt_id=__import__("uuid").UUID(row[11]) if row[11] else None,
                )
            )
        return results

    def get(self, evidence_id: str) -> Evidence | None:
        results = self.query(
            EvidenceQuery(limit=1)  # type: ignore[arg-type]
        )
        # Direct lookup is more efficient; use a dedicated query.
        import json

        with self._lock, closing(sqlite3.connect(self._database_path)) as conn:
            row = conn.execute(
                "SELECT evidence_id, evidence_type, validation_status, "
                "validation_errors, retention_policy, producer, submitted_at, "
                "expires_at, payload, workflow_run_id, task_run_id, attempt_id "
                "FROM adlc_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        if row[7] is not None:
            expires_at = datetime.fromisoformat(row[7])
            if expires_at <= _utc_now():
                return None
        return Evidence(
            evidence_id=row[0],
            evidence_type=EvidenceType(row[1]),
            validation_status=ValidationStatus(row[2]),
            validation_errors=tuple(json.loads(row[3])),
            retention_policy=RetentionPolicy(row[4]),
            producer=row[5],
            submitted_at=datetime.fromisoformat(row[6]),
            expires_at=datetime.fromisoformat(row[7]) if row[7] else None,
            payload=json.loads(row[8]),
            workflow_run_id=__import__("uuid").UUID(row[9]) if row[9] else None,
            task_run_id=__import__("uuid").UUID(row[10]) if row[10] else None,
            attempt_id=__import__("uuid").UUID(row[11]) if row[11] else None,
        )

    def mark_validated(
        self,
        evidence_id: str,
        status: ValidationStatus,
        errors: tuple[str, ...] = (),
    ) -> None:
        import json

        with self._lock, closing(sqlite3.connect(self._database_path)) as conn:
            cursor = conn.execute(
                "UPDATE adlc_evidence SET validation_status = ?, validation_errors = ? "
                "WHERE evidence_id = ?",
                (status.value, json.dumps(list(errors)), evidence_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                msg = f"Evidence {evidence_id} not found"
                raise KeyError(msg)

    def count(self, workflow_run_id: str | None = None) -> int:
        with self._lock, closing(sqlite3.connect(self._database_path)) as conn:
            if workflow_run_id is None:
                row = conn.execute("SELECT COUNT(*) FROM adlc_evidence").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM adlc_evidence WHERE workflow_run_id = ?",
                    (workflow_run_id,),
                ).fetchone()
        return int(row[0]) if row else 0


__all__ = [
    "EvidenceStore",
    "InMemoryEvidenceStore",
    "SQLEvidenceStore",
]

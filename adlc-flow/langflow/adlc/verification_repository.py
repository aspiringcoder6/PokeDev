"""Bounded, durable H6A approval, dispatch intent and retained evidence.

No background execution is initiated by opening or restoring this repository.
"""

# ruff: noqa: EM101 - exceptions expose fixed codes only.

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from langflow.adlc.verification_models import (
    MAX_EVIDENCE_BYTES,
    VerificationError,
    VerificationRead,
    canonical,
    compare,
    digest,
)

# Generated from the separately pinned protected runner; filled by H6A lock check.
RUNNER_DIGEST = "sha256:c2afb80f9585dd021ed819fdb5d115f8d602f2c63d50e587365dbc43d3b9966f"


def now():
    return datetime.now(timezone.utc)


class VerificationRepository:
    table_name = "adlc_verifications"
    record_type = VerificationRead
    runner_digest = RUNNER_DIGEST
    comparator = staticmethod(compare)
    active_states = frozenset({"RUNNING", "DISPATCH_UNCERTAIN"})
    evidence_limit = MAX_EVIDENCE_BYTES

    def query(self, sql, args=()):
        # Internal profiles only; callers cannot select tables or inject SQL.
        if self.table_name not in {"adlc_verifications", "adlc_verification_replays"}:
            raise VerificationError("VERIFICATION_STORE_INVALID", 503)
        return self.db.execute(sql.replace("adlc_verifications", self.table_name), args)

    def __init__(self, path=None, *, max_records=200, max_bytes=32 * 1024 * 1024):
        self.lock = RLock()
        self.max_records, self.max_bytes = max_records, max_bytes
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path is not None else ":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.query("""CREATE TABLE IF NOT EXISTS adlc_verifications (
            plan_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
            command_key TEXT NOT NULL, command_digest TEXT NOT NULL,
            record_json TEXT NOT NULL, candidate TEXT NOT NULL, content_digest TEXT NOT NULL,
            UNIQUE(owner_id, run_id, command_key))""")
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.query("BEGIN IMMEDIATE")
                yield
                self.db.commit()
            except sqlite3.Error:
                self.db.rollback()
                raise VerificationError("VERIFICATION_STORE_UNAVAILABLE", 503) from None
            except Exception:
                self.db.rollback()
                raise

    @staticmethod
    def _checksum(record, candidate):
        return hashlib.sha256((record + "\0" + candidate).encode()).hexdigest()

    def _read(self, row):
        if row is None:
            raise VerificationError("VERIFICATION_NOT_FOUND", 404)
        try:
            record = self.record_type.model_validate_json(row["record_json"])
            if (
                self._checksum(row["record_json"], row["candidate"]) != row["content_digest"]
                or record.plan_digest != digest(record.plan)
                or str(record.plan.plan_id) != row["plan_id"]
                or str(record.plan.workflow_run_id) != row["run_id"]
                or "sha256:" + hashlib.sha256(row["candidate"].encode()).hexdigest()
                != record.plan.candidate.content_digest
            ):
                raise ValueError
            if record.state != "DRAFT" and (not record.approved_by or not record.approved_at):
                raise ValueError
            if record.receipt:
                if record.receipt.execution_id != record.execution_id or record.report != self.comparator(
                    record.plan, record.receipt, self.runner_digest
                ):
                    raise ValueError
                evidence = {
                    "plan": record.plan.model_dump(mode="json"),
                    "receipt": record.receipt.model_dump(mode="json"),
                    "report": record.report.model_dump(mode="json"),
                }
                if record.evidence_digest != digest(evidence):
                    raise ValueError
            if (record.state in {"READY_FOR_SUBMISSION", "SUBMITTED"}) != (record.report is not None):
                raise ValueError
        except (ValidationError, ValueError, TypeError):
            raise VerificationError("VERIFICATION_STORE_INVALID", 503) from None
        return record

    def _row(self, plan_id, owner, run_id):
        return self.query(
            "SELECT * FROM adlc_verifications WHERE plan_id=? AND owner_id=? AND run_id=?",
            (str(plan_id), owner, str(run_id)),
        ).fetchone()

    def _save(self, record, candidate):
        body = record.model_dump_json()
        total = self.query(
            "SELECT COALESCE(SUM(length(CAST(record_json AS BLOB))+"
            "length(CAST(candidate AS BLOB))),0) FROM adlc_verifications"
        ).fetchone()[0]
        prior = self.query(
            "SELECT length(CAST(record_json AS BLOB)) FROM adlc_verifications WHERE plan_id=?",
            (str(record.plan.plan_id),),
        ).fetchone()
        if total + len(body.encode()) - (prior[0] if prior else 0) > self.max_bytes:
            raise VerificationError("VERIFICATION_STORE_FULL", 413)
        self.query(
            "UPDATE adlc_verifications SET record_json=?, content_digest=? WHERE plan_id=?",
            (body, self._checksum(body, candidate), str(record.plan.plan_id)),
        )

    def create(self, plan, content, *, owner, command_key, command_digest):
        with self.transaction():
            row = self.query(
                "SELECT * FROM adlc_verifications WHERE owner_id=? AND run_id=? AND command_key=?",
                (owner, str(plan.workflow_run_id), command_key),
            ).fetchone()
            if row:
                if row["command_digest"] != command_digest:
                    raise VerificationError("VERIFICATION_IDEMPOTENCY_CONFLICT")
                return self._read(row)
            if self.query("SELECT count(*) FROM adlc_verifications").fetchone()[0] >= self.max_records:
                raise VerificationError("VERIFICATION_STORE_FULL", 413)
            record = self.record_type(plan=plan, plan_digest=digest(plan), state="DRAFT", created_at=now())
            body = record.model_dump_json()
            self.query(
                "INSERT INTO adlc_verifications VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(plan.plan_id),
                    owner,
                    str(plan.workflow_run_id),
                    command_key,
                    command_digest,
                    body,
                    content,
                    self._checksum(body, content),
                ),
            )
            self._save(record, content)
            return record

    def get(self, plan_id, *, owner, run_id):
        with self.lock:
            return self._read(self._row(plan_id, owner, run_id))

    def list(self, *, owner, run_id, limit=100, offset=0, attempt_id=None, session_id=None):
        with self.lock:
            # Store-wide bounded archive (200 by default); filter before pagination.
            rows = self.query(
                "SELECT * FROM adlc_verifications WHERE owner_id=? AND run_id=? ORDER BY rowid DESC",
                (owner, str(run_id)),
            ).fetchall()
            records = [self._read(row) for row in rows]
            if attempt_id is not None or session_id is not None:
                records = [
                    r
                    for r in records
                    if r.plan.candidate.source_attempt_id == attempt_id
                    and r.plan.candidate.source_session_id == session_id
                ]
            return records[max(0, offset) : max(0, offset) + min(100, max(1, limit))]

    def action(self, plan_id, *, owner, run_id, plan_digest, operation):
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.plan_digest != plan_digest:
                raise VerificationError("VERIFICATION_REFERENCE_CONFLICT")
            if operation == "approve":
                if record.state == "DRAFT":
                    record.state, record.approved_by, record.approved_at = "APPROVED", owner, now()
            elif operation == "execute":
                if record.state == "APPROVED":
                    record.state, record.execution_id = "RUNNING", uuid4()
                else:
                    # Once intent is recorded, only observation is allowed. Even a
                    # repeated client POST cannot recreate a lost external job.
                    raise VerificationError("VERIFICATION_EXECUTION_NOT_ALLOWED")
            elif operation == "submit":
                if record.state == "READY_FOR_SUBMISSION":
                    record.state, record.submitted_at = "SUBMITTED", now()
                elif record.state != "SUBMITTED":
                    raise VerificationError("VERIFICATION_REPORT_NOT_READY")
            else:
                raise VerificationError("VERIFICATION_OPERATION_INVALID", 422)
            self._save(record, row["candidate"])
            return record, row["candidate"]

    def payload(self, plan_id, *, owner, run_id):
        with self.lock:
            row = self._row(plan_id, owner, run_id)
            return self._read(row), row["candidate"]

    def accept(self, plan_id, receipt, *, owner, run_id):
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.receipt is not None:
                if record.receipt != receipt:
                    raise VerificationError("VERIFICATION_RECEIPT_CONFLICT")
                return record
            if record.state not in self.active_states or record.execution_id != receipt.execution_id:
                raise VerificationError("VERIFICATION_EXECUTION_MISMATCH")
            report = self.comparator(record.plan, receipt, self.runner_digest)
            evidence = {
                "plan": record.plan.model_dump(mode="json"),
                "receipt": receipt.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            }
            if len(canonical(evidence)) > self.evidence_limit:
                raise VerificationError("VERIFICATION_EVIDENCE_TOO_LARGE", 413)
            record.receipt, record.report, record.state, record.error_code = (
                receipt,
                report,
                "READY_FOR_SUBMISSION",
                None,
            )
            record.evidence_digest = digest(evidence)
            self._save(record, row["candidate"])
            return record

    def diagnostic(self, plan_id, *, owner, run_id, code, uncertain=False):
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.state in self.active_states:
                record.state = "DISPATCH_UNCERTAIN" if uncertain else "NOT_VERIFIED"
                record.error_code = code
                self._save(record, row["candidate"])
            return record


@lru_cache(maxsize=1)
def get_verification_repository():
    configured = os.getenv("ADLC_VERIFICATION_DB_PATH")
    path = (
        (Path(__file__).resolve().parents[2] / "data" / "adlc-verifications.sqlite3")
        if configured is None
        else (configured.strip() or None)
    )
    return VerificationRepository(path)

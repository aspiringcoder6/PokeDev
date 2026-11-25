from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from uuid import uuid4

from .models import ReadinessRun, canonical_digest


class ReadinessStore:
    def __init__(self, path):
        self.path = str(path)
        self.fence = ContextVar("readiness_worker_lease", default=None)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS readiness_runs (
              id TEXT PRIMARY KEY, principal_id TEXT NOT NULL, project_id TEXT NOT NULL,
              request_id TEXT NOT NULL, input_digest TEXT NOT NULL, revision INTEGER NOT NULL,
              payload TEXT NOT NULL, UNIQUE(principal_id,project_id,request_id));
            CREATE TABLE IF NOT EXISTS readiness_operations (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, role TEXT NOT NULL,
              session_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, payload TEXT);
            CREATE TABLE IF NOT EXISTS readiness_commands (
              run_id TEXT NOT NULL, command_id TEXT NOT NULL, digest TEXT NOT NULL,
              result TEXT NOT NULL, PRIMARY KEY(run_id,command_id));
            CREATE TABLE IF NOT EXISTS readiness_leases (
              run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS readiness_receipts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, principal_id, request, config, runtime_manifest_digest=""):
        digest = canonical_digest({"input": request.model_dump(mode="json"), "config": config.model_dump(mode="json")})
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM readiness_runs WHERE principal_id=? AND project_id=? AND request_id=?",
                (principal_id, request.project_id, request.request_id),
            ).fetchone()
            if row:
                if row["input_digest"] != digest:
                    raise ValueError("READINESS_IDEMPOTENCY_CONFLICT")
                return ReadinessRun.model_validate_json(row["payload"])
            run = ReadinessRun(
                id=str(uuid4()),
                principal_id=principal_id,
                request=request,
                config=config,
                runtime_manifest_digest=runtime_manifest_digest,
            )
            db.execute(
                "INSERT INTO readiness_runs VALUES (?,?,?,?,?,?,?)",
                (run.id, principal_id, request.project_id, request.request_id, digest, 0, run.model_dump_json()),
            )
            return run

    def load(self, run_id, principal_id=None):
        with self.connect() as db:
            row = db.execute("SELECT payload,principal_id FROM readiness_runs WHERE id=?", (run_id,)).fetchone()
            if not row or principal_id is not None and row["principal_id"] != principal_id:
                raise ValueError("READINESS_NOT_FOUND")
            return ReadinessRun.model_validate_json(row["payload"])

    def all_runs(self):
        with self.connect() as db:
            return tuple(
                ReadinessRun.model_validate_json(row[0]) for row in db.execute("SELECT payload FROM readiness_runs")
            )

    def _update(self, db, run_id, expected_revision, changes):
        fence = self.fence.get()
        if fence and fence[0] == run_id:
            lease = db.execute("SELECT owner,expires FROM readiness_leases WHERE run_id=?", (run_id,)).fetchone()
            if not lease or lease[0] != fence[1] or lease[1] <= time.time():
                raise ValueError("READINESS_LEASE_LOST")
        row = db.execute(
            "SELECT payload FROM readiness_runs WHERE id=? AND revision=?", (run_id, expected_revision)
        ).fetchone()
        if row is None:
            raise ValueError("READINESS_REVISION_CONFLICT")
        payload = json.loads(row[0])
        payload.update(changes)
        payload["revision"] = expected_revision + 1
        run = ReadinessRun.model_validate(payload)
        db.execute(
            "UPDATE readiness_runs SET revision=?,payload=? WHERE id=? AND revision=?",
            (run.revision, run.model_dump_json(), run.id, expected_revision),
        )
        return run

    def update(self, run_id, expected_revision, changes):
        with self.connect() as db:
            return self._update(db, run_id, expected_revision, changes)

    def command(self, run_id, command_id, payload, expected_revision, changes, operation_result=None):
        digest = canonical_digest(payload)
        with self.connect() as db:
            row = db.execute(
                "SELECT digest,result FROM readiness_commands WHERE run_id=? AND command_id=?", (run_id, command_id)
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("READINESS_IDEMPOTENCY_CONFLICT")
                return ReadinessRun.model_validate_json(row[1])
            run = self._update(db, run_id, expected_revision, changes)
            if operation_result:
                identity, result = operation_result
                db.execute(
                    "UPDATE readiness_operations SET state='COMPLETED',payload=? WHERE id=? AND run_id=?",
                    (json.dumps(result), identity, run_id),
                )
            db.execute(
                "INSERT INTO readiness_commands VALUES (?,?,?,?)", (run_id, command_id, digest, run.model_dump_json())
            )
            return run

    def command_result(self, run_id, command_id, payload):
        with self.connect() as db:
            row = db.execute(
                "SELECT digest,result FROM readiness_commands WHERE run_id=? AND command_id=?", (run_id, command_id)
            ).fetchone()
            if row:
                if row[0] != canonical_digest(payload):
                    raise ValueError("READINESS_IDEMPOTENCY_CONFLICT")
                return ReadinessRun.model_validate_json(row[1])

    def begin_operation(self, run_id, operation_id, role, session_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM readiness_operations WHERE id=?", (operation_id,)).fetchone()
            if row:
                if (row["run_id"], row["role"], row["session_id"]) != (run_id, role, session_id):
                    raise ValueError("READINESS_OPERATION_BINDING_INVALID")
                return self._operation(row, False)
            db.execute(
                "INSERT INTO readiness_operations VALUES (?,?,?,?,?,NULL)",
                (operation_id, run_id, role, session_id, "INTENT"),
            )
            return SimpleNamespace(state="INTENT", is_new=True, result=None, session_id=session_id)

    @staticmethod
    def _operation(row, is_new=False):
        return SimpleNamespace(
            **dict(row), is_new=is_new, result=json.loads(row["payload"]) if row["payload"] else None
        )

    def observe_operation(self, operation_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM readiness_operations WHERE id=?", (operation_id,)).fetchone()
            return self._operation(row) if row else None

    def finish_operation(self, operation_id, result):
        self.operation_state(operation_id, "COMPLETED", result)

    def operation_state(self, operation_id, state, result=None):
        with self.connect() as db:
            db.execute(
                "UPDATE readiness_operations SET state=?,payload=? WHERE id=?",
                (state, json.dumps(result) if result is not None else None, operation_id),
            )

    def lease(self, run_id, owner, seconds=120):
        with self.connect() as db:
            db.execute("DELETE FROM readiness_leases WHERE expires<?", (time.time(),))
            row = db.execute("SELECT owner FROM readiness_leases WHERE run_id=?", (run_id,)).fetchone()
            if row and row[0] != owner:
                return False
            db.execute("INSERT OR REPLACE INTO readiness_leases VALUES (?,?,?)", (run_id, owner, time.time() + seconds))
            return True

    def release(self, run_id, owner):
        with self.connect() as db:
            db.execute("DELETE FROM readiness_leases WHERE run_id=? AND owner=?", (run_id, owner))

    def save_receipt(self, receipt):
        with self.connect() as db:
            db.execute("INSERT INTO readiness_receipts VALUES (?,?)", (receipt["id"], json.dumps(receipt)))

    def receipt(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM readiness_receipts WHERE id=?", (identity,)).fetchone()
            return json.loads(row[0]) if row else None

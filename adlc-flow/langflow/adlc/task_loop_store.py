"""Transactional loop/attempt checkpoints and crash-released execution locks."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime  # noqa: TC003 - Pydantic resolves this at runtime.
from typing import TYPE_CHECKING, Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves this at runtime.

from pydantic import Field, ValidationError, model_validator

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.models import Artifact, TaskRequest, TaskResult  # noqa: TC001 - Pydantic runtime fields.
from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopState, LiveLoopVerification
from langflow.adlc.task_loop_models import Digest, LoopModel
from langflow.adlc.task_loop_runtime_models import (
    LoopCandidateReference,
    LoopRuntimeCheckpoint,
)
from langflow.adlc.task_loop_runtime_v2 import LoopRuntimeCheckpointV2, runtime_models
from langflow.adlc.task_loop_workspace import LiveLoopError

if TYPE_CHECKING:
    from pathlib import Path

    from langflow.adlc.models import TaskRequest


class LiveLoopAttempt(LoopModel):
    attempt_id: UUID
    request_id: UUID
    idempotency_key: str
    request_digest: Digest
    loop_key: str
    iteration: int
    phase: Literal["RESERVED", "AGENT_RUNNING", "CANDIDATE_CAPTURED", "VERIFIED", "FINISHED"] = "RESERVED"
    started_at: datetime
    session_id: str | None = None
    candidate: LiveLoopCandidate | None = None
    verification: LiveLoopVerification | None = None
    additional_evidence: dict = Field(default_factory=dict)
    artifacts: tuple[Artifact, ...] = ()
    payloads: dict[str, str] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = 0.0
    result: TaskResult | None = None
    request_snapshot: TaskRequest | None = None
    runtime_checkpoint: LoopRuntimeCheckpoint | LoopRuntimeCheckpointV2 | None = None

    @model_validator(mode="after")
    def bound_runtime_header(self) -> LiveLoopAttempt:
        header = self.runtime_checkpoint
        if header is None:
            return self
        proof = (
            sha256_digest(
                {
                    "behavioral": self.verification.model_dump(mode="json"),
                    "additional": self.additional_evidence,
                }
            )
            if self.verification
            else None
        )
        if (
            header.attempt_id != self.attempt_id
            or header.request_id != self.request_id
            or header.iteration != self.iteration
            or header.phase != self.phase
            or f"{header.workflow_run_id}:{header.task_run_id}" != self.loop_key
            or header.candidate != (LoopCandidateReference.of(self.candidate) if self.candidate else None)
            or (header.session.session_id if header.session else None) != self.session_id
            or header.verification_digest != proof
            or (self.candidate and self.candidate.parent_candidate_id != header.parent_candidate.candidate_id)
            or (self.verification and self.verification.spec_digest != header.spec_digest)
            or (
                self.candidate
                and (
                    header.session is None
                    or not header.session.fresh_context
                    or (header.mode == "FILE_PROPOSAL" and not header.session.tools_disabled)
                )
            )
            or (
                header.usage
                and header.usage.model_dump()
                != {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "total_tokens": self.total_tokens,
                    "cost": self.cost,
                }
            )
        ):
            message = "Runtime checkpoint is not bound to the sealed kernel attempt"
            raise ValueError(message)
        return self


def seal_runtime_checkpoint(attempt: LiveLoopAttempt) -> LiveLoopAttempt:
    """Only the kernel ledger can attach captured candidates and executed proof to a runtime header."""
    header = attempt.runtime_checkpoint
    if header is None:
        return attempt
    _, _, _, checkpoint_model, usage_model = runtime_models(header.runtime)
    header = checkpoint_model.model_validate(
        {
            **header.model_dump(),
            "phase": attempt.phase,
            "candidate": LoopCandidateReference.of(attempt.candidate) if attempt.candidate else None,
            "usage": usage_model(
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                total_tokens=attempt.total_tokens,
                cost=attempt.cost,
            )
            if header.outcome_digest
            else header.usage,
            "verification_digest": sha256_digest(
                {
                    "behavioral": attempt.verification.model_dump(mode="json"),
                    "additional": attempt.additional_evidence,
                }
            )
            if attempt.verification
            else None,
        }
    )
    return attempt.model_copy(update={"runtime_checkpoint": header})


class AttemptLease:
    """Kernel lock: duplicates wait; a crashed process cannot retain ownership."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                if self.path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class TaskLoopStore:
    def __init__(self, database_path: Path, *, initialize: bool = True) -> None:
        self.path = database_path.resolve()
        if not initialize:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS task_loop_states (
                loop_key TEXT PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL, active_attempt TEXT
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS task_loop_attempts (
                attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, digest TEXT NOT NULL
            )""")
            connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS task_loop_runtime_unique_sessions
                ON task_loop_attempts(
                    COALESCE(json_extract(payload, '$.runtime_checkpoint.runtime.runtime_ref'),
                             'runtime:opencode-task-loop/0.1.0'),
                    json_extract(payload, '$.session_id'))
                WHERE json_extract(payload, '$.session_id') IS NOT NULL""")
            # Replace the private OpenCode-only index, retaining uniqueness for all legacy sessions.
            connection.execute("DROP INDEX IF EXISTS task_loop_unique_sessions")

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def key(request: TaskRequest) -> str:
        return f"{request.workflow_run_id}:{request.task_run_id}"

    def lease(self, request: TaskRequest) -> AttemptLease:
        return AttemptLease(self.path.parent / (self.path.name + ".locks") / f"{request.attempt_id.hex}.lock")

    @staticmethod
    def _decode(row, model):
        try:
            value = model.model_validate_json(row["payload"])
            if row["digest"] != sha256_digest(json.loads(row["payload"])):
                code = "TASK_LOOP_CHECKPOINT_CORRUPT"
                raise LiveLoopError(code)
        except (ValidationError, TypeError, KeyError) as exc:
            code = "TASK_LOOP_CHECKPOINT_CORRUPT"
            raise LiveLoopError(code) from exc
        else:
            return value

    def attempt(self, request: TaskRequest) -> LiveLoopAttempt | None:
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM task_loop_attempts WHERE attempt_id=? OR request_id=? OR idempotency_key=?",
                (str(request.attempt_id), str(request.request_id), request.idempotency_key),
            ).fetchall()
        if not rows:
            return None
        attempt = self._decode(rows[0], LiveLoopAttempt)
        if (
            len(rows) != 1
            or attempt.attempt_id != request.attempt_id
            or attempt.request_id != request.request_id
            or attempt.request_digest != sha256_digest(request.model_dump(mode="json"))
        ):
            code = "TASK_LOOP_IDEMPOTENCY_CONFLICT"
            raise LiveLoopError(code)
        if attempt.loop_key != self.key(request):
            code = "TASK_LOOP_CORRELATION_MISMATCH"
            raise LiveLoopError(code)
        return attempt

    def state(self, request: TaskRequest) -> LiveLoopState | None:
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM task_loop_states WHERE loop_key=?", (self.key(request),)).fetchone()
        return self._decode(row, LiveLoopState) if row else None

    def inspect(self, request: TaskRequest) -> tuple[LiveLoopState | None, tuple[LiveLoopAttempt, ...]]:
        """Read a consistent bounded ledger without reserving work or acquiring a lease."""
        key = self.key(request)
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            row = connection.execute("SELECT * FROM task_loop_states WHERE loop_key=?", (key,)).fetchone()
            rows = connection.execute(
                "SELECT * FROM task_loop_attempts WHERE json_extract(payload, '$.loop_key')=? "
                "ORDER BY json_extract(payload, '$.iteration') LIMIT 101",
                (key,),
            ).fetchall()
        state = self._decode(row, LiveLoopState) if row else None
        attempts = tuple(self._decode(item, LiveLoopAttempt) for item in rows)
        if (
            len(attempts) > 100  # noqa: PLR2004 - the public iteration cap.
            or (attempts and state is None)
            or (state and state.task_definition_id != request.task_definition_id)
            or (state and not 1 <= state.next_iteration <= 101)  # noqa: PLR2004
            or (
                state
                and {item.iteration for item in attempts}
                != set(range(1, state.next_iteration + bool(row["active_attempt"])))
            )
            or len({item.iteration for item in attempts}) != len(attempts)
            or (
                row
                and row["active_attempt"]
                and (
                    not attempts
                    or str(attempts[-1].attempt_id) != row["active_attempt"]
                    or attempts[-1].result is not None
                )
            )
            or (row and row["active_attempt"] is None and any(item.result is None for item in attempts))
            or any(item.loop_key != key for item in attempts)
            or any(
                item.result
                and (
                    item.result.workflow_run_id != request.workflow_run_id
                    or item.result.task_run_id != request.task_run_id
                    or item.result.attempt_id != item.attempt_id
                    or item.result.request_id != item.request_id
                )
                for item in attempts
            )
            or any(
                item.attempt_id == request.attempt_id
                and (
                    item.request_id != request.request_id
                    or item.request_digest != sha256_digest(request.model_dump(mode="json"))
                )
                for item in attempts
            )
        ):
            code = "TASK_LOOP_CHECKPOINT_CORRUPT"
            raise LiveLoopError(code)
        return state, attempts

    def artifact(self, request: TaskRequest, artifact_id: UUID) -> Artifact | None:
        _, attempts = self.inspect(request)
        return next(
            (
                item.model_copy(deep=True)
                for attempt in attempts
                for item in attempt.artifacts
                if item.artifact_id == artifact_id
                and item.kind == "SOURCE_PATCH"
                and item.workflow_run_id == request.workflow_run_id
                and item.task_run_id == request.task_run_id
            ),
            None,
        )

    def latest_request(self, run_id: UUID, task_id: UUID, definition_id: UUID) -> TaskRequest | None:
        """Read the last sealed request while the coordinator is between attempts."""
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM task_loop_attempts WHERE json_extract(payload, '$.loop_key')=? "
                "ORDER BY json_extract(payload, '$.iteration') DESC LIMIT 1",
                (f"{run_id}:{task_id}",),
            ).fetchone()
        if row is None:
            return None
        attempt = self._decode(row, LiveLoopAttempt)
        request = attempt.request_snapshot
        if request is None:
            return None  # Older checkpoints cannot restore a cleared inspection request.
        if (
            request.workflow_run_id != run_id
            or request.task_run_id != task_id
            or request.task_definition_id != definition_id
            or request.attempt_id != attempt.attempt_id
            or request.request_id != attempt.request_id
            or request.idempotency_key != attempt.idempotency_key
            or sha256_digest(request.model_dump(mode="json")) != attempt.request_digest
        ):
            code = "TASK_LOOP_CHECKPOINT_CORRUPT"
            raise LiveLoopError(code)
        return request.model_copy(deep=True)

    @staticmethod
    def _write_attempt(connection, attempt: LiveLoopAttempt) -> None:
        attempt = seal_runtime_checkpoint(attempt)
        connection.execute(
            "UPDATE task_loop_attempts SET payload=?, digest=? WHERE attempt_id=?",
            (attempt.model_dump_json(), sha256_digest(attempt.model_dump(mode="json")), str(attempt.attempt_id)),
        )

    def reserve(self, request: TaskRequest, state: LiveLoopState, started_at: datetime) -> LiveLoopAttempt:
        key = self.key(request)
        attempt = LiveLoopAttempt(
            attempt_id=request.attempt_id,
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            request_digest=sha256_digest(request.model_dump(mode="json")),
            loop_key=key,
            iteration=state.next_iteration,
            started_at=started_at,
            request_snapshot=request.model_copy(deep=True),
            cost=None if state.total_cost is None else 0.0,
        )
        try:
            with self.transaction() as connection:
                row = connection.execute("SELECT * FROM task_loop_states WHERE loop_key=?", (key,)).fetchone()
                if row:
                    persisted = self._decode(row, LiveLoopState)
                    if persisted.runtime_binding is None and state.runtime_binding is not None:
                        persisted = persisted.model_copy(update={"runtime_binding": state.runtime_binding})
                    if row["active_attempt"] is not None or persisted != state:
                        code = "TASK_LOOP_ATTEMPT_CONFLICT"
                        raise LiveLoopError(code)
                else:
                    connection.execute(
                        "INSERT INTO task_loop_states VALUES (?, ?, ?, NULL)",
                        (key, state.model_dump_json(), sha256_digest(state.model_dump(mode="json"))),
                    )
                connection.execute(
                    "INSERT INTO task_loop_attempts VALUES (?, ?, ?, ?, ?)",
                    (
                        str(attempt.attempt_id),
                        str(attempt.request_id),
                        attempt.idempotency_key,
                        attempt.model_dump_json(),
                        sha256_digest(attempt.model_dump(mode="json")),
                    ),
                )
                connection.execute(
                    "UPDATE task_loop_states SET payload=?, digest=?, active_attempt=? WHERE loop_key=?",
                    (
                        state.model_dump_json(),
                        sha256_digest(state.model_dump(mode="json")),
                        str(attempt.attempt_id),
                        key,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            code = "TASK_LOOP_IDEMPOTENCY_CONFLICT"
            raise LiveLoopError(code) from exc
        return attempt

    def checkpoint(self, attempt: LiveLoopAttempt) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT active_attempt FROM task_loop_states WHERE loop_key=?", (attempt.loop_key,)
            ).fetchone()
            if row is None or row["active_attempt"] != str(attempt.attempt_id):
                code = "TASK_LOOP_CHECKPOINT_CONFLICT"
                raise LiveLoopError(code)
            self._write_attempt(connection, attempt)

    def finish(self, attempt: LiveLoopAttempt, state: LiveLoopState, result: TaskResult) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT active_attempt FROM task_loop_states WHERE loop_key=?", (attempt.loop_key,)
            ).fetchone()
            if row is None or row["active_attempt"] != str(attempt.attempt_id):
                code = "TASK_LOOP_CHECKPOINT_CONFLICT"
                raise LiveLoopError(code)
            self._write_attempt(connection, attempt.model_copy(update={"phase": "FINISHED", "result": result}))
            connection.execute(
                "UPDATE task_loop_states SET payload=?, digest=?, active_attempt=NULL WHERE loop_key=?",
                (state.model_dump_json(), sha256_digest(state.model_dump(mode="json")), attempt.loop_key),
            )

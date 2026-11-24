"""Separate H6B archive, exact approval, cancellation intent and retained evidence."""

# ruff: noqa: EM101 - fixed public codes only.
import os
from functools import lru_cache
from pathlib import Path

from langflow.adlc.replay_models import MAX_REPLAY_EVIDENCE_BYTES, ReplayRead, compare_replay
from langflow.adlc.verification_models import VerificationError
from langflow.adlc.verification_repository import VerificationRepository, now

RUNNER_DIGEST = "sha256:b181341587bdc60dde4be167d9504af960927cb173046cd26886bd27ae250803"


class ReplayRepository(VerificationRepository):
    table_name = "adlc_verification_replays"
    record_type = ReplayRead
    runner_digest = RUNNER_DIGEST
    comparator = staticmethod(compare_replay)
    active_states = frozenset({"RUNNING", "DISPATCH_UNCERTAIN", "CANCEL_REQUESTED"})
    evidence_limit = MAX_REPLAY_EVIDENCE_BYTES

    def _read(self, row):
        record = super()._read(row)
        if (
            (record.cancel_requested_at is None) != (record.cancel_requested_by is None)
            or (record.cancel_requested_by is not None and record.cancel_requested_by != row["owner_id"])
            or (record.state in {"CANCEL_REQUESTED", "CANCELLED"} and not record.cancel_requested_at)
            or (record.state == "CANCELLED") != (record.cancelled_at is not None)
            or (record.approved_by is not None and record.approved_by != row["owner_id"])
        ):
            raise VerificationError("VERIFICATION_STORE_INVALID", 503)
        return record

    def action(self, plan_id, *, owner, run_id, plan_digest, operation):
        if operation != "cancel":
            return super().action(plan_id, owner=owner, run_id=run_id, plan_digest=plan_digest, operation=operation)
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.plan_digest != plan_digest:
                raise VerificationError("VERIFICATION_REFERENCE_CONFLICT")
            if record.state not in self.active_states | {"APPROVED", "CANCELLED"}:
                raise VerificationError("REPLAY_CANCELLATION_NOT_ALLOWED")
            if record.state != "CANCELLED":
                if not record.cancel_requested_at:
                    record.cancel_requested_by, record.cancel_requested_at = owner, now()
                # An approved but undispatched suite has no external target/job.
                record.state = "CANCEL_REQUESTED" if record.execution_id else "CANCELLED"
                if not record.execution_id:
                    record.cancelled_at = now()
                self._save(record, row["candidate"])
            return record, row["candidate"]

    def confirm_cancel(self, plan_id, *, owner, run_id, execution_id):
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.state == "CANCELLED":
                return record
            if record.state != "CANCEL_REQUESTED" or record.execution_id != execution_id:
                raise VerificationError("REPLAY_CANCELLATION_UNCONFIRMED")
            record.state, record.cancelled_at, record.error_code = "CANCELLED", now(), None
            self._save(record, row["candidate"])
            return record

    def diagnostic(self, plan_id, *, owner, run_id, code, uncertain=False):
        with self.transaction():
            row = self._row(plan_id, owner, run_id)
            record = self._read(row)
            if record.state in self.active_states:
                if record.state != "CANCEL_REQUESTED":
                    record.state = "DISPATCH_UNCERTAIN" if uncertain else "NOT_VERIFIED"
                record.error_code = code
                self._save(record, row["candidate"])
            return record


@lru_cache(maxsize=1)
def get_replay_repository():
    configured = os.getenv("ADLC_REPLAY_DB_PATH")
    path = (
        Path(__file__).resolve().parents[2] / "data" / "adlc-replays.sqlite3"
        if configured is None
        else (configured.strip() or None)
    )
    return ReplayRepository(path)

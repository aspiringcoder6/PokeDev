"""Bounded H6D sidecar archive. No scheduler, model, broker or verdict mutations."""

# ruff: noqa: EM101 - fixed codes only.
import base64
import binascii
import hashlib
import io
import os
import sqlite3
import struct
import warnings
import zlib
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from langflow.adlc.test_extension_models import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    MAX_PNG_BYTES,
    MAX_SCREENSHOTS_PER_PLAN,
    ProposalRead,
    ProposalReference,
    ReplaySource,
    ScreenshotRead,
    TestProposal,
)
from langflow.adlc.verification_models import VerificationError, digest
from langflow.adlc.verification_repository import now

PNG_CHUNK_OVERHEAD = 12


def bytes_digest(body):
    return "sha256:" + hashlib.sha256(body).hexdigest()


def proposal_reference(document):
    return ProposalReference(
        proposal_id=document.proposal_id, revision=document.revision, document_digest=digest(document)
    )


def replay_source(record):
    p = record.plan
    return ReplaySource(
        workflow_run_id=p.workflow_run_id,
        plan_id=p.plan_id,
        plan_digest=record.plan_digest,
        suite_digest=p.suite_digest,
        candidate_digest=p.candidate.content_digest,
        project_id=p.candidate.project_id,
        source_session_id=p.candidate.source_session_id,
        contract_reference=p.contract_reference,
    )


def normalize_png(command):
    """Single bounded raster only. Strip metadata/trailing payload by re-encoding.

    This validates image bytes, not a claimed screenshot's capture provenance.
    Never interpret SVG/HTML or fetch a remote artifact URL.
    """
    try:
        raw = base64.b64decode(command.png_base64, validate=True)
        if not raw or len(raw) > MAX_PNG_BYTES or bytes_digest(raw) != command.input_digest:
            raise ValueError
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError
        # Strip ancillary metadata before Pillow opens it, so compressed text/ICC
        # chunks cannot consume their decompression budget outside our raster cap.
        # Verify every chunk CRC; reject animation and unknown critical chunks.
        position, chunks, ended = 8, [raw[:8]], False
        allowed = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}
        while position < len(raw):
            if len(raw) - position < PNG_CHUNK_OVERHEAD:
                raise ValueError
            length = struct.unpack(">I", raw[position : position + 4])[0]
            end = position + length + 12
            if end > len(raw):
                raise ValueError
            kind, data = raw[position + 4 : position + 8], raw[position + 8 : position + 8 + length]
            checksum = struct.unpack(">I", raw[end - 4 : end])[0]
            if (
                zlib.crc32(kind + data) & 0xFFFFFFFF != checksum
                or kind in {b"acTL", b"fcTL", b"fdAT"}
                or (kind not in allowed and not kind[0] & 32)
            ):
                raise ValueError
            if kind in allowed:
                chunks.append(raw[position:end])
            position = end
            if kind == b"IEND":
                ended = True
                break
        if not ended:
            raise ValueError
        stripped = b"".join(chunks)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(stripped), formats=["PNG"]) as image:
                width, height = image.size
                if (
                    min(width, height) < 1
                    or max(width, height) > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise ValueError
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError
                image.verify()
            with Image.open(io.BytesIO(stripped), formats=["PNG"]) as image:
                output = io.BytesIO()
                image.convert("RGBA").save(output, format="PNG")
                body = output.getvalue()
                if len(body) > MAX_PNG_BYTES:
                    raise ValueError
    except (
        ValueError,
        binascii.Error,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        SyntaxError,
    ):
        raise VerificationError("TEST_SCREENSHOT_INVALID", 422) from None
    else:
        return body, width, height


class TestExtensionRepository:
    __test__ = False

    def __init__(self, path=None, *, max_records=200, max_commands=1000, max_bytes=8 * 1024 * 1024):
        self.lock = RLock()
        self.max_records, self.max_commands, self.max_bytes = max_records, max_commands, max_bytes
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path is not None else ":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS adlc_test_proposals (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, run TEXT NOT NULL,
                body TEXT NOT NULL, checksum TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS adlc_test_commands (
                owner TEXT NOT NULL, run TEXT NOT NULL, key TEXT NOT NULL,
                digest TEXT NOT NULL, proposal TEXT NOT NULL, UNIQUE(owner,run,key));
            CREATE TABLE IF NOT EXISTS adlc_test_images (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, run TEXT NOT NULL, plan TEXT NOT NULL,
                key TEXT NOT NULL, command_digest TEXT NOT NULL, body TEXT NOT NULL, png BLOB NOT NULL,
                checksum TEXT NOT NULL, UNIQUE(owner,run,key));
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                yield
                self.db.commit()
            except sqlite3.Error:
                self.db.rollback()
                raise VerificationError("TEST_ARCHIVE_UNAVAILABLE", 503) from None
            except Exception:
                self.db.rollback()
                raise

    def _quota(self):
        count, size = self.db.execute(
            "SELECT count(*),COALESCE(sum(length(CAST(body AS BLOB))),0) FROM adlc_test_proposals"
        ).fetchone()
        images, image_size = self.db.execute(
            "SELECT count(*),COALESCE(sum(length(CAST(body AS BLOB))+length(png)),0) FROM adlc_test_images"
        ).fetchone()
        commands, command_size = self.db.execute(
            "SELECT count(*),COALESCE(sum(length(owner)+length(run)+length(key)+length(digest)+length(proposal)),0) "
            "FROM adlc_test_commands"
        ).fetchone()
        if (
            count + images > self.max_records
            or size + image_size + command_size > self.max_bytes
            or commands > self.max_commands
        ):
            raise VerificationError("TEST_ARCHIVE_FULL", 413)

    def _read(self, row):
        if row is None:
            raise VerificationError("TEST_PROPOSAL_NOT_FOUND", 404)
        try:
            record = ProposalRead.model_validate_json(row["body"])
            if (
                bytes_digest(row["body"].encode()) != row["checksum"]
                or str(record.document.proposal_id) != row["id"]
                or str(record.document.source.workflow_run_id) != row["run"]
                or record.reference != proposal_reference(record.document)
                or (record.approved_by is not None and record.approved_by != row["owner"])
            ):
                raise ValueError
        except (ValueError, ValidationError, TypeError, RecursionError):
            raise VerificationError("TEST_ARCHIVE_INVALID", 503) from None
        else:
            return record

    def _row(self, proposal_id, owner, run_id):
        return self.db.execute(
            "SELECT * FROM adlc_test_proposals WHERE id=? AND owner=? AND run=?",
            (str(proposal_id), owner, str(run_id)),
        ).fetchone()

    def get(self, proposal_id, *, owner, run_id):
        with self.lock:
            return self._read(self._row(proposal_id, owner, run_id))

    def list(self, *, owner, run_id, session_id=None, limit=100, offset=0):
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM adlc_test_proposals WHERE owner=? AND run=? ORDER BY rowid DESC", (owner, str(run_id))
            ).fetchall()
            records = [self._read(row) for row in rows]
            if session_id is not None:
                records = [
                    r
                    for r in records
                    if session_id
                    in {
                        r.document.source.source_session_id,
                        r.document.authoring_session_id,
                    }
                ]
            return records[max(0, offset) : max(0, offset) + min(100, max(1, limit))]

    def _save(self, record, *, owner, run_id):
        # Revalidate internal model_copy transitions as well as incoming commands.
        record.reference = proposal_reference(record.document)
        record = ProposalRead.model_validate(record.model_dump(mode="json"))
        body = record.model_dump_json()
        self.db.execute(
            "INSERT INTO adlc_test_proposals VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET body=excluded.body, checksum=excluded.checksum",
            (str(record.reference.proposal_id), owner, str(run_id), body, bytes_digest(body.encode())),
        )
        self._quota()
        return record

    @staticmethod
    def exact(record, reference):
        if record.reference != reference:
            raise VerificationError("TEST_PROPOSAL_REFERENCE_CONFLICT")

    def command(self, command, *, owner, run_id, source=None, session_id=None, validate=None):
        with self.transaction():
            if command.operation == "get_status":
                return self._read(self._row(command.proposal_id, owner, run_id))
            checksum = digest({"command": command.model_dump(mode="json"), "session_id": session_id})
            prior = self.db.execute(
                "SELECT * FROM adlc_test_commands WHERE owner=? AND run=? AND key=?",
                (owner, str(run_id), command.idempotency_key),
            ).fetchone()
            if prior:
                if prior["digest"] != checksum:
                    raise VerificationError("TEST_PROPOSAL_IDEMPOTENCY_CONFLICT")
                return self._read(self._row(prior["proposal"], owner, run_id))
            if command.operation == "init":
                parent = None
                if command.parent_reference:
                    parent = self._read(self._row(command.parent_reference.proposal_id, owner, run_id))
                    self.exact(parent, command.parent_reference)
                    if parent.state == "DRAFT" or parent.document.source != replay_source(source):
                        raise VerificationError("TEST_PROPOSAL_FORK_NOT_ALLOWED")
                doc = TestProposal(
                    proposal_id=uuid4(),
                    revision=parent.reference.revision + 1 if parent else 1,
                    parent_reference=command.parent_reference,
                    source=replay_source(source),
                    authoring_session_id=session_id,
                    kind=command.kind,
                    title=command.title,
                    rationale=command.rationale,
                    cases=parent.document.cases if parent else source.plan.cases,
                )
                record = ProposalRead(document=doc, reference=proposal_reference(doc), state="DRAFT", created_at=now())
            else:
                record = self._read(self._row(command.reference.proposal_id, owner, run_id))
                self.exact(record, command.reference)
                if record.state != "DRAFT":
                    raise VerificationError("TEST_PROPOSAL_FROZEN")
                if session_id is not None and record.document.authoring_session_id != session_id:
                    raise VerificationError("TEST_PROPOSAL_NOT_FOUND", 404)
                doc = record.document
                if command.operation == "upsert_case":
                    doc.cases = [command.case if c.case_id == command.case.case_id else c for c in doc.cases]
                    if not any(c.case_id == command.case.case_id for c in doc.cases):
                        doc.cases.append(command.case)
                elif command.operation == "remove_case":
                    if not any(c.case_id == command.case_id for c in doc.cases):
                        raise VerificationError("TEST_PROPOSAL_CASE_NOT_FOUND", 422)
                    doc.cases = [c for c in doc.cases if c.case_id != command.case_id]
                elif command.operation == "set_permissions":
                    doc.permissions, doc.performance = command.permissions, command.performance
                elif command.operation == "validate":
                    if not doc.cases or not doc.permissions or (doc.kind == "performance" and not doc.performance):
                        raise VerificationError("TEST_PROPOSAL_INCOMPLETE", 422)
                    if validate is None:
                        raise VerificationError("TEST_PROPOSAL_VALIDATION_REQUIRED")
                    validate(doc)
                    record.state = "READY_FOR_REVIEW"
            try:
                record = self._save(record, owner=owner, run_id=run_id)
            except ValidationError:
                raise VerificationError("TEST_PROPOSAL_ARGUMENTS_INVALID", 422) from None
            self.db.execute(
                "INSERT INTO adlc_test_commands VALUES(?,?,?,?,?)",
                (owner, str(run_id), command.idempotency_key, checksum, str(record.reference.proposal_id)),
            )
            self._quota()
            return record

    def approve(self, reference, *, owner, run_id):
        with self.transaction():
            record = self._read(self._row(reference.proposal_id, owner, run_id))
            self.exact(record, reference)
            if record.state == "READY_FOR_REVIEW":
                record.state, record.approved_by, record.approved_at = "APPROVED", owner, now()
            elif record.state not in {"APPROVED", "MATERIALIZED"}:
                raise VerificationError("TEST_PROPOSAL_NOT_REVIEWABLE")
            return self._save(record, owner=owner, run_id=run_id)

    def materialized(self, reference, plan_id, *, owner, run_id):
        with self.transaction():
            record = self._read(self._row(reference.proposal_id, owner, run_id))
            self.exact(record, reference)
            if record.state not in {"APPROVED", "MATERIALIZED"} or record.document.kind != "suite-revision":
                raise VerificationError("TEST_PROPOSAL_MATERIALIZATION_NOT_ALLOWED")
            if record.materialized_plan_id not in {None, plan_id}:
                raise VerificationError("TEST_PROPOSAL_REFERENCE_CONFLICT")
            record.state, record.materialized_plan_id = "MATERIALIZED", plan_id
            return self._save(record, owner=owner, run_id=run_id)

    def _image(self, row):
        if row is None:
            raise VerificationError("TEST_SCREENSHOT_NOT_FOUND", 404)
        try:
            record = ScreenshotRead.model_validate_json(row["body"])
            body = row["png"]
            if (
                row["checksum"] != bytes_digest(row["body"].encode() + b"\0" + body)
                or record.content_digest != bytes_digest(body)
                or record.byte_size != len(body)
                or str(record.attachment_id) != row["id"]
                or str(record.workflow_run_id) != row["run"]
                or str(record.plan_id) != row["plan"]
                or record.uploaded_by != row["owner"]
            ):
                raise ValueError
        except (ValueError, TypeError, ValidationError):
            raise VerificationError("TEST_ARCHIVE_INVALID", 503) from None
        else:
            return record, body

    def screenshots(self, replay, *, owner):
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM adlc_test_images WHERE owner=? AND run=? AND plan=? ORDER BY rowid",
                (owner, str(replay.plan.workflow_run_id), str(replay.plan.plan_id)),
            ).fetchall()
            records = [self._image(row)[0] for row in rows]
            for r in records:
                self._image_binding(r, replay)
            return records

    @staticmethod
    def _image_binding(record, replay):
        if (
            not replay.receipt
            or not replay.report
            or record.plan_digest != replay.plan_digest
            or record.execution_id != replay.execution_id
            or record.candidate_digest != replay.plan.candidate.content_digest
            or record.case_evidence_digest != replay.evidence_digest
            or record.case_id not in {c.case_id for c in replay.plan.cases}
        ):
            raise VerificationError("TEST_SCREENSHOT_BINDING_INVALID")

    def screenshot(self, attachment_id, replay, *, owner):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM adlc_test_images WHERE id=? AND owner=? AND run=? AND plan=?",
                (str(attachment_id), owner, str(replay.plan.workflow_run_id), str(replay.plan.plan_id)),
            ).fetchone()
            record, body = self._image(row)
            self._image_binding(record, replay)
            return record, body

    def attach(self, command, replay, *, owner):
        if (
            not replay.receipt
            or not replay.report
            or command.plan_digest != replay.plan_digest
            or command.execution_id != replay.execution_id
            or command.case_id not in {c.case_id for c in replay.plan.cases}
        ):
            raise VerificationError("TEST_SCREENSHOT_BINDING_INVALID")
        checksum = digest(command)
        body, width, height = normalize_png(command)
        with self.transaction():
            prior = self.db.execute(
                "SELECT * FROM adlc_test_images WHERE owner=? AND run=? AND key=?",
                (owner, str(replay.plan.workflow_run_id), command.idempotency_key),
            ).fetchone()
            if prior:
                if prior["command_digest"] != checksum or prior["plan"] != str(replay.plan.plan_id):
                    raise VerificationError("TEST_PROPOSAL_IDEMPOTENCY_CONFLICT")
                return self._image(prior)[0]
            if len(self.screenshots(replay, owner=owner)) >= MAX_SCREENSHOTS_PER_PLAN:
                raise VerificationError("TEST_SCREENSHOT_QUOTA", 413)
            record = ScreenshotRead(
                attachment_id=uuid4(),
                workflow_run_id=replay.plan.workflow_run_id,
                plan_id=replay.plan.plan_id,
                plan_digest=replay.plan_digest,
                execution_id=replay.execution_id,
                candidate_digest=replay.plan.candidate.content_digest,
                case_id=command.case_id,
                caption=command.caption,
                uploaded_by=owner,
                uploaded_at=now(),
                input_digest=command.input_digest,
                content_digest=bytes_digest(body),
                byte_size=len(body),
                width=width,
                height=height,
                case_evidence_digest=replay.evidence_digest,
            )
            text = record.model_dump_json()
            self.db.execute(
                "INSERT INTO adlc_test_images VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    str(record.attachment_id),
                    owner,
                    str(record.workflow_run_id),
                    str(record.plan_id),
                    command.idempotency_key,
                    checksum,
                    text,
                    body,
                    bytes_digest(text.encode() + b"\0" + body),
                ),
            )
            self._quota()
            return record


@lru_cache(maxsize=1)
def get_test_extension_repository():
    configured = os.getenv("ADLC_TEST_EXTENSIONS_DB_PATH")
    path = (
        Path(__file__).resolve().parents[2] / "data" / "adlc-test-extensions.sqlite3"
        if configured is None
        else configured.strip() or None
    )
    return TestExtensionRepository(path)

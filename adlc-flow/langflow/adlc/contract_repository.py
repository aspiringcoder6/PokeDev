"""Atomic, owner-scoped JSON revisions and human approvals, independent of Harness cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import ValidationError

from langflow.adlc.contract_models import (
    MAX_REVISIONS,
    TOOL_ARGUMENT_MODELS,
    ContractApproval,
    ContractApprovalCommand,
    ContractForkCommand,
    ContractRead,
    ContractReference,
    ContractScope,
    ContractToolResult,
    ContractValidation,
    DependencyArguments,
    InitArguments,
    RemoveArguments,
    SkilltreeDependency,
    SkilltreeDocument,
    SkilltreeNode,
    StatusArguments,
    UpsertArguments,
    ValidateArguments,
)
from langflow.adlc.contract_validation import content_digest, document_bytes, structural_issues, validate_document

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import Any, Literal

MAX_LIST_PAGE_SIZE = 100
MAX_COMMANDS_PER_DOCUMENT = 2048


class ContractError(RuntimeError):
    def __init__(self, code: str, http_status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ContractRepository:
    """One transactional store: immutable content rows, separate validation/approval receipts.

    No workspace filename, agent-provided JSON document, owner or approval state is accepted.
    A SQLite write transaction also fences concurrent processes; no in-memory head cache is used.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        max_total_bytes: int = 32 * 1024 * 1024,
        max_documents: int = 1000,
    ) -> None:
        self.path = Path(path).resolve() if path is not None else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._max_total_bytes = max_total_bytes
        self._max_documents = max_documents
        self._lock = RLock()
        if max_total_bytes <= 0 or max_documents <= 0:
            msg = "Contract storage bounds must be positive."
            raise ValueError(msg)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.path) if self.path is not None else ":memory:", check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS adlc_contract_heads (
                contract_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, workflow_run_id TEXT NOT NULL,
                binding_json TEXT NOT NULL, revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS adlc_contract_revisions (
                contract_id TEXT NOT NULL REFERENCES adlc_contract_heads(contract_id), revision INTEGER NOT NULL,
                payload BLOB NOT NULL, content_digest TEXT NOT NULL, status TEXT NOT NULL,
                validation_json TEXT, approval_json TEXT, created_at TEXT NOT NULL,
                authored_by TEXT NOT NULL, authored_via TEXT NOT NULL,
                PRIMARY KEY(contract_id, revision)
            );
            CREATE TABLE IF NOT EXISTS adlc_contract_commands (
                command_key TEXT PRIMARY KEY, request_digest TEXT NOT NULL, contract_id TEXT NOT NULL,
                revision INTEGER NOT NULL, node_id TEXT
            );
            CREATE INDEX IF NOT EXISTS adlc_contract_owner_run ON adlc_contract_heads(owner_id, workflow_run_id);
        """)
        self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def approved_reference(self, reference: ContractReference, *, owner_id: str) -> ContractRead:
        """Resolve a reusable exact reference without trusting a caller's source run/owner."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM adlc_contract_heads WHERE contract_id=? AND owner_id=?",
                (str(reference.contract_id), owner_id),
            ).fetchone()
            if row is None:
                msg = "CONTRACT_NOT_FOUND"
                raise ContractError(msg, 404)
            current = self._read(row)
            if current.reference != reference:
                msg = "REVISION_CONFLICT"
                raise ContractError(msg)
            if current.status != "APPROVED" or current.approval is None:
                msg = "CONTRACT_EXECUTION_REQUIRES_APPROVAL"
                raise ContractError(msg)
            return current

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.commit()
            except sqlite3.Error:
                self._connection.rollback()
                msg = "CONTRACT_STORE_UNAVAILABLE"
                raise ContractError(msg, 503) from None
            except Exception:
                self._connection.rollback()
                raise

    def _head(self, contract_id: UUID, owner_id: str, run_id: UUID, scope: ContractScope | None = None) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM adlc_contract_heads WHERE contract_id=? AND owner_id=? AND workflow_run_id=?",
            (str(contract_id), owner_id, str(run_id)),
        ).fetchone()
        if row is None or (scope is not None and row["binding_json"] != scope.model_dump_json()):
            msg = "CONTRACT_NOT_FOUND"
            raise ContractError(msg, 404)
        return row

    def _read(self, head: sqlite3.Row, revision: int | None = None) -> ContractRead:
        row = self._connection.execute(
            "SELECT * FROM adlc_contract_revisions WHERE contract_id=? AND revision=?",
            (head["contract_id"], revision if revision is not None else head["revision"]),
        ).fetchone()
        if row is None:
            msg = "CONTRACT_NOT_FOUND"
            raise ContractError(msg, 404)
        try:
            document = SkilltreeDocument.model_validate_json(row["payload"])
            reference = ContractReference(
                contract_id=document.contract_id, revision=document.revision, content_digest=content_digest(document)
            )
            if (
                str(document.contract_id) != row["contract_id"]
                or document.revision != row["revision"]
                or reference.content_digest != row["content_digest"]
                or document_bytes(document) != bytes(row["payload"])
                or structural_issues(document)
            ):
                msg = "Invalid stored document"
                raise ValueError(msg)
            validation = (
                ContractValidation.model_validate_json(row["validation_json"]) if row["validation_json"] else None
            )
            approval = ContractApproval.model_validate_json(row["approval_json"]) if row["approval_json"] else None
            if validation and validation.content_digest != reference.content_digest:
                msg = "Invalid validation binding"
                raise ValueError(msg)
            if approval and (approval.reference != reference or approval.approved_by != head["owner_id"]):
                msg = "Invalid approval binding"
                raise ValueError(msg)
            if row["status"] in {"VALIDATED", "APPROVED"} and (validation is None or not validation.passed):
                msg = "Missing successful validation"
                raise ValueError(msg)
            if (row["status"] == "APPROVED") != (approval is not None):
                msg = "Invalid approval state"
                raise ValueError(msg)
            return ContractRead(
                document=document,
                reference=reference,
                binding=ContractScope.model_validate_json(head["binding_json"]),
                status=row["status"],
                validation=validation,
                approval=approval,
                created_at=row["created_at"],
                authored_by=row["authored_by"],
                authored_via=row["authored_via"],
            )
        except (ValidationError, ValueError, TypeError):
            msg = "CONTRACT_STORE_INVALID"
            raise ContractError(msg, 503) from None

    def get(
        self,
        contract_id: UUID,
        *,
        owner_id: str,
        run_id: UUID,
        revision: int | None = None,
        scope: ContractScope | None = None,
    ) -> ContractRead:
        with self._lock:
            return self._read(self._head(contract_id, owner_id, run_id, scope), revision)

    def list_for_run(
        self, run_id: UUID, *, owner_id: str, limit: int = 50, offset: int = 0, scope: ContractScope | None = None
    ) -> list[ContractRead]:
        if not 1 <= limit <= MAX_LIST_PAGE_SIZE or offset < 0:
            msg = "CONTRACT_QUERY_INVALID"
            raise ContractError(msg, 422)
        with self._lock:
            if scope is not None and scope.workflow_run_id != run_id:
                msg = "CONTRACT_QUERY_INVALID"
                raise ContractError(msg, 422)
            binding_json = scope.model_dump_json() if scope is not None else None
            heads = self._connection.execute(
                "SELECT * FROM adlc_contract_heads WHERE owner_id=? AND workflow_run_id=? "
                "AND (? IS NULL OR binding_json=?) ORDER BY contract_id LIMIT ? OFFSET ?",
                (owner_id, str(run_id), binding_json, binding_json, limit, offset),
            ).fetchall()
            return [self._read(head) for head in heads]

    @staticmethod
    def _command_identity(owner_id: str, scope: ContractScope, key: str, operation: str, arguments) -> tuple[str, str]:
        namespace = _json({"owner": owner_id, "scope": scope.model_dump(mode="json"), "key": key})
        command_key = hashlib.sha256(namespace.encode()).hexdigest()
        digest = hashlib.sha256(_json({"operation": operation, "arguments": arguments}).encode()).hexdigest()
        return command_key, digest

    def _replay(self, identity: tuple[str, str], owner_id: str, scope: ContractScope) -> ContractToolResult | None:
        row = self._connection.execute(
            "SELECT * FROM adlc_contract_commands WHERE command_key=?", (identity[0],)
        ).fetchone()
        if row is None:
            return None
        if row["request_digest"] != identity[1]:
            msg = "CONTRACT_IDEMPOTENCY_CONFLICT"
            raise ContractError(msg)
        head = self._head(UUID(row["contract_id"]), owner_id, scope.workflow_run_id, scope)
        return ContractToolResult(contract=self._read(head, row["revision"]), node_id=row["node_id"], replayed=True)

    def _remember(self, identity: tuple[str, str], result: ContractToolResult) -> None:
        count = self._connection.execute(
            "SELECT COUNT(*) FROM adlc_contract_commands WHERE contract_id=?",
            (str(result.contract.document.contract_id),),
        ).fetchone()[0]
        if count >= MAX_COMMANDS_PER_DOCUMENT:
            msg = "CONTRACT_COMMAND_LIMIT"
            raise ContractError(msg, 413)
        self._connection.execute(
            "INSERT INTO adlc_contract_commands VALUES (?, ?, ?, ?, ?)",
            (
                identity[0],
                identity[1],
                str(result.contract.document.contract_id),
                result.contract.document.revision,
                str(result.node_id) if result.node_id else None,
            ),
        )

    def _write_revision(self, document: SkilltreeDocument, *, actor_id: str, authored_via: str) -> None:
        issues = structural_issues(document)
        if issues:
            raise ContractError(issues[0], 413 if issues[0] == "CONTRACT_DOCUMENT_TOO_LARGE" else 409)
        payload = document_bytes(document)
        total = self._connection.execute(
            "SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM adlc_contract_revisions"
        ).fetchone()[0]
        if total + len(payload) > self._max_total_bytes:
            msg = "CONTRACT_STORE_FULL"
            raise ContractError(msg, 413)
        self._connection.execute(
            """INSERT INTO adlc_contract_revisions
               (contract_id, revision, payload, content_digest, status, created_at, authored_by, authored_via)
               VALUES (?, ?, ?, ?, 'DRAFT', ?, ?, ?)""",
            (
                str(document.contract_id),
                document.revision,
                payload,
                content_digest(document),
                self._clock().isoformat(),
                actor_id,
                authored_via,
            ),
        )
        self._connection.execute(
            "UPDATE adlc_contract_heads SET revision=? WHERE contract_id=?",
            (document.revision, str(document.contract_id)),
        )

    def _create(
        self, document: SkilltreeDocument, owner_id: str, scope: ContractScope, actor_id: str, authored_via: str
    ) -> ContractRead:
        count = self._connection.execute("SELECT COUNT(*) FROM adlc_contract_heads").fetchone()[0]
        if count >= self._max_documents:
            msg = "CONTRACT_STORE_FULL"
            raise ContractError(msg, 413)
        self._connection.execute(
            "INSERT INTO adlc_contract_heads VALUES (?, ?, ?, ?, 1)",
            (str(document.contract_id), owner_id, str(scope.workflow_run_id), scope.model_dump_json()),
        )
        self._write_revision(document, actor_id=actor_id, authored_via=authored_via)
        return self._read(self._head(document.contract_id, owner_id, scope.workflow_run_id, scope))

    def execute(
        self,
        tool: str,
        arguments: dict,
        *,
        owner_id: str,
        scope: ContractScope,
        actor_id: str,
        authored_via: Literal["HUMAN", "HARNESS_TOOL"],
    ) -> ContractToolResult:
        model = TOOL_ARGUMENT_MODELS.get(tool)
        if model is None:
            msg = "CONTRACT_TOOL_NOT_ALLOWED"
            raise ContractError(msg, 403)
        try:
            args = model.model_validate(arguments)
        except ValidationError:
            msg = "CONTRACT_ARGUMENTS_INVALID"
            raise ContractError(msg, 422) from None
        if isinstance(args, StatusArguments):
            return ContractToolResult(
                contract=self.get(
                    args.contract_id,
                    owner_id=owner_id,
                    run_id=scope.workflow_run_id,
                    scope=scope,
                    revision=args.revision,
                )
            )
        identity = self._command_identity(owner_id, scope, args.idempotency_key, tool, args.model_dump(mode="json"))
        with self._transaction():
            replay = self._replay(identity, owner_id, scope)
            if replay is not None:
                return replay
            if isinstance(args, InitArguments):
                created = self._create(
                    SkilltreeDocument(
                        contract_id=uuid4(),
                        revision=1,
                        title=args.title,
                        scope=args.scope,
                        constraints=args.constraints,
                    ),
                    owner_id,
                    scope,
                    actor_id,
                    authored_via,
                )
                result = ContractToolResult(contract=created)
            else:
                head = self._head(args.contract_id, owner_id, scope.workflow_run_id, scope)
                current = self._read(head)
                if current.status == "APPROVED":
                    msg = "CONTRACT_LOCKED"
                    raise ContractError(msg)
                if current.document.revision != args.expected_revision:
                    msg = "REVISION_CONFLICT"
                    raise ContractError(msg)
                if isinstance(args, ValidateArguments):
                    report = validate_document(current.document, self._clock())
                    self._connection.execute(
                        "UPDATE adlc_contract_revisions SET status=?, validation_json=? "
                        "WHERE contract_id=? AND revision=?",
                        (
                            "VALIDATED" if report.passed else "DRAFT",
                            report.model_dump_json(),
                            str(args.contract_id),
                            args.expected_revision,
                        ),
                    )
                    result = ContractToolResult(contract=self._read(head))
                else:
                    document, node_id = self._edit(current.document, args)
                    self._write_revision(document, actor_id=actor_id, authored_via=authored_via)
                    result = ContractToolResult(
                        contract=self._read(self._head(args.contract_id, owner_id, scope.workflow_run_id, scope)),
                        node_id=node_id,
                    )
            self._remember(identity, result)
            return result

    @staticmethod
    def _edit(document: SkilltreeDocument, args) -> tuple[SkilltreeDocument, UUID | None]:
        if document.revision >= MAX_REVISIONS:
            msg = "CONTRACT_REVISION_LIMIT"
            raise ContractError(msg, 413)
        content = document.model_dump(mode="json")
        content["revision"] += 1
        node_id = None
        if isinstance(args, UpsertArguments):
            node_id = args.node_id or uuid4()
            if args.node_id is not None and not any(node.node_id == node_id for node in document.nodes):
                msg = "CONTRACT_NODE_NOT_FOUND"
                raise ContractError(msg, 404)
            node = SkilltreeNode(node_id=node_id, **args.node.model_dump()).model_dump(mode="json")
            content["nodes"] = [node if item["node_id"] == str(node_id) else item for item in content["nodes"]]
            if args.node_id is None:
                content["nodes"].append(node)
        elif isinstance(args, RemoveArguments):
            if not any(node.node_id == args.node_id for node in document.nodes):
                msg = "CONTRACT_NODE_NOT_FOUND"
                raise ContractError(msg, 404)
            if any(args.node_id in {edge.source_id, edge.target_id} for edge in document.dependencies):
                msg = "CONTRACT_NODE_REFERENCED"
                raise ContractError(msg)
            content["nodes"] = [node for node in content["nodes"] if node["node_id"] != str(args.node_id)]
        elif isinstance(args, DependencyArguments):
            edge = SkilltreeDependency(source_id=args.source_id, target_id=args.target_id, relation=args.relation)
            if any(
                node_id not in {node.node_id for node in document.nodes} for node_id in (args.source_id, args.target_id)
            ):
                msg = "CONTRACT_DEPENDENCY_NODE_MISSING"
                raise ContractError(msg)
            content["dependencies"] = [item for item in content["dependencies"] if item != edge.model_dump(mode="json")]
            if args.operation == "ADD":
                content["dependencies"].append(edge.model_dump(mode="json"))
        else:
            msg = "CONTRACT_TOOL_NOT_ALLOWED"
            raise ContractError(msg, 403)
        try:
            return SkilltreeDocument.model_validate(content), node_id
        except ValidationError:
            msg = "CONTRACT_DOCUMENT_BOUNDS_INVALID"
            raise ContractError(msg, 413) from None

    # Shared SQL authoring uses the same pure six-tool reducer, without borrowing
    # an owner's filesystem transaction or changing the legacy repository API.
    edit_document = _edit

    def approve(self, command: ContractApprovalCommand, *, owner_id: str, run_id: UUID) -> ContractToolResult:
        """Called only by the authenticated human route, never by execute()/the tool bridge."""
        with self._transaction():
            head = self._head(command.reference.contract_id, owner_id, run_id)
            current = self._read(head)
            identity = self._command_identity(
                owner_id, current.binding, command.idempotency_key, "human-approve", command.model_dump(mode="json")
            )
            replay = self._replay(identity, owner_id, current.binding)
            if replay is not None:
                return replay
            if current.reference != command.reference:
                msg = "REVISION_CONFLICT"
                raise ContractError(msg)
            if current.status == "APPROVED":
                msg = "CONTRACT_LOCKED"
                raise ContractError(msg)
            report = validate_document(current.document, self._clock())
            if current.status != "VALIDATED" or not report.passed:
                msg = "CONTRACT_NOT_VALIDATED"
                raise ContractError(msg)
            approval = ContractApproval(
                approval_id=uuid4(),
                reference=current.reference,
                approved_by=owner_id,
                approved_at=self._clock(),
                comment=command.comment,
            )
            self._connection.execute(
                """UPDATE adlc_contract_revisions SET status='APPROVED', approval_json=?, validation_json=?
                   WHERE contract_id=? AND revision=?""",
                (
                    approval.model_dump_json(),
                    report.model_dump_json(),
                    str(command.reference.contract_id),
                    command.reference.revision,
                ),
            )
            result = ContractToolResult(contract=self._read(head))
            self._remember(identity, result)
            return result

    def fork(self, command: ContractForkCommand, *, owner_id: str, run_id: UUID) -> ContractToolResult:
        """Explicit human change request; preserve the approved document and all its IDs."""
        with self._transaction():
            original = self._read(self._head(command.reference.contract_id, owner_id, run_id))
            identity = self._command_identity(
                owner_id, original.binding, command.idempotency_key, "human-fork", command.model_dump(mode="json")
            )
            replay = self._replay(identity, owner_id, original.binding)
            if replay is not None:
                return replay
            if original.reference != command.reference or original.status != "APPROVED":
                msg = "CONTRACT_FORK_REQUIRES_APPROVED_REFERENCE"
                raise ContractError(msg)
            payload = original.document.model_dump(mode="json")
            payload.update(contract_id=str(uuid4()), revision=1, supersedes=command.reference.model_dump(mode="json"))
            created = self._create(
                SkilltreeDocument.model_validate(payload), owner_id, original.binding, owner_id, "HUMAN"
            )
            result = ContractToolResult(contract=created)
            self._remember(identity, result)
            return result


def create_contract_repository_from_environment() -> ContractRepository:
    configured = os.getenv("ADLC_CONTRACT_DB_PATH")
    if configured is not None and not configured.strip():
        return ContractRepository()
    default = Path(__file__).resolve().parents[2] / "data" / "adlc-contracts.sqlite3"
    return ContractRepository(configured.strip() if configured is not None else default)


@lru_cache(maxsize=1)
def get_contract_repository() -> ContractRepository:
    return create_contract_repository_from_environment()

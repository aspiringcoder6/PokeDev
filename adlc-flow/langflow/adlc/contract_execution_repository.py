"""Immutable attempt bindings and machine evidence, independent of patch expiry."""

import os
import sqlite3
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from langflow.adlc.contract_execution import compile_policy, model_digest, validate_proof
from langflow.adlc.contract_execution_models import ContractExecutionBinding, ContractExecutionProof
from langflow.adlc.contract_repository import ContractError

MAX_QUERY = 100


class ContractExecutionRepository:
    def __init__(self, path=None, *, max_records=1000, max_bytes=64 * 1024 * 1024):
        self._lock = RLock()
        self._max_records = max_records
        self._max_bytes = max_bytes
        if path is not None:
            path = Path(path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path) if path is not None else ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("""CREATE TABLE IF NOT EXISTS adlc_contract_executions (
            attempt_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, workflow_run_id TEXT NOT NULL,
            binding_json TEXT NOT NULL, binding_digest TEXT NOT NULL, proof_json TEXT, proof_digest TEXT
        )""")
        self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    def _quota(self, extra_bytes):
        used = self._db.execute(
            "SELECT COALESCE(SUM(length(CAST(binding_json AS BLOB)) + "
            "COALESCE(length(CAST(proof_json AS BLOB)), 0)), 0) FROM adlc_contract_executions"
        ).fetchone()[0]
        if used + extra_bytes > self._max_bytes:
            msg = "CONTRACT_EXECUTION_QUOTA_EXCEEDED"
            raise ContractError(msg, 413)

    def _read(self, row):
        try:
            binding = ContractExecutionBinding.model_validate_json(row["binding_json"])
            proof = ContractExecutionProof.model_validate_json(row["proof_json"]) if row["proof_json"] else None
            if (
                model_digest(binding) != row["binding_digest"]
                or str(binding.scope.attempt_id) != row["attempt_id"]
                or str(binding.scope.workflow_run_id) != row["workflow_run_id"]
                or binding.policy.contract_reference != binding.reference
                or model_digest(binding.policy) != binding.policy_digest
                or (proof is None) != (row["proof_digest"] is None)
            ):
                raise ValueError
            if proof:
                validate_proof(binding.policy, proof)
                if model_digest(proof) != row["proof_digest"]:
                    raise ValueError
        except (ValidationError, ValueError, ContractError):
            msg = "CONTRACT_EXECUTION_STORE_INVALID"
            raise ContractError(msg, 503) from None
        else:
            return binding, proof

    @contextmanager
    def _transaction(self):
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield
                self._db.commit()
            except sqlite3.Error:
                with suppress(sqlite3.Error):
                    self._db.rollback()
                msg = "CONTRACT_EXECUTION_STORE_UNAVAILABLE"
                raise ContractError(msg, 503) from None
            except Exception:
                self._db.rollback()
                raise

    def bind(self, *, owner_id, scope, execution_plan_id, resolved_node_digest, contract, policy):
        if policy != compile_policy(contract) or not owner_id:
            msg = "CONTRACT_EXECUTION_BINDING_MISMATCH"
            raise ContractError(msg)
        binding = ContractExecutionBinding(
            scope=scope,
            execution_plan_id=execution_plan_id,
            resolved_node_digest=resolved_node_digest,
            reference=contract.reference,
            policy=policy,
            policy_digest=model_digest(policy),
            bound_at=datetime.now(timezone.utc),
        )
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM adlc_contract_executions WHERE attempt_id=?", (str(scope.attempt_id),)
            ).fetchone()
            if row:
                current, proof = self._read(row)
                expected = binding.model_copy(update={"bound_at": current.bound_at})
                if row["owner_id"] != owner_id or current != expected:
                    msg = "CONTRACT_EXECUTION_BINDING_MISMATCH"
                    raise ContractError(msg)
                return current, proof
            if self._db.execute("SELECT COUNT(*) FROM adlc_contract_executions").fetchone()[0] >= self._max_records:
                msg = "CONTRACT_EXECUTION_QUOTA_EXCEEDED"
                raise ContractError(msg, 413)
            self._quota(len(binding.model_dump_json().encode()))
            self._db.execute(
                "INSERT INTO adlc_contract_executions VALUES (?,?,?,?,?,NULL,NULL)",
                (
                    str(scope.attempt_id),
                    owner_id,
                    str(scope.workflow_run_id),
                    binding.model_dump_json(),
                    model_digest(binding),
                ),
            )
            return binding, None

    def report(self, *, owner_id, binding, proof):
        validate_proof(binding.policy, proof)
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM adlc_contract_executions WHERE attempt_id=? AND owner_id=?",
                (str(binding.scope.attempt_id), owner_id),
            ).fetchone()
            if row is None:
                msg = "CONTRACT_EXECUTION_NOT_FOUND"
                raise ContractError(msg, 404)
            current, existing = self._read(row)
            if current != binding or (existing is not None and existing != proof):
                msg = "CONTRACT_EXECUTION_EVIDENCE_CONFLICT"
                raise ContractError(msg)
            if existing is None:
                self._quota(len(proof.model_dump_json().encode()))
                self._db.execute(
                    "UPDATE adlc_contract_executions SET proof_json=?, proof_digest=? WHERE attempt_id=?",
                    (proof.model_dump_json(), model_digest(proof), str(binding.scope.attempt_id)),
                )
            return proof

    def list_for_run(self, run_id, *, owner_id, limit=50, offset=0):
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= MAX_QUERY or offset < 0:
            msg = "CONTRACT_QUERY_INVALID"
            raise ContractError(msg, 422)
        with self._transaction():
            return [
                self._read(row)
                for row in self._db.execute(
                    "SELECT * FROM adlc_contract_executions WHERE owner_id=? AND workflow_run_id=? "
                    "ORDER BY attempt_id LIMIT ? OFFSET ?",
                    (owner_id, str(run_id), limit, offset),
                ).fetchall()
            ]

    def get_by_attempt(self, attempt_id, *, owner_id):
        with self._transaction():
            row = self._db.execute(
                "SELECT * FROM adlc_contract_executions WHERE owner_id=? AND attempt_id=?", (owner_id, str(attempt_id))
            ).fetchone()
            return self._read(row) if row else None


@lru_cache(maxsize=1)
def get_contract_execution_repository():
    configured = os.getenv("ADLC_CONTRACT_EXECUTION_DB_PATH")
    path = (
        None
        if configured is not None and not configured.strip()
        else (configured or Path(__file__).resolve().parents[2] / "data/adlc-contract-executions.sqlite3")
    )
    return ContractExecutionRepository(path)

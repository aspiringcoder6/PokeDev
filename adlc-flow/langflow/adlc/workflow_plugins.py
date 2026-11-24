"""Owner-bound workflow plugin executions, retained independently of verification verdicts."""

# ruff: noqa: EM101, PLR2004, TRY300 - stable public codes, bounded archive limits, guarded returns.

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import Field

from langflow.adlc.models import ServiceError, TaskMetrics, TaskResult, TaskResultStatus, TaskRunStatus
from langflow.adlc.workflow_plugin_client import (
    Closed,
    MemoryConnection,
    PluginError,
    ReplayConnection,
    WorkflowPluginClient,
)

SERVICE = "integration:workflow-plugins"
VERSION = "0.1.0"
PACKAGES = {
    "HEALTH": "workflow-plugin-check",
    "MEMORY_CONTEXT": "agent-memory-context",
    "TESTFORGE_REPLAY": "testforge-replay",
}
REFERENCES = frozenset(
    {
        SERVICE,
        "model:workflow-plugins/no-model",
        "prompt:workflow-plugins/0.1.0",
        "rules:workflow-plugins-bound-scope/0.1.0",
        "memory:workflow-plugins/advisory",
        "sandbox:workflow-plugins/remote-bound",
        "plugin:vai_agentmemory/1.0.0",
        "plugin:vai_testforge/1.0.0",
    }
)


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def enabled():
    return os.getenv("ADLC_WORKFLOW_PLUGINS_ENABLED", "").lower() == "true"


class ConnectionBinding(Closed):
    owner_id: UUID
    flow_id: UUID
    connection: str = Field(default="project", pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    memory: MemoryConnection | None = None
    replay: ReplayConnection | None = None

    def public(self):
        return {
            "connection": self.connection,
            "memory_configured": self.memory is not None,
            "replay_configured": self.replay is not None,
            "memory_dataset": self.memory.dataset if self.memory else None,
            "replay_session": self.replay.session if self.replay else None,
            "replay_target": self.replay.api_url if self.replay else None,
        }

    def digest(self):
        # Secret values participate in pinning, but are never returned or retained.
        value = self.model_dump(mode="json")
        for key in ("memory", "replay"):
            if value[key] is not None:
                value[key]["token"] = getattr(self, key).token.get_secret_value()
        return fingerprint(value)


class ConnectionRegistry(Closed):
    schema_version: str = Field(pattern=r"^0\.1$")
    bindings: list[ConnectionBinding] = Field(max_length=100)


def bindings(owner, flow_id):
    filename = os.getenv("ADLC_WORKFLOW_PLUGIN_REGISTRY", "")
    if not filename:
        return []
    try:
        path = Path(filename)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size > 131072:
            raise ValueError
        registry = ConnectionRegistry.model_validate_json(path.read_bytes())
        keys = [(item.owner_id, item.flow_id, item.connection) for item in registry.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError
        dataset_owners = {}
        for item in registry.bindings:
            if item.memory:
                scope = (item.memory.url, item.memory.tenant_id, item.memory.dataset)
                if scope in dataset_owners and dataset_owners[scope] != item.owner_id:
                    raise ValueError
                dataset_owners[scope] = item.owner_id
        return [
            item
            for item in registry.bindings
            if str(item.owner_id) == str(owner) and item.flow_id == UUID(str(flow_id))
        ]
    except (OSError, ValueError, RecursionError):
        raise PluginError("WORKFLOW_PLUGIN_REGISTRY_INVALID", 503) from None


class PluginLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS workflow_plugin_calls
                (id TEXT PRIMARY KEY,owner TEXT NOT NULL,run_id TEXT NOT NULL,
                 request_digest TEXT NOT NULL,payload TEXT NOT NULL,result TEXT)""")

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def begin(self, *, call_id, owner, run_id, flow_id, task_id, operation, request_digest, connection_digest):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT owner,request_digest,payload,result FROM workflow_plugin_calls WHERE id=?", (str(call_id),)
            ).fetchone()
            if existing:
                if existing[0] != str(owner) or existing[1] != request_digest:
                    raise PluginError("WORKFLOW_PLUGIN_CALL_CONFLICT")
                return (
                    json.loads(existing[2]),
                    TaskResult.model_validate_json(existing[3]) if existing[3] else None,
                    False,
                )
            if operation == "TESTFORGE_REPLAY" and task_id:
                previous = db.execute(
                    "SELECT payload FROM workflow_plugin_calls WHERE owner=? AND run_id=?", (str(owner), str(run_id))
                ).fetchall()
                for row in previous:
                    item = json.loads(row[0])
                    if (
                        item.get("task_id") == str(task_id)
                        and item["operation"] == operation
                        and item["state"] in {"DISPATCHING", "RUNNING", "UNKNOWN", "CANCEL_REQUESTED"}
                    ):
                        raise PluginError("WORKFLOW_PLUGIN_PREVIOUS_JOB_UNCONFIRMED")
            record = {
                "id": str(call_id),
                "run_id": str(run_id),
                "flow_id": str(flow_id),
                "task_id": str(task_id) if task_id else None,
                "operation": operation,
                "state": "DISPATCHING",
                "created_at": now(),
                "updated_at": now(),
                "connection_digest": connection_digest,
                "data": None,
                "error_code": None,
                "authority": "ADVISORY_UNTRUSTED",
                "verification_evidence": False,
            }
            db.execute(
                "INSERT INTO workflow_plugin_calls VALUES (?,?,?,?,?,NULL)",
                (str(call_id), str(owner), str(run_id), request_digest, json.dumps(record)),
            )
        return record, None, True

    def save(self, record, *, result=None):
        record["updated_at"] = now()
        encoded = json.dumps(record)
        if len(encoded.encode()) > 524288:
            raise PluginError("WORKFLOW_PLUGIN_HISTORY_LIMIT")
        with self.db() as db:
            db.execute(
                "UPDATE workflow_plugin_calls SET payload=?,result=COALESCE(?,result) WHERE id=? AND result IS NULL",
                (encoded, result.model_dump_json() if result else None, record["id"]),
            )
        return record

    def get(self, call_id, *, owner, run_id, request_digest=None):
        with self.db() as db:
            row = db.execute(
                "SELECT payload,result,request_digest FROM workflow_plugin_calls WHERE id=? AND owner=? AND run_id=?",
                (str(call_id), str(owner), str(run_id)),
            ).fetchone()
        if not row:
            raise PluginError("WORKFLOW_PLUGIN_NOT_FOUND", 404)
        if request_digest is not None and row[2] != request_digest:
            raise PluginError("WORKFLOW_PLUGIN_CALL_CONFLICT")
        return json.loads(row[0]), TaskResult.model_validate_json(row[1]) if row[1] else None

    def list(self, *, owner, run_id):
        with self.db() as db:
            rows = db.execute(
                "SELECT payload FROM workflow_plugin_calls WHERE owner=? AND run_id=? ORDER BY rowid DESC LIMIT 100",
                (str(owner), str(run_id)),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]


class WorkflowPluginService:
    def __init__(self, ledger, *, client=None):
        self.ledger, self.client = ledger, client or WorkflowPluginClient()
        self.locks = {}

    def lock(self, call_id):
        return self.locks.setdefault(str(call_id), asyncio.Lock())

    def connection(self, owner, flow_id, key, operation):
        if operation == "HEALTH":
            return None
        connection = next((item for item in bindings(owner, flow_id) if item.connection == key), None)
        if (
            not connection
            or (operation == "MEMORY_CONTEXT" and not connection.memory)
            or (operation == "TESTFORGE_REPLAY" and not connection.replay)
        ):
            raise PluginError("WORKFLOW_PLUGIN_PROJECT_NOT_CONFIGURED", 503)
        return connection

    async def perform(self, record, connection, configuration, *, fresh):
        if record["state"] in {"SUCCEEDED", "FAILED", "UNKNOWN", "CANCEL_REQUESTED"}:
            return record
        try:
            if record["operation"] == "TESTFORGE_REPLAY":
                if fresh:
                    # Durable local intent exists before the only create request.
                    job_id = await self.client.replay(connection.replay)
                    record.update(state="RUNNING", job_id=job_id)
                    self.ledger.save(record)
                elif not record.get("job_id"):
                    raise PluginError("WORKFLOW_PLUGIN_DISPATCH_UNCONFIRMED")
                deadline = asyncio.get_running_loop().time() + connection.replay.job_timeout_seconds + 30
                while True:
                    result = await self.client.job(connection.replay, record["job_id"])
                    record["data"] = result
                    self.ledger.save(record)
                    if result["status"] in {"completed", "failed"}:
                        exit_code = result.get("exit_code", result.get("returncode"))
                        record["state"] = (
                            "SUCCEEDED" if result["status"] == "completed" and exit_code in {None, 0} else "FAILED"
                        )
                        record["backend_job_status"] = result["status"]
                        record["verification_verdict"] = "NOT_ATTESTED"
                        break
                    if asyncio.get_running_loop().time() >= deadline:
                        raise PluginError("WORKFLOW_PLUGIN_JOB_STILL_RUNNING")
                    await asyncio.sleep(2)
            elif record["operation"] == "MEMORY_CONTEXT":
                if not fresh:
                    raise PluginError("WORKFLOW_PLUGIN_READ_INTERRUPTED")
                query = configuration.get("query", "")
                if not isinstance(query, str) or not 1 <= len(query.strip()) <= 4096:
                    raise PluginError("WORKFLOW_PLUGIN_QUERY_REQUIRED", 422)
                record["data"] = await self.client.memory(
                    connection.memory, query=query, top_k=configuration.get("top_k", 5)
                )
                record["state"] = "SUCCEEDED"
            else:
                if not fresh:
                    raise PluginError("WORKFLOW_PLUGIN_READ_INTERRUPTED")
                record["data"] = await self.client.health()
                record["state"] = (
                    "SUCCEEDED" if all(item["status"] == "ok" for item in record["data"].values()) else "FAILED"
                )
        except asyncio.CancelledError:
            record.update(state="CANCEL_REQUESTED", error_code="WORKFLOW_PLUGIN_CANCELLED_LOCALLY")
            self.ledger.save(record)
            # The broker has no cancel API. Never claim an external job stopped.
            raise
        except PluginError as exc:
            record.update(
                error_code=exc.code,
                state="UNKNOWN"
                if record["operation"] == "TESTFORGE_REPLAY"
                and (record.get("job_id") or exc.code != "WORKFLOW_PLUGIN_AUTH_REQUIRED")
                else "FAILED",
            )
        return self.ledger.save(record)


@lru_cache(maxsize=1)
def get_plugin_service():
    default = Path(__file__).resolve().parents[2] / "data/workflow-plugins"
    root = Path(os.getenv("ADLC_WORKFLOW_PLUGIN_STATE_ROOT", str(default)))
    return WorkflowPluginService(PluginLedger(root / "calls.sqlite3"))


class WorkflowPluginExecutor:
    service_name = SERVICE
    capabilities = ("workflow-plugin-nodes", "scoped-memory-context", "testforge-replay")

    def __init__(self, service=None):
        self.service = service or get_plugin_service()
        self.authorize = None

    def bind_plugin_workflow_authority(self, authorize):
        self.authorize = authorize

    def parse(self, request):
        operation = request.executor.operation
        trace = request.metadata.get("plan_traceability", {})
        if (
            not self.authorize
            or request.executor.service != SERVICE
            or operation not in PACKAGES
            or trace.get("package_id") != PACKAGES.get(operation)
            or trace.get("package_version") != VERSION
            or request.constraints.get("max_attempts") != 1
        ):
            raise PluginError("WORKFLOW_PLUGIN_REQUEST_INVALID")
        authority = self.authorize(request)
        return operation, authority

    def configure(self, request, authority, operation):
        if not enabled():
            raise PluginError("WORKFLOW_PLUGINS_DISABLED")
        configuration = request.metadata.get("resolved_configuration", {})
        connection = self.service.connection(
            authority["owner_id"], authority["flow_id"], configuration.get("connection", "project"), operation
        )
        return configuration, connection

    def task_result(self, request, record, started):
        success = record["state"] == "SUCCEEDED"
        data = record.get("data") or {}
        outputs = {"plugin_result": record}
        if record["operation"] == "MEMORY_CONTEXT":
            outputs["context"] = data
        else:
            outputs["report"] = data
        completed = datetime.now(timezone.utc)
        return TaskResult(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            status=TaskResultStatus.SUCCEEDED if success else TaskResultStatus.FAILED,
            output={"outputs": outputs},
            artifacts=[],
            error=None
            if success
            else ServiceError(
                error_id=uuid4(),
                code=record.get("error_code") or "WORKFLOW_PLUGIN_JOB_FAILED",
                category="DEPENDENCY",
                retryable=False,
                service=SERVICE,
                message="Không hoàn tất thao tác plugin; xem kết quả được lưu trong workflow.",
                occurred_at=completed,
            ),
            metrics=TaskMetrics(duration_ms=max(0, int((completed - started).total_seconds() * 1000))),
            started_at=started,
            completed_at=completed,
            metadata={
                "workflow_plugin": {
                    "operation": record["operation"],
                    "record_id": record["id"],
                    "verification_evidence": False,
                }
            },
        )

    async def execute(self, request, on_state_change):
        async with self.service.lock(request.attempt_id):
            return await self._execute(request, on_state_change)

    async def _execute(self, request, on_state_change):
        started = datetime.now(timezone.utc)
        await on_state_change(TaskRunStatus.RUNNING, None)
        record = None
        try:
            operation, authority = self.parse(request)
            try:
                _, saved = self.service.ledger.get(
                    request.attempt_id,
                    owner=authority["owner_id"],
                    run_id=request.workflow_run_id,
                    request_digest=fingerprint(request.model_dump(mode="json")),
                )
            except PluginError as exc:
                if exc.status != 404:
                    raise
                saved = None
            if saved:
                await on_state_change(TaskRunStatus(saved.status.value), saved)
                return saved
            configuration, connection = self.configure(request, authority, operation)
            record, saved, fresh = self.service.ledger.begin(
                call_id=request.attempt_id,
                owner=authority["owner_id"],
                run_id=request.workflow_run_id,
                flow_id=authority["flow_id"],
                task_id=request.task_run_id,
                operation=operation,
                request_digest=fingerprint(request.model_dump(mode="json")),
                connection_digest=connection.digest() if connection else None,
            )
            if saved:
                await on_state_change(TaskRunStatus(saved.status.value), saved)
                return saved
            if connection and record["connection_digest"] != connection.digest():
                raise PluginError("WORKFLOW_PLUGIN_CONNECTION_CHANGED")
            record = await self.service.perform(record, connection, configuration, fresh=fresh)
        except PluginError as exc:
            record = record or {
                "id": str(request.attempt_id),
                "operation": request.executor.operation,
                "data": None,
                "verification_evidence": False,
            }
            record.update(state="FAILED", error_code=exc.code)
        result = self.task_result(request, record, started)
        if "run_id" in record:
            self.service.ledger.save(record, result=result)
        await on_state_change(TaskRunStatus(result.status.value), result)
        return result

    async def get_saved_result(self, request):
        _, authority = self.parse(request)
        try:
            _, result = self.service.ledger.get(
                request.attempt_id,
                owner=authority["owner_id"],
                run_id=request.workflow_run_id,
                request_digest=fingerprint(request.model_dump(mode="json")),
            )
            return result
        except PluginError as exc:
            if exc.status == 404:
                return None
            raise

    async def resume(self, request, on_state_change):
        # execute reuses the persisted command: only GET polling may continue for
        # a known job; memory/health reads and uncertain creates are never replayed.
        return await self.execute(request, on_state_change)

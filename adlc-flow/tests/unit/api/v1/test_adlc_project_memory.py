"""H6C owner/current-attempt API, passive projection and no authority mutation."""

# ruff: noqa: S101, S105, SLF001, PLR2004, EM101
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from langflow.adlc.contract_bridge import sign_contract_command
from langflow.adlc.models import PlanTaskTraceability, TaskRunStatus, WorkflowExecutionMode
from langflow.adlc.project_memory_client import MemoryClients
from langflow.adlc.project_memory_models import MEMORY_DOMAIN, ProjectMemoryError
from langflow.adlc.project_memory_repository import MemoryRepository
from langflow.api.v1 import adlc_project_memory as api
from langflow.api.v1 import adlc_verification as previous_api
from tests.unit.adlc.test_project_memory import GatewayFixture, config
from tests.unit.api.v1 import test_adlc_contracts as contracts

api_fixture = contracts.api_fixture
SECRET = "isolated-memory-tool-key-32-bytes-at-least"


@pytest.fixture
async def memory_fixture(api_fixture, tmp_path, monkeypatch):
    f = api_fixture
    monkeypatch.setenv("ADLC_MEMORY_ENABLED", "true")
    monkeypatch.setenv("ADLC_MEMORY_TOOL_SECRET", SECRET)
    await contracts.authoring_session(f, session="memory-session")
    run = f.service._runs[f.run.id].run
    run.execution_mode = WorkflowExecutionMode.EXECUTION_PLAN
    run.execution_plan_id = uuid4()
    task = run.tasks[0]
    f.config = config(owner=f.user.id)
    task.request.context = {
        "adlc_local_project": {
            "project_id": str(f.config.project_id),
            "base_commit": "a" * 40,
            "source_ref": f"{f.config.project_id}/" + "a" * 40,
        }
    }
    task.plan_traceability = PlanTaskTraceability(
        execution_plan_id=run.execution_plan_id,
        plan_task_id=uuid4(),
        source_workflow_stage_id=uuid4(),
        resolved_node_spec_id=uuid4(),
        package_id="fixture",
        package_version="0.1.0",
        package_content_digest="sha256:" + "b" * 64,
        resolved_node_digest="sha256:" + "c" * 64,
    )

    def route(owner, project):
        if owner != str(f.user.id) or project != f.config.project_id:
            raise ProjectMemoryError("MEMORY_GATEWAY_NOT_CONFIGURED", 503)
        return f.config

    monkeypatch.setattr(api, "load_binding", route)
    f.gateway = GatewayFixture([f.config], sse=True)

    class Pool(MemoryClients):
        def get(self, binding):
            client = super().get(binding)
            client.transport = httpx.MockTransport(f.gateway.handle)
            return client

    f.store = MemoryRepository(tmp_path / "memory.sqlite3")
    f.pool = Pool()
    f.app.include_router(api.router, prefix="/api/v1")
    f.app.dependency_overrides[api.get_memory_repository] = lambda: f.store
    f.app.dependency_overrides[api.get_memory_clients] = lambda: f.pool
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: f.user
    f.root = f"/api/v1/adlc/runs/{run.id}/project-memory"
    f.command = {"query": "Earlier decision?", "top_k": 5, "idempotency_key": "first-read"}
    yield f
    f.store.close()


def sign(body, *, domain=MEMORY_DOMAIN, timestamp=None):
    payload = json.dumps(body, separators=(",", ":")).encode()
    timestamp = timestamp or str(int(time.time()))
    return payload, {
        "Content-Type": "application/json",
        "X-ADLC-Memory-Timestamp": timestamp,
        "X-ADLC-Memory-Signature": sign_contract_command(SECRET, timestamp, payload, domain=domain),
    }


async def agent(f, operation="context", **changes):
    body = {
        "session_id": "memory-session",
        "operation": operation,
        "arguments": f.command if operation == "context" else None,
        **changes,
    }
    payload, headers = sign(body)
    return await f.client.post("/api/v1/adlc/project-memory-tools", content=payload, headers=headers)


async def test_passive_view_no_gateway_calls_and_explicit_read_retains_only_context(memory_fixture):
    f = memory_fixture
    before = (await f.service.get_run(f.run.id, owner_id=str(f.user.id))).model_dump(mode="json")
    view = await f.client.get(f.root)
    assert view.status_code == 200
    assert view.json()["capabilities"]["configured"] is True
    assert view.headers["cache-control"] == "no-store"
    assert f.gateway.events == []
    response = await f.client.post(f.root + "/context", json=f.command)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["record"]["authority"] == "ADVISORY_UNTRUSTED"
    assert row["record"]["verification_evidence"] is False
    assert row["record"]["chunks"][0]["revision"] == "r2"
    count = len(f.gateway.events)
    assert (await f.client.post(f.root + "/context", json=f.command)).json() == row
    assert len(f.gateway.events) == count
    assert (await f.client.get("/api/v1/adlc/harness-sessions/memory-session/project-memory")).json()["records"] == [
        row
    ]
    after = (await f.service.get_run(f.run.id, owner_id=str(f.user.id))).model_dump(mode="json")
    assert after == before  # No task/event/plan/contract/callback/Verify mutation.


async def test_two_owners_cannot_read_query_status_write_or_delete_cross_scope(memory_fixture):
    f = memory_fixture
    await f.client.post(f.root + "/context", json=f.command)
    other = SimpleNamespace(id=uuid4())
    f.app.dependency_overrides[contracts.get_current_active_user] = lambda: other
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: other
    before = len(f.gateway.events)
    assert (await f.client.get(f.root)).status_code == 404
    assert (await f.client.get("/api/v1/adlc/harness-sessions/memory-session/project-memory")).status_code == 404
    assert (await f.client.post(f.root + "/context", json={**f.command, "idempotency_key": "other"})).status_code == 404
    assert (await f.client.post(f.root + "/status")).status_code == 404
    for op in ["remember", "forget", "ask"]:
        assert (await f.client.post(f.root + "/" + op, json={"confirm": True})).status_code == 403
    assert len(f.gateway.events) == before


async def test_arbitrary_tenant_dataset_urls_and_boolean_permission_are_not_inputs(memory_fixture):
    f = memory_fixture
    for bad in ["tenant_id", "dataset", "url", "confirm", "owner_id", "models"]:
        assert (await f.client.post(f.root + "/context", json={**f.command, bad: "anything"})).status_code == 422
    assert (await f.client.post(f.root + "/status", json={"dataset": "another"})).status_code == 422
    assert (await agent(f, arguments={**f.command, "tenant_id": "other"})).status_code == 422
    assert (await agent(f, "forget")).status_code == 422
    assert f.gateway.events == []


async def test_signed_active_attempt_and_exact_session_projection(memory_fixture):
    f = memory_fixture
    response = await agent(f)
    assert response.status_code == 200, response.text
    assert response.json()["binding"]["source_session_id"] == "memory-session"
    row = response.json()["result"]
    native = await f.client.get("/api/v1/adlc/harness-sessions/memory-session/project-memory")
    assert native.json()["records"] == [row]
    assert (await f.client.get("/api/v1/adlc/harness-sessions/unknown/project-memory")).status_code == 404
    task = f.service._runs[f.run.id].run.tasks[0]
    task.current_attempt_id = uuid4()
    assert (await agent(f, arguments={**f.command, "idempotency_key": "new"})).status_code == 403
    # Old-session archives remain readable despite the new current attempt.
    assert (await f.client.get("/api/v1/adlc/harness-sessions/memory-session/project-memory")).json()["records"] == [
        row
    ]


async def test_signed_bridge_has_separate_purpose_expiry_and_terminal_guards(memory_fixture):
    f = memory_fixture
    body = {"session_id": "memory-session", "operation": "health", "arguments": None}
    for domain, timestamp in [(b"adlc-contract-tools-v1\n", None), (MEMORY_DOMAIN, "1")]:
        payload, headers = sign(body, domain=domain, timestamp=timestamp)
        assert (
            await f.client.post("/api/v1/adlc/project-memory-tools", content=payload, headers=headers)
        ).status_code == 401
    assert (await f.client.post("/api/v1/adlc/project-memory-tools", json=body)).status_code == 401
    f.service._runs[f.run.id].run.tasks[0].status = TaskRunStatus.SUCCEEDED
    assert (await agent(f, "health")).status_code == 403
    assert f.gateway.events == []


async def test_outage_disabled_mode_and_stale_text_never_hide_official_results(memory_fixture, monkeypatch):
    f = memory_fixture
    f.gateway.content = f.gateway.content.model_copy(update={"source_commit": "b" * 40})
    first = await f.client.post(f.root + "/context", json=f.command)
    assert first.status_code == 200  # Stale text may be context; never expected values/evidence.
    row = first.json()

    async def offline(_):
        return httpx.Response(503)

    f.gateway.handle = offline
    failed = await f.client.post(f.root + "/context", json={**f.command, "idempotency_key": "offline-read"})
    assert failed.status_code == 503
    assert (await f.client.get(f.root)).json()["records"] == [row]
    assert (await f.client.post(f.root + "/context", json=f.command)).json() == row
    monkeypatch.setenv("ADLC_MEMORY_ENABLED", "false")
    assert (await f.client.get(f.root)).json()["records"] == [row]
    assert (await f.client.post(f.root + "/context", json=f.command)).status_code == 409


async def test_explicit_owner_queries_required_but_archives_remain_readable(memory_fixture):
    f = memory_fixture

    def denied():
        raise HTTPException(401, {"code": "CONTRACT_EXPLICIT_LOGIN_REQUIRED"})

    f.app.dependency_overrides[previous_api.explicit_owner] = denied
    assert (await f.client.post(f.root + "/context", json=f.command)).status_code == 401
    assert (await f.client.post(f.root + "/health")).status_code == 401
    assert (await f.client.get(f.root)).status_code == 200
    assert f.gateway.events == []


async def test_unpinned_legacy_or_conflicting_project_scope_is_blocked(memory_fixture):
    f = memory_fixture
    f.service._runs[f.run.id].run.execution_mode = WorkflowExecutionMode.LEGACY_FLOW
    assert (await f.client.post(f.root + "/context", json=f.command)).status_code == 409
    assert (await f.client.get(f.root)).json()["binding"] is None
    assert f.gateway.events == []


async def test_request_byte_limit_precedes_context_dispatch(memory_fixture):
    f = memory_fixture
    for path in [f.root + "/context", "/api/v1/adlc/project-memory-tools"]:
        response = await f.client.post(path, content=b" " * 8193, headers={"Content-Type": "application/json"})
        assert response.status_code == 413
    assert f.gateway.events == []

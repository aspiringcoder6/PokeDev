"""H5A human/API boundaries; no Docker, credentials or model calls are required."""

# ruff: noqa: S101, S105, SLF001, PLR2004
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from langflow.adlc.contract_bridge import AUTHORING_READ_DOMAIN, sign_contract_command
from langflow.adlc.contract_models import ContractScope
from langflow.adlc.contract_repository import ContractRepository
from langflow.adlc.harness_attempts import InMemoryTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.models import CreateWorkflowRunRequest, ExecutorTarget, TaskRequest, TaskRunStatus, WorkflowRunStatus
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.api.v1 import adlc_contracts as contract_api
from langflow.services.auth.utils import get_current_active_user

SECRET = "isolated-tool-bridge-secret-at-least-32-bytes"


@pytest.fixture
async def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("ADLC_CONTRACTS_ENABLED", "true")
    monkeypatch.setenv("ADLC_CONTRACT_TOOL_SECRET", SECRET)
    user = SimpleNamespace(id=uuid4(), username="owner")
    flow = SimpleNamespace(
        id=uuid4(),
        name="Contract fixture",
        user_id=None,
        workspace_id=None,
        folder_id=None,
        data={"nodes": [{"id": "plan", "type": "genericNode", "data": {"type": "Plan"}}], "edges": []},
    )
    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", AsyncMock(return_value=flow))
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", AsyncMock())
    service = AdlcRunService()
    run = await adlc_api.create_adlc_run(
        CreateWorkflowRunRequest(flowId=flow.id, executionMode="LEGACY_FLOW", delayMs=0),
        current_user=user,
        session=SimpleNamespace(commit=AsyncMock()),
        service=service,
    )
    repository = ContractRepository(tmp_path / "contracts.sqlite3")
    callbacks = HarnessCallbackReceiver(attempts=InMemoryTaskAttemptRepository())
    app = FastAPI()
    app.include_router(contract_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[contract_api.get_contract_approver] = lambda: user
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[adlc_api.get_harness_callback_receiver] = lambda: callbacks
    app.dependency_overrides[contract_api.get_contract_repository] = lambda: repository
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            user=user,
            run=run,
            task=run.tasks[0],
            repository=repository,
            service=service,
            callbacks=callbacks,
        )
    repository.close()
    await service.shutdown()


async def human_call(fixture, tool, arguments):
    return await fixture.client.post(
        f"/api/v1/adlc/runs/{fixture.run.id}/tasks/{fixture.task.id}/contract-tools",
        json={"tool": tool, "arguments": arguments},
    )


async def make_checked(fixture):
    created = await human_call(
        fixture,
        "skilltree_init",
        {"idempotency_key": "init", "title": "Roadmap", "scope": {"objective": "Ship a bounded slice"}},
    )
    assert created.status_code == 200
    contract = created.json()["contract"]
    added = await human_call(
        fixture,
        "skilltree_upsert_node",
        {
            "contract_id": contract["document"]["contract_id"],
            "expected_revision": 1,
            "idempotency_key": "task",
            "node": {
                "title": "Build the slice",
                "acceptance_criteria": [{"description": "Human approves the evidence"}],
            },
        },
    )
    assert added.status_code == 200
    checked = await human_call(
        fixture,
        "skilltree_validate",
        {"contract_id": contract["document"]["contract_id"], "expected_revision": 2, "idempotency_key": "validate"},
    )
    assert checked.status_code == 200
    return checked.json()["contract"]


def signed(body, *, domain=None):
    payload = json.dumps(body, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    return payload, {
        "content-type": "application/json",
        "X-ADLC-Contract-Timestamp": timestamp,
        "X-ADLC-Contract-Signature": sign_contract_command(
            SECRET, timestamp, payload, **({"domain": domain} if domain else {})
        ),
    }


async def authoring_session(fixture, session="h5a-session", profile="harness-profile:adlc-skilltree/0.1.0"):
    task = fixture.service._runs[fixture.run.id].run.tasks[0]
    fixture.service._runs[fixture.run.id].run.status = WorkflowRunStatus.RUNNING
    request = TaskRequest(
        request_id=uuid4(),
        workflow_run_id=fixture.run.id,
        task_run_id=task.id,
        attempt_id=uuid4(),
        task_definition_id=task.task_definition_id,
        task_type="planning",
        name="Authoring",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="skilltree-authoring"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=str(uuid4()),
        requested_at=datetime.now(timezone.utc),
        metadata={
            "resolved_configuration": {
                "harness_profile_ref": profile,
                "plugin_lock": [
                    {
                        "plugin_id": "vai-adlc-skilltree",
                        "version": "0.1.0",
                        "required": True,
                        "content_digest": "sha256:" + "a" * 64,
                    }
                ],
            }
        },
    )
    task.request = request
    task.current_attempt_id = request.attempt_id
    task.status = TaskRunStatus.RUNNING
    await fixture.callbacks.register_attempt(request)
    await fixture.callbacks.bind_session(request.attempt_id, session)
    await fixture.callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.RUNNING)
    return request


def session_draft(fixture, request, session, key="init"):
    scope = ContractScope(
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        request_id=request.request_id,
        attempt_id=request.attempt_id,
        session_id=session,
    )
    result = fixture.repository.execute(
        "skilltree_init",
        {
            "idempotency_key": key,
            "title": "Session roadmap",
            "scope": {"objective": "Review in either host"},
        },
        owner_id=str(fixture.user.id),
        scope=scope,
        actor_id="harness-session:" + session,
        authored_via="HARNESS_TOOL",
    )
    return result.contract


def validate_session_draft(fixture, contract):
    result = fixture.repository.execute(
        "skilltree_upsert_node",
        {
            "contract_id": str(contract.reference.contract_id),
            "expected_revision": 1,
            "idempotency_key": "task",
            "node": {
                "title": "Implement bounded work",
                "acceptance_criteria": [{"description": "Human reviews evidence"}],
            },
        },
        owner_id=str(fixture.user.id),
        scope=contract.binding,
        actor_id="tool",
        authored_via="HARNESS_TOOL",
    )
    return fixture.repository.execute(
        "skilltree_validate",
        {
            "contract_id": str(contract.reference.contract_id),
            "expected_revision": result.contract.reference.revision,
            "idempotency_key": "validate",
        },
        owner_id=str(fixture.user.id),
        scope=contract.binding,
        actor_id="tool",
        authored_via="HARNESS_TOOL",
    ).contract


async def test_h5b_session_viewer_is_exact_owner_scoped_and_survives_completion(api_fixture):
    fixture = api_fixture
    request = await authoring_session(fixture, session="viewer-session")
    contract = session_draft(fixture, request, "viewer-session")
    await make_checked(fixture)  # same owner's human contract, not this session
    url = "/api/v1/adlc/harness-sessions/viewer-session/contracts"
    response = await fixture.client.get(url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [item["reference"]["contract_id"] for item in response.json()] == [str(contract.reference.contract_id)]
    await fixture.callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.FAILED)
    assert (await fixture.client.get(url)).json() == response.json()
    fixture.app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
    denied = await fixture.client.get(url)
    unknown = await fixture.client.get("/api/v1/adlc/harness-sessions/not-a-session/contracts")
    assert denied.status_code == unknown.status_code == 404
    assert denied.json() == unknown.json()


async def test_h5b_result_selection_is_signed_read_only_validated_and_unambiguous(api_fixture):
    fixture = api_fixture
    request = await authoring_session(fixture, session="result-session")
    body = {"operation": "read-authoring-result", "session_id": "result-session"}
    url = "/api/v1/adlc/contract-authoring-result"
    raw, headers = signed(body)  # six-tool domain must not authenticate a final-result read
    assert (await fixture.client.post(url, content=raw, headers=headers)).status_code == 401
    raw, headers = signed(body, domain=AUTHORING_READ_DOMAIN)
    assert (await fixture.client.post(url, content=raw, headers=headers)).json()["detail"][
        "code"
    ] == "CONTRACT_AUTHORING_RESULT_AMBIGUOUS"
    draft = session_draft(fixture, request, "result-session")
    assert (await fixture.client.post(url, content=raw, headers=headers)).json()["detail"][
        "code"
    ] == "CONTRACT_NOT_VALIDATED"
    checked = validate_session_draft(fixture, draft)
    response = await fixture.client.post(url, content=raw, headers=headers)
    assert response.status_code == 200
    assert response.json()["contract"]["reference"] == checked.reference.model_dump(
        mode="json"
    )
    assert response.json()["contract"]["status"] == "VALIDATED"
    assert response.json()["contract"]["approval"] is None
    session_draft(fixture, request, "result-session", "second-draft")
    assert (await fixture.client.post(url, content=raw, headers=headers)).json()["detail"][
        "code"
    ] == "CONTRACT_AUTHORING_RESULT_AMBIGUOUS"
    assert (
        fixture.repository.get(
            checked.reference.contract_id, owner_id=str(fixture.user.id), run_id=fixture.run.id
        ).status
        == "VALIDATED"
    )


async def test_h5b_result_read_rejects_agent_reference_identity_and_inactive_attempt(api_fixture):
    fixture = api_fixture
    request = await authoring_session(fixture, session="read-bound")
    url = "/api/v1/adlc/contract-authoring-result"
    body = {"operation": "read-authoring-result", "session_id": "read-bound", "reference": {"approved": True}}
    raw, headers = signed(body, domain=AUTHORING_READ_DOMAIN)
    assert (await fixture.client.post(url, content=raw, headers=headers)).status_code == 422
    body.pop("reference")
    raw, headers = signed(body, domain=AUTHORING_READ_DOMAIN)
    await fixture.callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.FAILED)
    assert (await fixture.client.post(url, content=raw, headers=headers)).json()["detail"][
        "code"
    ] == "CONTRACT_ATTEMPT_INACTIVE"
    # Read-domain signatures cannot authorize any of the six write commands.
    raw, headers = signed(
        {"session_id": "read-bound", "tool": "skilltree_init", "arguments": {}}, domain=AUTHORING_READ_DOMAIN
    )
    assert (await fixture.client.post("/api/v1/adlc/contract-tools", content=raw, headers=headers)).status_code == 401


async def test_h5b_viewer_capabilities_expose_no_execution_or_secret_authority(api_fixture, monkeypatch):
    fixture = api_fixture
    monkeypatch.setattr(
        contract_api, "get_settings_service", lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=True))
    )
    response = await fixture.client.get("/api/v1/adlc/contract-viewer")
    assert response.status_code == 200
    assert response.json()["human_actions_configured"] is False
    assert response.json()["execution_policy_enforced"] is False
    assert SECRET not in response.text
    monkeypatch.setattr(
        contract_api, "get_settings_service", lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=False))
    )
    assert (await fixture.client.get("/api/v1/adlc/contract-viewer")).json()["human_actions_configured"] is True


async def test_human_review_approval_export_and_archive_do_not_submit_run(api_fixture):
    f = api_fixture
    checked = await make_checked(f)
    cid = checked["document"]["contract_id"]
    response = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/approve",
        json={"reference": checked["reference"], "idempotency_key": "approve"},
    )
    assert response.status_code == 200
    accepted = response.json()["contract"]
    assert accepted["status"] == "APPROVED"
    assert accepted["approval"]["approved_by"] == str(f.user.id)
    assert (await f.service.get_run(f.run.id, owner_id=str(f.user.id))).status == f.run.status
    read = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}")
    assert read.json() == accepted
    assert read.headers["cache-control"] == "no-store"
    export = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/file")
    assert "sha256:" + hashlib.sha256(export.content).hexdigest() == accepted["reference"]["content_digest"]
    assert export.json() == accepted["document"]
    assert ".roadmap.json" in export.headers["content-disposition"]
    summary = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/summary")
    assert "acceptance criteria have NOT been executed" in summary.text
    old = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}?revision=1")
    assert old.json()["status"] == "DRAFT"
    blocked = await human_call(
        f,
        "skilltree_upsert_node",
        {
            "contract_id": cid,
            "expected_revision": 2,
            "idempotency_key": "bypass",
            "node": {"title": "Post-approval modification"},
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CONTRACT_LOCKED"
    fork = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/fork",
        json={"reference": accepted["reference"], "idempotency_key": "fork"},
    )
    assert fork.status_code == 200
    assert fork.json()["contract"]["status"] == "DRAFT"
    assert fork.json()["contract"]["document"]["supersedes"] == accepted["reference"]


async def test_other_owner_wrong_run_task_and_revision_are_denied(api_fixture):
    f = api_fixture
    checked = await make_checked(f)
    cid = checked["document"]["contract_id"]
    wrong_task = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/tasks/{uuid4()}/contract-tools",
        json={"tool": "skilltree_get_status", "arguments": {"contract_id": cid}},
    )
    assert wrong_task.status_code == 404
    missing_revision = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}?revision=100")
    assert missing_revision.status_code == 404
    other = SimpleNamespace(id=uuid4())
    f.app.dependency_overrides[get_current_active_user] = lambda: other
    f.app.dependency_overrides[contract_api.get_contract_approver] = lambda: other
    for suffix in ["", "/file", "/summary"]:
        denied = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}{suffix}")
        assert denied.status_code == 404
        assert "Roadmap" not in denied.text
    denied = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/approve",
        json={"reference": checked["reference"], "idempotency_key": "approve"},
    )
    assert denied.status_code == 404


async def test_feature_flag_is_runtime_guard_and_default_off(api_fixture, monkeypatch):
    f = api_fixture
    monkeypatch.delenv("ADLC_CONTRACTS_ENABLED")
    response = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contracts")
    assert response.status_code == 404
    response = await f.client.post("/api/v1/adlc/contract-tools", content=b"{}")
    assert response.status_code == 404


async def test_signed_tool_bridge_uses_registered_session_and_not_caller_identity(api_fixture):
    f = api_fixture
    await authoring_session(f)
    body = {
        "session_id": "h5a-session",
        "tool": "skilltree_init",
        "arguments": {
            "idempotency_key": "agent-init",
            "title": "Agent roadmap",
            "scope": {"objective": "Use small tools"},
        },
    }
    payload, headers = signed(body)
    created = await f.client.post("/api/v1/adlc/contract-tools", content=payload, headers=headers)
    assert created.status_code == 200
    document = created.json()["contract"]
    assert document["binding"]["session_id"] == "h5a-session"
    assert document["authored_via"] == "HARNESS_TOOL"
    assert document["approval"] is None
    replay = await f.client.post("/api/v1/adlc/contract-tools", content=payload, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["replayed"]
    for field, value in [("owner_id", str(uuid4())), ("status", "APPROVED"), ("file", "/outside/escape.json")]:
        altered = {**body, field: value}
        data, signature = signed(altered)
        rejected = await f.client.post("/api/v1/adlc/contract-tools", content=data, headers=signature)
        assert rejected.status_code == 422
    data, signature = signed({**body, "tool": "skilltree_approve"})
    rejected = await f.client.post("/api/v1/adlc/contract-tools", content=data, headers=signature)
    assert rejected.status_code == 422


@pytest.mark.skipif(shutil.which("node") is None, reason="Cross-language tool boundary requires Node.js")
async def test_real_node_client_wire_bytes_reach_python_writer_and_human_freeze(api_fixture):
    f = api_fixture
    await authoring_session(f)
    root = Path(__file__).resolve().parents[5]
    helper = root / "agent-harness-server/deepseek-harness/plugins/vai-adlc-skilltree/tests/sign-command.mjs"

    async def node_call(tool, arguments):
        process = await asyncio.create_subprocess_exec(
            shutil.which("node"),
            str(helper),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = json.dumps(
            {"secret": SECRET, "session_id": "h5a-session", "tool": tool, "arguments": arguments}
        ).encode()
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(payload), timeout=15)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        assert process.returncode == 0, stderr.decode()
        wire = json.loads(stdout)
        return await f.client.post(
            "/api/v1/adlc/contract-tools", content=wire["body"].encode(), headers=wire["headers"]
        )

    created = await node_call(
        "skilltree_init",
        {
            "idempotency_key": "node.init",
            "title": "Roadmap tiếng Việt",
            "scope": {"objective": "Xác nhận hợp đồng"},
        },
    )
    assert created.status_code == 200
    cid = created.json()["contract"]["document"]["contract_id"]
    added = await node_call(
        "skilltree_upsert_node",
        {
            "contract_id": cid,
            "expected_revision": 1,
            "idempotency_key": "node.task",
            "node": {"title": "Giữ đầy đủ yêu cầu", "acceptance_criteria": [{"description": "Con người kiểm tra"}]},
        },
    )
    assert added.status_code == 200
    checked = await node_call(
        "skilltree_validate",
        {
            "contract_id": cid,
            "expected_revision": 2,
            "idempotency_key": "node.validate",
        },
    )
    assert checked.status_code == 200
    assert checked.json()["contract"]["validation"]["criteria_executed"] is False
    accepted = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/contracts/{cid}/approve",
        json={
            "reference": checked.json()["contract"]["reference"],
            "idempotency_key": "human.node.approve",
        },
    )
    assert accepted.status_code == 200
    rejected = await node_call(
        "skilltree_upsert_node",
        {
            "contract_id": cid,
            "expected_revision": 2,
            "idempotency_key": "node.late",
            "node": {"title": "Must never modify the approved contract"},
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "CONTRACT_LOCKED"


@pytest.mark.parametrize("mode", ["unknown-session", "coding-profile", "stale-attempt", "finished", "tampered-body"])
async def test_bridge_fails_closed_for_unauthorized_or_inactive_execution(api_fixture, mode):
    f = api_fixture
    request = await authoring_session(
        f,
        profile="harness-profile:adlc-coding/0.1.0"
        if mode == "coding-profile"
        else "harness-profile:adlc-skilltree/0.1.0",
    )
    if mode == "stale-attempt":
        f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    if mode == "finished":
        await f.callbacks.attempts.update_status(request.attempt_id, TaskAttemptStatus.FAILED)
    data, headers = signed(
        {
            "session_id": "unknown" if mode == "unknown-session" else "h5a-session",
            "tool": "skilltree_init",
            "arguments": {"idempotency_key": "init", "title": "Should fail", "scope": {"objective": "Do not accept"}},
        }
    )
    if mode == "tampered-body":
        data += b" "
    rejected = await f.client.post("/api/v1/adlc/contract-tools", content=data, headers=headers)
    assert rejected.status_code in {401, 403, 409}
    assert not f.repository.list_for_run(f.run.id, owner_id=str(f.user.id))


async def test_explicit_user_token_guard_blocks_auto_login_and_service_secret(monkeypatch):
    settings = SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=True))
    monkeypatch.setattr(contract_api, "get_settings_service", lambda: settings)
    auth = SimpleNamespace(get_current_user_from_access_token=AsyncMock(), get_current_active_user=AsyncMock())
    monkeypatch.setattr(contract_api, "get_auth_service", lambda: auth)

    def req(headers):
        return Request(
            {"type": "http", "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()]}
        )

    with pytest.raises(HTTPException) as error:
        await contract_api.get_contract_approver(req({"authorization": "Bearer " + SECRET}), session=object())
    assert error.value.status_code == 403
    auth.get_current_user_from_access_token.assert_not_awaited()
    settings.auth_settings.AUTO_LOGIN = False
    with pytest.raises(HTTPException) as error:
        await contract_api.get_contract_approver(req({"x-api-key": SECRET}), session=object())
    assert error.value.status_code == 401
    auth.get_current_user_from_access_token.assert_not_awaited()
    auth.get_current_user_from_access_token.side_effect = ValueError("invalid secret token")
    with pytest.raises(HTTPException) as error:
        await contract_api.get_contract_approver(req({"authorization": "Bearer " + SECRET}), session=object())
    assert error.value.status_code == 401
    assert SECRET not in str(error.value.detail)
    user = SimpleNamespace(id=uuid4())
    auth.get_current_user_from_access_token.side_effect = None
    auth.get_current_user_from_access_token.return_value = user
    auth.get_current_active_user.return_value = user
    assert (
        await contract_api.get_contract_approver(req({"authorization": "Bearer user-access-token"}), session=object())
        == user
    )
    auth.get_current_active_user.return_value = None
    with pytest.raises(HTTPException) as error:
        await contract_api.get_contract_approver(req({"authorization": "Bearer inactive-user-token"}), session=object())
    assert error.value.status_code == 401

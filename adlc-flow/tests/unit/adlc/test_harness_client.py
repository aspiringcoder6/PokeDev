# ruff: noqa: INP001, S101, S106

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from langflow.adlc.contract_execution_models import EXECUTION_PROFILE
from langflow.adlc.harness_client import (
    AUTHORING_API_ROOT,
    AUTHORING_PROFILE_REF,
    CONTRACT_API_ROOT,
    HarnessClientError,
    HarnessHttpClient,
    HarnessServerSettings,
)
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessExecutionSpec,
    HarnessInteractionResponse,
    HarnessSessionRequest,
)


def _session_request() -> HarnessSessionRequest:
    return HarnessSessionRequest(
        correlation=HarnessCorrelation(
            request_id=uuid4(),
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
            attempt_id=uuid4(),
        ),
        idempotency_key="attempt-1",
        objective="Implement it.",
        input={"requirement": "Implement it."},
        execution=HarnessExecutionSpec(profile_ref="profile:test/0.1.0", operation="coding-task"),
        result_schema_ref="adlc://schemas/source-patch/0.1",
    )


async def test_harness_http_client_uses_authenticated_versioned_endpoints() -> None:
    seen: list[httpx.Request] = []
    request = _session_request()
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "schema_version": "0.1",
        "session_id": "session-1",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": request.idempotency_key,
        "status": "READY_FOR_SUBMISSION",
        "submission_mode": "AUTO",
        "events": [],
        "result": None,
        "created_at": now,
        "updated_at": now,
    }

    def handler(incoming: httpx.Request) -> httpx.Response:
        seen.append(incoming)
        assert incoming.headers["authorization"] == "Bearer harness-token"
        if incoming.url.path.endswith("/health"):
            return httpx.Response(200, json={"ready": True, "version": "0.1.0"})
        if incoming.url.path.endswith("/plugins"):
            return httpx.Response(
                200,
                json={
                    "schema_version": "0.1",
                    "ready": True,
                    "checked_at": now,
                    "error_code": None,
                    "plugins": [],
                },
            )
        if incoming.url.path.endswith("/sessions") and incoming.method == "POST":
            return httpx.Response(202, json={"schema_version": "0.1", "session": session, "replayed": False})
        if incoming.url.path.endswith("/sessions/session-1") and incoming.method == "GET":
            return httpx.Response(200, json=session)
        if incoming.url.path.endswith("/submit"):
            return httpx.Response(
                202,
                json={
                    "schema_version": "0.1",
                    "session_id": "session-1",
                    "status": "DELIVERING",
                    "delivery_id": str(uuid4()),
                    "delivery_status": "PENDING",
                    "replayed": False,
                },
            )
        if incoming.url.path.endswith("/interactions/interaction-1/responses"):
            return httpx.Response(
                202,
                json={
                    "schema_version": "0.1",
                    "session_id": "session-1",
                    "interaction": {
                        "interaction_id": str(uuid4()),
                        "kind": "APPROVAL",
                        "status": "SUBMITTED",
                        "title": "Approve",
                        "prompt": "Continue?",
                        "input_schema": {},
                        "ui_schema": {},
                        "requested_at": now,
                        "resolved_at": now,
                        "response": {"action": "approve"},
                        "metadata": {},
                    },
                    "status": "RUNNING",
                    "replayed": False,
                },
            )
        return httpx.Response(404)

    client = HarnessHttpClient(
        HarnessServerSettings(api_token="harness-token"),
        transport=httpx.MockTransport(handler),
    )

    assert (await client.health())["ready"] is True
    assert (await client.get_plugin_inventory()).ready is True
    accepted = await client.create_session(request)
    assert accepted.session.session_id == "session-1"
    assert (await client.get_session("session-1")).status.value == "READY_FOR_SUBMISSION"
    interaction = await client.respond_to_interaction(
        "session-1",
        "interaction-1",
        HarnessInteractionResponse(response={"action": "approve"}),
    )
    assert interaction.interaction.response == {"action": "approve"}
    assert (await client.submit_session("session-1")).delivery_status.value == "PENDING"
    assert [item.url.path for item in seen] == [
        "/api/v1/adlc-harness/health",
        "/api/v1/adlc-harness/plugins",
        "/api/v1/adlc-harness/sessions",
        "/api/v1/adlc-harness/sessions/session-1",
        "/api/v1/adlc-harness/sessions/session-1/interactions/interaction-1/responses",
        "/api/v1/adlc-harness/sessions/session-1/submit",
    ]
    await client.close()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost",
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com?token=secret",
    ],
)
def test_harness_client_rejects_unsafe_server_urls(url: str) -> None:
    with pytest.raises(ValueError, match="Harness"):
        HarnessHttpClient(HarnessServerSettings(base_url=url))


async def test_authoring_create_is_opt_in_and_all_writes_route_to_its_fixed_endpoint():
    request = _session_request()
    request.execution.profile_ref = AUTHORING_PROFILE_REF
    request.execution.operation = "skilltree-authoring"
    seen = []
    timestamp = datetime.now(timezone.utc).isoformat()
    session = {
        "schema_version": "0.1",
        "session_id": "authoring-session",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": request.idempotency_key,
        "status": "RUNNING",
        "submission_mode": "MANUAL",
        "events": [],
        "result": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    def handler(incoming):
        seen.append((incoming.method, incoming.url.path))
        assert incoming.headers["authorization"] == "Bearer test-token"
        if incoming.url.path == AUTHORING_API_ROOT + "/sessions":
            return httpx.Response(202, json={"schema_version": "0.1", "session": session, "replayed": False})
        if incoming.url.path == AUTHORING_API_ROOT + "/sessions/authoring-session/cancel":
            return httpx.Response(200, json={**session, "status": "CANCELLED"})
        return httpx.Response(404)

    async with httpx.AsyncClient():
        disabled = HarnessHttpClient(
            HarnessServerSettings(api_token="test-token"),
            transport=httpx.MockTransport(handler),
            authoring_enabled=False,
        )
        try:
            with pytest.raises(HarnessClientError, match="HARNESS_AUTHORING_DISABLED"):
                await disabled.create_session(request)
            assert seen == []
        finally:
            await disabled.close()
        enabled = HarnessHttpClient(
            HarnessServerSettings(api_token="test-token"),
            transport=httpx.MockTransport(handler),
            authoring_enabled=True,
        )
        try:
            accepted = await enabled.create_session(request)
            await enabled.cancel_session(accepted.session.session_id)
            assert seen == [
                ("POST", AUTHORING_API_ROOT + "/sessions"),
                ("POST", AUTHORING_API_ROOT + "/sessions/authoring-session/cancel"),
            ]
        finally:
            await enabled.close()


@pytest.mark.parametrize(("first_status", "recovers"), [(404, True), (401, False), (500, False)])
async def test_authoring_restart_recovery_probes_get_only_and_never_repeats_a_write(first_status, recovers):
    request = _session_request()
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "schema_version": "0.1",
        "session_id": "recovery-session",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": request.idempotency_key,
        "status": "RUNNING",
        "submission_mode": "MANUAL",
        "events": [],
        "result": None,
        "created_at": now,
        "updated_at": now,
    }
    seen = []

    def handler(incoming):
        seen.append((incoming.method, incoming.url.path))
        if incoming.url.path.startswith("/api/v1/adlc-harness/"):
            return httpx.Response(first_status)
        if incoming.method == "POST":
            # A write failure must not fall through to the coding endpoint.
            return httpx.Response(500)
        return httpx.Response(200, json=session)

    client = HarnessHttpClient(
        HarnessServerSettings(api_token="test-token"), transport=httpx.MockTransport(handler), authoring_enabled=True
    )
    try:
        if recovers:
            with pytest.raises(HarnessClientError, match="HARNESS_SERVER_ERROR"):
                await client.cancel_session("recovery-session")
            assert seen == [
                ("GET", "/api/v1/adlc-harness/sessions/recovery-session"),
                ("GET", AUTHORING_API_ROOT + "/sessions/recovery-session"),
                ("POST", AUTHORING_API_ROOT + "/sessions/recovery-session/cancel"),
            ]
        else:
            with pytest.raises(HarnessClientError):
                await client.get_session("recovery-session")
            assert len(seen) == 1
            assert seen[0][0] == "GET"
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("h4_status", "author_status", "recovers"), [(404, 404, True), (401, 404, False), (404, 500, False)]
)
async def test_contract_restart_routes_bounded_artifact_reads_and_no_write_fallback(h4_status, author_status, recovers):
    request = _session_request()
    request.execution.profile_ref = EXECUTION_PROFILE
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "schema_version": "0.1",
        "session_id": "contract-session",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": "bound",
        "status": "RUNNING",
        "submission_mode": "MANUAL",
        "events": [],
        "result": None,
        "created_at": now,
        "updated_at": now,
    }
    seen = []

    def handler(incoming):
        path = incoming.url.path
        seen.append((incoming.method, path))
        if path.startswith("/api/v1/adlc-harness/"):
            return httpx.Response(h4_status)
        if path.startswith(AUTHORING_API_ROOT + "/"):
            return httpx.Response(author_status)
        if incoming.method == "POST":
            return httpx.Response(500)
        if "/artifacts/" in path:
            return httpx.Response(404)
        return httpx.Response(200, json=session)

    client = HarnessHttpClient(
        HarnessServerSettings(api_token="fixture-token"),
        transport=httpx.MockTransport(handler),
        authoring_enabled=True,
        contract_execution_enabled=True,
    )
    try:
        if recovers:
            assert (await client.get_session("contract-session")).session_id == "contract-session"
            with pytest.raises(HarnessClientError):
                await client.get_artifact("contract-session", "artifact")
            with pytest.raises(HarnessClientError, match="SERVER_ERROR"):
                await client.cancel_session("contract-session")
            assert seen[-2:] == [
                ("GET", CONTRACT_API_ROOT + "/sessions/contract-session/artifacts/artifact"),
                ("POST", CONTRACT_API_ROOT + "/sessions/contract-session/cancel"),
            ]
        else:
            with pytest.raises(HarnessClientError):
                await client.get_session("contract-session")
            assert all(not path.startswith(CONTRACT_API_ROOT) for _, path in seen)
    finally:
        await client.close()


async def test_contract_create_requires_optin_without_network_call():
    request = _session_request()
    request.execution.profile_ref = EXECUTION_PROFILE
    client = HarnessHttpClient(
        transport=httpx.MockTransport(lambda _request: pytest.fail("No HTTP allowed")), contract_execution_enabled=False
    )
    try:
        with pytest.raises(HarnessClientError, match="CONTRACT_EXECUTION_DISABLED"):
            await client.create_session(request)
    finally:
        await client.close()

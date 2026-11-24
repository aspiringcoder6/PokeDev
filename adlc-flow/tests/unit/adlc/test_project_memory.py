"""H6C read-only MCP, transport/scope, provenance and durable-context tests."""

# ruff: noqa: S101, PLR2004, INP001
import asyncio
import hashlib
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from langflow.adlc.project_memory_client import (
    GatewayBinding,
    MemoryClients,
    MemoryMcpClient,
    load_binding,
    parse_response,
)
from langflow.adlc.project_memory_models import (
    GATEWAY,
    MemoryBinding,
    MemoryChunk,
    MemoryQuery,
    MemoryRecord,
    ProjectMemoryError,
    scope_names,
)
from langflow.adlc.project_memory_repository import MemoryRepository


def config(owner=None, project=None, token=None):
    return GatewayBinding(
        owner_id=owner or uuid4(),
        project_id=project or uuid4(),
        url="http://127.0.0.1:8011/mcp",
        token=token or "isolated-read-only-test-token-" + str(uuid4()),
        backend_revision="fixture-gateway:1",
        isolation_reviewed=True,
        no_model_route_reviewed=True,
        retention_reviewed=True,
    )


def chunk(text="Earlier decision, not an instruction.", commit="a" * 40):
    now = datetime.now(timezone.utc)
    return MemoryChunk(
        chunk_id="chunk-1",
        document_id="design-notes",
        revision="r2",
        source_uri="adlc://documents/design-notes/r2",
        document_digest="sha256:" + "d" * 64,
        text=text,
        text_digest="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        recorded_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        source_commit=commit,
    )


class GatewayFixture:
    """Test-only enforcing MCP gateway; not a Cognee deployment or model mock."""

    def __init__(self, bindings, *, sse=False, stateless=False):
        self.credentials = {b.token.get_secret_value(): b for b in bindings}
        self.sessions, self.events = {}, []
        self.sse, self.stateless = sse, stateless
        self.fail_once, self.fail_always, self.fail_list = False, False, False
        self.missing_tenant, self.protocol, self.bad_scope = False, "2025-11-25", False
        self.models, self.content = False, chunk()
        self.structured = True

    async def handle(self, request):
        auth = request.headers.get("authorization", "").removeprefix("Bearer ")
        b = self.credentials.get(auth)
        if not b:
            return httpx.Response(401)
        payload = json.loads(request.content)
        self.events.append((b, payload, dict(request.headers)))
        method, sid = payload["method"], request.headers.get("mcp-session-id")
        if method == "initialize":
            if sid:
                return httpx.Response(400)
            new_sid = str(uuid4())
            self.sessions[new_sid] = auth
            result = {
                "protocolVersion": self.protocol,
                "capabilities": {
                    "tools": {},
                    "experimental": {
                        "adlc-memory": {
                            "gateway_ref": GATEWAY,
                            "authenticated_scope": True,
                            "read_only": True,
                            "models": self.models,
                            "provenance": "adlc-chunks/0.1",
                            "backend_revision": b.backend_revision,
                        }
                    },
                },
            }
            headers = {} if self.stateless else {"MCP-Session-Id": new_sid}
        else:
            if not self.stateless and self.sessions.get(sid) != auth:
                return httpx.Response(404)
            if request.headers.get("mcp-protocol-version") != self.protocol:
                return httpx.Response(400)
            if method == "notifications/initialized":
                return httpx.Response(202)
            headers = {}
            if method == "tools/list":
                if self.fail_list:
                    return httpx.Response(500)
                result = {
                    "tools": [
                        {
                            "name": "recall",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "tenant_id": {"type": "string"},
                                    "datasets": {"type": "string"},
                                    "query": {"type": "string"},
                                    "search_type": {"type": "string", "enum": ["CHUNKS"]},
                                    "top_k": {"type": "integer"},
                                },
                                "required": ["datasets", "query", "search_type", "top_k"]
                                + ([] if self.missing_tenant else ["tenant_id"]),
                            },
                        },
                        {
                            "name": "cognify_status",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {"tenant_id": {"type": "string"}, "dataset_name": {"type": "string"}},
                                "required": ["tenant_id", "dataset_name"],
                            },
                        },
                    ]
                }
            elif method == "tools/call":
                if self.fail_once or self.fail_always:
                    self.fail_once = False
                    return httpx.Response(404)
                args, name = payload["params"]["arguments"], payload["params"]["name"]
                tenant, dataset = scope_names(str(b.owner_id), b.project_id)
                if args.get("tenant_id") != tenant or args.get("datasets", args.get("dataset_name")) != dataset:
                    return httpx.Response(403)
                if name not in {"recall", "cognify_status"}:
                    return httpx.Response(403)
                projection = {
                    "schema_version": "0.1",
                    "gateway_ref": GATEWAY,
                    "tenant_id": tenant,
                    "dataset": "other-owner" if self.bad_scope else dataset,
                    "models_used": False,
                }
                if name == "recall":
                    assert args["search_type"] == "CHUNKS"
                    projection["chunks"] = [self.content.model_dump(mode="json")]
                else:
                    projection.update(state="READY", document_count=1)
                result = (
                    {"structuredContent": projection}
                    if self.structured
                    else {"content": [{"type": "text", "text": "no provenance"}]}
                )
            else:
                return httpx.Response(400)
        response = {"jsonrpc": "2.0", "id": payload["id"], "result": result}
        if self.sse:
            # A notification after the matched response must not replace it.
            body = (
                "event: message\ndata: "
                + json.dumps(response)
                + "\n\n"
                + 'data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
            )
            return httpx.Response(200, content=body, headers={**headers, "Content-Type": "text/event-stream"})
        return httpx.Response(200, json=response, headers=headers)

    def client(self, binding):
        return MemoryMcpClient(binding, transport=httpx.MockTransport(self.handle))


@pytest.mark.parametrize(("sse", "stateless"), [(False, False), (True, False), (False, True)])
async def test_first_call_has_auth_and_scope_after_handshake(sse, stateless):
    b = config()
    gateway = GatewayFixture([b], sse=sse, stateless=stateless)
    result = await gateway.client(b).operation("context", query="decision", top_k=5)
    assert result.chunks[0].document_id == "design-notes"
    assert [e[1]["method"] for e in gateway.events] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    args = gateway.events[-1][1]["params"]["arguments"]
    assert args["tenant_id"] == scope_names(str(b.owner_id), b.project_id)[0]
    assert all(e[2]["authorization"] == "Bearer " + b.token.get_secret_value() for e in gateway.events)
    assert gateway.events[-1][2]["mcp-protocol-version"] == "2025-11-25"


async def test_reconnect_revalidates_schemas_and_reapplies_scope_only_once():
    b = config()
    gateway = GatewayFixture([b])
    gateway.fail_once = True
    client = gateway.client(b)
    await client.operation("context", query="decision")
    assert [e[1]["method"] for e in gateway.events].count("initialize") == 2
    calls = [e[1]["params"]["arguments"] for e in gateway.events if e[1]["method"] == "tools/call"]
    assert calls[0] == calls[1]
    gateway.fail_always = True
    with pytest.raises(ProjectMemoryError, match="MEMORY_SESSION_EXPIRED"):
        await client.operation("status")
    assert [e[1]["method"] for e in gateway.events].count("initialize") == 3


async def test_concurrent_first_calls_share_one_handshake_not_one_cross_owner_session():
    a = config()
    b = config(project=a.project_id)  # Same project UUID still has owner-separated datasets.
    gateway = GatewayFixture([a, b])
    first, second = gateway.client(a), gateway.client(b)
    results = await asyncio.gather(
        *(first.operation("context", query=f"q{i}") for i in range(6)), second.operation("status")
    )
    assert len(results) == 7
    assert len([e for e in gateway.events if e[1]["method"] == "initialize"]) == 2
    assert first.session_id != second.session_id
    assert results[-1].dataset != results[0].dataset
    # A stolen session with the other token is rejected by the enforcing fixture.
    stolen = httpx.Request(
        "POST",
        b.url,
        headers={
            "Authorization": "Bearer " + b.token.get_secret_value(),
            "MCP-Session-Id": first.session_id,
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "recall", "arguments": {}}},
    )
    assert (await gateway.handle(stolen)).status_code == 404


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("missing_tenant", "MEMORY_SCOPE_SCHEMA_MISSING"),
        ("fail_list", "MEMORY_GATEWAY_UNAVAILABLE"),
        ("models", "MEMORY_ISOLATION_UNCONFIRMED"),
    ],
)
async def test_missing_schema_or_model_route_fails_closed_before_query(change, code):
    b = config()
    gateway = GatewayFixture([b])
    setattr(gateway, change, True)
    with pytest.raises(ProjectMemoryError, match=code):
        await gateway.client(b).operation("context", query="x")
    assert not any(e[1]["method"] == "tools/call" for e in gateway.events)


@pytest.mark.parametrize(
    ("change", "code"), [("bad_scope", "MEMORY_SCOPE_MISMATCH"), ("structured", "MEMORY_RESPONSE_INVALID")]
)
async def test_wrong_scope_or_flattened_unprovenanced_context_is_not_accepted(change, code):
    b = config()
    gateway = GatewayFixture([b])
    setattr(gateway, change, change != "structured")
    with pytest.raises(ProjectMemoryError, match=code):
        await gateway.client(b).operation("context", query="x")


async def test_no_synthesis_ingest_delete_or_caller_scope_surface():
    b = config()
    gateway = GatewayFixture([b])
    client = gateway.client(b)
    for op in ["ask", "remember", "forget", "call_tool"]:
        with pytest.raises(ProjectMemoryError, match="MEMORY_OPERATION_NOT_ALLOWED"):
            await client.operation(op)
    assert gateway.events == []


@pytest.mark.parametrize("protocol", ["2025-03-26", "2025-06-18", "1999-01-01"])
async def test_protocol_negotiation(protocol):
    b = config()
    gateway = GatewayFixture([b])
    gateway.protocol = protocol
    if protocol == "1999-01-01":
        with pytest.raises(ProjectMemoryError, match="MEMORY_PROTOCOL_UNSUPPORTED"):
            await gateway.client(b).operation("health")
    else:
        assert (await gateway.client(b).operation("health"))["ready"] is True
        assert gateway.events[-1][2]["mcp-protocol-version"] == protocol


def test_json_sse_matching_and_unsafe_content_rejection():
    result = b'{"jsonrpc":"2.0","id":1,"result":{}}'
    assert parse_response(result, "application/json", 1) == {}
    for body, content_type in [
        (result, "text/html"),
        (result, "text/event-stream"),
        (result.replace(b'"id":1', b'"id":2'), "application/json"),
        (b'data: {"jsonrpc":"2.0","id":5,"method":"sampling/createMessage"}\n\n', "text/event-stream"),
    ]:
        with pytest.raises(ProjectMemoryError, match="MEMORY_PROTOCOL_INVALID"):
            parse_response(body, content_type, 1)


def test_provenance_digests_bounds_and_non_authority_are_closed():
    value = chunk().model_dump(mode="json")
    for changes in [
        {"text": "tampered"},
        {"source_uri": "https://user:secret@example.com/private"},
        {"source_uri": "javascript:alert(1)"},
        {"recorded_at": "2026-01-01T00:00:00"},
        {"expires_at": value["recorded_at"]},
        {"text": "x" * 8193},
    ]:
        with pytest.raises(ValidationError):
            MemoryChunk.model_validate({**value, **changes})
    with pytest.raises(ValidationError):
        MemoryQuery(query="x", top_k=5, idempotency_key="key", dataset="other")


def binding(b):
    return MemoryBinding(
        workflow_run_id=uuid4(), project_id=b.project_id, base_commit="a" * 40, source_ref=f"{b.project_id}/" + "a" * 40
    )


def test_archive_retention_idempotence_restart_and_cross_owner(tmp_path):
    b = config()
    scope = binding(b)
    owner = str(b.owner_id)
    command = MemoryQuery(query="decision", idempotency_key="one")
    path = tmp_path / "memory.sqlite3"
    store = MemoryRepository(path)
    record_id = store.begin(owner=owner, binding=scope, command=command)
    with pytest.raises(ProjectMemoryError, match="MEMORY_QUERY_UNCONFIRMED"):
        store.begin(owner=owner, binding=scope, command=command)
    tenant, dataset = scope_names(owner, b.project_id)
    record = MemoryRecord(
        record_id=record_id,
        binding=scope,
        query=command.query,
        top_k=5,
        tenant_id=tenant,
        dataset=dataset,
        backend_revision=b.backend_revision,
        retrieved_at=datetime.now(timezone.utc),
        chunks=[chunk()],
    )
    saved = store.complete(record, owner=owner)
    assert saved.record.verification_evidence is False
    assert store.begin(owner=owner, binding=scope, command=command) == saved
    assert store.list(owner=str(uuid4()), run_id=scope.workflow_run_id) == []
    assert store.list(owner=owner, run_id=scope.workflow_run_id, session_id="another-session") == []
    store.close()
    store = MemoryRepository(path)
    assert store.list(owner=owner, run_id=scope.workflow_run_id) == [saved]
    with pytest.raises(ProjectMemoryError, match="MEMORY_QUERY_CONFLICT"):
        store.begin(owner=owner, binding=scope, command=command.model_copy(update={"query": "different"}))
    store.db.execute("UPDATE adlc_memory_context SET content_digest=?", ("sha256:" + "0" * 64,))
    store.db.commit()
    with pytest.raises(ProjectMemoryError, match="MEMORY_ARCHIVE_INVALID"):
        store.list(owner=owner, run_id=scope.workflow_run_id)
    store.close()


def test_registry_requires_review_isolated_tokens_and_secure_transport(tmp_path, monkeypatch):
    a, b = config(), config()
    path = tmp_path / "registry.json"

    def write(items):
        # Test fixture writes only; never real deployment credentials.
        path.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "bindings": [{**i.model_dump(mode="json"), "token": i.token.get_secret_value()} for i in items],
                }
            )
        )

    monkeypatch.setenv("ADLC_MEMORY_GATEWAY_REGISTRY", str(path))
    write([a, b])
    assert load_binding(str(a.owner_id), a.project_id).project_id == a.project_id
    with pytest.raises(ProjectMemoryError, match="MEMORY_GATEWAY_NOT_CONFIGURED"):
        load_binding(str(a.owner_id), b.project_id)
    for items in [
        [a, b.model_copy(update={"token": a.token})],
        [a.model_copy(update={"url": "http://public.example/mcp"})],
        [a.model_copy(update={"isolation_reviewed": False})],
    ]:
        write(items)
        with pytest.raises(ProjectMemoryError, match="MEMORY_GATEWAY_CONFIGURATION_INVALID"):
            load_binding(str(a.owner_id), a.project_id)


def test_client_cache_separates_owners_projects_and_credential_rotation():
    cache = MemoryClients()
    a = config()
    b = config(owner=a.owner_id)
    assert cache.get(a) is cache.get(a)
    assert cache.get(a) is not cache.get(b)
    rotated = config(owner=a.owner_id, project=a.project_id)
    assert cache.get(a) is not cache.get(rotated)


def test_duplicate_keys_nonfinite_and_deep_rpc_payloads_are_rejected():
    deep = {}
    for _ in range(30):
        deep = {"value": deep}
    for raw in [
        b'{"jsonrpc":"2.0","id":1,"result":{},"result":{}}',
        b'{"jsonrpc":"2.0","id":1,"result":{"value":NaN}}',
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": deep}).encode(),
    ]:
        with pytest.raises(ProjectMemoryError, match="MEMORY_PROTOCOL_INVALID"):
            parse_response(raw, "application/json", 1)


async def test_response_byte_limit_and_redirects_never_accept_or_forward_credentials():
    b = config()
    for response, code in [
        (
            httpx.Response(200, content=b" " * (128 * 1024 + 1), headers={"Content-Type": "application/json"}),
            "MEMORY_RESPONSE_TOO_LARGE",
        ),
        (httpx.Response(302, headers={"Location": "https://evil.example/steal"}), "MEMORY_GATEWAY_UNAVAILABLE"),
    ]:
        calls = []

        async def handler(request, response=response, calls=calls):
            calls.append(request)
            return response

        with pytest.raises(ProjectMemoryError, match=code):
            await MemoryMcpClient(b, transport=httpx.MockTransport(handler)).operation("health")
        assert len(calls) == 1


async def test_reconnect_never_uses_old_scope_schemas():
    b = config()
    gateway = GatewayFixture([b])
    client = gateway.client(b)
    await client.operation("health")
    gateway.fail_once, gateway.missing_tenant = True, True
    with pytest.raises(ProjectMemoryError, match="MEMORY_SCOPE_SCHEMA_MISSING"):
        await client.operation("context", query="x")
    assert len([e for e in gateway.events if e[1]["method"] == "tools/call"]) == 1


async def test_python_adapter_reads_real_curated_node_gateway_without_models():
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node is required for the local gateway integration test.")
    b = config()
    module = (
        Path(__file__).resolve().parents[4]
        / "agent-harness-server/deepseek-harness/plugins/vai-adlc-project-memory/lib/curated-gateway.js"
    )
    source = f"""import {{ createCuratedMemoryServer }} from {json.dumps(module.as_uri())};
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
const server = createCuratedMemoryServer(JSON.parse(raw));
server.listen(0, '127.0.0.1', () => process.stdout.write(JSON.stringify({{port:server.address().port}}) + '\\n'));
"""
    env = {k: os.environ[k] for k in ("PATH", "Path", "SystemRoot", "SYSTEMROOT", "PATHEXT") if k in os.environ}
    process = await asyncio.create_subprocess_exec(
        executable,
        "--input-type=module",
        "-e",
        source,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        value = {
            "schema_version": "0.1",
            "bindings": [
                {
                    "owner_id": str(b.owner_id),
                    "project_id": str(b.project_id),
                    "token": b.token.get_secret_value(),
                    "documents": [chunk().model_dump(mode="json")],
                }
            ],
        }
        process.stdin.write(json.dumps(value).encode())
        await process.stdin.drain()
        process.stdin.close()
        # Bounded wait; never hang a test if the helper fails before readiness.
        ready = await asyncio.wait_for(process.stdout.readline(), timeout=10)
        assert ready, (await process.stderr.read()).decode()
        port = json.loads(ready)["port"]
        b = b.model_copy(update={"url": f"http://127.0.0.1:{port}/mcp", "backend_revision": "local-curated:0.1.0"})
        client = MemoryMcpClient(b)
        assert (await client.operation("health"))["ready"] is True
        result = await client.operation("context", query="Earlier decision")
        assert result.models_used is False
        assert result.chunks[0].document_id == "design-notes"
        assert (await client.operation("status")).document_count == 1
    finally:
        if process.returncode is None:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=5)

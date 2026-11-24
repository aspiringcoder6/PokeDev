# ruff: noqa: S101, S105, PLR2004, INP001 - existing test namespace; explicit dummy credentials.
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from langflow.adlc.github_webhook_edge import create_edge
from langflow.adlc.memory_gateway_local import (
    BACKEND_REVISION,
    CogneeDocumentReader,
    LocalMemorySettings,
    create_gateway,
)
from langflow.adlc.project_memory_client import GatewayBinding, MemoryMcpClient
from langflow.adlc.project_memory_models import scope_names


def fixture(*, expired=False):
    owner, project, dataset, document = (uuid4() for _ in range(4))
    now = datetime.now(timezone.utc) - timedelta(days=2 if expired else 0, seconds=1)
    note = {
        "schema_version": "0.1",
        "owner_id": str(owner),
        "project_id": str(project),
        "text": "Python pagination must reject bool.",
        "revision": "note-1",
        "recorded_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "source_commit": "a" * 40,
    }
    raw = json.dumps(note).encode()
    settings = {
        "schema_version": "0.1",
        "backend_url": "http://127.0.0.1:8010",
        "backend_revision": BACKEND_REVISION,
        "bindings": [
            {
                "owner_id": str(owner),
                "project_id": str(project),
                "token": "r" * 40,
                "dataset_id": str(dataset),
                "email": "isolated@example.com",
                "password": "p" * 40,
                "documents": [{"data_id": str(document), "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}],
            }
        ],
    }
    calls = []

    def backend(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "backend-secret"})
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/datasets/{dataset}/data/{document}/raw"
        assert request.headers["Authorization"] == "Bearer backend-secret"
        return httpx.Response(200, content=raw)

    config = LocalMemorySettings.model_validate(settings)
    reader = CogneeDocumentReader(config, transport=httpx.MockTransport(backend))
    app = create_gateway(settings, reader=reader)
    binding = GatewayBinding(
        owner_id=owner,
        project_id=project,
        token="r" * 40,
        url="http://127.0.0.1:8012/mcp",
        backend_revision=BACKEND_REVISION,
        isolation_reviewed=True,
        no_model_route_reviewed=True,
        retention_reviewed=True,
    )
    return app, binding, calls, reader


async def test_existing_strict_client_reads_real_backend_projection_without_model_route():
    app, binding, calls, _ = fixture()
    client = MemoryMcpClient(binding, transport=httpx.ASGITransport(app=app))
    result = await client.operation("context", query="Python bool", top_k=1)
    assert result.models_used is False
    assert len(result.chunks) == 1
    assert result.chunks[0].source_uri.startswith("urn:cognee:dataset:")
    assert result.chunks[0].text == "Python pagination must reject bool."
    assert [c[0] for c in calls] == ["POST", "GET"]
    assert not any("cognify" in path or "search" in path or "remember" in path for _, path in calls)


@pytest.mark.parametrize("kind", ["credential", "dataset", "tenant", "mutation", "extra", "bool_top_k"])
async def test_gateway_rejects_scope_widening_before_calling_backend(kind):
    app, binding, calls, _ = fixture()
    tenant, dataset = scope_names(str(binding.owner_id), binding.project_id)
    args = {"tenant_id": tenant, "datasets": dataset, "query": "bool", "search_type": "CHUNKS", "top_k": 1}
    name, token = "recall", "r" * 40
    if kind == "credential":
        token = "wrong"
    if kind == "dataset":
        args["datasets"] = "all"
    if kind == "tenant":
        args["tenant_id"] = "someone-else"
    if kind == "mutation":
        name = "remember"
    if kind == "extra":
        args["backend_url"] = "http://another-server"
    if kind == "bool_top_k":
        args["top_k"] = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.post(
            "/mcp",
            headers={"Authorization": "Bearer " + token},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        )
    assert response.status_code in {401, 409}
    assert not calls


async def test_expired_backend_documents_are_not_served():
    app, binding, _, _ = fixture(expired=True)
    client = MemoryMcpClient(binding, transport=httpx.ASGITransport(app=app))
    result = await client.operation("context", query="bool", top_k=1)
    assert not result.chunks
    assert (await client.operation("status")).state == "EMPTY"


async def test_changed_pinned_backend_document_fails_closed():
    _, _, _, reader = fixture()
    pin = reader.settings.bindings[0].documents[0]
    pin.digest = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="MEMORY_DOCUMENT_CHANGED"):
        await reader.documents(reader.settings.bindings[0])


async def test_edge_only_forwards_signed_issue_requests_and_preserves_raw_bytes():
    calls, raw, secret = [], b'{ "repository": {"id": 123} }', "s" * 40

    def backend(request):
        calls.append(request)
        assert request.url == "http://127.0.0.1:7860/api/v1/adlc/harness-demo/github/webhook"
        assert request.content == raw
        assert "authorization" not in request.headers
        return httpx.Response(202, json={"run_id": "id"})

    app = create_edge(secret, transport=httpx.MockTransport(backend))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        assert (await client.get("/")).status_code == 404
        assert (await client.get("/api/v1/users")).status_code == 404
        assert (await client.get("/docs")).status_code == 404
        assert (await client.post("/webhooks/github/issues", content=raw)).status_code == 401
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        response = await client.post(
            "/webhooks/github/issues",
            content=raw,
            headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "issues"},
        )
        assert response.status_code == 202
    assert len(calls) == 1


async def test_owned_repository_selection_is_validated_and_frozen(tmp_path, monkeypatch):
    from langflow.adlc.harness_demo import github_repository
    from tests.unit.adlc.test_harness_demo import REQUIREMENT, service

    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "aspiringcoder6/vanguard")
    run = await service(tmp_path).create("owner", REQUIREMENT)
    assert run["github_repository"] == "aspiringcoder6/vanguard"
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "../../another/repo")
    with pytest.raises(Exception, match="DEMO_GITHUB_REPOSITORY_INVALID"):
        github_repository()


@pytest.mark.parametrize("unknown_ack", [False, True])
async def test_operator_issue_creation_never_replays_unknown_or_completed_post(tmp_path, monkeypatch, unknown_ack):
    from langflow.adlc import harness_demo_sandbox
    from langflow.adlc.harness_demo_models import REQUIREMENT
    from scripts import harness_connections as connections

    owner, repository, calls = uuid4(), "aspiringcoder6/vanguard", []
    monkeypatch.setattr(connections, "PRIVATE", tmp_path)
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", repository)
    monkeypatch.setenv("ADLC_DEMO_GITHUB_OWNER_ID", str(owner))
    monkeypatch.setenv("ADLC_DEMO_GITHUB_REPOSITORY_ID", "123")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_ENABLED", "true")

    async def cli(argv, *, data=None, **kwargs):
        calls.append(argv)
        assert kwargs["credential_context"] is True
        if len(calls) == 1:
            return 0, json.dumps({"id": 123, "name": repository, "push": True}), ""
        assert json.loads(data) == {"title": "[ADLC] Pagination task", "body": REQUIREMENT, "labels": ["adlc-harness"]}
        assert "--input" in argv
        return (
            (1, "", "unknown")
            if unknown_ack
            else (0, json.dumps({"number": 1, "url": f"https://github.com/{repository}/issues/1"}), "")
        )

    monkeypatch.setattr(harness_demo_sandbox, "process", cli)
    if unknown_ack:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="ISSUE_CREATION_UNCONFIRMED"):
                await connections.create_issue(owner, repository)
        assert not (tmp_path / "github-issue.json").exists()
    else:
        first = await connections.create_issue(owner, repository)
        assert await connections.create_issue(owner, repository) == first
    assert len(calls) == 2
    assert (tmp_path / "github-issue-intent.json").exists()


@pytest.mark.parametrize("scenario", ["success", "current_changed", "unknown_ack"])
async def test_webhook_url_update_binds_owned_hook_and_preserves_unknown_intent(tmp_path, monkeypatch, scenario):
    from langflow.adlc import harness_demo_sandbox
    from scripts import harness_connections as connections

    repository, calls = "aspiringcoder6/vanguard", []
    new_url = "https://new.example.com/webhooks/github/issues"
    previous = {
        "repository": repository,
        "id": 7,
        "url": "https://old.example.com/webhooks/github/issues",
        "active": True,
        "events": ["issues"],
    }
    connections.private_write(tmp_path / "github-webhook.json", previous)
    monkeypatch.setattr(connections, "PRIVATE", tmp_path)
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", repository)
    monkeypatch.setenv("ADLC_DEMO_GITHUB_WEBHOOK_SECRET", "s" * 40)

    async def cli(argv, *, data=None, **kwargs):
        calls.append(argv)
        assert kwargs["credential_context"] is True
        assert f"repos/{repository}/hooks/7" in argv
        if data is None:
            saved = json.loads((tmp_path / "github-webhook.json").read_bytes())
            result = {key: saved[key] for key in ("id", "url", "active", "events")}
            if scenario == "current_changed":
                result["url"] = "https://unexpected.example.com/webhooks/github/issues"
            return 0, json.dumps(result), ""
        assert json.loads(data) == {
            "config": {"url": new_url, "content_type": "json", "insecure_ssl": "0", "secret": "s" * 40}
        }
        assert "PATCH" in argv
        return (
            (1, "", "unknown")
            if scenario == "unknown_ack"
            else (0, json.dumps({"id": 7, "url": new_url, "active": True, "events": ["issues"]}), "")
        )

    monkeypatch.setattr(harness_demo_sandbox, "process", cli)
    if scenario == "success":
        first = await connections.update_webhook(repository, new_url)
        assert await connections.update_webhook(repository, new_url) == first
        assert len(calls) == 3  # GET/PATCH, then a read-only check without another PATCH.
    elif scenario == "current_changed":
        with pytest.raises(RuntimeError, match="WEBHOOK_CURRENT_CONFIGURATION_CHANGED"):
            await connections.update_webhook(repository, new_url)
        assert len(calls) == 1
    else:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="WEBHOOK_UPDATE_UNCONFIRMED"):
                await connections.update_webhook(repository, new_url)
        assert len(calls) == 2
        assert json.loads((tmp_path / "github-webhook.json").read_bytes()) == previous


@pytest.mark.parametrize(
    ("native_code", "public_code"),
    [
        ("EEXIST", "DEMO_HARNESS_WRITER_LEASE_BLOCKED"),
        ("DEMO_NOT_READY", "DEMO_NOT_READY"),
        ("untrusted diagnostic text", "DEMO_HARNESS_UNAVAILABLE"),
    ],
)
async def test_native_rejection_is_sanitized_and_never_retried(native_code, public_code):
    from langflow.adlc.harness_demo import DemoHarnessClient
    from langflow.adlc.harness_demo_models import DemoError

    calls = []

    def native(request):
        calls.append(request)
        return httpx.Response(409, json={"error_code": native_code})

    client = DemoHarnessClient("http://127.0.0.1:3080", "t" * 40, transport=httpx.MockTransport(native))
    with pytest.raises(DemoError) as failure:
        await client.request("POST", "/jobs", {})
    assert failure.value.code == public_code
    assert len(calls) == 1

"""Bounded backend calls for workflow plugin nodes; no model, healing or write tools."""

# ruff: noqa: EM101, PLR2004, TRY300 - stable public codes, bounded protocol limits, guarded returns.

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from langflow.adlc.project_memory_client import PROTOCOLS, parse_response
from langflow.adlc.project_memory_models import ProjectMemoryError

MAX_BYTES = 262144


class PluginError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryConnection(Closed):
    url: str = "http://10.0.10.195:8011/mcp"
    token: SecretStr = SecretStr("")
    tenant_id: str | None = Field(default=None, min_length=1, max_length=200)
    dataset: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


class ReplayConnection(Closed):
    url: str = "http://10.0.10.195:9099"
    token: SecretStr = SecretStr("")
    session: str = Field(min_length=1, max_length=512)
    api_url: str = Field(min_length=1, max_length=2048)
    email: str = Field(min_length=1, max_length=254)
    password_env: str = Field(default="STAGING_TTEAMFLOW_ADMIN_PASSWORD", pattern=r"^[A-Z][A-Z0-9_]{0,100}$")
    job_timeout_seconds: int = Field(default=120, ge=30, le=600)


def checked_url(value, *, mcp=False):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or "\\" in value
        or (parsed.path != "/mcp" if mcp else parsed.path not in {"", "/"})
    ):
        raise PluginError("WORKFLOW_PLUGIN_CONNECTION_INVALID", 503)
    # HTTP is limited to the supplied VPN service or local deployments. Other
    # deployments must use HTTPS; URLs never come from a task/model tool argument.
    if parsed.scheme == "http" and parsed.hostname not in {"10.0.10.195", "localhost", "127.0.0.1", "::1"}:
        raise PluginError("WORKFLOW_PLUGIN_CONNECTION_INVALID", 503)
    return value.rstrip("/")


class WorkflowPluginClient:
    def __init__(self, *, transport=None):
        self.transport = transport

    async def exchange(self, method, url, *, token="", body=None, headers=None):
        request_headers = {"Accept": "application/json", **(headers or {})}
        if token:
            request_headers["Authorization"] = token if token.startswith("Bearer ") else "Bearer " + token
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport, timeout=20, trust_env=False, follow_redirects=False
                ) as client,
                client.stream(method, url, headers=request_headers, json=body) as response,
            ):
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise PluginError("WORKFLOW_PLUGIN_RESPONSE_TOO_LARGE", 502)
                if response.status_code in {401, 403}:
                    raise PluginError("WORKFLOW_PLUGIN_AUTH_REQUIRED", 503)
                if response.status_code not in {200, 201, 202, 204}:
                    raise PluginError("WORKFLOW_PLUGIN_UPSTREAM_REJECTED", 502)
                return bytes(raw), dict(response.headers)
        except httpx.HTTPError:
            # No automatic retry, especially after a TestForge job-create POST.
            raise PluginError("WORKFLOW_PLUGIN_CONNECTION_LOST", 503) from None

    async def broker(self, path, *, connection=None, body=None):
        base = checked_url(connection.url if connection else "http://10.0.10.195:9099")
        token = connection.token.get_secret_value() if connection else ""
        raw, _ = await self.exchange("GET" if body is None else "POST", base + "/api/v1" + path, token=token, body=body)
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TypeError
            return value
        except (TypeError, ValueError, RecursionError):
            raise PluginError("WORKFLOW_PLUGIN_RESPONSE_INVALID", 502) from None

    async def memory(self, connection=None, *, query=None, top_k=5):
        url = checked_url(connection.url if connection else "http://10.0.10.195:8011/mcp", mcp=True)
        token = connection.token.get_secret_value() if connection else ""
        common = {"Accept": "application/json, text/event-stream"}

        async def rpc(request_id, method, params=None):
            body = {"jsonrpc": "2.0", "method": method}
            if request_id is not None:
                body["id"] = request_id
            if params is not None:
                body["params"] = params
            raw, headers = await self.exchange("POST", url, token=token, body=body, headers=common)
            if request_id is None:
                return {}, headers
            try:
                return parse_response(raw, headers.get("content-type", ""), request_id), headers
            except ProjectMemoryError:
                raise PluginError("WORKFLOW_PLUGIN_MCP_INVALID", 502) from None

        initialized, headers = await rpc(
            1,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "vAIPlatform-workflow-plugins", "version": "0.1.0"},
            },
        )
        protocol = initialized.get("protocolVersion")
        if protocol not in PROTOCOLS:
            raise PluginError("WORKFLOW_PLUGIN_MCP_VERSION_UNSUPPORTED", 502)
        common["MCP-Protocol-Version"] = protocol
        if headers.get("mcp-session-id"):
            session = headers["mcp-session-id"]
            if len(session) > 255 or any(ord(char) < 33 or ord(char) > 126 for char in session):
                raise PluginError("WORKFLOW_PLUGIN_MCP_INVALID", 502)
            common["Mcp-Session-Id"] = session
        await rpc(None, "notifications/initialized")
        listed, _ = await rpc(2, "tools/list")
        tools = listed.get("tools")
        if (
            not isinstance(tools, list)
            or len(tools) > 100
            or listed.get("nextCursor")
            or any(
                not isinstance(tool, dict)
                or not isinstance(tool.get("name"), str)
                or not isinstance(tool.get("inputSchema"), dict)
                for tool in tools
            )
        ):
            raise PluginError("WORKFLOW_PLUGIN_MCP_INVALID", 502)
        recall = next((tool for tool in tools if tool.get("name") == "recall"), None)
        properties = (recall or {}).get("inputSchema", {}).get("properties", {})
        scope_supported = {"query", "search_type", "datasets", "top_k"}.issubset(properties)
        if query is None:
            return {
                "status": "ok",
                "server": initialized.get("serverInfo"),
                "project_scope_supported": scope_supported,
                "tenant_scope_supported": "tenant_id" in properties,
                "tools": [tool.get("name") for tool in tools if isinstance(tool, dict)],
            }
        # Plain Cognee supports a dataset boundary but not tenant_id. ADLC's
        # backend registry binds that one dataset to its owner/flow. An explicitly
        # configured tenant must be enforced; never silently drop it.
        if not scope_supported or (connection.tenant_id and "tenant_id" not in properties):
            raise PluginError("WORKFLOW_PLUGIN_MEMORY_SCOPE_UNSUPPORTED", 503)
        arguments = {"query": query, "search_type": "CHUNKS", "datasets": connection.dataset, "top_k": top_k}
        if connection.tenant_id:
            arguments["tenant_id"] = connection.tenant_id
        if properties["datasets"].get("type") == "array":
            arguments["datasets"] = [connection.dataset]
        if set(recall.get("inputSchema", {}).get("required", [])) - arguments.keys():
            raise PluginError("WORKFLOW_PLUGIN_MEMORY_SCOPE_UNSUPPORTED", 503)
        result, _ = await rpc(3, "tools/call", {"name": "recall", "arguments": arguments})
        if result.get("isError"):
            raise PluginError("WORKFLOW_PLUGIN_MEMORY_READ_FAILED", 502)
        content = result.get("content", [])
        if not isinstance(content, list):
            raise PluginError("WORKFLOW_PLUGIN_RESPONSE_INVALID", 502)
        text = "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
        if len(text.encode()) > 131072:
            raise PluginError("WORKFLOW_PLUGIN_RESPONSE_TOO_LARGE", 502)
        if token:
            text = text.replace(token, "[redacted]")
        return {
            "context": text,
            "dataset": connection.dataset,
            "tenant_id": connection.tenant_id,
            "scope_mode": "TENANT_DATASET" if connection.tenant_id else "ADLC_OWNER_FLOW_DATASET",
            "backend_tenant_enforced": bool(connection.tenant_id),
            "search_type": "CHUNKS",
            "synthesis_requested": False,
            "source_provenance_verified": False,
        }

    async def health(self):
        results = {}
        for name, call in (("testforge", lambda: self.broker("/health")), ("agentmemory", lambda: self.memory())):
            try:
                value = await call()
                results[name] = {"status": "ok" if value.get("status") == "ok" else "error", "data": value}
            except PluginError as exc:
                results[name] = {"status": "error", "error_code": exc.code}
        return results

    async def replay(self, connection):
        if ".." in connection.session or not re.fullmatch(r"[A-Za-z0-9_./\\:-]+", connection.session):
            raise PluginError("WORKFLOW_PLUGIN_REPLAY_SESSION_INVALID", 503)
        parsed = urlsplit(connection.api_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise PluginError("WORKFLOW_PLUGIN_REPLAY_TARGET_INVALID", 503)
        result = await self.broker(
            "/replay",
            connection=connection,
            body={
                "session": connection.session,
                "api_url": connection.api_url,
                "email": connection.email,
                "password_env": connection.password_env,
                "cleanup_template": "",
                "heal": False,
                "fault_locator": [],
                "headed": False,
                "job_timeout_seconds": connection.job_timeout_seconds,
            },
        )
        job_id = result.get("job_id")
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise PluginError("WORKFLOW_PLUGIN_JOB_ACK_INVALID", 502)
        return job_id

    async def job(self, connection, job_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            raise PluginError("WORKFLOW_PLUGIN_JOB_ACK_INVALID", 502)
        value = await self.broker("/result/" + job_id, connection=connection)
        if value.get("job_id", job_id) != job_id or value.get("status") not in {
            "pending",
            "running",
            "completed",
            "failed",
        }:
            raise PluginError("WORKFLOW_PLUGIN_JOB_RESULT_INVALID", 502)
        # Logs and arbitrary evidence URLs can contain credentials or active HTML.
        # Retain only bounded JSON fields; never fetch an upstream-provided URL.
        selected = {
            key: value[key]
            for key in ("job_id", "status", "exit_code", "returncode", "metrics", "result")
            if key in value
        }
        return public_result(selected, token=connection.token.get_secret_value())


def public_result(value, *, token="", depth=0):
    """Retain plain bounded data without common credential fields or URL tokens."""
    if depth > 16:
        raise PluginError("WORKFLOW_PLUGIN_RESPONSE_INVALID", 502)
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if re.search(r"password|token|secret|authorization|credential|api.?key", key, re.IGNORECASE)
            else public_result(item, token=token, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [public_result(item, token=token, depth=depth + 1) for item in value]
    if isinstance(value, str):
        text = value.replace(token, "[redacted]") if token else value
        text = re.sub(r"(?i)([?&](?:token|api_key|password)=)[^&\s]+", r"\1[redacted]", text)
        return re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", text)
    return value

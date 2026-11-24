"""Strict read-only MCP gateway adapter, not a raw Cognee connector.

The operator must review the enforcing backend and bind a separate read-only
credential to each owner/project. Schema claims are compatibility checks, not
proof that an arbitrary server is trustworthy. No built-in remote default.
"""

# ruff: noqa: EM101, TC003, TRY300 - runtime Pydantic types; guarded read-only returns.
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import Field, SecretStr, ValidationError

from langflow.adlc.project_memory_models import (
    GATEWAY,
    MAX_RESPONSE_BYTES,
    GatewayContext,
    GatewayStatus,
    ProjectMemoryError,
    scope_names,
)
from langflow.adlc.verification_models import Closed

PROTOCOLS = {"2025-03-26", "2025-06-18", "2025-11-25"}
MIN_TOKEN_BYTES = 32
MAX_TOKEN_BYTES = 512
MAX_BINDINGS = 32
MAX_TOOLS = 100
MAX_SESSION_CHARS = 255
MAX_JSON_DEPTH = 24


class GatewayBinding(Closed):
    owner_id: UUID
    project_id: UUID
    url: str = Field(max_length=2048)
    token: SecretStr
    backend_revision: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    isolation_reviewed: bool
    no_model_route_reviewed: bool
    retention_reviewed: bool

    def checked(self):
        url = urlsplit(self.url)
        token = self.token.get_secret_value()
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != "/mcp"
            or "%" in self.url
            or "\\" in self.url
            or (url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"})
            or not MIN_TOKEN_BYTES <= len(token.encode()) <= MAX_TOKEN_BYTES
            or any(ord(c) < ord("!") or ord(c) > ord("~") for c in token)
            or not (self.isolation_reviewed and self.no_model_route_reviewed and self.retention_reviewed)
        ):
            raise ProjectMemoryError("MEMORY_GATEWAY_CONFIGURATION_INVALID", 503)
        return self


class GatewayRegistry(Closed):
    schema_version: str = Field(pattern=r"^0\.1$")
    bindings: list[GatewayBinding] = Field(max_length=32)


def load_binding(owner: str, project_id: UUID) -> GatewayBinding:
    value = os.getenv("ADLC_MEMORY_GATEWAY_REGISTRY", "").strip()
    if not value:
        raise ProjectMemoryError("MEMORY_GATEWAY_NOT_CONFIGURED", 503)
    try:
        path = Path(value)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size > 64 * 1024:
            raise ValueError
        with path.open("rb") as handle:
            raw = handle.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ValueError
        registry = GatewayRegistry.model_validate_json(raw)
        scopes, credentials = set(), set()
        for item in registry.bindings:
            item.checked()
            scope = (str(item.owner_id), item.project_id)
            credential = hashlib.sha256(item.token.get_secret_value().encode()).digest()
            if scope in scopes or credential in credentials:
                raise ValueError
            scopes.add(scope)
            credentials.add(credential)
        return next(item for item in registry.bindings if str(item.owner_id) == owner and item.project_id == project_id)
    except StopIteration:
        raise ProjectMemoryError("MEMORY_GATEWAY_NOT_CONFIGURED", 503) from None
    except (OSError, ValueError, RecursionError):
        raise ProjectMemoryError("MEMORY_GATEWAY_CONFIGURATION_INVALID", 503) from None


def parse_response(body: bytes, content_type: str, request_id: int):
    """Match exactly one JSON-RPC response; SSE uses events, not last data line."""
    try:
        text = body.decode("utf-8", errors="strict")
        messages = []
        if content_type.split(";", 1)[0].strip() == "application/json":
            messages = [strict_json(text)]
        elif content_type.split(";", 1)[0].strip() == "text/event-stream":
            for event in text.replace("\r\n", "\n").split("\n\n"):
                data = [line[5:].lstrip(" ") for line in event.split("\n") if line.startswith("data:")]
                if data:
                    messages.append(strict_json("\n".join(data)))
        else:
            raise ValueError
        # Never service server sampling/elicitation requests or follow metadata URLs.
        if any(not isinstance(m, dict) or ("method" in m and "id" in m) for m in messages):
            raise ValueError
        matches = [m for m in messages if m.get("id") == request_id and type(m.get("id")) is int]
        if len(matches) != 1:
            raise ValueError
        match = matches[0]
        if match.get("jsonrpc") != "2.0" or "error" in match or not isinstance(match.get("result"), dict):
            raise ValueError
        return match["result"]
    except (UnicodeError, ValueError, RecursionError):
        raise ProjectMemoryError("MEMORY_PROTOCOL_INVALID", 502) from None


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def constant(_value):
        raise ValueError

    def bounded(value, depth=0):
        if depth > MAX_JSON_DEPTH:
            raise ValueError
        if isinstance(value, dict):
            for child in value.values():
                bounded(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                bounded(child, depth + 1)

    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    bounded(result)
    return result


@dataclass
class MemoryMcpClient:
    binding: GatewayBinding
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)
    session_id: str | None = field(default=None, repr=False)
    protocol: str | None = None
    schemas: dict = field(default_factory=dict, repr=False)
    initialized: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _sequence: int = 0

    async def _exchange(self, payload, *, initialize=False, notification=False):
        headers = {
            "Authorization": "Bearer " + self.binding.token.get_secret_value(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
        }
        if not initialize:
            headers["MCP-Protocol-Version"] = self.protocol
            if self.session_id:
                headers["MCP-Session-Id"] = self.session_id
        try:
            async with (
                httpx.AsyncClient(
                    transport=self.transport, timeout=8, follow_redirects=False, trust_env=False
                ) as client,
                client.stream("POST", self.binding.url, headers=headers, json=payload) as response,
            ):
                if response.status_code == httpx.codes.NOT_FOUND and not initialize:
                    raise ProjectMemoryError("MEMORY_SESSION_EXPIRED", 502)
                if notification:
                    if response.status_code != httpx.codes.ACCEPTED:
                        raise ProjectMemoryError("MEMORY_PROTOCOL_INVALID", 502)
                    return None
                if response.status_code != httpx.codes.OK:
                    raise ProjectMemoryError("MEMORY_GATEWAY_UNAVAILABLE", 503)
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ProjectMemoryError("MEMORY_PROTOCOL_INVALID", 502)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ProjectMemoryError("MEMORY_RESPONSE_TOO_LARGE", 502)
                    data.extend(chunk)
                result = parse_response(bytes(data), response.headers.get("Content-Type", ""), payload["id"])
                if initialize:
                    sid = response.headers.get("MCP-Session-Id")
                    if sid and (
                        len(sid) > MAX_SESSION_CHARS or any(ord(c) < ord("!") or ord(c) > ord("~") for c in sid)
                    ):
                        raise ProjectMemoryError("MEMORY_PROTOCOL_INVALID", 502)
                    self.session_id = sid
                return result
        except (httpx.HTTPError, TimeoutError):
            raise ProjectMemoryError("MEMORY_GATEWAY_UNAVAILABLE", 503) from None

    async def _request(self, method, params, **kwargs):
        self._sequence += 1
        return await self._exchange(
            {"jsonrpc": "2.0", "id": self._sequence, "method": method, "params": params}, **kwargs
        )

    def _reset(self):
        self.session_id, self.protocol, self.initialized = None, None, False
        self.schemas.clear()

    async def _handshake(self):
        self._reset()
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "adlc-project-memory", "version": "0.1.0"},
            },
            initialize=True,
        )
        self.protocol = result.get("protocolVersion")
        policy = result.get("capabilities", {}).get("experimental", {}).get("adlc-memory", {})
        if self.protocol not in PROTOCOLS:
            raise ProjectMemoryError("MEMORY_PROTOCOL_UNSUPPORTED", 502)
        if policy != {
            "gateway_ref": GATEWAY,
            "authenticated_scope": True,
            "read_only": True,
            "models": False,
            "provenance": "adlc-chunks/0.1",
            "backend_revision": self.binding.backend_revision,
        }:
            raise ProjectMemoryError("MEMORY_ISOLATION_UNCONFIRMED", 503)
        # Mandatory even for stateless servers. No best-effort fallback.
        await self._exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}, notification=True)
        listed = await self._request("tools/list", {})
        tools = listed.get("tools")
        if not isinstance(tools, list) or len(tools) > MAX_TOOLS or listed.get("nextCursor"):
            raise ProjectMemoryError("MEMORY_SCOPE_SCHEMA_MISSING", 502)
        self.schemas = {
            t["name"]: t.get("inputSchema") for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)
        }
        for name, required in {
            "recall": {
                "tenant_id": "string",
                "datasets": "string",
                "query": "string",
                "search_type": "string",
                "top_k": "integer",
            },
            "cognify_status": {"tenant_id": "string", "dataset_name": "string"},
        }.items():
            schema = self.schemas.get(name)
            if (
                not isinstance(schema, dict)
                or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
            ):
                raise ProjectMemoryError("MEMORY_SCOPE_SCHEMA_MISSING", 502)
            properties = schema.get("properties", {})
            if any(
                properties.get(k, {}).get("type") != v or k not in schema.get("required", [])
                for k, v in required.items()
            ):
                raise ProjectMemoryError("MEMORY_SCOPE_SCHEMA_MISSING", 502)
            if name == "recall" and "CHUNKS" not in properties["search_type"].get("enum", []):
                raise ProjectMemoryError("MEMORY_SCOPE_SCHEMA_MISSING", 502)
        self.initialized = True

    async def _operation(self, operation, query=None, top_k=5):
        self.binding.checked()
        async with self._lock:
            for retry in range(2):
                try:
                    if not self.initialized:
                        await self._handshake()
                    tenant, dataset = scope_names(str(self.binding.owner_id), self.binding.project_id)
                    if operation == "health":
                        return {
                            "ready": True,
                            "profile_ref": "memory-profile:project-context/0.1.0",
                            "backend_revision": self.binding.backend_revision,
                        }
                    if operation not in {"context", "status"}:
                        raise ProjectMemoryError("MEMORY_OPERATION_NOT_ALLOWED", 403)
                    # Scope is applied AFTER successful handshake/schema validation,
                    # and reapplied after reconnect; caller arguments never pass through.
                    args = {"tenant_id": tenant}
                    if operation == "context":
                        args.update(datasets=dataset, search_type="CHUNKS", query=query, top_k=top_k)
                        name, model = "recall", GatewayContext
                    else:
                        args["dataset_name"] = dataset
                        name, model = "cognify_status", GatewayStatus
                    result = await self._request("tools/call", {"name": name, "arguments": args})
                    if result.get("isError") is True:
                        raise ProjectMemoryError("MEMORY_GATEWAY_REJECTED", 502)
                    projection = model.model_validate(result.get("structuredContent"))
                    if projection.tenant_id != tenant or projection.dataset != dataset:
                        raise ProjectMemoryError("MEMORY_SCOPE_MISMATCH", 502)
                    if operation == "context" and len(projection.chunks) > top_k:
                        raise ProjectMemoryError("MEMORY_RESPONSE_INVALID", 502)
                    return projection
                except ProjectMemoryError as exc:
                    self._reset()
                    if exc.code == "MEMORY_SESSION_EXPIRED" and retry == 0:
                        continue  # Read-only only: no ingestion/mutation retries exist.
                    raise
                except (ValidationError, TypeError, AttributeError, KeyError):
                    self._reset()
                    raise ProjectMemoryError("MEMORY_RESPONSE_INVALID", 502) from None
                except asyncio.CancelledError:
                    self._reset()  # Only the lock owner resets a cancelled exchange.
                    raise
        raise ProjectMemoryError("MEMORY_GATEWAY_UNAVAILABLE", 503)

    async def operation(self, operation, **kwargs):
        if operation not in {"context", "status", "health"}:
            raise ProjectMemoryError("MEMORY_OPERATION_NOT_ALLOWED", 403)
        try:
            return await asyncio.wait_for(self._operation(operation, **kwargs), timeout=30)
        except TimeoutError:
            raise ProjectMemoryError("MEMORY_GATEWAY_UNAVAILABLE", 503) from None


class MemoryClients:
    """Bounded cache; never share a session across owner/project or credential changes."""

    def __init__(self):
        self.clients = OrderedDict()

    def get(self, binding):
        key = hashlib.sha256(binding.model_dump_json().encode()).hexdigest()
        # SecretStr dumps as asterisks, so rotation must also participate in the key.
        key += hashlib.sha256(binding.token.get_secret_value().encode()).hexdigest()
        if key not in self.clients:
            if len(self.clients) >= MAX_BINDINGS:
                self.clients.popitem(last=False)
            self.clients[key] = MemoryMcpClient(binding)
        self.clients.move_to_end(key)
        return self.clients[key]


_clients = MemoryClients()


def get_memory_clients():
    return _clients

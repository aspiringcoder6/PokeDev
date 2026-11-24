"""Enforcing read-only Cognee document gateway. No raw MCP, synthesis or graph indexing.

Only operator-pinned documents in an authenticated owner/project dataset are
read. CHUNKS is the ADLC compatibility projection; ranking here is lexical,
not Cognee vector search. Expiration prevents serving, not physical deletion.
"""

# ruff: noqa: EM101, PLR2004, TC003 - fixed error codes/profile bounds; UUID is a Pydantic runtime type.
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import Field, SecretStr

from langflow.adlc.project_memory_client import PROTOCOLS, strict_json
from langflow.adlc.project_memory_models import GATEWAY, GatewayContext, GatewayStatus, MemoryChunk, scope_names
from langflow.adlc.verification_models import Closed

BACKEND_REVISION = "cognee:1.6.1/c9dcb2c-document-gateway/0.1.0"
LIMIT = 128 * 1024


class DocumentPin(Closed):
    data_id: UUID
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class LocalMemoryBinding(Closed):
    owner_id: UUID
    project_id: UUID
    token: SecretStr
    dataset_id: UUID
    email: str
    password: SecretStr
    documents: list[DocumentPin] = Field(min_length=1, max_length=32)


class LocalMemorySettings(Closed):
    schema_version: str = Field(pattern=r"^0\.1$")
    backend_url: str = Field(pattern=r"^http://127\.0\.0\.1:8010$")
    backend_revision: str = Field(pattern=r"^cognee:1\.6\.1/c9dcb2c-document-gateway/0\.1\.0$")
    bindings: list[LocalMemoryBinding] = Field(min_length=1, max_length=32)


class StoredNote(Closed):
    schema_version: str = Field(pattern=r"^0\.1$")
    owner_id: UUID
    project_id: UUID
    text: str = Field(min_length=1, max_length=8192)
    revision: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    recorded_at: datetime
    expires_at: datetime
    source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class CogneeDocumentReader:
    def __init__(self, settings, *, transport=None):
        self.settings, self.transport = settings, transport
        self.operations = deque(maxlen=128)

    async def documents(self, binding):
        async with httpx.AsyncClient(
            base_url=self.settings.backend_url,
            timeout=8,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            # The only POST is authentication for this exact project account.
            login = await client.post(
                "/api/v1/auth/login",
                data={"username": binding.email, "password": binding.password.get_secret_value()},
            )
            if login.status_code != 200 or len(login.content) > LIMIT:
                raise ValueError("MEMORY_BACKEND_AUTHENTICATION_FAILED")
            token = login.json().get("access_token")
            if not isinstance(token, str) or not 1 <= len(token) <= 4096:
                raise ValueError("MEMORY_BACKEND_RESPONSE_INVALID")
            result = []
            now = datetime.now(timezone.utc)
            for pin in binding.documents:
                path = f"/api/v1/datasets/{binding.dataset_id}/data/{pin.data_id}/raw"
                async with client.stream("GET", path, headers={"Authorization": "Bearer " + token}) as response:
                    if response.status_code != 200:
                        raise ValueError("MEMORY_BACKEND_DOCUMENT_UNAVAILABLE")
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > 16384:
                            raise ValueError("MEMORY_DOCUMENT_TOO_LARGE")
                self.operations.append(
                    {"method": "GET", "dataset_id": str(binding.dataset_id), "data_id": str(pin.data_id)}
                )
                if "sha256:" + hashlib.sha256(raw).hexdigest() != pin.digest:
                    raise ValueError("MEMORY_DOCUMENT_CHANGED")
                note = StoredNote.model_validate(strict_json(raw.decode()))
                if (note.owner_id, note.project_id) != (binding.owner_id, binding.project_id):
                    raise ValueError("MEMORY_BACKEND_SCOPE_MISMATCH")
                if (
                    note.recorded_at.utcoffset() is None
                    or note.expires_at.utcoffset() is None
                    or not note.recorded_at < note.expires_at <= note.recorded_at + timedelta(days=7)
                    or note.recorded_at > now
                ):
                    raise ValueError("MEMORY_RETENTION_INVALID")
                if note.expires_at <= now:
                    continue
                result.append(
                    MemoryChunk(
                        chunk_id=f"{pin.data_id}:0",
                        document_id=str(pin.data_id),
                        revision=note.revision,
                        source_uri=f"urn:cognee:dataset:{binding.dataset_id}:data:{pin.data_id}",
                        document_digest=pin.digest,
                        text=note.text,
                        text_digest="sha256:" + hashlib.sha256(note.text.encode()).hexdigest(),
                        recorded_at=note.recorded_at,
                        expires_at=note.expires_at,
                        source_commit=note.source_commit,
                    )
                )
            return result


def create_gateway(settings, *, reader=None):
    settings = LocalMemorySettings.model_validate(settings)
    tokens, scopes = set(), set()
    for item in settings.bindings:
        secret = item.token.get_secret_value()
        scope = (item.owner_id, item.project_id)
        if len(secret.encode()) < 32 or secret in tokens or scope in scopes:
            raise ValueError("MEMORY_GATEWAY_CONFIGURATION_INVALID")
        tokens.add(secret)
        scopes.add(scope)
    reader = reader or CogneeDocumentReader(settings)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.reader = reader

    def authenticated(request):
        supplied = request.headers.get("authorization", "")
        for item in settings.bindings:
            if hmac.compare_digest(supplied.encode(), ("Bearer " + item.token.get_secret_value()).encode()):
                return item
        raise HTTPException(401, {"code": "MEMORY_GATEWAY_UNAUTHENTICATED"})

    @app.post("/mcp")
    async def mcp(request: Request):
        binding = authenticated(request)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > 16384:
                raise HTTPException(413, {"code": "MEMORY_REQUEST_TOO_LARGE"})
        try:
            command = strict_json(raw.decode())
            if not isinstance(command, dict) or command.get("jsonrpc") != "2.0":
                raise ValueError
            if command == {"jsonrpc": "2.0", "method": "notifications/initialized"}:
                return Response(status_code=202)
            if set(command) != {"jsonrpc", "id", "method", "params"} or type(command["id"]) is not int:
                raise ValueError
            method, params = command["method"], command["params"]
            if method == "initialize":
                if params.get("protocolVersion") not in PROTOCOLS or params.get("capabilities") != {}:
                    raise ValueError
                result = {
                    "protocolVersion": params["protocolVersion"],
                    "serverInfo": {"name": "ADLC Cognee read-only gateway", "version": "0.1.0"},
                    "capabilities": {
                        "tools": {},
                        "experimental": {
                            "adlc-memory": {
                                "gateway_ref": GATEWAY,
                                "authenticated_scope": True,
                                "read_only": True,
                                "models": False,
                                "provenance": "adlc-chunks/0.1",
                                "backend_revision": settings.backend_revision,
                            }
                        },
                    },
                }
            elif method == "tools/list" and params == {}:
                result = {
                    "tools": [
                        {
                            "name": "recall",
                            "description": "Read pinned Cognee docs; lexical ranking only, no model or graph search.",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "tenant_id": {"type": "string"},
                                    "datasets": {"type": "string"},
                                    "query": {"type": "string"},
                                    "search_type": {"type": "string", "enum": ["CHUNKS"]},
                                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                                },
                                "required": ["tenant_id", "datasets", "query", "search_type", "top_k"],
                            },
                        },
                        {
                            "name": "cognify_status",
                            "description": "Stored document availability only; never runs cognify.",
                            "inputSchema": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {"tenant_id": {"type": "string"}, "dataset_name": {"type": "string"}},
                                "required": ["tenant_id", "dataset_name"],
                            },
                        },
                    ]
                }
            elif method == "tools/call" and isinstance(params, dict) and set(params) == {"name", "arguments"}:
                name, args = params["name"], params["arguments"]
                tenant, dataset = scope_names(str(binding.owner_id), binding.project_id)
                if not isinstance(args, dict) or args.get("tenant_id") != tenant:
                    raise ValueError
                base = {
                    "schema_version": "0.1",
                    "gateway_ref": GATEWAY,
                    "tenant_id": tenant,
                    "dataset": dataset,
                    "models_used": False,
                }
                if name == "recall":
                    if (
                        set(args) != {"tenant_id", "datasets", "query", "search_type", "top_k"}
                        or args["datasets"] != dataset
                        or args["search_type"] != "CHUNKS"
                        or not isinstance(args["query"], str)
                        or not 1 <= len(args["query"]) <= 2000
                        or not args["query"].strip()
                        or type(args["top_k"]) is not int
                        or not 1 <= args["top_k"] <= 10
                    ):
                        raise ValueError
                    chunks = await reader.documents(binding)
                    words = set(re.findall(r"\w+", args["query"].lower()))
                    ranked = sorted(
                        chunks, key=lambda c: (-len(words.intersection(re.findall(r"\w+", c.text.lower()))), c.chunk_id)
                    )
                    projection = GatewayContext(
                        **base,
                        chunks=[c for c in ranked if words.intersection(re.findall(r"\w+", c.text.lower()))][
                            : args["top_k"]
                        ],
                    )
                elif (
                    name == "cognify_status"
                    and set(args) == {"tenant_id", "dataset_name"}
                    and args["dataset_name"] == dataset
                ):
                    chunks = await reader.documents(binding)
                    projection = GatewayStatus(**base, state="READY" if chunks else "EMPTY", document_count=len(chunks))
                else:
                    raise ValueError
                result = {"structuredContent": projection.model_dump(mode="json"), "content": [], "isError": False}
            else:
                raise ValueError
            return {"jsonrpc": "2.0", "id": command["id"], "result": result}
        except (ValueError, TypeError, AttributeError, KeyError, httpx.HTTPError):
            raise HTTPException(409, {"code": "MEMORY_GATEWAY_REQUEST_REJECTED"}) from None

    return app


def create_app():
    path = Path(os.environ["ADLC_MEMORY_LOCAL_GATEWAY_CONFIG"])
    if not path.is_absolute() or path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError("MEMORY_GATEWAY_CONFIGURATION_INVALID")
    return create_gateway(json.loads(path.read_bytes()))

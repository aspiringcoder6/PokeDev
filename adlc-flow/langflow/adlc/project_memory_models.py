"""H6C: untrusted, advisory context; never a contract or verification receipt."""

# ruff: noqa: EM101, TRY003, TC001, TC003 - Pydantic runtime types and fixed diagnostics.
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from langflow.adlc.contract_models import Digest
from langflow.adlc.verification_models import Closed, canonical

PROFILE = "memory-profile:project-context/0.1.0"
GATEWAY = "gateway:adlc-memory-readonly/0.1.0"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 200
MEMORY_DOMAIN = b"adlc-project-memory-v1\n"
Id = Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")]
Commit = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]


class ProjectMemoryError(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def scope_names(owner: str, project_id: UUID) -> tuple[str, str]:
    """Names are routing identifiers, not credentials. Never accept names from a caller."""
    tenant = "adlc-owner-" + hashlib.sha256(owner.encode()).hexdigest()
    dataset = "adlc-project-" + hashlib.sha256(f"{owner}\n{project_id}".encode()).hexdigest()
    return tenant, dataset


class MemoryBinding(Closed):
    workflow_run_id: UUID
    project_id: UUID
    base_commit: Commit
    source_ref: Annotated[str, Field(max_length=140)]
    source_task_id: UUID | None = None
    source_attempt_id: UUID | None = None
    source_session_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,255}$")] | None = None

    @model_validator(mode="after")
    def bound_source(self):
        if self.source_ref != f"{self.project_id}/{self.base_commit}":
            raise ValueError("Source reference mismatch.")
        if self.source_session_id and not (self.source_task_id and self.source_attempt_id):
            raise ValueError("A session requires its exact task and attempt.")
        return self


class MemoryQuery(Closed):
    query: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
    top_k: Annotated[int, Field(strict=True, ge=1, le=10)] = 5
    idempotency_key: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")]


class MemoryChunk(Closed):
    chunk_id: Id
    document_id: Id
    revision: Id
    source_uri: Annotated[str, Field(min_length=1, max_length=1024)]
    document_digest: Digest
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    text_digest: Digest
    recorded_at: datetime
    expires_at: datetime
    source_commit: Commit | None = None

    @field_validator("source_uri")
    @classmethod
    def opaque_citation(cls, value):
        # Citations are displayed as text only; no fetch, HTML, file or credential URLs.
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if (
            url.scheme not in {"https", "urn", "adlc"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or any(ord(c) < ord(" ") for c in value)
            or (url.scheme == "https" and not url.hostname)
        ):
            raise ValueError("Invalid citation.")
        return value

    @model_validator(mode="after")
    def provenance(self):
        if self.recorded_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("Provenance dates must include a timezone.")
        if self.expires_at <= self.recorded_at:
            raise ValueError("Invalid retention interval.")
        actual = "sha256:" + hashlib.sha256(self.text.encode()).hexdigest()
        if actual != self.text_digest:
            raise ValueError("Chunk content digest mismatch.")
        return self


class GatewayContext(Closed):
    schema_version: Literal["0.1"]
    gateway_ref: Literal["gateway:adlc-memory-readonly/0.1.0"]
    tenant_id: str
    dataset: str
    models_used: Literal[False]
    chunks: list[MemoryChunk] = Field(max_length=10)


class GatewayStatus(Closed):
    schema_version: Literal["0.1"]
    gateway_ref: Literal["gateway:adlc-memory-readonly/0.1.0"]
    tenant_id: str
    dataset: str
    models_used: Literal[False]
    state: Literal["READY", "EMPTY"]
    document_count: Annotated[int, Field(strict=True, ge=0, le=1_000_000)]


class MemoryRecord(Closed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["memory-profile:project-context/0.1.0"] = PROFILE
    record_id: UUID
    binding: MemoryBinding
    query: Annotated[str, Field(min_length=1, max_length=2000)]
    top_k: Annotated[int, Field(strict=True, ge=1, le=10)]
    tenant_id: str
    dataset: str
    backend_revision: Id
    retrieved_at: datetime
    chunks: list[MemoryChunk] = Field(max_length=10)
    authority: Literal["ADVISORY_UNTRUSTED"] = "ADVISORY_UNTRUSTED"
    verification_evidence: Literal[False] = False
    source_provenance_verified: Literal[False] = False
    models_used: Literal[False] = False

    @model_validator(mode="after")
    def bounds(self):
        if self.retrieved_at.utcoffset() is None or len(self.chunks) > self.top_k:
            raise ValueError("Invalid retrieval.")
        identities = [(c.document_id, c.revision, c.chunk_id) for c in self.chunks]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate chunks.")
        if any(c.recorded_at > self.retrieved_at for c in self.chunks):
            raise ValueError("Future provenance date.")
        if len(canonical(self)) > MAX_RESPONSE_BYTES:
            raise ValueError("Memory record exceeds its limit.")
        return self


class MemoryRead(Closed):
    record: MemoryRecord
    content_digest: Digest


class MemoryCapabilities(Closed):
    profile_ref: Literal["memory-profile:project-context/0.1.0"] = PROFILE
    enabled: bool
    configured: bool
    live_certified: Literal[False] = False
    blockers: list[str]
    synthesis_enabled: Literal[False] = False
    ingestion_enabled: Literal[False] = False
    deletion_enabled: Literal[False] = False


class MemoryView(Closed):
    capabilities: MemoryCapabilities
    binding: MemoryBinding | None
    tenant_id: str | None
    dataset: str | None
    records: list[MemoryRead] = Field(max_length=100)


class MemoryBridgeCommand(Closed):
    session_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,255}$")]
    operation: Literal["context", "status", "health"]
    arguments: MemoryQuery | None = None

    @model_validator(mode="after")
    def operation_arguments(self):
        if (self.operation == "context") != (self.arguments is not None):
            raise ValueError("Only context accepts query arguments.")
        return self

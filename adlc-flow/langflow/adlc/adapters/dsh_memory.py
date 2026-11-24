"""DSH Memory Adapter — persistent memory via vai_agentmemory with Cognee fallback.

This adapter implements the ``MemoryAdapter`` protocol by storing task
context in a remote memory service. The primary backend is the
``vai_agentmemory`` plugin running on the DSH server (accessed via the
DSH SDK). When the DSH backend is unavailable, the adapter falls back
to a Cognee-compatible HTTP API (default: ``http://10.0.10.195:8002/v1``).

Flow:
    ADLC scheduler -> DSHMemoryAdapter.load_context(request)
        -> vai_agentmemory (via DSH SDK) if available
        -> else Cognee HTTP API
    ADLC scheduler -> DSHMemoryAdapter.record_result(request, result)
        -> vai_agentmemory (via DSH SDK) if available
        -> else Cognee HTTP API

This adapter is opt-in: set ``ADLC_MEMORY_ADAPTER=dsh`` to enable. The
``MockMemoryAdapter`` and ``SQLiteMemoryAdapter`` remain the defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from langflow.adlc.adapter_interfaces import MemoryContext
from langflow.adlc.evidence_plane import (
    Evidence,
    EvidencePlaneService,
    EvidenceType,
    ValidationStatus,
    get_default_evidence_plane,
)
from langflow.adlc.harness_dsh_client import DshHarnessClient
from langflow.adlc.models import TaskRequest, TaskResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Stable error codes for DSH memory failures.
ERR_DSH_MEMORY_UNREACHABLE = "DSH_MEMORY_UNREACHABLE"
ERR_COGNEE_UNREACHABLE = "COGNEE_MEMORY_UNREACHABLE"
ERR_MEMORY_STORE_FAILED = "MEMORY_STORE_FAILED"
ERR_MEMORY_RETRIEVE_FAILED = "MEMORY_RETRIEVE_FAILED"


@dataclass(frozen=True, slots=True)
class DSHMemoryConfig:
    """Configuration for the DSHMemoryAdapter."""

    dsh_client: DshHarnessClient | None = None
    cognee_base_url: str = "http://10.0.10.195:8002/v1"
    cognee_api_key: str = ""
    prefer_dsh: bool = True
    timeout_seconds: float = 30.0
    namespace: str = "adlc"


@dataclass(frozen=True, slots=True)
class _StoredRecord:
    """Internal projection of a stored memory record."""

    ref: str
    payload: dict[str, Any]
    stored_at: datetime
    backend: str  # "dsh" | "cognee" | "local"


class DSHMemoryAdapter:
    """MemoryAdapter backed by vai_agentmemory (DSH) with Cognee fallback."""

    service_name = "memory:dsh+cognee"

    def __init__(
        self,
        config: DSHMemoryConfig | None = None,
        evidence_plane: EvidencePlaneService | None = None,
    ) -> None:
        self._config = config or DSHMemoryConfig()
        self._evidence_plane = evidence_plane
        self._local_cache: dict[str, _StoredRecord] = {}

    @property
    def config(self) -> DSHMemoryConfig:
        return self._config

    async def load_context(self, request: TaskRequest) -> MemoryContext:
        """Resolve memory_refs from the request into a MemoryContext.

        Tries vai_agentmemory first, then falls back to Cognee, then to
        the local cache. Returns an empty context if no records are found.
        """
        memory_refs = self._extract_memory_refs(request)
        if not memory_refs:
            return MemoryContext()

        variables: dict[str, Any] = {}
        metadata: dict[str, Any] = {"backend": "none", "resolved": 0}
        for ref in memory_refs:
            record = await self._retrieve_record(ref)
            if record is not None:
                variables[ref] = record.payload.get("payload", record.payload)
                metadata["backend"] = record.backend
                metadata["resolved"] = int(metadata.get("resolved", 0)) + 1
        return MemoryContext(
            memory_refs=tuple(memory_refs),
            variables=variables,
            metadata=metadata,
        )

    async def record_result(
        self,
        request: TaskRequest,
        result: TaskResult,
    ) -> None:
        """Record a completed task attempt for later retrieval."""
        ref = f"{self._config.namespace}:{request.task_run_id}:{uuid4().hex[:8]}"
        record_payload = {
            "ref": ref,
            "task_run_id": str(request.task_run_id),
            "workflow_run_id": str(request.workflow_run_id),
            "task_type": request.task_type,
            "status": result.status.value if hasattr(result.status, "value") else str(result.status),
            "output": result.output,
            "error_code": result.error.code if result.error else None,
            "stored_at": _utc_now().isoformat(),
        }

        backend = "local"
        if self._config.prefer_dsh and self._config.dsh_client is not None:
            try:
                await self._store_dsh(ref, record_payload)
                backend = "dsh"
            except Exception:
                backend = await self._store_cognee(ref, record_payload)
        else:
            backend = await self._store_cognee(ref, record_payload)

        stored = _StoredRecord(
            ref=ref,
            payload=record_payload,
            stored_at=_utc_now(),
            backend=backend,
        )
        self._local_cache[ref] = stored
        await self._submit_evidence(request, stored)

    async def _retrieve_record(self, ref: str) -> _StoredRecord | None:
        """Retrieve a record, trying vai_agentmemory then Cognee then local cache."""
        cached = self._local_cache.get(ref)
        if cached is not None:
            return cached

        payload: dict[str, Any] | None = None
        if self._config.prefer_dsh and self._config.dsh_client is not None:
            payload = await self._retrieve_dsh(ref)
        if payload is None:
            payload = await self._retrieve_cognee(ref)
        if payload is not None:
            stored = _StoredRecord(
                ref=ref,
                payload=payload,
                stored_at=datetime.fromisoformat(payload["stored_at"])
                if "stored_at" in payload
                else _utc_now(),
                backend="dsh" if self._config.prefer_dsh else "cognee",
            )
            self._local_cache[ref] = stored
            return stored
        return None

    @staticmethod
    def _extract_memory_refs(request: TaskRequest) -> list[str]:
        """Extract memory_refs from the task request context."""
        context = request.context or {}
        refs = context.get("memory_refs", [])
        if isinstance(refs, list):
            return [str(ref) for ref in refs if isinstance(ref, (str, UUID))]
        if isinstance(refs, str):
            return [refs]
        return []

    async def _store_dsh(self, ref: str, payload: dict[str, Any]) -> None:
        """Store a record via the vai_agentmemory plugin (DSH SDK)."""
        import asyncio

        client = self._config.dsh_client
        if client is None:
            raise RuntimeError("DSH client not configured")
        await asyncio.to_thread(
            _sync_dsh_post,
            client,
            "/vai-agentmemory/store",
            {"ref": ref, "payload": payload},
        )

    async def _retrieve_dsh(self, ref: str) -> dict[str, Any] | None:
        """Retrieve a record via the vai_agentmemory plugin (DSH SDK)."""
        import asyncio

        client = self._config.dsh_client
        if client is None:
            return None
        try:
            response = await asyncio.to_thread(
                _sync_dsh_get,
                client,
                f"/vai-agentmemory/retrieve?ref={ref}",
            )
            if isinstance(response, dict):
                return response
        except Exception:
            return None
        return None

    async def _store_cognee(self, ref: str, payload: dict[str, Any]) -> str:
        """Store a record via the Cognee HTTP API. Returns 'cognee' on success."""
        import asyncio

        try:
            await asyncio.to_thread(
                _sync_cognee_post,
                self._config.cognee_base_url,
                self._config.cognee_api_key,
                "/memory/store",
                {"ref": ref, "payload": payload},
                self._config.timeout_seconds,
            )
            return "cognee"
        except Exception:
            return "local"

    async def _retrieve_cognee(self, ref: str) -> dict[str, Any] | None:
        """Retrieve a record via the Cognee HTTP API."""
        import asyncio

        try:
            response = await asyncio.to_thread(
                _sync_cognee_get,
                self._config.cognee_base_url,
                self._config.cognee_api_key,
                f"/memory/retrieve?ref={ref}",
                self._config.timeout_seconds,
            )
            if isinstance(response, dict):
                return response
        except Exception:
            return None
        return None

    async def _submit_evidence(
        self,
        request: TaskRequest,
        stored: _StoredRecord,
    ) -> None:
        """Submit a memory_record evidence entry to the Evidence Plane."""
        if self._evidence_plane is None:
            self._evidence_plane = get_default_evidence_plane()
        evidence = Evidence(
            evidence_id=uuid4(),
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
            evidence_type=EvidenceType.METRIC,
            validation_status=ValidationStatus.VALID,
            producer=self.service_name,
            payload={
                "ref": stored.ref,
                "backend": stored.backend,
                "stored_at": stored.stored_at.isoformat(),
                "kind": "memory_record",
            },
            submitted_at=_utc_now(),
        )
        self._evidence_plane.submit_evidence(evidence)


# ---- Synchronous HTTP helpers (run in thread pool) -----------------------


def _sync_dsh_post(client: DshHarnessClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Post to a DSH plugin route via the underlying SDK client."""
    import asyncio

    return asyncio.run(client._dsh.http_post(path, body))  # noqa: SLF001


def _sync_dsh_get(client: DshHarnessClient, path: str) -> dict[str, Any]:
    """Get a DSH plugin route via the underlying SDK client."""
    import asyncio

    return asyncio.run(client._dsh.http_get(path))  # noqa: SLF001


def _sync_cognee_post(
    base_url: str,
    api_key: str,
    path: str,
    body: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Post to the Cognee HTTP API."""
    import urllib.request

    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _sync_cognee_get(
    base_url: str,
    api_key: str,
    path: str,
    timeout: float,
) -> dict[str, Any]:
    """Get from the Cognee HTTP API."""
    import urllib.request

    url = f"{base_url.rstrip('/')}{path}"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


__all__ = [
    "DSHMemoryAdapter",
    "DSHMemoryConfig",
    "ERR_DSH_MEMORY_UNREACHABLE",
    "ERR_COGNEE_UNREACHABLE",
    "ERR_MEMORY_STORE_FAILED",
    "ERR_MEMORY_RETRIEVE_FAILED",
]

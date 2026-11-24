# ruff: noqa: INP001, S101, S106, S108, PLR2004, SLF001

"""Unit tests for the DSHMemoryAdapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.adapters.dsh_memory import (
    DSHMemoryAdapter,
    DSHMemoryConfig,
)
from langflow.adlc.models import (
    ExecutorTarget,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _FakeDshSdk:
    """Fake of the underlying dsh_web_sdk.DshClient."""

    store_payloads: list[dict[str, Any]] = field(default_factory=list)
    retrieve_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    store_error: Exception | None = None
    retrieve_error: Exception | None = None

    async def http_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path == "/vai-agentmemory/store":
            self.store_payloads.append(body)
            if self.store_error is not None:
                raise self.store_error
            return {"ok": True}
        raise NotImplementedError(path)

    async def http_get(self, path: str) -> dict[str, Any] | None:
        if path.startswith("/vai-agentmemory/retrieve"):
            ref = path.split("ref=")[-1]
            if self.retrieve_error is not None:
                raise self.retrieve_error
            return self.retrieve_payloads.get(ref)
        raise NotImplementedError(path)


@dataclass
class _FakeDshClient:
    """Minimal fake of DshHarnessClient for memory adapter tests."""

    _dsh: _FakeDshSdk = field(default_factory=_FakeDshSdk)


def _request() -> TaskRequest:
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="code_generation",
        name="Test task",
        executor=ExecutorTarget(service="agent-provider:dsh", operation="execute_task"),
        input={"spec": "test"},
        dependency_task_run_ids=[],
        idempotency_key="run-1:task-1:attempt-1",
        requested_at=_utc_now(),
    )


def _result() -> TaskResult:
    return TaskResult(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        status=TaskResultStatus.SUCCEEDED,
        output={"summary": "done"},
        artifacts=[],
        error=None,
        metrics=TaskMetrics(duration_ms=100),
        started_at=_utc_now(),
        completed_at=_utc_now(),
    )


def _adapter(
    *,
    dsh_client: _FakeDshClient | None = None,
    prefer_dsh: bool = True,
    cognee_base_url: str = "http://cognee.test/v1",
) -> DSHMemoryAdapter:
    config = DSHMemoryConfig(
        dsh_client=dsh_client,  # type: ignore[arg-type]
        prefer_dsh=prefer_dsh,
        cognee_base_url=cognee_base_url,
    )
    return DSHMemoryAdapter(config=config)


async def test_record_result_stores_via_dsh_when_available() -> None:
    client = _FakeDshClient()
    adapter = _adapter(dsh_client=client)

    await adapter.record_result(_request(), _result())

    assert len(client._dsh.store_payloads) == 1
    stored = client._dsh.store_payloads[0]
    assert stored["payload"]["task_type"] == "code_generation"
    assert stored["payload"]["status"] == "SUCCEEDED"


async def test_record_result_falls_back_to_local_when_dsh_fails() -> None:
    client = _FakeDshClient()
    client._dsh.store_error = RuntimeError("DSH down")
    adapter = _adapter(dsh_client=client)

    await adapter.record_result(_request(), _result())

    # DSH was attempted but failed; no Cognee configured, so local cache only.
    assert len(client._dsh.store_payloads) == 1
    assert len(adapter._local_cache) == 1  # noqa: SLF001


async def test_record_result_uses_cognee_when_dsh_disabled() -> None:
    """When prefer_dsh=False, Cognee is used directly (no DSH call)."""
    adapter = _adapter(dsh_client=None, prefer_dsh=False)

    # Cognee is unreachable in tests, so it falls back to local.
    await adapter.record_result(_request(), _result())

    assert len(adapter._local_cache) == 1  # noqa: SLF001


async def test_load_context_returns_empty_when_no_refs() -> None:
    adapter = _adapter()

    context = await adapter.load_context(_request())

    assert context.memory_refs == ()
    assert context.variables == {}


async def test_load_context_resolves_from_local_cache() -> None:
    adapter = _adapter()
    request = _request()
    await adapter.record_result(request, _result())
    ref = next(iter(adapter._local_cache))  # noqa: SLF001

    # Build a request with memory_refs in context.
    request_with_refs = request.model_copy(
        update={"context": {"memory_refs": [ref]}},
    )

    context = await adapter.load_context(request_with_refs)

    assert ref in context.variables
    assert context.metadata["backend"] in ("dsh", "local")


async def test_load_context_resolves_from_dsh_when_not_cached() -> None:
    client = _FakeDshClient()
    client._dsh.retrieve_payloads = {
        "remote-ref-1": {
            "ref": "remote-ref-1",
            "payload": {"hint": "from DSH"},
            "stored_at": _utc_now().isoformat(),
        }
    }
    adapter = _adapter(dsh_client=client)
    request = _request().model_copy(
        update={"context": {"memory_refs": ["remote-ref-1"]}},
    )

    context = await adapter.load_context(request)

    assert "remote-ref-1" in context.variables
    assert context.variables["remote-ref-1"]["hint"] == "from DSH"


async def test_load_context_returns_empty_when_ref_not_found() -> None:
    client = _FakeDshClient()
    client._dsh.retrieve_payloads = {}
    adapter = _adapter(dsh_client=client)
    request = _request().model_copy(
        update={"context": {"memory_refs": ["missing-ref"]}},
    )

    context = await adapter.load_context(request)

    assert context.variables == {}


async def test_extract_memory_refs_handles_string() -> None:
    adapter = _adapter()
    request = _request().model_copy(
        update={"context": {"memory_refs": "single-ref"}},
    )

    context = await adapter.load_context(request)

    # Single string ref is wrapped in a list internally.
    assert context.memory_refs == ("single-ref",)


async def test_extract_memory_refs_handles_uuid_list() -> None:
    adapter = _adapter()
    ref_uuid = uuid4()
    request = _request().model_copy(
        update={"context": {"memory_refs": [ref_uuid]}},
    )

    context = await adapter.load_context(request)

    assert context.memory_refs == (str(ref_uuid),)


async def test_extract_memory_refs_handles_missing_context() -> None:
    adapter = _adapter()

    context = await adapter.load_context(_request())

    assert context.memory_refs == ()


async def test_record_result_includes_error_code_when_failed() -> None:
    client = _FakeDshClient()
    adapter = _adapter(dsh_client=client)
    failed_result = _result().model_copy(
        update={
            "status": TaskResultStatus.FAILED,
            "error": ServiceError(
                error_id=uuid4(),
                code="TEST_FAILURE",
                category="EXECUTION",
                message="test failed",
                retryable=False,
                service="test",
                occurred_at=_utc_now(),
            ),
        },
    )

    await adapter.record_result(_request(), failed_result)

    stored = client._dsh.store_payloads[0]
    assert stored["payload"]["status"] == "FAILED"
    assert stored["payload"]["error_code"] == "TEST_FAILURE"


async def test_config_defaults() -> None:
    config = DSHMemoryConfig()
    assert config.cognee_base_url == "http://10.0.10.195:8002/v1"
    assert config.prefer_dsh is True
    assert config.namespace == "adlc"
    assert config.dsh_client is None


async def test_service_name() -> None:
    adapter = _adapter()
    assert adapter.service_name == "memory:dsh+cognee"

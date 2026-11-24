# ruff: noqa: INP001, S101, S106, PLR2004
"""H4A: real Git/runtime bytes through preview, signed acceptance and restart."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.harness_artifacts import HarnessArtifactImporter
from langflow.adlc.harness_attempts import SqliteTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackError, HarnessCallbackReceiver, HarnessCallbackSettings
from langflow.adlc.harness_client import HarnessClientError, HarnessHttpClient, HarnessServerSettings
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.harness_models import (
    HarnessArtifactRead,
    HarnessResultDelivery,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionReceipt,
)
from langflow.adlc.legacy_flow_normalizer import AdlcTaskDefinition, MockArtifactSpec
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import CreateWorkflowRunRequest, ExecutorTarget, WorkflowRunStatus
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user

ROOT = Path(__file__).resolve().parents[4]


async def _real_capture(directory, request):
    executable = shutil.which("node")
    assert executable is not None
    script = ROOT / "agent-harness-server/deepseek-harness/scripts/create-adlc-artifact-test-result.mjs"
    process = await asyncio.create_subprocess_exec(
        executable,
        str(script),
        str(directory),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(request.model_dump_json().encode()), timeout=30)
    assert process.returncode == 0, stderr.decode()
    return json.loads(stdout)


class _Client:
    def __init__(self, directory):
        self.directory = directory
        self.artifact_calls = 0
        self.create_calls = 0
        self.submit_calls = 0
        self.callbacks = None
        self.packet = None

    async def create_session(self, request):
        self.create_calls += 1
        self.packet = await _real_capture(self.directory, request)
        self.session = HarnessSessionRead.model_validate(self.packet["preview"])
        return HarnessSessionAccepted(session=self.session)

    async def get_session(self, session_id):
        assert session_id == self.session.session_id
        return self.session.model_copy(deep=True)

    async def get_artifact(self, session_id, artifact_id):
        self.artifact_calls += 1
        assert session_id == self.session.session_id
        assert artifact_id == self.packet["artifact_read"]["artifact"]["artifact_id"]
        return HarnessArtifactRead.model_validate(self.packet["artifact_read"])

    async def submit_session(self, session_id):
        self.submit_calls += 1
        delivery = self.packet["delivered"]
        headers = delivery["headers"]
        await self.callbacks.receive(
            delivery["body"].encode(),
            delivery_id=headers["x-adlc-delivery-id"],
            timestamp=headers["x-adlc-timestamp"],
            signature=headers["x-adlc-signature"],
        )
        self.session.status = HarnessSessionStatus.SUCCEEDED
        envelope = HarnessResultDelivery.model_validate_json(delivery["body"])
        return HarnessSubmissionReceipt(
            session_id=session_id,
            status="DELIVERING",
            delivery_id=envelope.delivery_id,
            delivery_status="PENDING",
            replayed=False,
        )

    async def cancel_session(self, _session_id):
        message = "A restart or preview must not cancel the remote session"
        raise AssertionError(message)


def _compose(directory, client, clock):
    payloads = BoundedArtifactPayloadStore(database_path=directory / "runs.sqlite3", now=lambda: clock[0])
    callbacks = HarnessCallbackReceiver(
        HarnessCallbackSettings(secret="test-callback-secret"),
        attempts=SqliteTaskAttemptRepository(directory / "attempts.sqlite3"),
        artifact_importer=HarnessArtifactImporter(payloads, client),
    )
    if client is not None:
        client.callbacks = callbacks
    routes = (
        {}
        if client is None
        else {
            DeepSeekHarnessTaskExecutor.service_name: DeepSeekHarnessTaskExecutor(
                client, callbacks, status_poll_interval_seconds=0.01
            )
        }
    )
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes=routes),
        repository=SqliteRunRepository(directory / "runs.sqlite3"),
        artifact_payloads=payloads,
        harness_callbacks=callbacks,
    )
    return service, callbacks, payloads


def _app(owner, service, callbacks, client):
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=owner[0])
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[adlc_api.get_harness_callback_receiver] = lambda: callbacks
    app.dependency_overrides[adlc_api.get_harness_client] = lambda: client
    return app


async def _until(service, run_id, owner, status):
    async def wait():
        while True:
            snapshot = await service.get_run(run_id, owner_id=str(owner))
            if snapshot.status is status:
                return snapshot
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(wait(), timeout=15)


@pytest.mark.skipif(
    not (ROOT / "agent-harness-server/deepseek-harness/scripts/create-adlc-artifact-test-result.mjs").is_file(),
    reason="Requires the companion Harness Git artifact capture fixture.",
)
async def test_real_git_patch_preview_submit_offline_archive_and_restart(tmp_path):
    clock = [datetime.now(timezone.utc)]
    client = _Client(tmp_path / "node")
    first, callbacks, _ = _compose(tmp_path, client, clock)
    package = json.loads(
        (ROOT / "adlc_components/packages/coding-agent-deepseek-harness/0.3.2/package.json").read_text()
    )
    definition = AdlcTaskDefinition(
        id=uuid4(),
        key="coding",
        name="H4A actual patch",
        task_type="coding",
        dependencies=[],
        predetermined_output={},
        artifact=MockArtifactSpec(kind="SOURCE_PATCH", name="source-patch", media_type="application/json", content=""),
        executor_target=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        constraints={"timeout_ms": 60_000},
        request_metadata={"resolved_configuration": package["defaults"]},
    )
    owner = [uuid4()]
    original_owner = owner[0]
    flow_id = uuid4()
    run = await first.start_run(
        flow_id=flow_id,
        flow_name="H4A hermetic integration",
        definitions=[definition],
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id=str(owner[0]),
    )
    waiting = await _until(first, run.id, owner[0], WorkflowRunStatus.WAITING_APPROVAL)
    session = client.session
    artifact = session.result.artifacts[0]
    # A valid signature is insufficient: bytes must be retained before acceptance.
    bad_read = HarnessArtifactRead.model_validate(client.packet["artifact_read"])
    bad_read.payload_base64 = base64.b64encode(b"not the captured patch").decode()
    original_read = client.get_artifact
    client.get_artifact = AsyncMock(return_value=bad_read)
    delivery = client.packet["delivered"]
    with pytest.raises(HarnessCallbackError) as refusal:
        await callbacks.receive(
            delivery["body"].encode(),
            delivery_id=delivery["headers"]["x-adlc-delivery-id"],
            timestamp=delivery["headers"]["x-adlc-timestamp"],
            signature=delivery["headers"]["x-adlc-signature"],
        )
    assert refusal.value.code == "HARNESS_ARTIFACT_CHECKSUM_MISMATCH"
    assert (await callbacks.attempts.get(artifact.attempt_id)).result is None
    assert callbacks.artifact_importer.payloads.total_bytes == 0
    prefix = f"/api/v1/adlc/runs/{run.id}"
    preview_path = f"{prefix}/harness-sessions/{session.session_id}/artifacts/{artifact.artifact_id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(owner, first, callbacks, client)), base_url="http://test"
    ) as api:
        denied_submit = await api.post(f"{prefix}/harness-sessions/{session.session_id}/submit")
        assert denied_submit.status_code == 503
        assert client.submit_calls == 0
        client.get_artifact = original_read
        preview = await api.get(preview_path)
        assert preview.status_code == 200, preview.text
        assert preview.headers["cache-control"] == "no-store"
        assert "+actual agent edit" in preview.json()["files"][0]["patch"]
        assert [item["file"] for item in preview.json()["files"]] == ["DEPLOYMENT.md", "docs/architecture.md"]
        assert preview.json()["base_commit"] == artifact.metadata["base_commit"]
        assert (await callbacks.attempts.get(artifact.attempt_id)).result is None
        assert client.submit_calls == 0
        assert (await api.get(f"{prefix}/artifacts/{artifact.artifact_id}")).status_code == 404
        owner[0] = uuid4()
        assert (await api.get(preview_path)).status_code == 404
        owner[0] = original_owner
        assert client.artifact_calls == 1
    await first.shutdown()

    second, callbacks, _ = _compose(tmp_path, client, clock)
    await second.recover()
    restored = await _until(second, run.id, owner[0], WorkflowRunStatus.WAITING_APPROVAL)
    assert restored.tasks[0].current_attempt_id == waiting.tasks[0].current_attempt_id
    assert client.create_calls == 1
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(owner, second, callbacks, client)), base_url="http://test"
    ) as api:
        assert (await api.get(preview_path)).status_code == 200
        assert client.artifact_calls == 1  # Restore never renews expiry or fetches a replacement.
        submitted = await api.post(f"{prefix}/harness-sessions/{session.session_id}/submit")
        assert submitted.status_code == 202, submitted.text
    completed = await _until(second, run.id, owner[0], WorkflowRunStatus.SUCCEEDED)
    assert completed.tasks[0].current_attempt_id == waiting.tasks[0].current_attempt_id
    assert client.create_calls == client.submit_calls == 1
    await second.shutdown()

    third, offline_callbacks, _ = _compose(tmp_path, None, clock)
    await third.recover()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(owner, third, offline_callbacks, None)), base_url="http://test"
    ) as api:
        saved = await api.get(f"{prefix}/artifacts/{artifact.artifact_id}")
        assert saved.status_code == 200, saved.text
        assert saved.json()["artifact"]["checksum"]["value"] == artifact.checksum.value
        archive = await api.get(f"{prefix}/harness-results")
        assert archive.status_code == 200
        assert archive.json()[0]["result"]["artifacts"][0]["artifact_id"] == str(artifact.artifact_id)
    # A duplicate callback is acknowledged without a live server, even after restart.
    delivered = client.packet["delivered"]
    receipt = await offline_callbacks.receive(
        delivered["body"].encode(),
        delivery_id=delivered["headers"]["x-adlc-delivery-id"],
        timestamp=delivered["headers"]["x-adlc-timestamp"],
        signature=delivered["headers"]["x-adlc-signature"],
    )
    assert receipt.duplicate
    await third.shutdown()
    clock[0] += timedelta(hours=25)
    expired, expired_callbacks, _ = _compose(tmp_path, None, clock)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(owner, expired, expired_callbacks, None)), base_url="http://test"
    ) as api:
        assert (await api.get(f"{prefix}/artifacts/{artifact.artifact_id}")).status_code == 410
        assert (await api.get(f"{prefix}/harness-results")).status_code == 200
    await expired.shutdown()


def _patch_projection(producer_version="0.1.0"):
    now = datetime.now(timezone.utc)
    correlation = {name: str(uuid4()) for name in ["request_id", "workflow_run_id", "task_run_id", "attempt_id"]}
    artifact_id = str(uuid4())
    snapshot = {
        "format": "harness-git-diff-v1",
        "base_commit": "a" * 40,
        "files": [{"file": "README.md", "patch": "+safe\n", "additions": 1, "deletions": 0}],
        "reported_files": ["README.md"],
    }
    payload = json.dumps(snapshot).encode()
    artifact = {
        "artifact_id": artifact_id,
        "workflow_run_id": correlation["workflow_run_id"],
        "task_run_id": correlation["task_run_id"],
        "attempt_id": correlation["attempt_id"],
        "kind": "SOURCE_PATCH",
        "name": "patch.json",
        "media_type": "application/json",
        "uri": f"adlc://runs/{correlation['workflow_run_id']}/artifacts/{artifact_id}",
        "size_bytes": len(payload),
        "checksum": {"algorithm": "SHA256", "value": hashlib.sha256(payload).hexdigest()},
        "producer": f"plugin:vai-adlc-artifacts-git/{producer_version}",
        "created_at": now,
        "expires_at": now + timedelta(hours=24),
        "metadata": {
            "capture": "harness-git-diff",
            "format": "harness-git-diff-v1",
            "base_commit": "a" * 40,
            "file_count": 1,
        },
    }
    return HarnessArtifactRead.model_validate(
        {
            "session_id": "session",
            "correlation": correlation,
            "artifact": artifact,
            "payload_base64": base64.b64encode(payload).decode(),
        }
    )


def _patch_result(projection, *, lock_version=None, required=True):
    return HarnessSessionResult(
        session_id=projection.session_id,
        correlation=projection.correlation,
        status="SUCCEEDED",
        output={},
        artifacts=[projection.artifact],
        plugin_lock=[
            {
                "plugin_id": "vai-adlc-artifacts-git",
                "version": lock_version or projection.artifact.producer.rsplit("/", 1)[1],
                "content_digest": "sha256:" + "a" * 64,
                "required": required,
            }
        ],
        error=None,
        started_at=projection.artifact.created_at,
        completed_at=projection.artifact.created_at,
    )


@pytest.mark.parametrize("producer_version", ["0.1.0", "0.1.1", "0.2.0"])
@pytest.mark.parametrize(
    "mutation", ["checksum", "correlation", "size", "base64", "path", "producer", "unknown-version", "uri"]
)
async def test_importer_rejects_untrusted_or_mismatched_bytes_before_retention(mutation, producer_version):
    projection = _patch_projection(producer_version)
    if mutation == "path":
        snapshot = json.loads(base64.b64decode(projection.payload_base64))
        snapshot["files"][0]["file"] = "../escape"
        payload = json.dumps(snapshot).encode()
        projection.payload_base64 = base64.b64encode(payload).decode()
        projection.artifact.size_bytes = len(payload)
        projection.artifact.checksum.value = hashlib.sha256(payload).hexdigest()
    if mutation == "checksum":
        projection.payload_base64 = base64.b64encode(b"other").decode()
    if mutation == "correlation":
        projection.correlation.attempt_id = uuid4()
    if mutation == "size":
        projection.artifact.size_bytes += 1
    if mutation == "base64":
        projection.payload_base64 = "not base64!"
    descriptor = projection.artifact.model_copy(deep=True)
    if mutation == "producer":
        descriptor.producer = "agent-self-report"
    if mutation == "unknown-version":
        descriptor.producer = "plugin:vai-adlc-artifacts-git/9.9.9"
    if mutation == "uri":
        descriptor.uri = "http://untrusted.invalid/secret"
    client = SimpleNamespace(get_artifact=AsyncMock(return_value=projection))
    store = BoundedArtifactPayloadStore()
    importer = HarnessArtifactImporter(store, client)
    with pytest.raises(HarnessClientError):
        await importer.read("session", projection.correlation, descriptor)
    assert store.total_bytes == 0


@pytest.mark.parametrize("producer_version", ["0.1.0", "0.1.1", "0.2.0"])
async def test_supported_collector_versions_are_retained_and_remain_readable_offline(producer_version):
    projection = _patch_projection(producer_version)
    client = SimpleNamespace(get_artifact=AsyncMock(return_value=projection))
    store = BoundedArtifactPayloadStore()
    importer = HarnessArtifactImporter(store, client)
    await importer.import_result(_patch_result(projection))
    assert client.get_artifact.await_count == 1
    offline = HarnessArtifactImporter(store, None)
    saved = await offline.read(projection.session_id, projection.correlation, projection.artifact)
    assert saved.files[0].patch == "+safe\n"
    assert saved.artifact.producer == f"plugin:vai-adlc-artifacts-git/{producer_version}"


@pytest.mark.parametrize("mutation", ["wrong-version", "missing-lock", "optional-lock"])
async def test_result_import_requires_the_artifact_producer_to_match_a_required_collector_lock(mutation):
    projection = _patch_projection("0.1.1")
    result = _patch_result(
        projection,
        lock_version="0.1.0" if mutation == "wrong-version" else "0.1.1",
        required=mutation != "optional-lock",
    )
    if mutation == "missing-lock":
        result.plugin_lock = []
    client = SimpleNamespace(get_artifact=AsyncMock(return_value=projection))
    store = BoundedArtifactPayloadStore()
    importer = HarnessArtifactImporter(store, client)
    with pytest.raises(HarnessClientError, match="HARNESS_ARTIFACT_PRODUCER_MISMATCH"):
        await importer.import_result(result)
    client.get_artifact.assert_not_awaited()
    assert store.total_bytes == 0


@pytest.mark.parametrize(
    ("status_code", "body", "code"),
    [
        (410, b"{}", "HARNESS_ARTIFACT_EXPIRED"),
        (401, b"{}", "HARNESS_SERVER_AUTHENTICATION_FAILED"),
        (200, b"x" * (768 * 1024 + 1), "HARNESS_ARTIFACT_RESPONSE_TOO_LARGE"),
    ],
    ids=["expired", "unauthenticated", "oversized"],
)
async def test_artifact_http_read_is_authenticated_bounded_and_never_follows_a_result_uri(status_code, body, code):
    def handler(request):
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/api/v1/adlc-harness/sessions/session/artifacts/artifact"
        return httpx.Response(status_code, content=body)

    client = HarnessHttpClient(HarnessServerSettings(api_token="test-token"), transport=httpx.MockTransport(handler))
    client._session_roots["session"] = "/api/v1/adlc-harness"  # noqa: SLF001 - isolate the artifact HTTP boundary.
    with pytest.raises(HarnessClientError, match=code):
        await client.get_artifact("session", "artifact")
    await client.close()

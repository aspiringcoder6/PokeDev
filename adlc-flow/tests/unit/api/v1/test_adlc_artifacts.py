# ruff: noqa: S101

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore, SourcePatchSnapshot
from langflow.adlc.legacy_flow_normalizer import normalize_legacy_flow_graph
from langflow.adlc.models import Artifact, Checksum, CreateWorkflowRunRequest
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user


async def _run_with_patch(store: BoundedArtifactPayloadStore, owner_id: str) -> tuple[AdlcRunService, Artifact]:
    service = AdlcRunService(artifact_payloads=store)
    flow_id = uuid4()
    definitions = normalize_legacy_flow_graph(
        flow_id,
        {"nodes": [{"id": "implement", "type": "genericNode", "data": {"type": "Implement"}}], "edges": []},
    )
    run = await service.start_run(
        flow_id=flow_id,
        flow_name="Artifact review",
        definitions=definitions,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
        owner_id=owner_id,
    )
    task = service._runs[run.id].run.tasks[0]  # noqa: SLF001 - seed the read boundary after a real scheduled run.
    snapshot = SourcePatchSnapshot(
        format="opencode-vcs-diff-v1",
        files=[
            {
                "file": "README.md",
                "patch": "--- a/README.md\n+++ b/README.md\n-old\n+new\n",
                "additions": 1,
                "deletions": 1,
            }
        ],
        reported_files=["README.md"],
    )
    payload = snapshot.model_dump_json().encode()
    artifact_id = uuid4()
    artifact = Artifact(
        artifact_id=artifact_id,
        workflow_run_id=run.id,
        task_run_id=task.id,
        attempt_id=task.current_attempt_id,
        kind="SOURCE_PATCH",
        name="source-patch.json",
        media_type="application/vnd.opencode.vcs-diff+json",
        uri=f"adlc://runs/{run.id}/artifacts/{artifact_id}",
        size_bytes=len(payload),
        checksum=Checksum(value=hashlib.sha256(payload).hexdigest()),
        producer="agent-provider:opencode",
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    store.retain(artifact, payload)
    task.artifacts.append(artifact)
    return service, artifact


async def test_patch_route_checks_run_ownership_and_returns_review_payload() -> None:
    owner_id = uuid4()
    viewer = [owner_id]
    store = BoundedArtifactPayloadStore()
    service, artifact = await _run_with_patch(store, str(owner_id))
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=viewer[0])
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service
    path = f"/api/v1/adlc/runs/{artifact.workflow_run_id}/artifacts/{artifact.artifact_id}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        owned = await client.get(path)
        viewer[0] = uuid4()
        foreign = await client.get(path)
        viewer[0] = owner_id
        missing = await client.get(f"/api/v1/adlc/runs/{artifact.workflow_run_id}/artifacts/{uuid4()}")

    assert owned.status_code == status.HTTP_200_OK
    assert owned.headers["cache-control"] == "no-store"
    assert owned.json()["artifact"]["checksum"]["value"] == artifact.checksum.value
    assert owned.json()["files"][0]["file"] == "README.md"
    assert "+new" in owned.json()["files"][0]["patch"]
    assert foreign.status_code == status.HTTP_404_NOT_FOUND
    assert missing.status_code == status.HTTP_404_NOT_FOUND


async def test_patch_route_reports_expired_process_local_payload() -> None:
    clock = [datetime.now(timezone.utc)]
    store = BoundedArtifactPayloadStore(retention=timedelta(minutes=5), now=lambda: clock[0])
    owner_id = uuid4()
    service, artifact = await _run_with_patch(store, str(owner_id))
    clock[0] += timedelta(minutes=6)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=owner_id)
    app.dependency_overrides[adlc_api.get_adlc_run_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/api/v1/adlc/runs/{artifact.workflow_run_id}/artifacts/{artifact.artifact_id}")

    assert response.status_code == status.HTTP_410_GONE
    assert response.json()["detail"]["code"] == "ARTIFACT_PAYLOAD_UNAVAILABLE"

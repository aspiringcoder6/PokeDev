"""H5D owner reconciliation and real SQLite/callback/coordinator restart campaign."""
# ruff: noqa: S101, S106, SLF001, PLR2004

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc import contract_execution, contract_execution_repository
from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.contract_execution_models import RECOVERY_REF
from langflow.adlc.harness_artifacts import HarnessArtifactImporter
from langflow.adlc.harness_attempts import SqliteTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver, HarnessCallbackSettings, sign_harness_delivery
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessResultDelivery,
    HarnessSessionRead,
    HarnessSessionResult,
    HarnessSessionStatus,
)
from langflow.adlc.models import Artifact, TaskRunStatus, WorkflowRunStatus
from langflow.adlc.run_repository import SqliteRunRepository, StoredAdlcRun
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from tests.unit.api.v1 import test_adlc_contract_execution as fixture_module

api_fixture = fixture_module.api_fixture
execution_fixture = fixture_module.execution_fixture


@pytest.fixture
async def recovery_fixture(execution_fixture, monkeypatch):
    f = execution_fixture
    monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "true")
    config = f.request.metadata["resolved_configuration"]
    config["recovery_ref"] = RECOVERY_REF
    config["submission_mode"] = "MANUAL"
    config["plugin_lock"].extend(
        [
            {
                "plugin_id": "vai-adlc-contract-recovery",
                "version": "0.1.0",
                "required": True,
                "content_digest": "sha256:" + "d" * 64,
            },
            {
                "plugin_id": "vai-adlc-artifacts-git",
                "version": "0.2.0",
                "required": True,
                "content_digest": "sha256:" + "e" * 64,
            },
        ]
    )
    task = f.service._runs[f.run.id].run.tasks[0]
    task.plan_traceability.package_version = "0.2.0"
    now = datetime.now(timezone.utc)
    value = HarnessSessionRead(
        session_id=f.session,
        correlation=HarnessCorrelation(
            request_id=f.request.request_id,
            workflow_run_id=f.run.id,
            task_run_id=f.request.task_run_id,
            attempt_id=f.request.attempt_id,
        ),
        idempotency_key=f.request.idempotency_key,
        status="VERIFYING",
        submission_mode="MANUAL",
        created_at=now,
        updated_at=now,
    )
    f.control = SimpleNamespace(
        get_session=AsyncMock(return_value=value),
        reconcile_contract_session=AsyncMock(
            return_value=value.model_copy(update={"status": HarnessSessionStatus.READY_FOR_SUBMISSION})
        ),
    )
    f.app.include_router(adlc_api.router, prefix="/api/v1")
    f.app.dependency_overrides[adlc_api.get_harness_client] = lambda: f.control
    return f


async def test_owner_can_retry_saved_verification_without_submit_or_execution(recovery_fixture):
    f = recovery_fixture
    response = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/harness-sessions/{f.session}/reconcile-verification", json={}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "READY_FOR_SUBMISSION"
    f.control.reconcile_contract_session.assert_awaited_once_with(f.session)
    assert f.service._runs[f.run.id].run.tasks[0].current_attempt_id == f.request.attempt_id


@pytest.mark.parametrize("case", ["owner", "body", "disabled", "version", "state", "attempt", "correlation"])
async def test_recovery_controls_reject_wrong_authority_before_harness_write(recovery_fixture, monkeypatch, case):
    f = recovery_fixture
    payload = {}
    if case == "owner":
        f.app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
    elif case == "body":
        payload = {"proof": {"passed": True}, "owner": str(f.user.id)}
    elif case == "disabled":
        monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "false")
    elif case == "version":
        f.service._runs[f.run.id].run.tasks[0].plan_traceability.package_version = "0.1.0"
    elif case == "state":
        f.control.get_session.return_value.status = "RUNNING"
    elif case == "correlation":
        f.control.get_session.return_value.correlation.attempt_id = uuid4()
    else:
        f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    response = await f.client.post(
        f"/api/v1/adlc/runs/{f.run.id}/harness-sessions/{f.session}/reconcile-verification", json=payload
    )
    assert response.status_code in {403, 404, 409, 422}
    f.control.reconcile_contract_session.assert_not_called()


@pytest.mark.parametrize("missing_proof", [False, True])
async def test_callback_during_adlc_downtime_is_adopted_once_with_exact_contract_gate_and_retained_patch(
    recovery_fixture, monkeypatch, tmp_path, missing_proof
):
    f = recovery_fixture
    assert (await fixture_module.bridge(f)).status_code == 200
    binding = f.executions.get_by_attempt(f.request.attempt_id, owner_id=str(f.user.id))[0]
    proof = fixture_module.proof_for(binding)
    now = datetime.now(timezone.utc)
    payload = json.dumps(
        {
            "format": "harness-git-diff-v1",
            "base_commit": proof.base_commit,
            "reported_files": ["demo.json"],
            "files": [
                {"file": "demo.json", "patch": "fixture patch", "additions": 1, "deletions": 1, "status": "MODIFIED"}
            ],
        }
    ).encode()
    proof.artifact_checksum = "sha256:" + hashlib.sha256(payload).hexdigest()
    artifact = Artifact(
        artifact_id=proof.artifact_id,
        workflow_run_id=f.run.id,
        task_run_id=f.request.task_run_id,
        attempt_id=f.request.attempt_id,
        kind="SOURCE_PATCH",
        name="source-patch.json",
        media_type="application/json",
        uri=f"adlc://runs/{f.run.id}/artifacts/{proof.artifact_id}",
        size_bytes=len(payload),
        checksum={"algorithm": "SHA256", "value": proof.artifact_checksum[7:]},
        producer="plugin:vai-adlc-artifacts-git/0.2.0",
        created_at=now,
        expires_at=now + timedelta(hours=24),
        metadata={
            "capture": "harness-git-diff",
            "format": "harness-git-diff-v1",
            "base_commit": proof.base_commit,
            "file_count": 1,
        },
    )
    if not missing_proof:
        assert (await fixture_module.bridge(f, "report", proof=proof.model_dump(mode="json"))).status_code == 200
    monkeypatch.setattr(contract_execution, "get_contract_repository", lambda: f.repository)
    monkeypatch.setattr(contract_execution_repository, "get_contract_execution_repository", lambda: f.executions)
    result = HarnessSessionResult(
        session_id=f.session,
        correlation=f.control.get_session.return_value.correlation,
        status="SUCCEEDED",
        output={
            "summary": "Contract-bound patch captured; only registered machine predicates were verified.",
            "outputs": {"contract_reference": binding.reference.model_dump(mode="json"), "source_patch": artifact.uri},
            "evidence": proof.model_dump(mode="json"),
        },
        artifacts=[artifact],
        error=None,
        plugin_lock=f.request.metadata["resolved_configuration"]["plugin_lock"],
        verification_reports=[
            {
                "verifier_ref": "plugin:vai-adlc-contract-execution/0.1.0",
                "status": "PASSED",
                "checks": [],
                "started_at": now,
                "completed_at": now,
            }
        ],
        started_at=now,
        completed_at=now,
        trace_ref=f"dsh-session://{f.session}",
        metadata={"driver": {"provider": "my-codex", "model": "cx/gpt-5.6-luna", "recovery_ref": RECOVERY_REF}},
    )
    runs = SqliteRunRepository(tmp_path / "runs.sqlite3")
    record = f.service._runs[f.run.id]
    snapshot = StoredAdlcRun(
        owner_id=record.owner_id,
        run=record.run.model_copy(deep=True),
        definitions={key: definition.model_copy(deep=True) for key, definition in record.definitions.items()},
        delay_ms=record.delay_ms,
    )
    snapshot.run.tasks[0].result = None
    snapshot.run.tasks[0].completed_at = None
    snapshot.run.completed_at = None
    runs.save(snapshot)
    await f.service.shutdown()
    payloads = BoundedArtifactPayloadStore(database_path=tmp_path / "patches.sqlite3")
    payloads.retain(artifact, payload)
    callbacks = HarnessCallbackReceiver(
        HarnessCallbackSettings(secret="isolated-callback-secret"),
        attempts=SqliteTaskAttemptRepository(tmp_path / "attempts.sqlite3"),
        artifact_importer=HarnessArtifactImporter(payloads, None),
    )
    await callbacks.register_attempt(f.request)
    await callbacks.bind_session(f.request.attempt_id, f.session)
    delivery = HarnessResultDelivery(delivery_id=uuid4(), callback_ref="adlc-primary", created_at=now, result=result)
    body = delivery.model_dump_json().encode()
    timestamp = str(int(now.timestamp()))
    arguments = {
        "timestamp": timestamp,
        "signature": sign_harness_delivery("isolated-callback-secret", timestamp, body),
        "delivery_id": str(delivery.delivery_id),
    }
    assert not (await callbacks.receive(body, **arguments)).duplicate
    # New receiver/process objects read the same durable stores. No Harness client.
    callbacks = HarnessCallbackReceiver(
        HarnessCallbackSettings(secret="isolated-callback-secret"),
        attempts=SqliteTaskAttemptRepository(tmp_path / "attempts.sqlite3"),
    )
    assert (await callbacks.receive(body, **arguments)).duplicate
    restored = AdlcRunService(
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        harness_callbacks=callbacks,
        artifact_payloads=BoundedArtifactPayloadStore(database_path=tmp_path / "patches.sqlite3"),
    )
    try:
        await restored.recover()
        await asyncio.gather(*restored._background_runs)
        completed = await restored.get_run(f.run.id, owner_id=str(f.user.id))
        task = completed.tasks[0]
        assert task.current_attempt_id == f.request.attempt_id
        if missing_proof:
            assert completed.status == WorkflowRunStatus.PAUSED
            assert task.status == TaskRunStatus.FAILED
            assert task.result.output is None
            assert task.result.error.code == "CONTRACT_EXECUTION_EVIDENCE_INVALID"
        else:
            assert completed.status == WorkflowRunStatus.SUCCEEDED
            assert task.status == TaskRunStatus.SUCCEEDED
            assert task.result.output["evidence"] == proof.model_dump(mode="json")
            assert (
                len(
                    [
                        e
                        for e in completed.events
                        if e.event_type == "task_run.succeeded" and e.attempt_id == f.request.attempt_id
                    ]
                )
                == 1
            )
            assert (await restored.get_source_patch(f.run.id, artifact.artifact_id, owner_id=str(f.user.id))).files[
                0
            ].file == "demo.json"
        await restored.shutdown()
        reopened = AdlcRunService(
            repository=SqliteRunRepository(tmp_path / "runs.sqlite3"), harness_callbacks=callbacks
        )
        try:
            assert (await reopened.get_run(f.run.id, owner_id=str(f.user.id))).model_dump(
                mode="json"
            ) == completed.model_dump(mode="json")
        finally:
            await reopened.shutdown()
    finally:
        await restored.shutdown()

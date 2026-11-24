"""H6A owner API, approval, capture binding, observation and publication."""

# ruff: noqa: S101, SLF001, PLR2004
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.contract_models import ContractApprovalCommand, ContractReference
from langflow.adlc.models import Artifact
from langflow.adlc.verification_repository import VerificationRepository
from langflow.api.v1 import adlc_verification as verification_api
from tests.unit.adlc import test_verification as reproduction_fixtures
from tests.unit.api.v1 import test_adlc_contracts as contract_fixtures
from tests.unit.api.v1.test_adlc_contracts import make_checked

api_fixture = contract_fixtures.api_fixture
real_worker = reproduction_fixtures.real_worker
example_plan = reproduction_fixtures.example_plan
receipt_for = reproduction_fixtures.receipt_for


@pytest.fixture
async def verification_fixture(api_fixture, monkeypatch, tmp_path):
    f = api_fixture
    monkeypatch.setenv("ADLC_VERIFICATION_ENABLED", "true")
    contract = await make_checked(f)
    approved = f.repository.approve(
        ContractApprovalCommand(
            reference=ContractReference.model_validate(contract["reference"]), idempotency_key="approve-verification"
        ),
        owner_id=str(f.user.id),
        run_id=f.run.id,
    ).contract
    f.app.include_router(verification_api.router, prefix="/api/v1")
    f.store = VerificationRepository(tmp_path / "verification.sqlite3")
    f.worker = SimpleNamespace(
        health=AsyncMock(return_value={"ready": True, "provider": "local-fixture"}),
        create=AsyncMock(),
        read=AsyncMock(),
    )
    f.app.dependency_overrides[verification_api.explicit_owner] = lambda: f.user
    f.app.dependency_overrides[verification_api.get_verification_repository] = lambda: f.store
    f.app.dependency_overrides[verification_api.get_verification_worker] = lambda: f.worker
    f.seed = example_plan()
    source = f.service._runs[f.run.id].run.tasks[0]
    source.current_attempt_id = f.seed.candidate.source_attempt_id
    source.result.metadata["harness_session_id"] = "source-session"
    source.result.artifacts.append(
        Artifact(
            artifact_id=f.seed.candidate.artifact_id,
            workflow_run_id=f.run.id,
            task_run_id=source.id,
            attempt_id=source.current_attempt_id,
            producer="plugin:vai-adlc-artifacts-git/0.2.0",
            metadata={"capture": "harness-git-diff"},
            kind="SOURCE_PATCH",
            name="fixture patch",
            media_type="application/json",
            uri=f"adlc://runs/{f.run.id}/artifacts/{f.seed.candidate.artifact_id}",
            size_bytes=100,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            checksum={"algorithm": "SHA256", "value": f.seed.candidate.artifact_digest[7:]},
        )
    )
    f.seed.candidate.source_task_id = source.id
    f.seed.candidate.source_session_id = "source-session"
    f.service.get_source_patch = AsyncMock(
        return_value=SimpleNamespace(
            format="harness-git-diff-v1",
            artifact=source.result.artifacts[-1],
            files=[SimpleNamespace(file="fixture.json")],
        )
    )
    monkeypatch.setattr(verification_api, "freeze_candidate", lambda *_: (f.seed.candidate, '{"answer":42}'))
    node = approved.document.nodes[0]
    f.command = {
        "source_task_id": str(source.id),
        "artifact_id": str(f.seed.candidate.artifact_id),
        "file": "fixture.json",
        "contract_reference": approved.reference.model_dump(mode="json"),
        "idempotency_key": "create-once",
        "cases": [
            {
                "case_id": "answer",
                "pointer": "/answer",
                "expected": 42,
                "criterion_node_id": str(node.node_id),
                "criterion_index": 0,
            }
        ],
    }
    f.root = f"/api/v1/adlc/runs/{f.run.id}/verifications"
    yield f
    f.store.close()


async def create(f):
    response = await f.client.post(f.root, json=f.command)
    assert response.status_code == 201, response.text
    f.row = response.json()
    f.item = f.root + "/" + f.row["plan"]["plan_id"]
    return response


async def action(f, op, plan_digest=None):
    return await f.client.post(f.item + "/" + op, json={"plan_digest": plan_digest or f.row["plan_digest"]})


async def test_exact_approval_precedes_execution_and_submit_is_separate(verification_fixture):
    f = verification_fixture
    await create(f)
    assert (await action(f, "execute")).status_code == 409
    assert (await action(f, "approve", "sha256:" + "f" * 64)).status_code == 409
    approved = await action(f, "approve")
    assert approved.json()["state"] == "APPROVED"
    started = await action(f, "execute")
    assert started.status_code == 200
    row = f.store.get(f.row["plan"]["plan_id"], owner=str(f.user.id), run_id=f.run.id)
    receipt = receipt_for(row.plan, execution_id=row.execution_id)
    f.worker.read.return_value = {"execution_id": str(row.execution_id), "state": "READY"}
    f.worker.receipt = lambda _: receipt
    prepared = await action(f, "reconcile")
    assert prepared.json()["state"] == "READY_FOR_SUBMISSION"
    assert prepared.json()["report"]["verdict"] == "PASS"
    assert prepared.json()["submitted_at"] is None
    published = await action(f, "submit")
    assert published.json()["state"] == "SUBMITTED"
    evidence = await f.client.get(f.item + "/evidence")
    assert evidence.status_code == 200
    assert evidence.headers["x-adlc-content-digest"] == published.json()["evidence_digest"]
    assert "no-store" in evidence.headers["cache-control"]


async def test_idempotency_unknown_authority_and_unmapped_criteria(verification_fixture):
    f = verification_fixture
    response = await create(f)
    duplicate = await f.client.post(f.root, json=f.command)
    assert duplicate.json()["plan"]["plan_id"] == response.json()["plan"]["plan_id"]
    changed = {**f.command, "file": "different.json"}
    assert (await f.client.post(f.root, json=changed)).status_code == 409
    assert (await f.client.post(f.root, json={**f.command, "approved_by": "owner"})).status_code == 422
    f.command["cases"][0]["criterion_node_id"] = str(uuid4())
    assert (await f.client.post(f.root, json=f.command)).status_code == 422


async def test_another_owner_and_session_cannot_read_or_approve(verification_fixture):
    f = verification_fixture
    await create(f)
    f.app.dependency_overrides[verification_api.explicit_owner] = lambda: SimpleNamespace(id=uuid4())
    assert (await action(f, "approve")).status_code == 404
    assert (await f.client.get("/api/v1/adlc/harness-sessions/unknown/verifications")).status_code == 404
    assert f.worker.create.await_count == 0


async def test_stale_attempt_never_dispatches(verification_fixture):
    f = verification_fixture
    await create(f)
    await action(f, "approve")
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    response = await action(f, "execute")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VERIFICATION_CANDIDATE_STALE"
    assert f.worker.create.await_count == 0


async def test_recorded_intent_cannot_be_dispatched_twice(verification_fixture):
    f = verification_fixture
    await create(f)
    await action(f, "approve")
    assert (await action(f, "execute")).status_code == 200
    assert (await action(f, "execute")).status_code == 409
    assert f.worker.create.await_count == 1


async def test_candidates_show_owned_approved_references_and_current_json_patch(verification_fixture):
    f = verification_fixture
    response = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/verification-candidates")
    assert response.status_code == 200
    assert response.json()["contracts"][0]["status"] == "APPROVED"
    assert response.json()["patches"][0]["files"] == ["fixture.json"]
    assert response.headers["cache-control"] == "no-store"
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    assert (await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/verification-candidates")).json()["patches"] == []


async def test_new_drafts_do_not_starve_an_older_dispatched_execution(verification_fixture):
    f = verification_fixture
    await create(f)
    await action(f, "approve")
    await action(f, "execute")
    row = f.store.get(f.row["plan"]["plan_id"], owner=str(f.user.id), run_id=f.run.id)
    for i in range(3):
        assert (await f.client.post(f.root, json={**f.command, "idempotency_key": f"draft-{i}"})).status_code == 201
    f.worker.read.return_value = {"state": "READY", "execution_id": str(row.execution_id)}
    f.worker.receipt = lambda _: receipt_for(row.plan, execution_id=row.execution_id)
    result = (await f.client.get(f.root)).json()
    assert result[-1]["state"] == "READY_FOR_SUBMISSION"
    assert f.worker.read.await_count == 1


async def test_captured_producer_and_source_session_cannot_be_substituted(verification_fixture):
    f = verification_fixture
    source = f.service._runs[f.run.id].run.tasks[0]
    source.result.artifacts[-1].producer = "candidate-self-report"
    assert (await f.client.post(f.root, json=f.command)).status_code == 409
    source.result.artifacts[-1].producer = "plugin:vai-adlc-artifacts-git/0.2.0"
    await create(f)
    await action(f, "approve")
    source.result.metadata["harness_session_id"] = "a-different-session"
    assert (await action(f, "execute")).status_code == 409
    assert f.worker.create.await_count == 0


async def test_session_view_is_exact_owner_scoped_and_survives_current_attempt_change(verification_fixture):
    from tests.unit.api.v1.test_adlc_contracts import authoring_session

    f = verification_fixture
    await create(f)
    # Register a real owned attempt ledger entry, then make it the archived source.
    await authoring_session(f, session="source-session")
    bound = await f.callbacks.attempts.find_by_session("source-session")
    # Draft is replaced by a new immutable reference to the registered source.
    f.seed.candidate.source_attempt_id = bound.attempt_id
    f.service._runs[f.run.id].run.tasks[0].result.artifacts[-1].attempt_id = bound.attempt_id
    f.command["idempotency_key"] = "source-ledger-plan"
    await create(f)
    response = await f.client.get("/api/v1/adlc/harness-sessions/source-session/verifications")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["plan"]["candidate"]["source_attempt_id"] == str(bound.attempt_id)
    assert response.headers["cache-control"] == "no-store"
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    assert len((await f.client.get("/api/v1/adlc/harness-sessions/source-session/verifications")).json()) == 1
    f.app.dependency_overrides[contract_fixtures.get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
    assert (await f.client.get("/api/v1/adlc/harness-sessions/source-session/verifications")).status_code == 404
    assert (await f.client.get(f.root)).status_code == 404
    assert (await f.client.get(f.item + "/evidence")).status_code == 404


async def test_worker_outage_is_uncertain_and_observation_does_not_resubmit(verification_fixture):
    from langflow.adlc.verification_models import VerificationError

    f = verification_fixture
    await create(f)
    await action(f, "approve")
    f.worker.create.side_effect = VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED")
    assert (await action(f, "execute")).json()["state"] == "DISPATCH_UNCERTAIN"
    f.worker.read.side_effect = VerificationError("VERIFICATION_WORKER_UNAVAILABLE")
    assert (await action(f, "reconcile")).json()["state"] == "DISPATCH_UNCERTAIN"
    assert f.worker.create.await_count == 1
    assert (await action(f, "submit")).status_code == 409


async def test_disabled_feature_does_not_run_but_archives_remain_readable(verification_fixture, monkeypatch):
    f = verification_fixture
    await create(f)
    monkeypatch.setenv("ADLC_VERIFICATION_ENABLED", "false")
    assert (await action(f, "approve")).status_code == 409
    assert (await f.client.get(f.root)).status_code == 200
    assert f.worker.create.await_count == 0


async def test_invalid_execution_evidence_is_not_a_fail_or_pass_verdict(verification_fixture):
    f = verification_fixture
    await create(f)
    await action(f, "approve")
    await action(f, "execute")
    row = f.store.get(f.row["plan"]["plan_id"], owner=str(f.user.id), run_id=f.run.id)
    f.worker.read.return_value = {"state": "READY", "execution_id": str(row.execution_id)}
    f.worker.receipt = lambda _: receipt_for(row.plan, execution_id=row.execution_id).model_copy(
        update={"tests_run": 0}
    )
    response = await action(f, "reconcile")
    assert response.json()["state"] == "NOT_VERIFIED"
    assert response.json()["report"] is None
    assert (await action(f, "submit")).status_code == 409


async def test_api_to_real_worker_retains_genuine_failure_and_manual_publication(verification_fixture, real_worker):
    f = verification_fixture
    f.command["cases"][0]["expected"] = 43
    f.app.dependency_overrides[verification_api.get_verification_worker] = lambda: real_worker
    await create(f)
    await action(f, "approve")
    assert (await action(f, "execute")).status_code == 200
    response = None
    for _ in range(100):
        response = await f.client.get(f.root)
        if response.json()[0]["state"] == "READY_FOR_SUBMISSION":
            break
        await asyncio.sleep(0.03)
    row = response.json()[0]
    assert row["report"]["verdict"] == "FAIL"
    assert row["report"]["checks"][0]["observed"] == 42
    assert row["submitted_at"] is None
    assert (await action(f, "submit")).json()["report"]["verdict"] == "FAIL"
    assert (await f.client.get(f.item + "/evidence")).status_code == 200

"""H6B owner/run/attempt boundaries and actual local evidence in both projections."""

# ruff: noqa: S101, SLF001, PLR2004
import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.replay_repository import ReplayRepository
from langflow.adlc.verification_models import VerificationError
from langflow.api.v1 import adlc_replay as api
from langflow.api.v1 import adlc_verification as previous_api
from tests.unit.adlc import test_replay as reproduction_fixtures
from tests.unit.api.v1 import test_adlc_contracts as contracts
from tests.unit.api.v1 import test_adlc_verification as verification_fixtures

api_fixture = verification_fixtures.api_fixture
verification_fixture = verification_fixtures.verification_fixture
real_replay_worker = reproduction_fixtures.real_replay_worker
replay_receipt = reproduction_fixtures.replay_receipt


@pytest.fixture
async def replay_fixture(verification_fixture, tmp_path, monkeypatch):
    f = verification_fixture
    monkeypatch.setenv("ADLC_REPLAY_ENABLED", "true")
    monkeypatch.setattr(
        api, "get_settings_service", lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=False))
    )
    f.app.include_router(api.router, prefix="/api/v1")
    f.replay_store = ReplayRepository(tmp_path / "replays.sqlite3")
    f.replay_worker = SimpleNamespace(
        health=AsyncMock(return_value={"ready": True, "provider": "local-http-fixture"}),
        create=AsyncMock(),
        read=AsyncMock(),
        cancel=AsyncMock(),
    )
    f.app.dependency_overrides[api.get_replay_repository] = lambda: f.replay_store
    f.app.dependency_overrides[api.get_replay_worker] = lambda: f.replay_worker
    f.root = f"/api/v1/adlc/runs/{f.run.id}/replays"
    yield f
    f.replay_store.close()


async def create(f):
    response = await f.client.post(f.root, json=f.command)
    assert response.status_code == 201, response.text
    f.row = response.json()
    f.item = f.root + "/" + f.row["plan"]["plan_id"]
    return response


async def action(f, operation, digest=None):
    return await f.client.post(f.item + "/" + operation, json={"plan_digest": digest or f.row["plan_digest"]})


async def test_frozen_approval_dispatch_intent_and_unsafe_oracle_options(replay_fixture):
    f = replay_fixture
    await create(f)
    assert f.row["plan"]["heal"] is False
    assert f.row["plan"]["models"] is False
    assert (await action(f, "execute")).status_code == 409
    assert (await action(f, "approve", "sha256:" + "f" * 64)).status_code == 409
    assert (await action(f, "approve")).json()["state"] == "APPROVED"
    f.replay_worker.create.side_effect = VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED")
    assert (await action(f, "execute")).json()["state"] == "DISPATCH_UNCERTAIN"
    assert (await action(f, "execute")).status_code == 409
    assert f.replay_worker.create.await_count == 1
    assert (await f.client.post(f.root, json={**f.command, "heal": True})).status_code == 422
    assert (await f.client.post(f.root, json={**f.command, "target_url": "http://prod"})).status_code == 422


async def test_cross_owner_stale_source_and_candidate_relabel_are_blocked(replay_fixture):
    f = replay_fixture
    await create(f)
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: SimpleNamespace(id=uuid4())
    assert (await action(f, "approve")).status_code == 404
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: f.user
    await action(f, "approve")
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    assert (await action(f, "execute")).status_code == 409
    assert f.replay_worker.create.await_count == 0
    # Cancel remains safe for an obsolete approved suite; no job was dispatched.
    assert (await action(f, "cancel")).json()["state"] == "CANCELLED"


async def test_cancel_intent_is_not_confirmation_and_cannot_be_published(replay_fixture):
    f = replay_fixture
    await create(f)
    await action(f, "approve")
    await action(f, "execute")
    f.replay_worker.cancel.side_effect = VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED")
    response = await action(f, "cancel")
    assert response.json()["state"] == "CANCEL_REQUESTED"
    assert response.json()["cancelled_at"] is None
    assert (await action(f, "submit")).status_code == 409
    f.replay_worker.read.return_value = {"state": "CANCELLED"}
    f.replay_worker.confirm_state = lambda *_: None
    response = await action(f, "reconcile")
    assert response.json()["state"] == "CANCELLED"
    assert response.json()["report"] is None


async def test_invalid_junit_blocks_verdict_but_history_survives(replay_fixture):
    f = replay_fixture
    await create(f)
    await action(f, "approve")
    await action(f, "execute")
    row = f.replay_store.get(f.row["plan"]["plan_id"], owner=str(f.user.id), run_id=f.run.id)
    f.replay_worker.read.return_value = {"state": "READY"}
    f.replay_worker.receipt = lambda _: replay_receipt(row.plan, execution_id=row.execution_id).model_copy(
        update={"tests_run": 0}
    )
    response = await action(f, "reconcile")
    assert response.json()["state"] == "NOT_VERIFIED"
    assert response.json()["report"] is None
    assert (await action(f, "submit")).status_code == 409


async def test_owner_api_to_real_http_runner_retains_fail_json_and_junit(replay_fixture, real_replay_worker):
    f = replay_fixture
    f.command["cases"][0]["expected"] = 43
    f.app.dependency_overrides[api.get_replay_worker] = lambda: real_replay_worker
    await create(f)
    await action(f, "approve")
    await action(f, "execute")
    for _ in range(100):
        response = await f.client.get(f.root)
        if response.json()[0]["state"] == "READY_FOR_SUBMISSION":
            break
        await asyncio.sleep(0.03)
    row = response.json()[0]
    assert row["report"]["verdict"] == "FAIL"
    assert row["submitted_at"] is None
    assert (await action(f, "submit")).json()["state"] == "SUBMITTED"
    for kind in ["json", "junit"]:
        evidence = await f.client.get(f.item + "/evidence/" + kind)
        assert evidence.status_code == 200
        actual = "sha256:" + hashlib.sha256(evidence.content).hexdigest()
        assert actual == evidence.headers["x-adlc-content-digest"]
        assert actual == (row["evidence_digest"] if kind == "json" else row["receipt"]["junit_digest"])
        assert "attachment" in evidence.headers["content-disposition"]
    f.app.dependency_overrides[contracts.get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
    assert (await f.client.get(f.item + "/evidence/junit")).status_code == 404


async def test_projection_is_exact_source_session_and_disabled_mode_does_not_run(replay_fixture, monkeypatch):
    f = replay_fixture
    await contracts.authoring_session(f, session="source-session")
    bound = await f.callbacks.attempts.find_by_session("source-session")
    f.seed.candidate.source_attempt_id = bound.attempt_id
    f.service._runs[f.run.id].run.tasks[0].result.artifacts[-1].attempt_id = bound.attempt_id
    await create(f)
    response = await f.client.get("/api/v1/adlc/harness-sessions/source-session/replays")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert (await f.client.get("/api/v1/adlc/harness-sessions/unknown/replays")).status_code == 404
    monkeypatch.setenv("ADLC_REPLAY_ENABLED", "false")
    assert (await action(f, "approve")).status_code == 409
    assert len((await f.client.get(f.root)).json()) == 1
    assert f.replay_worker.create.await_count == 0
    caps = (await f.client.get("/api/v1/adlc/replay-capabilities")).json()
    assert caps["enabled"] is False
    assert caps["testforge_ready"] is False
    assert caps["testforge_blockers"]

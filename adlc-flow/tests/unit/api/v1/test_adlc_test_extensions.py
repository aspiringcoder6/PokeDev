"""H6D owner approval, safe proposal materialization, protected projection and bridge."""

# ruff: noqa: S101, SLF001, PLR2004, S105, PT018 - bounded test fixture assertions.
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from langflow.adlc.contract_bridge import sign_contract_command
from langflow.adlc.models import PlanTaskTraceability, WorkflowExecutionMode
from langflow.adlc.test_extension_models import DOMAIN
from langflow.adlc.test_extension_repository import TestExtensionRepository, bytes_digest
from langflow.api.utils.core import injectable_session_scope
from langflow.api.v1 import adlc_test_extensions as api
from langflow.api.v1 import adlc_verification as previous_api
from tests.unit.adlc.test_test_extensions import BUDGET, PERMISSIONS, completed, upload
from tests.unit.api.v1 import test_adlc_contracts as contracts
from tests.unit.api.v1 import test_adlc_replay as replay

api_fixture = replay.api_fixture
verification_fixture = replay.verification_fixture
replay_fixture = replay.replay_fixture
SECRET = "proposal-only-purpose-separated-test-key-32-bytes"


@pytest.fixture
async def extension_fixture(replay_fixture, tmp_path, monkeypatch):
    f = replay_fixture
    monkeypatch.setenv("ADLC_TEST_EXTENSIONS_ENABLED", "true")
    monkeypatch.setenv("ADLC_TEST_PROPOSAL_TOOL_SECRET", SECRET)
    monkeypatch.setattr(
        api, "get_settings_service", lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=False))
    )
    f.app.include_router(api.router, prefix="/api/v1")
    f.extensions = TestExtensionRepository(tmp_path / "extensions.sqlite3")
    f.app.dependency_overrides[api.get_test_extension_repository] = lambda: f.extensions
    await replay.create(f)
    f.source = f.replay_store.get(f.row["plan"]["plan_id"], owner=str(f.user.id), run_id=f.run.id)
    f.proposals = f"/api/v1/adlc/runs/{f.run.id}/test-proposals"
    f.init = {
        "operation": "init",
        "source_plan_id": str(f.source.plan.plan_id),
        "kind": "suite-revision",
        "title": "Successor proposal",
        "rationale": "Never silently heal the approved suite.",
        "idempotency_key": "init",
    }
    yield f
    f.extensions.close()


async def tool(f, command):
    return await f.client.post(f.proposals + "/tools", json=command)


async def reviewed(f, *, kind="suite-revision"):
    response = await tool(f, {**f.init, "kind": kind})
    assert response.status_code == 200, response.text
    row = response.json()
    response = await tool(
        f,
        {
            "operation": "set_permissions",
            "reference": row["reference"],
            "permissions": PERMISSIONS,
            "performance": BUDGET if kind == "performance" else None,
            "idempotency_key": "permissions",
        },
    )
    assert response.status_code == 200, response.text
    response = await tool(
        f, {"operation": "validate", "reference": response.json()["reference"], "idempotency_key": "freeze"}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def action(f, row, operation, **extra):
    return await f.client.post(
        f.proposals + "/" + row["reference"]["proposal_id"] + "/" + operation,
        json={"reference": row["reference"], **extra},
    )


async def test_owner_approval_materializes_exact_new_draft_never_a_job_or_submit(extension_fixture):
    f = extension_fixture
    before = (await f.service.get_run(f.run.id, owner_id=str(f.user.id))).model_dump(mode="json")
    row = await reviewed(f)
    assert (await action(f, row, "materialize")).status_code == 409
    approved = (await action(f, row, "approve")).json()
    assert approved["approved_by"] == str(f.user.id)
    response = await action(f, row, "materialize")
    assert response.status_code == 200, response.text
    materialized = response.json()
    draft = f.replay_store.get(materialized["materialized_plan_id"], owner=str(f.user.id), run_id=f.run.id)
    assert draft.state == "DRAFT" and draft.approved_by is None and draft.execution_id is None
    assert draft.plan.plan_id != f.source.plan.plan_id
    assert draft.plan.cases == f.source.plan.cases
    assert (await action(f, row, "materialize")).json() == materialized
    assert len(f.replay_store.list(owner=str(f.user.id), run_id=f.run.id)) == 2
    assert f.replay_worker.create.await_count == 0
    assert f.replay_store.get(f.source.plan.plan_id, owner=str(f.user.id), run_id=f.run.id) == f.source
    assert (await f.service.get_run(f.run.id, owner_id=str(f.user.id))).model_dump(mode="json") == before


async def test_cross_store_interruption_recovers_same_draft_without_duplicate_dispatch(extension_fixture, monkeypatch):
    f = extension_fixture
    row = await reviewed(f)
    await action(f, row, "approve")
    mark = f.extensions.materialized
    monkeypatch.setattr(
        f.extensions,
        "materialized",
        lambda *_args, **_kwargs: api.fail(api.VerificationError("TEST_ARCHIVE_UNAVAILABLE", 503)),
    )
    assert (await action(f, row, "materialize")).status_code == 503
    monkeypatch.setattr(f.extensions, "materialized", mark)
    assert (await action(f, row, "materialize")).status_code == 200
    assert len(f.replay_store.list(owner=str(f.user.id), run_id=f.run.id)) == 2
    assert f.replay_worker.create.await_count == 0


@pytest.mark.parametrize("kind", ["exploration", "performance"])
async def test_risky_proposals_remain_non_executable_even_after_real_approval(extension_fixture, kind):
    f = extension_fixture
    row = await reviewed(f, kind=kind)
    assert (await action(f, row, "approve")).status_code == 200
    assert (await action(f, row, "execute")).json()["detail"]["code"] == "TEST_EXTENSION_EXECUTION_NOT_AVAILABLE"
    assert (await action(f, row, "materialize")).status_code == 409
    assert (await action(f, row, "execute", approved_by="human", role="human")).status_code == 422
    assert f.replay_worker.create.await_count == 0


async def test_forged_owner_cross_owner_stale_candidate_and_unknown_criterion_are_blocked(extension_fixture):
    f = extension_fixture
    assert (await tool(f, {**f.init, "approved_by": "human"})).status_code == 422
    row = await reviewed(f)
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: SimpleNamespace(id=uuid4())
    assert (await action(f, row, "approve")).status_code == 404
    f.app.dependency_overrides[previous_api.explicit_owner] = lambda: f.user
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = uuid4()
    assert (await action(f, row, "approve")).status_code == 409
    f.service._runs[f.run.id].run.tasks[0].current_attempt_id = f.source.plan.candidate.source_attempt_id
    # A bad agent-authored mapping can be a draft, never a frozen reviewed standard.
    second = (await tool(f, {**f.init, "idempotency_key": "second"})).json()
    case = second["document"]["cases"][0]
    change = await tool(
        f,
        {
            "operation": "upsert_case",
            "reference": second["reference"],
            "case": {**case, "criterion_node_id": str(uuid4())},
            "idempotency_key": "bad-case",
        },
    )
    assert change.status_code == 200
    ref = change.json()["reference"]
    assert (
        await tool(f, {"operation": "validate", "reference": ref, "idempotency_key": "bad-freeze"})
    ).status_code == 422


async def test_session_projection_matches_owner_archive_and_off_mode_is_passive(extension_fixture, monkeypatch):
    f = extension_fixture
    row = await reviewed(f)
    await contracts.authoring_session(f, session="source-session")
    response = await f.client.get("/api/v1/adlc/harness-sessions/source-session/test-proposals")
    assert response.json() == [row]
    assert response.headers["cache-control"] == "no-store"
    assert (await f.client.get("/api/v1/adlc/harness-sessions/unknown/test-proposals")).status_code == 404
    monkeypatch.setenv("ADLC_TEST_EXTENSIONS_ENABLED", "false")
    assert (await f.client.get(f.proposals)).json() == [row]
    assert (await action(f, row, "approve")).status_code == 409
    caps = (await f.client.get("/api/v1/adlc/test-extension-capabilities")).json()
    assert caps["performance_ready"] is False and caps["screenshot_capture_ready"] is False


async def test_owner_screenshot_retains_failed_report_checksums_and_escaped_labels(extension_fixture):
    f = extension_fixture
    source = completed(f.replay_store, f.source, {"owner": str(f.user.id), "run_id": f.run.id})
    route = f"/api/v1/adlc/runs/{f.run.id}/replay-screenshots/{f.source.plan.plan_id}"
    command = upload(source).model_dump(mode="json")
    response = await f.client.post(route, json=command)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["affects_verdict"] is False
    assert (await f.client.get(route)).json() == [row]
    image = await f.client.get(route + "/" + row["attachment_id"])
    assert image.headers["x-adlc-content-digest"] == bytes_digest(image.content)
    assert image.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in image.headers["content-security-policy"]
    assert f.replay_store.get(f.source.plan.plan_id, owner=str(f.user.id), run_id=f.run.id) == source
    assert (await f.client.post(route, json={**command, "capture_provenance_verified": True})).status_code == 422
    f.app.dependency_overrides[contracts.get_current_active_user] = lambda: SimpleNamespace(id=uuid4())
    assert (await f.client.get(route + "/" + row["attachment_id"])).status_code == 404


async def test_bounded_duplicate_json_and_bridge_purpose_checks(extension_fixture):
    f = extension_fixture
    assert (await f.client.post(f.proposals + "/tools", content=b"x" * (api.MAX_COMMAND_BYTES + 1))).status_code == 413
    assert (
        await f.client.post(f.proposals + "/tools", content=b'{"operation":"init","operation":"approve"}')
    ).status_code == 422
    body = json.dumps({"session_id": "source-session", "command": f.init}).encode()
    timestamp = str(int(time.time()))
    headers = {
        "X-ADLC-Test-Proposal-Timestamp": timestamp,
        "X-ADLC-Test-Proposal-Signature": sign_contract_command(SECRET, timestamp, body),
    }
    assert (await f.client.post("/api/v1/adlc/test-proposal-tools", content=body, headers=headers)).status_code == 401
    headers["X-ADLC-Test-Proposal-Signature"] = sign_contract_command(SECRET, timestamp, body, domain=DOMAIN)
    assert (await f.client.post("/api/v1/adlc/test-proposal-tools", content=body, headers=headers)).status_code == 403


async def agent_scope(f):
    run = f.service._runs[f.run.id].run
    # A separate active authoring task observes the completed source task. Do not
    # turn the old source attempt into the authoring attempt or relabel its patch.
    authoring = run.tasks[0].model_copy(deep=True)
    authoring.id = uuid4()
    run.tasks.insert(0, authoring)
    await contracts.authoring_session(f, session="proposal-author")
    run.execution_mode = WorkflowExecutionMode.EXECUTION_PLAN
    run.execution_plan_id = uuid4()
    authoring.request.context = {
        "adlc_local_project": {
            "project_id": str(f.source.plan.candidate.project_id),
            "base_commit": f.source.plan.candidate.base_commit,
            "source_ref": str(f.source.plan.candidate.project_id) + "/" + f.source.plan.candidate.base_commit,
        }
    }
    authoring.plan_traceability = PlanTaskTraceability(
        execution_plan_id=run.execution_plan_id,
        plan_task_id=uuid4(),
        source_workflow_stage_id=uuid4(),
        resolved_node_spec_id=uuid4(),
        package_id="fixture",
        package_version="0.1.0",
        package_content_digest="sha256:" + "b" * 64,
        resolved_node_digest="sha256:" + "c" * 64,
    )
    return authoring


async def agent_command(f, command, *, session="proposal-author"):
    raw = json.dumps({"session_id": session, "command": command}, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    return await f.client.post(
        "/api/v1/adlc/test-proposal-tools",
        content=raw,
        headers={
            "X-ADLC-Test-Proposal-Timestamp": timestamp,
            "X-ADLC-Test-Proposal-Signature": sign_contract_command(SECRET, timestamp, raw, domain=DOMAIN),
        },
    )


async def test_agent_six_tool_loop_freezes_but_cannot_approve_or_edit_human_draft(extension_fixture):
    f = extension_fixture
    human = (await tool(f, {**f.init, "idempotency_key": "human"})).json()
    await agent_scope(f)
    response = await agent_command(f, f.init)
    assert response.status_code == 200, response.text
    row = response.json()["result"]
    assert row["document"]["authoring_session_id"] == "proposal-author"
    assert row["state"] == "DRAFT" and row["approved_by"] is None
    # The signed tool caller cannot edit an independently human-authored draft.
    denied = await agent_command(
        f,
        {
            "operation": "remove_case",
            "reference": human["reference"],
            "case_id": "answer",
            "idempotency_key": "cross-draft",
        },
    )
    assert denied.status_code == 404
    response = await agent_command(
        f,
        {
            "operation": "set_permissions",
            "reference": row["reference"],
            "permissions": PERMISSIONS,
            "idempotency_key": "agent-permissions",
        },
    )
    row = response.json()["result"]
    response = await agent_command(
        f, {"operation": "validate", "reference": row["reference"], "idempotency_key": "agent-freeze"}
    )
    row = response.json()["result"]
    assert row["state"] == "READY_FOR_REVIEW" and row["approved_by"] is None
    forged = await agent_command(f, {"operation": "approve", "reference": row["reference"], "approved_by": "human"})
    assert forged.status_code == 422
    scoped = await f.client.get("/api/v1/adlc/harness-sessions/proposal-author/test-proposals")
    assert scoped.json() == [row]
    assert f.replay_worker.create.await_count == 0


async def test_agent_stale_attempt_and_cross_project_source_are_rejected(extension_fixture):
    f = extension_fixture
    authoring = await agent_scope(f)
    authoring.request.context["adlc_local_project"]["project_id"] = str(uuid4())
    authoring.request.context["adlc_local_project"]["source_ref"] = (
        authoring.request.context["adlc_local_project"]["project_id"] + "/" + f.source.plan.candidate.base_commit
    )
    assert (await agent_command(f, f.init)).status_code == 404
    authoring.current_attempt_id = uuid4()
    assert (await agent_command(f, f.init)).status_code in {403, 422}
    assert f.extensions.list(owner=str(f.user.id), run_id=f.run.id) == []


async def test_real_owner_dependency_rejects_auto_login_and_missing_user_token(extension_fixture, monkeypatch):
    f = extension_fixture
    row = await reviewed(f)
    f.app.dependency_overrides.pop(previous_api.explicit_owner)
    f.app.dependency_overrides[injectable_session_scope] = lambda: None
    monkeypatch.setattr(
        contracts.contract_api,
        "get_settings_service",
        lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=True)),
    )
    assert (await action(f, row, "approve")).status_code == 403
    monkeypatch.setattr(
        contracts.contract_api,
        "get_settings_service",
        lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=False)),
    )
    assert (await action(f, row, "approve")).status_code == 401

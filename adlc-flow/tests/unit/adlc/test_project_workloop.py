import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest

from langflow.adlc import project_workloop as mod
from langflow.adlc.project_workloop import ProjectWorkloop, job_summary, project_snapshot, text
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_project_workloop as api


class Client:
    def __init__(self):
        self.raw = {"job": {"job_id": "job-test", "wf_name": "build", "wf_version": 2, "status": "in_progress", "meta": json.dumps({"sha": "a" * 40, "nodes": ["build", "test"]})}, "events": []}
        self.pending = []
        self.calls = []
        self.offline = False
        self.post_error = None

    async def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.offline:
            raise ServiceCheckError("WORKLOOP_UNAVAILABLE", 503)
        if method == "POST":
            if self.post_error:
                raise self.post_error
            return {"ok": True, "signal_id": 9}
        if path.endswith("/approvals"):
            return {"pending": copy.deepcopy(self.pending)}
        return copy.deepcopy(self.raw)

    async def snapshot(self, job):
        return {"state": "pinned", "commit": "a" * 40, "tasks": [{"id": "build", "title": "Build"}, {"id": "test", "title": "Test"}], "edges": [{"source": "build", "target": "test"}]}


@pytest.fixture
async def bound(tmp_path):
    client = Client()
    service = ProjectWorkloop(tmp_path / "jobs.db", client)
    project = {"project_id": "project-a", "repository": "admin/app"}
    await service.bind("owner", project, "job-test", "Add search")
    client.calls.clear()
    return service, client, project


def test_job_and_node_vocabularies_are_not_confused():
    assert job_summary({"job_id": "job-1", "status": "completed"})["state"] == "COMPLETED"
    assert job_summary({"job_id": "job-1", "status": "in_progress"})["state"] == "RUNNING"
    assert job_summary({"job_id": "job-1", "status": "DONE"})["state"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_bind_is_owner_project_scoped_and_global_job_is_not_rebound(bound):
    service, client, project = bound
    assert not service.links("another-owner", "project-a")
    assert not service.links("owner", "another-project")
    for owner, project_id in [("another-owner", "project-a"), ("owner", "another-project")]:
        with pytest.raises(ServiceCheckError) as exc:
            await service.read(owner, project_id, "job-test")
        assert exc.value.status == 404
    assert not client.calls
    with pytest.raises(ServiceCheckError, match="ALREADY_LINKED"):
        await service.bind("owner", {**project, "project_id": "another-project"}, "job-test", "Wrong")


@pytest.mark.asyncio
async def test_read_has_actual_events_and_never_claims_verification(bound):
    service, client, _ = bound
    client.raw["events"] = [
        {"event_type": "node_started", "created_at": "2026-10-28T01:00:00Z", "payload": json.dumps({"node": "build"})},
        {"event_type": "node_terminal", "created_at": "2026-10-28T01:01:00Z", "payload": {"node": "build", "status": "DONE_WITH_CONCERNS", "session_ref": "session-a", "secret": "hidden"}},
    ]
    client.raw["job"]["status"] = "completed"
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    assert view["state"] == "COMPLETED" and view["verification"] == "unverified"
    assert view["tasks"][0]["state"] == "DONE_WITH_CONCERNS"
    assert view["tasks"][0]["session_id"] == "session-a"
    assert "hidden" not in json.dumps(view)
    assert view["topology"]["commit"] == "a" * 40


@pytest.mark.asyncio
async def test_signal_is_requested_until_observed_and_replay_never_posts_twice(bound):
    service, client, _ = bound
    command_id = str(uuid4())
    result = await service.command("owner", "project-a", "job-test", command_id, "PAUSE")
    assert result["state"] == "REQUESTED"
    assert (await service.command("owner", "project-a", "job-test", command_id, "PAUSE")) == result
    assert sum(c[0] == "POST" for c in client.calls) == 1
    client.raw["job"]["status"] = "suspended"
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    assert view["commands"][0]["state"] == "CONFIRMED"
    assert (await service.command("owner", "project-a", "job-test", str(uuid4()), "RESUME"))["state"] == "REQUESTED"


@pytest.mark.asyncio
async def test_interrupted_job_cannot_use_resume_and_command_binding_cannot_change(bound):
    service, client, _ = bound
    client.raw["job"]["status"] = "interrupted"
    with pytest.raises(ServiceCheckError, match="NOT_AVAILABLE"):
        await service.command("owner", "project-a", "job-test", str(uuid4()), "RESUME")
    assert not any(c[0] == "POST" for c in client.calls)
    client.raw["job"]["status"] = "in_progress"
    identity = str(uuid4())
    await service.command("owner", "project-a", "job-test", identity, "PAUSE")
    with pytest.raises(ServiceCheckError, match="CONFLICT"):
        await service.command("owner", "project-a", "job-test", identity, "STOP")


@pytest.mark.asyncio
async def test_uncertain_delivery_is_durable_and_never_blindly_replayed(bound):
    service, client, _ = bound
    client.post_error = ServiceCheckError("WORKLOOP_UNAVAILABLE", 503)
    identity = str(uuid4())
    result = await service.command("owner", "project-a", "job-test", identity, "PAUSE")
    assert result["state"] == "UNCERTAIN"
    restarted = ProjectWorkloop(service.path, client)
    assert (await restarted.command("owner", "project-a", "job-test", identity, "PAUSE"))["state"] == "UNCERTAIN"
    with pytest.raises(ServiceCheckError, match="COMMAND_PENDING"):
        await restarted.command("owner", "project-a", "job-test", str(uuid4()), "PAUSE")
    assert sum(c[0] == "POST" for c in client.calls) == 1


@pytest.mark.asyncio
async def test_outage_keeps_cache_with_original_checked_at_and_disables_writes(bound):
    service, client, _ = bound
    old = await service.read("owner", "project-a", "job-test")
    client.offline = True
    current = await service.read("owner", "project-a", "job-test", fresh=True)
    assert current["stale"] and current["checked_at"] == old["checked_at"]
    with pytest.raises(ServiceCheckError, match="REFRESH_REQUIRED"):
        await service.command("owner", "project-a", "job-test", str(uuid4()), "STOP")
    assert not any(c[0] == "POST" for c in client.calls)


def question():
    return {"event_id": "question-1", "event": "user-questions/request", "node": "build", "request": {"questions": [{"id": "q", "question": "Which color?", "options": [{"label": "Blue"}, {"label": "Green"}]}]}}


@pytest.mark.asyncio
async def test_answer_revalidates_request_and_uses_native_batch_envelope(bound):
    service, client, _ = bound
    client.pending = [question()]
    current = await service.read("owner", "project-a", "job-test", fresh=True)
    request = current["requests"][0]
    assert current["tasks"][0]["state"] == "WAITING_INPUT"
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        await service.command("owner", "project-a", "job-test", str(uuid4()), "ANSWER", "question-1", "b" * 64, {"answers": []})
    with pytest.raises(ServiceCheckError, match="RESPONSE_INVALID"):
        await service.command("owner", "project-a", "job-test", str(uuid4()), "ANSWER", "question-1", request["source_digest"], {"answers": [{"id": "q", "selected": ["Invalid"]}]})
    answer = {"answers": [{"id": "q", "selected": ["Blue"]}]}
    result = await service.command("owner", "project-a", "job-test", str(uuid4()), "ANSWER", "question-1", request["source_digest"], answer)
    assert result["state"] == "CONFIRMED"
    posted = [c for c in client.calls if c[0] == "POST"]
    assert posted[0][2] == {"answers": answer, "by": "vaiplatform:owner"}


@pytest.mark.asyncio
async def test_rejected_remote_answer_does_not_hide_waiting_question(bound):
    service, client, _ = bound
    q = question()
    client.raw["events"] = [{"event_type": "approval_requested", "payload": q}, {"event_type": "approval_answered", "payload": {"event_id": q["event_id"], "ok": False}}]
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    assert len(view["requests"]) == 1
    client.raw["events"][-1]["payload"]["ok"] = True
    assert not (await service.read("owner", "project-a", "job-test", fresh=True))["requests"]


@pytest.mark.asyncio
async def test_frozen_topology_reads_recorded_commit_only(monkeypatch):
    spec = "nodes:\n  build: {role: coder}\n  test: {role: tester}\nedges:\n  - build.report -> test.context\n"
    read = AsyncMock(return_value={"content": base64.b64encode(spec.encode()).decode()})
    monkeypatch.setattr(mod, "Gitea", lambda: SimpleNamespace(request=read))
    client = mod.WorkloopClient()
    raw = Client().raw["job"]
    graph = await client.snapshot(raw)
    assert graph["state"] == "pinned" and graph["edges"] == [{"source": "build", "target": "test"}]
    assert read.call_args.args[1].endswith("?ref=" + "a" * 40)
    read.return_value = {"content": base64.b64encode(b"nodes: {other: {}}\nedges: []").decode()}
    graph = await client.snapshot(raw)
    assert graph["state"] == "unavailable" and graph["edges"] == []


def test_raw_credentials_do_not_reach_the_browser():
    result = text("Authorization: Bearer abc123 api_key=secret123 xoxb-12345-password")
    assert all(value not in result for value in ["abc123", "secret123", "xoxb-12345-password"])


def test_native_gateway_raw_envelope_is_recognized():
    source = question()
    source["raw"] = {"event": source.pop("event"), "request": source.pop("request")}
    request = mod.approval_request(source, {"job_id": "job-test", "project_id": "p", "title": "Build", "linked_at": "now"})
    assert request["supported"] and request["kind"] == "question"


@pytest.mark.asyncio
async def test_terminal_job_never_shows_running_tasks_and_review_rounds_are_grouped(bound):
    service, client, _ = bound
    client.raw["job"]["status"] = "completed"
    client.raw["events"] = [
        {"event_type": "node_started", "payload": {"node": "build"}},
        {"event_type": "node_started", "payload": {"node": "test--r1"}},
        {"event_type": "node_terminal", "payload": {"node": "test--r1", "status": "DONE_WITH_CONCERNS"}},
        {"event_type": "node_done", "payload": {"node": "test--r1", "status": "IN_PROGRESS"}},
    ]
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    assert [t["id"] for t in view["tasks"]] == ["build", "test"]
    assert view["tasks"][0]["state"] == "UNCONFIRMED"
    assert view["tasks"][1]["state"] == "DONE_WITH_CONCERNS"
    assert view["tasks"][1]["attempts"] == ["test--r1"]


@pytest.mark.asyncio
async def test_human_review_gate_is_bound_to_the_jobs_own_event_and_answered_via_review_api(bound):
    service, client, _ = bound
    event = {"kind": "node_review", "gate": "test", "contract_n": "bound-contract", "criteria": "Tests pass", "round": 1}
    client.raw["events"] = [{"event_type": "node_review_pending", "payload": {**event, "node": "?", "request_id": "review-a"}}]
    original = client.request
    async def request(method, path, body=None):
        if method == "GET" and path == "/reviews/review-a":
            return {"id": "review-a", "state": "pending", "event": event, "submitted_at": "2026-10-28T01:00:00Z"}
        return await original(method, path, body)
    client.request = request
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    gate = view["requests"][0]
    assert gate["origin"] == "workflow_gate" and view["tasks"][1]["state"] == "WAITING_INPUT"
    await service.command("owner", "project-a", "job-test", str(uuid4()), "ANSWER", gate["request_id"], gate["source_digest"], {"decision": "allowed-once"})
    posted = [c for c in client.calls if c[0] == "POST"]
    assert posted[0][1] == "/reviews/review-a/approve" and posted[0][2]["actor"] == "vaiplatform:owner"
    event["gate"] = "unrelated-gate"
    view = await service.read("owner", "project-a", "job-test", fresh=True)
    assert not view["requests"][0]["supported"]


@pytest.mark.asyncio
async def test_all_routes_authorize_before_shared_remote_access(monkeypatch):
    remote = Mock()
    monkeypatch.setattr(api, "workloop_service", remote)
    monkeypatch.setattr(api, "live_service", lambda: object())
    monkeypatch.setattr(api, "authorize_project", AsyncMock(side_effect=ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404)))
    project, actor, session = uuid4(), SimpleNamespace(id=uuid4(), is_superuser=True), AsyncMock()
    calls = [lambda: api.jobs(project, session, actor, Response()), lambda: api.job(project, "job-test", session, actor, Response()), lambda: api.reports(project, "job-test", session, actor, Response()), lambda: api.link(project, api.LinkCommand(job_id="job-test", title="Test", confirm_repository="admin/app"), session, actor), lambda: api.command_job(project, "job-test", api.JobCommand(command_id=uuid4(), action="PAUSE"), session, actor), lambda: api.candidates(project, session, actor, Response())]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 404
    remote.assert_not_called()


@pytest.mark.asyncio
async def test_link_requires_admin_confirmation_and_execute_permission(monkeypatch):
    remote = Mock()
    monkeypatch.setattr(api, "workloop_service", remote)
    monkeypatch.setattr(api, "live_service", lambda: object())
    monkeypatch.setattr(api, "authorize_project", AsyncMock(return_value={"repository": "admin/app"}))
    execute = AsyncMock()
    monkeypatch.setattr(api, "ensure_flow_permission", execute)
    project, actor, session = uuid4(), SimpleNamespace(id=uuid4(), is_superuser=False), AsyncMock()
    command = api.LinkCommand(job_id="job-test", title="Test", confirm_repository="admin/app")
    with pytest.raises(HTTPException) as exc:
        await api.link(project, command, session, actor)
    assert exc.value.status_code == 403
    actor.is_superuser = True
    with pytest.raises(HTTPException) as exc:
        await api.link(project, command.model_copy(update={"confirm_repository": "wrong"}), session, actor)
    assert exc.value.status_code == 422
    execute.side_effect = ServiceCheckError("DENIED", 403)
    with pytest.raises(HTTPException):
        await api.command_job(project, "job-test", api.JobCommand(command_id=uuid4(), action="STOP"), session, actor)
    remote.assert_not_called()


@pytest.mark.asyncio
async def test_notification_index_filters_revoked_projects_before_reads(monkeypatch):
    service = SimpleNamespace(projects=Mock(return_value=["allowed", "revoked"]), index=AsyncMock(return_value={"items": [{"job_id": "job-test", "project_id": "allowed", "requests": []}]}))
    monkeypatch.setattr(api, "workloop_service", lambda: service)
    monkeypatch.setattr(api, "live_service", lambda: object())
    async def authorize(_live, _session, _actor, project):
        if project == "revoked":
            raise ServiceCheckError("DENIED", 403)
    monkeypatch.setattr(api, "authorize_project", authorize)
    actor = SimpleNamespace(id=uuid4())
    result = await api.attention(AsyncMock(), actor, Response())
    assert len(result["items"]) == 1
    service.index.assert_awaited_once_with(str(actor.id), "allowed")

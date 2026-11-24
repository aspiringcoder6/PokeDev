from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4
import asyncio

from fastapi import HTTPException, Response
import pytest

from langflow.adlc.live_workflows import LiveStore
from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.workspace_dashboard import summarize
from langflow.api.v1 import adlc_workspace as api, adlc_live

NOW = datetime(2026, 10, 28, 3, tzinfo=timezone.utc)
PROJECT = {"project_id": "a", "name": "Alpha", "repository": "admin/alpha"}


def row(identity, state="SUCCEEDED", created="2026-10-27T20:00:00Z", **extra):
    return {"run_id": identity, "project_id": "a", "title": identity, "repository": "admin/alpha", "state": state, "created_at": created, "phase": "execution", "nodes": [], **extra}


def test_totals_count_runs_once_and_exclude_waiting_and_unconfirmed_from_success_rate():
    succeeded = row("good", nodes=[{"id": "DEV", "kind": "implement", "state": "DONE"}, {"id": "DEV_REUSE", "kind": "implement", "state": "DONE", "reused_from": "old"}, {"id": "SYS_VERIFY", "role": "runner", "state": "DONE"}])
    runs = [succeeded, row("bad", "FAILED"), row("plan", "PLAN_READY"), row("unknown", "UNCONFIRMED"), row("blocked", "BLOCKED"), succeeded]
    data = summarize([PROJECT], runs, [], [], [], days=7, now=NOW)
    assert data["totals"]["runs"] == 5
    assert data["totals"]["finished"] == 2
    assert data["totals"]["success_rate"] == .5
    assert sum(d["total"] for d in data["daily"]) == 5
    assert next(d for d in data["daily"] if d["date"] == "2026-10-28")["total"] == 5
    assert sum(s["count"] for s in data["statuses"]) == 5
    assert next(r for r in data["roles"] if r["role"] == "developer")["total"] == 1
    assert next(r for r in data["roles"] if r["role"] == "control")["total"] == 1
    assert len(data["history"]) == 5


def test_local_midnight_boundary_and_old_pending_questions_are_not_hidden_by_date_filter():
    runs = [row("boundary", created="2026-10-20T17:00:00Z"), row("before", created="2026-10-20T16:59:59Z"), row("old", "RUNNING", "2026-09-01T00:00:00Z")]
    request = {"request_id": "q1", "run_id": "old", "kind": "question", "status": "PENDING", "can_respond": True, "created_at": "2026-10-01T12:00:00Z", "title": "Cần chọn phương án"}
    data = summarize([PROJECT], runs, [], [request, request], [], days=7, now=NOW)
    assert data["range"] == {"days": 7, "from": "2026-10-22", "to": "2026-10-28"}
    assert data["totals"]["runs"] == 0
    assert data["totals"]["success_rate"] is None
    assert data["totals"]["active_now"] == 1
    questions = [r for r in data["attention"] if r["kind"] == "question"]
    assert len(questions) == 1 and "focus=q1" in questions[0]["href"]
    assert questions[0]["since"].startswith("2026-10-01")
    start = summarize([PROJECT], [row("at", created="2026-10-21T17:00:00Z"), row("out", created="2026-10-21T16:59:59Z")], [], [], [], days=7, now=NOW)
    assert start["totals"]["runs"] == 1


def test_terminal_run_status_wins_over_a_stale_waiting_node():
    runs = [row("finished", nodes=[{"id": "DEV", "state": "WAITING_INPUT"}]), row("failed", "FAILED", nodes=[{"id": "DEV", "state": "WAITING_INPUT"}])]
    data = summarize([PROJECT], runs, [], [], [], now=NOW)
    assert data["totals"]["finished"] == 2
    assert data["totals"]["success_rate"] == .5
    assert data["totals"]["waiting_now"] == 0
    assert all(item["kind"] != "question" for item in data["attention"])
    assert {item["state"]: item["count"] for item in data["statuses"]}["failed"] == 1


def test_queue_deduplicates_sources_and_never_offers_to_resend_uncertain_responses():
    requests = [{"request_id": "q", "run_id": "active", "kind": "permission", "status": "UNCERTAIN", "can_respond": True, "created_at": None}]
    runs = [row("active", "RUNNING"), row("plan", "PLAN_READY"), row("done", handover={"state": "MERGED"}), row("recover", "UNCONFIRMED", recovery_status={"available": True, "saved_at": NOW.timestamp()})]
    reviews = [{"kind": "plan", "run_id": "plan"}, {"kind": "recovery", "run_id": "recover"}, {"kind": "issue", "proposal_id": "i", "project_id": "a", "run_title": "Issue"}] * 2
    data = summarize([PROJECT], runs, [], requests, reviews, now=NOW, permissions={"plan": False, "project:a": False})
    assert len(data["attention"]) == 4
    assert not next(a for a in data["attention"] if a["id"] == "input:q")["can_act"]
    assert next(a for a in data["attention"] if a["id"] == "plan:plan")["action_label"] == "Xem trạng thái"
    assert next(a for a in data["attention"] if a["id"] == "recovery:recover")["href"].endswith("focus=recovery")
    assert all(a["kind"] != "handover" for a in data["attention"])


def test_project_filter_and_incomplete_sources_do_not_fabricate_unknown_times_or_zero_success():
    data = summarize([PROJECT], [row("bad-time", "FAILED", created="broken"), row("other", project_id="b")], [{"project_id": "a"}, {"project_id": "b"}], [], [], project_id="a", now=NOW, sources={"errors": ["questions"], "native_connected": False})
    assert data["totals"]["runs"] == 0 and data["totals"]["success_rate"] is None
    assert data["totals"]["workflows"] == 1
    assert data["quality"]["invalid_timestamps"] == 1
    assert data["attention"][0]["since"] is None
    assert len(data["history"]) == 1


def test_retry_and_explicit_close_resolve_old_failure_actions_without_removing_history():
    data = summarize([PROJECT], [row("old", "FAILED"), row("retry", parent_run_id="old", handover={"state": "MERGED"}), row("closed", "FAILED", error_code="LIVE_INTERRUPTED_RUN_CLOSED"), row("plan", "PLAN_READY")], [], [], [], now=NOW)
    assert len(data["history"]) == 4
    assert [item["kind"] for item in data["attention"]] == ["plan"]
    assert data["attention"][0]["since"] is None


@pytest.mark.asyncio
async def test_dashboard_filters_read_permissions_and_aggregates_beyond_history_limit(tmp_path, monkeypatch):
    owner, outsider = str(uuid4()), str(uuid4())
    store = LiveStore(tmp_path / "live.db")
    first, hidden, foreign = str(uuid4()), str(uuid4()), str(uuid4())
    repo = {"id": 1, "name": "Alpha", "full_name": "admin/alpha", "html_url": "http://gitea/admin/alpha", "default_branch": "main"}
    store.save_project(owner, first, repo, "private-cache", "a" * 40)
    store.save_project(owner, hidden, {**repo, "id": 2, "name": "Denied"}, "hidden-cache", "b" * 40)
    store.save_project(outsider, foreign, repo, "foreign-cache", "c" * 40)
    delivery = str(uuid4())
    with store.db() as db:
        for i in range(131):
            pid, who = (first, owner) if i < 129 else (hidden, owner) if i == 129 else (foreign, outsider)
            payload = row(str(uuid4()), "PLAN_READY", project_id=pid, delivery_id=delivery, owner=who)
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (payload["run_id"], who, pid, delivery, json.dumps(payload)))
    monitor = SimpleNamespace(start=Mock(), pending=Mock(return_value=[]), legacy_reviews=AsyncMock(return_value=[]), connected=asyncio.Event())
    service = SimpleNamespace(store=store, observe=lambda r: store.update(r["run_id"], {"state": r["state"]}), recovery=SimpleNamespace(inspect=lambda r: {}), human_input=monitor, issue_service=SimpleNamespace(attention=lambda owner: []))
    async def authorize(service, session, actor, identity, **kwargs):
        if identity == hidden: raise ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404)
    monkeypatch.setattr(api, "authorize_project", authorize)
    monkeypatch.setattr(api, "source", AsyncMock(return_value=(None, SimpleNamespace(folder_id=UUID(first)))))
    monkeypatch.setattr(api, "permission", AsyncMock(return_value=False))
    monkeypatch.setattr(api, "live_service", lambda: service)
    monkeypatch.setattr(adlc_live, "legacy_runs", lambda owner: [])
    actor, session, response = SimpleNamespace(id=UUID(owner)), AsyncMock(), Response()
    data = await api.dashboard(session, actor, response, days=28)
    assert len(data["history"]) == 129
    assert data["totals"]["projects"] == 1
    assert {p["project_id"] for p in data["projects"]} == {first}
    assert all(not a["can_act"] for a in data["attention"])
    assert "private-cache" not in json.dumps(data) and "foreign-cache" not in json.dumps(data)
    assert response.headers["Cache-Control"] == "no-store"
    with pytest.raises(HTTPException) as denied:
        await api.dashboard(session, actor, Response(), days=28, project_id=UUID(hidden))
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as missing:
        await api.dashboard(session, actor, Response(), days=28, project_id=uuid4())
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_authorization_outage_is_an_error_instead_of_empty_success(monkeypatch):
    service = SimpleNamespace(store=SimpleNamespace(projects=lambda owner: [{"project_id": str(uuid4())}]))
    monkeypatch.setattr(api, "live_service", lambda: service)
    monkeypatch.setattr(api, "authorize_project", AsyncMock(side_effect=ServiceCheckError("AUTH_UNAVAILABLE", 503)))
    with pytest.raises(HTTPException) as exc:
        await api.dashboard(AsyncMock(), SimpleNamespace(id=uuid4()), Response(), days=28)
    assert exc.value.status_code == 503

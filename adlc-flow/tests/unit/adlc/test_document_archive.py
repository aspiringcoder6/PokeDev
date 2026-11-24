from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException, Response
import pytest

from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.document_intake import DocumentIntake
from langflow.api.v1 import adlc_document_intake as api
from test_document_intake import approved, Client, Pages, source


@pytest.fixture
async def intake(tmp_path):
    client, pages = Client(), Pages()
    service = DocumentIntake(tmp_path / "intake.sqlite3", client, pages)
    await service.sync("owner")
    return service, client, pages


@pytest.mark.asyncio
async def test_archive_survives_sync_and_late_callbacks_but_new_threads_still_arrive(intake):
    service, client, _ = intake
    await approved(intake)
    archived = service.archive("owner", 1)
    assert not archived["approval"]
    assert not service.rows("owner")
    client.docs += [source(2), {**source(3), "lifecycle_id": "lc-new-thread"}]
    await service.sync("owner", force=True)
    assert [r["document_id"] for r in service.rows("owner")] == ["3"]
    assert len(service.rows("owner", include_archived=True)) == 3
    assert service.get("owner", 2, include_archived=True)["archived_at"] == archived["archived_at"]
    with pytest.raises(ServiceCheckError, match="DOCUMENT_ARCHIVED"):
        service.change("owner", 1, lambda row: row.update(state="UPDATED"))


@pytest.mark.asyncio
async def test_restore_requires_review_and_does_not_reenable_outbound_sharing(intake):
    service, _, _ = intake
    await approved(intake)
    service.change("owner", 1, lambda row: row.update(progress={"enabled": True}, notifications={"enabled": True}))
    service.archive("owner", 1)
    row = service.restore("owner", 1)
    assert row["state"] == "NEEDS_REVIEW" and not row["approval"]
    assert not row["progress"]["enabled"] and not row["notifications"]["enabled"]
    assert len(service.rows("owner")) == 1


@pytest.mark.asyncio
async def test_archive_cancels_queued_notices_and_keeps_the_saved_bot_connection(intake):
    service, _, _ = intake
    service.notifications
    with service.db() as db, db:
        db.execute("INSERT INTO intake_slack_credentials VALUES('owner','encrypted-token','{}')")
        db.execute("INSERT INTO intake_slack_outbox(id,owner,document,state) VALUES('notice','owner','1','PENDING')")
    service.archive("owner", 1)
    with service.db() as db:
        assert db.execute("SELECT state FROM intake_slack_outbox WHERE id='notice'").fetchone()[0] == "CANCELLED"
        assert db.execute("SELECT COUNT(*) FROM intake_slack_credentials WHERE owner='owner'").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_archive_is_owner_scoped_and_cannot_hide_active_execution(intake):
    service, _, _ = intake
    await service.sync("other", force=True)
    service.change("owner", 1, lambda row: row.update(run_id="active-run"))
    with pytest.raises(ServiceCheckError, match="ARCHIVE_ACTIVE"):
        service.archive("owner", 1)
    service.change("owner", 1, lambda row: row.update(run_id=None, revision_request={"state": "PROCESSING"}))
    with pytest.raises(ServiceCheckError, match="ARCHIVE_ACTIVE"):
        service.archive("owner", 1)
    service.change("owner", 1, lambda row: row.update(revision_request={"state": "FAILED"}))
    service.archive("owner", 1)
    assert len(service.rows("other")) == 1
    with pytest.raises(ServiceCheckError, match="DOCUMENT_NOT_FOUND"):
        service.restore("unrelated-owner", 1)


@pytest.mark.asyncio
async def test_archive_and_restore_api_authorize_before_changing_the_inbox(intake, monkeypatch):
    service, _, _ = intake
    monkeypatch.setattr(api, "document_intake", lambda: service)
    monkeypatch.setattr(api, "access", AsyncMock(side_effect=ServiceCheckError("DENIED", 403)))
    actor = SimpleNamespace(id="owner", is_superuser=True)
    for operation in (api.archive_document, api.restore_document):
        with pytest.raises(HTTPException) as exc:
            await operation(1, AsyncMock(), actor)
        assert exc.value.status_code == 403
    assert not service.get("owner", 1).get("archived_at")


@pytest.mark.asyncio
async def test_archived_content_is_readable_offline_and_api_refuses_a_running_run(intake, monkeypatch):
    service, _, pages = intake
    service._progress = SimpleNamespace(wake=SimpleNamespace(set=Mock()))
    service.change("owner", 1, lambda row: row.update(run_id="run-1", run_started_at="2026-10-29T00:00:00Z"))
    run = {"state": "RUNNING"}
    live = SimpleNamespace(store=SimpleNamespace(get=lambda *args: run), observe=lambda value: value)
    monkeypatch.setattr(api, "document_intake", lambda: service)
    monkeypatch.setattr(api, "live_service", lambda: live)
    monkeypatch.setattr(api, "access", AsyncMock())
    actor = SimpleNamespace(id="owner", is_superuser=True)
    with pytest.raises(HTTPException) as exc:
        await api.archive_document(1, AsyncMock(), actor)
    assert exc.value.status_code == 409
    run["state"] = "SUCCEEDED"
    archived = await api.archive_document(1, AsyncMock(), actor)
    assert archived["state"] == "ARCHIVED" and archived["run_id"] == "run-1"
    pages.offline = True
    service.refresh = AsyncMock(side_effect=AssertionError("archived reads must not contact Confluence"))
    result = await api.read_document(1, AsyncMock(), actor, Response())
    assert result["state"] == "ARCHIVED" and not result["stale"]


@pytest.mark.asyncio
@pytest.mark.parametrize("permitted", [True, False])
async def test_channel_rules_remain_manageable_after_archiving_but_require_project_access(intake, monkeypatch, permitted):
    service, _, _ = intake
    row = await approved(intake)
    service.assign("owner", 1, {"project_id": row["project_id"], "repository": row["repository"]}, "", True)
    service.archive("owner", 1)
    assert not service.rows("owner") and service.rules("owner")
    authorize = AsyncMock(side_effect=None if permitted else ServiceCheckError("DENIED", 403))
    monkeypatch.setattr(api, "document_intake", lambda: service)
    monkeypatch.setattr(api, "live_service", lambda: object())
    monkeypatch.setattr(api, "authorize_project", authorize)
    result = await api.inbox(AsyncMock(), SimpleNamespace(id="owner", is_superuser=False), Response())
    assert not result["items"]
    assert bool(result["rules"]) == permitted
    authorize.assert_awaited_once()

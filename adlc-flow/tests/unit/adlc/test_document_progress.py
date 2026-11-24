import asyncio
import copy
from html import escape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import HTTPException
import pytest

from langflow.adlc.document_intake import DocumentIntake, public_document
from langflow.adlc.document_progress import ProgressPublisher, facts, report_title
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_document_intake as api
from test_document_intake import Client, Pages, source


class Gateway:
    def __init__(self):
        self.calls, self.page = [], None
        self.visible, self.lose_create_reply, self.offline = True, False, False

    async def call(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if self.offline:
            raise ServiceCheckError("PROGRESS_CONFLUENCE_UNAVAILABLE", 503)
        if tool == "confluence_search":
            return {"results": [copy.deepcopy(self.page)] if self.page and self.visible else []}
        if tool == "confluence_get_page":
            return copy.deepcopy(self.page)
        if tool == "confluence_create_page":
            self.page = {
                "id": "900",
                "title": arguments["title"],
                "body": "<p>" + escape(arguments["body_markdown"]) + "</p>",
                "version": 1,
                "link": "https://example.atlassian.net/wiki/spaces/SD/pages/900/Progress",
            }
            if self.lose_create_reply:
                raise ServiceCheckError("PROGRESS_CONFLUENCE_UNAVAILABLE", 503)
            return copy.deepcopy(self.page)
        if tool == "confluence_update_page":
            self.page.update(body="<p>" + escape(arguments["body_markdown"]) + "</p>", version=self.page["version"] + 1)
            return copy.deepcopy(self.page)
        raise AssertionError(tool)


@pytest.fixture
async def progress(tmp_path):
    client, pages, gateway = Client(), Pages(), Gateway()
    intake = DocumentIntake(tmp_path / "intake.db", client, pages)
    await intake.sync("owner")
    project = {"project_id": str(uuid4()), "repository": "admin/application"}
    intake.assign("owner", 1, project, "", share_progress=True)
    live = SimpleNamespace(
        store=SimpleNamespace(get=Mock()),
        observe=lambda row: row,
        human_input=SimpleNamespace(pending=Mock(return_value=[])),
    )
    publisher = ProgressPublisher(intake, live, gateway, AsyncMock())
    return publisher, intake, gateway, live, client, project


@pytest.mark.asyncio
async def test_creates_a_separate_real_snapshot_once_without_approving_or_running(progress):
    publisher, intake, gateway, _, client, _ = progress
    initial = intake.get("owner", 1)
    result = await publisher.publish("owner", 1, force=True)
    assert result["state"] == "SYNCED" and result["page_id"] == "900"
    assert "NOT_STARTED" in gateway.page["body"] and "Chưa có lượt chạy" in gateway.page["body"]
    assert "Slack channel: C01234567" in gateway.page["body"]
    assert "Backend and tests" not in gateway.page["body"]
    await publisher.publish("owner", 1, force=True)
    assert [t for t, _ in gateway.calls].count("confluence_create_page") == 1
    assert not any(t == "confluence_update_page" for t, _ in gateway.calls)
    current = intake.get("owner", 1)
    assert current["page_id"] == initial["page_id"] == "123" and current.get("approval") == initial.get("approval")
    assert not current.get("run_id") and all(c[0] == "GET" for c in client.calls)
    assert "lease" not in public_document(current)["progress"]


@pytest.mark.asyncio
async def test_native_progress_human_input_tests_and_pr_are_mirrored_with_origin_binding(progress):
    publisher, intake, gateway, live, _, project = progress
    run_id = str(uuid4())
    intake.change("owner", 1, lambda row: row.update(run_id=run_id))
    run = {
        "run_id": run_id,
        "project_id": project["project_id"],
        "state": "RUNNING",
        "phase": "execution",
        "origin_document": {"document_id": "1", "lifecycle_id": "lc-thread", "page_version": 8},
        "nodes": [{"id": "build", "state": "DONE"}, {"id": "verify", "state": "WAITING_INPUT"}],
        "checks": [{"tests": [{"passed": True}, {"passed": False}]}],
    }
    live.store.get.return_value = run
    live.human_input.pending.return_value = [{"request_id": "waiting"}]
    await publisher.publish("owner", 1, force=True)
    assert "WAITING_INPUT" in gateway.page["body"] and "Task hoàn tất: 1/2" in gateway.page["body"]
    assert (
        "Kiểm tra đạt: 1/2" in gateway.page["body"]
        and "Phiên bản tài liệu dùng cho lượt chạy: 8" in gateway.page["body"]
    )
    run.update(state="SUCCEEDED", handover={"pull": {"url": "http://gitea/admin/application/pulls/1", "merged": False}})
    live.human_input.pending.return_value = []
    await publisher.publish("owner", 1, force=True)
    assert "SUCCEEDED" in gateway.page["body"] and "pulls/1" in gateway.page["body"]
    assert [t for t, _ in gateway.calls].count("confluence_create_page") == 1
    assert [t for t, _ in gateway.calls].count("confluence_update_page") == 1
    run["origin_document"]["document_id"] = "another-document"
    assert facts(intake.get("owner", 1), live)["run_state"] == "UNCONFIRMED"


@pytest.mark.asyncio
async def test_unknown_create_is_not_repeated_and_reconciles_after_search_index_catches_up(progress):
    publisher, intake, gateway, live, _, _ = progress
    gateway.lose_create_reply = True
    assert (await publisher.publish("owner", 1, force=True))["state"] == "UNCONFIRMED"
    gateway.visible = False
    restarted = ProgressPublisher(intake, live, gateway, AsyncMock())
    assert (await restarted.publish("owner", 1, force=True))["error_code"] == "PROGRESS_CREATE_UNCONFIRMED"
    assert [t for t, _ in gateway.calls].count("confluence_create_page") == 1
    gateway.visible = True
    assert (await restarted.publish("owner", 1, force=True))["state"] == "SYNCED"
    assert [t for t, _ in gateway.calls].count("confluence_create_page") == 1


@pytest.mark.asyncio
async def test_outage_preserves_report_and_does_not_change_execution_permission(progress):
    publisher, intake, gateway, _, _, _ = progress
    first = await publisher.publish("owner", 1, force=True)
    gateway.offline = True
    result = await publisher.publish("owner", 1, force=True)
    assert result["state"] == "ERROR" and result["link"] == first["link"]
    assert result["synced_at"] == first["synced_at"]
    assert intake.get("owner", 1)["state"] == "NEEDS_REVIEW" and not intake.get("owner", 1).get("approval")


@pytest.mark.asyncio
async def test_existing_human_page_and_manual_report_edits_are_not_overwritten(progress):
    publisher, intake, gateway, _, _, _ = progress
    gateway.page = {
        "id": "900",
        "title": report_title(intake.get("owner", 1)),
        "body": "Human authored",
        "version": 1,
        "link": "https://example.atlassian.net/wiki/spaces/SD/pages/900/Progress",
    }
    result = await publisher.publish("owner", 1, force=True)
    assert result["error_code"] == "PROGRESS_REPORT_BINDING_CHANGED"
    assert not any(t in {"confluence_create_page", "confluence_update_page"} for t, _ in gateway.calls)
    gateway.page = None
    await publisher.publish("owner", 1, force=True)
    gateway.page["version"] += 1
    result = await publisher.publish("owner", 1, force=True)
    assert result["error_code"] == "PROGRESS_REPORT_MODIFIED"
    assert not any(t == "confluence_update_page" for t, _ in gateway.calls)


@pytest.mark.asyncio
async def test_disabled_or_unauthorized_owner_never_reads_or_writes_remote(progress):
    publisher, intake, gateway, _, _, _ = progress
    publisher.configure("owner", 1, False)
    await publisher.publish("owner", 1, force=True)
    assert not gateway.calls
    publisher.configure("owner", 1, True)
    publisher.permission.side_effect = ServiceCheckError("DENIED", 403)
    with pytest.raises(ServiceCheckError, match="DENIED"):
        await publisher.publish("owner", 1, force=True)
    assert not gateway.calls


@pytest.mark.asyncio
async def test_disabling_and_reenabling_refreshes_the_existing_report(progress):
    publisher, _, gateway, _, _, _ = progress
    await publisher.publish("owner", 1, force=True)
    publisher.configure("owner", 1, False)
    publisher.configure("owner", 1, True)
    assert (await publisher.publish("owner", 1))["state"] == "SYNCED"
    assert [tool for tool, _ in gateway.calls].count("confluence_create_page") == 1


def test_planning_nodes_are_not_counted_as_implemented_code_tasks():
    row = {
        "owner": "owner",
        "document_id": "1",
        "lifecycle_id": "lc-thread",
        "title": "Feature",
        "state": "APPROVED",
        "source_status": "approved",
        "project_id": "project",
        "run_id": "run",
    }
    run = {
        "project_id": "project",
        "state": "PLAN_READY",
        "phase": "planning",
        "origin_document": {"document_id": "1", "lifecycle_id": "lc-thread"},
        "nodes": [{"state": "DONE"}],
        "plan": {"tasks": [{"id": "code"}, {"id": "test"}]},
    }
    live = SimpleNamespace(
        store=SimpleNamespace(get=Mock(return_value=run)),
        observe=lambda row: row,
        human_input=SimpleNamespace(pending=Mock(return_value=[])),
    )
    snapshot = facts(row, live)
    assert snapshot["tasks_done"] == 0 and snapshot["tasks_total"] == 2 and snapshot["run_state"] == "PLAN_READY"


@pytest.mark.asyncio
async def test_channel_assignment_inherits_explicit_progress_sharing_without_auto_approval(progress):
    _, intake, _, _, client, project = progress
    intake.assign("owner", 1, project, "", automatic=True, share_progress=True, notify_slack=True)
    client.docs.append(source(2))
    await intake.sync("owner", force=True)
    row = intake.get("owner", 2)
    assert row["progress"]["enabled"] and row["project_id"] == project["project_id"]
    assert row["notifications"]["enabled"]
    assert row["state"] == "NEEDS_REVIEW" and not row.get("approval") and not row.get("run_id")


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["archived", "removed", "invalid"])
async def test_background_loop_keeps_publishing_and_delivering_after_unavailable_old_sources(
    progress, monkeypatch, caplog, unavailable
):
    publisher, intake, _, _, client, _ = progress
    client.docs.append({**source(2), "lifecycle_id": "lc-new-request"})
    await intake.sync("owner", force=True)
    if unavailable == "archived":
        intake.archive("owner", 1)
    else:
        original_get = intake.get

        def get(owner, identity, **kwargs):
            if str(identity) == "1":
                if unavailable == "removed":
                    raise ServiceCheckError("INTAKE_DOCUMENT_NOT_FOUND", 404)
                raise ValueError("private-source-body-must-not-enter-logs")
            return original_get(owner, identity, **kwargs)

        monkeypatch.setattr(intake, "get", get)
    publisher.publish = AsyncMock()
    notices = SimpleNamespace(live=None, observe=AsyncMock(), deliver=AsyncMock(side_effect=asyncio.CancelledError))
    intake._notifications = notices
    # End the test at the delivery boundary: reaching this point proves the
    # old source did not kill the workspace worker before handling source 2.
    with pytest.raises(asyncio.CancelledError):
        await publisher.loop()
    publisher.publish.assert_awaited_once_with("owner", "2")
    notices.observe.assert_awaited_once_with("owner", "2")
    notices.deliver.assert_awaited_once()
    assert "private-source-body-must-not-enter-logs" not in caplog.text


@pytest.mark.asyncio
async def test_progress_endpoint_authorizes_before_enabling_any_publication(progress, monkeypatch):
    _, intake, gateway, _, _, _ = progress
    monkeypatch.setattr(api, "document_intake", lambda: intake)
    monkeypatch.setattr(api, "live_service", lambda: object())
    monkeypatch.setattr(api, "authorize_project", AsyncMock(side_effect=ServiceCheckError("DENIED", 403)))
    actor = SimpleNamespace(id="owner", is_superuser=True)
    with pytest.raises(HTTPException) as exc:
        await api.progress_document(1, api.ProgressCommand(enabled=True), AsyncMock(), actor)
    assert exc.value.status_code == 403 and not gateway.calls


def test_factory_persona_keeps_original_model_and_only_adds_readonly_status_instructions():
    path = Path(__file__).resolve().parents[4] / "integration-sources/factory-wilson/agents/orchestrator.md"
    body = path.read_text(encoding="utf-8")
    body = " ".join(body.split())
    assert "model: zai-org/GLM-5.3-Flash" in body
    assert "confluence_search" in body and "confluence_get_page" in body
    assert "không tạo tài liệu yêu cầu mới" in body and "không sửa trang báo cáo" in body
    assert "Slack channel và Slack thread" in body and "thời điểm cập nhật" in body


def test_slack_report_links_open_the_configured_workspace_and_reject_foreign_hosts(monkeypatch):
    row = {"slack_channel": "C01234567", "slack_thread": "123.456"}
    monkeypatch.setenv("VAI_SLACK_WORKSPACE_URL", "https://adlcfactory.slack.com/")
    assert public_document(row)["slack_url"] == "https://adlcfactory.slack.com/archives/C01234567/p123456"
    monkeypatch.setenv("VAI_SLACK_WORKSPACE_URL", "https://example.invalid/")
    assert "slack_url" not in public_document(row)

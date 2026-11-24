import copy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from langflow.adlc.document_intake import DocumentIntake, public_document
from langflow.adlc.document_revision import request_revision, check_revision
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_document_intake as api
from test_document_intake import Client, Pages


class Revisions(Client):
    lose_reply = False

    async def request(self, method, path, body=None):
        if method == "POST":
            self.calls.append((method, path, body))
            query = parse_qs(urlsplit(path).query)
            identity = path.split("/spec-docs/")[1].split("/")[0]
            doc = next(d for d in self.docs if str(d["id"]) == identity)
            assert query["status"] == ["needs_changes"]
            doc.update(status="needs_changes", detail={"review_comment": query["comment"][0]})
            if self.lose_reply:
                raise ServiceCheckError("WORKLOOP_UNAVAILABLE", 503)
            return {"ok": True}
        return await super().request(method, path, body)


class Spec:
    def __init__(self):
        self.calls = []
        self.lose_reply = False
        self.status = "running"
        self.starts = 0

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "call_agent":
            self.starts += 1
            if self.lose_reply:
                raise ServiceCheckError("INTAKE_REVISION_AGENT_UNAVAILABLE", 503)
            return {"ok": True, "invocation_id": f"ag-test-{self.starts}", "status": "running"}
        return {"invocation_id": arguments["invocation_id"], "status": self.status, "ok": self.status != "failed"}


@pytest.fixture
async def revisions(tmp_path):
    client, pages = Revisions(), Pages()
    intake = DocumentIntake(tmp_path / "intake.sqlite3", client, pages)
    intake.revision_tools = Spec()
    await intake.sync("owner")
    row = await intake.refresh("owner", 1)
    return intake, client, pages, intake.contract_digest(row)


@pytest.mark.asyncio
async def test_feedback_reaches_only_the_matching_source_without_dispatch_and_is_replay_safe(revisions):
    intake, client, _, digest = revisions
    identity = uuid4()
    row = await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter and permissions.")
    assert row["revision_request"]["state"] == "PROCESSING" and row["state"] == "NEEDS_CHANGES"
    assert not row.get("approval") and not row.get("run_id")
    await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter and permissions.")
    assert intake.revision_tools.starts == 1
    assert not any(method == "POST" for method, _, _ in client.calls)
    sent = intake.revision_tools.calls[0][1]
    assert sent["name"] == "spec" and sent["thread_ts"] == row["slack_thread"]
    assert sent["lifecycle_id"] == row["lifecycle_id"]
    assert row["page_body"] in sent["context"]
    assert "wire_comment" not in public_document(row)["revision_request"]


@pytest.mark.asyncio
async def test_stale_page_and_different_thread_never_submit_feedback(revisions):
    intake, client, pages, digest = revisions
    pages.version += 1
    with pytest.raises(ServiceCheckError, match="DOCUMENT_CHANGED"):
        await request_revision(intake, "owner", 1, digest, uuid4(), "Clarify the year filter.")
    client.docs[0]["slack_thread"] = "999.123456"
    with pytest.raises(ServiceCheckError, match="SOURCE_MISSING"):
        await request_revision(intake, "owner", 1, digest, uuid4(), "Clarify the year filter.")
    assert not any(method == "POST" for method, _, _ in client.calls)
    assert intake.revision_tools.starts == 0


@pytest.mark.asyncio
async def test_unknown_submission_is_reconciled_without_repeating_the_model_trigger(revisions):
    intake, client, _, digest = revisions
    intake.revision_tools.lose_reply = True
    identity = uuid4()
    first = await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    assert first["revision_request"]["state"] == "UNCONFIRMED"
    second = await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    assert second["revision_request"]["state"] == "UNCONFIRMED"
    assert intake.revision_tools.starts == 1

    candidate = copy.deepcopy(client.docs[0])
    candidate.update(id=2, invocation_id="ag-test-1", created_at=first["revision_request"]["at"])
    client.docs.append(candidate)
    attached = await check_revision(intake, "owner", 1, identity, "ag-test-1")
    assert attached["revision_request"]["state"] == "PROCESSING"
    assert intake.revision_tools.starts == 1


@pytest.mark.asyncio
async def test_revision_blocks_approval_until_a_real_new_page_and_supports_next_invocation(revisions):
    intake, client, pages, digest = revisions
    identity = uuid4()
    await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    with pytest.raises(ServiceCheckError, match="REVISION_PENDING"):
        await intake.decide("owner", 1, digest, "approve")
    with pytest.raises(ServiceCheckError, match="REVISION_PENDING"):
        await request_revision(intake, "owner", 1, digest, uuid4(), "Also clarify unit permissions.")
    pages.version += 1
    pages.body += "\nClarification added."
    row = await intake.refresh("owner", 1, fresh=True)
    assert row["revision_request"]["state"] == "PROCESSING"
    with pytest.raises(ServiceCheckError, match="REVISION_PENDING"):
        await intake.decide("owner", 1, intake.contract_digest(row), "approve")
    intake.revision_tools.status = "done"
    row = await check_revision(intake, "owner", 1, identity)
    assert row["revision_request"]["state"] == "UPDATED" and row["state"] == "CHANGED"
    old = copy.deepcopy(client.docs[0])
    old["id"] = 2
    old["status"] = "pending"
    client.docs.append(old)
    row = await request_revision(
        intake, "owner", 1, intake.contract_digest(row), uuid4(), "Also clarify unit permissions."
    )
    assert row["revision_request"]["source_document_id"] == "2"
    assert len(row["revision_history"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code", [("failed", "INTAKE_REVISION_AGENT_FAILED"), ("done", "INTAKE_REVISION_NO_UPDATE")]
)
async def test_failed_or_empty_completion_is_reported_and_a_new_nonce_can_retry(revisions, status, code):
    intake, client, _, digest = revisions
    request_id = uuid4()
    await request_revision(intake, "owner", 1, digest, request_id, "Clarify the year filter.")
    intake.revision_tools.status = status
    result = await check_revision(intake, "owner", 1, request_id)
    assert result["revision_request"]["state"] == "FAILED"
    assert result["revision_request"]["error_code"] == code
    assert not result.get("approval")
    await request_revision(intake, "owner", 1, digest, request_id, "Clarify the year filter.")
    assert intake.revision_tools.starts == 1
    await request_revision(intake, "owner", 1, digest, uuid4(), "Clarify the year filter.")
    assert intake.revision_tools.starts == 2
    assert not any(m == "POST" for m, _, _ in client.calls)


@pytest.mark.asyncio
async def test_new_page_is_required_before_reporting_updated_and_never_auto_approves(revisions):
    intake, _, pages, digest = revisions
    identity = uuid4()
    await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    pages.version += 1
    pages.body += "\nYear clarification."
    intake.revision_tools.status = "done"
    row = await check_revision(intake, "owner", 1, identity)
    assert row["revision_request"]["state"] == "UPDATED"
    assert row["state"] == "CHANGED" and not row.get("approval")


@pytest.mark.asyncio
async def test_concurrent_page_edit_cannot_hide_a_failed_invocation(revisions):
    intake, _, pages, digest = revisions
    identity = uuid4()
    await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    pages.version += 1
    pages.body += "\nAn independent editor changed this page."
    await intake.refresh("owner", 1, fresh=True)
    intake.revision_tools.status = "failed"
    row = await check_revision(intake, "owner", 1, identity)
    assert row["revision_request"]["state"] == "FAILED"
    assert row["revision_request"]["error_code"] == "INTAKE_REVISION_AGENT_FAILED"
    assert not row.get("approval")


@pytest.mark.asyncio
async def test_legacy_invocation_requires_the_same_thread_and_a_newer_matching_source(revisions):
    intake, client, _, digest = revisions
    identity = str(uuid4())
    intake.change(
        "owner",
        1,
        lambda r: r.update(
            revision_request={
                "id": identity,
                "at": "2026-10-29T00:00:00+00:00",
                "state": "SENT",
                "source_document_id": "1",
            }
        ),
    )
    candidate = copy.deepcopy(client.docs[0])
    candidate.update(id=2, invocation_id="ag-legacy", created_at="2026-10-29T00:05:00Z", slack_thread="999.123456")
    client.docs.append(candidate)
    with pytest.raises(ServiceCheckError, match="INVOCATION_MISMATCH"):
        await check_revision(intake, "owner", 1, identity, "ag-legacy")
    assert not intake.revision_tools.calls
    candidate["slack_thread"] = client.docs[0]["slack_thread"]
    intake.revision_tools.status = "failed"
    result = await check_revision(intake, "owner", 1, identity, "ag-legacy")
    assert result["revision_request"]["state"] == "FAILED"
    assert result["revision_request"]["invocation_id"] == "ag-legacy"
    assert intake.revision_tools.starts == 0


@pytest.mark.asyncio
async def test_unchanged_poll_does_not_wake_a_busy_loop_and_restart_keeps_the_receipt(revisions):
    intake, client, pages, digest = revisions
    identity = uuid4()
    await request_revision(intake, "owner", 1, digest, identity, "Clarify the year filter.")
    restarted = DocumentIntake(intake.path, client, pages)
    restarted.revision_tools = intake.revision_tools
    restarted._progress = SimpleNamespace(
        wake=SimpleNamespace(set=lambda: pytest.fail("unchanged status must not wake"))
    )
    await check_revision(restarted, "owner", 1, identity)
    assert restarted.revision_tools.starts == 1


@pytest.mark.asyncio
async def test_revision_api_denies_access_before_remote_calls(revisions, monkeypatch):
    intake, client, _, digest = revisions
    before = len(client.calls)
    monkeypatch.setattr(api, "document_intake", lambda: intake)
    monkeypatch.setattr(api, "access", AsyncMock(side_effect=ServiceCheckError("DENIED", 403)))
    with pytest.raises(HTTPException) as exc:
        await api.revise_document(
            1,
            api.ReviseDocument(digest=digest, request_id=uuid4(), feedback="Clarify the filter."),
            AsyncMock(),
            SimpleNamespace(id="owner"),
        )
    assert exc.value.status_code == 403 and len(client.calls) == before
    with pytest.raises(HTTPException) as exc:
        await api.check_document_revision(
            1, api.CheckRevision(request_id=uuid4(), invocation_id="ag-test"), AsyncMock(), SimpleNamespace(id="owner")
        )
    assert exc.value.status_code == 403 and not intake.revision_tools.calls

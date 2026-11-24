import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import HTTPException, Response
import pytest

from langflow.adlc import document_intake as mod
from langflow.adlc.document_intake import DocumentIntake, page_text, public_document, source_document
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_document_intake as api


def source(identity=1):
    return {
        "id": identity,
        "title": "Add a feature",
        "doc_type": "ptyc",
        "lifecycle_id": "lc-thread",
        "status": "pending",
        "confluence_page_id": "123",
        "confluence_link": "https://example.atlassian.net/wiki/spaces/SD/pages/123/Feature",
        "slack_channel": "C01234567",
        "slack_thread": "1793074062.301049",
        "created_at": "2026-10-28T00:00:00Z",
    }


class Client:
    def __init__(self):
        self.docs, self.calls, self.offline = [source()], [], False
        self.before_return = None

    async def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.offline:
            raise ServiceCheckError("WORKLOOP_UNAVAILABLE", 503)
        if self.before_return:
            self.before_return()
        return {"spec_docs" if "/lifecycles/" in path else "docs": copy.deepcopy(self.docs)}


class Pages:
    def __init__(self):
        self.version, self.body, self.offline = 1, "# Feature\nRequirements and acceptance criteria", False
        self.before_return = None

    async def read(self, identity):
        if self.offline:
            raise ServiceCheckError("INTAKE_CONFLUENCE_UNAVAILABLE", 503)
        if self.before_return:
            self.before_return()
        return {
            "version": self.version,
            "body": self.body,
            "digest": hashlib.sha256(json.dumps([identity, self.version, self.body]).encode()).hexdigest(),
        }


@pytest.fixture
async def intake(tmp_path):
    client, pages = Client(), Pages()
    service = DocumentIntake(tmp_path / "intake.db", client, pages)
    await service.sync("owner")
    return service, client, pages


async def approved(intake, owner="owner", identity=1):
    service, _, _ = intake
    project = {"project_id": str(uuid4()), "repository": "admin/application"}
    service.assign(owner, identity, project, "Backend and tests only")
    row = await service.refresh(owner, identity)
    await service.decide(owner, identity, service.contract_digest(row), "approve")
    return service.get(owner, identity)


def test_page_parser_preserves_long_requirements_and_never_executes_markup():
    value = page_text(
        "<h1>Feature</h1><script>hidden</script><p>Required</p><ul><li>Test</li></ul>" + "a" * 30000 + " tail"
    )
    assert "hidden" not in value and "# Feature" in value and "- Test" in value and value.endswith(" tail")
    with pytest.raises(ServiceCheckError, match="TOO_LARGE"):
        page_text("a" * 60001)
    assert "xoxb-12345-private" not in page_text("<p>token xoxb-12345-private</p>")


def test_source_allowlist_rejects_credential_urls_and_invalid_slack_links():
    raw = {
        **source(),
        "confluence_link": "https://user:secret@example.com/123",
        "slack_channel": "../../private",
        "secret": "do-not-copy",
    }
    value = source_document(raw)
    assert not value["confluence_url"] and not value["slack_channel"] and "secret" not in json.dumps(value)


@pytest.mark.asyncio
async def test_catalog_discovers_new_documents_without_approving_or_running(intake):
    service, client, _ = intake
    client.docs.append({**source(2), "status": "approved"})
    await service.sync("owner", force=True)
    assert len(service.rows("owner")) == 2 and not service.rows("another-owner")
    assert all(
        r["state"] == "NEEDS_PROJECT" and not r.get("run_id") and not r.get("approval") for r in service.rows("owner")
    )
    assert all(method == "GET" for method, _, _ in client.calls)


@pytest.mark.asyncio
async def test_failed_spec_receipts_without_a_page_are_not_reviewable_documents(intake):
    service, client, _ = intake
    incomplete = {**source(2), "confluence_page_id": "", "confluence_link": ""}
    client.docs.append(incomplete)
    await service.sync("owner", force=True)
    assert service.get("owner", 2)["page_id"] == ""
    assert [r["document_id"] for r in service.rows("owner")] == ["1"]
    # Publishing the missing page later makes the same source visible normally,
    # without inventing an approval or requiring the user to import a link.
    client.docs[-1] = source(2)
    await service.sync("owner", force=True)
    assert len(service.rows("owner")) == 2
    assert service.get("owner", 2)["state"] == "NEEDS_PROJECT"
    assert not service.get("owner", 2).get("approval")


@pytest.mark.asyncio
async def test_channel_rule_routes_future_requests_with_repository_and_is_owner_scoped(intake):
    service, client, _ = intake
    project = {"project_id": str(uuid4()), "repository": "admin/app"}
    service.assign("owner", 1, project, "", True)
    client.docs.append(source(2))
    await service.sync("owner", force=True)
    row = service.get("owner", 2)
    assert row["project_id"] == project["project_id"] and row["repository"] == "admin/app"
    assert row["state"] == "NEEDS_REVIEW" and not row.get("approval")
    await service.sync("other", force=True)
    assert not service.get("other", 2)["project_id"] and not service.rules("other")


@pytest.mark.asyncio
async def test_catalog_network_race_cannot_overwrite_a_local_decision(intake):
    service, client, _ = intake
    await approved(intake)

    def decide_while_reading():
        service.change(
            "owner", 1, lambda current: current.update(instructions="New scope", state="NEEDS_REVIEW", approval=None)
        )

    client.before_return = decide_while_reading
    await service.sync("owner", force=True)
    assert service.get("owner", 1)["instructions"] == "New scope" and service.get("owner", 1)["approval"] is None


@pytest.mark.asyncio
async def test_page_refresh_merges_latest_assignment_instead_of_restoring_old_project(intake):
    service, _, pages = intake
    project = {"project_id": str(uuid4()), "repository": "admin/new"}
    pages.before_return = lambda: service.assign("owner", 1, project, "New scope")
    row = await service.refresh("owner", 1, fresh=True)
    assert row["project_id"] == project["project_id"] and row["instructions"] == "New scope"


@pytest.mark.asyncio
async def test_approval_is_bound_to_page_version_project_and_scope(intake):
    service, _, pages = intake
    row = await approved(intake)
    digest = service.contract_digest(row)
    pages.version = 2
    with pytest.raises(ServiceCheckError, match="DOCUMENT_CHANGED"):
        await service.decide("owner", 1, digest, "approve")
    assert service.get("owner", 1)["state"] == "CHANGED" and service.get("owner", 1)["approval"] is None
    with pytest.raises(ServiceCheckError, match="APPROVAL_REQUIRED"):
        await service.reserve("owner", 1, digest, str(uuid4()), None)
    assert not service.get("owner", 1).get("run_id")


@pytest.mark.asyncio
async def test_source_rejection_and_missing_source_block_future_planning(intake):
    service, client, _ = intake
    row = await approved(intake)
    client.docs[0]["status"] = "cancelled"
    await service.validate_source("owner", 1)
    with pytest.raises(ServiceCheckError, match="APPROVAL_REQUIRED"):
        await service.reserve("owner", 1, service.contract_digest(row), str(uuid4()), None)
    client.docs = []
    with pytest.raises(ServiceCheckError, match="SOURCE_MISSING"):
        await service.validate_source("owner", 1)


@pytest.mark.asyncio
async def test_outage_keeps_documents_and_decisions_but_cannot_make_fresh_approval(intake):
    service, client, pages = intake
    row = await approved(intake)
    client.offline, pages.offline = True, True
    assert (await service.sync("owner", force=True))["stale"]
    assert service.get("owner", 1)["approval"] == row["approval"]
    with pytest.raises(ServiceCheckError, match="CONFLUENCE_UNAVAILABLE"):
        await service.decide("owner", 1, service.contract_digest(row), "approve")


@pytest.mark.asyncio
async def test_oversized_requirement_is_rejected_before_reserving_or_creating_a_flow(intake):
    service, _, pages = intake
    pages.body = "Requirements " * 6500
    row = await approved(intake)
    with pytest.raises(ServiceCheckError, match="PLAN_TOO_LARGE"):
        await service.reserve("owner", 1, service.contract_digest(row), str(uuid4()), None)
    assert not service.get("owner", 1).get("run_id")


@pytest.mark.asyncio
async def test_complete_confluence_document_over_twenty_thousand_chars_is_frozen_without_trimming(intake):
    from langflow.adlc.delivery import CreateDelivery
    from langflow.adlc.document_intake import intake_requirement

    service, _, pages = intake
    pages.body = "# Complete specification\n" + "Requirement and evidence\n" * 1000 + "FINAL ACCEPTANCE CRITERION"
    row = await approved(intake)
    expected = service.contract_digest(row)
    row = await service.reserve("owner", 1, expected, str(uuid4()), None)
    snapshot = row["execution_snapshot"]
    requirement = intake_requirement(snapshot)
    delivery = CreateDelivery(flow_id=uuid4(), title="Complete specification", requirement=requirement)
    assert snapshot["page_body"] == pages.body
    assert len(requirement) > 20000
    assert delivery.requirement == requirement
    assert requirement.endswith("FINAL ACCEPTANCE CRITERION")


@pytest.mark.asyncio
async def test_reservation_is_durable_scoped_and_frozen_without_duplicate_runs(intake):
    service, client, pages = intake
    row = await approved(intake)
    digest, command = service.contract_digest(row), str(uuid4())
    first, second = await asyncio.gather(
        service.reserve("owner", 1, digest, command, None), service.reserve("owner", 1, digest, command, None)
    )
    assert first["run_id"] == second["run_id"]
    with pytest.raises(ServiceCheckError, match="EXECUTION_APPROVAL_FIXED"):
        await service.decide("owner", 1, digest, "reject")
    restarted = DocumentIntake(service.path, client, pages)
    assert (await restarted.reserve("owner", 1, digest, command, None))["run_id"] == first["run_id"]
    with pytest.raises(ServiceCheckError, match="RUN_ALREADY_EXISTS"):
        await service.reserve("owner", 1, digest, str(uuid4()), None)
    with pytest.raises(ServiceCheckError, match="START_PENDING"):
        service.assign("owner", 1, {"project_id": row["project_id"], "repository": row["repository"]}, "Changed")
    pages.version, pages.body = 2, "Changed content"
    await service.refresh("owner", 1, fresh=True)
    current = service.get("owner", 1)
    assert current["execution_snapshot"]["page_body"] != pages.body and current["page_body"] == pages.body
    public = public_document(current, body=True)
    assert "execution_snapshot" not in public and "owner" not in public and public["plan_command"]["id"] == command


@pytest.mark.asyncio
async def test_only_new_approved_revision_can_create_a_followup_and_preserves_history(intake):
    service, _, pages = intake
    row = await approved(intake)
    first = await service.reserve("owner", 1, service.contract_digest(row), str(uuid4()), None)
    pages.version = 2
    new = await service.refresh("owner", 1, fresh=True)
    digest = service.contract_digest(new)
    await service.decide("owner", 1, digest, "approve")
    with pytest.raises(ServiceCheckError, match="RUN_ALREADY_EXISTS"):
        await service.reserve("owner", 1, digest, str(uuid4()), None)
    second = await service.reserve("owner", 1, digest, str(uuid4()), None, allow_revision=True)
    assert second["run_id"] != first["run_id"] and second["previous_runs"][0]["run_id"] == first["run_id"]


@pytest.mark.asyncio
async def test_retry_updates_the_document_link_once_and_cannot_rebind_another_revision(intake):
    service, _, _ = intake
    row = await approved(intake)
    first = await service.reserve("owner", 1, service.contract_digest(row), str(uuid4()), None)
    child = str(uuid4())
    service.follow_retry("owner", 1, first["run_id"], child)
    service.follow_retry("owner", 1, first["run_id"], child)
    current = service.get("owner", 1)
    assert current["run_id"] == child and len(current["previous_runs"]) == 1
    service.follow_retry("owner", 1, "another-run", str(uuid4()))
    assert service.get("owner", 1)["run_id"] == child
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        service.follow_retry("another-owner", 1, child, str(uuid4()))


@pytest.mark.asyncio
async def test_detail_and_mutations_authorize_before_any_remote_read(intake, monkeypatch):
    service, client, pages = intake
    await approved(intake)
    actor = SimpleNamespace(id="owner", is_superuser=True)
    monkeypatch.setattr(api, "document_intake", lambda: service)
    monkeypatch.setattr(api, "live_service", lambda: object())
    authorize = AsyncMock(side_effect=ServiceCheckError("DENIED", 403))
    monkeypatch.setattr(api, "authorize_project", authorize)
    service.refresh = AsyncMock(wraps=service.refresh)
    client.calls.clear()
    calls = [
        lambda: api.read_document(1, AsyncMock(), actor, Response()),
        lambda: api.assign_document(1, api.AssignDocument(project_id=uuid4()), AsyncMock(), actor),
        lambda: api.decide_document(1, api.DecideDocument(digest="a" * 64, decision="approve"), AsyncMock(), actor),
        lambda: api.plan_document(1, api.DocumentPlan(digest="a" * 64, command_id=uuid4()), AsyncMock(), actor),
        lambda: api.clear_reservation(1, AsyncMock(), actor),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 403
    assert not client.calls and service.refresh.await_count == 0


@pytest.mark.asyncio
async def test_nonadmin_cannot_read_unassigned_catalog_or_create_channel_rules(intake, monkeypatch):
    service, client, _ = intake
    monkeypatch.setattr(api, "document_intake", lambda: service)
    monkeypatch.setattr(api, "live_service", lambda: object())
    actor = SimpleNamespace(id="owner", is_superuser=False)
    client.calls.clear()
    result = await api.inbox(AsyncMock(), actor, Response())
    assert not result["items"] and not client.calls
    with pytest.raises(HTTPException) as exc:
        await api.read_document(1, AsyncMock(), actor, Response())
    assert exc.value.status_code == 403 and not client.calls


@pytest.mark.asyncio
async def test_handoff_uses_frozen_content_and_normal_owned_delivery_plan(intake, monkeypatch):
    from langflow.api.v1 import adlc_delivery, adlc_live

    service, _, pages = intake
    row = await approved(intake)
    row = await service.reserve("owner", 1, service.contract_digest(row), str(uuid4()), None)
    actor = SimpleNamespace(id=uuid4())
    # Use the same owner UUID as a normal authenticated actor.
    owner = str(actor.id)
    row["owner"] = owner
    service.save(row)
    created = {}

    def get(_owner, identity):
        if not created:
            raise ServiceCheckError("LIVE_RUN_NOT_FOUND", 404)
        return copy.deepcopy(created)

    def update(identity, values):
        created.update(values)
        return copy.deepcopy(created)

    store = SimpleNamespace(get=Mock(side_effect=get), update=Mock(side_effect=update), workflow=Mock())
    live = SimpleNamespace(store=store)
    session = AsyncMock()
    session.get.return_value = SimpleNamespace(user_id=actor.id, folder_id=row["project_id"])
    create = AsyncMock(return_value={"id": str(uuid4())})
    monkeypatch.setattr(adlc_delivery, "create_delivery", create)

    async def plan(command, _session, _actor):
        created.update(
            run_id=str(command.run_id),
            project_id=str(command.project_id),
            requirement=create.call_args.args[0].requirement,
            state="PLANNING",
        )

    start = AsyncMock(side_effect=plan)
    monkeypatch.setattr(adlc_live, "plan", start)
    service.change(
        owner, 1, lambda current: current.update(page_body="Unapproved edits", instructions="Unapproved scope")
    )
    result = await mod.start_document_plan(live, service, row, session, actor)
    requirement = create.call_args.args[0].requirement
    assert pages.body in requirement and "Backend and tests only" in requirement
    assert "Unapproved edits" not in requirement and "Unapproved scope" not in requirement
    assert result["origin_document"]["page_version"] == 1 and result["origin_document"]["document_id"] == "1"
    await mod.start_document_plan(live, service, row, session, actor)
    assert start.await_count == 1 and create.await_count == 1

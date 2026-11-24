import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.issue_automation import IssueService, authorize_project
from langflow.adlc.issue_store import issue_requirement
from langflow.adlc.live_workflows import LiveService, LiveStore
from langflow.adlc.vai_services import ServiceCheckError


def raw_issue(number=1, **changes):
    return {
        "number": number,
        "title": "Add search to the notes",
        "body": "Search titles without changing the saved notes.",
        "state": "open",
        "user": {"login": "maintainer"},
        "labels": [],
        **changes,
    }


class GiteaSource:
    def __init__(self):
        self.items = [raw_issue()]
        self.error = None
        self.requests = []

    async def repository(self, identity):
        if self.error:
            raise self.error
        return {"id": identity, "full_name": "admin/notes"}

    async def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if self.error:
            raise self.error
        if "?" in path:
            return copy.deepcopy([i for i in self.items if i["state"] == "open"])
        number = int(path.rsplit("/", 1)[1])
        return copy.deepcopy(next(i for i in self.items if i["number"] == number))


class Runner:
    def __init__(self, live):
        self.live = live
        self.plans = 0
        self.executions = 0

    async def start_plan(self, proposal, policy):
        self.plans += 1
        p = self.live.store.project(proposal["owner"], proposal["project_id"])
        row, _ = self.live.store.create(
            proposal["owner"],
            p,
            str(uuid4()),
            proposal["run_id"],
            proposal["issue"]["body"],
            proposal["issue"]["title"],
            "a" * 40,
        )
        return row

    async def execute(self, proposal, store):
        row = self.live.store.get(proposal["owner"], proposal["run_id"])
        row, fresh = self.live.store.begin_execution(
            proposal["owner"],
            row["run_id"],
            row["plan"]["digest"],
            guard=lambda db, value: store.guard_auto_execution(db, proposal, value),
        )
        self.executions += int(fresh)
        return row


def setup(tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    project = store.save_project(
        "alice",
        str(uuid4()),
        {"id": 41, "name": "notes", "full_name": "admin/notes", "html_url": "http://gitea/admin/notes"},
        "/source",
        "a" * 40,
    )
    live = LiveService(store)
    live.observe = lambda value: value
    source, runner = GiteaSource(), Runner(live)
    service = IssueService(live, gitea=source, runner=runner)
    return live, project, source, runner, service


def automatic(service, project, **changes):
    p = service.store.settings("alice", project["project_id"])
    return service.store.save_settings(
        "alice",
        project["project_id"],
        expected_revision=p["revision"],
        watch_issues=True,
        mode="auto",
        labels=changes.get("labels", []),
        workflow_id=None,
        auto_confirmed=True,
    )


def ready(live, identity):
    return live.store.update(
        identity,
        {
            "state": "PLAN_READY",
            "plan": {
                "digest": "b" * 64,
                "tasks": [{"write_paths": ["app.js", "tests/test_search.py"]}],
                "commands": [{"argv": ["python", "-m", "unittest"]}],
            },
            "documents": [{"id": "SPEC"}],
        },
    )


def risk_policy(service, project, **changes):
    saved = service.store.settings("alice", project["project_id"])
    return service.store.save_settings(
        "alice",
        project["project_id"],
        expected_revision=saved["revision"],
        watch_issues=True,
        mode="risk",
        labels=[],
        workflow_id=None,
        auto_confirmed=True,
        auto_allowed_paths=changes.get("paths", ["app.js", "tests/**"]),
        auto_max_runs_per_day=changes.get("max_runs", 3),
        auto_max_active_minutes=changes.get("max_minutes", 20),
    )


def answers():
    return {
        "goal": "Show a counter for each click",
        "scope": "Only app.js and the related tests",
        "acceptance": "Three clicks must show three and resetting must show zero",
    }


@pytest.mark.asyncio
async def test_unclear_issue_notifies_then_uses_the_human_answers(tmp_path):
    _, p, source, runner, service = setup(tmp_path)
    source.items[0]["body"] = "TBD"
    risk_policy(service, p)
    row = (await service.scan(p))["items"][0]
    assert row["state"] == "NEEDS_CONTEXT"
    assert service.attention("alice")[0]["title"] == "Issue Gitea cần bạn bổ sung thông tin"
    await service.advance(p)
    assert runner.plans == 0
    with pytest.raises(ServiceCheckError, match="CLARIFICATION_REQUIRED"):
        await service.prepare("alice", p["project_id"], row["proposal_id"], row["source_digest"])
    clarified = await service.clarify(
        "alice", p["project_id"], row["proposal_id"], row["source_digest"], answers(), "spec_first"
    )
    assert clarified["triage"]["action"] == "ready" and clarified["state"] == "DETECTED"
    _, requirement = issue_requirement(p, clarified["issue"], clarified["clarification"])
    assert all(value in requirement for value in answers().values())
    assert "đặc tả" in requirement
    await service.advance(p)
    assert runner.plans == 1


@pytest.mark.asyncio
async def test_answers_are_not_reused_after_the_issue_changes(tmp_path):
    _, p, source, _, service = setup(tmp_path)
    source.items[0]["body"] = "TBD"
    row = (await service.scan(p))["items"][0]
    await service.clarify("alice", p["project_id"], row["proposal_id"], row["source_digest"], answers(), "implement")
    source.items[0]["body"] = "Please discuss a different unspecified goal"
    changed = (await service.scan(p))["items"][0]
    assert changed["state"] == "NEEDS_CONTEXT" and not changed.get("clarification")
    with pytest.raises(ServiceCheckError, match="ISSUE_CHANGED"):
        await service.clarify(
            "alice", p["project_id"], row["proposal_id"], row["source_digest"], answers(), "implement"
        )
    assert any(
        event["event"] == "clarified" for event in service.store.audit("alice", p["project_id"], row["proposal_id"])
    )


@pytest.mark.asyncio
async def test_risk_mode_approves_only_the_exact_allowed_plan_and_records_the_decision(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    policy = risk_policy(service, p)
    row = (await service.scan(p))["items"][0]
    await service.advance(p)
    current = service.store.get("alice", p["project_id"], row["proposal_id"])
    ready(live, current["run_id"])
    await service.advance(p)
    assert runner.executions == 1
    approved = live.store.get("alice", current["run_id"])
    assert approved["automation"]["risk"]["tier"] == "R1"
    assert approved["automation"]["settings_revision"] == policy["revision"]
    assert approved["auto_timing"]["limit_seconds"] == 1200
    await service.advance(p)
    events = service.store.audit("alice", p["project_id"], row["proposal_id"])
    assert sum(event["event"] == "auto_approved" for event in events) == 1
    assert service.store.usage("alice", p["project_id"])["used"] == 1


@pytest.mark.asyncio
async def test_outside_scope_and_sensitive_plans_wait_for_review(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    risk_policy(service, p, paths=["docs/**", "tests/**"])
    await service.scan(p)
    await service.advance(p)
    row = service.store.proposals("alice")[0]
    ready(live, row["run_id"])
    await service.advance(p)
    assert runner.executions == 0
    assert (
        service.store.get("alice", p["project_id"], row["proposal_id"])["review_reason"] == "ISSUE_PATH_REVIEW_REQUIRED"
    )
    assert live.store.get("alice", row["run_id"])["state"] == "PLAN_READY"


@pytest.mark.asyncio
async def test_atomic_approval_rechecks_risk_even_if_the_stored_assessment_was_safe(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    risk_policy(service, p, paths=["app.js", "src/**", "tests/**"])
    await service.scan(p)
    await service.advance(p)
    row = service.store.proposals("alice")[0]
    run = ready(live, row["run_id"])
    service.store.assess("alice", p["project_id"], row["proposal_id"], run["plan"])
    run["plan"]["tasks"][0]["write_paths"] = ["src/auth/permissions.py"]
    live.store.update(run["run_id"], {"plan": run["plan"]})
    with pytest.raises(ServiceCheckError, match="RISK_REVIEW_REQUIRED"):
        await runner.execute(row, service.store)
    assert live.store.get("alice", row["run_id"])["phase"] == "planning"
    assert not any(
        event["event"] == "auto_approved" for event in service.store.audit("alice", p["project_id"], row["proposal_id"])
    )


@pytest.mark.asyncio
async def test_sensitive_issue_does_not_spend_a_planning_slot(tmp_path):
    _, p, source, runner, service = setup(tmp_path)
    source.items[0]["body"] = "The app must change permissions for the payment operator."
    risk_policy(service, p)
    row = (await service.scan(p))["items"][0]
    assert row["risk"]["tier"] == "R3"
    await service.advance(p)
    assert runner.plans == 0 and service.store.usage("alice", p["project_id"])["used"] == 0


@pytest.mark.asyncio
async def test_manual_planning_never_inherits_automatic_approval(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    risk_policy(service, p)
    row = (await service.scan(p))["items"][0]
    planned = await service.prepare("alice", p["project_id"], row["proposal_id"], row["source_digest"])
    ready(live, planned["run_id"])
    await service.advance(p)
    assert runner.executions == 0
    assert service.store.usage("alice", p["project_id"])["used"] == 0
    assert (
        service.store.get("alice", p["project_id"], row["proposal_id"])["review_reason"] == "ISSUE_MANUAL_PLAN_REVIEW"
    )


@pytest.mark.asyncio
async def test_automatic_budget_survives_restart_and_recovers_after_the_rolling_window(tmp_path, monkeypatch):
    live, p, source, runner, service = setup(tmp_path)
    risk_policy(service, p, max_runs=1)
    source.items = [raw_issue(1), raw_issue(2)]
    await service.scan(p)
    await service.advance(p)
    running = next(row for row in service.store.proposals("alice") if row.get("run_id"))
    live.store.update(running["run_id"], {"state": "SUCCEEDED"})
    restarted = IssueService(live, gitea=source, runner=runner)
    await restarted.advance(p)
    second = next(row for row in restarted.store.proposals("alice") if row["issue"]["number"] == 2)
    assert second["run_id"] is None and second["review_reason"] == "ISSUE_AUTO_BUDGET_EXHAUSTED"
    assert runner.plans == 1
    import time

    later = time.time() + 86401
    monkeypatch.setattr("langflow.adlc.issue_store.time.time", lambda: later)
    await restarted.advance(p)
    assert runner.plans == 2


@pytest.mark.asyncio
async def test_audit_is_owner_scoped_and_does_not_grow_on_unchanged_polls(tmp_path):
    _, p, _, _, service = setup(tmp_path)
    row = (await service.scan(p))["items"][0]
    before = len(service.store.audit("alice", p["project_id"], row["proposal_id"]))
    await service.scan(p)
    service.list("alice", p["project_id"])
    assert len(service.store.audit("alice", p["project_id"], row["proposal_id"])) == before
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        service.store.audit("bob", p["project_id"], row["proposal_id"])


@pytest.mark.asyncio
async def test_detects_once_and_default_mode_never_starts_agents(tmp_path):
    _, project, source, runner, service = setup(tmp_path)
    first = await service.scan(project)
    second = await service.scan(project)
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["proposal_id"] == second["items"][0]["proposal_id"]
    assert first["settings"]["mode"] == "review"
    await service.advance(project)
    assert runner.plans == runner.executions == 0
    assert all(method == "GET" for method, _, _ in source.requests)
    assert "owner" not in first["items"][0] and "lease_owner" not in first["items"][0]


def test_auto_requires_explicit_confirmation_and_settings_have_revision_guard(tmp_path):
    _, p, _, _, service = setup(tmp_path)
    args = {
        "owner": "alice",
        "project": p["project_id"],
        "expected_revision": 1,
        "watch_issues": True,
        "mode": "auto",
        "labels": [],
        "workflow_id": None,
    }
    with pytest.raises(ServiceCheckError, match="CONFIRMATION_REQUIRED"):
        service.store.save_settings(**args)
    policy = service.store.save_settings(**args, auto_confirmed=True)
    assert policy["revision"] == 2
    with pytest.raises(ServiceCheckError, match="SETTINGS_CHANGED"):
        service.store.save_settings(**args, auto_confirmed=True)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        service.store.settings("bob", p["project_id"])


@pytest.mark.asyncio
async def test_auto_plans_and_executes_once_through_the_existing_pipeline(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    automatic(service, p)
    await service.scan(p)
    await service.advance(p)
    proposal = service.store.proposals("alice")[0]
    assert runner.plans == 1
    ready(live, proposal["run_id"])
    await service.advance(p)
    await service.advance(p)
    assert runner.executions == 1 and runner.plans == 1
    assert live.store.get("alice", proposal["run_id"])["approved_plan_digest"] == "b" * 64


@pytest.mark.asyncio
async def test_disabling_auto_between_planning_and_execution_preserves_human_review(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    policy = automatic(service, p)
    await service.scan(p)
    await service.advance(p)
    proposal = service.store.proposals("alice")[0]
    ready(live, proposal["run_id"])
    service.store.save_settings(
        "alice",
        p["project_id"],
        expected_revision=policy["revision"],
        watch_issues=True,
        mode="review",
        labels=[],
        workflow_id=None,
    )
    await service.advance(p)
    assert runner.executions == 0
    assert live.store.get("alice", proposal["run_id"])["state"] == "PLAN_READY"


def test_policy_revocation_is_checked_inside_the_exact_plan_approval_transaction(tmp_path):
    live, p, source, _, service = setup(tmp_path)
    policy = automatic(service, p)
    proposal = service.store.ingest("alice", p, source.items[0], policy)
    proposal, _ = service.store.claim(
        "alice", p["project_id"], proposal["proposal_id"], proposal["source_digest"], "instance", policy
    )
    row, _ = live.store.create("alice", p, "delivery", proposal["run_id"], "Requirement", "Title", "a" * 40)
    ready(live, row["run_id"])
    service.store.save_settings(
        "alice",
        p["project_id"],
        expected_revision=policy["revision"],
        watch_issues=False,
        mode="review",
        labels=[],
        workflow_id=None,
    )
    with pytest.raises(ServiceCheckError, match="POLICY_CHANGED"):
        live.store.begin_execution(
            "alice",
            row["run_id"],
            "b" * 64,
            guard=lambda db, value: service.store.guard_auto_execution(db, proposal, value),
        )
    assert live.store.get("alice", row["run_id"])["phase"] == "planning"


@pytest.mark.asyncio
async def test_issue_edited_before_execution_does_not_approve_the_old_snapshot(tmp_path):
    live, p, source, runner, service = setup(tmp_path)
    automatic(service, p)
    await service.scan(p)
    await service.advance(p)
    old = service.store.proposals("alice")[0]
    ready(live, old["run_id"])
    source.items[0]["body"] = "A different requirement with additional constraints."
    await service.advance(p)
    assert runner.executions == 0
    current = service.store.proposals("alice")[0]
    assert current["source_digest"] != old["source_digest"]
    assert current["previous_runs"][0]["run_id"] == old["run_id"]
    assert live.store.get("alice", old["run_id"])["state"] == "PLAN_READY"


@pytest.mark.asyncio
async def test_closed_issue_blocks_automatic_execution(tmp_path):
    live, p, source, runner, service = setup(tmp_path)
    automatic(service, p)
    await service.scan(p)
    await service.advance(p)
    old = service.store.proposals("alice")[0]
    ready(live, old["run_id"])
    source.items[0]["state"] = "closed"
    await service.advance(p)
    assert runner.executions == 0
    assert service.store.proposals("alice")[0]["state"] == "CLOSED"


@pytest.mark.asyncio
async def test_pull_requests_are_excluded_and_label_filter_is_explicit(tmp_path):
    _, p, source, runner, service = setup(tmp_path)
    automatic(service, p, labels=["ready"])
    source.items = [raw_issue(1), raw_issue(2, pull_request={"url": "pr"}), raw_issue(3, labels=[{"name": "Ready"}])]
    result = await service.scan(p)
    assert {x["issue"]["number"] for x in result["items"]} == {1, 3}
    await service.advance(p)
    assert runner.plans == 1
    selected = next(x for x in service.store.proposals("alice") if x.get("run_id"))
    assert selected["issue"]["number"] == 3


@pytest.mark.asyncio
async def test_one_run_per_project_prevents_overlapping_issues_and_manual_runs(tmp_path):
    live, p, source, runner, service = setup(tmp_path)
    automatic(service, p)
    source.items = [raw_issue(1), raw_issue(2)]
    await service.scan(p)
    await service.advance(p)
    await service.advance(p)
    assert runner.plans == 1
    first = next(x for x in service.store.proposals("alice") if x.get("run_id"))
    live.store.update(first["run_id"], {"state": "SUCCEEDED"})
    await service.advance(p)
    assert runner.plans == 2


@pytest.mark.asyncio
async def test_failed_automatic_run_is_not_retried_forever(tmp_path):
    live, p, _, runner, service = setup(tmp_path)
    automatic(service, p)
    await service.scan(p)
    await service.advance(p)
    row = service.store.proposals("alice")[0]
    live.store.update(row["run_id"], {"state": "FAILED"})
    for _ in range(3):
        await service.scan(p)
        await service.advance(p)
    assert runner.plans == 1


@pytest.mark.asyncio
async def test_ignored_issue_does_not_reappear_on_every_poll(tmp_path):
    _, p, _, _, service = setup(tmp_path)
    first = (await service.scan(p))["items"][0]
    service.store.ignore("alice", p["project_id"], first["proposal_id"], first["source_digest"])
    second = (await service.scan(p))["items"][0]
    assert second["state"] == "IGNORED"
    assert service.attention("alice") == []
    service.store.ignore("alice", p["project_id"], first["proposal_id"], first["source_digest"], restore=True)
    assert len(service.attention("alice")) == 1


@pytest.mark.asyncio
async def test_scan_failure_keeps_existing_proposals_and_reports_connection_state(tmp_path):
    _, p, source, _, service = setup(tmp_path)
    await service.scan(p)
    source.error = ServiceCheckError("GITEA_UNAVAILABLE", 503)
    with pytest.raises(ServiceCheckError):
        await service.scan(p)
    result = service.list("alice", p["project_id"])
    assert result["items"][0]["state"] == "DETECTED"
    assert result["settings"]["scan_error"] == "GITEA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_old_source_digest_and_other_owner_cannot_start_a_proposal(tmp_path):
    _, p, _, runner, service = setup(tmp_path)
    proposal = (await service.scan(p))["items"][0]
    with pytest.raises(ServiceCheckError, match="ISSUE_CHANGED"):
        await service.prepare("alice", p["project_id"], proposal["proposal_id"], "f" * 64)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        await service.prepare("bob", p["project_id"], proposal["proposal_id"], proposal["source_digest"])
    assert runner.plans == 0


def test_large_issue_is_not_silently_truncated_and_auto_executed(tmp_path):
    _, p, _, _, _ = setup(tmp_path)
    with pytest.raises(ServiceCheckError, match="MANUAL_SUMMARY"):
        issue_requirement(p, {"number": 1, "title": "Large issue", "body": "a" * 20000, "url": "http://gitea/issue/1"})


@pytest.mark.asyncio
async def test_metadata_authorization_checks_the_actual_project_owner(tmp_path):
    live, p, _, _, _ = setup(tmp_path)
    actor = SimpleNamespace(id=uuid4(), is_active=True)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        await authorize_project(live, AsyncMock(), actor, p["project_id"], write=True)


def test_turning_off_monitoring_does_not_require_auto_confirmation(tmp_path):
    _, project, _, _, service = setup(tmp_path)
    policy = automatic(service, project)
    saved = service.store.save_settings(
        "alice",
        project["project_id"],
        expected_revision=policy["revision"],
        watch_issues=False,
        mode="auto",
        labels=[],
        workflow_id=None,
    )
    assert saved["watch_issues"] is False


@pytest.mark.asyncio
async def test_settings_api_requires_execution_permission_before_delegation(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from langflow.api.v1 import adlc_issues
    from langflow import services
    from uuid import UUID

    live, project, _, _, service = setup(tmp_path)
    live._issue_service = service
    monkeypatch.setattr(adlc_issues, "live_service", lambda: live)
    authorize = AsyncMock(return_value=project)
    monkeypatch.setattr(adlc_issues, "authorize_project", authorize)
    permission = AsyncMock(side_effect=HTTPException(403, "execution denied"))
    monkeypatch.setattr(services.authorization, "ensure_flow_permission", permission)
    command = adlc_issues.IssueSettingsCommand(expected_revision=1, watch_issues=True, mode="auto", auto_confirmed=True)
    with pytest.raises(HTTPException) as exc:
        await adlc_issues.set_issue_settings(
            UUID(project["project_id"]), command, AsyncMock(), SimpleNamespace(id="alice")
        )
    assert exc.value.status_code == 403
    assert authorize.call_args.kwargs == {"write": True}
    assert service.store.settings("alice", project["project_id"])["mode"] == "review"


@pytest.mark.asyncio
async def test_ignore_cannot_cancel_a_claimed_proposal_and_hides_private_metadata(tmp_path, monkeypatch):
    from langflow.api.v1 import adlc_issues
    from uuid import UUID

    live, project, _, _, service = setup(tmp_path)
    live._issue_service = service
    proposal = (await service.scan(project))["items"][0]
    monkeypatch.setattr(adlc_issues, "live_service", lambda: live)
    monkeypatch.setattr(adlc_issues, "authorize_project", AsyncMock(return_value=project))
    command = adlc_issues.ProposalCommand(source_digest=proposal["source_digest"])
    value = await adlc_issues.ignore_issue(
        UUID(project["project_id"]), UUID(proposal["proposal_id"]), command, AsyncMock(), SimpleNamespace(id="alice")
    )
    assert value["state"] == "IGNORED" and "owner" not in value and "lease_until" not in value
    service.store.ignore(
        "alice", project["project_id"], proposal["proposal_id"], proposal["source_digest"], restore=True
    )
    service.store.claim(
        "alice",
        project["project_id"],
        proposal["proposal_id"],
        proposal["source_digest"],
        "instance",
        service.store.settings("alice", project["project_id"]),
    )
    with pytest.raises(ServiceCheckError, match="ISSUE_PROPOSAL_NOT_READY"):
        service.store.ignore("alice", project["project_id"], proposal["proposal_id"], proposal["source_digest"])


@pytest.mark.asyncio
async def test_automatic_execution_cannot_overlap_an_existing_manual_run(tmp_path):
    live, project, _, runner, service = setup(tmp_path)
    automatic(service, project)
    await service.scan(project)
    await service.advance(project)
    proposal = service.store.proposals("alice")[0]
    ready(live, proposal["run_id"])
    live.store.create("alice", project, str(uuid4()), str(uuid4()), "Other task", "Manual", "a" * 40)
    with pytest.raises(ServiceCheckError, match="LIVE_PROJECT_RUN_ACTIVE"):
        await runner.execute(proposal, service.store)
    assert live.store.get("alice", proposal["run_id"])["state"] == "PLAN_READY"


@pytest.mark.asyncio
async def test_preparation_error_waits_for_an_explicit_retry(tmp_path):
    _, project, _, runner, service = setup(tmp_path)
    automatic(service, project)
    proposal = (await service.scan(project))["items"][0]
    original = runner.start_plan
    runner.start_plan = AsyncMock(side_effect=ServiceCheckError("GITEA_UNAVAILABLE", 503))
    await service.advance(project)
    assert service.store.get("alice", project["project_id"], proposal["proposal_id"])["state"] == "ERROR"
    await service.advance(project)
    assert runner.start_plan.await_count == 1
    runner.start_plan = original
    result = await service.prepare("alice", project["project_id"], proposal["proposal_id"], proposal["source_digest"])
    assert result["run_id"] and result["state"] == "PLANNING"


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic_run", [False, True])
async def test_real_runner_creates_a_bound_delivery_and_reuses_normal_planning(tmp_path, monkeypatch, automatic_run):
    from contextlib import asynccontextmanager
    from uuid import UUID
    from langflow.adlc.issue_automation import IssueRunner
    from langflow.api.v1 import adlc_live, adlc_delivery, authz_route_dependencies, flows_helpers
    from langflow.services import deps

    live, _, _, _, service = setup(tmp_path)
    owner = str(uuid4())
    project = live.store.save_project(
        owner,
        str(uuid4()),
        {"id": 42, "name": "notes", "full_name": "admin/notes", "html_url": "http://gitea/admin/notes"},
        "/source",
        "a" * 40,
    )
    policy = service.store.settings(owner, project["project_id"])
    if automatic_run:
        policy = service.store.save_settings(
            owner,
            project["project_id"],
            expected_revision=policy["revision"],
            watch_issues=True,
            mode="auto",
            labels=[],
            workflow_id=None,
            auto_confirmed=True,
        )
    proposal = service.store.ingest(owner, project, raw_issue(), policy)
    proposal, _ = service.store.claim(
        owner,
        project["project_id"],
        proposal["proposal_id"],
        proposal["source_digest"],
        "test",
        policy,
        automatic=automatic_run,
    )
    actor = SimpleNamespace(id=UUID(owner), is_active=True)
    session = SimpleNamespace(get=AsyncMock(return_value=None))

    @asynccontextmanager
    async def scope():
        yield session

    runner = IssueRunner(live)
    runner.actor = AsyncMock(return_value=actor)
    monkeypatch.setattr(deps, "session_scope", scope)
    monkeypatch.setattr(deps, "get_storage_service", lambda: object())
    monkeypatch.setattr("langflow.adlc.issue_automation.authorize_project", AsyncMock(return_value=project))
    monkeypatch.setattr(
        authz_route_dependencies,
        "require_flow_create_permission",
        AsyncMock(return_value=(None, UUID(project["project_id"]))),
    )

    async def create_flow(**kwargs):
        session.get.return_value = SimpleNamespace(user_id=actor.id, folder_id=UUID(project["project_id"]))
        assert kwargs["flow"].folder_id == UUID(project["project_id"])
        assert kwargs["validate_folder"] and kwargs["widen_for_authz"]

    monkeypatch.setattr(flows_helpers, "_new_flow", create_flow)
    delivery_id = str(uuid4())
    delivery = AsyncMock(return_value={"id": delivery_id})
    monkeypatch.setattr(adlc_delivery, "create_delivery", delivery)

    async def plan(command, current_session, current_actor):
        assert current_session is session and current_actor is actor
        assert str(command.project_id) == project["project_id"]
        assert str(command.delivery_id) == delivery_id
        live.store.create(owner, project, delivery_id, str(command.run_id), "from delivery", "Issue", "a" * 40)

    monkeypatch.setattr(adlc_live, "plan", plan)
    run = await runner.start_plan(proposal, policy)
    command = delivery.call_args.args[0]
    assert proposal["issue"]["url"] in command.requirement
    assert proposal["issue"]["body"] in command.requirement
    assert run["issue"]["source_digest"] == proposal["source_digest"]
    assert run["issue"]["proposal_id"] == proposal["proposal_id"]
    assert (run.get("auto_timing") or {}).get("limit_seconds") == (1200 if automatic_run else None)
    if automatic_run:
        assert "20 phút" in command.requirement


@pytest.mark.asyncio
async def test_exhausted_active_time_never_spawns_more_work_and_preserves_the_stop_receipt(tmp_path, monkeypatch):
    from langflow.adlc import live_workflows

    live, p, _, _, service = setup(tmp_path)
    live._issue_service = service
    proposal = (await service.scan(p))["items"][0]
    row, _ = live.store.create("alice", p, "delivery", str(uuid4()), "Counter", "Counter", "a" * 40)
    row = live.store.update(
        row["run_id"],
        {
            "auto_timing": {"limit_seconds": 300, "active_seconds": 300},
            "issue": {"proposal_id": proposal["proposal_id"]},
            "nodes": [{"session_id": "owned-session", "state": "RUNNING"}],
        },
    )
    cancel = AsyncMock(return_value=True)
    live.cancel_auto_sessions = cancel
    spawn = AsyncMock()
    monkeypatch.setattr(live_workflows.asyncio, "create_subprocess_exec", spawn)
    await live.execute(row)
    spawn.assert_not_called()
    cancel.assert_awaited_once()
    final = live.store.get("alice", row["run_id"])
    assert final["state"] == "FAILED" and final["error_code"] == "LIVE_AUTO_TIME_LIMIT"
    assert LiveService.observe(live, final) == final
    assert any(
        event["event"] == "auto_time_limit"
        for event in service.store.audit("alice", p["project_id"], proposal["proposal_id"])
    )


@pytest.mark.asyncio
async def test_timeout_cancels_only_this_runs_bound_unfinished_sessions(tmp_path, monkeypatch):
    from langflow.adlc import live_workflows
    import dsh_web_sdk

    live, _, _, _, _ = setup(tmp_path)
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def session(self, identity):
            calls.append(identity)
            return SimpleNamespace(cancel=AsyncMock(return_value=True))

    monkeypatch.setattr(dsh_web_sdk, "DshClient", lambda *args, **kwargs: Client())
    monkeypatch.setattr(live_workflows, "settings", lambda: ("http://harness", "private-test-token"))
    assert await live.cancel_auto_sessions(
        {"nodes": [{"session_id": "ours", "state": "RUNNING"}, {"session_id": "completed", "state": "DONE"}]}
    )
    assert calls == ["ours"]

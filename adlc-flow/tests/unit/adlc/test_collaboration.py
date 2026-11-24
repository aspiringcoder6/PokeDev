"""H7B real SQL, actual compiler, four human roles; no paid/runtime side effects."""

# ruff: noqa: S101, PLR2004, INP001 - assertions in the existing namespace test suite.

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlmodel import SQLModel, select

from langflow.adlc import collaboration as c
from langflow.adlc.collaboration_models import (
    DecisionCommand,
    HumanCommand,
    ImportRunCommand,
    ResourceCommand,
    SuiteCommand,
    SuiteUpdate,
    ToolCommand,
    WorkflowCommand,
)
from langflow.adlc.models import WorkflowRun, WorkflowRunStatus
from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunService
from langflow.api.v1 import adlc_collaboration as api
from langflow.api.v1.adlc_team_access import explicit_team_user
from langflow.services.authorization import team_access as access
from langflow.services.authorization.team_catalog import TeamRole
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_workflow_run import AdlcWorkflowRun
from langflow.services.database.models.auth.collaboration import (
    AdlcProjectCommand,
    AdlcProjectDecision,
    AdlcProjectResource,
    AdlcProjectRevision,
)
from langflow.services.database.models.flow.model import Flow
from lfx.services.deps import injectable_session_scope
from tests.unit.services.authorization.test_team_access import db, grant  # noqa: F401 - shared isolated SQLite fixture.


@pytest_asyncio.fixture
async def team(db):  # noqa: F811 - pytest resolves the imported isolated database fixture.
    engine = db.sessions.kw["bind"]
    tables = [
        AdlcProjectResource.__table__,
        AdlcProjectRevision.__table__,
        AdlcProjectDecision.__table__,
        AdlcProjectCommand.__table__,
        AdlcExecutionPlan.__table__,
        AdlcWorkflowRun.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(conn, tables=tables))
    for revision, (name, roles) in enumerate(
        [
            ("ba", [TeamRole.BUSINESS_ANALYST]),
            ("developer", [TeamRole.DEVELOPER]),
            ("tester", [TeamRole.TESTER]),
            ("other", [TeamRole.BUSINESS_ANALYST, TeamRole.DEVELOPER]),
        ],
        1,
    ):
        await grant(db, name, roles, revision)
    async with db.sessions() as session:
        await c.enable(session, db.project, db.people["operator"], HumanCommand(policy_revision=5))
        await access.commit(session)
    return db


def exact(item, **changes):
    return {
        "policy_revision": item["policy_revision"],
        "expected_revision": item["revision"],
        "content_digest": item["content_digest"],
        **changes,
    }


async def contract(team, *, approved=True):
    async with team.sessions() as session:
        item = await c.contract_tool(
            session,
            team.project,
            team.people["ba"],
            ToolCommand(
                policy_revision=6,
                tool="skilltree_init",
                arguments={
                    "idempotency_key": str(uuid4()),
                    "title": "Pagination contract",
                    "scope": {"objective": "Validate pagination input."},
                },
            ),
        )
        await access.commit(session)
    async with team.sessions() as session:
        item = await c.contract_tool(
            session,
            team.project,
            team.people["ba"],
            ToolCommand(
                policy_revision=6,
                tool="skilltree_upsert_node",
                arguments={
                    "idempotency_key": str(uuid4()),
                    "contract_id": item["id"],
                    "expected_revision": 1,
                    "node": {
                        "title": "Reject invalid pages",
                        "acceptance_criteria": [
                            {"description": "Invalid pages are rejected.", "verification": "HUMAN"}
                        ],
                    },
                },
            ),
        )
        await access.commit(session)
    if approved:
        async with team.sessions() as session:
            await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
            await c.decide_resource(
                session,
                team.project,
                item["id"],
                team.people["other"],
                DecisionCommand(**exact(item), decision="APPROVE", comment="Business scope accepted."),
            )
            await access.commit(session)
            item = await c.view(session, team.project, item["id"], team.people["developer"])
    return item


def workflow_command(item, version="0.1.0"):
    return WorkflowCommand(
        policy_revision=6,
        name="Pagination implementation",
        contract_id=item["id"],
        contract_revision=item["revision"],
        contract_digest=item["content_digest"],
        stages=[
            {
                "stage_id": str(uuid4()),
                "stage_type": "IMPLEMENTATION",
                "name": "Implement",
                "objective": "Meet the contract",
                "inputs": {"requirement": "Validate pagination input."},
                "expected_outputs": ["source_patch"],
                "package_ref": {"package_id": "coding-agent", "version": version},
                "configuration_overrides": {},
                "execution_profile_overrides": {},
                "policy_overrides": {},
                "secret_refs": {},
                "position": {"x": 0, "y": 0},
                "metadata": {},
            }
        ],
    )


def compiler():
    return BlueprintCompiler(
        create_default_package_resolver(create_default_package_registry(), create_default_package_access_policy())
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["0.1.0", "0.3.0"])
async def test_ba_developer_tester_share_same_plan_and_canonical_prepared_run(team, version, monkeypatch):
    if version == "0.3.0":
        # Compiler visibility only; the H7B run cannot dispatch even with this flag.
        monkeypatch.setenv("ADLC_TASK_LOOP_HARNESS_ENABLED", "true")
    agreed = await contract(team)
    async with team.sessions() as session:
        workflow = await c.write_workflow(
            session, team.project, team.people["developer"], workflow_command(agreed, version)
        )
        result = await c.compile_plan(
            session,
            team.project,
            workflow["id"],
            team.people["developer"],
            ResourceCommand(**exact(workflow)),
            compiler(),
        )
        assert result["valid"], result.get("plan", {}).get("validation_errors")
        planned = result["resource"]
        await c.decide_resource(
            session,
            team.project,
            planned["id"],
            team.people["other"],
            DecisionCommand(**exact(planned), decision="APPROVE", comment="Technical plan accepted independently."),
        )
        prepared = await c.prepare_run(
            session, team.project, planned["id"], team.people["developer"], ResourceCommand(**exact(planned))
        )
        await access.commit(session)
    async with team.sessions() as session:
        for name in ("ba", "developer", "tester"):
            viewed = await c.view(session, team.project, prepared["id"], team.people[name])
            assert viewed["payload"]["status"] == "CREATED"
            assert viewed["payload"]["project_id"] == str(team.project)
        stored = await session.get(AdlcWorkflowRun, UUID(prepared["id"]))
        assert stored.owner_id == str(team.people["developer"].id)
        assert stored.run_payload["initiated_by"] == stored.owner_id
        assert stored.run_payload == prepared["payload"]
        decisions = (await session.exec(select(AdlcProjectDecision))).all()
        assert {d.decided_by for d in decisions} == {team.people["other"].id}


@pytest.mark.asyncio
async def test_creator_and_superuser_are_not_reviewers_by_identity(team):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        for name, code in (("ba", "TEAM_INDEPENDENT_REVIEWER_REQUIRED"), ("operator", "TEAM_PERMISSION_DENIED")):
            with pytest.raises(access.TeamAccessError, match=code):
                await c.decide_resource(
                    session,
                    team.project,
                    item["id"],
                    team.people[name],
                    DecisionCommand(**exact(item), decision="APPROVE", comment="Cannot self approve."),
                )


@pytest.mark.asyncio
async def test_cross_project_read_and_direct_write_denied(team):
    item = await contract(team)
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError):
            await c.view(session, team.other_project, item["id"], team.people["other"])
        with pytest.raises(access.TeamAccessError, match="TEAM_PERMISSION_DENIED"):
            await c.write_workflow(session, team.project, team.people["ba"], workflow_command(item))


@pytest.mark.asyncio
async def test_no_implicit_enablement_and_h7c_stays_closed(team):
    request = {
        "user_id": team.people["developer"].id,
        "obj": "flow:*",
        "act": "execute",
        "domain": f"project:{team.project}",
        "context": {"auth_method": "jwt"},
    }
    result = await team.provider.enforce_team(**request)
    assert not result.allowed
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError):
            await c.policy(session, team.other_project, team.people["other"], "requirement:write")
        own = await access.effective(
            session, await access.load_policy(session, team.project), team.people["developer"].id
        )
        assert own["permissions"]["flow:write"]["allowed"]
        assert not own["permissions"]["flow:execute"]["allowed"]


@pytest.mark.asyncio
async def test_locked_revision_is_immutable_and_change_request_does_not_edit_it(team):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        await c.decide_resource(
            session,
            team.project,
            item["id"],
            team.people["other"],
            DecisionCommand(**exact(item), decision="REQUEST_CHANGES", comment="Add edge cases before acceptance."),
        )
        await access.commit(session)
    async with team.sessions() as session:
        revised = await c.revise(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        await access.commit(session)
        assert revised["revision"] == 3
        previous = await c.view(session, team.project, item["id"], team.people["tester"], revision=2)
        assert previous["payload"] == item["payload"]
        assert not previous["can_decide"]


@pytest.mark.asyncio
async def test_revocation_and_policy_change_invalidate_old_approvals(team):
    item = await contract(team)
    async with team.sessions() as session:
        await access.remove_member(
            session,
            team.project,
            team.people["operator"],
            team.people["other"].id,
            access.RevisionCommand(expected_revision=6),
        )
        await access.commit(session)
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError, match="TEAM_CURRENT_APPROVAL_REQUIRED"):
            await c.write_workflow(
                session,
                team.project,
                team.people["developer"],
                workflow_command(item).model_copy(update={"policy_revision": 7}),
            )
        with pytest.raises(access.TeamAccessError):
            await c.view(session, team.project, item["id"], team.people["other"])


@pytest.mark.asyncio
async def test_duplicate_or_stale_approval_never_overwrites_first_decision(team):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        command = DecisionCommand(**exact(item), decision="APPROVE", comment="Approved once.")
        await c.decide_resource(session, team.project, item["id"], team.people["other"], command)
        with pytest.raises(access.TeamAccessError, match="TEAM_DECISION_ALREADY_RESOLVED"):
            await c.decide_resource(session, team.project, item["id"], team.people["other"], command)
        await access.commit(session)
        records = (await session.exec(select(AdlcProjectDecision))).all()
        assert len(records) == 1


@pytest.mark.asyncio
async def test_tool_replay_does_not_create_second_document(team):
    command = ToolCommand(
        policy_revision=6,
        tool="skilltree_init",
        arguments={
            "idempotency_key": "same-command",
            "title": "Requirement",
            "scope": {"objective": "Define a scoped task."},
        },
    )
    async with team.sessions() as session:
        first = await c.contract_tool(session, team.project, team.people["ba"], command)
        again = await c.contract_tool(session, team.project, team.people["ba"], command)
        await access.commit(session)
        assert first["id"] == again["id"]


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_resource_and_decision(team, monkeypatch):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        await access.commit(session)

    def broken(*_args, **_kwargs):
        message = "isolated audit failure"
        raise RuntimeError(message)

    monkeypatch.setattr(c, "audit", broken)
    async with team.sessions() as session:
        with pytest.raises(HTTPException):
            await api.decision(
                team.project,
                item["id"],
                DecisionCommand(**exact(item), decision="APPROVE", comment="Review"),
                session,
                team.people["other"],
            )
    async with team.sessions() as session:
        assert (await c.resource(session, team.project, item["id"])).status == "SUBMITTED"
        assert not (await session.exec(select(AdlcProjectDecision))).all()


@pytest.mark.asyncio
async def test_legacy_owner_coordinator_cannot_read_or_resume_shared_snapshot():
    from langflow.adlc.mock_executor import MockExecutor
    from langflow.adlc.models import AdlcTaskDefinition, CreateWorkflowRunRequest

    scopes = set()

    async def loader():
        return scopes

    legacy = AdlcRunService(MockExecutor(), project_scope_loader=loader)
    run = await legacy.start_run(
        flow_id=uuid4(),
        flow_name="Private run",
        definitions=[
            AdlcTaskDefinition(
                id=uuid4(),
                key="one",
                name="One",
                task_type="ONE",
                dependencies=[],
                predetermined_output={"ok": True},
                artifact={"kind": "REPORT", "name": "Report", "media_type": "text/plain", "content": "checked"},
            )
        ],
        request=CreateWorkflowRunRequest(flow_id=uuid4(), execution_mode="LEGACY_FLOW", delay_ms=0),
        owner_id="source-owner",
    )
    scopes.add(run.id)
    with pytest.raises(AdlcRunNotFoundError):
        await legacy.get_run(run.id, owner_id="source-owner")
    assert (await legacy.list_runs(owner_id="source-owner")).total == 0


@pytest.mark.asyncio
async def test_two_reviewers_race_only_one_decision_is_committed(team):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await c.submit(session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item)))
        await access.commit(session)
    await grant(team, "tester", [TeamRole.TESTER, TeamRole.BUSINESS_ANALYST], revision=6)

    async def review(name):
        async with team.sessions() as session:
            try:
                await c.decide_resource(
                    session,
                    team.project,
                    item["id"],
                    team.people[name],
                    DecisionCommand(
                        **exact(item, policy_revision=7), decision="APPROVE", comment="Independent review."
                    ),
                )
                await access.commit(session)
            except access.TeamAccessError as exc:
                await session.rollback()
                return exc.code
            else:
                return "accepted"

    outcomes = await asyncio.gather(review("other"), review("tester"))
    assert outcomes.count("accepted") == 1
    assert outcomes.count("TEAM_DECISION_ALREADY_RESOLVED") == 1


@pytest.mark.asyncio
async def test_no_independent_reviewer_is_rejected_at_submission(team):
    item = await contract(team, approved=False)
    async with team.sessions() as session:
        await access.remove_member(
            session,
            team.project,
            team.people["operator"],
            team.people["other"].id,
            access.RevisionCommand(expected_revision=6),
        )
        await access.commit(session)
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError, match="TEAM_INDEPENDENT_REVIEWER_REQUIRED"):
            await c.submit(
                session, team.project, item["id"], team.people["ba"], ResourceCommand(**exact(item, policy_revision=7))
            )


@pytest.mark.asyncio
async def test_frozen_suite_cannot_be_changed_or_marked_pass_by_client(team):
    item = await contract(team)
    body = {
        "policy_revision": 6,
        "name": "Pagination assertions",
        "contract_id": item["id"],
        "contract_revision": item["revision"],
        "contract_digest": item["content_digest"],
        "cases": [
            {
                "case_id": "page-case",
                "pointer": "/valid",
                "expected": True,
                "criterion_node_id": item["payload"]["nodes"][0]["node_id"],
                "criterion_index": 0,
            }
        ],
    }
    async with team.sessions() as session:
        suite = await c.create_suite(session, team.project, team.people["tester"], SuiteCommand(**body))
        await c.submit(session, team.project, suite["id"], team.people["tester"], ResourceCommand(**exact(suite)))
        await access.commit(session)
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError, match="TEAM_RESOURCE_LOCKED"):
            await c.create_suite(
                session,
                team.project,
                team.people["tester"],
                SuiteUpdate(**{**body, **exact(suite)}),
                resource_id=suite["id"],
            )
        stored = await c.view(session, team.project, suite["id"], team.people["ba"])
        assert stored["status"] == "FROZEN"
        assert stored["payload"]["criteria_executed"] is False
        assert "verdict" not in stored["payload"]


@pytest.mark.asyncio
async def test_http_extra_actor_and_raw_pass_payloads_are_rejected(team):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[explicit_team_user] = lambda: team.people["ba"]

    async def session_dependency():
        async with team.sessions() as session:
            yield session

    app.dependency_overrides[injectable_session_scope] = session_dependency
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        root = f"/adlc/collaboration/projects/{team.project}"
        response = await client.post(
            root + "/contracts/tools",
            json={
                "policy_revision": 6,
                "tool": "skilltree_init",
                "arguments": {
                    "idempotency_key": "http-create",
                    "title": "Requirement",
                    "scope": {"objective": "Read a report."},
                },
                "owner_id": str(team.people["operator"].id),
            },
        )
        assert response.status_code == 422
        response = await client.post(root + "/suites", json={"policy_revision": 6, "verdict": "PASS"})
        assert response.status_code == 422
        response = await client.get(root)
        assert response.status_code == 200
        assert response.json()["execution_enabled"] is False


@pytest.mark.asyncio
async def test_stream_rechecks_membership_after_first_frame(team, monkeypatch):
    from langflow.adlc.models import WorkflowExecutionMode

    run_id = uuid4()
    async with team.sessions() as session:
        row = await c.create_resource(
            session,
            team.project,
            team.people["developer"],
            "RUN",
            "Prepared",
            WorkflowRun(
                id=run_id,
                project_id=team.project,
                workflow_key="prepared",
                execution_mode=WorkflowExecutionMode.EXECUTION_PLAN,
                name="Prepared",
                status=WorkflowRunStatus.CREATED,
                tasks=[],
                created_at=c.now(),
            ).model_dump(mode="json"),
            identity=run_id,
            status="RETAINED",
        )
        await access.commit(session)

    @asynccontextmanager
    async def scope():
        async with team.sessions() as session:
            yield session

    monkeypatch.setattr(api, "session_scope", scope)
    monkeypatch.setattr(api, "explicit_team_user", AsyncMock(return_value=team.people["ba"]))
    monkeypatch.setattr(api.asyncio, "sleep", AsyncMock())
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    async with team.sessions() as session:
        response = await api.event_stream(team.project, row.id, request, session, team.people["ba"])
    frames = response.body_iterator
    assert "run_events" in await anext(frames)
    async with team.sessions() as session:
        await access.remove_member(
            session,
            team.project,
            team.people["operator"],
            team.people["ba"].id,
            access.RevisionCommand(expected_revision=6),
        )
        await access.commit(session)
    assert "access_revoked" in await anext(frames)
    await frames.aclose()


@pytest.mark.asyncio
async def test_selective_import_preserves_origin_and_requires_exact_manifest(team):
    from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore

    identity = uuid4()
    original = WorkflowRun(
        id=identity,
        workflow_key="old-private",
        execution_mode="LEGACY_FLOW",
        name="Old private run",
        status=WorkflowRunStatus.SUCCEEDED,
        tasks=[],
        created_at=c.now(),
        completed_at=c.now(),
    )
    async with team.sessions() as session:
        session.add(
            AdlcWorkflowRun(
                id=identity,
                owner_id=str(team.people["operator"].id),
                status="SUCCEEDED",
                execution_mode="LEGACY_FLOW",
                run_payload=original.model_dump(mode="json"),
                created_at=original.created_at,
            )
        )
        await access.commit(session)
    async with team.sessions() as session:
        preview = await c.import_preview(session, team.project, identity, team.people["operator"])
        assert "manifest" in preview
        command = ImportRunCommand(
            policy_revision=6, run_id=identity, content_digest=preview["content_digest"], confirm_share=True
        )
        with pytest.raises(access.TeamAccessError, match="TEAM_RESOURCE_REVISION_CONFLICT"):
            await c.import_run(
                session,
                team.project,
                team.people["operator"],
                command.model_copy(update={"content_digest": "sha256:" + "0" * 64}),
                artifact_store=BoundedArtifactPayloadStore(),
            )
        shared = await c.import_run(
            session, team.project, team.people["operator"], command, artifact_store=BoundedArtifactPayloadStore()
        )
        await access.commit(session)
    async with team.sessions() as session:
        stored = await session.get(AdlcWorkflowRun, identity)
        assert stored.run_payload == original.model_dump(mode="json")
        assert stored.owner_id == str(team.people["operator"].id)
        visible = await c.view(session, team.project, identity, team.people["tester"])
        assert visible["content_digest"] == shared["content_digest"]
        with pytest.raises(access.TeamAccessError):
            await c.view(session, team.other_project, identity, team.people["tester"])


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "person"), [(TeamRole.TESTER, "tester"), (TeamRole.DEVELOPER, "developer")])
async def test_hidden_requirement_cannot_be_read_indirectly_through_workflow_or_totals(team, monkeypatch, role, person):
    from langflow.services.authorization import guards, listing

    monkeypatch.setattr(listing, "get_authorization_service", lambda: team.provider)
    monkeypatch.setattr(listing, "get_settings_service", lambda: team.provider.settings_service)
    monkeypatch.setattr(listing, "_auth_context", lambda _: {"auth_method": "jwt"})
    agreed = await contract(team)
    async with team.sessions() as session:
        workflow = await c.write_workflow(session, team.project, team.people["developer"], workflow_command(agreed))
        await access.commit(session)
    request = {
        "user_id": team.people[person].id,
        "obj": f"flow:{workflow['id']}",
        "act": "read",
        "domain": "*",
        "context": {"auth_method": "jwt"},
    }
    assert (await team.provider.enforce_team(**request)).allowed
    async with team.sessions() as session:
        row = await access.load_policy(session, team.project)
        rules = access.policy_from(row)
        rules.roles[role].allow.remove("requirement:read")
        rules.roles[role].deny.append("requirement:read")
        await access.update_policy(
            session, team.project, team.people["operator"], access.PolicyCommand(expected_revision=6, policy=rules)
        )
        await access.commit(session)
    async with team.sessions() as session:
        with pytest.raises(access.TeamAccessError, match="TEAM_PERMISSION_DENIED"):
            await c.view(session, team.project, workflow["id"], team.people[person])
        overview = await c.overview(session, team.project, team.people[person])
        assert overview["total"] == 0
        assert overview["resources"] == []
        statement = await listing.restrict_team_flow_statement(session, team.people[person], select(Flow))
        assert not (await session.exec(statement)).all()
    assert not (await team.provider.enforce_team(**request)).allowed
    with pytest.raises(HTTPException):
        await guards.ensure_flow_permission(
            team.people[person], "read", flow_id=UUID(workflow["id"]), flow_user_id=team.people["developer"].id
        )


@pytest.mark.asyncio
async def test_legacy_project_owner_cannot_read_unbound_graph_or_leak_pagination_count(team, monkeypatch):
    from fastapi_pagination import Params

    from langflow.api.v1 import flows
    from langflow.api.v1.projects import read_project
    from langflow.services.authorization import listing
    from langflow.services.database.models.folder.constants import DEFAULT_FOLDER_NAME
    from langflow.services.database.models.folder.model import Folder

    monkeypatch.setattr(listing, "get_authorization_service", lambda: team.provider)
    monkeypatch.setattr(listing, "get_settings_service", lambda: team.provider.settings_service)
    monkeypatch.setattr(listing, "_auth_context", lambda _: {"auth_method": "jwt"})
    monkeypatch.setattr(flows, "get_settings_service", lambda: team.provider.settings_service)
    async with team.sessions() as session:
        session.add(Flow(name="Unbound graph", folder_id=team.project, user_id=team.people["operator"].id))
        session.add(Folder(name=DEFAULT_FOLDER_NAME, user_id=team.people["operator"].id))
        await access.commit(session)
    async with team.sessions() as session:
        view = await read_project(
            session=session, project_id=team.project, current_user=team.people["operator"], params=None
        )
        assert view.flows == []
        page = await read_project(
            session=session,
            project_id=team.project,
            current_user=team.people["operator"],
            params=Params(page=1, size=10),
            page=1,
            size=10,
        )
        assert page.flows.total == 0
        assert page.flows.items == []
        flow_page = await flows.read_flows(
            session=session,
            current_user=team.people["operator"],
            params=Params(page=1, size=10),
            folder_id=team.project,
            get_all=False,
        )
        assert flow_page.total == 0
        assert flow_page.items == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("observed", "can_accept"), [(42, True), (41, False)])
async def test_quality_acceptance_recomputes_the_quantitative_report(team, observed, can_accept):
    from langflow.adlc.verification_models import VerificationRead, compare, digest
    from langflow.adlc.verification_repository import RUNNER_DIGEST
    from tests.unit.adlc.test_verification import example_plan, receipt_for

    plan = example_plan()
    receipt = receipt_for(plan, observed=observed)
    report = compare(plan, receipt, RUNNER_DIGEST)
    verified = VerificationRead(
        plan=plan,
        plan_digest=digest(plan),
        state="READY_FOR_SUBMISSION",
        approved_by=str(team.people["developer"].id),
        approved_at=c.now(),
        execution_id=receipt.execution_id,
        receipt=receipt,
        report=report,
        created_at=c.now(),
        evidence_digest=digest(
            {
                "plan": plan.model_dump(mode="json"),
                "receipt": receipt.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            }
        ),
    )
    async with team.sessions() as session:
        row = await c.create_resource(
            session,
            team.project,
            team.people["developer"],
            "VERIFICATION",
            "Frozen evidence",
            verified.model_dump(mode="json"),
            status="SUBMITTED",
        )
        await access.commit(session)
    async with team.sessions() as session:
        item = await c.view(session, team.project, row.id, team.people["tester"])
        command = DecisionCommand(
            **exact(item), decision="APPROVE", comment="Reviewed the retained observations and comparison."
        )
        if can_accept:
            decision = await c.decide_resource(session, team.project, row.id, team.people["tester"], command)
            assert decision["decided_by"] == str(team.people["tester"].id)
        else:
            with pytest.raises(access.TeamAccessError, match="TEAM_VERIFIED_PASS_REQUIRED"):
                await c.decide_resource(session, team.project, row.id, team.people["tester"], command)
        assert (await c.snapshot(session, row))["report"] == report.model_dump(mode="json")
    forged = verified.model_dump(mode="json")
    forged["report"]["verdict"] = "FAIL" if can_accept else "PASS"
    forged["evidence_digest"] = digest(
        {"plan": forged["plan"], "receipt": forged["receipt"], "report": forged["report"]}
    )
    with pytest.raises(access.TeamAccessError, match="TEAM_VERIFICATION_BINDING_INVALID"):
        c.verified_evidence(forged)


@pytest.mark.asyncio
async def test_legacy_plan_route_cannot_borrow_original_owner_after_binding(team):
    from langflow.api.v1.adlc_collaboration_boundary import legacy_collaboration_boundary

    agreed = await contract(team)
    async with team.sessions() as session:
        request = SimpleNamespace(
            url=SimpleNamespace(path=f"/api/v1/adlc/execution-plans/{agreed['id']}"),
            path_params={"plan_id": agreed["id"]},
        )
        with pytest.raises(HTTPException) as error:
            await legacy_collaboration_boundary(request, session)
        assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_h7a_only_provider_cannot_activate_or_serve_h7b(team, monkeypatch):
    from langflow.services import deps

    monkeypatch.setattr(deps, "get_authorization_service", lambda: SimpleNamespace(TEAM_POLICY_VERSION="0.1"))
    with pytest.raises(HTTPException) as error:
        await api.collaboration_user(team.people["operator"])
    assert error.value.status_code == 503

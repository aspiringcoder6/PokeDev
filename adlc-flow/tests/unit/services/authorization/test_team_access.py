"""H7A uses real SQLite transactions; no model, Docker or GitHub calls."""

# ruff: noqa: S101, SLF001, PLR2004 - pytest assertions, boundary probes and fixed expected values.

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from langflow.api.v1 import adlc_team_access as api
from langflow.services.authorization import guards, team_provider
from langflow.services.authorization import team_access as store
from langflow.services.authorization.team_catalog import (
    TeamPolicy,
    TeamRole,
    decide,
    default_policy,
    role_id,
    role_name,
)
from langflow.services.database.models.auth import (
    AuthzAuditLog,
    AuthzRole,
    AuthzRoleAssignment,
    AuthzRoleAssignmentGrant,
    AuthzShare,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User
from lfx.services.authorization import AuthorizationMutation, AuthorizationMutationKind, AuthorizationMutationRejected
from lfx.services.deps import injectable_session_scope


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'team.sqlite3'}")
    tables = [
        User.__table__,
        Folder.__table__,
        Flow.__table__,
        AuthzRole.__table__,
        AuthzRoleAssignment.__table__,
        AuthzRoleAssignmentGrant.__table__,
        AuthzAuditLog.__table__,
        AuthzShare.__table__,
        AdlcProjectAccess.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: SQLModel.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        people = {
            name: User(
                username=name,
                password="not-a-real-password",  # noqa: S106 - isolated test identity, never a login credential.
                is_active=True,
                is_superuser=name in {"operator", "other"},
            )
            for name in ["operator", "other", "developer", "ba", "tester"]
        }
        session.add_all(list(people.values()))
        await session.flush()
        for role in TeamRole:
            session.add(AuthzRole(id=role_id(role), name=role_name(role), is_system=True, permissions=[]))
        await session.commit()

    @asynccontextmanager
    async def scope():
        async with sessions() as session:
            try:
                yield session
            finally:
                await session.rollback()

    monkeypatch.setattr(team_provider, "session_scope", scope)
    monkeypatch.setattr(team_provider, "_provider_required", False)
    settings = SimpleNamespace(auth_settings=SimpleNamespace(AUTHZ_ENABLED=False, AUTO_LOGIN=False))
    provider = team_provider.TeamAuthorizationService(settings)
    from langflow.services import deps

    monkeypatch.setattr(deps, "get_authorization_service", lambda: provider)
    monkeypatch.setattr(guards, "get_authorization_service", lambda: provider)
    monkeypatch.setattr(guards, "get_settings_service", lambda: settings)
    monkeypatch.setattr(guards, "_auth_context", lambda _: {"auth_method": "jwt"})
    monkeypatch.setattr(api, "get_authorization_service", lambda: provider)
    monkeypatch.setattr(api, "get_settings_service", lambda: settings)
    from langflow.api.v1 import authz_me

    monkeypatch.setattr(authz_me, "get_authorization_service", lambda: provider)

    async def audit_noop(**kwargs):
        pass

    monkeypatch.setattr(guards._audit, "audit_decision", audit_noop)
    async with sessions() as session:
        project = await store.create_project(session, people["operator"], "Project A")
        other_project = await store.create_project(session, people["other"], "Project B")
        await store.commit(session)
    yield SimpleNamespace(
        sessions=sessions, people=people, project=project, other_project=other_project, provider=provider
    )
    await engine.dispose()


async def grant(db, name, roles, revision=1):
    async with db.sessions() as session:
        await store.set_member(
            session,
            db.project,
            db.people["operator"],
            store.MemberCommand(expected_revision=revision, username=name, roles=roles),
        )
        await store.commit(session)


def test_closed_catalog_deny_wins_and_future_stays_closed():
    policy = default_policy()
    assert len(policy.roles) == 4
    assert decide(policy, {TeamRole.DEVELOPER}, "flow:execute") == (False, "TEAM_SHARED_EXECUTION_NOT_ENABLED")
    assert decide(policy, {TeamRole.ADMIN}, "secrets:read") == (False, "TEAM_UNKNOWN_ACTION")
    policy.roles[TeamRole.TESTER].allow.remove("project:read")
    policy.roles[TeamRole.TESTER].deny.append("project:read")
    assert decide(policy, {TeamRole.DEVELOPER, TeamRole.TESTER}, "project:read")[1] == "TEAM_EXPLICIT_DENY"


def test_cannot_grant_admin_or_unknown_actions_to_developer():
    raw = default_policy().model_dump(mode="json")
    raw["roles"]["developer"]["allow"].append("policy:manage")
    with pytest.raises(ValidationError, match="TEAM_ADMIN_PERMISSION_RESERVED"):
        TeamPolicy.model_validate(raw)
    with pytest.raises(ValidationError):
        store.PolicyCommand(expected_revision=1, policy=default_policy(), owner_id=str(uuid4()))


@pytest.mark.asyncio
async def test_project_scope_and_bootstrap_are_not_superuser_bypasses(db):
    async with db.sessions() as session:
        with pytest.raises(store.TeamAccessError, match="TEAM_BOOTSTRAP_OPERATOR_REQUIRED"):
            await store.create_project(session, db.people["developer"], "Denied")
        with pytest.raises(store.TeamAccessError, match="TEAM_MEMBERSHIP_REQUIRED"):
            await store.project_view(session, db.other_project, db.people["operator"])
        assert len(await store.visible_projects(session, db.people["operator"])) == 1


@pytest.mark.asyncio
async def test_four_roles_and_own_permissions_without_member_directory(db):
    for revision, (name, role) in enumerate(
        [("developer", TeamRole.DEVELOPER), ("ba", TeamRole.BUSINESS_ANALYST), ("tester", TeamRole.TESTER)], 1
    ):
        await grant(db, name, [role], revision)
    async with db.sessions() as session:
        view = await store.project_view(session, db.project, db.people["developer"])
        assert not view["can_manage"]
        assert view["members"] == []
        assert view["policy"] is None
        assert view["effective"]["permissions"]["flow:execute"]["allowed"] is False
        assert view["effective"]["permissions"]["flow:execute"]["granted"] is True
        assert view["effective"]["revision"] == 4
        admin = await store.project_view(session, db.project, db.people["operator"])
        assert len(admin["members"]) == 4


@pytest.mark.asyncio
async def test_non_admin_cannot_assign_self_or_modify_policy(db):
    await grant(db, "developer", [TeamRole.DEVELOPER])
    async with db.sessions() as session:
        with pytest.raises(store.TeamAccessError, match="TEAM_PERMISSION_DENIED"):
            await store.set_member(
                session,
                db.project,
                db.people["developer"],
                store.MemberCommand(expected_revision=2, username="developer", roles=[TeamRole.ADMIN]),
            )
        await session.rollback()
        with pytest.raises(store.TeamAccessError, match="TEAM_PERMISSION_DENIED"):
            await store.update_policy(
                session,
                db.project,
                db.people["developer"],
                store.PolicyCommand(expected_revision=2, policy=default_policy()),
            )


@pytest.mark.asyncio
async def test_policy_compare_and_swap_and_atomic_audit(db):
    async with db.sessions() as session:
        policy = default_policy()
        policy.roles[TeamRole.DEVELOPER].allow.remove("flow:write")
        await store.update_policy(
            session, db.project, db.people["operator"], store.PolicyCommand(expected_revision=1, policy=policy)
        )
        await store.commit(session)
    async with db.sessions() as session:
        with pytest.raises(store.TeamAccessError, match="TEAM_POLICY_REVISION_CONFLICT"):
            await store.update_policy(
                session,
                db.project,
                db.people["operator"],
                store.PolicyCommand(expected_revision=1, policy=default_policy()),
            )
        await session.rollback()
        row = await store.load_policy(session, db.project)
        assert row.revision == 2
        events = (await session.exec(select(AuthzAuditLog).where(AuthzAuditLog.resource_id == db.project))).all()
        assert [event.action for event in events].count("team_access:policy_updated") == 1


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_policy_and_revision(db, monkeypatch):
    def broken(*_args, **_kwargs):
        message = "simulated unavailable audit store"
        raise RuntimeError(message)

    monkeypatch.setattr(store, "add_audit", broken)
    async with db.sessions() as session:
        with pytest.raises(HTTPException) as error:
            await api.update_policy(
                db.project,
                store.PolicyCommand(expected_revision=1, policy=default_policy()),
                session,
                db.people["operator"],
            )
        assert error.value.status_code == 503
    async with db.sessions() as session:
        assert (await store.load_policy(session, db.project)).revision == 1


@pytest.mark.asyncio
async def test_last_admin_cannot_be_revoked_or_disabled(db):
    async with db.sessions() as session:
        with pytest.raises(store.TeamAccessError, match="TEAM_LAST_ADMIN_PROTECTED"):
            await store.remove_member(
                session,
                db.project,
                db.people["operator"],
                db.people["operator"].id,
                store.RevisionCommand(expected_revision=1),
            )
        await session.rollback()
        mutation = AuthorizationMutation(
            kind=AuthorizationMutationKind.USER_DISABLED,
            entity_id=db.people["operator"].id,
            actor_user_id=db.people["other"].id,
            affected_user_ids=(db.people["operator"].id,),
        )
        with pytest.raises(AuthorizationMutationRejected, match="TEAM_LAST_ADMIN_PROTECTED"):
            await db.provider.validate_identity_mutation(session=session, mutation=mutation)


@pytest.mark.asyncio
async def test_multi_role_deny_cannot_lock_out_last_effective_admin(db):
    await grant(db, "operator", [TeamRole.ADMIN, TeamRole.DEVELOPER])
    async with db.sessions() as session:
        policy = default_policy()
        policy.roles[TeamRole.DEVELOPER].deny.append("policy:manage")
        with pytest.raises(store.TeamAccessError, match="TEAM_LAST_ADMIN_PROTECTED"):
            await store.update_policy(
                session, db.project, db.people["operator"], store.PolicyCommand(expected_revision=2, policy=policy)
            )
        await session.rollback()
        assert (await store.load_policy(session, db.project)).revision == 2


@pytest.mark.asyncio
async def test_two_admins_concurrent_self_revocation_leaves_one(db):
    await grant(db, "other", [TeamRole.ADMIN])

    async def revoke(name):
        async with db.sessions() as session:
            try:
                await store.remove_member(
                    session, db.project, db.people[name], db.people[name].id, store.RevisionCommand(expected_revision=2)
                )
                await store.commit(session)
            except store.TeamAccessError as exc:
                await session.rollback()
                return exc.code
            else:
                return "removed"

    outcomes = await asyncio.gather(revoke("operator"), revoke("other"))
    assert outcomes.count("removed") == 1
    async with db.sessions() as session:
        await store.ensure_administrable(session, await store.load_policy(session, db.project))


@pytest.mark.asyncio
async def test_revocation_is_fresh_across_provider_instances_and_legacy_is_unchanged(db):
    await grant(db, "developer", [TeamRole.DEVELOPER])
    request = {
        "user_id": db.people["developer"].id,
        "obj": f"project:{db.project}",
        "act": "read",
        "domain": "*",
        "context": {"auth_method": "jwt"},
    }
    second = team_provider.TeamAuthorizationService(db.provider.settings_service)
    assert await second.enforce(**request)
    async with db.sessions() as session:
        await store.remove_member(
            session,
            db.project,
            db.people["operator"],
            db.people["developer"].id,
            store.RevisionCommand(expected_revision=2),
        )
        await store.commit(session)
    assert not await second.enforce(**request)
    assert await second.enforce(**{**request, "obj": f"project:{uuid4()}"})


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_legacy_lists_cannot_restore_revoked_owner_or_scope_prefilter(db, monkeypatch, enabled):
    from langflow.services.authorization import listing

    settings = db.provider.settings_service
    settings.auth_settings.AUTHZ_ENABLED = enabled
    monkeypatch.setattr(listing, "get_settings_service", lambda: settings)
    monkeypatch.setattr(listing, "get_authorization_service", lambda: db.provider)
    monkeypatch.setattr(listing, "_auth_context", lambda _: {"auth_method": "jwt"})
    scope_hook = AsyncMock()
    id_hook = AsyncMock()
    monkeypatch.setattr(db.provider, "get_resource_visibility", scope_hook)
    monkeypatch.setattr(db.provider, "list_visible_resource_ids", id_hook)
    assert await listing.visible_scope_prefilter(db.people["operator"], resource_type="project") is None
    assert await listing.visible_id_prefilter(db.people["operator"], resource_type="project") is None
    scope_hook.assert_not_awaited()
    id_hook.assert_not_awaited()
    async with db.sessions() as session:
        managed = await session.get(Folder, db.project)
        legacy = Folder(name="Still private", user_id=db.people["operator"].id)
        session.add(legacy)
        await session.commit()
    kwargs = {"resource_type": "project", "candidates": [managed, legacy], "owner_extractor": lambda item: item.user_id}
    assert await listing.filter_visible_resources(db.people["operator"], **kwargs) == [managed, legacy]
    await grant(db, "other", [TeamRole.ADMIN])
    async with db.sessions() as session:
        await store.remove_member(
            session,
            db.project,
            db.people["other"],
            db.people["operator"].id,
            store.RevisionCommand(expected_revision=2),
        )
        await store.commit(session)
    assert await listing.filter_visible_resources(db.people["operator"], **kwargs) == [legacy]


@pytest.mark.asyncio
async def test_managed_public_links_fail_closed_without_changing_legacy_links(db, monkeypatch):
    from langflow.services.authorization import public_access
    from langflow.services.database.models.flow.model import AccessTypeEnum
    from lfx.services.authorization import PublicResourceAction

    monkeypatch.setattr(public_access, "get_settings_service", lambda: db.provider.settings_service)
    monkeypatch.setattr(public_access, "get_authorization_service", lambda: db.provider)
    monkeypatch.setattr(public_access, "audit_decision", AsyncMock())
    async with db.sessions() as session:
        managed = Flow(
            name="Managed public",
            user_id=db.people["operator"].id,
            folder_id=db.project,
            access_type=AccessTypeEnum.PUBLIC,
        )
        legacy = Flow(name="Legacy public", user_id=db.people["operator"].id, access_type=AccessTypeEnum.PUBLIC)
        session.add_all([managed, legacy])
        await session.commit()
        for action in (PublicResourceAction.READ, PublicResourceAction.EXECUTE):
            with pytest.raises(HTTPException) as error:
                await public_access.authorize_public_flow_access(flow=managed, action=action, session=session)
            assert error.value.status_code == 404
        await public_access.authorize_public_flow_access(flow=legacy, action=PublicResourceAction.READ, session=session)


@pytest.mark.asyncio
async def test_user_delete_keeps_project_revision_and_audit_after_assignment_cascade(db):
    await grant(db, "developer", [TeamRole.DEVELOPER])
    mutation = AuthorizationMutation(
        kind=AuthorizationMutationKind.USER_DELETED,
        entity_id=db.people["developer"].id,
        actor_user_id=db.people["operator"].id,
        affected_user_ids=(db.people["developer"].id,),
    )
    async with db.sessions() as session:
        await db.provider.acquire_identity_mutation_lock(
            session=session, kind=mutation.kind, affected_user_ids=mutation.affected_user_ids
        )
        await db.provider.validate_identity_mutation(session=session, mutation=mutation)
        assignments = (
            await session.exec(
                select(AuthzRoleAssignment).where(AuthzRoleAssignment.user_id == db.people["developer"].id)
            )
        ).all()
        for assignment in assignments:
            grants = (
                await session.exec(
                    select(AuthzRoleAssignmentGrant).where(AuthzRoleAssignmentGrant.assignment_id == assignment.id)
                )
            ).all()
            for source in grants:
                await session.delete(source)
            await session.delete(assignment)
        await session.exec(delete(User).where(User.id == db.people["developer"].id))
        await session.flush()
        await db.provider.stage_identity_mutation(session=session, event=mutation)
        await store.commit(session)
    async with db.sessions() as session:
        assert (await store.load_policy(session, db.project)).revision == 3
        events = (
            await session.exec(select(AuthzAuditLog).where(AuthzAuditLog.action == "team_access:identity_revoked"))
        ).all()
        assert len(events) == 1
        assert events[0].details["subjects"] == [str(db.people["developer"].id)]


@pytest.mark.asyncio
async def test_guard_precedes_owner_and_disabled_global_authz(db):
    with pytest.raises(HTTPException) as error:
        await guards.ensure_project_permission(
            db.people["operator"], "write", project_id=db.project, project_user_id=db.people["operator"].id
        )
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "TEAM_UNKNOWN_ACTION"
    await guards.ensure_project_permission(
        db.people["operator"], "read", project_id=db.project, project_user_id=db.people["operator"].id
    )
    with pytest.raises(HTTPException):
        await guards.ensure_project_permission(
            db.people["operator"], "read", project_id=db.other_project, project_user_id=db.people["operator"].id
        )


@pytest.mark.asyncio
async def test_owner_loses_access_and_api_key_does_not_inherit_user(db):
    request = {"user_id": db.people["operator"].id, "obj": f"project:{db.project}", "act": "read", "domain": "*"}
    assert not await db.provider.enforce(**request, context={"auth_method": "api_key"})
    await grant(db, "other", [TeamRole.ADMIN])
    async with db.sessions() as session:
        await store.remove_member(
            session,
            db.project,
            db.people["operator"],
            db.people["operator"].id,
            store.RevisionCommand(expected_revision=2),
        )
        await store.commit(session)
    assert not await db.provider.enforce(**request, context={"auth_method": "jwt"})


@pytest.mark.asyncio
async def test_unavailable_policy_and_missing_provider_fail_closed(db, monkeypatch):
    async def unavailable(**_kwargs):
        message = "do not expose driver detail"
        raise RuntimeError(message)

    monkeypatch.setattr(db.provider, "enforce_team", unavailable)
    with pytest.raises(HTTPException) as error:
        await guards.ensure_project_permission(db.people["operator"], "read", project_id=db.project)
    assert error.value.status_code == 503
    assert "driver" not in str(error.value.detail)
    with pytest.raises(store.TeamAccessError, match="TEAM_ENFORCEMENT_PROVIDER_REQUIRED"):
        await team_provider.assert_team_access_ready(SimpleNamespace())


@pytest.mark.asyncio
async def test_http_owner_identity_cannot_be_overridden_by_payload(db):
    app = FastAPI()
    app.include_router(api.router)

    async def session_dependency():
        async with db.sessions() as session:
            yield session

    app.dependency_overrides[injectable_session_scope] = session_dependency
    app.dependency_overrides[api.explicit_team_user] = lambda: db.people["operator"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/adlc/team-access/projects/{db.other_project}")).status_code == 404
        response = await client.put(
            f"/adlc/team-access/projects/{db.project}/members",
            json={
                "expected_revision": 1,
                "username": "developer",
                "roles": ["developer"],
                "owner_id": str(db.people["other"].id),
            },
        )
        assert response.status_code == 422
        response = await client.put(
            f"/adlc/team-access/projects/{db.project}/members",
            json={"expected_revision": 1, "username": "developer", "roles": ["developer"]},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_explicit_login_never_accepts_auto_login_or_tool_identity(db, monkeypatch):
    monkeypatch.setattr(
        api, "get_settings_service", lambda: SimpleNamespace(auth_settings=SimpleNamespace(AUTO_LOGIN=True))
    )
    request = Request({"type": "http", "headers": []})
    async with db.sessions() as session:
        with pytest.raises(HTTPException) as error:
            await api.explicit_team_user(request, session)
        assert error.value.detail["code"] == "TEAM_EXPLICIT_LOGIN_REQUIRED"


@pytest.mark.asyncio
async def test_canonical_flow_scope_and_descendants_cannot_escape(db):
    await grant(db, "operator", [TeamRole.ADMIN, TeamRole.DEVELOPER])
    async with db.sessions() as session:
        child = Folder(id=uuid4(), name="Child", user_id=db.people["operator"].id, parent_id=db.project)
        session.add(child)
        await session.flush()
        flow = Flow(id=uuid4(), name="Bound flow", user_id=db.people["operator"].id, folder_id=child.id)
        session.add(flow)
        await store.commit(session)
    request = {
        "user_id": db.people["operator"].id,
        "domain": f"project:{db.other_project}",
        "obj": f"flow:{flow.id}",
        "act": "execute",
        "context": {"auth_method": "jwt", "folder_id": db.other_project},
    }
    decision = await db.provider.enforce_team(**request)
    assert decision
    assert not decision.allowed
    assert decision.reason == "TEAM_SHARED_EXECUTION_NOT_ENABLED"
    with pytest.raises(HTTPException):
        await guards.ensure_flows_permission(
            db.people["operator"],
            "delete",
            flow_ids=[flow.id],
            flow_user_id=db.people["operator"].id,
            folder_id=child.id,
        )


@pytest.mark.asyncio
async def test_effective_permissions_endpoint_cannot_restore_owner_override(db):
    from langflow.api.v1.authz_me import _apply_owner_permissions

    async with db.sessions() as session:
        result = await _apply_owner_permissions(
            session=session,
            permissions={db.project: []},
            resource_type="project",
            resource_ids=[db.project],
            actions=("write", "execute"),
            user_id=db.people["operator"].id,
        )
    assert result[db.project] == []


@pytest.mark.asyncio
async def test_corrupt_or_unknown_policy_never_falls_back_to_legacy(db):
    async with db.sessions() as session:
        row = await store.load_policy(session, db.project)
        row.mode = "RUN_ANYTHING"
        session.add(row)
        await store.commit(session)
    with pytest.raises(HTTPException) as error:
        await guards.ensure_project_permission(db.people["operator"], "read", project_id=db.project)
    assert error.value.status_code == 503


@pytest.mark.parametrize("metadata_precreated", [False, True])
def test_migration_seeds_exact_roles_without_changing_legacy_or_granting_membership(metadata_precreated):
    import importlib.util
    from datetime import datetime, timezone
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[4] / "langflow/alembic/versions/h7a1b2c3d4e5_add_adlc_project_access.py"
    spec = importlib.util.spec_from_file_location("h7a_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        SQLModel.metadata.create_all(
            connection,
            tables=[
                User.__table__,
                Folder.__table__,
                AuthzRole.__table__,
                AuthzRoleAssignment.__table__,
                AuthzRoleAssignmentGrant.__table__,
            ],
        )
        if metadata_precreated:
            AdlcProjectAccess.__table__.create(connection)
        legacy_id = uuid4()
        now = datetime.now(timezone.utc)
        connection.execute(
            sa.insert(AuthzRole).values(
                id=legacy_id,
                name="developer",
                permissions=["flow:write"],
                is_system=True,
                created_at=now,
                updated_at=now,
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        rows = connection.execute(sa.select(AuthzRole.__table__)).mappings().all()
        assert len(rows) == 5
        assert {row["id"] for row in rows if row["name"].startswith("adlc.")} == {role_id(role) for role in TeamRole}
        assert next(row for row in rows if row["id"] == legacy_id)["permissions"] == ["flow:write"]
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(AuthzRoleAssignment.__table__)).scalar_one() == 0
        )
        assert connection.execute(sa.select(sa.func.count()).select_from(AdlcProjectAccess.__table__)).scalar_one() == 0
    engine.dispose()


@pytest.mark.parametrize("collision", ["name", "id"])
def test_migration_rejects_reserved_role_collisions_before_creating_policy_store(collision):
    import importlib.util
    from datetime import datetime, timezone
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[4] / "langflow/alembic/versions/h7a1b2c3d4e5_add_adlc_project_access.py"
    spec = importlib.util.spec_from_file_location("h7a_migration_collision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        AuthzRole.__table__.create(connection)
        now = datetime.now(timezone.utc)
        connection.execute(
            sa.insert(AuthzRole).values(
                id=role_id(TeamRole.ADMIN) if collision == "id" else uuid4(),
                name="adlc.admin" if collision == "name" else "legacy-custom",
                is_system=False,
                permissions=[],
                created_at=now,
                updated_at=now,
            )
        )
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="unverified role"),
        ):
            module.upgrade()
        assert not sa.inspect(connection).has_table("adlc_project_access")
        assert connection.execute(sa.select(sa.func.count()).select_from(AuthzRole.__table__)).scalar_one() == 1
    engine.dispose()

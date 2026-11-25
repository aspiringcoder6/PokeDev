"""Durability, ownership, optimistic concurrency and migration regression checks."""

import asyncio
import importlib.util
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from langflow.adlc import intake
from langflow.adlc.intake_models import CancelIntake, CreateIntake, IntakeContent, UpdateIntake
from langflow.api.utils import CurrentActiveUser, DbSession
from langflow.api.v1.adlc_intake import router
from langflow.services.authorization import team_access
from langflow.services.authorization.team_catalog import TeamRole, role_id, role_name
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_intake import AdlcIntakeCommand, AdlcIntakeRequest, AdlcIntakeRevision
from langflow.services.database.models.adlc_workflow_run import AdlcWorkflowRun
from langflow.services.database.models.auth import AuthzRole, AuthzRoleAssignment, AuthzRoleAssignmentGrant
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User


@pytest_asyncio.fixture
async def database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'intake.db'}")

    @sa.event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        owner = User(username="intake-owner", password="test-only", is_active=True, is_superuser=True)
        other = User(username="intake-other", password="test-only", is_active=True)
        session.add_all([owner, other])
        session.add_all([AuthzRole(id=role_id(role), name=role_name(role), is_system=True) for role in TeamRole])
        await session.commit()
        yield engine, session, owner, other
    await engine.dispose()


def create_command(**kwargs):
    return CreateIntake(
        command_id=uuid4(),
        content=IntakeContent(title="Export revenue", description="Export a monthly report"),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_receipt_and_history_survive_new_session(database):
    engine, session, owner, _ = database
    command = create_command()
    original = await intake.create(session, owner, command)
    await session.commit()
    async with AsyncSession(engine, expire_on_commit=False) as reopened:
        replay = await intake.create(reopened, owner, command)
        assert replay == {**original, "replayed": True}
        history = await intake.history(reopened, owner, UUID(original["request"]["id"]))
        assert history["items"][0]["snapshot"] == original["request"]
        assert (await intake.listing(reopened, owner))["total"] == 1


@pytest.mark.asyncio
async def test_command_reuse_with_different_input_is_rejected(database):
    _, session, owner, _ = database
    command = create_command()
    await intake.create(session, owner, command)
    await session.commit()
    changed = command.model_copy(update={"content": IntakeContent(title="Other", description="Different input")})
    with pytest.raises(intake.IntakeError, match="COMMAND_CONFLICT"):
        await intake.create(session, owner, changed)


@pytest.mark.asyncio
async def test_owner_boundary_covers_read_history_update_and_listing(database):
    _, session, owner, other = database
    created = await intake.create(session, owner, create_command())
    await session.commit()
    identity = UUID(created["request"]["id"])
    for operation in [
        intake.owned(session, other, identity),
        intake.history(session, other, identity),
        intake.change(session, other, identity, CancelIntake(command_id=uuid4(), expected_revision=1)),
    ]:
        with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
            await operation
    assert (await intake.listing(session, other))["items"] == []


@pytest.mark.asyncio
async def test_stale_edit_does_not_overwrite_and_original_history_stays_intact(database):
    _, session, owner, _ = database
    first = await intake.create(session, owner, create_command())
    identity = UUID(first["request"]["id"])
    await session.commit()
    command = UpdateIntake(
        command_id=uuid4(),
        expected_revision=1,
        content=IntakeContent(title="CSV export", description="Confirmed monthly CSV"),
    )
    second = await intake.change(session, owner, identity, command)
    await session.commit()
    assert second["request"]["revision"] == 2
    assert (await intake.change(session, owner, identity, command))["replayed"] is True
    with pytest.raises(intake.IntakeError, match="REVISION_CONFLICT"):
        await intake.change(session, owner, identity, command.model_copy(update={"command_id": uuid4()}))
    history = (await intake.history(session, owner, identity))["items"]
    assert [r["revision"] for r in history] == [2, 1]
    assert history[-1]["snapshot"] == first["request"]


@pytest.mark.asyncio
async def test_cancel_is_revisioned_and_closes_edits(database):
    _, session, owner, _ = database
    first = await intake.create(session, owner, create_command())
    identity = UUID(first["request"]["id"])
    command = CancelIntake(command_id=uuid4(), expected_revision=1)
    result = await intake.change(session, owner, identity, command)
    await session.commit()
    assert result["request"]["status"] == "CANCELLED"
    assert result["request"]["revision"] == 2
    assert (await intake.change(session, owner, identity, command))["replayed"] is True
    with pytest.raises(intake.IntakeError, match="CLOSED"):
        await intake.change(
            session,
            owner,
            identity,
            UpdateIntake(
                command_id=uuid4(),
                expected_revision=2,
                content=IntakeContent(title="Try again", description="Closed request"),
            ),
        )


@pytest.mark.asyncio
async def test_project_binding_needs_membership_and_revocation_hides_intake(database):
    _, session, owner, other = database
    project_id = await team_access.create_project(session, owner, "Intake pilot")
    await session.commit()
    with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
        await intake.create(session, other, create_command(project_id=project_id))
    result = await intake.create(session, owner, create_command(project_id=project_id))
    await session.commit()
    assignment = (
        await session.exec(select(AuthzRoleAssignment).where(AuthzRoleAssignment.domain_id == project_id))
    ).one()
    await session.execute(
        sa.delete(AuthzRoleAssignmentGrant).where(AuthzRoleAssignmentGrant.assignment_id == assignment.id)
    )
    await session.delete(assignment)
    await session.commit()
    assert (await intake.listing(session, owner))["items"] == []
    with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
        await intake.owned(session, owner, UUID(result["request"]["id"]))


@pytest.mark.asyncio
async def test_rollback_does_not_leave_half_an_intake(database):
    _, session, owner, _ = database
    await intake.create(session, owner, create_command())
    await session.rollback()
    for model in [AdlcIntakeRequest, AdlcIntakeRevision, AdlcIntakeCommand]:
        assert (await session.exec(select(model))).all() == []


def revision_module():
    path = Path(__file__).resolve().parents[3] / "langflow/alembic/versions/li01a2b3c4d5_add_requirement_intake.py"
    spec = importlib.util.spec_from_file_location("intake_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("precreated", [False, True])
def test_migration_matches_runtime_schema(precreated):
    module = revision_module()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        SQLModel.metadata.create_all(connection, tables=[User.__table__, Folder.__table__])
        if precreated:
            SQLModel.metadata.create_all(
                connection,
                tables=[AdlcIntakeRequest.__table__, AdlcIntakeRevision.__table__, AdlcIntakeCommand.__table__],
            )
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        assert all(module._compatible(connection, table) for table in module.tables())
        assert all(
            module._compatible(connection, table)
            for table in [AdlcIntakeRequest.__table__, AdlcIntakeRevision.__table__, AdlcIntakeCommand.__table__]
        )
    engine.dispose()


def test_migration_rejects_incompatible_table():
    module = revision_module()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE adlc_intake_request (id VARCHAR PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="Refusing"):
            module.upgrade()
    engine.dispose()


@pytest_asyncio.fixture
async def http_client(database, monkeypatch):
    engine, _, owner, _ = database
    actor = {"user": owner}
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def user(session: DbSession):
        if actor["user"] is None:
            raise HTTPException(status_code=401)
        # Production authentication uses the same request session as the API.
        return await session.get(User, actor["user"].id)

    app.dependency_overrides[get_args(DbSession)[1].dependency] = db
    app.dependency_overrides[get_args(CurrentActiveUser)[1].dependency] = user
    monkeypatch.setenv("POKEDEV_INTAKE_ENABLED", "true")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, actor


@pytest.mark.asyncio
async def test_http_duplicate_create_is_atomic_and_does_not_execute(database, http_client):
    _, session, _, _ = database
    client, _ = http_client
    body = create_command().model_dump(mode="json")
    responses = await asyncio.gather(*(client.post("/api/v1/adlc/intake/requests", json=body) for _ in range(2)))
    assert [r.status_code for r in responses] == [201, 201]
    assert len({r.json()["request"]["id"] for r in responses}) == 1
    assert {r.json()["replayed"] for r in responses} == {False, True}
    for model in [AdlcIntakeRequest, AdlcIntakeRevision, AdlcIntakeCommand]:
        assert len((await session.exec(select(model))).all()) == 1
    for model in [AdlcExecutionPlan, AdlcWorkflowRun]:
        assert (await session.exec(select(model))).all() == []


@pytest.mark.asyncio
async def test_http_two_edits_have_one_winner(database, http_client):
    client, _ = http_client
    first = (await client.post("/api/v1/adlc/intake/requests", json=create_command().model_dump(mode="json"))).json()[
        "request"
    ]
    commands = [
        UpdateIntake(
            command_id=uuid4(), expected_revision=1, content=IntakeContent(title=name, description="Concurrent edit")
        ).model_dump(mode="json")
        for name in ["CSV", "XLSX"]
    ]
    responses = await asyncio.gather(
        *(client.put(f"/api/v1/adlc/intake/requests/{first['id']}", json=cmd) for cmd in commands)
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    latest = (await client.get(f"/api/v1/adlc/intake/requests/{first['id']}")).json()
    assert latest["revision"] == 2
    history = (await client.get(f"/api/v1/adlc/intake/requests/{first['id']}/history")).json()["items"]
    assert [h["revision"] for h in history] == [2, 1]


@pytest.mark.asyncio
async def test_http_cannot_forge_owner_or_cross_owner_boundary(database, http_client):
    _, _, _, other = database
    client, actor = http_client
    body = create_command().model_dump(mode="json")
    assert (
        await client.post("/api/v1/adlc/intake/requests", json={**body, "owner_id": str(other.id)})
    ).status_code == 422
    first = (await client.post("/api/v1/adlc/intake/requests", json=body)).json()["request"]
    actor["user"] = other
    for path in [f"/requests/{first['id']}", f"/requests/{first['id']}/history"]:
        assert (await client.get("/api/v1/adlc/intake" + path)).status_code == 404
    assert (await client.get("/api/v1/adlc/intake/requests")).json()["total"] == 0
    actor["user"] = None
    assert (await client.get("/api/v1/adlc/intake/requests")).status_code == 401


@pytest.mark.asyncio
async def test_disabled_intake_and_input_bounds(http_client, monkeypatch):
    client, _ = http_client
    body = create_command().model_dump(mode="json")
    body["content"]["title"] = " "
    assert (await client.post("/api/v1/adlc/intake/requests", json=body)).status_code == 422
    monkeypatch.setenv("POKEDEV_INTAKE_ENABLED", "false")
    assert (await client.get("/api/v1/adlc/intake/requests")).status_code == 404

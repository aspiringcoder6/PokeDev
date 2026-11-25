"""LI-02 ownership, pairing, transactional receipts and delivery races."""

import asyncio
import hashlib
import importlib.util
from datetime import timedelta
from pathlib import Path
from typing import get_args
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from pokedev_lark_contracts import DeliveryBatch, DeliveryResult, InboundMessage, IngestReceipt
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from test_requirement_intake import database as intake_database

from langflow.adlc import intake
from langflow.adlc import lark_intake as service
from langflow.api.utils import CurrentActiveUser, DbSession
from langflow.api.v1 import adlc_lark_intake as api
from langflow.services.authorization import team_access
from langflow.services.database.models.adlc_intake import AdlcIntakeRequest
from langflow.services.database.models.adlc_lark import AdlcLarkInbound, AdlcLarkLink, AdlcLarkOutbox
from langflow.services.database.models.adlc_workflow_run import AdlcWorkflowRun
from langflow.services.database.models.auth import AuthzRoleAssignment, AuthzRoleAssignmentGrant
from langflow.services.database.models.user.model import User

database = intake_database
CONFIG = service.Settings("app_test", "tenant_test", "s" * 48, "http://127.0.0.1:7862")


def message(name="new", **changes):
    return InboundMessage(
        app_id=CONFIG.app_id,
        tenant_key=CONFIG.tenant_key,
        event_id="event_" + name,
        message_id="om_" + name,
        chat_id="oc_test",
        open_id="ou_test",
        kind="text",
        text="Export monthly revenue",
        **changes,
    )


async def paired(session, owner):
    actor = intake.IntakeActor(owner.id)
    challenge = await service.start_link(session, actor, CONFIG, None, lambda hashed: hashed == "test-only")
    await session.commit()
    code = challenge["command"].split()[1]
    command = message("pair").model_copy(
        update={"kind": "pair", "text": None, "pair_digest": hashlib.sha256(code.encode()).hexdigest()}
    )
    result = await service.ingest(session, command, CONFIG)
    await session.commit()
    assert result.status == "LINKED"
    return actor, code, command


@pytest.mark.asyncio
async def test_pair_requires_password_and_failed_checks_survive_rollback(database):
    _, session, owner, _ = database
    actor = intake.IntakeActor(owner.id)
    for _ in range(5):
        with pytest.raises(intake.IntakeError, match="REAUTH_REQUIRED"):
            await service.start_link(session, actor, CONFIG, None, lambda hashed: False)
        await session.rollback()
    with pytest.raises(intake.IntakeError, match="RATE_LIMIT"):
        await service.start_link(session, actor, CONFIG, None, lambda hashed: True)
    row = await session.get(AdlcLarkLink, actor.id)
    assert row.password_failures == 5 and row.pair_digest is None


@pytest.mark.asyncio
async def test_pair_code_is_hashed_single_use_and_cannot_rebind_external_sender(database):
    _, session, owner, other = database
    actor, code, original = await paired(session, owner)
    row = await session.get(AdlcLarkLink, actor.id)
    assert row.pair_digest is None and row.open_id == "ou_test"
    replay = await service.ingest(session, original, CONFIG)
    assert replay.replayed
    reused = original.model_copy(update={"event_id": "event_reuse", "message_id": "om_reuse", "open_id": "ou_attacker"})
    assert (await service.ingest(session, reused, CONFIG)).status == "PAIR_REJECTED"
    await session.commit()
    for record in (await session.exec(select(AdlcLarkInbound))).all():
        assert code not in str(record.source)
    assert not (await service.link_status(session, intake.IntakeActor(other.id), CONFIG))["linked"]


@pytest.mark.asyncio
async def test_expired_pair_code_never_links(database):
    _, session, owner, _ = database
    actor = intake.IntakeActor(owner.id)
    challenge = await service.start_link(session, actor, CONFIG, None, lambda hashed: True)
    row = await session.get(AdlcLarkLink, actor.id)
    row.pair_expires_at = service.now() - timedelta(seconds=1)
    session.add(row)
    await session.commit()
    command = message().model_copy(
        update={
            "kind": "pair",
            "text": None,
            "pair_digest": hashlib.sha256(challenge["command"].split()[1].encode()).hexdigest(),
        }
    )
    assert (await service.ingest(session, command, CONFIG)).status == "PAIR_REJECTED"


@pytest.mark.asyncio
async def test_existing_external_identity_cannot_be_taken_over_by_another_account(database):
    _, session, owner, other = database
    await paired(session, owner)
    other_actor = intake.IntakeActor(other.id)
    challenge = await service.start_link(session, other_actor, CONFIG, None, lambda hashed: True)
    await session.commit()
    command = message("takeover").model_copy(
        update={
            "kind": "pair",
            "text": None,
            "pair_digest": hashlib.sha256(challenge["command"].split()[1].encode()).hexdigest(),
        }
    )
    assert (await service.ingest(session, command, CONFIG)).status == "PAIR_REJECTED"
    assert not (await service.link_status(session, other_actor, CONFIG))["linked"]


@pytest.mark.asyncio
async def test_revoked_project_membership_blocks_new_intake_and_pending_receipt(database):
    _, session, owner, _ = database
    project_id = await team_access.create_project(session, owner, "Lark pilot")
    await session.commit()
    actor, _, _ = await paired(session, owner)
    link = await session.get(AdlcLarkLink, actor.id)
    link.project_id = project_id
    session.add(link)
    await session.commit()
    assignment = (
        await session.exec(select(AuthzRoleAssignment).where(AuthzRoleAssignment.domain_id == project_id))
    ).one()
    await session.execute(
        sa.delete(AuthzRoleAssignmentGrant).where(AuthzRoleAssignmentGrant.assignment_id == assignment.id)
    )
    await session.delete(assignment)
    await session.commit()
    assert (await service.ingest(session, message(), CONFIG)).status == "DENIED"
    assert (await session.exec(select(AdlcIntakeRequest))).all() == []
    await service.claim(session, CONFIG)
    row = (await session.exec(select(AdlcLarkOutbox).where(AdlcLarkOutbox.owner_id == actor.id))).one()
    assert row.state == "BLOCKED"


@pytest.mark.asyncio
async def test_text_is_one_private_intake_with_atomic_source_and_outbox(database):
    _, session, owner, other = database
    actor, _, _ = await paired(session, owner)
    command = message()
    created = await service.ingest(session, command, CONFIG)
    await session.commit()
    assert created.status == "CREATED"
    assert (await service.ingest(session, command, CONFIG)).replayed
    assert (await service.ingest(session, command.model_copy(update={"event_id": "different_event"}), CONFIG)).replayed
    assert len((await session.exec(select(AdlcIntakeRequest))).all()) == 1
    assert len((await session.exec(select(AdlcLarkInbound))).all()) == 2  # pairing + requirement
    assert len((await session.exec(select(AdlcLarkOutbox))).all()) == 2
    assert (await intake.owned(session, actor, created.request_id)).content["description"] == command.text
    with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
        await intake.owned(session, intake.IntakeActor(other.id), created.request_id)
    assert (await session.exec(select(AdlcWorkflowRun))).all() == []
    with pytest.raises(intake.IntakeError, match="EVENT_CONFLICT"):
        await service.ingest(session, command.model_copy(update={"text": "Changed source"}), CONFIG)


@pytest.mark.asyncio
async def test_unlinked_and_wrong_tenant_never_create_requirements(database):
    _, session, _, _ = database
    assert (await service.ingest(session, message(), CONFIG)).status == "LINK_REQUIRED"
    with pytest.raises(intake.IntakeError, match="SOURCE_DENIED"):
        await service.ingest(session, message().model_copy(update={"tenant_key": "other"}), CONFIG)
    assert (await session.exec(select(AdlcIntakeRequest))).all() == []


@pytest.mark.asyncio
async def test_ingress_rollback_leaves_no_partial_requirement(database):
    _, session, owner, _ = database
    await paired(session, owner)
    await service.ingest(session, message(), CONFIG)
    await session.rollback()
    assert (await session.exec(select(AdlcIntakeRequest))).all() == []
    assert len((await session.exec(select(AdlcLarkInbound))).all()) == 1


@pytest.mark.asyncio
async def test_unlink_blocks_pending_private_deliveries(database):
    _, session, owner, _ = database
    actor, _, _ = await paired(session, owner)
    await service.ingest(session, message(), CONFIG)
    await service.unlink(session, actor, CONFIG, lambda hashed: True)
    await session.commit()
    assert not (await service.claim(session, CONFIG)).items
    assert all(row.state == "BLOCKED" for row in (await session.exec(select(AdlcLarkOutbox))).all())


@pytest.mark.asyncio
async def test_delivery_lease_expiry_never_requeues_unknown_send_and_receipt_is_idempotent(database):
    _, session, owner, _ = database
    await paired(session, owner)
    delivery = (await service.claim(session, CONFIG)).items[0]
    await session.commit()
    await session.execute(
        sa.update(AdlcLarkOutbox)
        .where(AdlcLarkOutbox.id == delivery.id)
        .values(leased_at=service.now() - timedelta(minutes=2))
    )
    await session.commit()
    assert not (await service.claim(session, CONFIG)).items
    await session.commit()
    assert (await session.get(AdlcLarkOutbox, delivery.id, populate_existing=True)).state == "UNCONFIRMED"
    receipt = DeliveryResult(lease_id=delivery.lease_id, state="DELIVERED", provider_message_id="om_receipt")
    assert (await service.delivery_result(session, CONFIG, delivery.id, receipt))["state"] == "DELIVERED"
    await session.commit()
    assert (await service.delivery_result(session, CONFIG, delivery.id, receipt))["replayed"]
    with pytest.raises(intake.IntakeError, match="RESULT_CONFLICT"):
        await service.delivery_result(
            session, CONFIG, delivery.id, receipt.model_copy(update={"provider_message_id": "om_other"})
        )


@pytest_asyncio.fixture
async def client(database, monkeypatch):
    engine, _, owner, _ = database
    actor_id = owner.id
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")

    async def db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def user(session: DbSession):
        return await session.get(User, actor_id)

    app.dependency_overrides[get_args(DbSession)[1].dependency] = db
    app.dependency_overrides[get_args(CurrentActiveUser)[1].dependency] = user
    monkeypatch.setenv("POKEDEV_INTAKE_ENABLED", "true")
    monkeypatch.setenv("POKEDEV_LARK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("POKEDEV_LARK_APP_ID", CONFIG.app_id)
    monkeypatch.setenv("POKEDEV_LARK_TENANT_KEY", CONFIG.tenant_key)
    monkeypatch.setenv("POKEDEV_LARK_CONNECTOR_SECRET", CONFIG.secret)
    monkeypatch.setattr(api, "verify_password", lambda plain, hashed: plain == "correct-password")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as connection:
        yield connection


AUTH = {"Authorization": "Bearer " + CONFIG.secret}
BASE = "/api/v1/adlc/intake/lark"


@pytest.mark.asyncio
async def test_http_concurrent_ingress_creates_one_intake(database, client):
    _, session, owner, _ = database
    await paired(session, owner)
    responses = await asyncio.gather(
        *(client.post(BASE + "/events", json=message().model_dump(mode="json"), headers=AUTH) for _ in range(2))
    )
    assert [r.status_code for r in responses] == [200, 200]
    parsed = [IngestReceipt.model_validate(r.json()) for r in responses]
    assert {r.replayed for r in parsed} == {True, False}
    assert len({r.request_id for r in parsed}) == 1
    assert len((await session.exec(select(AdlcIntakeRequest))).all()) == 1


@pytest.mark.asyncio
async def test_http_auth_ownership_and_contract_boundaries(client):
    body = message().model_dump(mode="json")
    assert (await client.post(BASE + "/events", json=body)).status_code == 401
    assert (
        await client.post(BASE + "/events", json={**body, "owner_id": str(uuid4())}, headers=AUTH)
    ).status_code == 422
    assert (await client.post(BASE + "/link", json={"password": "wrong"})).status_code == 403
    started = await client.post(BASE + "/link", json={"password": "correct-password"})
    assert started.status_code == 200 and started.headers["cache-control"] == "no-store"
    code = started.json()["command"].split()[1]
    paired_message = message("link-http").model_copy(
        update={"kind": "pair", "text": None, "pair_digest": hashlib.sha256(code.encode()).hexdigest()}
    )
    response = await client.post(BASE + "/events", json=paired_message.model_dump(mode="json"), headers=AUTH)
    assert response.json()["status"] == "LINKED"
    assert (await client.get(BASE + "/link")).json()["linked"]
    deliveries = await client.post(BASE + "/deliveries/claim", headers=AUTH)
    assert len(DeliveryBatch.model_validate(deliveries.json()).items) == 1


@pytest.mark.asyncio
async def test_http_concurrent_claims_have_one_winner_and_conflicting_receipts_cannot_overwrite(database, client):
    _, session, owner, _ = database
    await paired(session, owner)
    claims = await asyncio.gather(*(client.post(BASE + "/deliveries/claim", headers=AUTH) for _ in range(2)))
    deliveries = [d for response in claims for d in DeliveryBatch.model_validate(response.json()).items]
    assert len(deliveries) == 1
    delivery = deliveries[0]
    results = [
        DeliveryResult(lease_id=delivery.lease_id, state="DELIVERED", provider_message_id=name)
        for name in ("om_first", "om_second")
    ]
    responses = await asyncio.gather(
        *(
            client.post(BASE + f"/deliveries/{delivery.id}/result", headers=AUTH, json=result.model_dump(mode="json"))
            for result in results
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 409]


@pytest.mark.parametrize("precreated", [False, True])
def test_lark_migration_matches_schema(precreated):
    path = Path(__file__).resolve().parents[3] / "langflow/alembic/versions/li02a2b3c4d5_add_lark_intake.py"
    spec = importlib.util.spec_from_file_location("lark_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        if precreated:
            SQLModel.metadata.create_all(connection)
        else:
            SQLModel.metadata.create_all(
                connection, tables=[User.__table__, SQLModel.metadata.tables["folder"], AdlcIntakeRequest.__table__]
            )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert all(migration._compatible(connection, table) for table in migration.tables())
    engine.dispose()

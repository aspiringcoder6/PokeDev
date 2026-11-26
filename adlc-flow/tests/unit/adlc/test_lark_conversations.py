"""LI03-01..07: native routing, privacy, transport compatibility and migrations."""

import asyncio
import hashlib
import importlib.util
from dataclasses import replace
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
from pokedev_lark_contracts import DeliveryResult, InboundMessage, v2
from sqlmodel import Session, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession
from test_lark_intake import paired
from test_requirement_intake import database as intake_database

from langflow.adlc import intake
from langflow.adlc import lark_conversations as conversations
from langflow.adlc import lark_intake as identity
from langflow.adlc.intake_models import CancelIntake, CreateIntake, IntakeContent
from langflow.api.utils import CurrentActiveUser, DbSession
from langflow.api.v1 import adlc_lark_intake as api
from langflow.services.authorization import team_access
from langflow.services.database.models.adlc_intake import AdlcIntakeRequest
from langflow.services.database.models.adlc_lark import AdlcLarkInbound, AdlcLarkLink, AdlcLarkOutbox
from langflow.services.database.models.adlc_lark_conversation import (
    AdlcLarkConversation,
    AdlcLarkDeliveryRoute,
    AdlcLarkMessageAlias,
)
from langflow.services.database.models.adlc_workflow_run import AdlcWorkflowRun
from langflow.services.database.models.auth import AuthzRoleAssignment, AuthzRoleAssignmentGrant
from langflow.services.database.models.user.model import User

database = intake_database
CONFIG = identity.Settings(
    "app_test", "tenant_test", "s" * 48, "http://127.0.0.1:7862", True, "ou_bot", {"oc_group": v2.GroupPolicy()}
)
BASE = "/api/v1/adlc/intake/lark"
AUTH = {"Authorization": "Bearer " + CONFIG.secret}


def message(name="root", **changes):
    return v2.InboundMessage.model_validate(
        {
            "app_id": CONFIG.app_id,
            "tenant_key": CONFIG.tenant_key,
            "event_id": "event_" + name,
            "message_id": "om_" + name,
            "chat_id": "oc_group",
            "chat_type": "group",
            "open_id": "ou_test",
            "mentioned_open_ids": ["ou_bot"],
            "kind": "text",
            "text": "Export monthly revenue",
            **changes,
        }
    )


async def receive(session, command, config=CONFIG):
    receipt = await conversations.ingest(session, command, config)
    await session.commit()
    return receipt


async def settle(session, config=CONFIG):
    receipts = {}
    for _ in range(100):
        batch = await identity.claim(session, config, version=2)
        await session.commit()
        if not batch.items:
            # A claim can consume one revoked row as BLOCKED without returning
            # a delivery. The live worker polls again; model that drain here.
            pending = (await session.exec(select(AdlcLarkOutbox).where(AdlcLarkOutbox.state == "PENDING"))).first()
            if pending is None:
                return receipts
            continue
        for delivery in batch.items:
            provider = "om_bot_" + delivery.id.hex
            await identity.delivery_result(
                session,
                config,
                delivery.id,
                DeliveryResult(lease_id=delivery.lease_id, state="DELIVERED", provider_message_id=provider),
            )
            await session.commit()
            receipts[delivery.reply_to] = provider
    raise AssertionError("Fixture deliveries did not settle after bounded polling")


@pytest.mark.asyncio
async def test_two_threads_and_replies_to_bot_receipts_never_mix_or_edit_briefs(database):
    _, session, owner, _ = database
    await paired(session, owner)
    first = await receive(session, message("alpha", text="Alpha original"))
    second = await receive(session, message("beta", text="Beta original"))
    acks = await settle(session)
    assert first.request_id != second.request_id
    reply = message(
        "reply", parent_id=acks["om_alpha"], root_id="om_alpha", thread_id="omt_alpha", text="Alpha supplementary"
    )
    assert (await receive(session, reply)).request_id == first.request_id
    assert (
        await receive(
            session, message("beta_reply", parent_id="om_beta", thread_id="omt_beta", text="Beta supplementary")
        )
    ).request_id == second.request_id
    alpha = await conversations.history(session, owner, first.request_id)
    beta = await conversations.history(session, owner, second.request_id)
    assert [item.text for item in alpha.items] == ["Alpha original", "Alpha supplementary"]
    assert [item.text for item in beta.items] == ["Beta original", "Beta supplementary"]
    current = await intake.owned(session, owner, first.request_id)
    assert current.revision == 1 and current.content["description"] == "Alpha original"
    assert alpha.items[-1].parent_id == acks["om_alpha"] and alpha.items[-1].thread_id == "omt_alpha"
    assert not (await session.exec(select(AdlcWorkflowRun))).all()


@pytest.mark.asyncio
async def test_conflicting_unknown_and_cross_chat_anchors_require_explicit_target(database):
    _, session, owner, _ = database
    await paired(session, owner)
    first = await receive(session, message("first"))
    second = await receive(session, message("second"))
    for name, fields in [
        ("conflict", {"parent_id": "om_first", "root_id": "om_second"}),
        ("unknown", {"parent_id": "om_unknown"}),
        ("foreign_chat", {"chat_id": "oc_dm", "chat_type": "p2p", "parent_id": "om_first"}),
        ("unknown_thread", {"thread_id": "omt_unknown"}),
    ]:
        result = await receive(session, message(name, **fields))
        assert result.status == "TARGET_REQUIRED" and result.request_id is None
    chosen = await receive(
        session,
        message(
            "chosen",
            parent_id="om_first",
            root_id="om_second",
            text=f"/intake {first.request_id} explicit supplementary",
        ),
    )
    assert chosen.status == "APPENDED" and chosen.request_id == first.request_id
    assert (await conversations.history(session, owner, second.request_id)).total == 1


@pytest.mark.asyncio
async def test_explicit_link_from_web_checks_owner_and_group_project(database):
    _, session, owner, other = database
    await paired(session, owner)
    owned = await intake.create(
        session,
        owner,
        CreateIntake(command_id=uuid4(), content=IntakeContent(title="Web", description="PRIVATE_SENTINEL")),
    )
    foreign = await intake.create(
        session,
        other,
        CreateIntake(command_id=uuid4(), content=IntakeContent(title="Other", description="FOREIGN_SENTINEL")),
    )
    await session.commit()
    accepted = await receive(session, message("select_web", text=f"/intake {owned['request']['id']} new public source"))
    assert accepted.status == "APPENDED"
    denied = await receive(session, message("select_foreign", text=f"/intake {foreign['request']['id']} steal"))
    assert denied.status == "DENIED" and denied.request_id is None
    for row in (await session.exec(select(AdlcLarkOutbox))).all():
        assert "PRIVATE_SENTINEL" not in row.text and "FOREIGN_SENTINEL" not in row.text and "Web" not in row.text
    project = await team_access.create_project(session, owner, "Group project")
    await session.commit()
    configured = replace(CONFIG, groups={"oc_group": v2.GroupPolicy(project_id=project)})
    assert (
        await receive(session, message("wrong_project", text=f"/intake {owned['request']['id']} text"), configured)
    ).status == "DENIED"


@pytest.mark.asyncio
async def test_other_linked_actor_cannot_append_to_private_group_request(database):
    _, session, owner, other = database
    await paired(session, owner)
    first = await receive(session, message())
    challenge = await identity.start_link(session, other, CONFIG, None, lambda _: True)
    await session.commit()
    await identity.ingest(
        session,
        InboundMessage(
            app_id=CONFIG.app_id,
            tenant_key=CONFIG.tenant_key,
            event_id="event_other_link",
            message_id="om_other_link",
            chat_id="oc_other_dm",
            open_id="ou_other",
            kind="pair",
            pair_digest=hashlib.sha256(challenge["command"].split()[1].encode()).hexdigest(),
        ),
        CONFIG,
    )
    await session.commit()
    assert (await receive(session, message("other_reply", parent_id="om_root", open_id="ou_other"))).status == "DENIED"
    assert (await conversations.history(session, owner, first.request_id)).total == 1
    with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
        await conversations.history(session, other, first.request_id)


@pytest.mark.asyncio
async def test_group_allowlist_mentions_capability_and_probe_are_independent(database):
    _, session, owner, _ = database
    await paired(session, owner)
    for name, body in [
        ("unconfigured", {"chat_id": "oc_unconfigured"}),
        ("other_mention", {"mentioned_open_ids": ["ou_someone"]}),
        ("probe", {"kind": "unsupported", "text": None, "discovery": True}),
    ]:
        assert (await receive(session, message(name, **body))).status == "IGNORED"
    root = await receive(session, message())
    unmentioned = message("no_at", parent_id="om_root", mentioned_open_ids=[])
    assert (await receive(session, unmentioned)).status == "IGNORED"
    verified = replace(CONFIG, groups={"oc_group": v2.GroupPolicy(unmentioned_replies_verified=True)})
    accepted = await receive(session, message("verified", parent_id="om_root", mentioned_open_ids=[]), verified)
    assert accepted.status == "APPENDED" and accepted.request_id == root.request_id
    for name, fields in [
        ("unmentioned_root", {}),
        ("unmentioned_native_root", {"root_id": "om_unmentioned_native_root", "thread_id": "omt_untracked"}),
        ("unmentioned_unknown_parent", {"parent_id": "om_untracked"}),
        ("unmentioned_unknown_thread", {"thread_id": "omt_untracked"}),
    ]:
        assert (await receive(session, message(name, mentioned_open_ids=[], **fields), verified)).status == "IGNORED"
    assert len((await session.exec(select(AdlcIntakeRequest))).all()) == 1
    group_deliveries = (await session.exec(select(AdlcLarkOutbox).where(AdlcLarkOutbox.chat_id == "oc_group"))).all()
    assert len(group_deliveries) == 2
    assert {row.reply_to for row in group_deliveries} == {"om_root", "om_verified"}


@pytest.mark.asyncio
async def test_unknown_thread_new_is_explicit_and_dm_roots_remain_independent(database):
    _, session, owner, _ = database
    await paired(session, owner)
    one = await receive(session, message("dm_one", chat_type="p2p", chat_id="oc_dm"))
    two = await receive(session, message("dm_two", chat_type="p2p", chat_id="oc_dm"))
    assert one.request_id != two.request_id
    appended = await receive(session, message("dm_reply", chat_type="p2p", chat_id="oc_dm", parent_id="om_dm_one"))
    assert appended.request_id == one.request_id
    fresh = await receive(
        session,
        message("new_explicit", parent_id="om_untracked", thread_id="omt_new", text="/new An independent request"),
    )
    assert fresh.status == "CREATED"
    assert (await intake.owned(session, owner, fresh.request_id)).content["description"] == "An independent request"


@pytest.mark.asyncio
async def test_dedupe_and_rollback_do_not_leave_partial_conversation_state(database):
    _, session, owner, _ = database
    await paired(session, owner)
    first = await receive(session, message())
    replay = await receive(session, message(event_id="event_retry"))
    assert replay.replayed and replay.request_id == first.request_id
    with pytest.raises(intake.IntakeError, match="EVENT_CONFLICT"):
        await conversations.ingest(session, message(text="Changed event body"), CONFIG)
    await session.rollback()
    await conversations.ingest(session, message("rolled_back"), CONFIG)
    await session.rollback()
    assert len((await session.exec(select(AdlcIntakeRequest))).all()) == 1
    assert len((await session.exec(select(AdlcLarkConversation))).all()) == 1
    assert len((await session.exec(select(AdlcLarkMessageAlias))).all()) == 1


@pytest.mark.asyncio
async def test_revocation_closed_intake_and_group_removal_block_replies_and_pending_deliveries(database):
    _, session, owner, _ = database
    await paired(session, owner)
    root = await receive(session, message())
    await intake.change(session, owner, root.request_id, CancelIntake(command_id=uuid4(), expected_revision=1))
    await session.commit()
    assert (await receive(session, message("closed", parent_id="om_root"))).status == "DENIED"
    await settle(session)
    route = (
        await session.exec(
            select(AdlcLarkDeliveryRoute)
            .join(AdlcLarkOutbox, AdlcLarkOutbox.id == AdlcLarkDeliveryRoute.delivery_id)
            .where(AdlcLarkDeliveryRoute.conversation_id.is_not(None))
        )
    ).one()
    assert (await session.get(AdlcLarkOutbox, route.delivery_id)).state == "BLOCKED"
    second = await receive(session, message("second"))
    await settle(session, replace(CONFIG, groups={}))
    assert (await conversations.history(session, owner, second.request_id)).total == 1
    link = await session.get(AdlcLarkLink, owner.id)
    link.revision += 1
    session.add(link)
    await session.commit()
    assert (await receive(session, message("revoked", parent_id="om_second"))).status == "DENIED"


@pytest.mark.asyncio
async def test_project_revocation_applies_to_new_group_ingress_and_private_history(database):
    _, session, owner, _ = database
    await paired(session, owner)
    project = await team_access.create_project(session, owner, "Scoped group")
    await session.commit()
    config = replace(CONFIG, groups={"oc_group": v2.GroupPolicy(project_id=project)})
    root = await receive(session, message(), config)
    assignment = (await session.exec(select(AuthzRoleAssignment).where(AuthzRoleAssignment.domain_id == project))).one()
    await session.execute(
        sa.delete(AuthzRoleAssignmentGrant).where(AuthzRoleAssignmentGrant.assignment_id == assignment.id)
    )
    await session.delete(assignment)
    await session.commit()
    assert (await receive(session, message("after_revoke", parent_id="om_root"), config)).status == "DENIED"
    with pytest.raises(intake.IntakeError, match="NOT_FOUND"):
        await conversations.history(session, owner, root.request_id)


@pytest.mark.asyncio
async def test_pair_code_in_group_is_invalidated_without_linking(database):
    _, session, owner, _ = database
    challenge = await identity.start_link(session, owner, CONFIG, None, lambda _: True)
    await session.commit()
    result = await receive(
        session,
        message(
            kind="pair", text=None, pair_digest=hashlib.sha256(challenge["command"].split()[1].encode()).hexdigest()
        ),
    )
    assert result.status == "PAIR_REJECTED"
    link = await session.get(AdlcLarkLink, owner.id)
    assert link.open_id is None and link.pair_digest is None


@pytest.mark.asyncio
async def test_v1_client_never_claims_v2_routes_and_old_dm_receipts_gain_aliases(database):
    _, session, owner, _ = database
    await paired(session, owner)
    await settle(session)
    await receive(session, message())
    assert not (await identity.claim(session, CONFIG)).items
    legacy = InboundMessage(
        app_id=CONFIG.app_id,
        tenant_key=CONFIG.tenant_key,
        event_id="event_old",
        message_id="om_old",
        chat_id="oc_dm",
        open_id="ou_test",
        kind="text",
        text="Old DM",
    )
    created = await identity.ingest(session, legacy, CONFIG)
    await session.commit()
    old = (await identity.claim(session, CONFIG)).items[0]
    result = DeliveryResult(lease_id=old.lease_id, state="DELIVERED", provider_message_id="om_old_ack")
    await identity.delivery_result(session, CONFIG, old.id, result)
    await session.commit()
    assert (await identity.delivery_result(session, CONFIG, old.id, result))["replayed"]
    appended = await receive(session, message("reply_old", chat_type="p2p", chat_id="oc_dm", parent_id="om_old_ack"))
    assert appended.request_id == created.request_id and appended.status == "APPENDED"
    duplicate = v2.InboundMessage.model_validate({**legacy.model_dump(mode="json"), "version": "2", "chat_type": "p2p"})
    assert (await receive(session, duplicate)).replayed


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
    monkeypatch.setattr(identity, "settings", lambda: CONFIG)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as connection:
        yield connection


@pytest.mark.asyncio
@pytest.mark.parametrize("event,message_id", [("event_alpha", "om_beta"), ("event_beta", "om_alpha")])
async def test_event_and_message_identity_collision_never_joins_two_requests(database, event, message_id):
    _, session, owner, _ = database
    await paired(session, owner)
    await receive(session, message("alpha"))
    await receive(session, message("beta"))
    with pytest.raises(intake.IntakeError, match="EVENT_CONFLICT"):
        await conversations.ingest(session, message("collision", event_id=event, message_id=message_id), CONFIG)


@pytest.mark.asyncio
async def test_inactive_owner_cannot_append_and_pending_receipt_is_blocked(database):
    _, session, owner, _ = database
    await paired(session, owner)
    await receive(session, message())
    owner.is_active = False
    session.add(owner)
    await session.commit()
    assert (await receive(session, message("inactive", parent_id="om_root"))).status == "DENIED"
    await settle(session)
    rows = (
        await session.exec(
            select(AdlcLarkOutbox)
            .join(AdlcLarkDeliveryRoute, AdlcLarkDeliveryRoute.delivery_id == AdlcLarkOutbox.id)
            .where(AdlcLarkDeliveryRoute.conversation_id.is_not(None))
        )
    ).all()
    assert rows and all(row.state == "BLOCKED" for row in rows)


@pytest.mark.parametrize(
    "groups", ["[]", '{"oc_group":{"unmentioned_replies_verified":"true"}}', '{"oc_group":{"owner_id":"untrusted"}}']
)
def test_group_configuration_rejects_ambiguous_or_caller_granted_authority(monkeypatch, groups):
    for key, value in {
        "POKEDEV_INTAKE_ENABLED": "true",
        "POKEDEV_LARK_INTAKE_ENABLED": "true",
        "POKEDEV_LARK_APP_ID": CONFIG.app_id,
        "POKEDEV_LARK_TENANT_KEY": CONFIG.tenant_key,
        "POKEDEV_LARK_CONNECTOR_SECRET": CONFIG.secret,
        "POKEDEV_LARK_CONVERSATIONS_ENABLED": "true",
        "POKEDEV_LARK_GROUPS_ENABLED": "true",
        "POKEDEV_LARK_BOT_OPEN_ID": "ou_bot",
        "POKEDEV_LARK_GROUPS_JSON": groups,
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(intake.IntakeError, match="GROUP_CONFIGURATION_REQUIRED"):
        identity.settings()


@pytest.mark.asyncio
async def test_http_duplicate_and_parallel_reply_ingress_keep_both_sources(database, client):
    _, session, owner, _ = database
    await paired(session, owner)
    responses = await asyncio.gather(
        *(client.post(BASE + "/v2/events", json=message().model_dump(mode="json"), headers=AUTH) for _ in range(2))
    )
    assert [item.status_code for item in responses] == [200, 200]
    parsed = [v2.IngestReceipt.model_validate(item.json()) for item in responses]
    assert {item.replayed for item in parsed} == {True, False}
    identity = parsed[0].request_id
    replies = await asyncio.gather(
        *(
            client.post(
                BASE + "/v2/events",
                json=message("reply_" + name, parent_id="om_root", text="Supplement " + name).model_dump(mode="json"),
                headers=AUTH,
            )
            for name in ("one", "two")
        )
    )
    assert [item.status_code for item in replies] == [200, 200]
    page = await client.get(BASE + f"/requests/{identity}/conversation")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    parsed_page = v2.ConversationPage.model_validate(page.json())
    assert parsed_page.total == 3 and {item.text for item in parsed_page.items} == {
        "Export monthly revenue",
        "Supplement one",
        "Supplement two",
    }


@pytest.mark.asyncio
async def test_http_v2_contract_auth_and_native_owner_boundary(database, client):
    _, session, owner, other = database
    await paired(session, owner)
    payload = message().model_dump(mode="json")
    assert (await client.post(BASE + "/v2/events", json=payload)).status_code == 401
    assert (
        await client.post(BASE + "/v2/events", json={**payload, "owner_id": str(other.id)}, headers=AUTH)
    ).status_code == 422
    foreign = await intake.create(
        session, other, CreateIntake(command_id=uuid4(), content=IntakeContent(title="Other", description="Private"))
    )
    await session.commit()
    assert (await client.get(BASE + f"/requests/{foreign['request']['id']}/conversation")).status_code == 404
    root = await receive(session, message())
    assert (
        await client.get(BASE + f"/requests/{root.request_id}/conversation", params={"offset": -1})
    ).status_code == 422


@pytest.mark.parametrize("precreated", [False, True])
def test_migration_adopts_and_backfills_legacy_dm_and_bot_alias_without_changing_receipts(precreated):
    path = Path(__file__).resolve().parents[3] / "langflow/alembic/versions/li03a2b3c4d5_add_lark_conversations.py"
    spec = importlib.util.spec_from_file_location("conversation_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    new_tables = [AdlcLarkConversation.__table__, AdlcLarkMessageAlias.__table__, AdlcLarkDeliveryRoute.__table__]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        SQLModel.metadata.create_all(
            connection,
            tables=[table for table in SQLModel.metadata.sorted_tables if precreated or table not in new_tables],
        )
        with Session(connection) as session:
            owner = User(username="migration-pilot", password="test", is_active=True)
            session.add(owner)
            session.flush()
            request = AdlcIntakeRequest(
                owner_id=owner.id, content={"description": "Old preserved"}, content_digest="original"
            )
            session.add(request)
            session.flush()
            inbound = AdlcLarkInbound(
                app_id=CONFIG.app_id,
                tenant_key=CONFIG.tenant_key,
                event_id="event_legacy",
                message_id="om_legacy",
                content_digest="old_fingerprint",
                source={
                    "version": "1",
                    "app_id": CONFIG.app_id,
                    "tenant_key": CONFIG.tenant_key,
                    "chat_id": "oc_legacy",
                    "message_id": "om_legacy",
                    "text": "Old preserved",
                },
                result={"status": "CREATED", "request_id": str(request.id)},
                request_id=request.id,
            )
            session.add(inbound)
            session.flush()
            outbox = AdlcLarkOutbox(
                inbound_id=inbound.id,
                owner_id=owner.id,
                link_revision=2,
                chat_id="oc_legacy",
                reply_to="om_legacy",
                text="Old receipt",
                state="DELIVERED",
                provider_message_id="om_legacy_bot",
                result_digest="unchanged",
            )
            session.add(outbox)
            session.flush()
            session.commit()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert all(migration._compatible(connection, table) for table in migration.tables())
        assert connection.scalar(sa.select(sa.func.count()).select_from(AdlcLarkConversation.__table__)) == 1
        assert set(connection.scalars(sa.select(AdlcLarkMessageAlias.__table__.c.message_id))) == {
            "om_legacy",
            "om_legacy_bot",
        }
        assert connection.scalar(sa.select(AdlcLarkOutbox.__table__.c.result_digest)) == "unchanged"
        assert connection.scalar(sa.select(AdlcIntakeRequest.__table__.c.content))["description"] == "Old preserved"
    engine.dispose()

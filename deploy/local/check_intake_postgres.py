"""Opt-in PostgreSQL intake check; its entire private schema is rolled back."""

import asyncio
import hashlib
import importlib.util
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langflow.adlc import intake
from langflow.adlc import lark_conversations as conversations
from langflow.adlc import lark_intake as lark
from langflow.adlc.intake_models import CreateIntake, IntakeContent, UpdateIntake
from langflow.services.database.models.adlc_lark_conversation import (
    AdlcLarkConversation,
    AdlcLarkDeliveryRoute,
    AdlcLarkMessageAlias,
)
from langflow.services.database.models.user.model import User
from pokedev_lark_contracts import DeliveryResult, InboundMessage, v2
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


async def check():
    url = os.environ.get("LANGFLOW_DATABASE_URL", "")
    if os.getenv("POKEDEV_TEST_POSTGRES") != "1" or not url.startswith("postgresql"):
        raise RuntimeError(
            "Run explicitly in the app test container with POKEDEV_TEST_POSTGRES=1"
        )
    path = Path(
        "/app/adlc-flow/langflow/alembic/versions/li01a2b3c4d5_add_requirement_intake.py"
    )
    spec = importlib.util.spec_from_file_location("intake_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    next_spec = importlib.util.spec_from_file_location(
        "lark_migration", path.with_name("li02a2b3c4d5_add_lark_intake.py")
    )
    lark_migration = importlib.util.module_from_spec(next_spec)
    next_spec.loader.exec_module(lark_migration)
    conversation_spec = importlib.util.spec_from_file_location(
        "conversation_migration",
        path.with_name("li03a2b3c4d5_add_lark_conversations.py"),
    )
    conversation_migration = importlib.util.module_from_spec(conversation_spec)
    conversation_spec.loader.exec_module(conversation_migration)
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            schema = "pokedev_intake_" + uuid4().hex
            await connection.execute(sa.schema.CreateSchema(schema))
            await connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            await connection.run_sync(SQLModel.metadata.create_all)

            def adopt(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
                    lark_migration.upgrade()
                    conversation_migration.upgrade()
                assert all(
                    migration._compatible(sync, table) for table in migration.tables()
                )
                assert all(
                    lark_migration._compatible(sync, table)
                    for table in lark_migration.tables()
                )
                assert all(
                    conversation_migration._compatible(sync, table)
                    for table in conversation_migration.tables()
                )

            await connection.run_sync(adopt)
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                owner = User(
                    username="intake-pg-test", password="test-only", is_active=True
                )
                session.add(owner)
                await session.commit()
                command = CreateIntake(
                    command_id=uuid4(),
                    content=IntakeContent(
                        title="PG regression", description="Temporary schema only"
                    ),
                )
                first = await intake.create(session, owner, command)
                await session.commit()
                assert (await intake.create(session, owner, command))["replayed"]
                identity = UUID(first["request"]["id"])
                updated = await intake.change(
                    session,
                    owner,
                    identity,
                    UpdateIntake(
                        command_id=uuid4(),
                        expected_revision=1,
                        content=IntakeContent(
                            title="PG regression revised", description="Confirmed scope"
                        ),
                    ),
                )
                await session.commit()
                assert updated["request"]["revision"] == 2
                assert (
                    len((await intake.history(session, owner, identity))["items"]) == 2
                )
                assert (await intake.listing(session, owner))["total"] == 1
                config = lark.Settings(
                    "app_test", "tenant_test", "s" * 48, "http://127.0.0.1:7862"
                )
                actor = intake.IntakeActor(owner.id)
                challenge = await lark.start_link(
                    session, actor, config, None, lambda hashed: hashed == "test-only"
                )
                await session.commit()
                pair = InboundMessage(
                    app_id=config.app_id,
                    tenant_key=config.tenant_key,
                    event_id="ev_pair",
                    message_id="om_pair",
                    chat_id="oc_test",
                    open_id="ou_test",
                    kind="pair",
                    pair_digest=hashlib.sha256(
                        challenge["command"].split()[1].encode()
                    ).hexdigest(),
                )
                assert (await lark.ingest(session, pair, config)).status == "LINKED"
                await session.commit()
                dm = InboundMessage(
                    app_id=config.app_id,
                    tenant_key=config.tenant_key,
                    event_id="ev_dm",
                    message_id="om_dm",
                    chat_id="oc_test",
                    open_id="ou_test",
                    kind="text",
                    text="PG requirement",
                )
                first = await lark.ingest(session, dm, config)
                await session.commit()
                assert (
                    first.status == "CREATED"
                    and (await lark.ingest(session, dm, config)).replayed
                )
                claimed = (await lark.claim(session, config)).items[0]
                await session.commit()
                result = DeliveryResult(
                    lease_id=claimed.lease_id,
                    state="DELIVERED",
                    provider_message_id="om_reply",
                )
                assert (
                    await lark.delivery_result(session, config, claimed.id, result)
                )["state"] == "DELIVERED"
                await session.commit()
                assert (
                    await lark.delivery_result(session, config, claimed.id, result)
                )["replayed"]
                # Finish the remaining legacy DM receipt, then exercise the
                # frozen migration's backfill only inside this disposable schema.
                dm_delivery = (await lark.claim(session, config)).items[0]
                await session.commit()
                await lark.delivery_result(
                    session,
                    config,
                    dm_delivery.id,
                    DeliveryResult(
                        lease_id=dm_delivery.lease_id,
                        state="DELIVERED",
                        provider_message_id="om_pg_dm_ack",
                    ),
                )
                await session.commit()
                for model in (
                    AdlcLarkDeliveryRoute,
                    AdlcLarkMessageAlias,
                    AdlcLarkConversation,
                ):
                    await session.execute(sa.delete(model))
                await session.commit()
                await connection.run_sync(conversation_migration.backfill)
                native_config = replace(
                    config,
                    conversations_enabled=True,
                    bot_open_id="ou_bot",
                    groups={"oc_group": v2.GroupPolicy()},
                )
                reply = v2.InboundMessage.model_validate(
                    {
                        **dm.model_dump(mode="json"),
                        "version": "2",
                        "event_id": "ev_dm_reply",
                        "message_id": "om_dm_reply",
                        "parent_id": "om_pg_dm_ack",
                        "text": "Additional DM source",
                    }
                )
                appended = await conversations.ingest(session, reply, native_config)
                await session.commit()
                assert (
                    appended.status == "APPENDED"
                    and appended.request_id == first.request_id
                )
                assert (
                    await conversations.history(session, actor, first.request_id)
                ).total == 2
                roots = []
                for suffix in ("alpha", "beta"):
                    root = v2.InboundMessage(
                        app_id=config.app_id,
                        tenant_key=config.tenant_key,
                        event_id="ev_group_" + suffix,
                        message_id="om_group_" + suffix,
                        chat_id="oc_group",
                        chat_type="group",
                        open_id="ou_test",
                        mentioned_open_ids=["ou_bot"],
                        kind="text",
                        text="Group root " + suffix,
                    )
                    created = await conversations.ingest(session, root, native_config)
                    await session.commit()
                    roots.append(created)
                assert roots[0].request_id != roots[1].request_id
                group_reply = root.model_copy(
                    update={
                        "event_id": "ev_group_reply",
                        "message_id": "om_group_reply",
                        "parent_id": "om_group_alpha",
                        "root_id": "om_group_alpha",
                        "thread_id": "omt_alpha",
                        "text": "Alpha source",
                    }
                )
                routed = await conversations.ingest(session, group_reply, native_config)
                await session.commit()
                assert routed.request_id == roots[0].request_id
                assert (
                    await conversations.ingest(session, group_reply, native_config)
                ).replayed
                page = await conversations.history(session, actor, roots[0].request_id)
                assert [item.text for item in page.items] == [
                    "Group root alpha",
                    "Alpha source",
                ]
                while True:
                    batch = await lark.claim(session, native_config, version=2)
                    await session.commit()
                    if not batch.items:
                        break
                    for delivery in batch.items:
                        assert delivery.version == "2"
                        if delivery.chat_id == "oc_group":
                            assert delivery.reply_in_thread
                        await lark.delivery_result(
                            session,
                            native_config,
                            delivery.id,
                            DeliveryResult(
                                lease_id=delivery.lease_id,
                                state="DELIVERED",
                                provider_message_id="om_pg_ack_" + delivery.id.hex,
                            ),
                        )
                        await session.commit()
                print(
                    "POSTGRES_INTAKE_AND_LARK_CONVERSATIONS_OK: migrations, legacy backfill, scoped threads, DM replies, dedupe, outbox and receipts"
                )
        finally:
            await transaction.rollback()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

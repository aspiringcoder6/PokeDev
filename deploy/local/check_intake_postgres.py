"""Opt-in PostgreSQL intake check; its entire private schema is rolled back."""

import asyncio
import importlib.util
import os
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from langflow.adlc import intake
from langflow.adlc.intake_models import CreateIntake, IntakeContent, UpdateIntake
from langflow.services.database.models.user.model import User
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
                assert all(
                    migration._compatible(sync, table) for table in migration.tables()
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
                print(
                    "POSTGRES_INTAKE_OK: migration adoption, create, replay, update, history, listing"
                )
        finally:
            await transaction.rollback()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check())

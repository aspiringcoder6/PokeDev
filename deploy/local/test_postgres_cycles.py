"""Opt-in PostgreSQL regression checks; every test rolls back its private schema."""
import importlib.util
import os
from pathlib import Path
from datetime import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.fixture
def database():
    url = os.getenv("LANGFLOW_DATABASE_URL", "")
    if os.getenv("POKEDEV_TEST_POSTGRES") != "1" or not url.startswith("postgresql"):
        pytest.skip("Run explicitly in the local app container with POKEDEV_TEST_POSTGRES=1")
    revision = Path("/app/adlc-flow/langflow/alembic/versions/h8b1c2d3e4f5_add_product_cycles.py")
    spec = importlib.util.spec_from_file_location("cycle_revision", revision)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            schema = f"pokedev_test_{uuid4().hex}"
            connection.execute(sa.schema.CreateSchema(schema))
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            tables = module.tables()
            tables[0].metadata.create_all(connection)
            yield connection, module, tables
        finally:
            transaction.rollback()
    engine.dispose()


def test_postgres_adopts_identical_schema_after_server_rewrites_checks(database):
    connection, module, tables = database
    assert all(module._compatible(connection, table) for table in tables)


def test_postgres_rejects_weakened_check(database):
    connection, module, tables = database
    connection.exec_driver_sql("ALTER TABLE adlc_product_cycle DROP CONSTRAINT ck_adlc_cycle_revision")
    connection.exec_driver_sql("ALTER TABLE adlc_product_cycle ADD CONSTRAINT ck_adlc_cycle_revision CHECK (number >= 0 AND revision >= 1 AND spec_revision >= 1)")
    assert not module._compatible(connection, tables[0])


def test_postgres_rejects_missing_index(database):
    connection, module, tables = database
    connection.exec_driver_sql("DROP INDEX ix_adlc_product_cycle_delivery_id")
    assert not module._compatible(connection, tables[0])


def test_postgres_keeps_populated_table_guard(database):
    connection, module, tables = database
    cycle = tables[0]
    actor, delivery, identity = uuid4(), uuid4(), uuid4()
    connection.execute(cycle.metadata.tables["user"].insert().values(id=actor))
    connection.execute(cycle.metadata.tables["adlc_delivery"].insert().values(id=delivery))
    connection.execute(cycle.insert().values(id=identity, delivery_id=delivery, number=1,
        revision=1, spec_revision=1, state="DRAFT", goal="migration regression",
        authority={}, created_by=actor, created_at=datetime.now(), updated_at=datetime.now()))
    with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="populated"):
        module.upgrade()
    assert connection.scalar(sa.select(sa.func.count()).select_from(cycle)) == 1

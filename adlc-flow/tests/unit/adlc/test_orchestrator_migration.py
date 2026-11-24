# ruff: noqa: INP001, S101

"""The orchestrator migration accepts tables bootstrapped by SQLModel."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_orchestrator_migration_preserves_bootstrapped_tables_and_rows(tmp_path, monkeypatch):
    script = (
        Path(__file__).resolve().parents[3] / "langflow/alembic/versions/99685e5e0f03_add_adlc_orchestrator_tables.py"
    )
    spec = importlib.util.spec_from_file_location("orchestrator_migration", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    flow_id = uuid4()
    metadata = sa.MetaData()
    flow = sa.Table("flow", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    expected = {
        "adlc_run_trigger",
        "adlc_workflow_run",
        "adlc_execution_plan",
        "adlc_workflow_definition_version",
    }
    with engine.begin() as connection:
        flow.create(connection)
        connection.execute(flow.insert().values(id=flow_id))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        assert expected.issubset(sa.inspect(connection).get_table_names())
        version = sa.Table("adlc_workflow_definition_version", sa.MetaData(), autoload_with=connection)
        connection.execute(
            version.insert().values(
                id=uuid4().hex,
                flow_id=flow_id.hex,
                version_number=1,
                status="DRAFT",
                created_by="owner",
                created_at=datetime.now(timezone.utc),
                data={"nodes": [], "edges": []},
            )
        )
        before = {table: sa.inspect(connection).get_indexes(table) for table in expected}
        module.upgrade()
        assert connection.scalar(sa.select(sa.func.count()).select_from(version)) == 1
        assert {table: sa.inspect(connection).get_indexes(table) for table in expected} == before
        module.downgrade()
        assert expected.isdisjoint(sa.inspect(connection).get_table_names())
    engine.dispose()

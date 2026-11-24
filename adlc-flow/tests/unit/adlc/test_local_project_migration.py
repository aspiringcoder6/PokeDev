# ruff: noqa: INP001, S101
"""Upgrade and rollback on a real SQLite database, including source ownership constraints."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_local_project_migration_round_trip(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[3] / "langflow/alembic/versions/c41e8d07a9b2_add_adlc_local_projects.py"
    spec = importlib.util.spec_from_file_location("local_project_migration", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    metadata = sa.MetaData()
    folder = sa.Table("folder", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        folder.create(connection)
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        inspector = sa.inspect(connection)
        assert "adlc_local_project" in inspector.get_table_names()
        assert inspector.get_foreign_keys("adlc_local_project")[0]["referred_table"] == "folder"
        assert inspector.get_indexes("adlc_local_project")[0]["name"] == "ix_adlc_local_project_owner_id"
        assert inspector.get_unique_constraints("adlc_local_project")[0]["column_names"] == ["owner_id", "source_path"]
        project = sa.Table("adlc_local_project", sa.MetaData(), autoload_with=connection)
        identity = uuid4()
        connection.execute(folder.insert().values(id=identity))
        connection.execute(
            project.insert().values(project_id=identity.hex, owner_id="owner", source_path="local-source")
        )
        module.upgrade()
        assert connection.scalar(sa.select(sa.func.count()).select_from(project)) == 1
        connection.execute(folder.delete().where(folder.c.id == identity))
        assert connection.scalar(sa.select(sa.func.count()).select_from(project)) == 0
        module.downgrade()
        assert "adlc_local_project" not in sa.inspect(connection).get_table_names()
    engine.dispose()

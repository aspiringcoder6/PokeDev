"""Frozen H7B migration, including create_all-before-Alembic installs."""

# ruff: noqa: S101, INP001 - assertions in the existing namespace test suite.

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import SQLModel

from langflow.services.database.models.auth.collaboration import (
    AdlcProjectCommand,
    AdlcProjectDecision,
    AdlcProjectResource,
    AdlcProjectRevision,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User


def migration():
    path = Path(__file__).resolve().parents[3] / "langflow/alembic/versions/h7b2c3d4e5f6_add_project_collaboration.py"
    spec = importlib.util.spec_from_file_location("h7b_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("metadata_precreated", [False, True])
def test_upgrade_adds_only_empty_stores_without_enabling_or_granting_access(metadata_precreated):
    module = migration()
    engine = sa.create_engine("sqlite://")
    tables = [
        AdlcProjectResource.__table__,
        AdlcProjectRevision.__table__,
        AdlcProjectDecision.__table__,
        AdlcProjectCommand.__table__,
    ]
    with engine.begin() as connection:
        SQLModel.metadata.create_all(connection, tables=[User.__table__, Folder.__table__, AdlcProjectAccess.__table__])
        if metadata_precreated:
            SQLModel.metadata.create_all(connection, tables=tables)
        before = connection.execute(sa.select(sa.func.count()).select_from(AdlcProjectAccess.__table__)).scalar_one()
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        for table in tables:
            assert set(sa.inspect(connection).get_pk_constraint(table.name)["constrained_columns"]) == {
                column.name for column in table.primary_key
            }
            assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 0
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(AdlcProjectAccess.__table__)).scalar_one()
            == before
        )
        with pytest.raises(RuntimeError, match="preservation migration"):
            module.downgrade()
    engine.dispose()


def test_all_existing_tables_are_preflighted_before_any_ddl():
    module = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE adlc_project_decision (id INTEGER PRIMARY KEY)"))
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="incompatible"),
        ):
            module.upgrade()
        assert not sa.inspect(connection).has_table("adlc_project_resource")
        assert not sa.inspect(connection).has_table("adlc_project_revision")
    engine.dispose()


@pytest.mark.parametrize("corruption", ["primary_key", "column_type", "unique"])
def test_matching_column_names_do_not_hide_incompatible_constraints(corruption):
    module = migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):

        def corrupt(name, *definitions):
            if name != "adlc_project_decision":
                return
            definitions = list(definitions)
            if corruption == "unique":
                definitions = [item for item in definitions if not isinstance(item, sa.UniqueConstraint)]
            else:
                for column in definitions:
                    if isinstance(column, sa.Column) and column.name == "id":
                        if corruption == "primary_key":
                            column.primary_key = False
                        else:
                            column.type = sa.Integer()
            module.op.create_table(name, *definitions)

        module._definitions(corrupt)  # noqa: SLF001 - exercise the frozen Alembic definition, not live models.
        with pytest.raises(RuntimeError, match="incompatible"):
            module.upgrade()
        assert not sa.inspect(connection).has_table("adlc_project_resource")
    engine.dispose()

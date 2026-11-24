"""Frozen migration compatibility with the actual Alembic naming convention."""

# ruff: noqa: S101, INP001 - isolated SQL assertions.

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations

from langflow.services.database.models.adlc_delivery import AdlcDelivery
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User
from tests.unit.adlc.test_project_constraint_names import load_revision, runtime_convention


@pytest.mark.parametrize("precreated", [False, True])
def test_fresh_or_create_all_schema_matches_runtime_metadata(precreated, monkeypatch):
    expected = sa.MetaData(naming_convention=runtime_convention())
    for model in (User, Folder, Flow, AdlcDelivery):
        model.__table__.to_metadata(expected)
    monkeypatch.setattr(AdlcDelivery.metadata, "naming_convention", runtime_convention())
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        expected.create_all(connection, tables=[expected.tables[name] for name in ("user", "folder", "flow")])
        if precreated:
            expected.create_all(connection)
        with Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": AdlcDelivery.metadata})
        ):
            load_revision("dw01a2b3c4d5_add_delivery_workspace.py").upgrade()
        assert compare_metadata(MigrationContext.configure(connection), expected) == []
        assert sa.inspect(connection).get_check_constraints("adlc_delivery")[0]["name"] == "ck_adlc_delivery_revision"
    engine.dispose()


def test_lookalike_empty_table_without_constraints_is_not_adopted():
    metadata = sa.MetaData()
    sa.Table(
        "adlc_delivery",
        metadata,
        *[sa.Column(column.name, column.type, nullable=column.nullable) for column in AdlcDelivery.__table__.columns],
    )
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        metadata.create_all(connection)
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="Refusing to adopt"),
        ):
            load_revision("dw01a2b3c4d5_add_delivery_workspace.py").upgrade()
    engine.dispose()

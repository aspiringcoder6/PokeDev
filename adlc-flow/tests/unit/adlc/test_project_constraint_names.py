"""Project revision checks must agree with Alembic's actual naming convention."""

# ruff: noqa: S101, INP001 - assertions in the existing namespace test suite.

import ast
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import SQLModel

from langflow.services.authorization.team_catalog import TeamRole, default_policy, role_id
from langflow.services.database.models.auth import AuthzRole, AuthzRoleAssignment, AuthzRoleAssignmentGrant
from langflow.services.database.models.auth.collaboration import (
    AdlcProjectCommand,
    AdlcProjectDecision,
    AdlcProjectResource,
    AdlcProjectRevision,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User

ALEMBIC_ROOT = Path(__file__).resolve().parents[3] / "langflow/alembic"
CHECKS = {
    "adlc_project_access": "ck_adlc_project_access_revision",
    "adlc_project_resource": "ck_adlc_project_resource_revision",
}
SCOPE_MODELS = (
    User,
    Folder,
    AuthzRole,
    AuthzRoleAssignment,
    AuthzRoleAssignmentGrant,
    AdlcProjectAccess,
    AdlcProjectResource,
    AdlcProjectRevision,
    AdlcProjectDecision,
    AdlcProjectCommand,
)


def load_revision(filename):
    spec = importlib.util.spec_from_file_location(filename, ALEMBIC_ROOT / "versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_convention():
    # Read the real constant without importing env.py (which runs migrations).
    source = ast.parse((ALEMBIC_ROOT / "env.py").read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in source.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "NAMING_CONVENTION" for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def test_fresh_team_migrations_use_final_check_names_with_the_runtime_convention(monkeypatch):
    monkeypatch.setattr(SQLModel.metadata, "naming_convention", runtime_convention())
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        SQLModel.metadata.create_all(connection, tables=[User.__table__, Folder.__table__, AuthzRole.__table__])
        with Operations.context(MigrationContext.configure(connection, opts={"target_metadata": SQLModel.metadata})):
            load_revision("h7a1b2c3d4e5_add_adlc_project_access.py").upgrade()
            load_revision("h7b2c3d4e5f6_add_project_collaboration.py").upgrade()
        inspector = sa.inspect(connection)
        for table, name in CHECKS.items():
            assert [item["name"] for item in inspector.get_check_constraints(table)] == [name]
    engine.dispose()


def scope_metadata(*, legacy=False):
    metadata = sa.MetaData(naming_convention=runtime_convention())
    for model in SCOPE_MODELS:
        model.__table__.to_metadata(metadata)
    if legacy:
        for table, canonical in CHECKS.items():
            for check in metadata.tables[table].constraints:
                if isinstance(check, sa.CheckConstraint) and check.name == canonical:
                    check.name = sa.schema.conv(f"ck_{table}_{canonical}")
    return metadata


def seed_scope(connection, metadata):
    writer = User(username="constraint-writer", password="test-only-hash")  # noqa: S106 - isolated SQL fixture.
    reviewer = User(username="constraint-reviewer", password="test-only-hash")  # noqa: S106
    folder = Folder(name="Preserve team history", user_id=writer.id)
    role = AuthzRole(id=role_id(TeamRole.ADMIN), name="adlc.admin", is_system=True, permissions=[])
    assignment = AuthzRoleAssignment(
        user_id=writer.id, role_id=role.id, domain_type="project", domain_id=folder.id, assigned_by=writer.id
    )
    grant = AuthzRoleAssignmentGrant(assignment_id=assignment.id, source_kind="manual", administrative_actor=writer.id)
    policy = AdlcProjectAccess(
        project_id=folder.id,
        created_by=writer.id,
        revision=7,
        mode="COLLABORATION",
        role_rules=default_policy().model_dump(mode="json"),
    )
    resource = AdlcProjectResource(
        id=uuid4(),
        project_id=folder.id,
        kind="CONTRACT",
        title="Retain this contract",
        created_by=writer.id,
        origin_owner_id=str(writer.id),
        responsible_ids=[str(writer.id)],
        revision=3,
        content_digest="sha256:" + "a" * 64,
        status="APPROVED",
    )
    snapshot = AdlcProjectRevision(
        resource_id=resource.id,
        revision=3,
        content_digest=resource.content_digest,
        authored_by=writer.id,
        payload={"frozen": "Must survive the repair"},
    )
    decision = AdlcProjectDecision(
        project_id=folder.id,
        resource_id=resource.id,
        resource_revision=3,
        content_digest=resource.content_digest,
        policy_revision=7,
        action="contract:approve",
        decision="APPROVE",
        decided_by=reviewer.id,
        comment="Keep the original signature",
        dependencies={},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    command = AdlcProjectCommand(
        project_id=folder.id,
        actor_id=writer.id,
        command_key="original-idempotency-key",
        request_digest="sha256:" + "b" * 64,
        resource_id=resource.id,
        resource_revision=3,
    )
    for row in (writer, reviewer, folder, role, assignment, grant, policy, resource, snapshot, decision, command):
        connection.execute(metadata.tables[row.__tablename__].insert(), row.model_dump())


def stored_rows(connection, metadata):
    return {
        table.name: connection.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings().all()
        for table in metadata.sorted_tables
    }


def stored_indexes(connection, metadata):
    inspector = sa.inspect(connection)
    return {
        table.name: [
            {
                **item,
                "dialect_options": {key: str(value) for key, value in item.get("dialect_options", {}).items()},
            }
            for item in inspector.get_indexes(table.name)
        ]
        for table in metadata.sorted_tables
    }


@pytest.mark.parametrize("legacy", [False, True])
def test_forward_repair_preserves_rows_grants_evidence_and_alembic_check(legacy):
    repair = load_revision("h7b3c4d5e6f7_normalize_project_revision_constraints.py")
    expected = scope_metadata()
    original = scope_metadata(legacy=legacy)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        original.create_all(connection)
        seed_scope(connection, original)
        before = stored_rows(connection, original)
        before_indexes = stored_indexes(connection, original)
        context = MigrationContext.configure(connection, opts={"target_metadata": expected})
        if legacy:
            assert compare_metadata(context, expected)
        with Operations.context(context):
            repair.upgrade()
            repair.upgrade()  # No table rebuild or side effect once normalized.
        assert stored_rows(connection, expected) == before
        assert compare_metadata(MigrationContext.configure(connection), expected) == []
        inspector = sa.inspect(connection)
        for table, name in CHECKS.items():
            assert [item["name"] for item in inspector.get_check_constraints(table)] == [name]
            with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
                connection.execute(sa.update(expected.tables[table]).values(revision=0))
        assert stored_indexes(connection, expected) == before_indexes
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        repair.downgrade()  # Retains canonical names and all historical evidence.
        assert stored_rows(connection, expected) == before
    engine.dispose()


@pytest.mark.parametrize("blocker", ["foreign_keys", "custom_trigger", "unexpected_check"])
def test_repair_preflights_all_tables_before_any_ddl(blocker):
    repair = load_revision("h7b3c4d5e6f7_normalize_project_revision_constraints.py")
    metadata = scope_metadata(legacy=True)
    resource = metadata.tables["adlc_project_resource"]
    if blocker == "unexpected_check":
        for check in resource.constraints:
            if isinstance(check, sa.CheckConstraint):
                check.sqltext = sa.text("revision >= 0")
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        if blocker == "foreign_keys":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with connection.begin_nested():
            metadata.create_all(connection)
            if blocker == "custom_trigger":
                connection.exec_driver_sql(
                    "CREATE TRIGGER preserve_custom_resource_trigger "
                    "AFTER UPDATE ON adlc_project_resource BEGIN SELECT 1; END"
                )
            with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError):
                repair.upgrade()
            # A blocker on the second table must not rebuild the first table.
            for table, name in CHECKS.items():
                assert [item["name"] for item in sa.inspect(connection).get_check_constraints(table)] == [
                    f"ck_{table}_{name}"
                ]
    engine.dispose()

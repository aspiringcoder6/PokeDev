"""Normalize H7A/H7B revision check names without changing rows or grants.

Phase: EXPAND
The original migrations let Alembic apply its ck naming convention twice.
Changing historical DDL alone cannot repair databases already at H7B.
"""

# ruff: noqa: INP001 - Alembic revision.

import re

import sqlalchemy as sa
from alembic import op

revision = "h7b3c4d5e6f7"
down_revision = "h7b2c3d4e5f6"
branch_labels = None
depends_on = None

# Frozen identifiers, independent of application models and role policies.
CHECKS = (
    ("adlc_project_access", "ck_adlc_project_access_revision"),
    ("adlc_project_resource", "ck_adlc_project_resource_revision"),
)


def _repair_plan(connection):
    inspector = sa.inspect(connection)
    planned = []
    for table, canonical in CHECKS:
        if not inspector.has_table(table):
            msg = "Project revision check repair requires the H7A/H7B tables"
            raise RuntimeError(msg)
        doubled = f"ck_{table}_{canonical}"
        checks = [item for item in inspector.get_check_constraints(table) if item.get("name") in {canonical, doubled}]
        if len(checks) != 1 or re.sub(r'[\s()"]', "", checks[0]["sqltext"]).lower() != "revision>=1":
            msg = "Unexpected project revision check; refusing to replace an unverified constraint"
            raise RuntimeError(msg)
        if checks[0]["name"] == canonical:
            continue
        if (
            connection.dialect.name == "sqlite"
            and connection.execute(
                sa.text("SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :table LIMIT 1"),
                {"table": table},
            ).first()
        ):
            msg = "Project revision check repair requires preserving custom SQLite triggers explicitly"
            raise RuntimeError(msg)
        planned.append((table, doubled, canonical))
    if planned and connection.dialect.name not in {"sqlite", "postgresql"}:
        msg = "Project revision check repair supports SQLite and PostgreSQL only"
        raise RuntimeError(msg)
    if planned and connection.dialect.name == "sqlite" and connection.exec_driver_sql("PRAGMA foreign_keys").scalar():
        # SQLite batch DDL rebuilds the parent table. Never disable FK checks
        # inside an active transaction or risk ON DELETE cascades on children.
        # Langflow's Alembic engine uses a separate, default-FK-off connection.
        msg = "Run project revision check repair in the dedicated Alembic maintenance connection (SQLite FK checks off)"
        raise RuntimeError(msg)
    return planned


def upgrade():
    connection = op.get_bind()
    # Preflight both tables before any DDL. Do not rewrite data or reseed roles.
    for table, old, canonical in _repair_plan(connection):
        if connection.dialect.name == "postgresql":
            quote = connection.dialect.identifier_preparer.quote
            # All identifiers originate from CHECKS, never user/model input.
            op.execute(sa.text(f"ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(old)} TO {quote(canonical)}"))
        else:
            reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
            # Reflection returns plain names; mark them final before copying so
            # unrelated reflected constraints are not prefixed a second time.
            for constraint in reflected.constraints:
                if constraint.name:
                    constraint.name = sa.schema.conv(str(constraint.name))
            with op.batch_alter_table(table, copy_from=reflected, recreate="always") as batch:
                batch.drop_constraint(op.f(old), type_="check")
                batch.create_check_constraint(op.f(canonical), "revision >= 1")


def downgrade():
    # Names only: retaining canonical names keeps the previous invariant intact.
    # Never restore the known-bad double-prefix names or discard project data.
    pass

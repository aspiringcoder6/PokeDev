"""H7A: project policy and protected ADLC role presets; no automatic membership."""

# ruff: noqa: INP001 - Alembic revisions are not a Python package.

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "h7a1b2c3d4e5"
down_revision = "c41e8d07a9b2"
branch_labels = None
depends_on = None


def _create_policy_table() -> None:
    op.create_table(
        "adlc_project_access",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("folder.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("role_rules", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_adlc_project_access_revision")),
    )


def upgrade() -> None:
    conn = op.get_bind()
    roles = sa.table(
        "authz_role",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("permissions", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    # Validate all reserved identities before DDL or partial role insertion.
    # SQLite may persist DDL even when a later migration statement rolls back.
    presets = ("admin", "developer", "business_analyst", "tester")
    names = [f"adlc.{role}" for role in presets]
    identities = [uuid5(NAMESPACE_URL, f"adlc:team-role:0.1:{role}") for role in presets]
    if conn.execute(sa.select(roles.c.id).where(sa.or_(roles.c.name.in_(names), roles.c.id.in_(identities)))).first():
        msg = "ADLC role identity already exists; refusing to adopt an unverified role"
        raise RuntimeError(msg)
    inspector = sa.inspect(conn)
    if inspector.has_table("adlc_project_access"):
        expected = {
            "project_id",
            "revision",
            "schema_version",
            "mode",
            "role_rules",
            "created_by",
            "created_at",
            "updated_at",
        }
        actual = {column["name"] for column in inspector.get_columns("adlc_project_access")}
        if actual != expected or conn.execute(sa.text("SELECT COUNT(*) FROM adlc_project_access")).scalar_one():
            msg = "Refusing to adopt an existing non-empty or incompatible ADLC policy table"
            raise RuntimeError(msg)
    else:
        _create_policy_table()
    now = datetime.now(timezone.utc)
    # Frozen migration constants: never import future application role presets.
    for role in presets:
        name = f"adlc.{role}"
        conn.execute(
            roles.insert().values(
                id=uuid5(NAMESPACE_URL, f"adlc:team-role:0.1:{role}"),
                name=name,
                description=f"ADLC {role} v0.1; project-only; managed by Team Access",
                is_system=True,
                # These are not global legacy role grants. Project rules own permissions.
                permissions=[],
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    # Security state and append-only evidence are not silently discarded by rollback.
    msg = "H7A downgrade requires an explicit project-policy migration; never fall back to allow-all"
    raise RuntimeError(msg)

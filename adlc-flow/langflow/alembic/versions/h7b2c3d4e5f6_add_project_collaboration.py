"""H7B durable scope and accountable decisions; existing resources stay private."""

# ruff: noqa: INP001 - Alembic revision.

import sqlalchemy as sa
from alembic import op

revision = "h7b2c3d4e5f6"
down_revision = "h7a1b2c3d4e5"
branch_labels = None
depends_on = None


def _validate_existing(name, *columns):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(name):
        # Fresh installs may have called SQLModel.create_all before Alembic.
        expected = {column.name: column for column in columns if isinstance(column, sa.Column)}
        actual = {column["name"]: column for column in inspector.get_columns(name)}
        count = bind.execute(sa.select(sa.func.count()).select_from(sa.table(name))).scalar_one()
        primary_key = inspector.get_pk_constraint(name)["constrained_columns"]
        expected_key = [column.name for column in expected.values() if column.primary_key]
        unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
        expected_unique = {("resource_id", "resource_revision")} if name == "adlc_project_decision" else set()
        same_columns = actual.keys() == expected.keys() and all(
            actual[key]["nullable"] == column.nullable
            and str(actual[key]["type"].compile(dialect=bind.dialect)).upper()
            == str(column.type.compile(dialect=bind.dialect)).upper()
            for key, column in expected.items()
        )
        foreign_keys = {
            (column, f"{item['referred_table']}.{target}")
            for item in inspector.get_foreign_keys(name)
            for column, target in zip(item["constrained_columns"], item["referred_columns"], strict=True)
        }
        expected_foreign_keys = {
            (column.name, key.target_fullname) for column in expected.values() for key in column.foreign_keys
        }
        checks = {item["sqltext"].replace(" ", "") for item in inspector.get_check_constraints(name)}
        expected_checks = {
            str(item.sqltext).replace(" ", "") for item in columns if isinstance(item, sa.CheckConstraint)
        }
        if (
            count
            or not same_columns
            or primary_key != expected_key
            or unique != expected_unique
            or foreign_keys != expected_foreign_keys
            or checks != expected_checks
        ):
            msg = "Refusing to adopt a non-empty or incompatible collaboration table"
            raise RuntimeError(msg)
    return inspector.has_table(name)


def _definitions(create):
    create(
        "adlc_project_resource",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("folder.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("origin_owner_id", sa.String(64), nullable=False),
        sa.Column("responsible_ids", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(71), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_adlc_project_resource_revision")),
    )
    create(
        "adlc_project_revision",
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("adlc_project_resource.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("content_digest", sa.String(71), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("authored_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "adlc_project_decision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("folder.id"), nullable=False, index=True),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("adlc_project_resource.id"), nullable=False, index=True),
        sa.Column("resource_revision", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(71), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("comment", sa.String(2000), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("resource_id", "resource_revision", name="uq_adlc_project_decision"),
    )
    create(
        "adlc_project_command",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("folder.id"), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("command_key", sa.String(128), primary_key=True),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("resource_id", sa.Uuid(), sa.ForeignKey("adlc_project_resource.id"), nullable=False),
        sa.Column("resource_revision", sa.Integer(), nullable=False),
    )


def upgrade():
    tables = []

    def collect(name, *columns):
        tables.append((name, columns))

    _definitions(collect)
    # Validate every existing table before any DDL; SQLite DDL may survive a
    # later statement failure. No automatic project activation or grants.
    existing = [_validate_existing(name, *columns) for name, columns in tables]
    for (name, columns), exists in zip(tables, existing, strict=True):
        if not exists:
            op.create_table(name, *columns)


def downgrade():
    msg = "H7B scope and decision evidence require an explicit preservation migration"
    raise RuntimeError(msg)

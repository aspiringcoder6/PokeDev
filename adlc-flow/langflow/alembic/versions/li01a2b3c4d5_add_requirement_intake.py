"""LI-01: durable private requirement intake and command receipts."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "li01a2b3c4d5"
down_revision = "h8b1c2d3e4f5"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    sa.Table("user", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("folder", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    request = sa.Table(
        "adlc_intake_request",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("folder.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(71), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_intake_revision")),
    )
    sa.Index("ix_adlc_intake_request_project_id", request.c.project_id)
    history = sa.Table(
        "adlc_intake_revision",
        metadata,
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("adlc_intake_request.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_intake_history_revision")),
    )
    command = sa.Table(
        "adlc_intake_command",
        metadata,
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("command_id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("adlc_intake_request.id"), nullable=False, index=True),
        sa.Column("input_digest", sa.String(71), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    return request, history, command


def upgrade():
    connection = op.get_bind()
    for table in tables():
        if sa.inspect(connection).has_table(table.name):
            if not _compatible(connection, table) or connection.scalar(sa.select(sa.func.count()).select_from(table)):
                raise RuntimeError(f"Refusing to adopt incompatible or populated intake table: {table.name}")
        else:
            table.create(connection)


def downgrade():
    raise RuntimeError("Intake history requires an explicit preservation migration")


def _expected_checks(connection, table):
    constraints = [item for item in table.constraints if isinstance(item, sa.CheckConstraint)]
    if connection.dialect.name != "postgresql" or not constraints:
        return {(item.name, "".join(str(item.sqltext).split())) for item in constraints}

    # PostgreSQL rewrites IN as = ANY (ARRAY[...]) and adds casts. Ask the
    # same server to normalize the frozen checks, without touching real data.
    temporary = sa.Table(
        f"adlc_intake_checks_{uuid4().hex[:16]}",
        sa.MetaData(),
        *(sa.Column(column.name, column.type) for column in table.c),
        *(sa.CheckConstraint(str(item.sqltext), name=sa.schema.conv(item.name)) for item in constraints),
        prefixes=["TEMPORARY"],
        postgresql_on_commit="DROP",
    )
    temporary.create(connection)
    try:
        schema = connection.scalar(sa.text("SELECT pg_my_temp_schema()::regnamespace::text"))
        return {
            (item["name"], "".join(item["sqltext"].split()))
            for item in sa.inspect(connection).get_check_constraints(temporary.name, schema=schema)
        }
    finally:
        temporary.drop(connection)


def _compatible(connection, table):
    inspector = sa.inspect(connection)
    actual = inspector.get_columns(table.name)
    if {item["name"] for item in actual} != set(table.c.keys()):
        return False
    for item in actual:
        expected = table.c[item["name"]]
        if item["nullable"] != expected.nullable:
            return False
        # Dialect type compilation handles SQLite UUID reflection as CHAR(32).
        if str(item["type"].compile(dialect=connection.dialect)) != str(
            expected.type.compile(dialect=connection.dialect)
        ):
            return False
    checks = {(item["name"], "".join(item["sqltext"].split())) for item in inspector.get_check_constraints(table.name)}
    expected_checks = _expected_checks(connection, table)
    uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
    expected_uniques = {
        tuple(column.name for column in item.columns)
        for item in table.constraints
        if isinstance(item, sa.UniqueConstraint)
    }
    foreign = {
        (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
        for item in inspector.get_foreign_keys(table.name)
    }
    expected_foreign = {
        (
            tuple(column.name for column in item.columns),
            item.referred_table.name,
            tuple(element.column.name for element in item.elements),
        )
        for item in table.constraints
        if isinstance(item, sa.ForeignKeyConstraint)
    }
    indexes = {
        tuple(item["column_names"])
        for item in inspector.get_indexes(table.name)
        if not item.get("duplicates_constraint")
    }
    return (
        checks == expected_checks
        and uniques == expected_uniques
        and foreign == expected_foreign
        and indexes == {tuple(column.name for column in item.columns) for item in table.indexes}
        and inspector.get_pk_constraint(table.name)["constrained_columns"]
        == [column.name for column in table.primary_key]
    )

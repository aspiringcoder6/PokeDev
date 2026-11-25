"""Add durable product-cycle history without changing legacy authority.

Phase: EXPAND. Frozen table definitions and deterministic legacy import.
"""

# ruff: noqa: INP001 - Alembic revision.

import hashlib
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from alembic import op

revision = "h8b1c2d3e4f5"
down_revision = "dw01a2b3c4d5"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    sa.Table("user", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("adlc_delivery", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    cycle = sa.Table(
        "adlc_product_cycle",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("adlc_delivery.id"), nullable=False, index=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("spec_revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("goal", sa.String(), nullable=False),
        sa.Column("plan_id", sa.Uuid()),
        sa.Column("run_id", sa.Uuid()),
        sa.Column("dispatch_plan_id", sa.Uuid()),
        sa.Column("authority", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("delivery_id", "number", name=sa.schema.conv("uq_adlc_cycle_number")),
        sa.CheckConstraint(
            "number >= 1 AND revision >= 1 AND spec_revision >= 1", name=sa.schema.conv("ck_adlc_cycle_revision")
        ),
        sa.CheckConstraint(
            "state IN ('PLANNING', 'DRAFT', 'DISPATCH_RESERVED', 'LINKED')", name=sa.schema.conv("ck_adlc_cycle_state")
        ),
    )
    head = sa.Table(
        "adlc_cycle_head",
        metadata,
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("adlc_delivery.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.Column("latest_cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id"), nullable=False),
        sa.Column("execution_cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id")),
        sa.CheckConstraint("revision >= 1 AND next_number >= 2", name=sa.schema.conv("ck_adlc_cycle_head_revision")),
    )
    spec = sa.Table(
        "adlc_cycle_spec",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id"), nullable=False, index=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(71), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cycle_id", "revision", name=sa.schema.conv("uq_adlc_cycle_spec_revision")),
        sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_cycle_spec_revision")),
    )
    plan = sa.Table(
        "adlc_cycle_plan_revision",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id"), nullable=False, index=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_plan_id", sa.Uuid()),
        sa.Column("plan_digest", sa.String(71), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("workflow_snapshot", sa.JSON(), nullable=False),
        sa.Column("approval", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("cycle_id", "ordinal", name=sa.schema.conv("uq_adlc_cycle_plan_ordinal")),
        sa.UniqueConstraint("plan_id", name=sa.schema.conv("uq_adlc_cycle_plan_id")),
        sa.CheckConstraint("ordinal >= 1", name=sa.schema.conv("ck_adlc_cycle_plan_ordinal")),
    )
    feedback = sa.Table(
        "adlc_cycle_feedback",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("adlc_delivery.id"), nullable=False, index=True),
        sa.Column("source_cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id"), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("delivery_id", "source_key", name=sa.schema.conv("uq_adlc_cycle_feedback_source")),
        sa.CheckConstraint(
            "status IN ('OPEN', 'SELECTED', 'DEFERRED', 'RESOLVED')",
            name=sa.schema.conv("ck_adlc_cycle_feedback_status"),
        ),
    )
    operation = sa.Table(
        "adlc_cycle_operation",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("adlc_delivery.id"), nullable=False, index=True),
        sa.Column("cycle_id", sa.Uuid(), sa.ForeignKey("adlc_product_cycle.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("command_key", sa.String(200), nullable=False),
        sa.Column("input_digest", sa.String(71), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("delivery_id", "kind", "command_key", name=sa.schema.conv("uq_adlc_cycle_operation_key")),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'SUCCEEDED', 'UNCONFIRMED', 'FAILED')",
            name=sa.schema.conv("ck_adlc_cycle_operation_status"),
        ),
    )
    return cycle, head, spec, plan, feedback, operation


def _digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )


def _plan_digest(value):
    payload = {key: item for key, item in value.items() if key not in {"status", "approved_by", "approved_at"}}
    payload["metadata"] = {key: item for key, item in payload["metadata"].items() if key != "plan_approval"}
    return _digest(payload)


def _graph_digest(graph):
    return _digest(
        {
            "definition": {
                key: value for key, value in graph.get("adlc", {}).items() if key not in {"version", "status"}
            },
            "nodes": [{key: node.get(key) for key in ("id", "type", "data")} for node in graph.get("nodes", [])],
            "edges": [
                {key: edge.get(key) for key in ("id", "source", "target", "sourceHandle", "targetHandle", "data")}
                for edge in graph.get("edges", [])
            ],
        }
    )


def _expected_checks(connection, table):
    constraints = [item for item in table.constraints if isinstance(item, sa.CheckConstraint)]
    if connection.dialect.name != "postgresql" or not constraints:
        return {(item.name, "".join(str(item.sqltext).split())) for item in constraints}

    # PostgreSQL rewrites IN as = ANY (ARRAY[...]) and adds casts. Ask the
    # same server to normalize the frozen checks, without touching real data.
    temporary = sa.Table(
        f"adlc_cycle_checks_{uuid4().hex[:16]}",
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


def _backfill(connection, new_tables):
    cycle, head, spec, binding, feedback, operation = new_tables
    sources = sa.MetaData()
    delivery = sa.Table("adlc_delivery", sources, autoload_with=connection)
    flow = sa.Table("flow", sources, autoload_with=connection)
    archive = sa.Table("adlc_execution_plan", sources, autoload_with=connection)
    for row in connection.execute(sa.select(delivery)).mappings():
        identity, owner = UUID(str(row["id"])), UUID(str(row["owner_id"]))
        cycle_id = uuid5(NAMESPACE_URL, f"adlc:{identity}:cycle:1")
        graph = connection.execute(sa.select(flow.c.data).where(flow.c.id == row["flow_id"])).scalar_one() or {}
        authority = {}
        for key in (
            "workflow_approved_digest",
            "workflow_approved_by",
            "workflow_approved_at",
            "plan_approved_digest",
            "plan_approved_by",
            "plan_approved_at",
        ):
            value = row[key]
            if isinstance(value, datetime):
                value = (
                    value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
                ).isoformat()
            authority[key] = str(UUID(str(value))) if value and key.endswith("_by") else value
        connection.execute(
            cycle.insert().values(
                id=cycle_id,
                delivery_id=identity,
                number=1,
                predecessor_id=None,
                revision=row["revision"],
                spec_revision=1,
                state="LINKED" if row["run_id"] else "DISPATCH_RESERVED" if row["dispatch_plan_id"] else "PLANNING",
                goal=row["requirement"],
                plan_id=UUID(str(row["plan_id"])) if row["plan_id"] else None,
                run_id=UUID(str(row["run_id"])) if row["run_id"] else None,
                dispatch_plan_id=UUID(str(row["dispatch_plan_id"])) if row["dispatch_plan_id"] else None,
                authority=authority,
                created_by=owner,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )
        connection.execute(
            head.insert().values(
                delivery_id=identity,
                revision=row["revision"],
                next_number=2,
                latest_cycle_id=cycle_id,
                execution_cycle_id=cycle_id if row["run_id"] or row["dispatch_plan_id"] else None,
            )
        )
        payload = {
            "schema_version": "0.1",
            "delivery_id": str(identity),
            "cycle_id": str(cycle_id),
            "predecessor_id": None,
            "goal": row["requirement"],
            "workflow_id": str(UUID(str(row["flow_id"]))),
            "workflow_version": graph.get("adlc", {}).get("version"),
            "workflow_digest": _graph_digest(graph),
            "workflow_snapshot": graph,
            "baseline": None,
            "acceptance_criteria": [],
            "selected_feedback_ids": [],
            "execution_ready": False,
            "source": "LEGACY_IMPORT",
        }
        connection.execute(
            spec.insert().values(
                id=uuid5(cycle_id, "spec:1"),
                cycle_id=cycle_id,
                revision=1,
                digest=_digest(payload),
                payload=payload,
                created_by=owner,
                created_at=row["created_at"],
            )
        )
        chain, cursor, seen = [], row["plan_id"], set()
        while cursor:
            key = str(cursor)
            if key in seen:
                message = "Cycle detected in legacy execution-plan lineage"
                raise RuntimeError(message)
            seen.add(key)
            old = connection.execute(sa.select(archive).where(archive.c.id == cursor)).mappings().one_or_none()
            if not old or str(old["owner_id"]) != str(owner) or old["workflow_definition_id"] != row["flow_id"]:
                message = "Cannot preserve a missing or foreign legacy execution plan"
                raise RuntimeError(message)
            chain.append(old)
            cursor = old["supersedes_plan_id"]
        for ordinal, old in enumerate(reversed(chain), start=1):
            plan_id = UUID(str(old["id"]))
            connection.execute(
                binding.insert().values(
                    id=uuid5(cycle_id, f"plan:{plan_id}"),
                    cycle_id=cycle_id,
                    ordinal=ordinal,
                    plan_id=plan_id,
                    predecessor_plan_id=UUID(str(old["supersedes_plan_id"])) if old["supersedes_plan_id"] else None,
                    plan_digest=_plan_digest(old["plan_payload"]),
                    plan_snapshot=old["plan_payload"],
                    workflow_snapshot=old["workflow_payload"],
                    created_at=old["generated_at"],
                    approval={key: value for key, value in authority.items() if key.startswith("plan_")}
                    if old["id"] == row["plan_id"] and row["plan_approved_digest"]
                    else {},
                )
            )
        for note in row["notes"]:
            connection.execute(
                feedback.insert().values(
                    id=uuid5(cycle_id, f"note:{note['id']}"),
                    delivery_id=identity,
                    source_cycle_id=cycle_id,
                    source_key=f"note:{note['id']}",
                    status="OPEN",
                    payload=note,
                    created_at=datetime.fromisoformat(note["created_at"]),
                )
            )
        if row["dispatch_plan_id"]:
            dispatch_id = str(UUID(str(row["dispatch_plan_id"])))
            inputs = {"plan_id": dispatch_id, "plan_digest": row["plan_approved_digest"]}
            connection.execute(
                operation.insert().values(
                    id=uuid5(cycle_id, "legacy:dispatch"),
                    delivery_id=identity,
                    cycle_id=cycle_id,
                    kind="DISPATCH",
                    command_key=dispatch_id,
                    input_digest=_digest(inputs),
                    input_snapshot=inputs,
                    status="SUCCEEDED" if row["run_id"] else "UNCONFIRMED",
                    result={"run_id": str(UUID(str(row["run_id"])))} if row["run_id"] else {},
                    actor_id=owner,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )


def upgrade():
    connection = op.get_bind()
    new_tables = tables()
    for table in new_tables:
        if sa.inspect(connection).has_table(table.name):
            if (
                not _compatible(connection, table)
                or connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            ):
                message = f"Refusing to adopt incompatible or populated cycle table: {table.name}"
                raise RuntimeError(message)
        else:
            table.create(connection)
    _backfill(connection, new_tables)


def downgrade():
    message = "Cycle specs, approval lineage and command receipts require an explicit preservation migration"
    raise RuntimeError(message)

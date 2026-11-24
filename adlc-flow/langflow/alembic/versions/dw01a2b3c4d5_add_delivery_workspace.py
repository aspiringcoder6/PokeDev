"""Add workflow delivery links and human review receipts; no dispatch or grants.

Phase: EXPAND
"""

# ruff: noqa: INP001 - Alembic revision.

import sqlalchemy as sa
from alembic import op

revision = "dw01a2b3c4d5"
down_revision = "h7b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if sa.inspect(connection).has_table("adlc_delivery"):
        # create_all may precede Alembic. Never adopt populated/unverified data.
        expected = {
            "id",
            "owner_id",
            "flow_id",
            "title",
            "requirement",
            "revision",
            "workflow_approved_digest",
            "workflow_approved_by",
            "workflow_approved_at",
            "plan_id",
            "plan_approved_digest",
            "plan_approved_by",
            "plan_approved_at",
            "run_id",
            "dispatch_plan_id",
            "notes",
            "created_at",
            "updated_at",
        }
        inspector = sa.inspect(connection)
        columns = inspector.get_columns("adlc_delivery")
        actual = {item["name"] for item in columns}
        optional = {
            "workflow_approved_digest",
            "workflow_approved_by",
            "workflow_approved_at",
            "plan_id",
            "plan_approved_digest",
            "plan_approved_by",
            "plan_approved_at",
            "run_id",
            "dispatch_plan_id",
        }
        foreign_keys = {
            (tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"]))
            for item in inspector.get_foreign_keys("adlc_delivery")
        }
        checks = inspector.get_check_constraints("adlc_delivery")
        compatible = (
            actual == expected
            and all(item["nullable"] == (item["name"] in optional) for item in columns)
            and inspector.get_pk_constraint("adlc_delivery")["constrained_columns"] == ["id"]
            and any(item["column_names"] == ["flow_id"] for item in inspector.get_unique_constraints("adlc_delivery"))
            and any(item["column_names"] == ["owner_id"] for item in inspector.get_indexes("adlc_delivery"))
            and foreign_keys
            == {
                (("owner_id",), "user", ("id",)),
                (("flow_id",), "flow", ("id",)),
                (("workflow_approved_by",), "user", ("id",)),
                (("plan_approved_by",), "user", ("id",)),
            }
            and len(checks) == 1
            and checks[0]["name"] == "ck_adlc_delivery_revision"
            and "".join(checks[0]["sqltext"].split()) == "revision>=1"
        )
        if not compatible or connection.execute(sa.text("SELECT COUNT(*) FROM adlc_delivery")).scalar_one():
            message = "Refusing to adopt an incompatible or non-empty delivery workspace table"
            raise RuntimeError(message)
        return
    op.create_table(
        "adlc_delivery",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("flow_id", sa.Uuid(), sa.ForeignKey("flow.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("requirement", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("workflow_approved_digest", sa.String(71), nullable=True),
        sa.Column("workflow_approved_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("workflow_approved_at", sa.DateTime(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("plan_approved_digest", sa.String(71), nullable=True),
        sa.Column("plan_approved_by", sa.Uuid(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("plan_approved_at", sa.DateTime(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("dispatch_plan_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_adlc_delivery_revision")),
        sa.UniqueConstraint("flow_id", name=op.f("uq_adlc_delivery_flow_id")),
    )


def downgrade():
    message = "Delivery review evidence requires an explicit preservation migration"
    raise RuntimeError(message)

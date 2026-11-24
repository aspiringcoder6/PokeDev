"""Add owner-scoped local project source configuration.

Revision ID: c41e8d07a9b2
Revises: 99685e5e0f03
"""

# ruff: noqa: INP001 - Alembic's versions directory is intentionally not a Python package.

import sqlalchemy as sa
from alembic import op

from langflow.utils import migration

revision = "c41e8d07a9b2"
down_revision = "99685e5e0f03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if migration.table_exists("adlc_local_project", op.get_bind()):
        return
    op.create_table(
        "adlc_local_project",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["folder.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("owner_id", "source_path", name="uq_adlc_local_project_source"),
    )
    op.create_index("ix_adlc_local_project_owner_id", "adlc_local_project", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_adlc_local_project_owner_id", table_name="adlc_local_project")
    op.drop_table("adlc_local_project")

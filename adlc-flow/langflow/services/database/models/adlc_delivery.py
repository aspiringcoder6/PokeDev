"""User-facing workspace linking canonical workflow, plan and run records."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


def utc_now():
    return datetime.now(timezone.utc)


class AdlcDelivery(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_delivery"
    __table_args__ = (
        sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_delivery_revision")),
        sa.UniqueConstraint("flow_id", name=sa.schema.conv("uq_adlc_delivery_flow_id")),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(foreign_key="user.id", index=True)
    flow_id: UUID = Field(foreign_key="flow.id")
    title: str = Field(max_length=200)
    requirement: str
    revision: int = Field(default=1)
    workflow_approved_digest: str | None = Field(default=None, max_length=71)
    workflow_approved_by: UUID | None = Field(default=None, foreign_key="user.id")
    workflow_approved_at: datetime | None = None
    plan_id: UUID | None = None
    plan_approved_digest: str | None = Field(default=None, max_length=71)
    plan_approved_by: UUID | None = Field(default=None, foreign_key="user.id")
    plan_approved_at: datetime | None = None
    run_id: UUID | None = None
    dispatch_plan_id: UUID | None = None
    notes: list[dict] = Field(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

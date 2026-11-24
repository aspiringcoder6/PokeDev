"""Durable product-cycle lineage; execution still belongs to the ADLC coordinator."""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel

from langflow.services.database.models.adlc_delivery import utc_now


class AdlcProductCycle(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_product_cycle"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "number", name=sa.schema.conv("uq_adlc_cycle_number")),
        sa.CheckConstraint(
            "number >= 1 AND revision >= 1 AND spec_revision >= 1", name=sa.schema.conv("ck_adlc_cycle_revision")
        ),
        sa.CheckConstraint(
            "state IN ('PLANNING', 'DRAFT', 'DISPATCH_RESERVED', 'LINKED')", name=sa.schema.conv("ck_adlc_cycle_state")
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    delivery_id: UUID = Field(foreign_key="adlc_delivery.id", index=True)
    number: int
    predecessor_id: UUID | None = Field(default=None, foreign_key="adlc_product_cycle.id")
    revision: int = 1
    spec_revision: int = 1
    state: str = Field(default="DRAFT", max_length=32)
    goal: str
    plan_id: UUID | None = None
    run_id: UUID | None = None
    dispatch_plan_id: UUID | None = None
    authority: dict = Field(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))
    created_by: UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AdlcCycleHead(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_cycle_head"
    __table_args__ = (
        sa.CheckConstraint("revision >= 1 AND next_number >= 2", name=sa.schema.conv("ck_adlc_cycle_head_revision")),
    )
    delivery_id: UUID = Field(foreign_key="adlc_delivery.id", primary_key=True)
    revision: int = 1
    next_number: int = 2
    latest_cycle_id: UUID = Field(foreign_key="adlc_product_cycle.id")
    # At most one reservation slot per product, including uncertain acknowledgements.
    execution_cycle_id: UUID | None = Field(default=None, foreign_key="adlc_product_cycle.id")


class AdlcCycleSpec(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_cycle_spec"
    __table_args__ = (
        sa.UniqueConstraint("cycle_id", "revision", name=sa.schema.conv("uq_adlc_cycle_spec_revision")),
        sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_cycle_spec_revision")),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    cycle_id: UUID = Field(foreign_key="adlc_product_cycle.id", index=True)
    revision: int = 1
    digest: str = Field(max_length=71)
    payload: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_by: UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)


class AdlcCyclePlanRevision(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_cycle_plan_revision"
    __table_args__ = (
        sa.UniqueConstraint("cycle_id", "ordinal", name=sa.schema.conv("uq_adlc_cycle_plan_ordinal")),
        sa.UniqueConstraint("plan_id", name=sa.schema.conv("uq_adlc_cycle_plan_id")),
        sa.CheckConstraint("ordinal >= 1", name=sa.schema.conv("ck_adlc_cycle_plan_ordinal")),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    cycle_id: UUID = Field(foreign_key="adlc_product_cycle.id", index=True)
    ordinal: int
    plan_id: UUID
    predecessor_plan_id: UUID | None = None
    plan_digest: str = Field(max_length=71)
    plan_snapshot: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    workflow_snapshot: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    approval: dict = Field(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class AdlcCycleFeedback(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_cycle_feedback"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "source_key", name=sa.schema.conv("uq_adlc_cycle_feedback_source")),
        sa.CheckConstraint(
            "status IN ('OPEN', 'SELECTED', 'DEFERRED', 'RESOLVED')",
            name=sa.schema.conv("ck_adlc_cycle_feedback_status"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    delivery_id: UUID = Field(foreign_key="adlc_delivery.id", index=True)
    source_cycle_id: UUID = Field(foreign_key="adlc_product_cycle.id")
    source_key: str = Field(max_length=200)
    status: str = Field(default="OPEN", max_length=32)
    payload: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class AdlcCycleOperation(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_cycle_operation"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", "kind", "command_key", name=sa.schema.conv("uq_adlc_cycle_operation_key")),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'SUCCEEDED', 'UNCONFIRMED', 'FAILED')",
            name=sa.schema.conv("ck_adlc_cycle_operation_status"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    delivery_id: UUID = Field(foreign_key="adlc_delivery.id", index=True)
    cycle_id: UUID = Field(foreign_key="adlc_product_cycle.id")
    kind: str = Field(max_length=32)
    command_key: str = Field(max_length=200)
    input_digest: str = Field(max_length=71)
    input_snapshot: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    status: str = Field(default="RESERVED", max_length=32)
    result: dict = Field(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))
    actor_id: UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

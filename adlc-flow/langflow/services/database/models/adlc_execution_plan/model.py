"""Durable execution-plan archive for the ADLC planning boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint
from sqlmodel import JSON, Field, SQLModel


class AdlcExecutionPlan(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_execution_plan"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: str = Field(nullable=False, index=True, max_length=64)
    workflow_definition_id: UUID = Field(
        sa_column=Column(ForeignKey("flow.id", ondelete="CASCADE"), index=True, nullable=False),
    )
    workflow_definition_version: int = Field(nullable=False, ge=1)
    plan_version: int = Field(nullable=False, ge=1)
    status: str = Field(nullable=False, max_length=32)
    validation_status: str = Field(nullable=False, max_length=32)
    supersedes_plan_id: UUID | None = Field(default=None, nullable=True)
    approval_required: bool = Field(default=False, nullable=False)
    plan_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    workflow_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    generated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "workflow_definition_id",
            "plan_version",
            name="uq_adlc_execution_plan_version",
        ),
    )


class AdlcExecutionPlanSummaryRead(BaseModel):
    """Projection for listing archived plan versions without heavy payloads."""

    execution_plan_id: UUID
    workflow_definition_id: UUID
    workflow_definition_version: int
    plan_version: int
    status: str
    validation_status: str
    supersedes_plan_id: UUID | None
    approval_required: bool
    generated_at: datetime

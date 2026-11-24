"""Durable run-state snapshots for the ADLC runtime coordinator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime
from sqlmodel import JSON, Field, SQLModel


class AdlcWorkflowRun(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_workflow_run"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: str = Field(nullable=False, index=True, max_length=64)
    status: str = Field(nullable=False, max_length=32, index=True)
    execution_mode: str = Field(nullable=False, max_length=32)
    flow_id: UUID | None = Field(default=None, nullable=True)
    execution_plan_id: UUID | None = Field(default=None, nullable=True)
    run_number: int | None = Field(default=None, nullable=True)
    run_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    definitions_payload: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

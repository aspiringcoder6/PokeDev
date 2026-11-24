"""Durable run-trigger definitions for the ADLC orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime
from sqlmodel import JSON, Field, SQLModel


class AdlcRunTrigger(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_run_trigger"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: str = Field(nullable=False, index=True, max_length=64)
    name: str = Field(nullable=False, max_length=128)
    enabled: bool = Field(default=True, nullable=False)
    flow_id: UUID = Field(nullable=False, index=True)
    flow_name: str = Field(nullable=False, max_length=255)
    execution_mode: str = Field(nullable=False, max_length=32)
    overlap_policy: str = Field(default="SKIP", nullable=False, max_length=16)
    missed_policy: str = Field(default="SKIP", nullable=False, max_length=16)
    webhook_enabled: bool = Field(default=False, nullable=False)
    webhook_token: str | None = Field(default=None, nullable=True, max_length=255, index=True)
    schedule_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    definitions_payload: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    next_due_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_fired_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_fire_status: str | None = Field(default=None, nullable=True, max_length=32)
    last_run_id: UUID | None = Field(default=None, nullable=True)
    active_run_ids: list[UUID] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
        ),
    )

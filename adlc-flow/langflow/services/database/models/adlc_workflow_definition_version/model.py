"""Durable workflow-definition version history for ADLC blueprints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint, func
from sqlmodel import JSON, Field, SQLModel


class AdlcWorkflowDefinitionVersion(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_workflow_definition_version"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    flow_id: UUID = Field(
        sa_column=Column(ForeignKey("flow.id", ondelete="CASCADE"), index=True, nullable=False),
    )
    version_number: int = Field(nullable=False, ge=1)
    status: str = Field(nullable=False, max_length=32, default="PUBLISHED")
    description: str | None = Field(default=None, nullable=True, max_length=500)
    created_by: str = Field(nullable=False, max_length=64)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True),
    )
    data: dict | None = Field(default=None, sa_column=Column(JSON))

    __table_args__ = (
        UniqueConstraint("flow_id", "version_number", name="uq_adlc_workflow_definition_version"),
    )


class AdlcWorkflowDefinitionVersionRead(BaseModel):
    id: UUID
    flow_id: UUID
    version_number: int
    status: str
    description: str | None
    created_by: str
    created_at: datetime

    @property
    def version_tag(self) -> str:
        return f"v{self.version_number}"


class AdlcWorkflowDefinitionVersionReadWithData(AdlcWorkflowDefinitionVersionRead):
    data: dict | None

"""Project-scoped ADLC policy. Identity stays in the canonical authz tables."""

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


class AdlcProjectAccess(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_project_access"
    __table_args__ = (sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_project_access_revision")),)

    project_id: UUID = Field(foreign_key="folder.id", primary_key=True)
    revision: int = Field(default=1)
    schema_version: str = Field(default="0.1", max_length=16)
    # H7A deliberately has no switch that enables shared execution.
    mode: str = Field(default="CONFIGURATION_ONLY", max_length=32)
    role_rules: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_by: UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

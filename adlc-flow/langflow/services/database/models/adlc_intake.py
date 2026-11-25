"""Private, revisioned requirements before planning or execution."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


class AdlcIntakeRequest(SQLModel, table=True):
    __tablename__ = "adlc_intake_request"
    __table_args__ = (sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_intake_revision")),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_id: UUID = Field(foreign_key="user.id", index=True)
    project_id: UUID | None = Field(default=None, foreign_key="folder.id", index=True)
    revision: int = Field(default=1)
    status: str = Field(default="NEW", max_length=32)
    content: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    content_digest: str = Field(max_length=71)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdlcIntakeRevision(SQLModel, table=True):
    __tablename__ = "adlc_intake_revision"
    __table_args__ = (sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_intake_history_revision")),)

    request_id: UUID = Field(foreign_key="adlc_intake_request.id", primary_key=True)
    revision: int = Field(primary_key=True)
    actor_id: UUID = Field(foreign_key="user.id")
    command_id: UUID
    snapshot: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdlcIntakeCommand(SQLModel, table=True):
    __tablename__ = "adlc_intake_command"

    owner_id: UUID = Field(foreign_key="user.id", primary_key=True)
    command_id: UUID = Field(primary_key=True)
    request_id: UUID = Field(foreign_key="adlc_intake_request.id", index=True)
    input_digest: str = Field(max_length=71)
    result: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

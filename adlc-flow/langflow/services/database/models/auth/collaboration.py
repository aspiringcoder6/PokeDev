"""Immutable project scope, authoring revisions and accountable human decisions."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


def utc_now():
    return datetime.now(timezone.utc)


class AdlcProjectResource(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_project_resource"
    __table_args__ = (sa.CheckConstraint("revision >= 1", name=sa.schema.conv("ck_adlc_project_resource_revision")),)
    id: UUID = Field(primary_key=True)
    project_id: UUID = Field(foreign_key="folder.id", index=True)
    kind: str = Field(max_length=32, index=True)
    parent_id: UUID | None = Field(default=None, index=True)
    title: str = Field(max_length=256)
    created_by: UUID = Field(foreign_key="user.id")
    origin_owner_id: str = Field(max_length=64)
    responsible_ids: list[str] = Field(sa_column=Column(sa.JSON, nullable=False))
    revision: int = Field(default=1)
    content_digest: str = Field(max_length=71)
    # RUN state is read from the canonical coordinator snapshot, not this field.
    status: str = Field(max_length=32)
    dependencies: dict = Field(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AdlcProjectRevision(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_project_revision"
    resource_id: UUID = Field(foreign_key="adlc_project_resource.id", primary_key=True)
    revision: int = Field(primary_key=True)
    content_digest: str = Field(max_length=71)
    payload: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    authored_by: UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utc_now)


class AdlcProjectDecision(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_project_decision"
    __table_args__ = (sa.UniqueConstraint("resource_id", "resource_revision", name="uq_adlc_project_decision"),)
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    project_id: UUID = Field(foreign_key="folder.id", index=True)
    resource_id: UUID = Field(foreign_key="adlc_project_resource.id", index=True)
    resource_revision: int
    content_digest: str = Field(max_length=71)
    policy_revision: int
    action: str = Field(max_length=64)
    decision: str = Field(max_length=32)
    decided_by: UUID = Field(foreign_key="user.id")
    comment: str = Field(max_length=2000)
    dependencies: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class AdlcProjectCommand(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_project_command"
    project_id: UUID = Field(foreign_key="folder.id", primary_key=True)
    actor_id: UUID = Field(foreign_key="user.id", primary_key=True)
    command_key: str = Field(primary_key=True, max_length=128)
    request_digest: str = Field(max_length=71)
    resource_id: UUID = Field(foreign_key="adlc_project_resource.id")
    resource_revision: int

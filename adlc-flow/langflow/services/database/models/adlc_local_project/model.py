"""Owner-scoped local source configuration for an existing workflow project."""

from uuid import UUID

from sqlalchemy import Column, ForeignKey, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


class AdlcLocalProject(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "adlc_local_project"

    project_id: UUID = Field(sa_column=Column(ForeignKey("folder.id", ondelete="CASCADE"), primary_key=True))
    owner_id: str = Field(index=True, max_length=64)
    source_path: str = Field(sa_column=Column(Text, nullable=False))

    __table_args__ = (UniqueConstraint("owner_id", "source_path", name="uq_adlc_local_project_source"),)

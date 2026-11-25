"""LI-02 verified identity, inbound receipts and transactional delivery intents."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Column, Field, SQLModel


class AdlcLarkLink(SQLModel, table=True):
    __tablename__ = "adlc_lark_link"
    __table_args__ = (
        sa.UniqueConstraint("app_id", "tenant_key", "open_id", name="uq_lark_external_identity"),
        sa.UniqueConstraint("pair_digest", name="uq_lark_pair_digest"),
    )
    owner_id: UUID = Field(foreign_key="user.id", primary_key=True)
    app_id: str = Field(max_length=256)
    tenant_key: str | None = Field(default=None, max_length=256)
    open_id: str | None = Field(default=None, max_length=256)
    project_id: UUID | None = Field(default=None, foreign_key="folder.id")
    revision: int = 0
    linked_at: datetime | None = None
    pair_digest: str | None = Field(default=None, max_length=64)
    pair_expires_at: datetime | None = None
    password_failures: int = 0
    cooldown_until: datetime | None = None


class AdlcLarkInbound(SQLModel, table=True):
    __tablename__ = "adlc_lark_inbound"
    __table_args__ = (
        sa.UniqueConstraint("app_id", "tenant_key", "event_id", name="uq_lark_inbound_event"),
        sa.UniqueConstraint("app_id", "tenant_key", "message_id", name="uq_lark_inbound_message"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    app_id: str = Field(max_length=256)
    tenant_key: str = Field(max_length=256)
    event_id: str = Field(max_length=256)
    message_id: str = Field(max_length=256)
    content_digest: str = Field(max_length=71)
    source: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    result: dict = Field(sa_column=Column(sa.JSON, nullable=False))
    request_id: UUID | None = Field(default=None, foreign_key="adlc_intake_request.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdlcLarkOutbox(SQLModel, table=True):
    __tablename__ = "adlc_lark_outbox"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    inbound_id: UUID = Field(foreign_key="adlc_lark_inbound.id", index=True)
    owner_id: UUID | None = Field(default=None, foreign_key="user.id")
    link_revision: int | None = None
    chat_id: str = Field(max_length=256)
    reply_to: str = Field(max_length=256)
    text: str = Field(max_length=4000)
    state: str = Field(default="PENDING", max_length=32, index=True)
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lease_id: UUID | None = None
    leased_at: datetime | None = None
    provider_message_id: str | None = Field(default=None, max_length=256)
    result_digest: str | None = Field(default=None, max_length=71)
    error_code: str | None = Field(default=None, max_length=80)

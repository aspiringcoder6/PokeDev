"""LI-03 explicit chat/message bindings; no implicit group authorization."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlmodel import Field, SQLModel


class AdlcLarkConversation(SQLModel, table=True):
    __tablename__ = "adlc_lark_conversation"
    __table_args__ = (
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "request_id", name="uq_lark_chat_request"),
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "anchor_id", name="uq_lark_chat_anchor"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    app_id: str = Field(max_length=256)
    tenant_key: str = Field(max_length=256)
    chat_id: str = Field(max_length=256)
    chat_type: str = Field(max_length=16)
    anchor_id: str = Field(max_length=256)
    thread_id: str | None = Field(default=None, max_length=256)
    request_id: UUID = Field(foreign_key="adlc_intake_request.id", index=True)
    owner_id: UUID = Field(foreign_key="user.id")
    link_revision: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdlcLarkMessageAlias(SQLModel, table=True):
    __tablename__ = "adlc_lark_message_alias"
    __table_args__ = (
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "message_id", name="uq_lark_message_alias"),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    app_id: str = Field(max_length=256)
    tenant_key: str = Field(max_length=256)
    chat_id: str = Field(max_length=256)
    message_id: str = Field(max_length=256)
    conversation_id: UUID = Field(foreign_key="adlc_lark_conversation.id", index=True)


class AdlcLarkDeliveryRoute(SQLModel, table=True):
    __tablename__ = "adlc_lark_delivery_route"
    __table_args__ = (sa.CheckConstraint("wire_version IN (1, 2)", name="ck_lark_route_wire_version"),)
    delivery_id: UUID = Field(foreign_key="adlc_lark_outbox.id", primary_key=True)
    conversation_id: UUID | None = Field(default=None, foreign_key="adlc_lark_conversation.id")
    wire_version: int
    chat_type: str = Field(max_length=16)
    reply_in_thread: bool = False

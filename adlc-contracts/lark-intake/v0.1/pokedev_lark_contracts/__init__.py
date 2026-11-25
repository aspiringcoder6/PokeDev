"""LI-02 wire contract shared by the backend and Lark connector."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InboundMessage(Closed):
    version: Literal["1"] = "1"
    app_id: Identifier
    tenant_key: Identifier
    event_id: Identifier
    message_id: Identifier
    chat_id: Identifier
    open_id: Identifier
    kind: Literal["text", "pair", "unsupported"]
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    pair_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parent_id: Identifier | None = None
    root_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_body(self):
        if self.kind == "text" and (
            not self.text or not self.text.strip() or self.pair_digest is not None
        ):
            raise ValueError("TEXT_BODY_REQUIRED")
        if self.kind == "pair" and (self.pair_digest is None or self.text is not None):
            raise ValueError("PAIR_DIGEST_REQUIRED")
        if self.kind == "unsupported" and (
            self.text is not None or self.pair_digest is not None
        ):
            raise ValueError("UNSUPPORTED_BODY_FORBIDDEN")
        return self


class IngestReceipt(Closed):
    event_id: str
    status: Literal[
        "LINKED", "LINK_REQUIRED", "CREATED", "IGNORED", "DENIED", "PAIR_REJECTED"
    ]
    request_id: UUID | None = None
    replayed: bool = False


class Delivery(Closed):
    id: UUID
    lease_id: UUID
    chat_id: Identifier
    reply_to: Identifier
    text: str = Field(min_length=1, max_length=4000)
    uuid: UUID


class DeliveryBatch(Closed):
    items: list[Delivery]


class DeliveryResult(Closed):
    lease_id: UUID
    state: Literal["DELIVERED", "UNCONFIRMED", "FAILED", "RETRY"]
    provider_message_id: Identifier | None = None
    retry_after: int = Field(default=60, ge=1, le=3600)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")

    @model_validator(mode="after")
    def receipt_required(self):
        if self.state == "DELIVERED" and self.provider_message_id is None:
            raise ValueError("PROVIDER_MESSAGE_ID_REQUIRED")
        return self

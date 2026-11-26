"""LI-03 wire v2. The package root continues to expose the frozen v1 models."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from . import Closed, Identifier
from . import Delivery as DeliveryV1
from . import DeliveryResult as DeliveryResultV1
from . import InboundMessage as InboundMessageV1


class InboundMessage(InboundMessageV1):
    version: Literal["2"] = "2"
    chat_type: Literal["p2p", "group"] = "p2p"
    thread_id: Identifier | None = None
    mentioned_open_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    discovery: bool = False

    @model_validator(mode="after")
    def validate_discovery(self):
        if self.discovery and (self.chat_type != "group" or self.kind != "unsupported"):
            raise ValueError("DISCOVERY_METADATA_ONLY")
        return self


class IngestReceipt(Closed):
    version: Literal["2"] = "2"
    event_id: str
    status: Literal[
        "LINKED",
        "LINK_REQUIRED",
        "CREATED",
        "IGNORED",
        "DENIED",
        "PAIR_REJECTED",
        "APPENDED",
        "TARGET_REQUIRED",
    ]
    request_id: UUID | None = None
    replayed: bool = False


class Delivery(DeliveryV1):
    version: Literal["2"] = "2"
    reply_in_thread: bool = False


class DeliveryBatch(Closed):
    version: Literal["2"] = "2"
    items: list[Delivery]


class DeliveryResult(DeliveryResultV1):
    version: Literal["2"] = "2"


class ConversationEntry(Closed):
    id: UUID
    received_at: str
    chat_type: Literal["p2p", "group"]
    message_id: Identifier
    parent_id: Identifier | None = None
    root_id: Identifier | None = None
    thread_id: Identifier | None = None
    text: str
    action: Literal["CREATED", "APPENDED"]


class ConversationPage(Closed):
    enabled: bool
    items: list[ConversationEntry]
    total: int


class GroupPolicy(Closed):
    project_id: UUID | None = None
    unmentioned_replies_verified: bool = Field(default=False, strict=True)

"""LI-03 durable conversation anchors, aliases and versioned send routes."""

import json
import re
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from alembic import op

from langflow.alembic.versions.li02a2b3c4d5_add_lark_intake import _compatible

revision = "li03a2b3c4d5"
down_revision = "li02a2b3c4d5"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name in ("user", "adlc_intake_request", "adlc_lark_outbox"):
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    conversation = sa.Table(
        "adlc_lark_conversation",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("app_id", sa.String(256), nullable=False),
        sa.Column("tenant_key", sa.String(256), nullable=False),
        sa.Column("chat_id", sa.String(256), nullable=False),
        sa.Column("chat_type", sa.String(16), nullable=False),
        sa.Column("anchor_id", sa.String(256), nullable=False),
        sa.Column("thread_id", sa.String(256)),
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("adlc_intake_request.id"), nullable=False, index=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("link_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "request_id", name="uq_lark_chat_request"),
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "anchor_id", name="uq_lark_chat_anchor"),
    )
    aliases = sa.Table(
        "adlc_lark_message_alias",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("app_id", sa.String(256), nullable=False),
        sa.Column("tenant_key", sa.String(256), nullable=False),
        sa.Column("chat_id", sa.String(256), nullable=False),
        sa.Column("message_id", sa.String(256), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("adlc_lark_conversation.id"), nullable=False, index=True),
        sa.UniqueConstraint("app_id", "tenant_key", "chat_id", "message_id", name="uq_lark_message_alias"),
    )
    routes = sa.Table(
        "adlc_lark_delivery_route",
        metadata,
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("adlc_lark_outbox.id"), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("adlc_lark_conversation.id")),
        sa.Column("wire_version", sa.Integer(), nullable=False),
        sa.Column("chat_type", sa.String(16), nullable=False),
        sa.Column("reply_in_thread", sa.Boolean(), nullable=False),
        sa.CheckConstraint("wire_version IN (1, 2)", name="ck_lark_route_wire_version"),
    )
    return conversation, aliases, routes


def backfill(connection):
    """Adopt only persisted LI-02 CREATED DM facts; never infer another channel."""
    conversation, aliases, routes = tables()
    metadata = sa.MetaData()
    inbound = sa.Table("adlc_lark_inbound", metadata, autoload_with=connection)
    request = sa.Table("adlc_intake_request", metadata, autoload_with=connection)
    outbox = sa.Table("adlc_lark_outbox", metadata, autoload_with=connection)
    records = (
        connection.execute(sa.select(inbound, request.c.owner_id).join(request, request.c.id == inbound.c.request_id))
        .mappings()
        .all()
    )
    for row in records:
        source = json.loads(row["source"]) if isinstance(row["source"], str) else row["source"]
        result = json.loads(row["result"]) if isinstance(row["result"], str) else row["result"]
        if result.get("status") != "CREATED" or source.get("version") != "1" or source.get("parent_id"):
            continue
        if not all(
            isinstance(source.get(key), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", source[key])
            for key in ("app_id", "tenant_key", "chat_id", "message_id")
        ):
            raise RuntimeError("Refusing to backfill an invalid persisted Lark source")
        deliveries = connection.execute(sa.select(outbox).where(outbox.c.inbound_id == row["id"])).mappings().all()
        owned = [
            item for item in deliveries if item["owner_id"] == row["owner_id"] and item["link_revision"] is not None
        ]
        if not owned:
            continue
        request_id, owner_id = UUID(str(row["request_id"])), UUID(str(row["owner_id"]))
        identity = uuid5(
            NAMESPACE_URL,
            f"lark-conversation:{source['app_id']}:{source['tenant_key']}:{source['chat_id']}:{request_id}",
        )
        scope = {key: source[key] for key in ("app_id", "tenant_key", "chat_id")}
        connection.execute(
            conversation.insert().values(
                id=identity,
                **scope,
                chat_type="p2p",
                anchor_id=source["message_id"],
                thread_id=None,
                request_id=request_id,
                owner_id=owner_id,
                link_revision=owned[0]["link_revision"],
                created_at=row["created_at"],
            )
        )
        message_ids = {source["message_id"]}
        for item in owned:
            connection.execute(
                routes.insert().values(
                    delivery_id=UUID(str(item["id"])),
                    conversation_id=identity,
                    wire_version=1,
                    chat_type="p2p",
                    reply_in_thread=False,
                )
            )
            if item["state"] == "DELIVERED" and item["provider_message_id"]:
                message_ids.add(item["provider_message_id"])
        for message_id in message_ids:
            connection.execute(
                aliases.insert().values(
                    id=uuid5(identity, message_id),
                    **scope,
                    message_id=message_id,
                    conversation_id=identity,
                )
            )


def upgrade():
    connection = op.get_bind()
    for table in tables():
        if sa.inspect(connection).has_table(table.name):
            if not _compatible(connection, table) or connection.scalar(sa.select(sa.func.count()).select_from(table)):
                raise RuntimeError(f"Refusing to adopt incompatible or populated Lark conversation table: {table.name}")
        else:
            table.create(connection)
    backfill(connection)


def downgrade():
    raise RuntimeError("Conversation evidence requires an explicit preservation migration")

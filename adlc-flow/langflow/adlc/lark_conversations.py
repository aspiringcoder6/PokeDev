"""LI-03 source routing. Conversation evidence never edits or approves a brief."""

import os
import re
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from pokedev_lark_contracts import InboundMessage as LegacyMessage
from pokedev_lark_contracts import v2
from sqlmodel import col, select

from langflow.adlc import intake, lark_intake
from langflow.adlc.intake_models import CreateIntake, IntakeContent
from langflow.services.database.models.adlc_lark import AdlcLarkInbound, AdlcLarkLink, AdlcLarkOutbox
from langflow.services.database.models.adlc_lark_conversation import (
    AdlcLarkConversation,
    AdlcLarkDeliveryRoute,
    AdlcLarkMessageAlias,
)
from langflow.services.database.models.user.model import User

TARGET = re.compile(r"^/intake\s+([0-9a-fA-F-]{36})\s+(.+)$", re.DOTALL)
GUIDANCE = "Chưa xác định được một hồ sơ duy nhất. Bạn reply vào đúng tin đã theo dõi, dùng /intake <ID hồ sơ> <nội dung>, hoặc /new <nội dung> để tạo mới. Trong nhóm, bạn nhớ @bot."


def require_enabled(config):
    if not config.conversations_enabled:
        raise intake.IntakeError("LARK_CONVERSATIONS_DISABLED", 404)


def scope(model, message):
    return (model.app_id == message.app_id, model.tenant_key == message.tenant_key, model.chat_id == message.chat_id)


async def bind(session, message, request_id, owner_id, link_revision, *, explicit=False):
    row = (
        await session.exec(
            select(AdlcLarkConversation).where(
                *scope(AdlcLarkConversation, message),
                AdlcLarkConversation.request_id == request_id,
            )
        )
    ).one_or_none()
    if row is None:
        row = AdlcLarkConversation(
            app_id=message.app_id,
            tenant_key=message.tenant_key,
            chat_id=message.chat_id,
            chat_type=getattr(message, "chat_type", "p2p"),
            anchor_id=message.message_id,
            thread_id=getattr(message, "thread_id", None),
            request_id=request_id,
            owner_id=owner_id,
            link_revision=link_revision,
        )
        session.add(row)
        await session.flush()
    elif row.owner_id != owner_id or row.chat_type != getattr(message, "chat_type", "p2p"):
        raise intake.IntakeError("LARK_CONVERSATION_DENIED", 403)
    elif explicit:
        row.link_revision = link_revision
        session.add(row)
        await session.flush()
    return row


async def alias(session, conversation, message_id):
    previous = (
        await session.exec(
            select(AdlcLarkMessageAlias).where(
                *scope(AdlcLarkMessageAlias, conversation),
                AdlcLarkMessageAlias.message_id == message_id,
            )
        )
    ).one_or_none()
    if previous:
        if previous.conversation_id != conversation.id:
            raise intake.IntakeError("LARK_ALIAS_CONFLICT")
        return
    session.add(
        AdlcLarkMessageAlias(
            app_id=conversation.app_id,
            tenant_key=conversation.tenant_key,
            chat_id=conversation.chat_id,
            message_id=message_id,
            conversation_id=conversation.id,
        )
    )
    await session.flush()


async def verified_link(session, owner_id, revision, config):
    # Native link/unlink reauthentication locks User first. Use that same order
    # so revocation and intake acceptance cannot pass each other on PostgreSQL.
    user = (await session.exec(select(User).where(User.id == owner_id).with_for_update())).one_or_none()
    if user is None:
        raise intake.IntakeError("LARK_LINK_INACTIVE", 403)
    return await lark_intake.active_link(session, owner_id, revision, config)


async def delivered_alias(session, delivery_id, provider_message_id):
    route = await session.get(AdlcLarkDeliveryRoute, delivery_id)
    if route and route.conversation_id:
        conversation = await session.get(AdlcLarkConversation, route.conversation_id)
        await alias(session, conversation, provider_message_id)


async def authorize(session, conversation, link, config):
    if conversation.owner_id != link.owner_id or conversation.link_revision != link.revision:
        raise intake.IntakeError("LARK_CONVERSATION_DENIED", 403)
    request = await intake.owned(session, intake.IntakeActor(link.owner_id), conversation.request_id, lock_project=True)
    if request.status != "NEW":
        raise intake.IntakeError("INTAKE_CLOSED")
    if conversation.chat_type == "group":
        policy = config.groups.get(conversation.chat_id)
        if policy is None or policy.project_id != request.project_id:
            raise intake.IntakeError("LARK_GROUP_PROJECT_DENIED", 403)
    return request


async def delivery_allowed(session, delivery, route, config):
    if route.wire_version == 2 and not config.conversations_enabled:
        return False
    if route.chat_type == "group" and delivery.chat_id not in config.groups:
        return False
    if not route.conversation_id:
        return True
    conversation = await session.get(AdlcLarkConversation, route.conversation_id, populate_existing=True)
    if conversation is None or conversation.chat_id != delivery.chat_id:
        return False
    try:
        link = await verified_link(session, conversation.owner_id, conversation.link_revision, config)
        await authorize(session, conversation, link, config)
    except intake.IntakeError:
        return False
    return True


async def candidates(session, message):
    anchors = {value for value in (message.parent_id, message.root_id) if value}
    identities = set()
    if anchors:
        identities.update(
            (
                await session.exec(
                    select(AdlcLarkMessageAlias.conversation_id).where(
                        *scope(AdlcLarkMessageAlias, message),
                        col(AdlcLarkMessageAlias.message_id).in_(anchors),
                    )
                )
            ).all()
        )
    if message.thread_id:
        identities.update(
            (
                await session.exec(
                    select(AdlcLarkConversation.id).where(
                        *scope(AdlcLarkConversation, message),
                        AdlcLarkConversation.thread_id == message.thread_id,
                    )
                )
            ).all()
        )
    return identities


async def track_thread(session, conversation, message):
    if not message.thread_id:
        return True
    if conversation.thread_id is not None:
        return conversation.thread_id == message.thread_id
    updated = await session.execute(
        sa.update(AdlcLarkConversation)
        .where(
            AdlcLarkConversation.id == conversation.id,
            col(AdlcLarkConversation.thread_id).is_(None),
        )
        .values(thread_id=message.thread_id)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        raise intake.IntakeError("INTAKE_REVISION_CONFLICT")
    return True


async def process_text(session, message, link, config):
    body = message.text.strip()
    selection = TARGET.fullmatch(body)
    explicit, create_new = bool(selection), body.startswith("/new ")
    if explicit:
        try:
            target = UUID(selection[1])
        except ValueError:
            return "TARGET_REQUIRED", None, GUIDANCE
        body = selection[2].strip()
        request = await intake.owned(session, intake.IntakeActor(link.owner_id), target, lock_project=True)
        if request.status != "NEW":
            raise intake.IntakeError("INTAKE_CLOSED")
        if message.chat_type == "group" and config.groups[message.chat_id].project_id != request.project_id:
            raise intake.IntakeError("LARK_GROUP_PROJECT_DENIED", 403)
        conversation = await bind(session, message, target, link.owner_id, link.revision, explicit=True)
    elif body.startswith(("/intake", "/new")) and not create_new:
        return "TARGET_REQUIRED", None, GUIDANCE
    else:
        ids = await candidates(session, message)
        if create_new:
            body = body[5:].strip()
            ids = set()
        if not body:
            return "TARGET_REQUIRED", None, GUIDANCE
        is_root = not message.parent_id and (not message.root_id or message.root_id == message.message_id)
        if (
            not create_new
            and len(ids) != 1
            and (ids or not is_root or (message.thread_id and message.root_id != message.message_id))
        ):
            return "TARGET_REQUIRED", None, GUIDANCE
        if ids:
            conversation = await session.get(AdlcLarkConversation, next(iter(ids)), populate_existing=True)
            await authorize(session, conversation, link, config)
            if not await track_thread(session, conversation, message):
                return "TARGET_REQUIRED", None, GUIDANCE
        else:
            project = config.groups[message.chat_id].project_id if message.chat_type == "group" else link.project_id
            created = await intake.create(
                session,
                intake.IntakeActor(link.owner_id),
                CreateIntake(
                    command_id=uuid5(NAMESPACE_URL, f"lark:{message.app_id}:{message.tenant_key}:{message.message_id}"),
                    project_id=project,
                    content=IntakeContent(title=body.splitlines()[0][:200], description=body),
                ),
            )
            conversation = await bind(session, message, UUID(created["request"]["id"]), link.owner_id, link.revision)
            return "CREATED", conversation, "Đã tạo hồ sơ yêu cầu riêng của bạn."
    return "APPENDED", conversation, "Đã lưu tin bổ sung vào hồ sơ của bạn; nội dung brief chưa được thay đổi."


def matches_previous(previous, message, fingerprint):
    if previous.content_digest == fingerprint:
        return True
    if previous.source.get("version") != "1" or message.chat_type != "p2p":
        return False
    legacy = LegacyMessage.model_validate(
        {
            **{
                key: value
                for key, value in message.model_dump(mode="json").items()
                if key in LegacyMessage.model_fields
            },
            "version": "1",
        }
    )
    return previous.content_digest == intake.digest(legacy.model_dump(mode="json", exclude={"event_id"}))


async def ingest(session, message: v2.InboundMessage, config):
    require_enabled(config)
    if message.app_id != config.app_id or message.tenant_key != config.tenant_key:
        raise intake.IntakeError("LARK_SOURCE_DENIED", 403)
    fingerprint = intake.digest(message.model_dump(mode="json", exclude={"event_id"}))
    previous_rows = (
        await session.exec(
            select(AdlcLarkInbound).where(
                AdlcLarkInbound.app_id == message.app_id,
                AdlcLarkInbound.tenant_key == message.tenant_key,
                sa.or_(AdlcLarkInbound.event_id == message.event_id, AdlcLarkInbound.message_id == message.message_id),
            )
        )
    ).all()
    if len(previous_rows) > 1:
        raise intake.IntakeError("LARK_EVENT_CONFLICT")
    previous = previous_rows[0] if previous_rows else None
    if previous:
        if not matches_previous(previous, message, fingerprint):
            raise intake.IntakeError("LARK_EVENT_CONFLICT")
        return v2.IngestReceipt.model_validate(
            {**previous.result, "version": "2", "event_id": message.event_id, "replayed": True}
        )
    group = message.chat_type == "group"
    policy = config.groups.get(message.chat_id) if group else None
    mentioned = config.bot_open_id in message.mentioned_open_ids
    tracked_reply = False
    if group and not mentioned and policy and policy.unmentioned_replies_verified:
        is_reply = bool(
            message.parent_id
            or (message.root_id and message.root_id != message.message_id)
            or (message.thread_id and not message.root_id)
        )
        tracked_reply = is_reply and bool(await candidates(session, message))
    if message.discovery or (group and (policy is None or (not mentioned and not tracked_reply))):
        status, text, conversation, link = "IGNORED", None, None, None
    elif message.kind == "pair" and not group:
        legacy = LegacyMessage.model_validate(
            {
                **{
                    key: value
                    for key, value in message.model_dump(mode="json").items()
                    if key in LegacyMessage.model_fields
                },
                "version": "1",
            }
        )
        receipt = await lark_intake.ingest(session, legacy, config)
        return v2.IngestReceipt.model_validate({**receipt.model_dump(mode="json"), "version": "2"})
    else:
        status, text, conversation, link = "IGNORED", None, None, None
        if message.kind == "pair":
            # A code posted to a group is exposed. Consume it without linking.
            await session.execute(
                sa.update(AdlcLarkLink)
                .where(
                    AdlcLarkLink.app_id == config.app_id,
                    AdlcLarkLink.pair_digest == message.pair_digest,
                )
                .values(pair_digest=None, pair_expires_at=None)
            )
            status, text = (
                "PAIR_REJECTED",
                "Mã liên kết chỉ dùng trong DM. Bạn tạo mã mới trong PokeDev rồi gửi riêng cho bot.",
            )
        elif message.kind == "unsupported":
            text = "Hiện chỉ nhận văn bản. Bạn gửi nội dung mới hoặc reply vào đúng hồ sơ; trong nhóm hãy @bot."
        else:
            link = (
                await session.exec(
                    select(AdlcLarkLink).where(
                        AdlcLarkLink.app_id == message.app_id,
                        AdlcLarkLink.tenant_key == message.tenant_key,
                        AdlcLarkLink.open_id == message.open_id,
                    )
                )
            ).one_or_none()
            if link is None:
                status, text = (
                    "LINK_REQUIRED",
                    "Bạn cần liên kết tài khoản qua " + config.public_url + "/intake trước khi giao việc.",
                )
            else:
                try:
                    link = await verified_link(session, link.owner_id, link.revision, config)
                    status, conversation, text = await process_text(session, message, link, config)
                except intake.IntakeError as exc:
                    if exc.code in {"INTAKE_REVISION_CONFLICT", "LARK_ALIAS_CONFLICT"}:
                        raise
                    status, text, conversation = (
                        "DENIED",
                        "Không thể ghi vào hồ sơ này. Bạn kiểm tra tài khoản, quyền dự án và đích hội thoại trong PokeDev.",
                        None,
                    )
    receipt = v2.IngestReceipt(
        event_id=message.event_id, status=status, request_id=conversation.request_id if conversation else None
    )
    row = AdlcLarkInbound(
        app_id=message.app_id,
        tenant_key=message.tenant_key,
        event_id=message.event_id,
        message_id=message.message_id,
        content_digest=fingerprint,
        source=message.model_dump(mode="json"),
        result=receipt.model_dump(mode="json"),
        request_id=receipt.request_id,
    )
    session.add(row)
    await session.flush()
    if conversation:
        await alias(session, conversation, message.message_id)
    if text:
        if conversation:
            text += " Mở hồ sơ: " + config.public_url + "/intake/" + str(conversation.request_id)
        if group:
            text += " Khi bổ sung trong thread, bạn @bot để bảo đảm nhận được tin."
        delivery = AdlcLarkOutbox(
            inbound_id=row.id,
            owner_id=link.owner_id if conversation else None,
            link_revision=link.revision if conversation else None,
            chat_id=message.chat_id,
            reply_to=message.message_id,
            text=text,
        )
        session.add(delivery)
        await session.flush()
        session.add(
            AdlcLarkDeliveryRoute(
                delivery_id=delivery.id,
                conversation_id=conversation.id if conversation else None,
                wire_version=2,
                chat_type=message.chat_type,
                reply_in_thread=group,
            )
        )
        await session.flush()
    return receipt


async def history(session, actor, request_id, *, limit=50, offset=0):
    await intake.owned(session, actor, request_id)
    condition = AdlcLarkInbound.request_id == request_id
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(AdlcLarkInbound).where(condition))
    ).scalar_one()
    rows = (
        await session.exec(
            select(AdlcLarkInbound)
            .where(condition)
            .order_by(col(AdlcLarkInbound.created_at).desc(), AdlcLarkInbound.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    entries = [
        v2.ConversationEntry(
            id=row.id,
            received_at=intake.timestamp(row.created_at),
            chat_type=row.source.get("chat_type", "p2p"),
            message_id=row.source["message_id"],
            parent_id=row.source.get("parent_id"),
            root_id=row.source.get("root_id"),
            thread_id=row.source.get("thread_id"),
            text=row.source["text"],
            action=row.result["status"],
        )
        for row in reversed(rows)
    ]
    enabled = total > 0 or os.getenv("POKEDEV_LARK_CONVERSATIONS_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return v2.ConversationPage(enabled=enabled, items=entries, total=total)

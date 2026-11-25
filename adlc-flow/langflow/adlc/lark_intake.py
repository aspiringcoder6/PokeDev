"""Verified DM intake. No model, readiness worker or workflow execution calls."""

import asyncio
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import sqlalchemy as sa
from pokedev_lark_contracts import Delivery, DeliveryBatch, DeliveryResult, InboundMessage, IngestReceipt
from sqlmodel import col, select

from langflow.adlc import intake
from langflow.adlc.intake_models import CreateIntake, IntakeContent
from langflow.services.database.models.adlc_lark import AdlcLarkInbound, AdlcLarkLink, AdlcLarkOutbox
from langflow.services.database.models.user.model import User


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Settings:
    app_id: str
    tenant_key: str
    secret: str
    public_url: str


def settings():
    if (
        os.getenv("POKEDEV_LARK_INTAKE_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}
        or not intake.enabled()
    ):
        raise intake.IntakeError("LARK_DISABLED", 404)
    values = [
        os.getenv(key, "")
        for key in ("POKEDEV_LARK_APP_ID", "POKEDEV_LARK_TENANT_KEY", "POKEDEV_LARK_CONNECTOR_SECRET")
    ]
    url = os.getenv("POKEDEV_PUBLIC_URL", "http://127.0.0.1:7862").rstrip("/")
    parsed = urlsplit(url)
    if (
        not all(values)
        or len(values[2]) < 32
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise intake.IntakeError("LARK_CONFIGURATION_REQUIRED", 503)
    return Settings(*values, url)


async def link_status(session, actor, config):
    row = await session.get(AdlcLarkLink, actor.id)
    user = await session.get(User, actor.id)
    linked = bool(row and row.app_id == config.app_id and row.open_id)
    return {
        "enabled": True,
        "username": user.username,
        "linked": linked,
        "project_id": str(row.project_id) if linked and row.project_id else None,
        "linked_at": intake.timestamp(row.linked_at) if linked else None,
    }


async def reauthenticate(session, actor, config, password_check):
    user = (await session.exec(select(User).where(User.id == actor.id).with_for_update())).one_or_none()
    if user is None or not user.is_active:
        raise intake.IntakeError("LARK_USER_INACTIVE", 403)
    row = await session.get(AdlcLarkLink, actor.id, populate_existing=True)
    if row is None:
        row = AdlcLarkLink(owner_id=actor.id, app_id=config.app_id)
        session.add(row)
        await session.flush()
    if row.cooldown_until and utc(row.cooldown_until) > now():
        raise intake.IntakeError("LARK_REAUTH_RATE_LIMIT", 429)
    valid = await asyncio.to_thread(password_check, user.password)
    if not valid:
        await session.execute(
            sa.update(AdlcLarkLink)
            .where(AdlcLarkLink.owner_id == actor.id)
            .values(
                password_failures=AdlcLarkLink.password_failures + 1,
                cooldown_until=sa.case(
                    (AdlcLarkLink.password_failures >= 4, now() + timedelta(minutes=5)),
                    else_=AdlcLarkLink.cooldown_until,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        # Preserve failed checks even though the HTTP operation is rejected.
        await session.commit()
        raise intake.IntakeError("LARK_REAUTH_REQUIRED", 403)
    row.password_failures = 0
    row.cooldown_until = None
    return row


async def start_link(session, actor, config, project_id, password_check):
    row = await reauthenticate(session, actor, config, password_check)
    if row.open_id:
        raise intake.IntakeError("LARK_ALREADY_LINKED")
    await intake.project_access(session, actor, project_id, lock=True)
    code = secrets.token_urlsafe(24)
    row.app_id = config.app_id
    row.project_id = project_id
    row.pair_digest = hashlib.sha256(code.encode()).hexdigest()
    row.pair_expires_at = now() + timedelta(minutes=10)
    row.revision += 1
    session.add(row)
    await session.flush()
    return {"command": "/link " + code, "expires_at": intake.timestamp(row.pair_expires_at)}


async def unlink(session, actor, config, password_check):
    row = await reauthenticate(session, actor, config, password_check)
    row.open_id = row.tenant_key = row.linked_at = row.pair_digest = row.pair_expires_at = None
    row.project_id = None
    row.revision += 1
    session.add(row)
    await session.execute(
        sa.update(AdlcLarkOutbox)
        .where(AdlcLarkOutbox.owner_id == actor.id, AdlcLarkOutbox.state == "PENDING")
        .values(state="BLOCKED", error_code="LINK_REVOKED")
    )
    await session.flush()
    return {"linked": False}


async def active_link(session, owner_id, revision, config):
    user = await session.get(User, owner_id, populate_existing=True)
    link = await session.get(AdlcLarkLink, owner_id, populate_existing=True)
    if (
        not user
        or not user.is_active
        or not link
        or not link.open_id
        or link.app_id != config.app_id
        or link.tenant_key != config.tenant_key
        or link.revision != revision
    ):
        raise intake.IntakeError("LARK_LINK_INACTIVE", 403)
    await intake.project_access(session, intake.IntakeActor(owner_id), link.project_id, lock=True)
    return link


async def pair_candidate(session, message, config):
    row = (
        await session.exec(
            select(AdlcLarkLink)
            .where(AdlcLarkLink.app_id == config.app_id, AdlcLarkLink.pair_digest == message.pair_digest)
            .with_for_update()
        )
    ).one_or_none()
    if not row or not row.pair_expires_at or utc(row.pair_expires_at) <= now() or row.open_id:
        return None
    existing = (
        await session.exec(
            select(AdlcLarkLink).where(
                AdlcLarkLink.app_id == config.app_id,
                AdlcLarkLink.tenant_key == config.tenant_key,
                AdlcLarkLink.open_id == message.open_id,
            )
        )
    ).first()
    user = await session.get(User, row.owner_id)
    if existing or not user or not user.is_active:
        return None
    try:
        await intake.project_access(session, intake.IntakeActor(row.owner_id), row.project_id, lock=True)
    except intake.IntakeError:
        return None
    return row


async def ingest(session, message: InboundMessage, config):
    if message.app_id != config.app_id or message.tenant_key != config.tenant_key:
        raise intake.IntakeError("LARK_SOURCE_DENIED", 403)
    fingerprint = intake.digest(message.model_dump(mode="json", exclude={"event_id"}))
    previous = (
        await session.exec(
            select(AdlcLarkInbound).where(
                AdlcLarkInbound.app_id == message.app_id,
                AdlcLarkInbound.tenant_key == message.tenant_key,
                sa.or_(AdlcLarkInbound.event_id == message.event_id, AdlcLarkInbound.message_id == message.message_id),
            )
        )
    ).first()
    if previous:
        if previous.content_digest != fingerprint:
            raise intake.IntakeError("LARK_EVENT_CONFLICT")
        return IngestReceipt.model_validate({**previous.result, "event_id": message.event_id, "replayed": True})
    status, request_id, owner, revision, text = "IGNORED", None, None, None, None
    if message.parent_id or message.kind == "unsupported":
        text = "Bước này chỉ nhận yêu cầu bằng tin nhắn văn bản mới trong DM. Bạn gửi một tin mới để tạo hồ sơ."
    elif message.kind == "pair":
        row = await pair_candidate(session, message, config)
        if row:
            updated = await session.execute(
                sa.update(AdlcLarkLink)
                .where(
                    AdlcLarkLink.owner_id == row.owner_id,
                    AdlcLarkLink.revision == row.revision,
                    AdlcLarkLink.pair_digest == message.pair_digest,
                    col(AdlcLarkLink.open_id).is_(None),
                )
                .values(
                    tenant_key=message.tenant_key,
                    open_id=message.open_id,
                    linked_at=now(),
                    pair_digest=None,
                    pair_expires_at=None,
                    revision=row.revision + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount != 1:
                raise intake.IntakeError("INTAKE_REVISION_CONFLICT")
            owner, revision, status = row.owner_id, row.revision + 1, "LINKED"
            text = "Đã liên kết tài khoản Lark với PokeDev. Mỗi tin nhắn văn bản mới trong DM này sẽ tạo một hồ sơ yêu cầu riêng."
        else:
            status, text = (
                "PAIR_REJECTED",
                "Mã liên kết không hợp lệ hoặc đã hết hạn. Bạn tạo mã mới trong PokeDev rồi gửi lại.",
            )
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
                "Bạn cần liên kết tài khoản trước khi giao việc. Mở "
                + config.public_url
                + "/intake và chọn Liên kết Lark.",
            )
        else:
            try:
                await active_link(session, link.owner_id, link.revision, config)
            except intake.IntakeError:
                status, text = (
                    "DENIED",
                    "Tài khoản hoặc quyền dự án đã thay đổi. Bạn kiểm tra lại liên kết trong PokeDev.",
                )
            else:
                content = message.text.strip()
                command = CreateIntake(
                    command_id=uuid5(NAMESPACE_URL, f"lark:{message.app_id}:{message.tenant_key}:{message.message_id}"),
                    project_id=link.project_id,
                    content=IntakeContent(title=content.splitlines()[0][:200], description=content),
                )
                created = await intake.create(session, intake.IntakeActor(link.owner_id), command)
                request_id, owner, revision, status = (
                    UUID(created["request"]["id"]),
                    link.owner_id,
                    link.revision,
                    "CREATED",
                )
                text = "Đã tạo hồ sơ yêu cầu của bạn. Mở hồ sơ: " + config.public_url + "/intake/" + str(request_id)
    receipt = IngestReceipt(event_id=message.event_id, status=status, request_id=request_id)
    row = AdlcLarkInbound(
        app_id=message.app_id,
        tenant_key=message.tenant_key,
        event_id=message.event_id,
        message_id=message.message_id,
        content_digest=fingerprint,
        source=message.model_dump(mode="json"),
        result=receipt.model_dump(mode="json"),
        request_id=request_id,
    )
    session.add(row)
    await session.flush()
    if text:
        session.add(
            AdlcLarkOutbox(
                inbound_id=row.id,
                owner_id=owner,
                link_revision=revision,
                chat_id=message.chat_id,
                reply_to=message.message_id,
                text=text,
            )
        )
        await session.flush()
    return receipt


async def claim(session, config):
    cutoff = now() - timedelta(seconds=60)
    scoped = select(AdlcLarkInbound.id).where(
        AdlcLarkInbound.app_id == config.app_id, AdlcLarkInbound.tenant_key == config.tenant_key
    )
    await session.execute(
        sa.update(AdlcLarkOutbox)
        .where(
            AdlcLarkOutbox.state == "SENDING",
            col(AdlcLarkOutbox.inbound_id).in_(scoped),
            AdlcLarkOutbox.leased_at < cutoff,
        )
        .values(state="UNCONFIRMED", error_code="LEASE_EXPIRED")
    )
    rows = (
        await session.exec(
            select(AdlcLarkOutbox)
            .where(
                AdlcLarkOutbox.state == "PENDING",
                col(AdlcLarkOutbox.inbound_id).in_(scoped),
                AdlcLarkOutbox.next_attempt_at <= now(),
            )
            .order_by(AdlcLarkOutbox.next_attempt_at)
            .limit(1)
        )
    ).all()
    items = []
    for row in rows:
        source = await session.get(AdlcLarkInbound, row.inbound_id)
        if source.app_id != config.app_id or source.tenant_key != config.tenant_key:
            continue
        if row.owner_id:
            try:
                await active_link(session, row.owner_id, row.link_revision, config)
            except intake.IntakeError:
                row.state, row.error_code = "BLOCKED", "AUTHORIZATION_CHANGED"
                session.add(row)
                continue
        lease = uuid4()
        result = await session.execute(
            sa.update(AdlcLarkOutbox)
            .where(AdlcLarkOutbox.id == row.id, AdlcLarkOutbox.state == "PENDING")
            .values(
                state="SENDING",
                lease_id=lease,
                leased_at=now(),
                attempts=AdlcLarkOutbox.attempts + 1,
                result_digest=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            items.append(
                Delivery(
                    id=row.id, lease_id=lease, chat_id=row.chat_id, reply_to=row.reply_to, text=row.text, uuid=row.id
                )
            )
    return DeliveryBatch(items=items)


async def delivery_result(session, config, identity, result: DeliveryResult):
    row = await session.get(AdlcLarkOutbox, identity, populate_existing=True)
    source = await session.get(AdlcLarkInbound, row.inbound_id) if row else None
    if not source or source.app_id != config.app_id or source.tenant_key != config.tenant_key:
        raise intake.IntakeError("LARK_DELIVERY_NOT_FOUND", 404)
    fingerprint = intake.digest(result.model_dump(mode="json"))
    if row.lease_id != result.lease_id:
        raise intake.IntakeError("LARK_DELIVERY_LEASE_CONFLICT")
    if row.result_digest == fingerprint:
        return {"state": row.state, "replayed": True}
    if row.state not in {"SENDING", "UNCONFIRMED"} or row.result_digest:
        raise intake.IntakeError("LARK_DELIVERY_RESULT_CONFLICT")
    state = (
        "PENDING"
        if result.state == "RETRY" and row.attempts < 5
        else "FAILED"
        if result.state == "RETRY"
        else result.state
    )
    updated = await session.execute(
        sa.update(AdlcLarkOutbox)
        .where(
            AdlcLarkOutbox.id == identity,
            AdlcLarkOutbox.lease_id == result.lease_id,
            col(AdlcLarkOutbox.result_digest).is_(None),
            col(AdlcLarkOutbox.state).in_(["SENDING", "UNCONFIRMED"]),
        )
        .values(
            state=state,
            provider_message_id=result.provider_message_id,
            next_attempt_at=now() + timedelta(seconds=result.retry_after),
            error_code=result.error_code,
            result_digest=fingerprint,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        raise intake.IntakeError("INTAKE_REVISION_CONFLICT")
    await session.flush()
    return {"state": state, "replayed": False}

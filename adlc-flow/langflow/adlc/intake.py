"""LI-01 durable intake. This module never calls an agent or execution service."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import col, select

from langflow.adlc.intake_models import CancelIntake, CreateIntake, UpdateIntake
from langflow.services.authorization import team_access
from langflow.services.database.models.adlc_intake import AdlcIntakeCommand, AdlcIntakeRequest, AdlcIntakeRevision
from langflow.services.database.models.auth.team_access import AdlcProjectAccess


@dataclass(frozen=True)
class IntakeActor:
    # Snapshot authenticated identity before a transaction rollback can expire
    # the ORM user. Project permissions are still queried on every operation.
    id: UUID


class IntakeError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def enabled() -> bool:
    return os.getenv("POKEDEV_INTAKE_ENABLED", "false").lower() in {"true", "1", "yes", "on"}


def digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def timestamp(value: datetime) -> str:
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)).isoformat()


def snapshot(row: AdlcIntakeRequest) -> dict:
    return {
        "id": str(row.id),
        "owner_id": str(row.owner_id),
        "project_id": str(row.project_id) if row.project_id else None,
        "revision": row.revision,
        "status": row.status,
        "content": row.content,
        "content_digest": row.content_digest,
        "created_at": timestamp(row.created_at),
        "updated_at": timestamp(row.updated_at),
    }


async def project_access(session, actor, project_id: UUID | None, *, lock=False):
    if project_id is None:
        return
    if lock:
        await session.exec(
            select(AdlcProjectAccess).where(AdlcProjectAccess.project_id == project_id).with_for_update()
        )
    try:
        # An intake remains private to its author. Project read permits proposing
        # a requirement, not editing shared contracts or approving execution.
        await team_access.require_permission(session, project_id, actor, "project:read")
    except team_access.TeamAccessError:
        raise IntakeError("INTAKE_NOT_FOUND", 404) from None


async def owned(session, actor, identity: UUID, *, lock_project=False):
    row = await session.get(AdlcIntakeRequest, identity, populate_existing=True)
    if row is None or row.owner_id != actor.id:
        raise IntakeError("INTAKE_NOT_FOUND", 404)
    await project_access(session, actor, row.project_id, lock=lock_project)
    return row


async def replay(session, actor, command_id, fingerprint):
    receipt = await session.get(AdlcIntakeCommand, (actor.id, command_id), populate_existing=True)
    if receipt is None:
        return None
    if receipt.input_digest != fingerprint:
        raise IntakeError("INTAKE_COMMAND_CONFLICT")
    await owned(session, actor, receipt.request_id)
    return {"request": receipt.result, "replayed": True}


async def record(session, actor, command_id, fingerprint, row):
    result = snapshot(row)
    session.add(
        AdlcIntakeRevision(
            request_id=row.id, revision=row.revision, actor_id=actor.id, command_id=command_id, snapshot=result
        )
    )
    session.add(
        AdlcIntakeCommand(
            owner_id=actor.id, command_id=command_id, request_id=row.id, input_digest=fingerprint, result=result
        )
    )
    await session.flush()
    return {"request": result, "replayed": False}


async def create(session, actor, command: CreateIntake):
    fingerprint = digest({"operation": "CREATE", **command.model_dump(mode="json", exclude={"command_id"})})
    previous = await replay(session, actor, command.command_id, fingerprint)
    if previous is not None:
        return previous
    await project_access(session, actor, command.project_id, lock=True)
    content = command.content.model_dump(mode="json")
    row = AdlcIntakeRequest(
        owner_id=actor.id, project_id=command.project_id, content=content, content_digest=digest(content)
    )
    session.add(row)
    await session.flush()
    return await record(session, actor, command.command_id, fingerprint, row)


async def change(session, actor, identity: UUID, command: UpdateIntake | CancelIntake):
    operation = "UPDATE" if isinstance(command, UpdateIntake) else "CANCEL"
    fingerprint = digest(
        {"operation": operation, "request_id": str(identity), **command.model_dump(mode="json", exclude={"command_id"})}
    )
    previous = await replay(session, actor, command.command_id, fingerprint)
    if previous is not None:
        return previous
    row = await owned(session, actor, identity, lock_project=True)
    if row.revision != command.expected_revision:
        raise IntakeError("INTAKE_REVISION_CONFLICT")
    if row.status != "NEW":
        raise IntakeError("INTAKE_CLOSED")
    content = command.content.model_dump(mode="json") if isinstance(command, UpdateIntake) else row.content
    result = await session.execute(
        sa.update(AdlcIntakeRequest)
        .where(
            AdlcIntakeRequest.id == identity,
            AdlcIntakeRequest.owner_id == actor.id,
            AdlcIntakeRequest.revision == command.expected_revision,
            AdlcIntakeRequest.status == "NEW",
        )
        .values(
            revision=command.expected_revision + 1,
            status="CANCELLED" if operation == "CANCEL" else "NEW",
            content=content,
            content_digest=digest(content),
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise IntakeError("INTAKE_REVISION_CONFLICT")
    await session.refresh(row)
    return await record(session, actor, command.command_id, fingerprint, row)


async def projects(session, actor):
    return [
        {"id": str(row["project_id"]), "name": row["name"]}
        for row in await team_access.visible_projects(session, actor)
    ]


async def listing(session, actor, *, limit=50, offset=0):
    visible = [UUID(row["id"]) for row in await projects(session, actor)]
    criteria = (
        AdlcIntakeRequest.owner_id == actor.id,
        sa.or_(col(AdlcIntakeRequest.project_id).is_(None), col(AdlcIntakeRequest.project_id).in_(visible)),
    )
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(AdlcIntakeRequest).where(*criteria))
    ).scalar_one()
    rows = (
        await session.exec(
            select(AdlcIntakeRequest)
            .where(*criteria)
            .order_by(col(AdlcIntakeRequest.updated_at).desc(), AdlcIntakeRequest.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {"items": [snapshot(row) for row in rows], "total": total}


async def history(session, actor, identity, *, before_revision=None, limit=50):
    await owned(session, actor, identity)
    query = select(AdlcIntakeRevision).where(AdlcIntakeRevision.request_id == identity)
    if before_revision is not None:
        query = query.where(AdlcIntakeRevision.revision < before_revision)
    rows = (await session.exec(query.order_by(col(AdlcIntakeRevision.revision).desc()).limit(limit))).all()
    return {
        "items": [
            {
                "revision": row.revision,
                "actor_id": str(row.actor_id),
                "created_at": timestamp(row.created_at),
                "snapshot": row.snapshot,
            }
            for row in rows
        ],
        "next_before_revision": rows[-1].revision if len(rows) == limit else None,
    }

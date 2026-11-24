from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from langflow.services.database.models.adlc_run_trigger.model import AdlcRunTrigger

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession


async def save_run_trigger(session: AsyncSession, *, row: AdlcRunTrigger) -> AdlcRunTrigger:
    """Insert or update one durable trigger row keyed by its trigger id."""
    existing = (await session.exec(select(AdlcRunTrigger).where(AdlcRunTrigger.id == row.id))).first()
    if existing is not None:
        existing.owner_id = row.owner_id
        existing.name = row.name
        existing.enabled = row.enabled
        existing.flow_id = row.flow_id
        existing.flow_name = row.flow_name
        existing.execution_mode = row.execution_mode
        existing.overlap_policy = row.overlap_policy
        existing.missed_policy = row.missed_policy
        existing.webhook_enabled = row.webhook_enabled
        existing.webhook_token = row.webhook_token
        existing.schedule_payload = row.schedule_payload
        existing.definitions_payload = row.definitions_payload
        existing.next_due_at = row.next_due_at
        existing.last_fired_at = row.last_fired_at
        existing.last_fire_status = row.last_fire_status
        existing.last_run_id = row.last_run_id
        existing.active_run_ids = row.active_run_ids
        existing.created_at = row.created_at
        session.add(existing)
        await session.flush()
        return existing
    session.add(row)
    await session.flush()
    return row


async def get_run_trigger(session: AsyncSession, *, trigger_id: UUID) -> AdlcRunTrigger | None:
    statement = select(AdlcRunTrigger).where(AdlcRunTrigger.id == trigger_id)
    return (await session.exec(statement)).first()


async def list_run_triggers(
    session: AsyncSession,
    *,
    owner_id: str | None = None,
    limit: int = 500,
) -> list[AdlcRunTrigger]:
    """Return durable trigger rows oldest first, optionally scoped to one owner."""
    statement = select(AdlcRunTrigger).order_by(col(AdlcRunTrigger.created_at), col(AdlcRunTrigger.id))
    if owner_id is not None:
        statement = statement.where(AdlcRunTrigger.owner_id == owner_id)
    return list((await session.exec(statement.limit(limit))).all())


async def delete_run_trigger(session: AsyncSession, *, trigger_id: UUID) -> bool:
    """Delete one durable trigger row and report whether it existed."""
    row = await get_run_trigger(session, trigger_id=trigger_id)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from langflow.services.database.models.adlc_workflow_run.model import AdlcWorkflowRun

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

MAX_SNAPSHOT_ROWS = 200


async def save_workflow_run_snapshot(session: AsyncSession, *, row: AdlcWorkflowRun) -> AdlcWorkflowRun:
    """Insert or update one durable run snapshot keyed by its workflow-run id."""
    existing = (
        await session.exec(select(AdlcWorkflowRun).where(AdlcWorkflowRun.id == row.id))
    ).first()
    if existing is not None:
        existing.owner_id = row.owner_id
        existing.status = row.status
        existing.execution_mode = row.execution_mode
        existing.flow_id = row.flow_id
        existing.execution_plan_id = row.execution_plan_id
        existing.run_number = row.run_number
        existing.run_payload = row.run_payload
        existing.definitions_payload = row.definitions_payload
        existing.created_at = row.created_at
        session.add(existing)
        await session.flush()
        return existing
    session.add(row)
    await session.flush()
    return row


async def get_workflow_run_snapshot(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> AdlcWorkflowRun | None:
    statement = select(AdlcWorkflowRun).where(AdlcWorkflowRun.id == run_id)
    return (await session.exec(statement)).first()


async def list_workflow_run_snapshots(
    session: AsyncSession,
    *,
    owner_id: str | None = None,
    limit: int = MAX_SNAPSHOT_ROWS,
) -> list[AdlcWorkflowRun]:
    """Return durable run snapshots oldest first, optionally scoped to one owner."""
    statement = select(AdlcWorkflowRun).order_by(col(AdlcWorkflowRun.created_at), col(AdlcWorkflowRun.id))
    if owner_id is not None:
        statement = statement.where(AdlcWorkflowRun.owner_id == owner_id)
    return list((await session.exec(statement.limit(limit))).all())


async def delete_workflow_run_snapshots(session: AsyncSession) -> int:
    """Delete every durable run snapshot row and return how many went away."""
    rows = list((await session.exec(select(AdlcWorkflowRun))).all())
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)

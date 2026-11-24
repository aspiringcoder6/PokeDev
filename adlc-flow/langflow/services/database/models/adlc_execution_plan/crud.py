from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from langflow.services.database.models.adlc_execution_plan.model import AdlcExecutionPlan

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession


async def save_execution_plan(
    session: AsyncSession,
    *,
    owner_id: str,
    workflow_definition_id: UUID,
    workflow_definition_version: int,
    plan_version: int,
    status: str,
    validation_status: str,
    supersedes_plan_id: UUID | None,
    approval_required: bool,
    generated_at: datetime,
    plan_payload: dict,
    workflow_payload: dict,
    execution_plan_id: UUID,
) -> AdlcExecutionPlan:
    """Insert or update one archived plan snapshot (idempotent by plan identity)."""
    existing = (
        await session.exec(
            select(AdlcExecutionPlan).where(
                AdlcExecutionPlan.id == execution_plan_id,
                AdlcExecutionPlan.owner_id == owner_id,
            )
        )
    ).first()
    if existing is not None:
        existing.status = status
        existing.validation_status = validation_status
        existing.approval_required = approval_required
        existing.plan_payload = plan_payload
        existing.workflow_payload = workflow_payload
        session.add(existing)
        await session.flush()
        return existing
    row = AdlcExecutionPlan(
        id=execution_plan_id,
        owner_id=owner_id,
        workflow_definition_id=workflow_definition_id,
        workflow_definition_version=workflow_definition_version,
        plan_version=plan_version,
        status=status,
        validation_status=validation_status,
        supersedes_plan_id=supersedes_plan_id,
        approval_required=approval_required,
        generated_at=generated_at,
        plan_payload=plan_payload,
        workflow_payload=workflow_payload,
    )
    session.add(row)
    await session.flush()
    return row


async def get_execution_plan_archive(
    session: AsyncSession,
    *,
    plan_id: UUID,
    owner_id: str,
) -> AdlcExecutionPlan | None:
    statement = select(AdlcExecutionPlan).where(
        AdlcExecutionPlan.id == plan_id,
        AdlcExecutionPlan.owner_id == owner_id,
    )
    return (await session.exec(statement)).first()


async def list_execution_plan_archives(
    session: AsyncSession,
    *,
    owner_id: str,
    workflow_definition_id: UUID,
    limit: int = 100,
) -> list[AdlcExecutionPlan]:
    statement = (
        select(AdlcExecutionPlan)
        .where(
            AdlcExecutionPlan.owner_id == owner_id,
            AdlcExecutionPlan.workflow_definition_id == workflow_definition_id,
        )
        .order_by(col(AdlcExecutionPlan.plan_version).desc())
        .limit(limit)
    )
    return list((await session.exec(statement)).all())

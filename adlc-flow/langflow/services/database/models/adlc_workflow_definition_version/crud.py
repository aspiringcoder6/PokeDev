from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from langflow.services.database.models.adlc_workflow_definition_version.model import (
    AdlcWorkflowDefinitionVersion,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel.ext.asyncio.session import AsyncSession

_MAX_VERSION_RETRIES = 3


async def get_next_definition_version_number(session: AsyncSession, flow_id: UUID) -> int:
    result = await session.exec(
        select(func.max(AdlcWorkflowDefinitionVersion.version_number)).where(
            AdlcWorkflowDefinitionVersion.flow_id == flow_id
        )
    )
    return (result.one() or 0) + 1


async def get_definition_version_rows(
    session: AsyncSession,
    *,
    flow_id: UUID,
    created_by: str,
) -> list[AdlcWorkflowDefinitionVersion]:
    statement = (
        select(AdlcWorkflowDefinitionVersion)
        .where(
            AdlcWorkflowDefinitionVersion.flow_id == flow_id,
            AdlcWorkflowDefinitionVersion.created_by == created_by,
        )
        .order_by(col(AdlcWorkflowDefinitionVersion.version_number).desc())
    )
    return list((await session.exec(statement)).all())


async def get_definition_version_row(
    session: AsyncSession,
    *,
    flow_id: UUID,
    version_number: int,
    created_by: str,
) -> AdlcWorkflowDefinitionVersion | None:
    statement = select(AdlcWorkflowDefinitionVersion).where(
        AdlcWorkflowDefinitionVersion.flow_id == flow_id,
        AdlcWorkflowDefinitionVersion.version_number == version_number,
        AdlcWorkflowDefinitionVersion.created_by == created_by,
    )
    return (await session.exec(statement)).first()


async def publish_definition_version(
    session: AsyncSession,
    *,
    flow_id: UUID,
    version_number: int,
    created_by: str,
    data: dict | None,
    description: str | None = None,
) -> AdlcWorkflowDefinitionVersion:
    """Insert one definition snapshot, superseding any previous latest row.

    A version-number collision rolls the transaction back and retries with
    the next available number so concurrent publishes converge safely.
    """
    for _attempt in range(_MAX_VERSION_RETRIES):
        rows = await get_definition_version_rows(session, flow_id=flow_id, created_by=created_by)
        for row in rows:
            if row.status != "SUPERSEDED":
                row.status = "SUPERSEDED"
                session.add(row)
        row = AdlcWorkflowDefinitionVersion(
            flow_id=flow_id,
            version_number=version_number,
            status="PUBLISHED",
            description=description,
            created_by=created_by,
            data=data,
        )
        session.add(row)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError:
            await session.rollback()
            if _attempt == _MAX_VERSION_RETRIES - 1:
                raise
            version_number = await get_next_definition_version_number(session, flow_id)
        else:
            return row
    msg = f"Failed to publish definition version for flow {flow_id}"
    raise RuntimeError(msg)

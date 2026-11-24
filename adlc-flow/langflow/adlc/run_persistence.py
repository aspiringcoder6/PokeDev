"""SQL-backed durable snapshots for the in-memory ADLC run coordinator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from langflow.adlc.models import AdlcTaskDefinition, WorkflowRun
from langflow.adlc.run_service import AdlcRunPersistence
from langflow.services.database.models.adlc_workflow_run import (
    AdlcWorkflowRun,
    delete_workflow_run_snapshots,
    list_workflow_run_snapshots,
    save_workflow_run_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession


def database_session_factory() -> Callable[[], AsyncSession]:
    """Bind run snapshots to the process-wide Langflow database service."""

    def factory() -> AsyncSession:
        from langflow.services.deps import get_db_service

        return get_db_service().async_session_maker()

    return factory


class SqlAdlcRunPersistence(AdlcRunPersistence):
    """Persist one JSON snapshot row per run, reusing the Langflow session factory."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, *, owner_id: str, run: WorkflowRun, definitions: dict[str, AdlcTaskDefinition]) -> None:
        row = AdlcWorkflowRun(
            id=run.id,
            owner_id=owner_id,
            status=run.status.value,
            execution_mode=run.execution_mode.value,
            flow_id=run.flow_id,
            execution_plan_id=run.execution_plan_id,
            run_number=run.run_number,
            run_payload=run.model_dump(mode="json"),
            definitions_payload=[definition.model_dump(mode="json") for definition in definitions.values()],
            created_at=run.created_at,
        )
        async with self._session_factory() as session:
            await save_workflow_run_snapshot(session, row=row)
            await session.commit()

    async def load(
        self, *, owner_id: str | None = None
    ) -> list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]]:
        async with self._session_factory() as session:
            rows = await list_workflow_run_snapshots(session, owner_id=owner_id)
        snapshots: list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]] = []
        for row in rows:
            try:
                run = WorkflowRun.model_validate(row.run_payload)
                definitions = [
                    AdlcTaskDefinition.model_validate(definition) for definition in row.definitions_payload
                ]
            except ValidationError:
                continue
            snapshots.append((row.owner_id, run, definitions))
        return snapshots

    async def clear(self) -> None:
        async with self._session_factory() as session:
            await delete_workflow_run_snapshots(session)
            await session.commit()

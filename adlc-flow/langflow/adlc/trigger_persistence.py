"""SQL-backed durable storage for ADLC run triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from langflow.adlc.models import AdlcTaskDefinition, WorkflowExecutionMode
from langflow.adlc.triggers import (
    AdlcRunTrigger,
    AdlcTriggerPersistence,
    TriggerFireStatus,
    TriggerMissedPolicy,
    TriggerOverlapPolicy,
    TriggerSchedule,
)
from langflow.services.database.models.adlc_run_trigger import (
    AdlcRunTrigger as AdlcRunTriggerRow,
)
from langflow.services.database.models.adlc_run_trigger import (
    delete_run_trigger,
    list_run_triggers,
    save_run_trigger,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAdlcTriggerPersistence(AdlcTriggerPersistence):
    """Persist one JSON snapshot row per run trigger."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, *, trigger: AdlcRunTrigger) -> None:
        row = AdlcRunTriggerRow(
            id=trigger.trigger_id,
            owner_id=trigger.owner_id,
            name=trigger.name,
            enabled=trigger.enabled,
            flow_id=trigger.flow_id,
            flow_name=trigger.flow_name,
            execution_mode=trigger.execution_mode.value,
            overlap_policy=trigger.overlap_policy.value,
            missed_policy=trigger.missed_policy.value,
            webhook_enabled=trigger.webhook_enabled,
            webhook_token=trigger.webhook_token,
            schedule_payload=trigger.schedule.model_dump(mode="json"),
            definitions_payload=[definition.model_dump(mode="json") for definition in trigger.definitions],
            next_due_at=trigger.next_due_at,
            last_fired_at=trigger.last_fired_at,
            last_fire_status=trigger.last_fire_status.value if trigger.last_fire_status else None,
            last_run_id=trigger.last_run_id,
            active_run_ids=list(trigger.active_run_ids),
            created_at=trigger.created_at,
        )
        async with self._session_factory() as session:
            await save_run_trigger(session, row=row)
            await session.commit()

    async def load(self) -> list[AdlcRunTrigger]:
        async with self._session_factory() as session:
            rows = await list_run_triggers(session)
        triggers: list[AdlcRunTrigger] = []
        for row in rows:
            try:
                triggers.append(_trigger_from_row(row))
            except ValidationError:
                continue
        return triggers

    async def delete(self, *, trigger_id: UUID) -> bool:
        async with self._session_factory() as session:
            deleted = await delete_run_trigger(session, trigger_id=trigger_id)
            await session.commit()
        return deleted


def _trigger_from_row(row: AdlcRunTriggerRow) -> AdlcRunTrigger:
    return AdlcRunTrigger(
        trigger_id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        enabled=row.enabled,
        flow_id=row.flow_id,
        flow_name=row.flow_name,
        execution_mode=WorkflowExecutionMode(row.execution_mode),
        schedule=TriggerSchedule.model_validate(row.schedule_payload),
        overlap_policy=TriggerOverlapPolicy(row.overlap_policy),
        missed_policy=TriggerMissedPolicy(row.missed_policy),
        webhook_enabled=row.webhook_enabled,
        webhook_token=row.webhook_token,
        definitions=[AdlcTaskDefinition.model_validate(item) for item in row.definitions_payload],
        next_due_at=row.next_due_at,
        last_fired_at=row.last_fired_at,
        last_fire_status=TriggerFireStatus(row.last_fire_status) if row.last_fire_status else None,
        last_run_id=row.last_run_id,
        active_run_ids=list(row.active_run_ids),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

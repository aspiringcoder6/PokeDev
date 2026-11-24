"""Scheduled and webhook run triggers for the ADLC orchestrator (P2).

A trigger owns a frozen task-definition snapshot taken from a saved flow at
creation time. When its schedule is due — or its webhook is called — the
service starts one run through the existing :class:`AdlcRunService`, honoring
an anti-overlap policy, a missed-schedule policy, and owner scoping.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from langflow.adlc.cron import CronParseError, parse_cron
from langflow.adlc.models import (
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)
from lfx.log.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langflow.adlc.run_service import AdlcRunService

TRIGGER_CONTRACT_VERSION = "0.1"
WEBHOOK_TOKEN_BYTES = 24
MIN_INTERVAL_SECONDS = 30
MAX_INTERVAL_SECONDS = 30 * 24 * 3600

ACTIVE_RUN_STATUSES = frozenset(
    {
        WorkflowRunStatus.CREATED,
        WorkflowRunStatus.QUEUED,
        WorkflowRunStatus.RUNNING,
        WorkflowRunStatus.PAUSED,
        WorkflowRunStatus.WAITING_APPROVAL,
    }
)

_TRIGGER_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9 ._@-]{0,127}$"


class TriggerScheduleKind(str, Enum):
    INTERVAL = "INTERVAL"
    CRON = "CRON"


class TriggerOverlapPolicy(str, Enum):
    """What to do when the previous run started by this trigger is still active."""

    SKIP = "SKIP"
    ALLOW = "ALLOW"


class TriggerMissedPolicy(str, Enum):
    """What to do when the process was down across one or more due times."""

    SKIP = "SKIP"
    CATCH_UP = "CATCH_UP"


class TriggerFireStatus(str, Enum):
    FIRED = "FIRED"
    SKIPPED_OVERLAP = "SKIPPED_OVERLAP"
    FAILED = "FAILED"


class TriggerSchedule(BaseModel):
    """Exactly one of a fixed interval or a five-field cron expression."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    kind: TriggerScheduleKind
    interval_seconds: int | None = Field(
        default=None,
        ge=MIN_INTERVAL_SECONDS,
        le=MAX_INTERVAL_SECONDS,
        alias="intervalSeconds",
    )
    cron: str | None = Field(default=None, min_length=9, max_length=128)

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parse_cron(value)
        except CronParseError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> TriggerSchedule:
        if self.kind is TriggerScheduleKind.INTERVAL and self.interval_seconds is None:
            message = "INTERVAL schedules require interval_seconds"
            raise ValueError(message)
        if self.kind is TriggerScheduleKind.CRON:
            if self.cron is None:
                message = "CRON schedules require a cron expression"
                raise ValueError(message)
            if self.interval_seconds is not None:
                message = "CRON schedules must not set interval_seconds"
                raise ValueError(message)
        return self

    def next_due_after(self, value: datetime) -> datetime:
        """Return the next due time strictly after the aware datetime."""
        if self.kind is TriggerScheduleKind.INTERVAL:
            if self.interval_seconds is None:
                message = "INTERVAL schedules require interval_seconds"
                raise ValueError(message)
            return value + timedelta(seconds=self.interval_seconds)
        if self.cron is None:
            message = "CRON schedules require a cron expression"
            raise ValueError(message)
        return parse_cron(self.cron).next_after(value)


class CreateRunTriggerCommand(BaseModel):
    """Creation payload for one run trigger."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=128, pattern=_TRIGGER_NAME_PATTERN)
    flow_id: UUID = Field(alias="flowId")
    flow_name: str = Field(min_length=1, max_length=255, alias="flowName")
    execution_mode: WorkflowExecutionMode = Field(
        default=WorkflowExecutionMode.LEGACY_FLOW,
        alias="executionMode",
    )
    schedule: TriggerSchedule
    overlap_policy: TriggerOverlapPolicy = Field(default=TriggerOverlapPolicy.SKIP, alias="overlapPolicy")
    missed_policy: TriggerMissedPolicy = Field(default=TriggerMissedPolicy.SKIP, alias="missedPolicy")
    webhook_enabled: bool = Field(default=False, alias="webhookEnabled")


class UpdateRunTriggerCommand(BaseModel):
    """Partial update payload for one run trigger."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=128, pattern=_TRIGGER_NAME_PATTERN)
    enabled: bool | None = None
    schedule: TriggerSchedule | None = None
    overlap_policy: TriggerOverlapPolicy | None = Field(default=None, alias="overlapPolicy")
    missed_policy: TriggerMissedPolicy | None = Field(default=None, alias="missedPolicy")
    webhook_enabled: bool | None = Field(default=None, alias="webhookEnabled")


class AdlcRunTrigger(BaseModel):
    """One scheduled or webhook-started run source with its frozen workflow snapshot."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = TRIGGER_CONTRACT_VERSION
    trigger_id: UUID = Field(default_factory=uuid4)
    owner_id: str
    name: str
    enabled: bool = True
    flow_id: UUID
    flow_name: str
    execution_mode: WorkflowExecutionMode = WorkflowExecutionMode.LEGACY_FLOW
    schedule: TriggerSchedule
    overlap_policy: TriggerOverlapPolicy = TriggerOverlapPolicy.SKIP
    missed_policy: TriggerMissedPolicy = TriggerMissedPolicy.SKIP
    webhook_enabled: bool = False
    webhook_token: str | None = Field(default=None, min_length=16, max_length=255)
    definitions: list[AdlcTaskDefinition] = Field(default_factory=list)
    next_due_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_fire_status: TriggerFireStatus | None = None
    last_run_id: UUID | None = None
    active_run_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def public_view(self) -> AdlcRunTriggerView:
        """Return the owner-facing projection without the webhook secret."""
        return AdlcRunTriggerView(
            trigger_id=self.trigger_id,
            owner_id=self.owner_id,
            name=self.name,
            enabled=self.enabled,
            flow_id=self.flow_id,
            flow_name=self.flow_name,
            execution_mode=self.execution_mode,
            schedule=self.schedule,
            overlap_policy=self.overlap_policy,
            missed_policy=self.missed_policy,
            webhook_enabled=self.webhook_enabled,
            webhook_configured=self.webhook_token is not None,
            next_due_at=self.next_due_at,
            last_fired_at=self.last_fired_at,
            last_fire_status=self.last_fire_status,
            last_run_id=self.last_run_id,
            active_run_ids=list(self.active_run_ids),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class AdlcRunTriggerView(BaseModel):
    """Owner-facing trigger projection; never carries the webhook token."""

    model_config = ConfigDict(extra="forbid")

    trigger_id: UUID
    owner_id: str
    name: str
    enabled: bool
    flow_id: UUID
    flow_name: str
    execution_mode: WorkflowExecutionMode
    schedule: TriggerSchedule
    overlap_policy: TriggerOverlapPolicy
    missed_policy: TriggerMissedPolicy
    webhook_enabled: bool
    webhook_configured: bool = False
    next_due_at: datetime | None = None
    last_fired_at: datetime | None = None
    last_fire_status: TriggerFireStatus | None = None
    last_run_id: UUID | None = None
    active_run_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WebhookFireResponse(BaseModel):
    """Result of one webhook invocation."""

    model_config = ConfigDict(extra="forbid")

    trigger_id: UUID
    status: TriggerFireStatus
    workflow_run_id: UUID | None = None
    message: str | None = None


class WebhookTokenView(BaseModel):
    """One-time reveal of a rotated webhook secret."""

    model_config = ConfigDict(extra="forbid")

    webhook_token: str


class NextTriggerRunsView(BaseModel):
    """Preview of upcoming fire times for one trigger schedule."""

    model_config = ConfigDict(extra="forbid")

    trigger_id: UUID
    next_run_times: list[datetime]


class AdlcTriggerPersistence(Protocol):
    """Replaceable storage port for run triggers."""

    async def save(self, *, trigger: AdlcRunTrigger) -> None: ...

    async def load(self) -> list[AdlcRunTrigger]: ...

    async def delete(self, *, trigger_id: UUID) -> bool: ...


class InMemoryAdlcTriggerPersistence:
    """Thread-free recorder used by unit tests and isolated compositions."""

    def __init__(self) -> None:
        self.triggers: dict[UUID, AdlcRunTrigger] = {}

    async def save(self, *, trigger: AdlcRunTrigger) -> None:
        self.triggers[trigger.trigger_id] = trigger.model_copy(deep=True)

    async def load(self) -> list[AdlcRunTrigger]:
        return [trigger.model_copy(deep=True) for trigger in self.triggers.values()]

    async def delete(self, *, trigger_id: UUID) -> bool:
        return self.triggers.pop(trigger_id, None) is not None


class TriggerTickOutcome(BaseModel):
    """One trigger's outcome during a scheduler tick."""

    model_config = ConfigDict(extra="forbid")

    trigger_id: UUID
    status: TriggerFireStatus
    workflow_run_id: UUID | None = None
    detail: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_webhook_token() -> str:
    """Generate one opaque webhook bearer token."""
    return secrets.token_urlsafe(WEBHOOK_TOKEN_BYTES)


class AdlcTriggerService:
    """Evaluate due triggers and start runs through the run service."""

    def __init__(
        self,
        run_service: AdlcRunService,
        *,
        persistence: AdlcTriggerPersistence | None = None,
        clock: Callable[[], datetime] | None = None,
        tick_interval_seconds: float = 30.0,
    ) -> None:
        self._run_service = run_service
        self._persistence = persistence if persistence is not None else InMemoryAdlcTriggerPersistence()
        self._clock = clock or _utc_now
        self._tick_interval = tick_interval_seconds
        self._triggers: dict[UUID, AdlcRunTrigger] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._loop_lock = asyncio.Lock()
        self._loaded = False

    async def create_trigger(
        self,
        *,
        owner_id: str,
        command: CreateRunTriggerCommand,
        definitions: Sequence[AdlcTaskDefinition],
    ) -> AdlcRunTrigger:
        """Persist one trigger with a definition snapshot and webhook secret."""
        if command.execution_mode is not WorkflowExecutionMode.LEGACY_FLOW:
            message = "Run triggers currently support only LEGACY_FLOW execution mode"
            raise ValueError(message)
        if not definitions:
            message = "Run triggers require at least one task definition"
            raise ValueError(message)
        now = self._clock()
        token = new_webhook_token() if command.webhook_enabled else None
        trigger = AdlcRunTrigger(
            owner_id=owner_id,
            name=command.name,
            flow_id=command.flow_id,
            flow_name=command.flow_name,
            execution_mode=command.execution_mode,
            schedule=command.schedule,
            overlap_policy=command.overlap_policy,
            missed_policy=command.missed_policy,
            webhook_enabled=command.webhook_enabled,
            webhook_token=token,
            definitions=[definition.model_copy(deep=True) for definition in definitions],
            next_due_at=command.schedule.next_due_after(now),
            created_at=now,
            updated_at=now,
        )
        async with self._loop_lock:
            self._triggers[trigger.trigger_id] = trigger
        await self._persistence.save(trigger=trigger)
        return trigger

    async def list_triggers(self, *, owner_id: str) -> list[AdlcRunTriggerView]:
        await self._ensure_loaded()
        triggers = [
            trigger.public_view
            for trigger in self._triggers.values()
            if trigger.owner_id == owner_id
        ]
        triggers.sort(key=lambda view: (view.created_at, view.trigger_id))
        return triggers

    async def get_trigger(self, trigger_id: UUID, *, owner_id: str) -> AdlcRunTriggerView:
        trigger = await self._owned_trigger(trigger_id, owner_id)
        return trigger.public_view

    async def update_trigger(
        self,
        trigger_id: UUID,
        *,
        owner_id: str,
        command: UpdateRunTriggerCommand,
    ) -> AdlcRunTriggerView:
        """Apply a partial update and recompute the next due time when needed."""
        trigger = await self._owned_trigger(trigger_id, owner_id)
        now = self._clock()
        updated = trigger.model_copy(deep=True)
        if command.name is not None:
            updated.name = command.name
        if command.enabled is not None:
            updated.enabled = command.enabled
        if command.overlap_policy is not None:
            updated.overlap_policy = command.overlap_policy
        if command.missed_policy is not None:
            updated.missed_policy = command.missed_policy
        if command.webhook_enabled is not None:
            updated.webhook_enabled = command.webhook_enabled
            if command.webhook_enabled and updated.webhook_token is None:
                updated.webhook_token = new_webhook_token()
        schedule_changed = command.schedule is not None and command.schedule != trigger.schedule
        if command.schedule is not None:
            updated.schedule = command.schedule
        if schedule_changed or updated.next_due_at is None:
            updated.next_due_at = updated.schedule.next_due_after(now)
        updated.updated_at = now
        async with self._loop_lock:
            self._triggers[trigger_id] = updated
        await self._persistence.save(trigger=updated)
        return updated.public_view

    async def delete_trigger(self, trigger_id: UUID, *, owner_id: str) -> bool:
        await self._ensure_loaded()
        trigger = self._triggers.get(trigger_id)
        if trigger is None or trigger.owner_id != owner_id:
            return False
        async with self._loop_lock:
            self._triggers.pop(trigger_id, None)
        return await self._persistence.delete(trigger_id=trigger_id)

    async def rotate_webhook_token(self, trigger_id: UUID, *, owner_id: str) -> str:
        """Replace the webhook secret and return the new token once."""
        trigger = await self._owned_trigger(trigger_id, owner_id)
        token = new_webhook_token()
        updated = trigger.model_copy(
            deep=True,
            update={"webhook_token": token, "updated_at": self._clock()},
        )
        async with self._loop_lock:
            self._triggers[trigger_id] = updated
        await self._persistence.save(trigger=updated)
        return token

    async def fire_webhook(self, *, token: str) -> WebhookFireResponse:
        """Start one run for the trigger that owns the webhook token."""
        await self._ensure_loaded()
        trigger = next(
            (
                candidate
                for candidate in self._triggers.values()
                if candidate.webhook_enabled and candidate.webhook_token == token
            ),
            None,
        )
        if trigger is None:
            message = "No enabled trigger matches this webhook token"
            raise LookupError(message)
        outcome = await self._fire(trigger, reason="webhook")
        return WebhookFireResponse(
            trigger_id=trigger.trigger_id,
            status=outcome.status,
            workflow_run_id=outcome.workflow_run_id,
            message=outcome.detail,
        )

    async def tick(self, *, now: datetime | None = None) -> list[TriggerTickOutcome]:
        """Evaluate every enabled trigger once and persist each state change."""
        await self._ensure_loaded()
        current = now or self._clock()
        outcomes: list[TriggerTickOutcome] = []
        for stored in list(self._triggers.values()):
            if not stored.enabled:
                continue
            candidate = stored
            if candidate.next_due_at is None:
                candidate = candidate.model_copy(update={"next_due_at": candidate.schedule.next_due_after(current)})
                await self._store(candidate)
            due_at = candidate.next_due_at
            if due_at is None or due_at > current:
                continue
            outcomes.append(await self._fire(candidate, reason="schedule", due_at=due_at))
        return outcomes

    def start(self) -> None:
        """Start the background tick loop (idempotent)."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run_loop(), name="adlc-trigger-loop")

    async def stop(self) -> None:
        """Cancel the background tick loop and wait for it to finish."""
        task = self._loop_task
        self._loop_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive trigger failures
                await self._log_warning("adlc.trigger.tick_failed")

    async def _fire(
        self,
        trigger: AdlcRunTrigger,
        *,
        reason: str,
        due_at: datetime | None = None,
    ) -> TriggerTickOutcome:
        """Start one run unless the overlap policy says otherwise."""
        current = self._clock()
        fire_at = due_at or current
        active_ids = await self._active_run_ids(trigger)
        if trigger.overlap_policy is TriggerOverlapPolicy.SKIP and active_ids:
            updated = trigger.model_copy(
                deep=True,
                update={
                    "next_due_at": self._advance(trigger, fire_at),
                    "last_fired_at": current,
                    "last_fire_status": TriggerFireStatus.SKIPPED_OVERLAP,
                    "active_run_ids": sorted(active_ids),
                    "updated_at": current,
                },
            )
            await self._store(updated)
            return TriggerTickOutcome(
                trigger_id=trigger.trigger_id,
                status=TriggerFireStatus.SKIPPED_OVERLAP,
                detail=f"previous run {next(iter(active_ids))} is still active",
            )
        request = CreateWorkflowRunRequest(
            flow_id=trigger.flow_id,
            execution_mode=trigger.execution_mode,
        )
        try:
            run = await self._run_service.start_run(
                flow_id=trigger.flow_id,
                flow_name=trigger.flow_name,
                definitions=[definition.model_copy(deep=True) for definition in trigger.definitions],
                request=request,
                owner_id=trigger.owner_id,
            )
        except Exception as exc:  # noqa: BLE001 - record and keep the loop alive
            updated = trigger.model_copy(
                deep=True,
                update={
                    "next_due_at": self._advance(trigger, fire_at),
                    "last_fired_at": current,
                    "last_fire_status": TriggerFireStatus.FAILED,
                    "active_run_ids": sorted(active_ids),
                    "updated_at": current,
                },
            )
            await self._store(updated)
            await self._log_warning("adlc.trigger.fire_failed", code=getattr(exc, "code", None))
            return TriggerTickOutcome(
                trigger_id=trigger.trigger_id,
                status=TriggerFireStatus.FAILED,
                detail=f"{reason} fire failed",
            )
        active = sorted({*active_ids, run.id})
        updated = trigger.model_copy(
            deep=True,
            update={
                "next_due_at": self._advance(trigger, fire_at),
                "last_fired_at": current,
                "last_fire_status": TriggerFireStatus.FIRED,
                "last_run_id": run.id,
                "active_run_ids": active,
                "updated_at": current,
            },
        )
        await self._store(updated)
        return TriggerTickOutcome(
            trigger_id=trigger.trigger_id,
            status=TriggerFireStatus.FIRED,
            workflow_run_id=run.id,
        )

    def _advance(self, trigger: AdlcRunTrigger, fired_from: datetime) -> datetime:
        """Compute the next due time, honoring fixed-rate intervals without drift."""
        return trigger.schedule.next_due_after(fired_from)

    async def _active_run_ids(self, trigger: AdlcRunTrigger) -> set[UUID]:
        """Re-derive still-active runs owned by this trigger."""
        active: set[UUID] = set()
        for run_id in trigger.active_run_ids:
            try:
                run = await self._run_service.get_run(run_id, owner_id=trigger.owner_id)
            except Exception:  # noqa: BLE001, S112 - unknown or cleared runs are simply not active
                continue
            if run.status in ACTIVE_RUN_STATUSES:
                active.add(run_id)
        return active

    async def _owned_trigger(self, trigger_id: UUID, owner_id: str) -> AdlcRunTrigger:
        await self._ensure_loaded()
        trigger = self._triggers.get(trigger_id)
        if trigger is None or trigger.owner_id != owner_id:
            message = f"Run trigger {trigger_id} was not found"
            raise LookupError(message)
        return trigger

    async def _store(self, trigger: AdlcRunTrigger) -> None:
        async with self._loop_lock:
            self._triggers[trigger.trigger_id] = trigger
        await self._persistence.save(trigger=trigger)

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        restored_ids: set[UUID] = set()
        async with self._loop_lock:
            if self._loaded:
                return
            for trigger in await self._persistence.load():
                if trigger.trigger_id not in self._triggers:
                    self._triggers[trigger.trigger_id] = trigger
                    restored_ids.add(trigger.trigger_id)
            self._loaded = True
        if restored_ids:
            await self._apply_missed_policies(restored_ids)

    async def _apply_missed_policies(self, restored_ids: set[UUID]) -> None:
        """Resolve overdue due-times after process downtime per trigger policy."""
        current = self._clock()
        for stored_id in sorted(restored_ids):
            trigger = self._triggers.get(stored_id)
            if trigger is None:
                continue
            due_at = trigger.next_due_at
            if not trigger.enabled or due_at is None or due_at > current:
                continue
            if trigger.missed_policy is TriggerMissedPolicy.CATCH_UP:
                updated = trigger.model_copy(update={"next_due_at": current})
            else:
                updated = trigger.model_copy(update={"next_due_at": self._advance(trigger, current)})
            async with self._loop_lock:
                self._triggers[stored_id] = updated
            await self._persistence.save(trigger=updated)

    async def _log_warning(self, event: str, **fields: object) -> None:
        payload = {key: value for key, value in fields.items() if value is not None}
        with contextlib.suppress(Exception):  # logging must never break triggers
            logger.warning(event, **payload)

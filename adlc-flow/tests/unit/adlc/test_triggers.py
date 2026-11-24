# ruff: noqa: INP001, PLR2004, S101, S106, SLF001

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from langflow.adlc.models import (
    AdlcTaskDefinition,
    MockArtifactSpec,
    WorkflowExecutionMode,
    WorkflowRunStatus,
)
from langflow.adlc.run_service import AdlcRunNotFoundError
from langflow.adlc.triggers import (
    AdlcTriggerService,
    CreateRunTriggerCommand,
    InMemoryAdlcTriggerPersistence,
    TriggerFireStatus,
    TriggerMissedPolicy,
    TriggerOverlapPolicy,
    TriggerSchedule,
    TriggerScheduleKind,
    UpdateRunTriggerCommand,
)


def _definition(key: str = "alpha", *, dependencies: list[str] | None = None) -> AdlcTaskDefinition:
    return AdlcTaskDefinition(
        id=uuid4(),
        key=key,
        name=key.title(),
        task_type="mock",
        dependencies=dependencies or [],
        predetermined_output={"summary": f"{key} done"},
        artifact=MockArtifactSpec(
            kind="MOCK_SUMMARY",
            name=f"{key}-artifact",
            media_type="text/plain",
            content=f"{key} output",
        ),
    )


def _schedule_interval(seconds: int = 3600) -> TriggerSchedule:
    return TriggerSchedule(kind=TriggerScheduleKind.INTERVAL, interval_seconds=max(30, seconds))


def _schedule_cron(expression: str = "0 9 * * *") -> TriggerSchedule:
    return TriggerSchedule(kind=TriggerScheduleKind.CRON, cron=expression)


def _command(**overrides: object) -> CreateRunTriggerCommand:
    payload: dict[str, object] = {
        "name": "nightly-rebuild",
        "flow_id": uuid4(),
        "flow_name": "Nightly rebuild",
        "schedule": _schedule_interval(),
        "webhook_enabled": True,
    }
    payload.update(overrides)
    return CreateRunTriggerCommand(**payload)  # type: ignore[arg-type]


@dataclass
class _FakeRun:
    id: UUID
    status: WorkflowRunStatus = WorkflowRunStatus.RUNNING


@dataclass
class _FakeRunService:
    """Duck-typed stand-in exposing start_run/get_run for trigger tests."""

    runs: dict[UUID, _FakeRun] = field(default_factory=dict)
    start_count: int = 0
    fail_next_start: bool = False

    async def start_run(self, **kwargs: object) -> _FakeRun:  # noqa: ARG002 - duck-typed service port
        self.start_count += 1
        if self.fail_next_start:
            self.fail_next_start = False
            raise RuntimeError("synthetic start failure")  # noqa: EM101, TRY003 - test fake
        run = _FakeRun(id=uuid4())
        self.runs[run.id] = run
        return run

    async def get_run(self, run_id: UUID, *, owner_id: str) -> _FakeRun:  # noqa: ARG002 - owner scoping only
        run = self.runs.get(run_id)
        if run is None:
            raise AdlcRunNotFoundError(f"run {run_id} not found")  # noqa: EM102, TRY003 - test fake
        return run


class _MutableClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _service(
    run_service: _FakeRunService | None = None,
    persistence: InMemoryAdlcTriggerPersistence | None = None,
    clock: _MutableClock | None = None,
) -> tuple[AdlcTriggerService, _FakeRunService, InMemoryAdlcTriggerPersistence, _MutableClock]:
    run_service = run_service or _FakeRunService()
    persistence = persistence or InMemoryAdlcTriggerPersistence()
    clock = clock or _MutableClock(datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc))
    service = AdlcTriggerService(run_service, persistence=persistence, clock=clock)
    return service, run_service, persistence, clock


async def test_create_trigger_snapshots_definitions_and_computes_due() -> None:
    service, _, _, clock = _service()
    definitions = [_definition(), _definition("beta", dependencies=["alpha"])]
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=definitions)

    assert trigger.owner_id == "owner-1"
    assert trigger.enabled is True
    assert trigger.next_due_at == clock() + timedelta(seconds=3600)
    assert len(trigger.definitions) == 2
    assert trigger.definitions[0].id == definitions[0].id
    assert trigger.webhook_token is not None
    assert len(trigger.webhook_token) >= 16
    assert trigger.public_view.webhook_configured is True
    assert trigger.public_view.model_dump(mode="json").get("webhook_token") is None


async def test_create_trigger_rejects_non_legacy_and_empty_definitions() -> None:
    service, _, _, _ = _service()
    with pytest.raises(ValueError, match="LEGACY_FLOW"):
        await service.create_trigger(
            owner_id="owner-1",
            command=_command(execution_mode=WorkflowExecutionMode.MOCK_WORKFLOW),
            definitions=[_definition()],
        )
    with pytest.raises(ValueError, match="at least one"):
        await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[])


async def test_tick_fires_due_interval_trigger_and_advances_due() -> None:
    service, run_service, _, clock = _service()
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])

    clock.advance(3600)
    outcomes = await service.tick()

    assert [outcome.status for outcome in outcomes] == [TriggerFireStatus.FIRED]
    assert outcomes[0].workflow_run_id is not None
    assert run_service.start_count == 1
    stored = (await service.get_trigger(trigger.trigger_id, owner_id="owner-1")).next_due_at
    assert stored == clock() + timedelta(seconds=3600)


async def test_tick_ignores_future_and_disabled_triggers() -> None:
    service, run_service, _, _clock = _service()
    await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    disabled = await service.create_trigger(
        owner_id="owner-1",
        command=_command(name="off"),
        definitions=[_definition()],
    )
    await service.update_trigger(
        disabled.trigger_id,
        owner_id="owner-1",
        command=UpdateRunTriggerCommand(enabled=False),
    )

    _clock.advance(7200)
    await service.tick()

    assert run_service.start_count == 1


async def test_overlap_skip_defers_until_previous_run_finishes() -> None:
    service, run_service, _, clock = _service()
    trigger = await service.create_trigger(
        owner_id="owner-1",
        command=_command(overlap_policy=TriggerOverlapPolicy.SKIP),
        definitions=[_definition()],
    )

    clock.advance(3600)
    first = await service.tick()
    assert first[0].status is TriggerFireStatus.FIRED
    first_run_id = first[0].workflow_run_id

    clock.advance(3600)
    skipped = await service.tick()
    assert skipped[0].status is TriggerFireStatus.SKIPPED_OVERLAP
    assert run_service.start_count == 1

    assert first_run_id is not None
    run_service.runs[first_run_id].status = WorkflowRunStatus.SUCCEEDED
    clock.advance(3600)
    resumed = await service.tick()
    assert resumed[0].status is TriggerFireStatus.FIRED
    assert run_service.start_count == 2
    view = await service.get_trigger(trigger.trigger_id, owner_id="owner-1")
    assert view.last_fire_status is TriggerFireStatus.FIRED


async def test_overlap_allow_starts_concurrent_runs() -> None:
    service, run_service, _, clock = _service()
    await service.create_trigger(
        owner_id="owner-1",
        command=_command(overlap_policy=TriggerOverlapPolicy.ALLOW),
        definitions=[_definition()],
    )

    clock.advance(3600)
    await service.tick()
    clock.advance(3600)
    await service.tick()

    assert run_service.start_count == 2


async def test_missed_policy_on_restart_skip_vs_catch_up() -> None:
    run_service = _FakeRunService()
    persistence = InMemoryAdlcTriggerPersistence()
    clock = _MutableClock(datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc))
    first, _, _, _ = _service(run_service, persistence, clock)
    skip_trigger = await first.create_trigger(
        owner_id="owner-1",
        command=_command(name="skip-me"),
        definitions=[_definition()],
    )
    catch_trigger = await first.create_trigger(
        owner_id="owner-1",
        command=_command(name="catch-me", missed_policy=TriggerMissedPolicy.CATCH_UP),
        definitions=[_definition()],
    )

    clock.advance(3 * 3600)
    restarted, run_service2, _, _ = _service(run_service, persistence, clock)
    await restarted._ensure_loaded()

    skip_view = await restarted.get_trigger(skip_trigger.trigger_id, owner_id="owner-1")
    assert skip_view.next_due_at is not None
    assert skip_view.next_due_at > clock()
    catch_view = await restarted.get_trigger(catch_trigger.trigger_id, owner_id="owner-1")
    assert catch_view.next_due_at == clock()

    outcomes = await restarted.tick()
    assert [outcome.status for outcome in outcomes] == [TriggerFireStatus.FIRED]
    assert run_service2.start_count == 1


async def test_webhook_fires_by_token_and_rotates() -> None:
    service, run_service, _, _ = _service()
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    token = trigger.webhook_token
    assert token is not None

    response = await service.fire_webhook(token=token)
    assert response.status is TriggerFireStatus.FIRED
    assert response.workflow_run_id is not None
    assert run_service.start_count == 1

    rotated = await service.rotate_webhook_token(trigger.trigger_id, owner_id="owner-1")
    assert rotated != token
    with pytest.raises(LookupError):
        await service.fire_webhook(token=token)
    again = await service.fire_webhook(token=rotated)
    assert again.status is TriggerFireStatus.SKIPPED_OVERLAP
    assert again.trigger_id == trigger.trigger_id
    assert run_service.start_count == 1


async def test_webhook_unknown_token_and_owner_scoping() -> None:
    service, _, _, _ = _service()
    await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    with pytest.raises(LookupError):
        await service.fire_webhook(token="no-such-token")

    other, _, _, _ = _service()
    with pytest.raises(LookupError):
        await other.fire_webhook(token="anything")


async def test_update_trigger_recomputes_next_due_on_schedule_change() -> None:
    service, _, _, _clock = _service()
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    original_due = trigger.next_due_at

    updated = await service.update_trigger(
        trigger.trigger_id,
        owner_id="owner-1",
        command=UpdateRunTriggerCommand(schedule=_schedule_cron("30 5 * * *")),
    )
    assert updated.schedule.cron == "30 5 * * *"
    assert updated.next_due_at != original_due
    assert updated.next_due_at == datetime(2026, 10, 9, 5, 30, tzinfo=timezone.utc)


async def test_delete_and_owner_isolation() -> None:
    service, _, persistence, _ = _service()
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])

    with pytest.raises(LookupError):
        await service.get_trigger(trigger.trigger_id, owner_id="owner-2")
    assert await service.delete_trigger(trigger.trigger_id, owner_id="owner-2") is False
    assert await service.delete_trigger(trigger.trigger_id, owner_id="owner-1") is True
    assert persistence.triggers == {}


async def test_failed_start_is_recorded_and_loop_survives() -> None:
    service, run_service, _, clock = _service()
    trigger = await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    run_service.fail_next_start = True

    clock.advance(3600)
    outcomes = await service.tick()

    assert outcomes[0].status is TriggerFireStatus.FAILED
    view = await service.get_trigger(trigger.trigger_id, owner_id="owner-1")
    assert view.last_fire_status is TriggerFireStatus.FAILED
    assert view.next_due_at is not None

    clock.advance(3600)
    retried = await service.tick()
    assert retried[0].status is TriggerFireStatus.FIRED


async def test_background_loop_starts_and_stops() -> None:
    service, run_service, _, clock = _service()
    service._tick_interval = 0.01
    await service.create_trigger(owner_id="owner-1", command=_command(), definitions=[_definition()])
    clock.advance(3600)

    service.start()
    for _ in range(200):
        if run_service.start_count > 0:
            break
        await _sleep(0.01)
    assert run_service.start_count >= 1
    await service.stop()
    await service.stop()


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)

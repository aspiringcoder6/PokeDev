# ruff: noqa: PLR2004, S101, S105, S106

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.trigger_persistence import SqlAdlcTriggerPersistence
from langflow.adlc.triggers import (
    AdlcRunTrigger,
    AdlcTriggerService,
    CreateRunTriggerCommand,
    InMemoryAdlcTriggerPersistence,
    TriggerSchedule,
    TriggerScheduleKind,
)
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user
from lfx.services.deps import injectable_session_scope

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from sqlalchemy.ext.asyncio import AsyncEngine


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "plan", "type": "genericNode", "data": {"type": "Plan"}},
            {"id": "verify", "type": "genericNode", "data": {"type": "Verify"}},
        ],
        "edges": [{"source": "plan", "target": "verify"}],
    }


def _command() -> CreateRunTriggerCommand:
    return CreateRunTriggerCommand(
        name="nightly",
        flow_id=uuid4(),
        flow_name="Nightly rebuild",
        schedule=TriggerSchedule(kind=TriggerScheduleKind.INTERVAL, interval_seconds=3600),
        webhook_enabled=True,
    )


async def _engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'triggers.sqlite3'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all, tables=[SQLModel.metadata.tables["adlc_run_trigger"]])
    return engine


async def test_sql_trigger_persistence_round_trip_and_delete(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)

    def factory() -> AsyncSession:
        return AsyncSession(engine)

    persistence = SqlAdlcTriggerPersistence(factory)
    command = _command()
    stored = AdlcRunTrigger(
        owner_id="owner-1",
        name=command.name,
        flow_id=command.flow_id,
        flow_name=command.flow_name,
        schedule=command.schedule,
        webhook_enabled=True,
        webhook_token="token-abc-123456",
        definitions=[],
    )
    await persistence.save(trigger=stored)
    loaded = await persistence.load()
    assert len(loaded) == 1
    restored = loaded[0]
    assert restored.trigger_id == stored.trigger_id
    assert restored.webhook_token == "token-abc-123456"
    assert restored.schedule.kind is TriggerScheduleKind.INTERVAL
    assert restored.schedule.interval_seconds == 3600

    stored.enabled = False
    await persistence.save(trigger=stored)
    reloaded = await persistence.load()
    assert len(reloaded) == 1
    assert reloaded[0].enabled is False

    assert await persistence.delete(trigger_id=stored.trigger_id) is True
    assert await persistence.load() == []
    assert await persistence.delete(trigger_id=stored.trigger_id) is False
    await engine.dispose()


def _app(trigger_service: AdlcTriggerService, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    flow = type("Flow", (), {})()
    flow.id = uuid4()
    flow.name = "Nightly rebuild"
    flow.data = _graph()
    flow.user_id = None
    flow.workspace_id = None
    flow.folder_id = None
    user = type("User", (), {})()
    user.id = uuid4()
    user.username = "owner"

    async def authorized_flow(**_kwargs):
        return flow

    async def allow_execute(*_args, **_kwargs):
        return None

    def _session():
        return SimpleSession()

    monkeypatch.setattr(adlc_api, "get_authorized_flow_for_read", authorized_flow)
    monkeypatch.setattr(adlc_api, "ensure_flow_permission", allow_execute)
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[injectable_session_scope] = _session
    app.dependency_overrides[adlc_api.get_adlc_trigger_service] = lambda: trigger_service
    return app


class SimpleSession:
    commit = AsyncMock()


async def test_trigger_api_lifecycle_and_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    trigger_service = AdlcTriggerService(
        AdlcRunService(),
        persistence=InMemoryAdlcTriggerPersistence(),
    )
    app = _app(trigger_service, monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/adlc/triggers",
            json={
                "name": "nightly",
                "flowId": str(uuid4()),
                "flowName": "Nightly rebuild",
                "schedule": {"kind": "INTERVAL", "intervalSeconds": 3600},
                "webhookEnabled": True,
            },
        )
        assert created.status_code == status.HTTP_201_CREATED
        body = created.json()
        assert body["webhook_configured"] is True
        assert "webhook_token" not in body

        listed = await client.get("/api/v1/adlc/triggers")
        assert listed.status_code == status.HTTP_200_OK
        assert [item["name"] for item in listed.json()] == ["nightly"]

        preview = await client.get(f"/api/v1/adlc/triggers/{body['trigger_id']}/next-runs?count=2")
        assert preview.status_code == status.HTTP_200_OK
        assert len(preview.json()["next_run_times"]) == 2

        cron_preview = await client.post(
            "/api/v1/adlc/triggers",
            json={
                "name": "cron",
                "flowId": str(uuid4()),
                "flowName": "Cron rebuild",
                "schedule": {"kind": "CRON", "cron": "30 5 * * *"},
            },
        )
        assert cron_preview.status_code == status.HTTP_201_CREATED
        cron_id = cron_preview.json()["trigger_id"]
        cron_times = await client.get(f"/api/v1/adlc/triggers/{cron_id}/next-runs?count=1")
        assert cron_times.status_code == status.HTTP_200_OK
        assert "T05:30" in cron_times.json()["next_run_times"][0]

        invalid = await client.post(
            "/api/v1/adlc/triggers",
            json={
                "name": "broken",
                "flowId": str(uuid4()),
                "flowName": "Broken",
                "schedule": {"kind": "CRON", "cron": "not a cron"},
            },
        )
        assert invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        token_view = await client.post(f"/api/v1/adlc/triggers/{body['trigger_id']}/rotate-webhook-token")
        assert token_view.status_code == status.HTTP_200_OK
        token = token_view.json()["webhook_token"]

        fired = await client.post(f"/api/v1/adlc/triggers/webhook/{token}")
        assert fired.status_code == status.HTTP_200_OK
        assert fired.json()["status"] == "FIRED"
        assert fired.json()["workflow_run_id"] is not None

        unknown = await client.post("/api/v1/adlc/triggers/webhook/not-a-token")
        assert unknown.status_code == status.HTTP_404_NOT_FOUND

        disabled = await client.patch(
            f"/api/v1/adlc/triggers/{body['trigger_id']}",
            json={"enabled": False},
        )
        assert disabled.status_code == status.HTTP_200_OK
        assert disabled.json()["enabled"] is False

        deleted = await client.delete(f"/api/v1/adlc/triggers/{body['trigger_id']}")
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        missing = await client.get(f"/api/v1/adlc/triggers/{body['trigger_id']}")
        assert missing.status_code == status.HTTP_404_NOT_FOUND

# ruff: noqa: S101, PLR2004, PT018, EM101 - owner and idempotency assertions with fixed errors.

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, Response

from langflow.adlc.run_service import AdlcRunNotFoundError
from langflow.adlc.workflow_plugin_client import WorkflowPluginClient
from langflow.adlc.workflow_plugins import PluginLedger, WorkflowPluginService
from langflow.api.v1.adlc_workflow_plugins import HealthCommand, health, view
from tests.unit.adlc.test_workflow_plugins import Backend


async def test_owner_only_health_is_idempotent_and_history_survives_service_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("ADLC_WORKFLOW_PLUGINS_ENABLED", "true")
    monkeypatch.delenv("ADLC_WORKFLOW_PLUGIN_REGISTRY", raising=False)
    owner, flow_id, run_id = uuid4(), uuid4(), uuid4()

    class Runs:
        async def get_run(self, incoming, *, owner_id):
            if str(owner_id) != str(owner) or incoming != run_id:
                raise AdlcRunNotFoundError("unknown")
            return SimpleNamespace(id=run_id, flow_id=flow_id)

    backend = Backend()
    plugins = WorkflowPluginService(
        PluginLedger(tmp_path / "calls.db"),
        client=WorkflowPluginClient(transport=httpx.MockTransport(backend.response)),
    )
    command = HealthCommand(call_id=uuid4())
    first = await health(run_id, command, SimpleNamespace(id=owner), Runs(), plugins)
    count = len(backend.requests)
    second = await health(run_id, command, SimpleNamespace(id=owner), Runs(), plugins)
    assert first == second and len(backend.requests) == count
    with pytest.raises(HTTPException) as other:
        await health(run_id, command, SimpleNamespace(id=uuid4()), Runs(), plugins)
    assert other.value.status_code == 404 and len(backend.requests) == count
    fresh = WorkflowPluginService(PluginLedger(tmp_path / "calls.db"))
    result = await view(run_id, SimpleNamespace(id=owner), Runs(), fresh, Response())
    assert len(result["records"]) == 1 and result["records"][0]["state"] == "SUCCEEDED"

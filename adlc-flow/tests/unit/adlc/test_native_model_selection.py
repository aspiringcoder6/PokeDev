from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.api.v1 import adlc_live as api
from langflow.adlc.live_workflows import LiveStore, validate_plan
from langflow.adlc.vai_services import ServiceCheckError
from test_live_workflows import plan, project


async def test_only_catalog_routes_can_be_selected_and_no_model_is_invoked(monkeypatch):
    client = AsyncMock()
    client.rpc.return_value = {"groups": [{"id": "alternate", "models": [{"id": "model-a"}]}]}
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr("dsh_web_sdk.DshClient", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(api, "settings", lambda: ("http://harness", "private-token"))
    assert await api.validated_execution_model(None) is None
    chosen = api.NativeModelRoute(provider="alternate", model="model-a")
    assert await api.validated_execution_model(chosen) == chosen.model_dump()
    client.rpc.assert_awaited_once_with("session/modelCatalog", {})
    client.create_session.assert_not_called()
    with pytest.raises(ServiceCheckError, match="LIVE_MODEL_NOT_AVAILABLE"):
        await api.validated_execution_model(api.NativeModelRoute(provider="alternate", model="unknown"))
    client.rpc.side_effect = RuntimeError("private transport detail")
    with pytest.raises(ServiceCheckError, match="LIVE_MODEL_CATALOG_UNAVAILABLE"):
        await api.validated_execution_model(chosen)


def test_execution_model_is_atomic_audited_and_cannot_change_on_replay(tmp_path):
    store = LiveStore(tmp_path / "live.db")
    owner = "alice"
    repo = project(store, owner)
    row, _ = store.create(owner, repo, "delivery", str(uuid4()), "Approved requirement", "Feature", "a" * 40)
    original = {"provider": "original", "model": "model-a"}
    alternate = {"provider": "alternate", "model": "model-b"}
    approved = validate_plan(plan())
    store.update(row["run_id"], {"state": "PLAN_READY", "plan": approved, "model_route": original})
    first, fresh = store.begin_execution(owner, row["run_id"], approved["digest"], model_route=alternate)
    assert fresh and first["model_route"] == alternate and first["planning_model_route"] == original
    assert first["execution_model_selected_by"] == owner
    assert first["plan"]["digest"] == approved["digest"]
    assert store.begin_execution(owner, row["run_id"], approved["digest"], model_route=alternate)[1] is False
    with pytest.raises(ServiceCheckError, match="LIVE_MODEL_ROUTE_CHANGED"):
        store.begin_execution(owner, row["run_id"], approved["digest"], model_route=original)
    with pytest.raises(ServiceCheckError, match="LIVE_RUN_NOT_FOUND"):
        store.begin_execution("bob", row["run_id"], approved["digest"], model_route=alternate)

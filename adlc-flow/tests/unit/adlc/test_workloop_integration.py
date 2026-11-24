from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException, Response
import pytest

from langflow.adlc.workloop_integration import WorkloopIntegration, bot_link, checked_url
from langflow.api.v1 import adlc_integrations as api


def test_bot_link_uses_the_slack_app_id_and_never_interprets_a_url_as_an_id():
    assert bot_link("A0CA54Q7FV3") == "https://slack.com/app_redirect?app=A0CA54Q7FV3"
    assert bot_link("A0CA54Q7FV3", "T12345678").endswith("&team=T12345678")
    assert bot_link("https://evil.example/") is None
    assert "team=" not in bot_link("A0CA54Q7FV3", "invalid")
    with pytest.raises(ValueError):
        checked_url("http://user:secret@host/")
    with pytest.raises(ValueError):
        checked_url("http://host/?token=secret")


@pytest.mark.asyncio
async def test_existing_registration_is_not_reported_as_a_verified_bot_response(monkeypatch):
    bridge = WorkloopIntegration()
    monkeypatch.setattr(bridge, "health", AsyncMock(return_value={"connector_connected": False}))
    monkeypatch.setattr(bridge, "mcp", AsyncMock(return_value={"server": {"name": "workloop-factory", "version": "1.30"}, "registered": True, "registry_error": False}))
    result = await bridge.inspect()
    assert result["workloop"]["available"] and result["mcp"]["available"]
    assert result["slack"]["registered"] is True
    assert result["slack"]["connector_connected"] is False
    assert result["slack"]["bot_response_status"] == "unverified"
    assert result["slack"]["scope"] == "conversation_and_spec"
    assert not result["errors"]


@pytest.mark.asyncio
async def test_outage_is_unknown_registration_and_does_not_leak_transport_details(monkeypatch):
    bridge = WorkloopIntegration()
    monkeypatch.setattr(bridge, "health", AsyncMock(side_effect=RuntimeError("private token value")))
    monkeypatch.setattr(bridge, "mcp", AsyncMock(side_effect=RuntimeError("private token value")))
    result = await bridge.inspect()
    assert result["slack"]["registered"] is None
    assert set(result["errors"]) == {"workloop", "mcp"}
    assert "private token value" not in str(result)


@pytest.mark.asyncio
async def test_registry_failure_preserves_verified_mcp_but_not_slack_registration(monkeypatch):
    bridge = WorkloopIntegration()
    monkeypatch.setattr(bridge, "health", AsyncMock(return_value={"connector_connected": False}))
    monkeypatch.setattr(bridge, "mcp", AsyncMock(return_value={"server": {}, "registered": None, "registry_error": True}))
    result = await bridge.inspect()
    assert result["mcp"]["available"]
    assert result["slack"]["registered"] is None
    assert result["errors"] == ["slack_registry"]


@pytest.mark.asyncio
async def test_api_requires_workspace_administrator_before_any_remote_call(monkeypatch):
    inspect = AsyncMock(return_value={"ok": True})
    factory = Mock(return_value=SimpleNamespace(inspect=inspect))
    monkeypatch.setattr(api, "WorkloopIntegration", factory)
    with pytest.raises(HTTPException) as exc:
        await api.workloop_integration(SimpleNamespace(is_superuser=False), Response())
    assert exc.value.status_code == 403
    factory.assert_not_called()
    response = Response()
    assert await api.workloop_integration(SimpleNamespace(is_superuser=True), response) == {"ok": True}
    assert response.headers["Cache-Control"] == "no-store"
    inspect.assert_awaited_once_with()

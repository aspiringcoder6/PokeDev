from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.vai_services import CheckService, CheckStore, PlatformClient, ServiceCheckError, redact, settings


def reserve(store, *, service="sandbox", identity=None, owner="owner", delivery="delivery", cycle="cycle"):
    return store.reserve(owner, delivery, cycle, service, identity or str(uuid4()))


def test_store_scopes_results_and_idempotency(tmp_path):
    store = CheckStore(tmp_path / "checks.sqlite")
    row, fresh = reserve(store)
    assert fresh
    assert reserve(store, identity=row["check_id"])[1] is False
    with pytest.raises(ServiceCheckError, match="ID_CONFLICT"):
        reserve(store, identity=row["check_id"], owner="other")
    assert store.list("other", "delivery", "cycle") == []
    assert store.list("owner", "delivery", "other-cycle") == []
    with pytest.raises(ServiceCheckError, match="ALREADY_ACTIVE"):
        reserve(store)
    store.update(row["check_id"], {"state": "SUCCEEDED"})
    assert reserve(store)[1]


@pytest.mark.asyncio
async def test_restart_observes_existing_intent_without_resending_create(tmp_path):
    store = CheckStore(tmp_path / "checks.sqlite")
    row, _ = reserve(store)
    store.update(row["check_id"], {"state": "UNCONFIRMED"})
    client = AsyncMock()
    client.request.return_value = {**row, "state": "SUCCEEDED", "summary": {"passed": True}}
    service = CheckService(CheckStore(store.path), client)
    await service.follow(row)
    client.request.assert_awaited_once_with("GET", "/api/v1/pokedev-services/checks/" + row["check_id"] + "?service=sandbox&scope_id=" + row["scope_id"])
    assert store.list("owner", "delivery", "cycle")[0]["state"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_uncertain_create_is_retained_and_never_retried(tmp_path):
    store = CheckStore(tmp_path / "checks.sqlite")
    row, _ = reserve(store)
    client = AsyncMock()
    client.request.side_effect = ServiceCheckError("VAI_PLATFORM_UNAVAILABLE", 503)
    service = CheckService(store, client)
    await service.follow(row, create=True)
    assert client.request.await_count == 1
    assert client.request.call_args.args[0] == "POST"
    retained = store.list("owner", "delivery", "cycle")[0]
    assert retained["state"] == "UNCONFIRMED"
    assert retained["verification_evidence"] is False


@pytest.mark.asyncio
async def test_gateway_retry_is_only_for_observations():
    client = PlatformClient()
    client._request_once = AsyncMock(side_effect=[ServiceCheckError("VAI_PLATFORM_UNAVAILABLE", 503), {"observed": True}])
    assert await client.request("GET", "/checks/known") == {"observed": True}
    assert client._request_once.await_count == 2
    client._request_once = AsyncMock(side_effect=ServiceCheckError("VAI_PLATFORM_UNAVAILABLE", 503))
    with pytest.raises(ServiceCheckError):
        await client.request("POST", "/checks", {"check_id": "known"})
    assert client._request_once.await_count == 1


def test_wrong_scope_receipt_is_rejected_and_cannot_attest_verify(tmp_path):
    store = CheckStore(tmp_path / "checks.sqlite")
    row, _ = reserve(store)
    service = CheckService(store, AsyncMock())
    for change in ({"scope_id": "foreign"}, {"request_digest": "wrong"}, {"verification_evidence": True}):
        with pytest.raises(ServiceCheckError, match="SCOPE_MISMATCH"):
            service.accept(row, {**row, "state": "SUCCEEDED", **change})
    assert store.list("owner", "delivery", "cycle")[0]["state"] == "RESERVED"


def test_private_settings_and_redaction(tmp_path, monkeypatch):
    file = tmp_path / ".env"
    file.write_text("VAI_PLATFORM_URL=http://platform.test:9982\nVAI_PLATFORM_TOKEN=private\n")
    monkeypatch.setenv("ADLC_VAI_PLATFORM_ENV_FILE", str(file))
    monkeypatch.delenv("VAI_PLATFORM_URL", raising=False)
    monkeypatch.delenv("VAI_PLATFORM_TOKEN", raising=False)
    assert settings() == ("http://platform.test:9982", "private")
    monkeypatch.setenv("VAI_PLATFORM_URL", "http://platform.test/?token=private")
    with pytest.raises(ServiceCheckError, match="NOT_CONFIGURED"):
        settings()
    assert "private" not in str(redact({"token": "private", "text": "Bearer private http://x/?token=private"}))


def test_process_configuration_never_reads_a_dotenv_file(monkeypatch):
    monkeypatch.setenv("VAI_PLATFORM_URL", "http://platform.test:9982")
    monkeypatch.setenv("VAI_PLATFORM_TOKEN", "private")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("dotenv must not be read")
    monkeypatch.setattr("langflow.adlc.vai_services.dotenv_values", forbidden)
    assert settings() == ("http://platform.test:9982", "private")


@pytest.mark.asyncio
async def test_api_authorizes_delivery_and_cycle_before_calling_platform(monkeypatch):
    from langflow.api.v1 import adlc_vai_services as api
    from fastapi import HTTPException

    session, actor = AsyncMock(), object()
    source = AsyncMock(side_effect=HTTPException(404))
    monkeypatch.setattr(api, "source", source)
    with pytest.raises(HTTPException):
        await api.scope(session, uuid4(), uuid4(), actor, write=True)
    assert source.call_args.kwargs["write"] is True
    session.commit.assert_not_awaited()

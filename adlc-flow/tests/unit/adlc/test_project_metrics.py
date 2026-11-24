import copy
import json
import time
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from langflow.adlc.live_workflows import LiveStore
from langflow.adlc.project_metrics import ProjectMetrics, TOKEN_KEYS, measured_usage, run_timing, session_bindings, union_seconds
from langflow.adlc.vai_services import ServiceCheckError


def setup_metrics(tmp_path):
    store = LiveStore(tmp_path / "runs.db")
    owner, project = str(uuid4()), str(uuid4())
    p = store.save_project(owner, project, {"id": 1, "name": "metrics", "full_name": "admin/metrics", "html_url": "http://example/metrics"}, "/source", "a"*40)
    live = SimpleNamespace(store=store, observe=lambda r: r)
    metrics = ProjectMetrics(live)
    run, _ = store.create(owner, p, str(uuid4()), str(uuid4()), "Requirement", "Test metrics", "a"*40)
    run = store.update(run["run_id"], {"phase": "execution", "state": "SUCCEEDED", "completed_at": time.time(), "model_route": {"provider": "netmind", "model": "test-model"}, "nodes": [{"id": "DEV", "session_id": "owned-session", "state": "DONE"}]})
    return metrics, store, owner, project, run


def usage(identity, tokens=None):
    return {"sessionId": identity, "projections": {"values": {"tokenUsage": tokens or {"uncachedInputTokens": 100, "cacheReadTokens": 20, "cacheWriteTokens": 10, "outputTokens": 30}}}}


def test_missing_usage_is_unknown_but_explicit_zero_is_measured():
    assert measured_usage({}) is None
    assert measured_usage(usage("s", {"other": 12})) is None
    assert measured_usage(usage("s", {"uncachedInputTokens": 0})) is None
    assert measured_usage(usage("s", {"uncachedInputTokens": 0, "outputTokens": 0})) == dict.fromkeys(TOKEN_KEYS, 0)
    for invalid in (-1, True, "123", 1.2, float("nan")):
        assert measured_usage(usage("s", {"outputTokens": invalid})) is None


def test_parallel_human_waits_are_unioned_and_approval_wait_is_excluded():
    run = {"state": "SUCCEEDED", "phase": "execution", "created_at": 100, "planning_completed_at": 200, "execution_started_at": 300, "completed_at": 500, "nodes": [{"id": "FIX1"}, {"id": "DEV_R1", "repair": True}], "checks": [{"id": "verify-0"}, {"id": "verify-1"}]}
    questions = [{"created_at": 320, "responded_at": 360}, {"created_at": 330, "responded_at": 380}]
    result = run_timing(run, questions, clock=600)
    assert result["human_wait_seconds"] == 60
    assert result["approval_wait_seconds"] == 100
    assert result["active_seconds"] == 240
    assert result["repair_rounds"] == 2 and result["verification_attempts"] == 2
    assert run_timing({**run, "auto_timing": {"active_seconds": 210}}, questions)["active_seconds"] == 210
    assert run_timing({**run, "state": "UNCONFIRMED"}, questions)["active_seconds"] is None
    assert union_seconds([(1, 3), (2, 5), (8, 9), (None, 10)]) == 5


@pytest.mark.asyncio
async def test_only_own_sessions_are_persisted_and_prices_require_explicit_configuration(tmp_path):
    metrics, store, owner, project, run = setup_metrics(tmp_path)
    client = SimpleNamespace(rpc=AsyncMock(return_value={"items": [usage("owned-session"), usage("foreign-session")]}))
    result = await metrics.refresh(owner, project, client)
    assert result["measured_sessions"] == 1
    assert client.rpc.await_args.args[1]["_request"]["sessionIds"] == ["owned-session"]
    with closing(store.db()) as db:
        assert [r[0] for r in db.execute("SELECT session FROM project_usage")] == ["owned-session"]
    summary = metrics.summary(owner, project)
    assert summary["usage"]["tokens"] == 160 and summary["usage"]["cost_usd"] is None
    rates = [{"provider": "netmind", "model": "test-model", "source": "User contract 2026-10-27", "input": 1, "cache_read": .5, "cache_write": 2, "output": 3}]
    metrics.save_pricing(owner, project, 1, rates)
    priced = metrics.summary(owner, project)
    assert priced["usage"]["cost_usd"] == .00022
    assert priced["usage"]["cost_kind"] == "estimate_from_configured_rates"
    assert priced["models"] == [{"provider": "netmind", "model": "test-model"}]
    with pytest.raises(ServiceCheckError, match="CHANGED"): metrics.save_pricing(owner, project, 1, rates)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"): metrics.summary("foreign", project)


@pytest.mark.asyncio
async def test_unavailable_source_keeps_known_usage_and_reused_session_is_not_charged_twice(tmp_path):
    metrics, store, owner, project, run = setup_metrics(tmp_path)
    await metrics.refresh(owner, project, SimpleNamespace(rpc=AsyncMock(return_value={"items": [usage("owned-session")]})))
    await metrics.refresh(owner, project, SimpleNamespace(rpc=AsyncMock(side_effect=TimeoutError)))
    summary = metrics.summary(owner, project)
    assert summary["usage"]["tokens"] == 160
    assert summary["refresh"]["error_code"] == "LIVE_METRICS_SOURCE_UNAVAILABLE"
    reused = {**run, "run_id": "retry", "nodes": [{"id": "DEV", "session_id": "owned-session", "reused_from": run["run_id"]}]}
    assert len(session_bindings([run, reused])) == 1
    assert session_bindings([reused]) == {}


@pytest.mark.parametrize("change", [{"input": -1}, {"input": float("inf")}, {"cache_read": None}, {"source": ""}, {"provider": " "}, {"output": True}])
def test_price_config_cannot_invent_missing_rates_or_invalid_numbers(tmp_path, change):
    metrics, store, owner, project, run = setup_metrics(tmp_path)
    rate = {"provider": "netmind", "model": "test-model", "source": "Explicit contract", "input": 1, "cache_read": 1, "cache_write": 1, "output": 1, **change}
    with pytest.raises(ServiceCheckError, match="PRICING_INVALID"): metrics.save_pricing(owner, project, 1, [rate])
    assert metrics.pricing(owner, project)["rates"] == []


def test_worker_captured_usage_is_available_without_projection_retention(tmp_path):
    metrics, store, owner, project, run = setup_metrics(tmp_path)
    node = {**run["nodes"][0], "usage": {"tokens": dict.fromkeys(TOKEN_KEYS, 5), "source": "harness_session_projection", "collected_at": "2026-10-27T12:00:00+00:00"}}
    store.update(run["run_id"], {"nodes": [node]})
    assert metrics.summary(owner, project)["usage"]["tokens"] == 20


@pytest.mark.asyncio
async def test_metrics_api_checks_project_permission_before_reading_or_pricing(monkeypatch):
    from langflow.api.v1 import adlc_metrics as api
    service = SimpleNamespace(metrics=SimpleNamespace(summary=AsyncMock(), save_pricing=AsyncMock()))
    monkeypatch.setattr(api, "live_service", lambda: service)
    authorize = AsyncMock(side_effect=ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404))
    monkeypatch.setattr(api, "authorize_project", authorize)
    actor = SimpleNamespace(id=uuid4()); project = uuid4(); session = AsyncMock()
    with pytest.raises(api.HTTPException): await api.project_metrics(project, session, actor, SimpleNamespace(headers={}), 30)
    with pytest.raises(api.HTTPException): await api.save_pricing(project, api.PricingCommand(expected_revision=1, rates=[]), session, actor)
    assert authorize.await_args.kwargs == {"write": True}
    service.metrics.summary.assert_not_called(); service.metrics.save_pricing.assert_not_called()

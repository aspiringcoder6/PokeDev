# ruff: noqa: INP001, PLR2004, S101

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langflow.adlc.metrics import (
    ALERT_DEADLINE_BREACH,
    ALERT_DISPATCH_DENIED,
    ALERT_TASK_FAILURE_RATE,
    AdlcMetricsCollector,
    CompositeAdlcObservabilitySink,
    render_prometheus,
)
from langflow.adlc.observability import (
    AdlcObservationOutcome,
    AdlcObservationType,
    AdlcOperationObservation,
)
from langflow.api.v1 import adlc as adlc_api
from langflow.services.auth.utils import get_current_active_user

_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _observation(
    *,
    event_type: AdlcObservationType = AdlcObservationType.TASK_DISPATCH_COMPLETED,
    outcome: AdlcObservationOutcome = AdlcObservationOutcome.SUCCEEDED,
    duration_ms: float = 100.0,
    error_code: str | None = None,
    occurred_at: datetime = _NOW,
) -> AdlcOperationObservation:
    return AdlcOperationObservation(
        event_type=event_type,
        outcome=outcome,
        duration_ms=duration_ms,
        error_code=error_code,
        occurred_at=occurred_at,
    )


def _collector_with(events: list[AdlcOperationObservation], *, window_seconds: float = 900.0) -> AdlcMetricsCollector:
    collector = AdlcMetricsCollector(window_seconds=window_seconds, clock=lambda: _NOW)
    for event in events:
        collector.emit(event)
    return collector


def test_snapshot_counts_outcomes_errors_and_durations() -> None:
    events = [
        _observation(duration_ms=10.0),
        _observation(duration_ms=30.0),
        _observation(outcome=AdlcObservationOutcome.FAILED, duration_ms=90.0, error_code="EXECUTION_FAILED"),
        _observation(
            event_type=AdlcObservationType.PLAN_VALIDATION_COMPLETED,
            outcome=AdlcObservationOutcome.INVALID,
            duration_ms=5.0,
        ),
    ]
    snapshot = _collector_with(events).snapshot(now=_NOW)

    assert snapshot.total_observations == 4
    dispatch_counters = snapshot.counters["adlc.task_dispatch.completed"]
    assert dispatch_counters == {"SUCCEEDED": 2, "FAILED": 1}
    assert snapshot.counters["adlc.plan_validation.completed"] == {"INVALID": 1}
    assert snapshot.error_counters == {"EXECUTION_FAILED": 1}
    stats = snapshot.durations["adlc.task_dispatch.completed"]
    assert stats.count == 3
    assert stats.max_ms == 90.0
    assert stats.p50_ms >= 10.0
    assert snapshot.alerts == []


def test_rolling_window_prunes_expired_events() -> None:
    old = _observation(occurred_at=_NOW - timedelta(seconds=1800))
    fresh = _observation(occurred_at=_NOW)
    snapshot = _collector_with([old, fresh]).snapshot(now=_NOW)

    assert snapshot.total_observations == 1
    assert snapshot.counters["adlc.task_dispatch.completed"]["SUCCEEDED"] == 1


def test_failure_rate_alert_requires_min_samples_and_threshold() -> None:
    below_samples = [
        _observation(outcome=AdlcObservationOutcome.FAILED, error_code="EXECUTION_FAILED"),
        _observation(),
        _observation(),
        _observation(),
    ]
    assert _collector_with(below_samples).snapshot(now=_NOW).alerts == []

    many_failures = [
        _observation(outcome=AdlcObservationOutcome.FAILED, error_code="EXECUTION_FAILED") for _ in range(6)
    ] + [_observation() for _ in range(4)]
    alerts = _collector_with(many_failures).snapshot(now=_NOW).alerts
    assert [alert.code for alert in alerts] == [ALERT_TASK_FAILURE_RATE]
    assert alerts[0].severity == "ERROR"
    assert alerts[0].observed_value == 0.6


def test_deadline_breach_and_denied_alerts() -> None:
    breaches = [
        _observation(outcome=AdlcObservationOutcome.FAILED, error_code="TASK_DEADLINE_EXCEEDED") for _ in range(2)
    ]
    alerts = _collector_with(breaches).snapshot(now=_NOW).alerts
    assert [alert.code for alert in alerts] == [ALERT_DEADLINE_BREACH]
    assert alerts[0].severity == "WARNING"

    denied = [_observation(outcome=AdlcObservationOutcome.DENIED) for _ in range(3)]
    alerts = _collector_with(denied).snapshot(now=_NOW).alerts
    assert [alert.code for alert in alerts] == [ALERT_DISPATCH_DENIED]


def test_composite_sink_fans_out_to_all_sinks() -> None:
    first = AdlcMetricsCollector(clock=lambda: _NOW)
    second = AdlcMetricsCollector(clock=lambda: _NOW)
    composite = CompositeAdlcObservabilitySink((first, second))
    composite.emit(_observation())

    assert first.snapshot(now=_NOW).total_observations == 1
    assert second.snapshot(now=_NOW).total_observations == 1


def test_clear_empties_window() -> None:
    collector = _collector_with([_observation()])
    collector.clear()
    assert collector.snapshot(now=_NOW).total_observations == 0


def test_prometheus_render_contains_counters_durations_and_alerts() -> None:
    events = [
        _observation(duration_ms=10.0),
        _observation(outcome=AdlcObservationOutcome.FAILED, duration_ms=50.0, error_code="EXECUTION_FAILED"),
    ] * 5
    snapshot = _collector_with(events).snapshot(now=_NOW)
    rendered = render_prometheus(snapshot)

    assert "adlc_observations_total 10" in rendered
    assert 'adlc_task_dispatch_completed_total{outcome="FAILED"} 5' in rendered
    assert 'adlc_task_dispatch_completed_duration_ms{quantile="0.95"}' in rendered
    assert "adlc_error_execution_failed_total 5" in rendered
    assert "adlc_alert_adlc_task_failure_rate_high" in rendered
    assert rendered.endswith("\n")


async def test_metrics_api_exposes_json_and_prometheus() -> None:
    collector = AdlcMetricsCollector(clock=lambda: _NOW)
    collector.emit(_observation(duration_ms=12.0))
    user = type("User", (), {})()
    user.id = uuid4()
    app = FastAPI()
    app.include_router(adlc_api.router, prefix="/api/v1")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[adlc_api.get_adlc_metrics_collector] = lambda: collector

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        json_response = await client.get("/api/v1/adlc/metrics")
        assert json_response.status_code == 200
        body = json_response.json()
        assert body["total_observations"] == 1
        assert body["counters"]["adlc.task_dispatch.completed"]["SUCCEEDED"] == 1
        assert body["durations"]["adlc.task_dispatch.completed"]["count"] == 1

        prometheus_response = await client.get("/api/v1/adlc/metrics/prometheus")
        assert prometheus_response.status_code == 200
        assert prometheus_response.headers["content-type"].startswith("text/plain")
        assert "adlc_observations_total 1" in prometheus_response.text

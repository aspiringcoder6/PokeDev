"""Metrics aggregation, alert rules, and Prometheus export over the ADLC observation stream."""

from __future__ import annotations

import os
from collections import deque
from datetime import datetime, timedelta, timezone
from statistics import quantiles
from threading import Lock
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.observability import (
    AdlcObservabilitySink,
    AdlcObservationOutcome,
    AdlcObservationType,
    AdlcOperationObservation,
)
from lfx.log.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

METRICS_CONTRACT_VERSION = "0.1"
_DEFAULT_WINDOW_SECONDS = 900.0
_MAX_WINDOW_EVENTS = 20_000

ALERT_TASK_FAILURE_RATE = "ADLC_TASK_FAILURE_RATE_HIGH"
ALERT_DEADLINE_BREACH = "ADLC_TASK_DEADLINE_BREACH"
ALERT_DISPATCH_DENIED = "ADLC_TASK_DISPATCH_DENIED"


class AdlcAlertThresholds(BaseModel):
    """Configurable alert thresholds for one collector instance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    failure_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    failure_min_samples: int = Field(default=10, ge=1)
    deadline_breaches: int = Field(default=1, ge=1)
    denied_dispatches: int = Field(default=3, ge=1)


_THRESHOLD_ENV_KEYS: dict[str, tuple[str, type]] = {
    "ADLC_METRICS_FAILURE_RATE": ("failure_rate", float),
    "ADLC_METRICS_FAILURE_MIN_SAMPLES": ("failure_min_samples", int),
    "ADLC_METRICS_DEADLINE_BREACHES": ("deadline_breaches", int),
    "ADLC_METRICS_DENIED_DISPATCHES": ("denied_dispatches", int),
}


def thresholds_from_environment(environ: Mapping[str, str] | None = None) -> AdlcAlertThresholds:
    """Build alert thresholds from ADLC_METRICS_* environment variables."""
    source = os.environ if environ is None else environ
    overrides: dict[str, float | int] = {}
    for env_key, (field_name, caster) in _THRESHOLD_ENV_KEYS.items():
        raw = source.get(env_key)
        if raw is None or raw == "":
            continue
        try:
            overrides[field_name] = caster(raw)
        except ValueError:
            logger.warning("adlc.metrics.invalid_threshold_env", env_key=env_key, raw_value=raw)
    return AdlcAlertThresholds(**overrides)


_DEFAULT_THRESHOLDS = AdlcAlertThresholds()


class DurationStats(BaseModel):
    """Latency percentiles for one observed operation type over the window."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    p99_ms: float = Field(ge=0)
    max_ms: float = Field(ge=0)


class AdlcAlert(BaseModel):
    """One threshold breach projected from the metrics window."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Literal["WARNING", "ERROR"]
    message: str
    observed_value: float = Field(ge=0)
    threshold: float = Field(ge=0)
    triggered_at: datetime


class AdlcMetricsSnapshot(BaseModel):
    """Allow-listed aggregation view of the observation stream window."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = METRICS_CONTRACT_VERSION
    generated_at: datetime
    window_seconds: float = Field(gt=0)
    total_observations: int = Field(ge=0)
    counters: dict[str, dict[str, int]] = Field(default_factory=dict)
    error_counters: dict[str, int] = Field(default_factory=dict)
    durations: dict[str, DurationStats] = Field(default_factory=dict)
    alerts: list[AdlcAlert] = Field(default_factory=list)


class _WindowEvent:
    __slots__ = ("duration_ms", "error_code", "event_type", "occurred_at", "outcome")

    def __init__(
        self,
        occurred_at: datetime,
        event_type: AdlcObservationType,
        outcome: AdlcObservationOutcome,
        duration_ms: float,
        error_code: str | None,
    ) -> None:
        self.occurred_at = occurred_at
        self.event_type = event_type
        self.outcome = outcome
        self.duration_ms = duration_ms
        self.error_code = error_code


class AdlcMetricsCollector:
    """Thread-safe rolling-window aggregator usable as an observability sink."""

    def __init__(
        self,
        *,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
        max_events: int = _MAX_WINDOW_EVENTS,
        thresholds: AdlcAlertThresholds | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._window_seconds = window_seconds
        self._thresholds = thresholds if thresholds is not None else _DEFAULT_THRESHOLDS
        self._events: deque[_WindowEvent] = deque(maxlen=max_events)
        self._lock = Lock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def emit(self, observation: AdlcOperationObservation) -> None:
        """Record one observation into the rolling window."""
        event = _WindowEvent(
            occurred_at=observation.occurred_at,
            event_type=observation.event_type,
            outcome=observation.outcome,
            duration_ms=observation.duration_ms,
            error_code=observation.error_code,
        )
        with self._lock:
            self._events.append(event)
            self._prune_locked(self._window_deadline(self._clock()))

    def snapshot(self, *, now: datetime | None = None) -> AdlcMetricsSnapshot:
        """Return the current aggregation and evaluate alert rules."""
        current = now or self._clock()
        deadline = self._window_deadline(current)
        with self._lock:
            self._prune_locked(deadline)
            events = list(self._events)
        counters: dict[str, dict[str, int]] = {}
        error_counters: dict[str, int] = {}
        durations: dict[str, list[float]] = {}
        for event in events:
            outcome_map = counters.setdefault(event.event_type.value, {})
            outcome_map[event.outcome.value] = outcome_map.get(event.outcome.value, 0) + 1
            if event.error_code:
                error_counters[event.error_code] = error_counters.get(event.error_code, 0) + 1
            durations.setdefault(event.event_type.value, []).append(event.duration_ms)
        stats = {name: _duration_stats(samples) for name, samples in durations.items()}
        alerts = _evaluate_alerts(events, current, self._thresholds)
        return AdlcMetricsSnapshot(
            generated_at=current,
            window_seconds=self._window_seconds,
            total_observations=len(events),
            counters=counters,
            error_counters=error_counters,
            durations=stats,
            alerts=alerts,
        )

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def _window_deadline(self, current: datetime) -> datetime:
        return current - timedelta(seconds=self._window_seconds)

    def _prune_locked(self, deadline: datetime) -> None:
        while self._events and self._events[0].occurred_at < deadline:
            self._events.popleft()


def _duration_stats(samples: list[float]) -> DurationStats:
    ordered = sorted(samples)
    if not ordered:
        return DurationStats(count=0, p50_ms=0.0, p95_ms=0.0, p99_ms=0.0, max_ms=0.0)
    if len(ordered) == 1:
        value = ordered[0]
        return DurationStats(count=1, p50_ms=value, p95_ms=value, p99_ms=value, max_ms=value)
    cut_points = quantiles(ordered, n=100, method="inclusive")
    return DurationStats(
        count=len(ordered),
        p50_ms=cut_points[49],
        p95_ms=cut_points[94],
        p99_ms=cut_points[98],
        max_ms=ordered[-1],
    )


def _evaluate_alerts(
    events: list[_WindowEvent],
    current: datetime,
    thresholds: AdlcAlertThresholds,
) -> list[AdlcAlert]:
    alerts: list[AdlcAlert] = []
    dispatches = [event for event in events if event.event_type is AdlcObservationType.TASK_DISPATCH_COMPLETED]
    failures = [event for event in dispatches if event.outcome is AdlcObservationOutcome.FAILED]
    if len(dispatches) >= thresholds.failure_min_samples:
        rate = len(failures) / len(dispatches)
        if rate >= thresholds.failure_rate:
            alerts.append(
                AdlcAlert(
                    code=ALERT_TASK_FAILURE_RATE,
                    severity="ERROR",
                    message="Task dispatch failure rate is at or above the alert threshold.",
                    observed_value=round(rate, 4),
                    threshold=thresholds.failure_rate,
                    triggered_at=current,
                )
            )
    deadline_breaches = sum(1 for event in failures if event.error_code == "TASK_DEADLINE_EXCEEDED")
    if deadline_breaches >= thresholds.deadline_breaches:
        alerts.append(
            AdlcAlert(
                code=ALERT_DEADLINE_BREACH,
                severity="WARNING",
                message="One or more coordinator deadline breaches occurred in the window.",
                observed_value=float(deadline_breaches),
                threshold=float(thresholds.deadline_breaches),
                triggered_at=current,
            )
        )
    denied = sum(1 for event in dispatches if event.outcome is AdlcObservationOutcome.DENIED)
    if denied >= thresholds.denied_dispatches:
        alerts.append(
            AdlcAlert(
                code=ALERT_DISPATCH_DENIED,
                severity="WARNING",
                message="Repeated denied task dispatches suggest an authorization or routing problem.",
                observed_value=float(denied),
                threshold=float(thresholds.denied_dispatches),
                triggered_at=current,
            )
        )
    return alerts


class AdlcAlertSink(Protocol):
    """Optional port that receives alerts when a snapshot is evaluated."""

    def handle_alert(self, alert: AdlcAlert) -> None: ...


class CompositeAdlcObservabilitySink(AdlcObservabilitySink):
    """Fan one observation out to several sinks without letting one break the rest."""

    def __init__(self, sinks: tuple[AdlcObservabilitySink, ...]) -> None:
        self._sinks = sinks

    def emit(self, observation: AdlcOperationObservation) -> None:
        for sink in self._sinks:
            sink.emit(observation)


def render_prometheus(snapshot: AdlcMetricsSnapshot) -> str:
    """Render a minimal Prometheus text exposition for the snapshot."""
    lines: list[str] = []
    lines.append("# HELP adlc_observations_total ADLC observations aggregated in the rolling window.")
    lines.append("# TYPE adlc_observations_total counter")
    lines.append(f"adlc_observations_total {snapshot.total_observations}")
    for event_type, outcomes in sorted(snapshot.counters.items()):
        metric = f"adlc_{event_type.replace('.', '_').lower()}_total"
        lines.append(f"# TYPE {metric} counter")
        for outcome, count in sorted(outcomes.items()):
            lines.append(f'{metric}{{outcome="{outcome}"}} {count}')
    for event_type, stats in sorted(snapshot.durations.items()):
        metric = f"adlc_{event_type.replace('.', '_').lower()}_duration_ms"
        lines.append(f"# TYPE {metric} summary")
        lines.append(f'{metric}{{quantile="0.5"}} {stats.p50_ms}')
        lines.append(f'{metric}{{quantile="0.95"}} {stats.p95_ms}')
        lines.append(f'{metric}{{quantile="0.99"}} {stats.p99_ms}')
        lines.append(f"{metric}_max {stats.max_ms}")
    for code, count in sorted(snapshot.error_counters.items()):
        metric = f"adlc_error_{code.lower()}_total"
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {count}")
    for alert in snapshot.alerts:
        metric = f"adlc_alert_{alert.code.lower()}"
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f'{metric}{{severity="{alert.severity}"}} 1')
    return "\n".join(lines) + "\n"

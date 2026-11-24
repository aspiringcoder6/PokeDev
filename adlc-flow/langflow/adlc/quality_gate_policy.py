"""Configuration-driven quality gate policy for the ADLC run scheduler (G6).

The scheduler consults this module before attaching the independent
quality verdict to a succeeded ``TaskResult``. Every rule is sourced from
environment configuration so deployments can enable/disable the gate per
task type, per executor service, or for mock execution without touching
code:

* ``ADLC_QUALITY_GATE`` — master switch (default: ``on``).
* ``ADLC_QUALITY_GATE_TASK_TYPES`` — comma-separated allowlist of task
  types the gate applies to (default: empty = every task type).
* ``ADLC_QUALITY_GATE_EXEMPT_TASK_TYPES`` — comma-separated task types
  the gate never applies to (default: empty).
* ``ADLC_QUALITY_GATE_EXEMPT_SERVICES`` — comma-separated executor
  services the gate never applies to (default: empty).
* ``ADLC_QUALITY_GATE_EXEMPT_MOCK`` — whether mock execution (run
  metadata ``mock=true``) skips the gate (default: ``on``).
* ``ADLC_RUN_REFLECTION`` — whether run completion dispatches
  ``host.dispatch_reflect`` and stores a ``ReflectionReport`` in run
  metadata (default: ``on``; skipped gracefully when no reflection
  plugin is available).

The gate itself only ever runs when a task definition declares
``acceptance_criteria``; with no declared criteria the legacy behavior
is preserved byte-for-byte.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

QUALITY_GATE_ENV = "ADLC_QUALITY_GATE"
QUALITY_GATE_TASK_TYPES_ENV = "ADLC_QUALITY_GATE_TASK_TYPES"
QUALITY_GATE_EXEMPT_TASK_TYPES_ENV = "ADLC_QUALITY_GATE_EXEMPT_TASK_TYPES"
QUALITY_GATE_EXEMPT_SERVICES_ENV = "ADLC_QUALITY_GATE_EXEMPT_SERVICES"
QUALITY_GATE_EXEMPT_MOCK_ENV = "ADLC_QUALITY_GATE_EXEMPT_MOCK"
RUN_REFLECTION_ENV = "ADLC_RUN_REFLECTION"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in _TRUE_VALUES


def _word_set(name: str) -> frozenset[str]:
    raw = os.getenv(name, "")
    return frozenset(item.strip().upper() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class QualityGateRunPolicy:
    """Resolved gate policy for one run service instance."""

    enabled: bool = True
    task_types: frozenset[str] = frozenset()
    exempt_task_types: frozenset[str] = frozenset()
    exempt_services: frozenset[str] = frozenset()
    exempt_mock_execution: bool = True

    def applies_to_task(
        self,
        *,
        task_type: str,
        executor_service: str,
        mock_execution: bool,
    ) -> bool:
        """Return whether the independent gate must judge this task."""
        if not self.enabled:
            return False
        if executor_service in self.exempt_services:
            return False
        if mock_execution and self.exempt_mock_execution:
            return False
        normalized = task_type.strip().upper()
        if normalized in self.exempt_task_types:
            return False
        if self.task_types and normalized not in self.task_types:
            return False
        return True


def load_quality_gate_policy() -> QualityGateRunPolicy:
    """Read the gate policy from environment configuration."""
    return QualityGateRunPolicy(
        enabled=_flag(QUALITY_GATE_ENV, True),
        task_types=_word_set(QUALITY_GATE_TASK_TYPES_ENV),
        exempt_task_types=_word_set(QUALITY_GATE_EXEMPT_TASK_TYPES_ENV),
        exempt_services=frozenset(os.getenv(QUALITY_GATE_EXEMPT_SERVICES_ENV, "").split(",")) - {""},
        exempt_mock_execution=_flag(QUALITY_GATE_EXEMPT_MOCK_ENV, True),
    )


def reflection_enabled() -> bool:
    """Return whether post-run reflection is configured on."""
    return _flag(RUN_REFLECTION_ENV, True)


__all__ = [
    "QUALITY_GATE_ENV",
    "QUALITY_GATE_EXEMPT_MOCK_ENV",
    "QUALITY_GATE_EXEMPT_SERVICES_ENV",
    "QUALITY_GATE_EXEMPT_TASK_TYPES_ENV",
    "QUALITY_GATE_TASK_TYPES_ENV",
    "RUN_REFLECTION_ENV",
    "QualityGateRunPolicy",
    "load_quality_gate_policy",
    "reflection_enabled",
]

"""Secret-safe operational observations for the ADLC planning and runtime path."""

from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from time import perf_counter_ns
from typing import Annotated, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lfx.log.logger import logger

OBSERVABILITY_CONTRACT_VERSION = "0.1"
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_DENIED_ERROR_CODES = frozenset({"CAPABILITY_NOT_AUTHORIZED", "PACKAGE_NOT_VISIBLE"})
_StableCode = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")]
_RegistryKey = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$"),
]
_SemanticVersion = Annotated[
    str,
    Field(
        min_length=5,
        max_length=128,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    ),
]
_Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
_ExecutorService = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$"),
]


class AdlcObservationType(str, Enum):
    """Stable operation names exported by the initial ADLC observability seam."""

    PACKAGE_RESOLUTION_COMPLETED = "adlc.package_resolution.completed"
    PLAN_VALIDATION_COMPLETED = "adlc.plan_validation.completed"
    PLAN_MATERIALIZATION_COMPLETED = "adlc.plan_materialization.completed"
    TASK_DISPATCH_COMPLETED = "adlc.task_dispatch.completed"


class AdlcObservationOutcome(str, Enum):
    """Low-cardinality outcomes shared by every observed operation."""

    SUCCEEDED = "SUCCEEDED"
    INVALID = "INVALID"
    DENIED = "DENIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AdlcOperationObservation(BaseModel):
    """Allow-listed telemetry projection; request bodies and result content are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal["0.1"] = OBSERVABILITY_CONTRACT_VERSION
    observation_id: UUID = Field(default_factory=uuid4)
    event_type: AdlcObservationType
    outcome: AdlcObservationOutcome
    occurred_at: datetime = Field(default_factory=_utc_now)
    duration_ms: float = Field(ge=0)
    error_code: _StableCode | None = None

    workflow_definition_id: UUID | None = None
    workflow_definition_version: int | None = Field(default=None, ge=1)
    execution_plan_id: UUID | None = None
    workflow_run_id: UUID | None = None
    plan_task_id: UUID | None = None
    source_workflow_stage_id: UUID | None = None
    resolved_node_spec_id: UUID | None = None
    task_run_id: UUID | None = None
    attempt_id: UUID | None = None

    package_id: _RegistryKey | None = None
    package_version: _SemanticVersion | None = None
    package_content_digest: _Sha256Digest | None = None
    resolved_node_digest: _Sha256Digest | None = None
    executor_service: _ExecutorService | None = None

    task_count: int | None = Field(default=None, ge=0)
    resolved_node_count: int | None = Field(default=None, ge=0)
    validation_issue_count: int | None = Field(default=None, ge=0)
    validation_issue_codes: tuple[_StableCode, ...] = Field(default=(), max_length=64)
    artifact_count: int | None = Field(default=None, ge=0)
    attempt_number: int | None = Field(default=None, ge=1)
    idempotent_replay: bool | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            message = "occurred_at must include a timezone"
            raise ValueError(message)
        return value


@runtime_checkable
class AdlcObservabilitySink(Protocol):
    """Replaceable output port for operational observations."""

    def emit(self, observation: AdlcOperationObservation) -> None:
        """Export one completed-operation observation."""
        ...


class NoOpAdlcObservabilitySink:
    """Default for isolated services that have not been composed with telemetry."""

    def emit(self, observation: AdlcOperationObservation) -> None:  # noqa: ARG002
        return


class InMemoryAdlcObservabilitySink:
    """Thread-safe recorder used by unit tests and local adapter verification."""

    def __init__(self) -> None:
        self._observations: list[AdlcOperationObservation] = []
        self._lock = Lock()

    def emit(self, observation: AdlcOperationObservation) -> None:
        with self._lock:
            self._observations.append(observation.model_copy(deep=True))

    @property
    def observations(self) -> tuple[AdlcOperationObservation, ...]:
        with self._lock:
            return tuple(observation.model_copy(deep=True) for observation in self._observations)

    def clear(self) -> None:
        with self._lock:
            self._observations.clear()


class StructuredLogAdlcObservabilitySink:
    """Export allow-listed ADLC observations through Langflow's structured logger."""

    def emit(self, observation: AdlcOperationObservation) -> None:
        payload = observation.model_dump(mode="json", exclude_none=True)
        payload.pop("event_type", None)
        logger.info(observation.event_type.value, **payload)


NOOP_ADLC_OBSERVABILITY_SINK = NoOpAdlcObservabilitySink()


def elapsed_milliseconds(started_at_ns: int) -> float:
    """Return a monotonic elapsed duration suitable for an observation."""
    return max(0.0, round((perf_counter_ns() - started_at_ns) / 1_000_000, 3))


def observation_error_code(exc: object, fallback: str) -> str:
    """Use only stable machine codes; never project exception text into telemetry."""
    candidate = getattr(exc, "code", None)
    if isinstance(candidate, str) and _ERROR_CODE_PATTERN.fullmatch(candidate):
        return candidate
    return fallback


def observation_outcome_for_exception(exc: object) -> AdlcObservationOutcome:
    """Classify authorization failures without inspecting or exporting their messages."""
    code = getattr(exc, "code", None)
    if code in _DENIED_ERROR_CODES:
        return AdlcObservationOutcome.DENIED
    return AdlcObservationOutcome.FAILED


def emit_observation_safely(
    sink: AdlcObservabilitySink,
    observation: AdlcOperationObservation,
) -> None:
    """Keep a telemetry exporter failure from changing planning or execution behavior."""
    try:
        sink.emit(observation)
    except Exception:  # noqa: BLE001 - observability must never break the operation it observes
        _warn_observation_failure(
            observation.event_type,
            failure_stage="sink",
            observation_id=observation.observation_id,
        )


def record_observation_safely(
    sink: AdlcObservabilitySink,
    *,
    event_type: AdlcObservationType,
    outcome: AdlcObservationOutcome,
    duration_ms: float,
    **fields: object,
) -> None:
    """Validate and emit inside one failure-isolated observability boundary."""
    try:
        observation = AdlcOperationObservation.model_validate(
            {
                "event_type": event_type,
                "outcome": outcome,
                "duration_ms": duration_ms,
                **fields,
            }
        )
    except Exception:  # noqa: BLE001 - invalid telemetry must not alter the observed operation
        _warn_observation_failure(event_type, failure_stage="contract")
        return
    emit_observation_safely(sink, observation)


def _warn_observation_failure(
    event_type: AdlcObservationType,
    *,
    failure_stage: Literal["contract", "sink"],
    observation_id: UUID | None = None,
) -> None:
    with contextlib.suppress(Exception):
        logger.warning(
            "adlc.observability.emit_failed",
            failed_event_type=event_type.value,
            failure_stage=failure_stage,
            **({"observation_id": str(observation_id)} if observation_id is not None else {}),
        )

# ruff: noqa: INP001, S101

from typing import Any

import pytest
from pydantic import ValidationError

import langflow.adlc.observability as observability_module
from langflow.adlc.blueprints.errors import PACKAGE_NOT_VISIBLE, PackageAccessError
from langflow.adlc.observability import (
    AdlcObservationOutcome,
    AdlcObservationType,
    AdlcOperationObservation,
    InMemoryAdlcObservabilitySink,
    StructuredLogAdlcObservabilitySink,
    emit_observation_safely,
    observation_error_code,
    observation_outcome_for_exception,
    record_observation_safely,
)


class _FailingSink:
    def emit(self, observation: AdlcOperationObservation) -> None:  # noqa: ARG002
        message = "The telemetry exporter is unavailable."
        raise RuntimeError(message)


class _CapturingLogger:
    def __init__(self) -> None:
        self.event: str | None = None
        self.fields: dict[str, Any] = {}

    def info(self, event: str, **fields: Any) -> None:
        self.event = event
        self.fields = fields


def test_observation_contract_rejects_unlisted_payload_content() -> None:
    with pytest.raises(ValidationError):
        AdlcOperationObservation(
            event_type=AdlcObservationType.TASK_DISPATCH_COMPLETED,
            outcome=AdlcObservationOutcome.SUCCEEDED,
            duration_ms=1,
            task_input={"api_key": "must-not-be-exported"},
        )


def test_exporter_failure_does_not_escape_the_observability_boundary() -> None:
    observation = AdlcOperationObservation(
        event_type=AdlcObservationType.PLAN_VALIDATION_COMPLETED,
        outcome=AdlcObservationOutcome.SUCCEEDED,
        duration_ms=1,
    )

    emit_observation_safely(_FailingSink(), observation)


def test_invalid_observation_does_not_escape_the_observability_boundary() -> None:
    sink = InMemoryAdlcObservabilitySink()

    record_observation_safely(
        sink,
        event_type=AdlcObservationType.TASK_DISPATCH_COMPLETED,
        outcome=AdlcObservationOutcome.SUCCEEDED,
        duration_ms=1,
        executor_service="invalid author-provided value",
    )

    assert sink.observations == ()


def test_authorization_failure_uses_denied_outcome_without_exporting_message() -> None:
    failure = PackageAccessError(PACKAGE_NOT_VISIBLE, "Sensitive policy explanation")

    assert observation_outcome_for_exception(failure) is AdlcObservationOutcome.DENIED
    assert observation_error_code(failure, "FALLBACK") == PACKAGE_NOT_VISIBLE


def test_structured_sink_uses_the_event_name_and_allow_listed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    capturing_logger = _CapturingLogger()
    monkeypatch.setattr(observability_module, "logger", capturing_logger)
    observation = AdlcOperationObservation(
        event_type=AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED,
        outcome=AdlcObservationOutcome.SUCCEEDED,
        duration_ms=1,
        package_id="coding-agent",
        package_version="0.1.0",
    )

    StructuredLogAdlcObservabilitySink().emit(observation)

    assert capturing_logger.event == AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED.value
    assert capturing_logger.fields["outcome"] == AdlcObservationOutcome.SUCCEEDED.value
    assert capturing_logger.fields["package_id"] == "coding-agent"
    assert "event_type" not in capturing_logger.fields

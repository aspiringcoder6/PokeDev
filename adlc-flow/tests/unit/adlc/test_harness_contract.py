# ruff: noqa: INP001, S101

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from langflow.adlc.harness_models import (
    HarnessArtifactRead,
    HarnessCallbackReceipt,
    HarnessInteractionReceipt,
    HarnessInteractionResponse,
    HarnessPluginInventory,
    HarnessReconciliationReport,
    HarnessResultDelivery,
    HarnessRunResultProjection,
    HarnessRunSessionProjection,
    HarnessSessionAccepted,
    HarnessSessionEvent,
    HarnessSessionRead,
    HarnessSessionRequest,
    HarnessSessionResult,
    HarnessSubmissionReceipt,
    HarnessVerificationReport,
    TaskAttemptRecord,
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _contract_root() -> Path:
    return _repository_root() / "adlc-contracts" / "harness" / "v0.1"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


MODELS = (
    ("artifact-read.schema.json", HarnessArtifactRead),
    ("session-request.schema.json", HarnessSessionRequest),
    ("session-event.schema.json", HarnessSessionEvent),
    ("session-read.schema.json", HarnessSessionRead),
    ("session-accepted.schema.json", HarnessSessionAccepted),
    ("interaction-response.schema.json", HarnessInteractionResponse),
    ("interaction-receipt.schema.json", HarnessInteractionReceipt),
    ("plugin-inventory.schema.json", HarnessPluginInventory),
    ("submission-receipt.schema.json", HarnessSubmissionReceipt),
    ("verification-report.schema.json", HarnessVerificationReport),
    ("session-result.schema.json", HarnessSessionResult),
    ("result-delivery.schema.json", HarnessResultDelivery),
    ("callback-receipt.schema.json", HarnessCallbackReceipt),
    ("task-attempt.schema.json", TaskAttemptRecord),
    ("run-session-projection.schema.json", HarnessRunSessionProjection),
    ("run-result-projection.schema.json", HarnessRunResultProjection),
    ("reconciliation-report.schema.json", HarnessReconciliationReport),
)


@pytest.mark.parametrize(("schema_name", "model"), MODELS)
def test_generated_harness_schema_is_in_sync_with_runtime_model(schema_name, model) -> None:
    expected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://adlc.dev/contracts/harness/v0.1/{schema_name}",
        **model.model_json_schema(mode="validation"),
    }

    assert _load_json(_contract_root() / schema_name) == expected


@pytest.mark.parametrize(
    ("schema_name", "example_name", "model"),
    [
        ("session-request.schema.json", "session-request.json", HarnessSessionRequest),
        ("session-event.schema.json", "session-event.json", HarnessSessionEvent),
        ("verification-report.schema.json", "verification-report.json", HarnessVerificationReport),
        ("session-result.schema.json", "session-result.json", HarnessSessionResult),
        ("result-delivery.schema.json", "result-delivery.json", HarnessResultDelivery),
    ],
)
def test_harness_examples_match_json_schema_and_runtime_model(schema_name, example_name, model) -> None:
    schema = _load_json(_contract_root() / schema_name)
    example = _load_json(_contract_root() / "examples" / example_name)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    model.model_validate(example)


def test_state_machine_keeps_interaction_delivery_and_attempt_lifecycles_separate() -> None:
    machines = _load_json(_contract_root() / "state-machines.json")["machines"]

    assert set(machines) == {"harness_session", "result_delivery", "interaction", "task_attempt"}
    assert machines["interaction"]["initial"] == "PENDING"
    assert machines["result_delivery"]["terminal"] == ["DELIVERED", "DEAD_LETTER"]
    assert "RESULT_RECEIVED" in machines["task_attempt"]["transitions"]

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from langflow.adlc.command_models import (
    ArtifactReference,
    CommandExecutionRequest,
    CommandExecutionResponse,
    CommandExecutionStatus,
    ExecutionLogEntry,
)


def _repository_root() -> Path:
    return Path(__file__).parents[4]


def _contract_root() -> Path:
    return _repository_root() / "adlc-contracts" / "v0.1"


def _schema() -> dict:
    return json.loads((_contract_root() / "execution-contract.schema.json").read_text(encoding="utf-8"))


def _validator(definition: str) -> Draft202012Validator:
    schema = _schema()
    wrapped = {
        "$schema": schema["$schema"],
        "$ref": f"#/$defs/{definition}",
        "$defs": schema["$defs"],
    }
    return Draft202012Validator(wrapped, format_checker=FormatChecker())


def _example(name: str) -> dict:
    return json.loads((_contract_root() / "examples" / name).read_text(encoding="utf-8"))


def test_command_execution_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_schema())


def test_command_statuses_and_state_machine_match_the_combined_contract() -> None:
    machines = json.loads((_contract_root() / "state-machines.json").read_text(encoding="utf-8"))
    machine = machines["command_execution"]
    statuses = [status.value for status in CommandExecutionStatus]

    assert statuses == ["QUEUED", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"]
    assert machine["states"] == statuses
    assert machine["initial_state"] == "QUEUED"
    assert machine["terminal_states"] == ["SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"]
    assert machine["transitions"] == {
        "QUEUED": ["RUNNING", "FAILED", "TIMEOUT", "CANCELLED"],
        "RUNNING": ["SUCCESS", "FAILED", "TIMEOUT", "CANCELLED"],
        "SUCCESS": [],
        "FAILED": [],
        "TIMEOUT": [],
        "CANCELLED": [],
    }


@pytest.mark.parametrize(
    ("filename", "definition", "model"),
    [
        ("artifact-reference.json", "ArtifactReference", ArtifactReference),
        ("command-execution-request.json", "CommandExecutionRequest", CommandExecutionRequest),
        ("command-execution-success.json", "CommandExecutionResponse", CommandExecutionResponse),
        ("command-execution-timeout.json", "CommandExecutionResponse", CommandExecutionResponse),
        ("execution-log-entry.json", "ExecutionLogEntry", ExecutionLogEntry),
    ],
)
def test_examples_validate_against_json_schema_and_runtime_models(filename, definition: str, model) -> None:
    payload = _example(filename)

    _validator(definition).validate(payload)
    parsed = model.model_validate(payload)
    _validator(definition).validate(parsed.model_dump(mode="json"))


def test_success_response_rejects_nonzero_exit_code() -> None:
    payload = _example("command-execution-success.json")
    payload["exit_code"] = 1

    with pytest.raises(ValidationError, match="exit_code=0"):
        CommandExecutionResponse.model_validate(payload)
    assert list(_validator("CommandExecutionResponse").iter_errors(payload))


def test_timeout_response_requires_timeout_service_error() -> None:
    payload = _example("command-execution-timeout.json")
    payload["error"]["category"] = "EXECUTION"

    with pytest.raises(ValidationError, match="TIMEOUT ServiceError"):
        CommandExecutionResponse.model_validate(payload)
    assert list(_validator("CommandExecutionResponse").iter_errors(payload))


def test_request_rejects_shell_string_as_an_unknown_field() -> None:
    payload = _example("command-execution-request.json")
    payload["command"] = "python -m pytest"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CommandExecutionRequest.model_validate(payload)

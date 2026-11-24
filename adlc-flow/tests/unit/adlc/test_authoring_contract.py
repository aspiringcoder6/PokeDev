import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from langflow.adlc.blueprints import (
    ExecutionPlan,
    NodePackageDefinition,
    WorkflowDefinition,
    canonical_json_bytes,
    sha256_digest,
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _contract_root() -> Path:
    return _repository_root() / "adlc-contracts" / "workflow" / "v0.1"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("schema_name", "example_name", "model"),
    [
        ("node-package.schema.json", "node-package-coding-agent.json", NodePackageDefinition),
        ("node-package.schema.json", "node-package-approval.json", NodePackageDefinition),
        ("workflow-definition.schema.json", "workflow-definition.json", WorkflowDefinition),
        ("execution-plan.schema.json", "execution-plan.json", ExecutionPlan),
    ],
)
def test_authoring_examples_match_json_schema_and_runtime_model(schema_name, example_name, model) -> None:
    contract_root = _contract_root()
    schema = _load_json(contract_root / schema_name)
    example = _load_json(contract_root / "examples" / example_name)

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    model.model_validate(example)


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("node-package.schema.json", NodePackageDefinition),
        ("workflow-definition.schema.json", WorkflowDefinition),
        ("execution-plan.schema.json", ExecutionPlan),
    ],
)
def test_generated_schema_is_in_sync_with_runtime_model(schema_name, model) -> None:
    expected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://adlc.dev/contracts/workflow/v0.1/{schema_name}",
        **model.model_json_schema(mode="validation"),
    }

    assert _load_json(_contract_root() / schema_name) == expected


@pytest.mark.parametrize(
    ("example_name", "package_path"),
    [
        ("node-package-coding-agent.json", ("coding-agent", "0.1.0")),
        ("node-package-approval.json", ("approval", "0.1.0")),
    ],
)
def test_package_examples_equal_the_registered_package_source(example_name, package_path) -> None:
    repository_root = _repository_root()
    example = _load_json(_contract_root() / "examples" / example_name)
    registered = _load_json(
        repository_root / "adlc_components" / "packages" / package_path[0] / package_path[1] / "package.json"
    )

    assert example == registered


def test_closed_model_rejects_unknown_fields() -> None:
    payload = _load_json(_contract_root() / "examples" / "node-package-coding-agent.json")
    invalid = deepcopy(payload)
    invalid["unexpected"] = True

    with pytest.raises(ValidationError):
        NodePackageDefinition.model_validate(invalid)


def test_unsupported_authoring_contract_version_is_rejected() -> None:
    schema = _load_json(_contract_root() / "node-package.schema.json")
    payload = _load_json(_contract_root() / "examples" / "node-package-coding-agent.json")
    payload["schema_version"] = "0.2"

    assert not Draft202012Validator(schema).is_valid(payload)
    with pytest.raises(ValidationError):
        NodePackageDefinition.model_validate(payload)


def test_canonical_json_has_a_cross_platform_digest_vector() -> None:
    payload = {"z": [3, 2, 1], "a": {"β": True, "n": None}}

    assert canonical_json_bytes(payload) == b'{"a":{"n":null,"\xce\xb2":true},"z":[3,2,1]}'
    assert sha256_digest(payload) == "sha256:ca3e7e88e20e13795bf3a6f09ec9f2b3b6cf00c630266f53fe737485256713d5"
    assert sha256_digest({"a": {"n": None, "β": True}, "z": [3, 2, 1]}) == sha256_digest(payload)

# ruff: noqa: INP001, S101

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

EXPECTED_NEW_RUN_EDGES = {
    ("SUCCEEDED", "COMPENSATING"),
    ("FAILED", "COMPENSATING"),
    ("COMPENSATING", "COMPENSATED"),
    ("COMPENSATING", "FAILED"),
}
EXPECTED_NEW_TASK_EDGES = {
    ("SUCCEEDED", "COMPENSATING"),
    ("COMPENSATING", "COMPENSATED"),
    ("COMPENSATING", "FAILED"),
}


def _repository_root() -> Path:
    return Path(__file__).parents[4]


def _v01_root() -> Path:
    return _repository_root() / "adlc-contracts" / "v0.1"


def _v02_root() -> Path:
    return _repository_root() / "adlc-contracts" / "v0.2"


def _workflow_v01_root() -> Path:
    return _repository_root() / "adlc-contracts" / "workflow" / "v0.1"


def _workflow_v02_root() -> Path:
    return _repository_root() / "adlc-contracts" / "workflow" / "v0.2"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bundle_validator(root: Path, definition: str) -> Draft202012Validator:
    schema = _load(root / "execution-contract.schema.json")
    wrapped = {
        "$schema": schema["$schema"],
        "$ref": f"#/$defs/{definition}",
        "$defs": schema["$defs"],
    }
    return Draft202012Validator(wrapped, format_checker=FormatChecker())


def _plan_validator(root: Path) -> Draft202012Validator:
    schema = _load(root / "execution-plan.schema.json")
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _machines(version_root: Path) -> dict:
    return _load(version_root / "state-machines.json")


def _task_request(version: str = "0.2") -> dict:
    payload = _load(_v01_root() / "examples" / "task-request.json")
    payload["schema_version"] = version
    return payload


def _map_child_request() -> dict:
    payload = _task_request()
    payload["task_run_id"] = "22222222-2222-4222-8222-222222222203"
    payload["idempotency_key"] = "11111111:22222222:33333333:0"
    payload["purpose"] = "EXECUTION"
    payload["parent_task_run_id"] = "22222222-2222-4222-8222-222222222222"
    payload["map_index"] = 0
    payload["map_key"] = "acct-001"
    return payload


def _compensation_request() -> dict:
    payload = _task_request()
    payload["task_run_id"] = "22222222-2222-4222-8222-222222222209"
    payload["task_type"] = "coding.rollback"
    payload["idempotency_key"] = "11111111:22222222:33333333:compensate"
    payload["executor"] = {"service": "coding-agent", "operation": "rollback"}
    payload["constraints"] = {"timeout_ms": 300000, "priority": 50, "max_attempts": 1}
    payload["purpose"] = "COMPENSATION"
    payload["compensates_task_run_id"] = "22222222-2222-4222-8222-222222222222"
    return payload


def _v01_plan() -> dict:
    return _load(_workflow_v01_root() / "examples" / "execution-plan.json")


def _to_v02_plan(plan: dict) -> dict:
    upgraded = copy.deepcopy(plan)
    upgraded["schema_version"] = "0.2"
    upgraded["contract_version"] = "0.2"
    for spec in upgraded["resolved_node_specs"]:
        spec["schema_version"] = "0.2"
    return upgraded


def _map_plan() -> dict:
    plan = _to_v02_plan(_v01_plan())
    plan["tasks"][0]["control_flow"] = {
        "shape": "MAP",
        "collection_source": "{{run.input.accounts}}",
        "item_alias": "account",
        "max_fanout": 100,
        "join": {"kind": "ALL"},
        "failure_policy": "FAIL_FAST",
        "body": ["77777777-7777-4777-8777-777777777777"],
    }
    plan["tasks"][1]["compensation"] = {
        "task_type": "coding.rollback",
        "executor": {"service": "coding-agent", "operation": "rollback"},
        "input_template": "{{task.77777777-7777-4777-8777-777777777777.output.commit_sha}}",
        "timeout_ms": 300000,
        "max_attempts": 1,
    }
    return plan


def test_v02_state_machines_extend_v01_without_removals() -> None:
    v01 = _machines(_v01_root())
    v02 = _machines(_v02_root())

    assert set(v02) == set(v01)
    for machine_name in ("workflow_run", "task_run", "command_execution"):
        v01_machine = v01[machine_name]
        v02_machine = v02[machine_name]
        assert set(v01_machine["states"]) <= set(v02_machine["states"]), machine_name
        v01_edges = {
            (source, target)
            for source, targets in v01_machine["transitions"].items()
            for target in targets
        }
        v02_edges = {
            (source, target)
            for source, targets in v02_machine["transitions"].items()
            for target in targets
        }
        assert v01_edges <= v02_edges, machine_name
        assert v02_machine["initial_state"] == v01_machine["initial_state"], machine_name


def test_v02_adds_exactly_the_documented_new_edges() -> None:
    v01 = _machines(_v01_root())
    v02 = _machines(_v02_root())

    run_v01_edges = {
        (source, target)
        for source, targets in v01["workflow_run"]["transitions"].items()
        for target in targets
    }
    run_v02_edges = {
        (source, target)
        for source, targets in v02["workflow_run"]["transitions"].items()
        for target in targets
    }
    assert run_v02_edges - run_v01_edges == EXPECTED_NEW_RUN_EDGES

    task_v01_edges = {
        (source, target)
        for source, targets in v01["task_run"]["transitions"].items()
        for target in targets
    }
    task_v02_edges = {
        (source, target)
        for source, targets in v02["task_run"]["transitions"].items()
        for target in targets
    }
    assert task_v02_edges - task_v01_edges == EXPECTED_NEW_TASK_EDGES

    assert v02["command_execution"] == v01["command_execution"]
    assert v02["schema_version"] == "0.2"
    assert v02["workflow_run"]["terminal_states"] == ["CANCELLED", "COMPENSATED"]
    assert v02["task_run"]["terminal_states"] == ["CANCELLED", "SKIPPED", "COMPENSATED"]
    assert v02["task_run"]["reopenable_states"] == v01["task_run"]["reopenable_states"]
    for machine_name in ("workflow_run", "task_run", "command_execution"):
        machine = v02[machine_name]
        for terminal in machine["terminal_states"]:
            assert machine["transitions"][terminal] == [], (machine_name, terminal)


def test_v02_execution_contract_is_valid_draft_2020_12() -> None:
    schema = _load(_v02_root() / "execution-contract.schema.json")
    Draft202012Validator.check_schema(schema)
    plan_schema = _load(_workflow_v02_root() / "execution-plan.schema.json")
    Draft202012Validator.check_schema(plan_schema)


def test_map_child_task_request_validates() -> None:
    payload = _map_child_request()

    _bundle_validator(_v02_root(), "TaskRequest").validate(payload)


def test_compensation_task_request_validates() -> None:
    payload = _compensation_request()

    _bundle_validator(_v02_root(), "TaskRequest").validate(payload)


def test_task_request_still_rejects_unknown_fields() -> None:
    payload = _map_child_request()
    payload["tenant_id"] = "tenant-1"

    errors = list(_bundle_validator(_v02_root(), "TaskRequest").iter_errors(payload))
    assert errors
    assert any("tenant_id" in error.message for error in errors)


def test_v02_rejects_schema_version_0_3() -> None:
    payload = _map_child_request()
    payload["schema_version"] = "0.3"

    assert list(_bundle_validator(_v02_root(), "TaskRequest").iter_errors(payload))

    plan = _to_v02_plan(_v01_plan())
    plan["schema_version"] = "0.3"

    assert list(_plan_validator(_workflow_v02_root()).iter_errors(plan))


def test_v01_plan_schema_rejects_v02_control_flow_and_compensation() -> None:
    plan = _v01_plan()
    plan["tasks"][0]["control_flow"] = {
        "shape": "MAP",
        "collection_source": "{{run.input.accounts}}",
        "join": {"kind": "ALL"},
        "body": ["66666666-6666-4666-8666-666666666666"],
    }
    plan["tasks"][0]["compensation"] = {
        "task_type": "coding.rollback",
        "executor": {"service": "coding-agent", "operation": "rollback"},
        "input_template": "{{task.55555555-5555-4555-8555-555555555555.output.commit_sha}}",
    }

    errors = list(_plan_validator(_workflow_v01_root()).iter_errors(plan))
    assert errors
    assert any("control_flow" in error.message for error in errors)
    assert any("compensation" in error.message for error in errors)


def test_v02_plan_schema_accepts_control_flow_and_compensation() -> None:
    plan = _map_plan()

    _plan_validator(_workflow_v02_root()).validate(plan)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda flow: flow.update({"unexpected_field": True}),
        lambda flow: flow.update({"join": {"kind": "MAJORITY"}}),
        lambda flow: flow.update({"join": {"kind": "QUORUM"}}),
        lambda flow: flow.update({"failure_policy": "RETRY_ALL"}),
        lambda flow: flow.update({"shape": "FOREACH"}),
        lambda flow: flow.update({"body": []}),
    ],
)
def test_v02_plan_schema_rejects_invalid_map_control_flow(mutation) -> None:
    plan = _map_plan()
    mutation(plan["tasks"][0]["control_flow"])

    assert list(_plan_validator(_workflow_v02_root()).iter_errors(plan))


def test_v02_plan_schema_rejects_retryable_compensation() -> None:
    plan = _map_plan()
    plan["tasks"][1]["compensation"]["max_attempts"] = 2

    assert list(_plan_validator(_workflow_v02_root()).iter_errors(plan))


@pytest.mark.parametrize(
    ("filename", "definition"),
    [
        ("task-request-map-child.json", "TaskRequest"),
        ("task-request-compensation.json", "TaskRequest"),
        ("run-event-map-expanded.json", "RunEvent"),
        ("run-event-compensating.json", "RunEvent"),
    ],
)
def test_v02_examples_validate(filename: str, definition: str) -> None:
    payload = _load(_v02_root() / "examples" / filename)

    _bundle_validator(_v02_root(), definition).validate(payload)


def test_v02_plan_example_validates() -> None:
    plan = _load(_workflow_v02_root() / "examples" / "execution-plan.json")

    _plan_validator(_workflow_v02_root()).validate(plan)

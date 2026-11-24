# ruff: noqa: INP001, S101, S106, S108, PLR2004, SLF001

"""Unit tests for the DSH Task Loop SDK."""

from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from typing import Any
from uuid import UUID

import pytest

from langflow.adlc.sdk.dsh_task_loop_sdk import (
    DEFAULT_CONTEXT_BUDGET_CHARS,
    DEFAULT_MAX_DURATION_MS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_STALLED_ITERATIONS,
    DEFAULT_MAX_TOTAL_COST,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_VERIFIER_REF,
    DSHTaskLoopCommand,
    DSHTaskLoopCriterion,
    DSHTaskLoopIncompleteSpecError,
    DSHTaskLoopSDK,
    DSHTaskLoopSpec,
    DSHTaskLoopSpecError,
    LoopExitReason,
    SCHEMA_REF,
    SCHEMA_VERSION,
)


# ---- Fixtures -------------------------------------------------------------


def _valid_spec(**overrides: Any) -> DSHTaskLoopSpec:
    """Build a valid spec; pass overrides to tweak individual fields."""
    defaults: dict[str, Any] = {
        "specification": "Implement add(a, b) and document it in README.md.",
        "base_commit": "a" * 40,
        "writable_paths": ("math_utils.py", "README.md"),
        "acceptance_criteria": (
            DSHTaskLoopCriterion(
                criterion_id="addition",
                description="add(a, b) returns a + b",
                check_refs=("acceptance",),
            ),
        ),
        "verification_commands": (
            DSHTaskLoopCommand(
                check_id="acceptance",
                test_path="test_acceptance.py",
            ),
        ),
    }
    defaults.update(overrides)
    return DSHTaskLoopSpec(**defaults)


def _make_invalid_spec(**overrides: Any) -> DSHTaskLoopSpec:
    """Build a spec bypassing __post_init__ validation (for negative tests)."""
    valid = _valid_spec()
    spec = object.__new__(DSHTaskLoopSpec)
    for f in dc_fields(DSHTaskLoopSpec):
        object.__setattr__(spec, f.name, getattr(valid, f.name))
    for key, value in overrides.items():
        object.__setattr__(spec, key, value)
    return spec


# ---- Criterion validation -------------------------------------------------


def test_criterion_rejects_invalid_id() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="criterion_id"):
        DSHTaskLoopCriterion(
            criterion_id="Invalid-ID",
            description="desc",
            check_refs=("a",),
        )


def test_criterion_rejects_empty_description() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="description"):
        DSHTaskLoopCriterion(
            criterion_id="ok",
            description="",
            check_refs=("a",),
        )


def test_criterion_rejects_too_many_check_refs() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="check_refs"):
        DSHTaskLoopCriterion(
            criterion_id="ok",
            description="desc",
            check_refs=tuple(f"r{i}" for i in range(20)),
        )


def test_criterion_to_dict_roundtrip() -> None:
    c = DSHTaskLoopCriterion(
        criterion_id="addition",
        description="add returns a + b",
        check_refs=("acceptance", "unit"),
    )
    d = c.to_dict()
    assert d == {
        "criterion_id": "addition",
        "description": "add returns a + b",
        "check_refs": ["acceptance", "unit"],
    }


# ---- Command validation ---------------------------------------------------


def test_command_rejects_invalid_check_id() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="check_id"):
        DSHTaskLoopCommand(check_id="Bad-ID", test_path="t.py")


def test_command_rejects_non_default_verifier() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="verifier_ref"):
        DSHTaskLoopCommand(
            check_id="ok",
            test_path="t.py",
            verifier_ref="verifier:shell/1.0",
        )


def test_command_rejects_timeout_out_of_bounds() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="timeout_ms"):
        DSHTaskLoopCommand(check_id="ok", test_path="t.py", timeout_ms=10)


def test_command_to_dict_roundtrip() -> None:
    c = DSHTaskLoopCommand(check_id="acceptance", test_path="t.py", timeout_ms=5000)
    d = c.to_dict()
    assert d == {
        "check_id": "acceptance",
        "verifier_ref": DEFAULT_VERIFIER_REF,
        "test_path": "t.py",
        "timeout_ms": 5000,
    }


# ---- Spec validation ------------------------------------------------------


def test_spec_rejects_missing_specification() -> None:
    with pytest.raises(DSHTaskLoopSpecError) as exc_info:
        DSHTaskLoopSpec(
            specification="",
            base_commit="a" * 40,
            writable_paths=("x.py",),
            acceptance_criteria=(
                DSHTaskLoopCriterion(criterion_id="c", description="d", check_refs=("k",)),
            ),
            verification_commands=(
                DSHTaskLoopCommand(check_id="k", test_path="t.py"),
            ),
        )
    assert any("specification" in f for f in exc_info.value.missing_fields)


def test_spec_rejects_invalid_base_commit() -> None:
    with pytest.raises(DSHTaskLoopSpecError) as exc_info:
        DSHTaskLoopSpec(
            specification="valid spec",
            base_commit="not-a-commit",
            writable_paths=("x.py",),
            acceptance_criteria=(
                DSHTaskLoopCriterion(criterion_id="c", description="d", check_refs=("k",)),
            ),
            verification_commands=(
                DSHTaskLoopCommand(check_id="k", test_path="t.py"),
            ),
        )
    assert any("base_commit" in f for f in exc_info.value.missing_fields)


def test_spec_rejects_empty_writable_paths() -> None:
    with pytest.raises(DSHTaskLoopSpecError) as exc_info:
        DSHTaskLoopSpec(
            specification="valid spec",
            base_commit="a" * 40,
            writable_paths=(),
            acceptance_criteria=(
                DSHTaskLoopCriterion(criterion_id="c", description="d", check_refs=("k",)),
            ),
            verification_commands=(
                DSHTaskLoopCommand(check_id="k", test_path="t.py"),
            ),
        )
    assert any("writable_paths" in f for f in exc_info.value.missing_fields)


def test_spec_rejects_empty_acceptance_criteria() -> None:
    with pytest.raises(DSHTaskLoopSpecError) as exc_info:
        DSHTaskLoopSpec(
            specification="valid spec",
            base_commit="a" * 40,
            writable_paths=("x.py",),
            acceptance_criteria=(),
            verification_commands=(
                DSHTaskLoopCommand(check_id="k", test_path="t.py"),
            ),
        )
    assert any("acceptance_criteria" in f for f in exc_info.value.missing_fields)


def test_spec_rejects_empty_verification_commands() -> None:
    with pytest.raises(DSHTaskLoopSpecError) as exc_info:
        DSHTaskLoopSpec(
            specification="valid spec",
            base_commit="a" * 40,
            writable_paths=("x.py",),
            acceptance_criteria=(
                DSHTaskLoopCriterion(criterion_id="c", description="d", check_refs=("k",)),
            ),
            verification_commands=(),
        )
    assert any("verification_commands" in f for f in exc_info.value.missing_fields)


def test_spec_rejects_unknown_check_ref() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="unknown check_id"):
        _valid_spec(
            acceptance_criteria=(
                DSHTaskLoopCriterion(
                    criterion_id="c",
                    description="d",
                    check_refs=("nonexistent",),
                ),
            ),
        )


def test_spec_rejects_max_iterations_out_of_bounds() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="max_iterations"):
        _valid_spec(max_iterations=0)


def test_spec_rejects_negative_max_total_cost() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="max_total_cost"):
        _valid_spec(max_total_cost=-1.0)


def test_spec_accepts_null_max_total_cost() -> None:
    spec = _valid_spec(max_total_cost=None)
    assert spec.max_total_cost is None


def test_spec_defaults_are_sensible() -> None:
    spec = _valid_spec()
    assert spec.loop_until_pass is True  # UI checkbox default
    assert spec.max_iterations == DEFAULT_MAX_ITERATIONS
    assert spec.max_stalled_iterations == DEFAULT_MAX_STALLED_ITERATIONS
    assert spec.context_budget_chars == DEFAULT_CONTEXT_BUDGET_CHARS
    assert spec.max_duration_ms == DEFAULT_MAX_DURATION_MS
    assert spec.max_total_tokens == DEFAULT_MAX_TOTAL_TOKENS
    assert spec.max_total_cost == DEFAULT_MAX_TOTAL_COST
    assert spec.revision == 1
    assert isinstance(spec.spec_id, UUID)


def test_spec_loop_until_pass_can_be_disabled() -> None:
    spec = _valid_spec(loop_until_pass=False)
    assert spec.loop_until_pass is False


def test_spec_rejects_non_bool_loop_until_pass() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="loop_until_pass"):
        _valid_spec(loop_until_pass="yes")  # type: ignore[arg-type]


def test_spec_with_overrides_returns_new_instance() -> None:
    spec = _valid_spec()
    spec2 = spec.with_overrides(max_iterations=5, loop_until_pass=False)
    assert spec.max_iterations == DEFAULT_MAX_ITERATIONS
    assert spec.loop_until_pass is True
    assert spec2.max_iterations == 5
    assert spec2.loop_until_pass is False


# ---- Serialization --------------------------------------------------------


def test_spec_to_dict_has_schema_version() -> None:
    spec = _valid_spec()
    d = spec.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["spec_id"] == str(spec.spec_id)
    assert d["revision"] == 1
    assert d["loop_until_pass"] is True
    assert d["specification"] == spec.specification
    assert d["base_commit"] == spec.base_commit
    assert d["writable_paths"] == ["math_utils.py", "README.md"]
    assert len(d["acceptance_criteria"]) == 1
    assert len(d["verification_commands"]) == 1


def test_spec_to_dict_omits_null_optional_budgets() -> None:
    spec = _valid_spec(max_total_tokens=None, max_total_cost=None)
    d = spec.to_dict()
    assert "max_total_tokens" not in d
    assert "max_total_cost" not in d


def test_spec_to_json_is_valid_json() -> None:
    spec = _valid_spec()
    text = spec.to_json()
    parsed = json.loads(text)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_spec_from_dict_roundtrip() -> None:
    spec = _valid_spec()
    d = spec.to_dict()
    spec2 = DSHTaskLoopSpec.from_dict(d)
    assert spec2.specification == spec.specification
    assert spec2.base_commit == spec.base_commit
    assert spec2.writable_paths == spec.writable_paths
    assert spec2.spec_id == spec.spec_id
    assert spec2.loop_until_pass == spec.loop_until_pass


def test_spec_from_dict_raises_on_missing_field() -> None:
    with pytest.raises(DSHTaskLoopSpecError, match="missing required field"):
        DSHTaskLoopSpec.from_dict({"specification": "x"})


# ---- SDK validation helpers -----------------------------------------------


def test_sdk_missing_fields_returns_empty_for_valid_spec() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    spec = _valid_spec()
    assert sdk.missing_fields(spec) == []


def test_sdk_missing_fields_lists_each_missing_field() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    spec_no_spec = _make_invalid_spec(specification="")
    spec_no_commit = _make_invalid_spec(base_commit="bad")
    spec_no_paths = _make_invalid_spec(writable_paths=())
    spec_no_criteria = _make_invalid_spec(acceptance_criteria=())
    spec_no_commands = _make_invalid_spec(verification_commands=())

    assert "specification" in sdk.missing_fields(spec_no_spec)
    assert "base_commit" in sdk.missing_fields(spec_no_commit)
    assert "writable_paths" in sdk.missing_fields(spec_no_paths)
    assert "acceptance_criteria" in sdk.missing_fields(spec_no_criteria)
    assert "verification_commands" in sdk.missing_fields(spec_no_commands)


def test_sdk_validate_passes_for_valid_spec() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    sdk.validate(_valid_spec())  # should not raise


# ---- Schema reference constants -------------------------------------------


def test_schema_ref_is_v0_2() -> None:
    assert SCHEMA_REF == "adlc://schemas/task-loop-spec/0.2"
    assert SCHEMA_VERSION == "0.2"


def test_default_verifier_is_python_unittest() -> None:
    assert DEFAULT_VERIFIER_REF == "verifier:python-unittest/0.1.0"


def test_default_max_iterations_is_high_enough_to_loop_until_pass() -> None:
    """The default max_iterations should be high enough that DSH can
    loop until acceptance criteria pass (not capped at 3)."""
    assert DEFAULT_MAX_ITERATIONS >= 10


# ---- Loop exit reasons ----------------------------------------------------


def test_loop_exit_reason_values() -> None:
    assert LoopExitReason.ALL_CRITERIA_PASSED.value == "all_criteria_passed"
    assert LoopExitReason.MAX_ITERATIONS_REACHED.value == "max_iterations_reached"
    assert LoopExitReason.MAX_STALLED_REACHED.value == "max_stalled_reached"
    assert LoopExitReason.MAX_DURATION_REACHED.value == "max_duration_reached"
    assert LoopExitReason.MAX_TOKENS_REACHED.value == "max_tokens_reached"
    assert LoopExitReason.MAX_COST_REACHED.value == "max_cost_reached"
    assert LoopExitReason.SESSION_FAILED.value == "session_failed"
    assert LoopExitReason.CANCELLED.value == "cancelled"


# ---- Incomplete spec error ------------------------------------------------


def test_incomplete_spec_error_carries_requested_fields() -> None:
    err = DSHTaskLoopIncompleteSpecError(
        "DSH agent needs more info",
        requested_fields=["base_commit", "writable_paths"],
    )
    assert err.requested_fields == ["base_commit", "writable_paths"]
    assert "base_commit" in err.missing_fields
    assert "writable_paths" in err.missing_fields


# ---- Prompt composition ---------------------------------------------------


def test_prompt_includes_loop_instruction_when_enabled() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    spec = _valid_spec(loop_until_pass=True)
    prompt = sdk._compose_prompt(spec, spec.to_dict())  # noqa: SLF001
    assert "Loop until pass (UI checkbox: ON)" in prompt
    assert f"Maximum iterations: {spec.max_iterations}" in prompt


def test_prompt_omits_loop_instruction_when_disabled() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    spec = _valid_spec(loop_until_pass=False)
    prompt = sdk._compose_prompt(spec, spec.to_dict())  # noqa: SLF001
    assert "Loop until pass (UI checkbox: OFF)" in prompt
    assert "Run the verification commands ONCE" in prompt


def test_prompt_includes_all_required_fields() -> None:
    sdk = DSHTaskLoopSDK(client=None)  # type: ignore[arg-type]
    spec = _valid_spec()
    prompt = sdk._compose_prompt(spec, spec.to_dict())  # noqa: SLF001
    assert spec.specification in prompt
    assert "math_utils.py" in prompt
    assert "README.md" in prompt
    assert "addition" in prompt
    assert "test_acceptance.py" in prompt


# ---- Exit reason parsing --------------------------------------------------


def test_parse_exit_reason_all_criteria_passed() -> None:
    text = "ALL_CRITERIA_PASSED: addition, docs"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.ALL_CRITERIA_PASSED


def test_parse_exit_reason_all_criteria_passed_at_end() -> None:
    """The agent may put the marker at the end of the message."""
    text = (
        "Both files are correctly implemented.\n"
        "ALL_CRITERIA_PASSED\n"
        "- greet_function_exists\n"
        "- greet_test_passes\n"
    )
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.ALL_CRITERIA_PASSED


def test_parse_exit_reason_criteria_failed() -> None:
    text = "CRITERIA_FAILED: addition"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.MAX_ITERATIONS_REACHED


def test_parse_exit_reason_max_iterations() -> None:
    text = "EXIT_REASON: MAX_ITERATIONS_REACHED"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.MAX_ITERATIONS_REACHED


def test_parse_exit_reason_timeout() -> None:
    text = "some text"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": True})  # noqa: SLF001
    assert reason is LoopExitReason.MAX_DURATION_REACHED


def test_parse_exit_reason_unknown() -> None:
    text = "some text"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.SESSION_FAILED


def test_parse_exit_reason_does_not_match_substring() -> None:
    """The marker must be a whole word, not a substring."""
    text = "NOT_ALL_CRITERIA_PASSED_HERE"
    reason = DSHTaskLoopSDK._parse_exit_reason(text, {"timeout": False})  # noqa: SLF001
    assert reason is LoopExitReason.SESSION_FAILED


def test_parse_iteration_count() -> None:
    text = "Completed 5 iterations"
    count = DSHTaskLoopSDK._parse_iteration_count(text)  # noqa: SLF001
    assert count == 5


def test_parse_iteration_count_default() -> None:
    text = "no count here"
    count = DSHTaskLoopSDK._parse_iteration_count(text)  # noqa: SLF001
    assert count == 1

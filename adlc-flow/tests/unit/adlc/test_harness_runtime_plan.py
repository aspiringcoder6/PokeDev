# ruff: noqa: INP001, S101, S105, S106

"""Unit tests for plan-orchestration env helpers in :mod:`langflow.adlc.harness_runtime`."""

from __future__ import annotations

import pytest

from langflow.adlc.harness_runtime import (
    HARNESS_MAX_PARALLEL_SUBTASKS_ENV,
    HARNESS_PLAN_ORCHESTRATION_ENV,
    harness_max_parallel_subtasks_from_environment,
    harness_plan_orchestration_enabled,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the relevant env vars before each test."""
    monkeypatch.delenv(HARNESS_PLAN_ORCHESTRATION_ENV, raising=False)
    monkeypatch.delenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, raising=False)


def test_plan_orchestration_defaults_to_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HARNESS_PLAN_ORCHESTRATION_ENV, raising=False)
    assert harness_plan_orchestration_enabled() is True


def test_plan_orchestration_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HARNESS_PLAN_ORCHESTRATION_ENV, "false")
    assert harness_plan_orchestration_enabled() is False


def test_plan_orchestration_accepts_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "yes", "on", "TRUE", "Yes"):
        monkeypatch.setenv(HARNESS_PLAN_ORCHESTRATION_ENV, value)
        assert harness_plan_orchestration_enabled() is True, f"Failed for {value!r}"


def test_plan_orchestration_accepts_falsy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("0", "false", "no", "off", "FALSE"):
        monkeypatch.setenv(HARNESS_PLAN_ORCHESTRATION_ENV, value)
        assert harness_plan_orchestration_enabled() is False, f"Failed for {value!r}"


def test_max_parallel_defaults_to_five(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, raising=False)
    assert harness_max_parallel_subtasks_from_environment() == 5


def test_max_parallel_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, "10")
    assert harness_max_parallel_subtasks_from_environment() == 10


def test_max_parallel_falls_back_on_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, "not-a-number")
    assert harness_max_parallel_subtasks_from_environment() == 5


def test_max_parallel_clamps_to_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, "0")
    assert harness_max_parallel_subtasks_from_environment() == 1
    monkeypatch.setenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, "-5")
    assert harness_max_parallel_subtasks_from_environment() == 1

# ruff: noqa: INP001, S101, S106

"""Unit tests for :mod:`langflow.adlc.plan_prompt`."""

from __future__ import annotations

from langflow.adlc.plan_prompt import (
    PLAN_GENERATION_PROMPT,
    render_plan_prompt,
)


def test_render_plan_prompt_includes_request() -> None:
    prompt = render_plan_prompt("Build a REST API for todos")
    assert "Build a REST API for todos" in prompt


def test_render_plan_prompt_strips_request_whitespace() -> None:
    prompt = render_plan_prompt("  Build a thing  \n")
    assert "Build a thing" in prompt
    assert "  Build a thing  " not in prompt


def test_prompt_contains_schema_documentation() -> None:
    assert "schema_version" in PLAN_GENERATION_PROMPT
    assert "subtasks" in PLAN_GENERATION_PROMPT
    assert "dependencies" in PLAN_GENERATION_PROMPT
    assert "trigger" in PLAN_GENERATION_PROMPT


def test_prompt_documents_all_triggers() -> None:
    assert "on_success" in PLAN_GENERATION_PROMPT
    assert "on_failure" in PLAN_GENERATION_PROMPT
    assert "on_completed" in PLAN_GENERATION_PROMPT


def test_prompt_documents_granularity_rules() -> None:
    assert "2-15 minutes" in PLAN_GENERATION_PROMPT
    assert "1 and 10" in PLAN_GENERATION_PROMPT


def test_prompt_requires_acyclic_graph() -> None:
    assert "acyclic" in PLAN_GENERATION_PROMPT


def test_prompt_forbids_secrets() -> None:
    assert "secrets" in PLAN_GENERATION_PROMPT.lower()

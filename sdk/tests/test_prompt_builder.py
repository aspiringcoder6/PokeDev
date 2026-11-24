"""Tests for the DshPrompt builder (common prompt standard)."""

from __future__ import annotations

import json

from dsh_web_sdk.prompt_builder import (
    Catalogue,
    DshPrompt,
    FileSpec,
    PromptContext,
    ReplyContract,
    load_prompt_schema,
)


def test_load_prompt_schema_returns_canonical_document() -> None:
    schema = load_prompt_schema()
    assert schema["title"] == "DSH Prompt Structure"
    assert "role" in schema["required"]
    assert "objective" in schema["required"]
    assert "reply_contract" in schema["required"]


def test_dshprompt_to_dict_matches_schema_shape() -> None:
    prompt = DshPrompt(
        role="ADLC blueprint planner",
        objective="Build a todo app.",
        reply_contract=ReplyContract(
            format="adlc-file-block",
            summary_required=True,
            files=[FileSpec(path="blueprint.json", format="json")],
        ),
    )
    payload = prompt.to_dict()
    assert payload["role"] == "ADLC blueprint planner"
    assert payload["objective"] == "Build a todo app."
    assert payload["reply_contract"]["format"] == "adlc-file-block"
    assert payload["reply_contract"]["files"][0]["path"] == "blueprint.json"


def test_dshprompt_render_includes_objective_and_file_block() -> None:
    prompt = DshPrompt(
        role="ADLC blueprint planner",
        objective="Build a todo app.",
        reply_contract=ReplyContract(
            format="adlc-file-block",
            summary_required=True,
            files=[FileSpec(path="blueprint.json", format="json")],
        ),
    )
    rendered = prompt.render()
    assert "You are ADLC blueprint planner." in rendered
    assert "# Objective" in rendered
    assert "Build a todo app." in rendered
    assert '<adlc:file path="blueprint.json">' in rendered
    assert "</adlc:file>" in rendered


def test_dshprompt_render_includes_catalogues_and_constraints() -> None:
    prompt = DshPrompt(
        role="ADLC reviewer",
        objective="Review the patch.",
        reply_contract=ReplyContract(format="json-only"),
        context=PromptContext(
            catalogues=[
                Catalogue(
                    catalogue_id="node-packages",
                    items=[{"package_id": "coding-agent", "version": "0.1.0"}],
                )
            ],
            constraints={"max_files": 10},
        ),
    )
    rendered = prompt.render()
    assert "# Catalogue: node-packages" in rendered
    assert "coding-agent" in rendered
    assert "# Constraints" in rendered
    assert "max_files" in rendered


def test_dshprompt_render_omits_optional_sections_when_empty() -> None:
    prompt = DshPrompt(
        role="ADLC planner",
        objective="Build something.",
        reply_contract=ReplyContract(format="free-text"),
    )
    rendered = prompt.render()
    assert "# Extra instructions" not in rendered
    assert "# Current state" not in rendered
    assert "# Catalogue" not in rendered
    assert "# Constraints" not in rendered


def test_dshprompt_render_includes_rules() -> None:
    prompt = DshPrompt(
        role="ADLC planner",
        objective="Build something.",
        reply_contract=ReplyContract(
            format="adlc-file-block",
            files=[FileSpec(path="blueprint.json", format="json")],
            rules=["Use only package_id@version pairs from the catalogue."],
        ),
    )
    rendered = prompt.render()
    assert "Rules:" in rendered
    assert "Use only package_id@version pairs from the catalogue." in rendered


def test_dshprompt_to_dict_is_json_serializable() -> None:
    prompt = DshPrompt(
        role="ADLC planner",
        objective="Build something.",
        reply_contract=ReplyContract(
            format="adlc-file-block",
            files=[FileSpec(path="blueprint.json", format="json")],
        ),
        context=PromptContext(
            catalogues=[Catalogue(catalogue_id="node-packages", items=[{"id": "x"}])],
        ),
    )
    # Must be JSON-serializable so callers can log/inspect the payload.
    json.dumps(prompt.to_dict())

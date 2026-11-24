# ruff: noqa: INP001, PLR2004, S101, S106

"""Unit tests for the DSH-backed blueprint generator."""

from __future__ import annotations

import builtins
import json
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from langflow.adlc.blueprint_generator import (
    BLUEPRINT_FILE_PATH,
    BlueprintGenerationError,
    BlueprintGenerationSettings,
    applied_stages_summary,
    apply_blueprint_to_flow_data,
    current_stages_projection,
    extract_blueprint_file,
    generate_blueprint_document,
    render_blueprint_prompt,
)
from langflow.adlc.packages import create_default_package_registry

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import NodePackageDefinition


def _packages() -> list[NodePackageDefinition]:
    registry = create_default_package_registry()
    return [
        registered.definition
        for registered in registry.list_packages()
        if registered.definition.package_id in {"coding-agent", "approval"}
    ]


def _blueprint_document() -> dict[str, Any]:
    return {
        "name": "Todo frontend",
        "stages": [
            {
                "key": "implement",
                "name": "Implement todo UI",
                "objective": "Build the todo list page.",
                "package_id": "coding-agent",
                "version": "0.2.1",
                "inputs": {"requirement": "Todo list with add and complete."},
                "configuration_overrides": {"delay_ms": 10},
            },
            {
                "key": "approve",
                "name": "Approve",
                "objective": "Approve the implementation.",
                "package_id": "approval",
                "version": "0.1.0",
            },
        ],
        "edges": [
            {
                "from": "implement",
                "to": "approve",
                "bindings": [{"source_output": "source_patch", "target_input": "approval_context"}],
            }
        ],
    }


def _final_text(document: dict[str, Any] | str, *, summary: str = "Blueprint ready.") -> str:
    body = document if isinstance(document, str) else json.dumps(document, indent=2)
    return f'{summary}\n\n<adlc:file path="{BLUEPRINT_FILE_PATH}">\n{body}\n</adlc:file>\n'


@dataclass
class _FakeRunState:
    final_text: str | None = None
    timeout: bool = False
    error: Exception | None = None


@dataclass
class _FakeDshSession:
    state: _FakeRunState
    session_id: str
    prompts: list[str] = field(default_factory=list)

    async def prompt(self, text: str) -> bool:
        self.prompts.append(text)
        if self.state.error is not None:
            raise self.state.error
        return True

    async def wait(self, *, timeout_s: float, poll_s: float, idle_s: float) -> dict[str, Any]:
        assert timeout_s > 0
        assert poll_s > 0
        assert idle_s >= 0
        return {"finished": not self.state.timeout, "final_text": self.state.final_text, "timeout": self.state.timeout}


class _FakeDshClient:
    def __init__(self, state: _FakeRunState) -> None:
        self.state = state
        self.created: list[_FakeDshSession] = []
        self.routes: list[dict] = []

    async def rpc(self, method: str, args: dict):
        assert method == "session/selectModel"
        self.routes.append(args["request"])
        return {"selected": {key: args["request"][key] for key in ("provider", "model")}}

    async def __aenter__(self) -> _FakeDshClient:  # noqa: PYI034 - test double
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def create_session(self, **_kwargs) -> _FakeDshSession:
        session = _FakeDshSession(self.state, "fx-blueprint-1")
        self.created.append(session)
        return session


def _settings() -> BlueprintGenerationSettings:
    return BlueprintGenerationSettings(
        base_url="http://127.0.0.1:3080",
        api_token="dsh-token",
        generation_timeout_seconds=60.0,
    )


def test_render_prompt_carries_requirement_packages_and_reply_contract() -> None:
    packages = _packages()
    prompt = render_blueprint_prompt(
        "Build a todo app.",
        packages,
        instructions="Prefer one approval stage.",
    )
    assert "Build a todo app." in prompt
    assert "Prefer one approval stage." in prompt
    assert '"package_id": "coding-agent"' in prompt
    assert '"package_id": "approval"' in prompt
    assert f'<adlc:file path="{BLUEPRINT_FILE_PATH}">' in prompt
    # The blueprint shape (including the "edges" key) is rendered inside the
    # constraints section as JSON, so the quotes are escaped.
    assert "edges" in prompt
    assert "blueprint_shape" in prompt


def test_extract_blueprint_file_parses_the_document_block() -> None:
    payload = extract_blueprint_file(_final_text(_blueprint_document()))
    assert payload["stages"][0]["key"] == "implement"


def test_extract_blueprint_file_ignores_other_paths_and_requires_the_block() -> None:
    text = 'ok\n<adlc:file path="notes.txt">not the blueprint</adlc:file>\n'
    with pytest.raises(BlueprintGenerationError) as exc_info:
        extract_blueprint_file(text)
    assert exc_info.value.code == "BLUEPRINT_REPLY_MISSING_FILE"


def test_extract_blueprint_file_rejects_invalid_json() -> None:
    with pytest.raises(BlueprintGenerationError) as exc_info:
        extract_blueprint_file(_final_text("{not json"))
    assert exc_info.value.code == "BLUEPRINT_REPLY_INVALID_JSON"


def test_validate_document_requires_non_empty_stages() -> None:
    with pytest.raises(BlueprintGenerationError):
        apply_blueprint_to_flow_data(
            {"nodes": [], "edges": []},
            {"stages": []},
            _packages(),
            flow_id="flow-1",
        )


async def test_generate_blueprint_document_extracts_the_reply() -> None:
    state = _FakeRunState(final_text=_final_text(_blueprint_document()))
    fake = _FakeDshClient(state)
    document, session_id = await generate_blueprint_document(
        "Build a todo app.",
        _packages(),
        settings=_settings(),
        dsh_client=fake,
    )
    assert session_id == "fx-blueprint-1"
    assert document["name"] == "Todo frontend"
    assert "Build a todo app." in fake.created[0].prompts[0]
    assert fake.routes == [{"sessionId": "fx-blueprint-1", "provider": "my-codex", "model": "cx/gpt-5.6-luna"}]


async def test_model_route_mismatch_never_sends_a_planning_prompt():
    from unittest.mock import AsyncMock

    fake = _FakeDshClient(_FakeRunState())
    fake.rpc = AsyncMock(return_value={"selected": {"provider": "other", "model": "other"}})
    with pytest.raises(BlueprintGenerationError) as error:
        await generate_blueprint_document("Build a todo app.", _packages(), settings=_settings(), dsh_client=fake)
    assert error.value.code == "BLUEPRINT_MODEL_MISMATCH"
    assert fake.created[0].prompts == []


async def test_generate_blueprint_document_translates_dsh_errors(monkeypatch) -> None:
    class DshProtocolError(Exception):
        pass

    monkeypatch.setitem(sys.modules, "dsh_web_sdk", SimpleNamespace(DshClient=_FakeDshClient))
    monkeypatch.setitem(sys.modules, "dsh_web_sdk.errors", SimpleNamespace(DshError=DshProtocolError))
    state = _FakeRunState(error=DshProtocolError("HTTP 502"))
    fake = _FakeDshClient(state)
    with pytest.raises(BlueprintGenerationError) as exc_info:
        await generate_blueprint_document(
            "Build a todo app.",
            _packages(),
            settings=_settings(),
            dsh_client=fake,
        )
    assert exc_info.value.code == "BLUEPRINT_GENERATION_DSH_FAILED"
    assert exc_info.value.http_status == 502


async def test_missing_optional_sdk_rejects_generation_but_allows_injected_clients(monkeypatch) -> None:
    original_import = builtins.__import__

    def without_dsh_sdk(name, *args, **kwargs):
        if name == "dsh_web_sdk" or name.startswith("dsh_web_sdk."):
            raise ModuleNotFoundError(name=name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_dsh_sdk)
    with pytest.raises(BlueprintGenerationError) as exc_info:
        await generate_blueprint_document("Build a todo app.", _packages(), settings=_settings())
    assert exc_info.value.code == "BLUEPRINT_GENERATION_SDK_UNAVAILABLE"
    assert exc_info.value.http_status == 503

    document, session_id = await generate_blueprint_document(
        "Build a todo app.",
        _packages(),
        settings=_settings(),
        dsh_client=_FakeDshClient(_FakeRunState(final_text=_final_text(_blueprint_document()))),
    )
    assert document["name"] == "Todo frontend"
    assert session_id == "fx-blueprint-1"


async def test_generate_blueprint_document_reports_timeout() -> None:
    state = _FakeRunState(final_text=_final_text(_blueprint_document()), timeout=True)
    with pytest.raises(BlueprintGenerationError) as exc_info:
        await generate_blueprint_document(
            "Build a todo app.",
            _packages(),
            settings=_settings(),
            dsh_client=_FakeDshClient(state),
        )
    assert exc_info.value.code == "BLUEPRINT_GENERATION_TIMEOUT"
    assert exc_info.value.http_status == 504


async def test_generate_blueprint_document_requires_an_assistant_reply() -> None:
    state = _FakeRunState(final_text=None)
    with pytest.raises(BlueprintGenerationError) as exc_info:
        await generate_blueprint_document(
            "Build a todo app.",
            _packages(),
            settings=_settings(),
            dsh_client=_FakeDshClient(state),
        )
    assert exc_info.value.code == "BLUEPRINT_REPLY_EMPTY"


def test_settings_validate_requires_a_token() -> None:
    settings = BlueprintGenerationSettings(base_url="http://127.0.0.1:3080", api_token=None)
    with pytest.raises(BlueprintGenerationError) as exc_info:
        settings.validate()
    assert exc_info.value.code == "BLUEPRINT_GENERATION_NOT_CONFIGURED"
    assert exc_info.value.http_status == 503


def test_web_gateway_does_not_reuse_the_plugin_bearer(monkeypatch) -> None:
    monkeypatch.delenv("ADLC_BLUEPRINT_DSH_TOKEN", raising=False)
    monkeypatch.setenv("ADLC_HARNESS_API_TOKEN", "plugin-bearer-not-a-web-credential")
    settings = BlueprintGenerationSettings.from_environment()
    assert settings.api_token is None
    with pytest.raises(BlueprintGenerationError) as error:
        settings.validate()
    assert error.value.code == "BLUEPRINT_GENERATION_NOT_CONFIGURED"


def test_apply_blueprint_builds_marker_stage_nodes_and_edges() -> None:
    flow_data: dict[str, Any] = {"nodes": [], "edges": []}
    updated, stage_nodes, adlc_edges, warnings = apply_blueprint_to_flow_data(
        flow_data,
        _blueprint_document(),
        _packages(),
        flow_id="flow-1",
    )
    assert warnings == []
    assert updated["adlc"]["document_type"] == "WORKFLOW_DEFINITION"
    assert updated["adlc"]["workflow_definition_id"] == "flow-1"
    assert [node["type"] for node in updated["nodes"]] == ["adlcStageNode", "adlcStageNode"]

    implement = stage_nodes[0]["data"]["adlc"]
    assert implement["stage_type"] == "IMPLEMENTATION"
    assert implement["package_ref"] == {"package_id": "coding-agent", "version": "0.2.1"}
    assert implement["inputs"] == {"requirement": "Todo list with add and complete."}
    assert "source_patch" in implement["expected_outputs"]
    assert implement["metadata"]["generated_by"] == "dsh-blueprint-request"
    assert stage_nodes[0]["data"]["node"]["display_name"] == "Implement todo UI"

    approve = stage_nodes[1]["data"]["adlc"]
    assert approve["stage_type"] == "APPROVAL"
    assert approve["inputs"] == {}

    assert len(adlc_edges) == 1
    edge_contract = adlc_edges[0]["data"]["adlc"]
    assert edge_contract["condition"] == "ON_SUCCESS"
    assert edge_contract["bindings"] == [{"source_output": "source_patch", "target_input": "approval_context"}]
    assert adlc_edges[0]["source"] == stage_nodes[0]["id"]
    assert adlc_edges[0]["target"] == stage_nodes[1]["id"]
    assert adlc_edges[0]["type"] == "adlcEdge"

    # Dependency layout: the dependent stage is placed in a later column.
    assert stage_nodes[1]["position"]["x"] > stage_nodes[0]["position"]["x"]


def test_apply_skips_unknown_packages_and_their_edges() -> None:
    document = _blueprint_document()
    document["stages"][1]["package_id"] = "does-not-exist"
    updated, stage_nodes, adlc_edges, warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        document,
        _packages(),
        flow_id="flow-1",
    )
    assert len(stage_nodes) == 1
    assert adlc_edges == []
    assert any("does-not-exist" in warning for warning in warnings)
    assert len(updated["nodes"]) == 1


def test_apply_filters_incompatible_bindings_and_flags_cycles() -> None:
    document = _blueprint_document()
    document["stages"][0]["inputs"] = {"requirement": "ok", "mystery": 1}
    document["edges"].append({"from": "approve", "to": "implement"})
    _updated, stage_nodes, adlc_edges, warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        document,
        _packages(),
        flow_id="flow-1",
    )
    assert stage_nodes[0]["data"]["adlc"]["inputs"] == {"requirement": "ok"}
    assert len(adlc_edges) == 2
    assert any("cycle" in warning for warning in warnings)
    assert any("mystery" in warning for warning in warnings)


def test_apply_warns_when_dsh_picks_non_default_agent() -> None:
    """When DSH picks a non-default agent, the apply step must warn."""
    document = _blueprint_document()
    # Force the implement stage to use a non-default coding agent version.
    document["stages"][0]["package_id"] = "coding-agent"
    document["stages"][0]["version"] = "0.1.0"
    _updated, _stage_nodes, _adlc_edges, warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        document,
        _packages(),
        flow_id="flow-1",
    )
    assert any("not the default coding agent" in warning and "coding-agent@0.1.0" in warning for warning in warnings)


def test_apply_does_not_warn_for_approval_or_review_kinds() -> None:
    """APPROVAL and REVIEW gates are allowed to use their own packages."""
    document = _blueprint_document()
    # The approve stage already uses the 'approval' package — no warning.
    _updated, _stage_nodes, _adlc_edges, warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        document,
        _packages(),
        flow_id="flow-1",
    )
    assert not any("not the default coding agent" in warning for warning in warnings)


def test_render_prompt_pins_default_coding_agent() -> None:
    """The prompt must tell DSH to use coding-agent@0.2.1 as the default."""
    prompt = render_blueprint_prompt(
        "Build a todo app",
        _packages(),
    )
    assert "coding-agent@0.2.1" in prompt
    assert "DEFAULT AGENT" in prompt
    assert "not currently supported" in prompt


def test_prompt_keeps_explicit_package_scope_and_planning_only_boundary() -> None:
    prompt = render_blueprint_prompt(
        "Use coding-agent@0.3.0 with a frozen app.py-only task loop and an approval stage.",
        _packages(),
    )
    assert "coding-agent@0.3.0" in prompt
    assert "Do not override an explicitly requested package/version" in prompt
    assert "do not run commands, edit files" in prompt
    assert "Every stage's package_id and version MUST be set" not in prompt


def test_apply_preserves_the_existing_marker_and_note_nodes() -> None:
    marker = {
        "document_type": "WORKFLOW_DEFINITION",
        "schema_version": "0.1",
        "workflow_definition_id": "flow-1",
        "version": 3,
        "status": "DRAFT",
        "default_policies": {},
        "metadata": {"purpose": "keep-me"},
    }
    flow_data = {
        "adlc": dict(marker),
        "nodes": [
            {"id": "note-1", "type": "noteNode", "position": {"x": 0, "y": 0}, "data": {}},
        ],
        "edges": [],
        "viewport": {"x": 4, "y": 5, "zoom": 1},
    }
    updated, stage_nodes, adlc_edges, _warnings = apply_blueprint_to_flow_data(
        flow_data,
        _blueprint_document(),
        _packages(),
        flow_id="flow-1",
    )
    assert updated["adlc"]["version"] == 3
    assert updated["adlc"]["metadata"] == {"purpose": "keep-me"}
    assert [node["id"] for node in updated["nodes"]][:1] == ["note-1"]
    assert len(updated["nodes"]) == 3
    assert updated["viewport"] == {"x": 4, "y": 5, "zoom": 1}
    assert len(stage_nodes) == 2
    assert len(adlc_edges) == 1


def test_applied_stages_summary_projects_contracts() -> None:
    _updated, stage_nodes, adlc_edges, _warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        _blueprint_document(),
        _packages(),
        flow_id="flow-1",
    )
    summary = applied_stages_summary(stage_nodes)
    assert summary[0]["package"] == "coding-agent@0.2.1"
    assert summary[1]["stage_type"] == "APPROVAL"
    assert adlc_edges[0]["source"] == summary[0]["node_id"]


def test_current_stages_projection_lists_existing_stages() -> None:
    updated, _stage_nodes, _adlc_edges, _warnings = apply_blueprint_to_flow_data(
        {"nodes": [], "edges": []},
        _blueprint_document(),
        _packages(),
        flow_id="flow-1",
    )
    projection = current_stages_projection(updated)
    assert [stage["package"] for stage in projection] == ["coding-agent@0.2.1", "approval@0.1.0"]

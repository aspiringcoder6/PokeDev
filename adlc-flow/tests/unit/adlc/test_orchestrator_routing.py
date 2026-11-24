# ruff: noqa: INP001, S101
"""Unit tests for the orchestrator routing flag and routing seam (G1 + G2)."""

from __future__ import annotations

import pytest

from langflow.adlc.orchestrator_plugin import (
    DeepSeekHarnessPlugin,
    MonarchPlugin,
    OrchestratorHost,
    PluginMetadata,
    get_production_host,
    reset_production_host,
)
from langflow.adlc.orchestrator_routing import (
    ORCHESTRATOR_AUTO_ADAPTER_REF,
    ORCHESTRATOR_ROUTING_ENV,
    orchestrator_routing_enabled,
)
from langflow.adlc.planning.errors import PLAN_NO_CAPABLE_PLUGIN, ExecutionPlanStateError
from langflow.adlc.planning.materializer import parse_required_capabilities, resolve_orchestrator_route
from langflow.adlc.resource_manager import AgentCapability


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "True", "Yes", " on "])
def test_flag_is_on_for_explicit_true_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, value)
    assert orchestrator_routing_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "unexpected", "enabled=1"])
def test_flag_is_off_for_any_other_value(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, value)
    assert orchestrator_routing_enabled() is False


def test_flag_defaults_to_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the env var the flag must be off: legacy routing is intact."""
    monkeypatch.delenv(ORCHESTRATOR_ROUTING_ENV, raising=False)
    assert orchestrator_routing_enabled() is False


def test_empty_value_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, "")
    assert orchestrator_routing_enabled() is False


def test_reserved_auto_adapter_ref_value() -> None:
    """The reserved adapter_ref value is exactly "orchestrator:auto" (ADR)."""
    assert ORCHESTRATOR_AUTO_ADAPTER_REF == "orchestrator:auto"


class _StubPlugin:
    """Minimal plugin used to test registration-order tie-breaking."""

    def __init__(self, plugin_id: str, capabilities: frozenset[AgentCapability]) -> None:
        self._metadata = PluginMetadata(
            plugin_id=plugin_id,
            display_name=plugin_id,
            version="1.0.0",
            supported_capabilities=capabilities,
        )

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata


class TestProductionHostFactory:
    def test_production_host_registers_monarch_enabled_and_harness_disabled(self) -> None:
        reset_production_host()
        host = get_production_host()
        metadata = {meta.plugin_id: meta for meta in host.list_metadata()}
        assert set(metadata) == {"monarch", "deepseek-harness"}
        assert metadata["monarch"].enabled is True
        assert metadata["deepseek-harness"].enabled is False

    def test_production_host_is_singleton_until_reset(self) -> None:
        reset_production_host()
        assert get_production_host() is get_production_host()
        reset_production_host()
        assert get_production_host() is not None

    def test_production_host_find_capable_excludes_disabled_stub(self) -> None:
        reset_production_host()
        host = get_production_host()
        # SECURITY_SCAN is only declared by the disabled DeepSeek stub.
        assert host.find_capable(frozenset({AgentCapability.SECURITY_SCAN})) == ()
        capable = host.find_capable(frozenset({AgentCapability.CODE_GENERATION}))
        assert [plugin.metadata.plugin_id for plugin in capable] == ["monarch"]


class TestParseRequiredCapabilities:
    def test_keeps_only_known_capability_values(self) -> None:
        parsed = parse_required_capabilities(
            ["code_generation", "agent-provider:mock", "model:mock/deterministic"]
        )
        assert parsed == (AgentCapability.CODE_GENERATION,)

    def test_deduplicates_and_preserves_first_seen_order(self) -> None:
        parsed = parse_required_capabilities(
            ["test_runner", "code_generation", "test_runner"]
        )
        assert parsed == (AgentCapability.TEST_RUNNER, AgentCapability.CODE_GENERATION)

    def test_empty_when_no_semantic_capability_present(self) -> None:
        assert parse_required_capabilities(["agent-provider:mock", "tool:mock-artifact"]) == ()


class TestResolveOrchestratorRoute:
    def test_resolves_monarch_for_code_generation(self) -> None:
        """(a) orchestrator:auto + matching capability → correct plugin."""
        reset_production_host()
        selected = resolve_orchestrator_route(["agent-provider:mock", "code_generation"])
        assert selected.plugin_id == "monarch"

    def test_prefers_first_registered_plugin_on_capability_tie(self) -> None:
        """(b) two capable plugins → registration order decides, deterministically."""
        host = OrchestratorHost()
        first = _StubPlugin("first-plugin", frozenset({AgentCapability.CODE_GENERATION}))
        second = _StubPlugin("second-plugin", frozenset({AgentCapability.CODE_GENERATION}))
        host.register(second)
        host.register(first)
        selected = resolve_orchestrator_route(["code_generation"], host=host)
        assert selected.plugin_id == "second-plugin"

    def test_order_tie_break_with_production_host_registration_order(self) -> None:
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())
        selected = resolve_orchestrator_route(["code_generation"], host=host)
        assert selected.plugin_id == "monarch"

    def test_no_capable_plugin_raises_domain_error(self) -> None:
        reset_production_host()
        # SECURITY_SCAN is declared only by the disabled DeepSeek stub.
        with pytest.raises(ExecutionPlanStateError) as excinfo:
            resolve_orchestrator_route(["security_scan"])
        assert excinfo.value.code == PLAN_NO_CAPABLE_PLUGIN
        assert excinfo.value.details["adapter_ref"] == "orchestrator:auto"
        assert excinfo.value.details["recognized_capabilities"] == ["security_scan"]

    def test_no_recognized_capability_raises_domain_error(self) -> None:
        reset_production_host()
        with pytest.raises(ExecutionPlanStateError) as excinfo:
            resolve_orchestrator_route(["agent-provider:mock", "tool:mock-artifact"])
        assert excinfo.value.code == PLAN_NO_CAPABLE_PLUGIN
        assert excinfo.value.details["recognized_capabilities"] == []

    def test_explicit_host_overrides_production_default(self) -> None:
        host = OrchestratorHost()
        host.register(_StubPlugin("only-plugin", frozenset({AgentCapability.PLANNING})))
        selected = resolve_orchestrator_route(["planning"], host=host)
        assert selected.plugin_id == "only-plugin"

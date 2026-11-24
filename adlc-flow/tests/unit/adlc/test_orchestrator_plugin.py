"""Unit tests for the Orchestrator Plugin module."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from langflow.adlc.orchestrator_plugin import (
    DeepSeekHarnessPlugin,
    ExecutionPlan,
    ExecutionResult,
    Intent,
    IntentType,
    MonarchPlugin,
    NoCapablePluginError,
    OrchestratorHost,
    OrchestratorPlugin,
    PlanStep,
    PluginMetadata,
    PluginNotFoundError,
    ReflectionReport,
    StepResult,
    get_default_host,
    reset_default_host,
)
from langflow.adlc.resource_manager import AgentCapability


def _run(coro):
    """Run an async coroutine in a test."""
    return asyncio.run(coro)


def _make_intent(
    intent_type: IntentType = IntentType.CODE_GENERATION,
    description: str = "Test intent",
    capabilities: frozenset[AgentCapability] | None = None,
) -> Intent:
    return Intent(
        intent_type=intent_type,
        description=description,
        required_capabilities=capabilities or frozenset({AgentCapability.CODE_GENERATION}),
    )


class TestInterfaceModels:
    def test_intent_requires_description(self):
        with pytest.raises(ValueError):
            Intent(intent_type=IntentType.CODE_GENERATION, description="")

    def test_intent_default_capabilities_empty(self):
        intent = Intent(
            intent_type=IntentType.CODE_GENERATION,
            description="test",
        )
        assert intent.required_capabilities == frozenset()

    def test_plan_step_requires_capabilities(self):
        with pytest.raises(ValueError):
            PlanStep(
                name="test",
                required_capabilities=frozenset(),
            )

    def test_execution_plan_requires_steps(self):
        intent = _make_intent()
        with pytest.raises(ValueError):
            ExecutionPlan(intent_id=intent.intent_id, steps=(), plugin_id="test")

    def test_plugin_metadata_requires_capabilities(self):
        with pytest.raises(ValueError):
            PluginMetadata(
                plugin_id="test",
                display_name="Test",
                version="1.0",
                supported_capabilities=frozenset(),
            )


class TestMonarchPlugin:
    def test_metadata(self):
        plugin = MonarchPlugin()
        meta = plugin.metadata
        assert meta.plugin_id == "monarch"
        assert meta.enabled
        assert AgentCapability.CODE_GENERATION in meta.supported_capabilities

    def test_plan_produces_single_step(self):
        plugin = MonarchPlugin()
        intent = _make_intent(IntentType.CODE_GENERATION)
        plan = _run(plugin.plan(intent))
        assert plan.intent_id == intent.intent_id
        assert plan.plugin_id == "monarch"
        assert len(plan.steps) == 1
        assert AgentCapability.CODE_GENERATION in plan.steps[0].required_capabilities

    def test_plan_uses_intent_capabilities(self):
        plugin = MonarchPlugin()
        intent = _make_intent(
            IntentType.CODE_REVIEW,
            capabilities=frozenset({AgentCapability.CODE_REVIEW}),
        )
        plan = _run(plugin.plan(intent))
        assert AgentCapability.CODE_REVIEW in plan.steps[0].required_capabilities

    def test_execute_plan_only_mode(self):
        plugin = MonarchPlugin()  # No monarch_agent → plan-only mode
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        result = _run(plugin.execute(plan))
        assert result.status == "succeeded"
        assert len(result.step_results) == 1
        assert result.step_results[0].status == "succeeded"
        assert result.step_results[0].output["mode"] == "plan-only"

    def test_execute_with_mock_agent(self):
        plugin = MonarchPlugin(monarch_agent={"name": "mock"})
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        result = _run(plugin.execute(plan))
        assert result.step_results[0].output["mode"] == "live"

    def test_reflect_summarizes_result(self):
        plugin = MonarchPlugin()
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        result = _run(plugin.execute(plan))
        report = _run(plugin.reflect(result))
        assert report.plan_id == plan.plan_id
        assert "succeeded" in report.summary
        assert len(report.successes) == 1


class TestDeepSeekHarnessPlugin:
    def test_metadata_disabled_by_default(self):
        plugin = DeepSeekHarnessPlugin()
        assert plugin.metadata.plugin_id == "deepseek-harness"
        assert not plugin.metadata.enabled  # Disabled until client wired
        assert AgentCapability.SECURITY_SCAN in plugin.metadata.supported_capabilities

    def test_execute_stub_mode(self):
        plugin = DeepSeekHarnessPlugin()  # No client → stub mode
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        result = _run(plugin.execute(plan))
        assert result.status == "succeeded"
        assert result.step_results[0].status == "skipped"
        assert result.step_results[0].output["mode"] == "stub"

    def test_reflect_suggests_wiring_client(self):
        plugin = DeepSeekHarnessPlugin()
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        result = _run(plugin.execute(plan))
        report = _run(plugin.reflect(result))
        assert any("harness_client" in s for s in report.suggestions)


class TestOrchestratorHost:
    def test_register_and_get(self):
        host = OrchestratorHost()
        plugin = MonarchPlugin()
        host.register(plugin)
        assert host.get("monarch") is plugin

    def test_get_unknown_raises(self):
        host = OrchestratorHost()
        with pytest.raises(PluginNotFoundError):
            host.get("nonexistent")

    def test_unregister(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.unregister("monarch")
        with pytest.raises(PluginNotFoundError):
            host.get("monarch")

    def test_register_replaces(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(MonarchPlugin())  # Replace
        assert len(host.list_metadata()) == 1

    def test_list_metadata(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())
        meta = host.list_metadata()
        assert len(meta) == 2
        ids = {m.plugin_id for m in meta}
        assert ids == {"monarch", "deepseek-harness"}

    def test_list_enabled_excludes_disabled(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())  # enabled
        host.register(DeepSeekHarnessPlugin())  # disabled
        enabled = host.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].metadata.plugin_id == "monarch"

    def test_find_capable(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())
        # Monarch supports CODE_GENERATION.
        capable = host.find_capable(frozenset({AgentCapability.CODE_GENERATION}))
        assert len(capable) == 1
        assert capable[0].metadata.plugin_id == "monarch"

    def test_find_capable_excludes_disabled(self):
        host = OrchestratorHost()
        host.register(DeepSeekHarnessPlugin())  # disabled
        capable = host.find_capable(frozenset({AgentCapability.SECURITY_SCAN}))
        assert len(capable) == 0

    def test_dispatch_plan_with_explicit_plugin(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        intent = _make_intent()
        plan = _run(host.dispatch_plan(intent, plugin_id="monarch"))
        assert plan.plugin_id == "monarch"

    def test_dispatch_plan_auto_selects(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        intent = _make_intent(capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        plan = _run(host.dispatch_plan(intent))
        assert plan.plugin_id == "monarch"

    def test_dispatch_plan_no_capable_raises(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        intent = _make_intent(capabilities=frozenset({AgentCapability.SECURITY_SCAN}))
        with pytest.raises(NoCapablePluginError):
            _run(host.dispatch_plan(intent))

    def test_dispatch_execute_uses_plan_plugin(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        intent = _make_intent()
        plan = _run(host.dispatch_plan(intent))
        result = _run(host.dispatch_execute(plan))
        assert result.plugin_id == "monarch"

    def test_dispatch_reflect_uses_result_plugin(self):
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        intent = _make_intent()
        plan = _run(host.dispatch_plan(intent))
        result = _run(host.dispatch_execute(plan))
        report = _run(host.dispatch_reflect(result))
        assert report.plugin_id == "monarch"

    def test_dispatch_execute_unknown_plugin_raises(self):
        host = OrchestratorHost()
        intent = _make_intent()
        plan = ExecutionPlan(
            intent_id=intent.intent_id,
            steps=(
                PlanStep(
                    name="test",
                    required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
                ),
            ),
            plugin_id="nonexistent",
        )
        with pytest.raises(PluginNotFoundError):
            _run(host.dispatch_execute(plan))


class TestDefaultHost:
    def test_get_default_host_returns_singleton(self):
        reset_default_host()
        host1 = get_default_host()
        host2 = get_default_host()
        assert host1 is host2

    def test_reset_clears_singleton(self):
        host1 = get_default_host()
        reset_default_host()
        host2 = get_default_host()
        assert host1 is not host2

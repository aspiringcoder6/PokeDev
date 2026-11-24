"""Integration tests for the Orchestrator Plugin module.

Verifies:
1. End-to-end plan → execute → reflect flow
2. Multi-plugin dispatch (Monarch + DeepSeek Harness stub)
3. Backward compatibility: existing Monarch component still works
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from langflow.adlc.orchestrator_plugin import (
    DeepSeekHarnessPlugin,
    ExecutionPlan,
    Intent,
    IntentType,
    MonarchPlugin,
    NoCapablePluginError,
    OrchestratorHost,
    PlanStep,
    PluginNotFoundError,
    get_default_host,
    reset_default_host,
)
from langflow.adlc.resource_manager import (
    AgentCapability,
    AgentProfile,
    CapabilityRequirement,
    CostTier,
    ResourceManager,
)


def _run(coro):
    return asyncio.run(coro)


def _make_intent(
    intent_type: IntentType = IntentType.CODE_GENERATION,
    capabilities: frozenset[AgentCapability] | None = None,
) -> Intent:
    return Intent(
        intent_type=intent_type,
        description=f"Test {intent_type.value}",
        required_capabilities=capabilities or frozenset({AgentCapability.CODE_GENERATION}),
    )


class TestEndToEndFlow:
    def test_plan_execute_reflect_cycle(self):
        """Full lifecycle: plan → execute → reflect."""
        host = OrchestratorHost()
        host.register(MonarchPlugin())

        intent = _make_intent(IntentType.CODE_GENERATION)
        plan = _run(host.dispatch_plan(intent))
        assert plan.plugin_id == "monarch"
        assert len(plan.steps) == 1

        result = _run(host.dispatch_execute(plan))
        assert result.status == "succeeded"
        assert result.plugin_id == "monarch"

        report = _run(host.dispatch_reflect(result))
        assert report.plugin_id == "monarch"
        assert "succeeded" in report.summary

    def test_multi_intent_workflow(self):
        """Handle multiple intents in sequence."""
        host = OrchestratorHost()
        host.register(MonarchPlugin())

        intents = [
            _make_intent(IntentType.CODE_GENERATION),
            _make_intent(IntentType.CODE_REVIEW),
            _make_intent(IntentType.TESTING),
        ]

        for intent in intents:
            plan = _run(host.dispatch_plan(intent))
            result = _run(host.dispatch_execute(plan))
            report = _run(host.dispatch_reflect(result))
            assert result.status == "succeeded"
            assert report.plugin_id == "monarch"


class TestMultiPluginDispatch:
    def test_dispatch_to_specific_plugin(self):
        """Explicit plugin_id routes to the correct plugin."""
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())

        intent = _make_intent()
        plan = _run(host.dispatch_plan(intent, plugin_id="deepseek-harness"))
        assert plan.plugin_id == "deepseek-harness"

    def test_auto_select_picks_capable_plugin(self):
        """Auto-selection picks the first capable plugin."""
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())

        # SECURITY_SCAN is only supported by DeepSeek Harness, but it's disabled.
        # So auto-select should fail.
        intent = _make_intent(
            capabilities=frozenset({AgentCapability.SECURITY_SCAN})
        )
        with pytest.raises(NoCapablePluginError):
            _run(host.dispatch_plan(intent))

    def test_enable_deepseek_harness_for_testing(self):
        """Enable DeepSeek Harness and verify it can be selected."""
        host = OrchestratorHost()
        dsh = DeepSeekHarnessPlugin()
        # Manually enable for testing.
        object.__setattr__(
            dsh._metadata, "enabled", True
        )
        host.register(MonarchPlugin())
        host.register(dsh)

        intent = _make_intent(
            capabilities=frozenset({AgentCapability.SECURITY_SCAN})
        )
        plan = _run(host.dispatch_plan(intent))
        assert plan.plugin_id == "deepseek-harness"


class TestIntegrationWithResourceManager:
    def test_plugin_capabilities_match_resource_manager(self):
        """Plugin capabilities should be usable with Resource Manager."""
        host = OrchestratorHost()
        host.register(MonarchPlugin())

        rm = ResourceManager()
        # Register an agent that matches Monarch's capabilities.
        rm.register_agent(
            AgentProfile(
                agent_id="monarch-agent",
                display_name="Monarch Agent",
                capabilities=frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.MEDIUM,
                trust_score=0.8,
            )
        )

        # Resource Manager can allocate based on intent requirements.
        intent = _make_intent(IntentType.CODE_GENERATION)
        decision = rm.allocate(
            CapabilityRequirement(
                required_capabilities=intent.required_capabilities,
                task_id=uuid4(),
            )
        )
        assert decision.agent_id == "monarch-agent"

        # Orchestrator Host can plan based on the same intent.
        plan = _run(host.dispatch_plan(intent))
        assert plan.plugin_id == "monarch"


class TestBackwardCompatibility:
    def test_default_host_is_singleton(self):
        """get_default_host returns the same instance."""
        reset_default_host()
        host1 = get_default_host()
        host2 = get_default_host()
        assert host1 is host2

    def test_plugin_metadata_is_serializable(self):
        """Plugin metadata can be serialized to dict."""
        plugin = MonarchPlugin()
        meta = plugin.metadata
        data = meta.model_dump()
        assert data["plugin_id"] == "monarch"
        assert "code_generation" in data["supported_capabilities"]

    def test_execution_plan_is_serializable(self):
        """Execution plan can be serialized to dict."""
        plugin = MonarchPlugin()
        intent = _make_intent()
        plan = _run(plugin.plan(intent))
        data = plan.model_dump()
        assert data["plugin_id"] == "monarch"
        assert len(data["steps"]) == 1

    def test_monarch_plugin_uses_existing_capability_taxonomy(self):
        """Monarch plugin capabilities match the Resource Manager taxonomy."""
        from langflow.adlc.resource_manager import AgentCapability

        plugin = MonarchPlugin()
        # All plugin capabilities should be valid AgentCapability values.
        for cap in plugin.metadata.supported_capabilities:
            assert isinstance(cap, AgentCapability)

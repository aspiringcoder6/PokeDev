"""Orchestrator Plugin Host — registry and dispatcher.

The Host manages a collection of OrchestratorPlugin instances and
provides a single entry point for the control plane to dispatch
intents to the appropriate plugin based on capability matching.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

from langflow.adlc.orchestrator_plugin.interface import (
    ExecutionPlan,
    ExecutionResult,
    Intent,
    OrchestratorPlugin,
    PluginMetadata,
    ReflectionReport,
)
from langflow.adlc.resource_manager import AgentCapability


class PluginNotFoundError(KeyError):
    """Raised when a requested plugin is not registered."""

    def __init__(self, plugin_id: str) -> None:
        super().__init__(f"Plugin '{plugin_id}' is not registered")
        self.plugin_id = plugin_id


class NoCapablePluginError(RuntimeError):
    """Raised when no registered plugin supports the required capabilities."""

    def __init__(self, capabilities: frozenset[AgentCapability]) -> None:
        super().__init__(
            f"No enabled plugin supports capabilities: "
            f"{sorted(c.value for c in capabilities)}"
        )
        self.capabilities = capabilities


class OrchestratorHost:
    """Registry and dispatcher for OrchestratorPlugin instances.

    Typical usage:
        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())
        plan = await host.dispatch_plan(intent)
        result = await host.dispatch_execute(plan)
    """

    def __init__(self) -> None:
        self._plugins: dict[str, OrchestratorPlugin] = {}
        self._lock = RLock()

    def register(self, plugin: OrchestratorPlugin) -> None:
        """Register a plugin. Replaces if plugin_id already exists."""
        with self._lock:
            self._plugins[plugin.metadata.plugin_id] = plugin

    def unregister(self, plugin_id: str) -> None:
        """Remove a plugin by ID. No-op if not present."""
        with self._lock:
            self._plugins.pop(plugin_id, None)

    def get(self, plugin_id: str) -> OrchestratorPlugin:
        """Return a plugin by ID. Raises PluginNotFoundError if absent."""
        with self._lock:
            plugin = self._plugins.get(plugin_id)
            if plugin is None:
                raise PluginNotFoundError(plugin_id)
            return plugin

    def list_metadata(self) -> tuple[PluginMetadata, ...]:
        """Return metadata for all registered plugins."""
        with self._lock:
            return tuple(p.metadata for p in self._plugins.values())

    def list_enabled(self) -> tuple[OrchestratorPlugin, ...]:
        """Return all enabled plugins."""
        with self._lock:
            return tuple(
                p for p in self._plugins.values() if p.metadata.enabled
            )

    def find_capable(
        self, capabilities: frozenset[AgentCapability]
    ) -> tuple[OrchestratorPlugin, ...]:
        """Return all enabled plugins that support ALL given capabilities."""
        with self._lock:
            results = []
            for plugin in self._plugins.values():
                if not plugin.metadata.enabled:
                    continue
                if capabilities.issubset(plugin.metadata.supported_capabilities):
                    results.append(plugin)
            return tuple(results)

    async def dispatch_plan(
        self,
        intent: Intent,
        *,
        plugin_id: str | None = None,
    ) -> ExecutionPlan:
        """Dispatch plan() to the appropriate plugin.

        If plugin_id is given, use that plugin. Otherwise, pick the
        first enabled plugin that supports the intent's required
        capabilities.
        """
        plugin = self._select_plugin(intent.required_capabilities, plugin_id)
        return await plugin.plan(intent)

    async def dispatch_execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Dispatch execute() to the plugin that produced the plan."""
        plugin = self.get(plan.plugin_id)
        return await plugin.execute(plan, context)

    async def dispatch_reflect(
        self,
        result: ExecutionResult,
    ) -> ReflectionReport:
        """Dispatch reflect() to the plugin that produced the result."""
        plugin = self.get(result.plugin_id)
        return await plugin.reflect(result)

    def _select_plugin(
        self,
        capabilities: frozenset[AgentCapability],
        plugin_id: str | None,
    ) -> OrchestratorPlugin:
        if plugin_id is not None:
            return self.get(plugin_id)
        capable = self.find_capable(capabilities)
        if not capable:
            raise NoCapablePluginError(capabilities)
        # Deterministic: pick the first capable plugin.
        return capable[0]


# Module-level default host for convenience.
_default_host: OrchestratorHost | None = None


def get_default_host() -> OrchestratorHost:
    """Return a process-wide default OrchestratorHost instance."""
    global _default_host
    if _default_host is None:
        _default_host = OrchestratorHost()
    return _default_host


def reset_default_host() -> None:
    """Reset the process-wide default host (for tests)."""
    global _default_host
    _default_host = None


_production_host: OrchestratorHost | None = None


def get_production_host() -> OrchestratorHost:
    """Return a process-wide OrchestratorHost wired for production routing.

    Follows the get_default_host() singleton pattern, but pre-registers
    the standard production plugin set: MonarchPlugin (enabled) and the
    DeepSeekHarnessPlugin stub (disabled until its client is wired).
    ``find_capable`` returns plugins in registration order, so Monarch
    wins capability ties unless callers replace the host.
    """
    global _production_host
    if _production_host is None:
        from langflow.adlc.orchestrator_plugin.plugins.deepseek_harness import (
            DeepSeekHarnessPlugin,
        )
        from langflow.adlc.orchestrator_plugin.plugins.monarch import MonarchPlugin

        host = OrchestratorHost()
        host.register(MonarchPlugin())
        host.register(DeepSeekHarnessPlugin())
        _production_host = host
    return _production_host


def reset_production_host() -> None:
    """Reset the process-wide production host (for tests)."""
    global _production_host
    _production_host = None


__all__ = [
    "NoCapablePluginError",
    "OrchestratorHost",
    "PluginNotFoundError",
    "get_default_host",
    "get_production_host",
    "reset_default_host",
    "reset_production_host",
]

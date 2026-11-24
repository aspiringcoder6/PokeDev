"""Orchestrator Plugin — pluggable agent runtime backends.

The Orchestrator Plugin interface decouples the ADLC control plane from
any specific agent runtime. Plugins are opt-in infrastructure: the
production execution path (run_service + executor_router) does not
dispatch through this host yet. Monarch (OpenCode backend) and the
DeepSeek Harness stub are wired only in tests pending integration.

Public API:
- Intent, IntentType, ExecutionPlan, PlanStep, ExecutionResult, StepResult
- ReflectionReport, PluginMetadata
- OrchestratorPlugin (Protocol)
- OrchestratorHost, PluginNotFoundError, NoCapablePluginError
- MonarchPlugin, DeepSeekHarnessPlugin
- PlanGenerationError, StepDraft (LLM plan DAG validation)
- DelegatedTask and skilltree materialization (delegation contracts)
"""

from langflow.adlc.orchestrator_plugin.delegation import (
    DELEGATION_OUTPUT_SCHEMA,
    DelegatedTask,
    build_skilltree_document,
    delegation_schema_example,
    parse_delegated_task,
    to_roadmap_constraints,
    to_skilltree_node_spec,
)
from langflow.adlc.orchestrator_plugin.host import (
    NoCapablePluginError,
    OrchestratorHost,
    PluginNotFoundError,
    get_default_host,
    get_production_host,
    reset_default_host,
    reset_production_host,
)
from langflow.adlc.orchestrator_plugin.interface import (
    ExecutionPlan,
    ExecutionResult,
    Intent,
    IntentType,
    OrchestratorPlugin,
    PlanStep,
    PluginMetadata,
    ReflectionReport,
    StepResult,
)
from langflow.adlc.orchestrator_plugin.plan_dag import (
    PlanGenerationError,
    StepDraft,
)
from langflow.adlc.orchestrator_plugin.plugins.deepseek_harness import (
    DeepSeekHarnessPlugin,
)
from langflow.adlc.orchestrator_plugin.plugins.monarch import MonarchPlugin

__all__ = [
    # Interface
    "DELEGATION_OUTPUT_SCHEMA",
    "DelegatedTask",
    "ExecutionPlan",
    "ExecutionResult",
    "Intent",
    "IntentType",
    "OrchestratorPlugin",
    "PlanGenerationError",
    "PlanStep",
    "PluginMetadata",
    "ReflectionReport",
    "StepDraft",
    "StepResult",
    # Host
    "NoCapablePluginError",
    "OrchestratorHost",
    "PluginNotFoundError",
    "get_default_host",
    "get_production_host",
    "reset_default_host",
    "reset_production_host",
    # Plugins
    "DeepSeekHarnessPlugin",
    "MonarchPlugin",
    # Delegation contracts
    "build_skilltree_document",
    "delegation_schema_example",
    "parse_delegated_task",
    "to_roadmap_constraints",
    "to_skilltree_node_spec",
]

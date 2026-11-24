"""Orchestrator Plugin — abstract interface for agent runtime backends.

The Orchestrator Plugin interface decouples the ADLC control plane from
any specific agent runtime. Today the only production plugin is Monarch
(backed by OpenCode); tomorrow DeepSeek Harness can be plugged in
without changing the control plane.

This module is additive: existing Monarch usage in
adlc_components/custom_component/agents/orchestrator.py continues to
work. The plugin interface provides a clean seam for future runtimes.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from langflow.adlc.resource_manager import AgentCapability


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntentType(str, Enum):
    """High-level intent categories the orchestrator can handle."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TESTING = "testing"
    PLANNING = "planning"
    REFLECTION = "reflection"
    ORCHESTRATION = "orchestration"


class Intent(BaseModel):
    """A high-level intent submitted to the orchestrator.

    The intent describes WHAT the user wants, not HOW to do it. The
    orchestrator plugin is responsible for planning and execution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    intent_type: IntentType
    description: str = Field(min_length=1, max_length=4096)
    context: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
    submitted_at: datetime = Field(default_factory=_utc_now)
    submitted_by: str | None = None


class PlanStep(BaseModel):
    """A single step in an execution plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    required_capabilities: frozenset[AgentCapability]
    depends_on: tuple[UUID, ...] = Field(default=(), max_length=64)
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("required_capabilities")
    @classmethod
    def _require_non_empty_capabilities(
        cls, value: frozenset[AgentCapability]
    ) -> frozenset[AgentCapability]:
        if not value:
            msg = "PlanStep must declare at least one required capability"
            raise ValueError(msg)
        return value


class ExecutionPlan(BaseModel):
    """A plan produced by an orchestrator plugin.

    The plan is a DAG of steps. The control plane is responsible for
    scheduling and dispatch; the plugin only produces the plan.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    steps: tuple[PlanStep, ...]
    created_at: datetime = Field(default_factory=_utc_now)
    plugin_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("steps")
    @classmethod
    def _require_non_empty_steps(
        cls, value: tuple[PlanStep, ...]
    ) -> tuple[PlanStep, ...]:
        if not value:
            msg = "ExecutionPlan must contain at least one step"
            raise ValueError(msg)
        return value


class StepResult(BaseModel):
    """Result of executing one plan step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: UUID
    status: str  # "succeeded" | "failed" | "skipped"
    output: Any = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime
    artifacts: tuple[dict[str, Any], ...] = Field(default=())


class ExecutionResult(BaseModel):
    """Result of executing an entire plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: UUID
    intent_id: UUID
    status: str  # "succeeded" | "failed" | "partial"
    step_results: tuple[StepResult, ...]
    started_at: datetime
    completed_at: datetime
    plugin_id: str


class ReflectionReport(BaseModel):
    """Post-execution reflection produced by the orchestrator.

    The reflection captures what worked, what failed, and suggestions
    for future runs. Used by the Agent Trust Score module (Phase 2
    follow-up) to update agent profiles.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    intent_id: UUID
    summary: str
    successes: tuple[str, ...] = Field(default=(), max_length=64)
    failures: tuple[str, ...] = Field(default=(), max_length=64)
    suggestions: tuple[str, ...] = Field(default=(), max_length=64)
    created_at: datetime = Field(default_factory=_utc_now)
    plugin_id: str


class PluginMetadata(BaseModel):
    """Static metadata about an orchestrator plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plugin_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    version: str = Field(min_length=1, max_length=64)
    author: str = Field(default="", max_length=256)
    supported_capabilities: frozenset[AgentCapability]
    description: str = Field(default="", max_length=1024)
    enabled: bool = True

    @field_validator("supported_capabilities")
    @classmethod
    def _require_non_empty_capabilities(
        cls, value: frozenset[AgentCapability]
    ) -> frozenset[AgentCapability]:
        if not value:
            msg = "PluginMetadata must declare at least one supported capability"
            raise ValueError(msg)
        return value


@runtime_checkable
class OrchestratorPlugin(Protocol):
    """Abstract interface for orchestrator plugins.

    A plugin wraps an agent runtime (OpenCode, DeepSeek Harness, etc.)
    and exposes a uniform API to the ADLC control plane:

    1. plan(intent) → ExecutionPlan: produce a DAG of steps
    2. execute(plan, context) → ExecutionResult: run the plan
    3. reflect(result) → ReflectionReport: post-execution analysis

    The control plane handles scheduling, retry, approval, and
    persistence. The plugin only handles planning and execution.
    """

    @property
    def metadata(self) -> PluginMetadata:
        """Return static metadata about this plugin."""
        ...

    @abstractmethod
    async def plan(self, intent: Intent) -> ExecutionPlan:
        """Produce an execution plan for the given intent.

        The plan is a DAG of steps. The plugin decides which steps
        are needed and in what order. The control plane will
        schedule and dispatch the steps.
        """
        ...

    @abstractmethod
    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute the plan and return the result.

        The plugin is responsible for invoking the agent runtime
        for each step. The control plane provides context (memory,
        sandbox, etc.) via the context dict.
        """
        ...

    @abstractmethod
    async def reflect(self, result: ExecutionResult) -> ReflectionReport:
        """Analyze the execution result and produce a reflection.

        The reflection is used to update agent trust scores and
        improve future planning.
        """
        ...


__all__ = [
    "ExecutionPlan",
    "ExecutionResult",
    "Intent",
    "IntentType",
    "OrchestratorPlugin",
    "PlanStep",
    "PluginMetadata",
    "ReflectionReport",
    "StepResult",
]

"""Resource Manager — capability schema and registry.

Defines the taxonomy of agent capabilities, the requirement model for
tasks, and the registry that maps agent IDs to their capability profiles.

This module is additive: existing package authorization in
packages/access.py continues to work unchanged. The Resource Manager
extends it with capability-based allocation and least-privilege grants.
"""

from __future__ import annotations

from enum import Enum
from threading import RLock
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentCapability(str, Enum):
    """Stable taxonomy of agent capabilities.

    Each capability represents a distinct class of work an agent can
    perform. Capabilities are coarse-grained on purpose: fine-grained
    permissions are handled by PrivilegeGrant (see privileges.py).
    """

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TEST_RUNNER = "test_runner"
    SECURITY_SCAN = "security_scan"
    CONTENT_WRITING = "content_writing"
    PLANNING = "planning"
    REFLECTION = "reflection"
    ORCHESTRATION = "orchestration"


class CostTier(str, Enum):
    """Relative cost tier for an agent.

    Used by allocation policies to balance cost vs. quality. The actual
    cost in USD/token is provider-specific; this is a coarse label.
    """

    CHEAP = "cheap"
    MEDIUM = "medium"
    EXPENSIVE = "expensive"


class CapabilityRequirement(BaseModel):
    """Declared capabilities needed to execute a task.

    A task may require multiple capabilities (e.g. code_generation AND
    test_runner). The Resource Manager selects an agent that satisfies
    ALL required capabilities.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_capabilities: frozenset[AgentCapability] = Field(
        default_factory=frozenset,
        description="All capabilities the selected agent must have.",
    )
    preferred_capabilities: frozenset[AgentCapability] = Field(
        default_factory=frozenset,
        description="Nice-to-have capabilities that improve selection score.",
    )
    max_cost_tier: CostTier | None = Field(
        default=None,
        description="Maximum acceptable cost tier; None means no limit.",
    )
    min_trust_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum trust score (0.0–1.0) the agent must have.",
    )
    task_id: UUID | None = Field(
        default=None,
        description="Optional task ID for traceability.",
    )


class AgentProfile(BaseModel):
    """Static profile of an agent registered with the Resource Manager.

    Trust score is updated dynamically by the AgentTrustScore module
    (see Phase 2 follow-up). For now, it is a static field on the
    profile.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=256)
    capabilities: frozenset[AgentCapability]
    cost_tier: CostTier = CostTier.MEDIUM
    trust_score: float = Field(default=0.5, ge=0.0, le=1.0)
    enabled: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("capabilities")
    @classmethod
    def _require_non_empty_capabilities(cls, value: frozenset[AgentCapability]) -> frozenset[AgentCapability]:
        if not value:
            msg = "AgentProfile must declare at least one capability"
            raise ValueError(msg)
        return value


class AllocationDecision(BaseModel):
    """Result of a Resource Manager allocation request.

    Contains the selected agent plus the privilege grant that should
    be applied for the task execution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: UUID
    agent_id: str
    profile: AgentProfile
    granted_capabilities: frozenset[AgentCapability]
    policy_id: str
    score: float = Field(ge=0.0, description="Selection score from the policy.")
    rationale: str = Field(default="", description="Human-readable selection reason.")


@runtime_checkable
class CapabilityRegistry(Protocol):
    """Registry port for agent profiles."""

    def register(self, profile: AgentProfile) -> None:
        """Add or replace an agent profile."""
        ...

    def unregister(self, agent_id: str) -> None:
        """Remove an agent profile."""
        ...

    def get(self, agent_id: str) -> AgentProfile | None:
        """Return one agent profile by ID, or None if absent."""
        ...

    def list_enabled(self) -> tuple[AgentProfile, ...]:
        """Return all enabled agent profiles."""
        ...

    def find_by_capability(
        self,
        capability: AgentCapability,
        *,
        enabled_only: bool = True,
    ) -> tuple[AgentProfile, ...]:
        """Return all agents that have the given capability."""
        ...


class InMemoryCapabilityRegistry:
    """Thread-safe in-memory capability registry.

    Suitable for tests and single-process deployments. For multi-process
    or durable storage, swap with a SQL-backed implementation.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        self._lock = RLock()

    def register(self, profile: AgentProfile) -> None:
        with self._lock:
            self._profiles[profile.agent_id] = profile

    def unregister(self, agent_id: str) -> None:
        with self._lock:
            self._profiles.pop(agent_id, None)

    def get(self, agent_id: str) -> AgentProfile | None:
        with self._lock:
            return self._profiles.get(agent_id)

    def list_enabled(self) -> tuple[AgentProfile, ...]:
        with self._lock:
            return tuple(p for p in self._profiles.values() if p.enabled)

    def find_by_capability(
        self,
        capability: AgentCapability,
        *,
        enabled_only: bool = True,
    ) -> tuple[AgentProfile, ...]:
        with self._lock:
            results = []
            for profile in self._profiles.values():
                if enabled_only and not profile.enabled:
                    continue
                if capability in profile.capabilities:
                    results.append(profile)
            return tuple(results)


__all__ = [
    "AgentCapability",
    "AgentProfile",
    "AllocationDecision",
    "CapabilityRegistry",
    "CapabilityRequirement",
    "CostTier",
    "InMemoryCapabilityRegistry",
]

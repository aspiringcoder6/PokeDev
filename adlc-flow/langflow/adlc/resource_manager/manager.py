"""Resource Manager — high-level facade.

Composes a CapabilityRegistry, an AllocationPolicy, and a
PrivilegeCalculator to provide a single entry point for allocating
agents to tasks with least-privilege grants.
"""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from langflow.adlc.resource_manager.capabilities import (
    AgentProfile,
    AllocationDecision,
    CapabilityRegistry,
    CapabilityRequirement,
    InMemoryCapabilityRegistry,
)
from langflow.adlc.resource_manager.policies import (
    AllocationPolicy,
    BalancedPolicy,
)
from langflow.adlc.resource_manager.privileges import (
    PrivilegeCalculator,
    PrivilegeGrant,
)


class NoEligibleAgentError(RuntimeError):
    """Raised when no registered agent satisfies a requirement."""

    def __init__(self, requirement: CapabilityRequirement) -> None:
        super().__init__(
            f"No enabled agent satisfies requirement: {requirement.required_capabilities}"
        )
        self.requirement = requirement


class ResourceManager:
    """High-level facade for agent allocation and privilege grants.

    Typical usage:
        manager = ResourceManager()
        manager.register_agent(AgentProfile(...))
        decision = manager.allocate(requirement)
        # decision.granted_capabilities is the least-privilege set
        # decision.profile is the selected agent
    """

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        policy: AllocationPolicy | None = None,
        calculator: PrivilegeCalculator | None = None,
    ) -> None:
        self._registry: CapabilityRegistry = registry or InMemoryCapabilityRegistry()
        self._policy: AllocationPolicy = policy or BalancedPolicy()
        self._calculator: PrivilegeCalculator = calculator or PrivilegeCalculator()
        self._active_grants: dict[UUID, PrivilegeGrant] = {}
        self._lock = RLock()

    @property
    def registry(self) -> CapabilityRegistry:
        return self._registry

    @property
    def policy(self) -> AllocationPolicy:
        return self._policy

    def register_agent(self, profile: AgentProfile) -> None:
        """Add or replace an agent profile in the registry."""
        self._registry.register(profile)

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent profile from the registry."""
        self._registry.unregister(agent_id)

    def allocate(self, requirement: CapabilityRequirement) -> AllocationDecision:
        """Select the best agent for the requirement and issue a grant.

        Raises NoEligibleAgentError if no enabled agent satisfies the
        hard requirements (required capabilities, min trust, max cost).
        """
        candidates = self._registry.list_enabled()
        scored: list[tuple[float, AgentProfile]] = []
        for profile in candidates:
            score = self._policy.score(profile, requirement)
            if score > 0.0:
                scored.append((score, profile))

        if not scored:
            raise NoEligibleAgentError(requirement)

        # Pick the highest-scoring candidate. For RoundRobinPolicy, rotate
        # among tied candidates; otherwise break ties by agent_id for
        # determinism.
        from langflow.adlc.resource_manager.policies import RoundRobinPolicy

        if isinstance(self._policy, RoundRobinPolicy):
            # All eligible candidates have the same score (1.0); rotate.
            idx = self._policy.next_index(len(scored))
            best_score, best_profile = scored[idx]
        else:
            scored.sort(key=lambda item: (-item[0], item[1].agent_id))
            best_score, best_profile = scored[0]

        grant = self._calculator.compute_grant(
            best_profile.agent_id, requirement
        )
        with self._lock:
            self._active_grants[grant.grant_id] = grant

        rationale = self._build_rationale(best_profile, requirement, best_score)
        return AllocationDecision(
            grant_id=grant.grant_id,
            agent_id=best_profile.agent_id,
            profile=best_profile,
            granted_capabilities=grant.granted_capabilities,
            policy_id=self._policy.policy_id,
            score=best_score,
            rationale=rationale,
        )

    def revoke(self, grant_id: UUID) -> None:
        """Revoke a previously issued grant.

        Idempotent: revoking an already-revoked or unknown grant is a
        no-op.
        """
        with self._lock:
            grant = self._active_grants.get(grant_id)
            if grant is None:
                return
            self._active_grants[grant_id] = grant.model_copy(update={"revoked": True})

    def get_grant(self, grant_id: UUID) -> PrivilegeGrant | None:
        """Return the current state of a grant."""
        with self._lock:
            return self._active_grants.get(grant_id)

    def active_grant_count(self) -> int:
        """Return the number of non-revoked, non-expired grants."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        with self._lock:
            return sum(
                1
                for g in self._active_grants.values()
                if not g.revoked and g.expires_at > now
            )

    @staticmethod
    def _build_rationale(
        profile: AgentProfile,
        requirement: CapabilityRequirement,
        score: float,
    ) -> str:
        caps = ", ".join(sorted(c.value for c in profile.capabilities))
        return (
            f"Selected {profile.agent_id} (score={score:.2f}, "
            f"cost={profile.cost_tier.value}, trust={profile.trust_score:.2f}) "
            f"with capabilities: {caps}"
        )


__all__ = [
    "NoEligibleAgentError",
    "ResourceManager",
]

"""Resource Manager — allocation policies.

Defines the AllocationPolicy Protocol and built-in implementations:
- LeastCostPolicy: pick the cheapest agent that satisfies the requirement
- HighestTrustPolicy: pick the agent with the highest trust score
- BalancedPolicy: weighted combination of cost and trust
- RoundRobinPolicy: rotate through eligible agents (for testing)

Each policy returns a score in [0.0, 1.0] for each candidate; the
Resource Manager picks the highest-scoring candidate.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langflow.adlc.resource_manager.capabilities import (
    AgentProfile,
    CapabilityRequirement,
    CostTier,
)


@runtime_checkable
class AllocationPolicy(Protocol):
    """Policy port for selecting among eligible agents."""

    @property
    def policy_id(self) -> str:
        """Stable identifier for this policy (e.g. 'least-cost-v1')."""
        ...

    def score(
        self,
        profile: AgentProfile,
        requirement: CapabilityRequirement,
    ) -> float:
        """Return a score in [0.0, 1.0] for the candidate.

        Higher is better. The Resource Manager picks the highest score.
        Return 0.0 to disqualify a candidate.
        """
        ...


# Cost tier ordering: cheaper < medium < expensive.
_COST_TIER_ORDER = {CostTier.CHEAP: 0, CostTier.MEDIUM: 1, CostTier.EXPENSIVE: 2}


def _cost_tier_rank(tier: CostTier) -> int:
    return _COST_TIER_ORDER[tier]


def _satisfies_requirement(
    profile: AgentProfile, requirement: CapabilityRequirement
) -> bool:
    """Return whether the profile satisfies the hard requirements."""
    if not requirement.required_capabilities.issubset(profile.capabilities):
        return False
    if profile.trust_score < requirement.min_trust_score:
        return False
    if (
        requirement.max_cost_tier is not None
        and _cost_tier_rank(profile.cost_tier)
        > _cost_tier_rank(requirement.max_cost_tier)
    ):
        return False
    return True


class LeastCostPolicy:
    """Pick the cheapest agent that satisfies the requirement.

    Score = 1.0 - (cost_tier_rank / 2.0), so CHEAP=1.0, MEDIUM=0.5,
    EXPENSIVE=0.0. Trust score is ignored.
    """

    @property
    def policy_id(self) -> str:
        return "least-cost-v1"

    def score(
        self,
        profile: AgentProfile,
        requirement: CapabilityRequirement,
    ) -> float:
        if not _satisfies_requirement(profile, requirement):
            return 0.0
        return 1.0 - (_cost_tier_rank(profile.cost_tier) / 2.0)


class HighestTrustPolicy:
    """Pick the agent with the highest trust score.

    Score = trust_score directly. Cost is ignored.
    """

    @property
    def policy_id(self) -> str:
        return "highest-trust-v1"

    def score(
        self,
        profile: AgentProfile,
        requirement: CapabilityRequirement,
    ) -> float:
        if not _satisfies_requirement(profile, requirement):
            return 0.0
        return profile.trust_score


class BalancedPolicy:
    """Weighted combination of cost and trust.

    Score = (1 - cost_weight) * trust_score + cost_weight * (1 - cost_rank/2)
    Default weights: 0.5 trust, 0.5 cost.
    """

    def __init__(self, trust_weight: float = 0.5, cost_weight: float = 0.5) -> None:
        total = trust_weight + cost_weight
        if total <= 0:
            msg = "trust_weight + cost_weight must be positive"
            raise ValueError(msg)
        self._trust_weight = trust_weight / total
        self._cost_weight = cost_weight / total

    @property
    def policy_id(self) -> str:
        return "balanced-v1"

    def score(
        self,
        profile: AgentProfile,
        requirement: CapabilityRequirement,
    ) -> float:
        if not _satisfies_requirement(profile, requirement):
            return 0.0
        cost_score = 1.0 - (_cost_tier_rank(profile.cost_tier) / 2.0)
        return (
            self._trust_weight * profile.trust_score
            + self._cost_weight * cost_score
        )


class RoundRobinPolicy:
    """Rotate through eligible agents.

    Score is constant (1.0) for all eligible candidates; the Resource
    Manager's rotation counter breaks ties. Useful for testing and
    for load distribution across identical agents.
    """

    def __init__(self) -> None:
        self._counter = 0

    @property
    def policy_id(self) -> str:
        return "round-robin-v1"

    def score(
        self,
        profile: AgentProfile,
        requirement: CapabilityRequirement,
    ) -> float:
        if not _satisfies_requirement(profile, requirement):
            return 0.0
        return 1.0

    def next_index(self, count: int) -> int:
        """Return the next index in the rotation; advances the counter."""
        if count <= 0:
            msg = "count must be positive"
            raise ValueError(msg)
        idx = self._counter % count
        self._counter += 1
        return idx


__all__ = [
    "AllocationPolicy",
    "BalancedPolicy",
    "HighestTrustPolicy",
    "LeastCostPolicy",
    "RoundRobinPolicy",
]

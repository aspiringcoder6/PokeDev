"""Unit tests for the Resource Manager module."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from langflow.adlc.resource_manager import (
    AgentCapability,
    AgentProfile,
    AllocationDecision,
    BalancedPolicy,
    CapabilityRequirement,
    CostTier,
    HighestTrustPolicy,
    InMemoryCapabilityRegistry,
    LeastCostPolicy,
    NoEligibleAgentError,
    PrivilegeCalculator,
    PrivilegeGrant,
    ResourceManager,
    RoundRobinPolicy,
)


def _make_profile(
    agent_id: str,
    capabilities: frozenset[AgentCapability],
    *,
    cost_tier: CostTier = CostTier.MEDIUM,
    trust_score: float = 0.5,
    enabled: bool = True,
) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        display_name=agent_id.replace("-", " ").title(),
        capabilities=capabilities,
        cost_tier=cost_tier,
        trust_score=trust_score,
        enabled=enabled,
    )


class TestAgentProfile:
    def test_profile_requires_capabilities(self):
        with pytest.raises(ValueError):
            AgentProfile(
                agent_id="x",
                display_name="X",
                capabilities=frozenset(),
            )

    def test_profile_is_frozen(self):
        profile = _make_profile("a", frozenset({AgentCapability.CODE_GENERATION}))
        with pytest.raises(Exception):
            profile.trust_score = 0.9  # type: ignore[misc]


class TestInMemoryCapabilityRegistry:
    def test_register_and_get(self):
        registry = InMemoryCapabilityRegistry()
        profile = _make_profile("a", frozenset({AgentCapability.CODE_GENERATION}))
        registry.register(profile)
        assert registry.get("a") == profile

    def test_unregister(self):
        registry = InMemoryCapabilityRegistry()
        profile = _make_profile("a", frozenset({AgentCapability.CODE_GENERATION}))
        registry.register(profile)
        registry.unregister("a")
        assert registry.get("a") is None

    def test_list_enabled_excludes_disabled(self):
        registry = InMemoryCapabilityRegistry()
        registry.register(_make_profile("a", frozenset({AgentCapability.CODE_GENERATION})))
        registry.register(
            _make_profile("b", frozenset({AgentCapability.CODE_GENERATION}), enabled=False)
        )
        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].agent_id == "a"

    def test_find_by_capability(self):
        registry = InMemoryCapabilityRegistry()
        registry.register(_make_profile("a", frozenset({AgentCapability.CODE_GENERATION})))
        registry.register(_make_profile("b", frozenset({AgentCapability.TEST_RUNNER})))
        registry.register(
            _make_profile("c", frozenset({AgentCapability.CODE_GENERATION, AgentCapability.TEST_RUNNER}))
        )
        results = registry.find_by_capability(AgentCapability.CODE_GENERATION)
        assert {p.agent_id for p in results} == {"a", "c"}


class TestPolicies:
    def test_least_cost_prefers_cheap(self):
        policy = LeastCostPolicy()
        cheap = _make_profile("cheap", frozenset({AgentCapability.CODE_GENERATION}), cost_tier=CostTier.CHEAP)
        expensive = _make_profile("exp", frozenset({AgentCapability.CODE_GENERATION}), cost_tier=CostTier.EXPENSIVE)
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        assert policy.score(cheap, req) > policy.score(expensive, req)

    def test_highest_trust_prefers_high_trust(self):
        policy = HighestTrustPolicy()
        low = _make_profile("low", frozenset({AgentCapability.CODE_GENERATION}), trust_score=0.3)
        high = _make_profile("high", frozenset({AgentCapability.CODE_GENERATION}), trust_score=0.9)
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        assert policy.score(high, req) > policy.score(low, req)

    def test_balanced_combines_cost_and_trust(self):
        policy = BalancedPolicy(trust_weight=0.5, cost_weight=0.5)
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        # Cheap + low trust vs expensive + high trust: balanced should be close.
        cheap_low = _make_profile("cl", frozenset({AgentCapability.CODE_GENERATION}), cost_tier=CostTier.CHEAP, trust_score=0.3)
        exp_high = _make_profile("eh", frozenset({AgentCapability.CODE_GENERATION}), cost_tier=CostTier.EXPENSIVE, trust_score=0.9)
        s1 = policy.score(cheap_low, req)
        s2 = policy.score(exp_high, req)
        # Both should be around 0.65 (0.5*0.3 + 0.5*1.0 = 0.65; 0.5*0.9 + 0.5*0.0 = 0.45)
        assert s1 > s2

    def test_policy_disqualifies_missing_capability(self):
        policy = LeastCostPolicy()
        profile = _make_profile("a", frozenset({AgentCapability.TEST_RUNNER}))
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        assert policy.score(profile, req) == 0.0

    def test_policy_disqualifies_low_trust(self):
        policy = LeastCostPolicy()
        profile = _make_profile("a", frozenset({AgentCapability.CODE_GENERATION}), trust_score=0.2)
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            min_trust_score=0.5,
        )
        assert policy.score(profile, req) == 0.0

    def test_policy_disqualifies_over_cost(self):
        policy = LeastCostPolicy()
        profile = _make_profile("a", frozenset({AgentCapability.CODE_GENERATION}), cost_tier=CostTier.EXPENSIVE)
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            max_cost_tier=CostTier.CHEAP,
        )
        assert policy.score(profile, req) == 0.0

    def test_round_robin_rotates(self):
        policy = RoundRobinPolicy()
        assert policy.next_index(3) == 0
        assert policy.next_index(3) == 1
        assert policy.next_index(3) == 2
        assert policy.next_index(3) == 0  # wraps


class TestPrivilegeCalculator:
    def test_compute_grant_covers_only_required(self):
        calc = PrivilegeCalculator()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            preferred_capabilities=frozenset({AgentCapability.TEST_RUNNER}),
        )
        grant = calc.compute_grant("agent-a", req)
        assert grant.agent_id == "agent-a"
        assert grant.granted_capabilities == frozenset({AgentCapability.CODE_GENERATION})
        assert not grant.covers(AgentCapability.TEST_RUNNER)

    def test_grant_has_ttl(self):
        calc = PrivilegeCalculator(default_ttl=timedelta(minutes=30))
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        grant = calc.compute_grant("a", req)
        assert grant.expires_at > grant.issued_at
        assert (grant.expires_at - grant.issued_at) == timedelta(minutes=30)

    def test_grant_is_valid_until_expired(self):
        calc = PrivilegeCalculator(default_ttl=timedelta(seconds=1))
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        grant = calc.compute_grant("a", req)
        assert grant.is_valid()

    def test_extend_grant_adds_capabilities(self):
        calc = PrivilegeCalculator()
        req = CapabilityRequirement(required_capabilities=frozenset({AgentCapability.CODE_GENERATION}))
        grant = calc.compute_grant("a", req)
        extended = calc.extend_grant(
            grant, frozenset({AgentCapability.TEST_RUNNER})
        )
        assert extended.granted_capabilities == frozenset(
            {AgentCapability.CODE_GENERATION, AgentCapability.TEST_RUNNER}
        )
        assert extended.grant_id != grant.grant_id  # new grant

    def test_rejects_non_positive_ttl(self):
        with pytest.raises(ValueError):
            PrivilegeCalculator(default_ttl=timedelta(0))


class TestResourceManager:
    def _build_manager(self) -> ResourceManager:
        manager = ResourceManager()
        manager.register_agent(
            _make_profile(
                "code-gen-cheap",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.CHEAP,
                trust_score=0.6,
            )
        )
        manager.register_agent(
            _make_profile(
                "code-gen-expensive",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.EXPENSIVE,
                trust_score=0.9,
            )
        )
        manager.register_agent(
            _make_profile(
                "test-runner",
                frozenset({AgentCapability.TEST_RUNNER}),
                cost_tier=CostTier.MEDIUM,
                trust_score=0.7,
            )
        )
        manager.register_agent(
            _make_profile(
                "full-stack",
                frozenset(
                    {
                        AgentCapability.CODE_GENERATION,
                        AgentCapability.TEST_RUNNER,
                        AgentCapability.CODE_REVIEW,
                    }
                ),
                cost_tier=CostTier.EXPENSIVE,
                trust_score=0.95,
            )
        )
        return manager

    def test_allocate_picks_eligible_agent(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        assert decision.agent_id in {"code-gen-cheap", "code-gen-expensive", "full-stack"}
        assert AgentCapability.CODE_GENERATION in decision.granted_capabilities

    def test_allocate_raises_when_no_eligible(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.SECURITY_SCAN})
        )
        with pytest.raises(NoEligibleAgentError):
            manager.allocate(req)

    def test_allocate_respects_min_trust(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            min_trust_score=0.85,
        )
        decision = manager.allocate(req)
        # Only code-gen-expensive (0.9) and full-stack (0.95) qualify.
        assert decision.agent_id in {"code-gen-expensive", "full-stack"}

    def test_allocate_respects_max_cost(self):
        manager = ResourceManager(policy=LeastCostPolicy())
        manager.register_agent(
            _make_profile(
                "cheap",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.CHEAP,
            )
        )
        manager.register_agent(
            _make_profile(
                "expensive",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.EXPENSIVE,
            )
        )
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            max_cost_tier=CostTier.CHEAP,
        )
        decision = manager.allocate(req)
        assert decision.agent_id == "cheap"

    def test_allocate_uses_balanced_policy_by_default(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        assert decision.policy_id == "balanced-v1"

    def test_allocate_uses_custom_policy(self):
        manager = ResourceManager(policy=HighestTrustPolicy())
        manager.register_agent(
            _make_profile(
                "low-trust",
                frozenset({AgentCapability.CODE_GENERATION}),
                trust_score=0.3,
            )
        )
        manager.register_agent(
            _make_profile(
                "high-trust",
                frozenset({AgentCapability.CODE_GENERATION}),
                trust_score=0.9,
            )
        )
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        assert decision.agent_id == "high-trust"
        assert decision.policy_id == "highest-trust-v1"

    def test_revoke_makes_grant_invalid(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        grant = manager.get_grant(decision.grant_id)  # type: ignore[arg-type]
        assert grant is not None
        assert grant.is_valid()
        manager.revoke(decision.grant_id)  # type: ignore[arg-type]
        revoked = manager.get_grant(decision.grant_id)  # type: ignore[arg-type]
        assert revoked is not None
        assert not revoked.is_valid()

    def test_revoke_unknown_grant_is_noop(self):
        manager = self._build_manager()
        manager.revoke(uuid4())  # should not raise

    def test_active_grant_count(self):
        manager = self._build_manager()
        assert manager.active_grant_count() == 0
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        manager.allocate(req)
        assert manager.active_grant_count() == 1

    def test_disabled_agent_not_considered(self):
        manager = ResourceManager()
        manager.register_agent(
            _make_profile(
                "disabled",
                frozenset({AgentCapability.CODE_GENERATION}),
                enabled=False,
            )
        )
        manager.register_agent(
            _make_profile(
                "enabled",
                frozenset({AgentCapability.CODE_GENERATION}),
                enabled=True,
            )
        )
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        assert decision.agent_id == "enabled"

    def test_decision_includes_rationale(self):
        manager = self._build_manager()
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        decision = manager.allocate(req)
        assert decision.agent_id in decision.rationale
        assert "score=" in decision.rationale

"""Integration tests for the Resource Manager.

Verifies:
1. End-to-end allocation flow with multiple agents and policies
2. Integration with existing package authorization (packages/access.py)
3. Backward compatibility: existing flows that don't use Resource Manager still work
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from langflow.adlc.resource_manager import (
    AgentCapability,
    AgentProfile,
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
from langflow.adlc.packages.access import (
    AllowAllPackageAccessPolicy,
    InMemoryPackageAccessPolicy,
)


def _make_profile(
    agent_id: str,
    capabilities: frozenset[AgentCapability],
    *,
    cost_tier: CostTier = CostTier.MEDIUM,
    trust_score: float = 0.5,
) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        display_name=agent_id.replace("-", " ").title(),
        capabilities=capabilities,
        cost_tier=cost_tier,
        trust_score=trust_score,
    )


class TestEndToEndAllocation:
    def test_full_workflow_with_balanced_policy(self):
        """Simulate a full task allocation workflow."""
        manager = ResourceManager(policy=BalancedPolicy(trust_weight=0.9, cost_weight=0.1))

        # Register a diverse set of agents.
        manager.register_agent(
            _make_profile(
                "junior-dev",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.CHEAP,
                trust_score=0.5,
            )
        )
        manager.register_agent(
            _make_profile(
                "senior-dev",
                frozenset({AgentCapability.CODE_GENERATION, AgentCapability.CODE_REVIEW}),
                cost_tier=CostTier.EXPENSIVE,
                trust_score=0.9,
            )
        )
        manager.register_agent(
            _make_profile(
                "tester",
                frozenset({AgentCapability.TEST_RUNNER}),
                cost_tier=CostTier.MEDIUM,
                trust_score=0.7,
            )
        )

        # Task 1: code generation (balanced with trust_weight=0.9 picks senior-dev).
        req1 = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION}),
            task_id=uuid4(),
        )
        decision1 = manager.allocate(req1)
        # senior-dev: 0.9*0.9 + 0.1*0.0 = 0.81
        # junior-dev: 0.9*0.5 + 0.1*1.0 = 0.55
        assert decision1.agent_id == "senior-dev"
        assert decision1.policy_id == "balanced-v1"
        assert AgentCapability.CODE_GENERATION in decision1.granted_capabilities

        # Task 2: test running (only tester qualifies).
        req2 = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.TEST_RUNNER}),
            task_id=uuid4(),
        )
        decision2 = manager.allocate(req2)
        assert decision2.agent_id == "tester"

        # Task 3: security scan (no agent qualifies).
        req3 = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.SECURITY_SCAN}),
            task_id=uuid4(),
        )
        with pytest.raises(NoEligibleAgentError):
            manager.allocate(req3)

        # Verify grants are tracked.
        assert manager.active_grant_count() == 2

        # Revoke one grant.
        manager.revoke(decision1.grant_id)
        assert manager.active_grant_count() == 1

    def test_policy_switching(self):
        """Same registry, different policies produce different selections."""
        registry = InMemoryCapabilityRegistry()
        registry.register(
            _make_profile(
                "cheap-low-trust",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.CHEAP,
                trust_score=0.3,
            )
        )
        registry.register(
            _make_profile(
                "expensive-high-trust",
                frozenset({AgentCapability.CODE_GENERATION}),
                cost_tier=CostTier.EXPENSIVE,
                trust_score=0.9,
            )
        )

        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )

        # LeastCostPolicy picks cheap.
        manager_lc = ResourceManager(registry=registry, policy=LeastCostPolicy())
        assert manager_lc.allocate(req).agent_id == "cheap-low-trust"

        # HighestTrustPolicy picks expensive.
        manager_ht = ResourceManager(registry=registry, policy=HighestTrustPolicy())
        assert manager_ht.allocate(req).agent_id == "expensive-high-trust"

    def test_round_robin_load_distribution(self):
        """RoundRobinPolicy distributes load across identical agents."""
        registry = InMemoryCapabilityRegistry()
        for i in range(3):
            registry.register(
                _make_profile(
                    f"agent-{i}",
                    frozenset({AgentCapability.CODE_GENERATION}),
                    cost_tier=CostTier.MEDIUM,
                    trust_score=0.5,
                )
            )

        policy = RoundRobinPolicy()
        manager = ResourceManager(registry=registry, policy=policy)
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )

        # First allocation: index 0.
        d1 = manager.allocate(req)
        # Second: index 1.
        d2 = manager.allocate(req)
        # Third: index 2.
        d3 = manager.allocate(req)
        # Fourth: wraps to index 0.
        d4 = manager.allocate(req)

        # All should be different agents (or wrap correctly).
        assert len({d1.agent_id, d2.agent_id, d3.agent_id}) == 3
        assert d4.agent_id == d1.agent_id


class TestPrivilegeLifecycle:
    def test_grant_expires_after_ttl(self):
        calc = PrivilegeCalculator(default_ttl=timedelta(milliseconds=10))
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        grant = calc.compute_grant("a", req)
        assert grant.is_valid()
        import time
        time.sleep(0.02)
        assert not grant.is_valid()

    def test_extend_grant_preserves_expiry(self):
        calc = PrivilegeCalculator(default_ttl=timedelta(hours=1))
        req = CapabilityRequirement(
            required_capabilities=frozenset({AgentCapability.CODE_GENERATION})
        )
        original = calc.compute_grant("a", req)
        extended = calc.extend_grant(
            original, frozenset({AgentCapability.TEST_RUNNER})
        )
        assert extended.expires_at == original.expires_at
        assert extended.granted_capabilities == frozenset(
            {AgentCapability.CODE_GENERATION, AgentCapability.TEST_RUNNER}
        )


class TestBackwardCompatibility:
    def test_package_access_policy_still_works(self):
        """Existing package authorization is unaffected by Resource Manager."""
        policy = AllowAllPackageAccessPolicy()
        # Should not raise.
        policy.ensure_plan_authorized("any-subject", None)  # type: ignore[arg-type]

    def test_in_memory_package_access_policy_still_works(self):
        """InMemoryPackageAccessPolicy continues to work."""
        from langflow.adlc.blueprints.models import PackageReference

        policy = InMemoryPackageAccessPolicy(
            default_visible_packages=(),
            default_authorized_references=(),
        )
        ref = PackageReference(package_id="test", version="1.0.0")
        # No visible packages, so this should raise.
        with pytest.raises(Exception):
            policy.ensure_package_visible("any", ref)

    def test_resource_manager_does_not_affect_package_authorization(self):
        """Resource Manager and package authorization are independent."""
        manager = ResourceManager()
        manager.register_agent(
            _make_profile(
                "a",
                frozenset({AgentCapability.CODE_GENERATION}),
            )
        )
        # Package policy is separate.
        package_policy = AllowAllPackageAccessPolicy()
        # Both can coexist.
        assert manager.registry.get("a") is not None
        package_policy.ensure_plan_authorized("any", None)  # type: ignore[arg-type]

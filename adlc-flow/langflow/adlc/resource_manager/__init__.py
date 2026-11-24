"""Resource Manager — capability-based agent allocation with least-privilege grants.

The Resource Manager addresses the "Phân bổ Agent mù quáng" problem
from the ADLC slide: instead of giving an LLM full control over which
agent to call, the Resource Manager selects agents based on a declared
capability table and issues least-privilege grants for each task.

Public API:
- AgentCapability, CostTier, CapabilityRequirement, AgentProfile, AllocationDecision
- CapabilityRegistry (Protocol), InMemoryCapabilityRegistry
- AllocationPolicy (Protocol), LeastCostPolicy, HighestTrustPolicy, BalancedPolicy, RoundRobinPolicy
- PrivilegeGrant, PrivilegeCalculator
- ResourceManager, NoEligibleAgentError
"""

from langflow.adlc.resource_manager.capabilities import (
    AgentCapability,
    AgentProfile,
    AllocationDecision,
    CapabilityRegistry,
    CapabilityRequirement,
    CostTier,
    InMemoryCapabilityRegistry,
)
from langflow.adlc.resource_manager.manager import (
    NoEligibleAgentError,
    ResourceManager,
)
from langflow.adlc.resource_manager.policies import (
    AllocationPolicy,
    BalancedPolicy,
    HighestTrustPolicy,
    LeastCostPolicy,
    RoundRobinPolicy,
)
from langflow.adlc.resource_manager.privileges import (
    PrivilegeCalculator,
    PrivilegeGrant,
)

__all__ = [
    # Capabilities
    "AgentCapability",
    "AgentProfile",
    "AllocationDecision",
    "CapabilityRegistry",
    "CapabilityRequirement",
    "CostTier",
    "InMemoryCapabilityRegistry",
    # Policies
    "AllocationPolicy",
    "BalancedPolicy",
    "HighestTrustPolicy",
    "LeastCostPolicy",
    "RoundRobinPolicy",
    # Privileges
    "PrivilegeCalculator",
    "PrivilegeGrant",
    # Manager
    "NoEligibleAgentError",
    "ResourceManager",
]

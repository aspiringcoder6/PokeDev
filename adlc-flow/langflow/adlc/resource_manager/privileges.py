"""Resource Manager — least-privilege grants.

Computes the minimum set of capabilities an agent needs to execute a
task, and produces a PrivilegeGrant that can be enforced at execution
time.

This module is additive: existing package authorization in
packages/access.py continues to work. PrivilegeGrant is a higher-level
abstraction that composes with package-level authorization.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.resource_manager.capabilities import (
    AgentCapability,
    CapabilityRequirement,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PrivilegeGrant(BaseModel):
    """A time-bounded grant of capabilities to an agent for one task.

    The grant is the contract between the Resource Manager and the
    execution layer: the agent may only use the granted capabilities
    for the duration of the task.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: UUID = Field(default_factory=uuid4)
    agent_id: str = Field(min_length=1, max_length=128)
    task_id: UUID | None = None
    granted_capabilities: frozenset[AgentCapability]
    issued_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime
    revoked: bool = False

    def is_valid(self, now: datetime | None = None) -> bool:
        """Return whether the grant is still valid at the given time."""
        if self.revoked:
            return False
        check_at = now or _utc_now()
        return check_at < self.expires_at

    def covers(self, capability: AgentCapability) -> bool:
        """Return whether the grant covers the given capability."""
        return capability in self.granted_capabilities


class PrivilegeCalculator:
    """Computes least-privilege grants from task requirements.

    The default policy grants exactly the required capabilities plus
    any preferred capabilities the agent already has. No implicit
    escalation: if a task needs CODE_REVIEW, the agent gets CODE_REVIEW
    and nothing else.
    """

    def __init__(self, default_ttl: timedelta = timedelta(hours=1)) -> None:
        if default_ttl <= timedelta(0):
            msg = "default_ttl must be positive"
            raise ValueError(msg)
        self._default_ttl = default_ttl

    def compute_grant(
        self,
        agent_id: str,
        requirement: CapabilityRequirement,
        *,
        ttl: timedelta | None = None,
    ) -> PrivilegeGrant:
        """Compute a least-privilege grant for the given requirement.

        The grant covers exactly the required capabilities. Preferred
        capabilities are NOT included by default — they are nice-to-have,
        not required. Callers can extend the grant if needed.
        """
        effective_ttl = ttl or self._default_ttl
        issued_at = _utc_now()
        return PrivilegeGrant(
            agent_id=agent_id,
            task_id=requirement.task_id,
            granted_capabilities=frozenset(requirement.required_capabilities),
            issued_at=issued_at,
            expires_at=issued_at + effective_ttl,
        )

    def extend_grant(
        self,
        grant: PrivilegeGrant,
        additional: frozenset[AgentCapability],
    ) -> PrivilegeGrant:
        """Return a new grant with additional capabilities added.

        The original grant is unchanged (frozen). The new grant has a
        fresh grant_id and the same expiry.
        """
        return PrivilegeGrant(
            grant_id=uuid4(),
            agent_id=grant.agent_id,
            task_id=grant.task_id,
            granted_capabilities=grant.granted_capabilities | additional,
            issued_at=_utc_now(),
            expires_at=grant.expires_at,
        )


__all__ = [
    "PrivilegeCalculator",
    "PrivilegeGrant",
]

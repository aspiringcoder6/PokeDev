"""Stable execution adapter interfaces used by the ADLC scheduler boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from langflow.adlc.models import TaskRequest, TaskResult, TaskRunStatus

StateChangeCallback = Callable[[TaskRunStatus, TaskResult | None], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SandboxSession:
    """Opaque sandbox allocation passed to an agent adapter."""

    session_id: str
    workspace_uri: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Resolved memory references and variables for one task attempt."""

    memory_refs: tuple[str, ...] = ()
    variables: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SandboxAdapter(Protocol):
    """Provision and release the isolated workspace used by a task attempt."""

    service_name: str

    async def open_session(self, request: TaskRequest) -> SandboxSession:
        """Provision a sandbox for the task attempt."""
        ...

    async def close_session(self, request: TaskRequest, session: SandboxSession) -> None:
        """Release resources associated with the task attempt."""
        ...


@runtime_checkable
class MemoryAdapter(Protocol):
    """Load task context and record the final result."""

    service_name: str

    async def load_context(self, request: TaskRequest) -> MemoryContext:
        """Resolve the references in a TaskRequest into scoped context."""
        ...

    async def record_result(self, request: TaskRequest, result: TaskResult) -> None:
        """Record a completed attempt for later retrieval."""
        ...


@runtime_checkable
class TestingAdapter(Protocol):
    """Evaluate or enrich an agent result before it becomes final."""

    service_name: str

    async def evaluate(self, request: TaskRequest, result: TaskResult) -> TaskResult:
        """Return the contract-shaped result accepted by the coordinator."""
        ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Perform task work using prepared sandbox and memory context."""

    service_name: str
    capabilities: tuple[str, ...]

    async def execute(
        self,
        request: TaskRequest,
        *,
        sandbox: SandboxSession,
        memory: MemoryContext,
    ) -> TaskResult:
        """Execute one task attempt and return a v0.1 TaskResult."""
        ...


@runtime_checkable
class TaskExecutor(Protocol):
    """The only execution port used directly by an ADLC scheduler."""

    service_name: str
    capabilities: tuple[str, ...]

    async def execute(self, request: TaskRequest, on_state_change: StateChangeCallback) -> TaskResult:
        """Execute one request and report RUNNING plus one terminal state."""
        ...


@dataclass(frozen=True, slots=True)
class AdapterBundle:
    """Concrete adapters composed behind the scheduler's TaskExecutor port."""

    sandbox: SandboxAdapter
    memory: MemoryAdapter
    testing: TestingAdapter
    agent: AgentAdapter

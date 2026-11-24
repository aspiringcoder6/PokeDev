"""Runtime state for :class:`PlanExecutor`.

The executor tracks the status of every subtask as it moves through the
DAG. These models are the single source of truth for "what is happening
right now" and are what the UI reads to render progress bars and
subtask lists.

State machine for a subtask::

    PENDING ──► READY ──► RUNNING ──► SUCCEEDED
                          │      ╲
                          │       ╲──► FAILED
                          │       ╲
                          │        ╲──► SKIPPED (dependency failed)
                          ╲
                           ╲──► CANCELLED

``READY`` is a transient state used internally by the executor to mark
subtasks whose dependencies are satisfied and that are waiting to be
dispatched in the next batch.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.models import ServiceError

if TYPE_CHECKING:
    from langflow.adlc.plan_models import PlanSpec, SubtaskSpec, TaskSpec


class SubtaskStatus(str, Enum):
    """Lifecycle status of a single subtask."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES = frozenset(
    {
        SubtaskStatus.SUCCEEDED,
        SubtaskStatus.FAILED,
        SubtaskStatus.SKIPPED,
        SubtaskStatus.CANCELLED,
    }
)


class SubtaskState(BaseModel):
    """Mutable runtime state for one subtask."""

    model_config = ConfigDict(extra="forbid")

    subtask_id: str
    task_id: str
    status: SubtaskStatus = SubtaskStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: ServiceError | None = None
    attempt_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES


class TaskState(BaseModel):
    """Aggregated state for one task (group of subtasks)."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    subtask_states: dict[str, SubtaskState] = Field(default_factory=dict)
    status: SubtaskStatus = SubtaskStatus.PENDING

    @property
    def total(self) -> int:
        return len(self.subtask_states)

    @property
    def succeeded(self) -> int:
        return sum(1 for s in self.subtask_states.values() if s.status is SubtaskStatus.SUCCEEDED)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.subtask_states.values() if s.status is SubtaskStatus.FAILED)

    @property
    def running(self) -> int:
        return sum(1 for s in self.subtask_states.values() if s.status is SubtaskStatus.RUNNING)

    @property
    def pending(self) -> int:
        return sum(
            1
            for s in self.subtask_states.values()
            if s.status in (SubtaskStatus.PENDING, SubtaskStatus.READY)
        )

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.subtask_states.values() if s.status is SubtaskStatus.SKIPPED)

    @property
    def is_terminal(self) -> bool:
        return all(s.is_terminal for s in self.subtask_states.values())


class PlanState(BaseModel):
    """Aggregated state for the whole plan."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    task_states: dict[str, TaskState] = Field(default_factory=dict)
    status: SubtaskStatus = SubtaskStatus.PENDING

    @property
    def total(self) -> int:
        return sum(t.total for t in self.task_states.values())

    @property
    def succeeded(self) -> int:
        return sum(t.succeeded for t in self.task_states.values())

    @property
    def failed(self) -> int:
        return sum(t.failed for t in self.task_states.values())

    @property
    def running(self) -> int:
        return sum(t.running for t in self.task_states.values())

    @property
    def pending(self) -> int:
        return sum(t.pending for t in self.task_states.values())

    @property
    def skipped(self) -> int:
        return sum(t.skipped for t in self.task_states.values())

    @property
    def is_terminal(self) -> bool:
        return all(t.is_terminal for t in self.task_states.values())

    def all_subtask_states(self) -> list[SubtaskState]:
        """Flatten all subtask states across all tasks."""
        return [s for t in self.task_states.values() for s in t.subtask_states.values()]


def initialize_plan_state(plan: PlanSpec, plan_id: str) -> PlanState:
    """Build the initial :class:`PlanState` for a plan.

    Every subtask starts as ``PENDING``. The executor will transition
    them to ``READY`` as their dependencies complete.
    """
    task_states: dict[str, TaskState] = {}
    for task in plan.tasks:
        subtask_states = {
            subtask.id: SubtaskState(
                subtask_id=subtask.id,
                task_id=task.id,
                status=SubtaskStatus.PENDING,
            )
            for subtask in task.subtasks
        }
        task_states[task.id] = TaskState(
            task_id=task.id,
            subtask_states=subtask_states,
            status=SubtaskStatus.PENDING,
        )
    return PlanState(plan_id=plan_id, task_states=task_states)


__all__ = [
    "PlanState",
    "SubtaskState",
    "SubtaskStatus",
    "TaskState",
    "initialize_plan_state",
]

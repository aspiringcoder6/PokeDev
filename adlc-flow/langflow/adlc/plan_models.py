"""Structured execution-plan schema for DAG-based task/subtask orchestration.

A :class:`PlanSpec` is the contract between the planner (DSH LLM) and the
executor. It expresses a directed acyclic graph of :class:`TaskSpec` nodes,
each of which fans out into a DAG of :class:`SubtaskSpec` leaves. Subtasks
are the unit of execution — each one is dispatched as an independent ADLC
task against the Harness server.

The schema is intentionally strict (``extra="forbid"``) so that malformed
LLM output is rejected at the boundary instead of silently corrupting the
execution graph.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PLAN_CONTRACT_VERSION = "0.1"

# Identifier pattern: lowercase letters, digits, dashes, dots, underscores.
# Allows hierarchical IDs like "task-1.sub-2".
NodeId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$"),
]
NonEmptyTitle = Annotated[str, Field(min_length=1, max_length=255)]
ObjectiveText = Annotated[str, Field(min_length=10, max_length=20_000)]


class SubtaskTrigger(str, Enum):
    """When a dependent subtask should run, relative to its dependency's outcome."""

    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"
    ON_COMPLETED = "on_completed"


class AggregationStrategy(str, Enum):
    """How a parent task combines its subtask outputs into a single result."""

    COLLECT = "collect"            # Concatenate outputs into a list.
    JOIN = "join"                  # Merge outputs into a single dict.
    FINALIZE_SUBTASK = "finalize"  # One designated subtask produces the final output.


class ClosedPlanModel(BaseModel):
    """Reject unknown fields on every public plan payload."""

    model_config = ConfigDict(extra="forbid")


class SubtaskSpec(ClosedPlanModel):
    """A leaf node in the execution DAG — the unit dispatched to the agent."""

    id: NodeId
    name: NonEmptyTitle
    description: str = ""
    objective: ObjectiveText
    dependencies: list[NodeId] = Field(default_factory=list)
    trigger: SubtaskTrigger = SubtaskTrigger.ON_SUCCESS
    timeout_seconds: float | None = Field(default=None, gt=0, le=86_400)
    expected_outputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _no_self_dependency(self) -> SubtaskSpec:
        if self.id in self.dependencies:
            msg = f"Subtask {self.id!r} cannot depend on itself."
            raise ValueError(msg)
        return self


class TaskSpec(ClosedPlanModel):
    """A logical grouping of subtasks. A task completes when its subtasks do."""

    id: NodeId
    name: NonEmptyTitle
    description: str = ""
    objective: ObjectiveText
    subtasks: list[SubtaskSpec] = Field(min_length=1)
    dependencies: list[NodeId] = Field(default_factory=list)
    aggregation: AggregationStrategy = AggregationStrategy.COLLECT
    finalize_subtask_id: NodeId | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_finalize_subtask(self) -> TaskSpec:
        if self.aggregation is not AggregationStrategy.FINALIZE_SUBTASK:
            return self
        if self.finalize_subtask_id is None:
            msg = (
                f"Task {self.id!r} uses aggregation='finalize' but "
                "finalize_subtask_id is not set."
            )
            raise ValueError(msg)
        ids = {s.id for s in self.subtasks}
        if self.finalize_subtask_id not in ids:
            msg = (
                f"Task {self.id!r} finalize_subtask_id={self.finalize_subtask_id!r} "
                "does not match any subtask in this task."
            )
            raise ValueError(msg)
        return self


class PlanSpec(ClosedPlanModel):
    """The top-level execution plan: a DAG of tasks, each containing subtasks."""

    schema_version: Literal["0.1"] = PLAN_CONTRACT_VERSION
    objective: NonEmptyTitle
    description: str = ""
    tasks: list[TaskSpec] = Field(min_length=1, max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> PlanSpec:
        seen: set[str] = set()
        for task in self.tasks:
            if task.id in seen:
                msg = f"Duplicate task id: {task.id!r}."
                raise ValueError(msg)
            seen.add(task.id)
            for subtask in task.subtasks:
                if subtask.id in seen:
                    msg = f"Duplicate subtask id: {subtask.id!r}."
                    raise ValueError(msg)
                seen.add(subtask.id)
        return self


__all__ = [
    "PLAN_CONTRACT_VERSION",
    "AggregationStrategy",
    "ClosedPlanModel",
    "NodeId",
    "NonEmptyTitle",
    "ObjectiveText",
    "PlanSpec",
    "SubtaskSpec",
    "SubtaskTrigger",
    "TaskSpec",
]

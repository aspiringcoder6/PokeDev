"""Proposed-plan contract for the ADLC Planner Agent slice.

The Planner Agent is a *proposal generator only*. It never executes tasks,
never touches the scheduler, and never mutates runtime state. Every proposal
must pass orchestrator validation and explicit approval before the existing
``BlueprintCompiler`` → ``ExecutionPlan`` → ``ExecutionPlanMaterializer``
pipeline consumes it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from langflow.adlc.blueprints.models import (
    ClosedModel,
    ExecutionPlan,
    NonEmptyString,
    PackageReference,
    PlanValidationIssue,
    SlotName,
)

PLANNER_CONTRACT_VERSION = "0.1"


def _is_none(value: object) -> bool:
    return value is None


class ProposalStatus(str, Enum):
    """Lifecycle of one planner proposal owned by the orchestrator."""

    GENERATED = "GENERATED"
    VALIDATED = "VALIDATED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class PlannerMode(str, Enum):
    MOCK = "MOCK"
    LLM = "LLM"


class ProposedTask(ClosedModel):
    """One planner-proposed unit of work, still subject to orchestrator validation."""

    task_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    source_stage_id: UUID
    name: NonEmptyString = Field(max_length=200)
    description: str = Field(default="", max_length=4000)
    objective: NonEmptyString = Field(max_length=4000)
    parent_task_id: str | None = Field(default=None, exclude_if=_is_none)
    dependency_task_ids: list[str] = Field(default_factory=list)
    assigned_package: PackageReference
    expected_outputs: list[SlotName] = Field(default_factory=list)
    inputs: dict[SlotName, Any] = Field(default_factory=dict)
    planning_rationale: str = Field(default="", max_length=4000)
    priority: int = Field(default=50, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_proposed_task(self) -> ProposedTask:
        if len(self.dependency_task_ids) != len(set(self.dependency_task_ids)):
            raise ValueError("dependency_task_ids must be unique")
        if len(self.expected_outputs) != len(set(self.expected_outputs)):
            raise ValueError("expected_outputs must be unique")
        if self.parent_task_id == self.task_id:
            raise ValueError("a proposed task cannot be its own parent")
        if self.task_id in self.dependency_task_ids:
            raise ValueError("a proposed task cannot depend on itself")
        return self


class ProposedPlan(ClosedModel):
    """One immutable planner proposal awaiting orchestrator validation/approval."""

    schema_version: Literal["0.1"] = "0.1"
    proposal_id: UUID
    workflow_definition_id: UUID
    workflow_definition_version: int = Field(ge=1)
    proposal_version: int = Field(ge=1)
    status: ProposalStatus
    planner_mode: PlannerMode
    planner_version: NonEmptyString
    tasks: list[ProposedTask] = Field(default_factory=list)
    validation_errors: list[PlanValidationIssue] = Field(default_factory=list)
    warnings: list[PlanValidationIssue] = Field(default_factory=list)
    assumptions: list[NonEmptyString] = Field(default_factory=list)
    clarifications: list[NonEmptyString] = Field(default_factory=list)
    generated_by: NonEmptyString
    generated_at: datetime
    validated_at: datetime | None = Field(default=None, exclude_if=_is_none)
    approved_by: str | None = Field(default=None, exclude_if=_is_none)
    approved_at: datetime | None = Field(default=None, exclude_if=_is_none)
    supersedes_proposal_id: UUID | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    materialized_plan_id: UUID | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_proposed_plan(self) -> ProposedPlan:
        # Duplicate task IDs and dependency integrity are orchestrator-validator
        # concerns (the planner output is untrusted and must remain inspectable);
        # only structural status invariants are enforced here.
        if self.status is ProposalStatus.VALIDATED and self.validation_errors:
            raise ValueError("VALIDATED proposals must not carry validation errors")
        if self.status is ProposalStatus.REVISION_REQUIRED and not self.validation_errors:
            raise ValueError("REVISION_REQUIRED proposals must record validation errors")
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError("approved_by and approved_at must be present or absent together")
        if self.status is ProposalStatus.APPROVED and self.approved_at is None:
            raise ValueError("APPROVED proposals require approval provenance")
        if self.status is ProposalStatus.APPROVED and self.materialized_plan_id is None:
            raise ValueError("APPROVED proposals must reference their materialized execution plan")
        if self.approved_at is not None and self.approved_at < self.generated_at:
            raise ValueError("approved_at cannot precede generated_at")
        if self.validated_at is not None and self.validated_at < self.generated_at:
            raise ValueError("validated_at cannot precede generated_at")
        return self


class PlanProposalLimits(ClosedModel):
    """Bounded decomposition configuration; prevents unbounded planning."""

    max_tasks: int = Field(default=24, ge=1, le=100)
    max_tasks_per_stage: int = Field(default=8, ge=1, le=32)
    max_depth: int = Field(default=2, ge=1, le=4)


class GeneratePlanProposalConfig(ClosedModel):
    """Caller-tunable planner knobs; ``None`` falls back to environment defaults."""

    mode: PlannerMode | None = None
    limits: PlanProposalLimits | None = None


class GeneratePlanProposalRequest(BaseModel):
    """HTTP request body for proposal generation (camelCase wire format)."""

    model_config = ConfigDict(populate_by_name=True)

    mode: str | None = Field(default=None, alias="mode")
    max_tasks: int | None = Field(default=None, alias="maxTasks", ge=1, le=100)
    max_tasks_per_stage: int | None = Field(
        default=None, alias="maxTasksPerStage", ge=1, le=32
    )
    max_depth: int | None = Field(default=None, alias="maxDepth", ge=1, le=4)


class ProposalApprovalCommand(BaseModel):
    comment: str | None = Field(default=None, max_length=4096)


class ProposalApprovalResponse(ClosedModel):
    """Result of approving one proposal: updated proposal + materialized plan."""

    proposal: ProposedPlan
    execution_plan: ExecutionPlan

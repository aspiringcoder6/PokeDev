"""Typed models for the contract-aligned ADLC mock workflow."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "0.1"


def _is_none(value: object) -> bool:
    return value is None


class WorkflowRunStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowExecutionMode(str, Enum):
    """Explicit source contract used to create a workflow run."""

    LEGACY_FLOW = "LEGACY_FLOW"
    EXECUTION_PLAN = "EXECUTION_PLAN"
    MOCK_WORKFLOW = "MOCK_WORKFLOW"


class TaskRunStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class TaskResultStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class GateType(str, Enum):
    BEFORE_TASK = "BEFORE_TASK"
    ACTION = "ACTION"
    AFTER_TASK = "AFTER_TASK"


class MockTaskKey(str, Enum):
    PLAN = "plan"
    IMPLEMENT_BACKEND = "implement_backend"
    IMPLEMENT_UI = "implement_ui"
    VERIFY = "verify"
    APPROVAL = "approval"


class Actor(BaseModel):
    type: Literal["USER", "SERVICE", "AGENT", "SYSTEM"]
    id: str | None = None
    display_name: str | None = None


class ExecutorTarget(BaseModel):
    service: str
    operation: str
    agent_id: str | None = Field(default=None, exclude_if=_is_none)
    environment_id: str | None = Field(default=None, exclude_if=_is_none)
    capabilities: list[str] = Field(default_factory=list)


class ExecutorContract(BaseModel):
    """Executor connection-contract hints carried by one TaskRequest (v1).

    Optional by design (backward compatible): the control plane may omit
    it entirely and legacy executors keep working. When present, an
    executor MUST honor it:

    * ``allowed_paths`` — repository-relative scope paths the executor
      may touch, including everything its internal sessions/subagents
      touch. Same rules as the skilltree contract ``allowed_paths``.
    * ``denied_permissions`` — permission hints, e.g. ``"shell"``,
      ``"write"``, ``"network"``. Advisory for v1: executors without a
      privilege plane must treat them as hard refusals.
    * ``cost_tier`` — desired ``CostTier`` label: ``cheap`` /
      ``medium`` / ``expensive`` (see resource_manager).
    """

    schema_version: Literal["0.1"] = CONTRACT_VERSION
    allowed_paths: list[str] = Field(default_factory=list)
    denied_permissions: list[str] = Field(default_factory=list)
    cost_tier: Literal["cheap", "medium", "expensive"] | None = Field(default=None, exclude_if=_is_none)

    @field_validator("allowed_paths")
    @classmethod
    def _validate_relative_paths(cls, paths: list[str]) -> list[str]:
        for path in paths:
            if path == "*":
                continue
            if (
                path.startswith("/")
                or "\\" in path
                or ":" in path
                or any(part in {"", ".", ".."} for part in path.rstrip("/").split("/"))
                or any(ord(char) < 32 for char in path)
            ):
                msg = f"allowed_paths must be repository-relative paths, got {path!r}."
                raise ValueError(msg)
        return paths

    @field_validator("denied_permissions")
    @classmethod
    def _validate_permission_words(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or value.strip() != value or not all(char.isalnum() or char in "-_" for char in value):
                msg = f"denied_permissions entries must be simple words, got {value!r}."
                raise ValueError(msg)
        return values


class TaskRequest(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    request_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    task_definition_id: UUID
    task_type: str
    name: str
    executor: ExecutorTarget
    input: Any
    context: dict[str, Any] | None = Field(default=None, exclude_if=_is_none)
    dependency_task_run_ids: list[UUID]
    constraints: dict[str, Any] | None = Field(default=None, exclude_if=_is_none)
    idempotency_key: str
    requested_at: datetime
    trace_context: dict[str, str] | None = Field(default=None, exclude_if=_is_none)
    metadata: dict[str, Any] = Field(default_factory=dict)
    executor_contract: ExecutorContract | None = Field(default=None, exclude_if=_is_none)

    @model_validator(mode="before")
    @classmethod
    def _lift_executor_contract_from_constraints(cls, data: Any) -> Any:
        """Backward-compatible shim: a contract hidden in ``constraints``
        (how run_service merges task-definition constraints today) is
        lifted into the typed field automatically. An explicit typed
        field always wins."""
        if not isinstance(data, dict) or data.get("executor_contract") is not None:
            return data
        constraints = data.get("constraints")
        if isinstance(constraints, dict) and isinstance(constraints.get("executor_contract"), dict):
            data = {**data, "executor_contract": constraints["executor_contract"]}
        return data


class Checksum(BaseModel):
    algorithm: Literal["SHA256"] = "SHA256"
    value: str


class Artifact(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    artifact_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    kind: str
    name: str
    media_type: str
    uri: str
    size_bytes: int
    checksum: Checksum
    producer: str
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceError(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    error_id: UUID
    code: str
    category: Literal[
        "VALIDATION",
        "AUTHENTICATION",
        "AUTHORIZATION",
        "NOT_FOUND",
        "CONFLICT",
        "RATE_LIMIT",
        "TIMEOUT",
        "DEPENDENCY",
        "EXECUTION",
        "CANCELLED",
        "INTERNAL",
    ]
    message: str
    retryable: bool
    service: str
    http_status: int | None = Field(default=None, exclude_if=_is_none)
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, exclude_if=_is_none)
    occurred_at: datetime


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TaskMetrics(BaseModel):
    duration_ms: int
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    custom: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    request_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    status: TaskResultStatus
    output: Any
    artifacts: list[Artifact]
    error: ServiceError | None
    metrics: TaskMetrics | None = Field(default=None, exclude_if=_is_none)
    started_at: datetime
    completed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    event_id: UUID
    event_type: str
    workflow_run_id: UUID
    task_run_id: UUID | None = Field(default=None, exclude_if=_is_none)
    attempt_id: UUID | None = Field(default=None, exclude_if=_is_none)
    approval_request_id: UUID | None = Field(default=None, exclude_if=_is_none)
    aggregate_type: Literal["WORKFLOW_RUN", "TASK_RUN", "APPROVAL_REQUEST"]
    aggregate_id: UUID
    sequence: int
    previous_status: str | None
    status: str
    actor: Actor
    correlation_id: str | None = Field(default=None, exclude_if=_is_none)
    causation_event_id: UUID | None = Field(default=None, exclude_if=_is_none)
    occurred_at: datetime
    producer: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalAction(BaseModel):
    action_id: str
    label: str
    effect: Literal["APPROVE", "REJECT", "CANCEL"]
    comment_required: bool


class ApprovalDecision(BaseModel):
    action_id: str
    effect: Literal["APPROVE", "REJECT", "CANCEL", "EXPIRE"]
    decided_by: Actor
    comment: str | None = None
    decided_at: datetime


class ApprovalContext(BaseModel):
    summary: str
    risk: str | None = Field(default=None, exclude_if=_is_none)
    requested_action: str | None = Field(default=None, exclude_if=_is_none)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    schema_version: Literal["0.1"] = CONTRACT_VERSION
    approval_request_id: UUID
    workflow_run_id: UUID
    task_run_id: UUID
    attempt_id: UUID
    gate_type: GateType
    status: ApprovalStatus
    blocking: Literal[True] = True
    title: str
    requested_by: Actor
    required_role: str
    reviewer_ids: list[str]
    actions: list[ApprovalAction]
    context: ApprovalContext
    decision: ApprovalDecision | None
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MockArtifactSpec(BaseModel):
    kind: str
    name: str
    media_type: str
    content: str


class PlanTaskTraceability(BaseModel):
    """Immutable links from a runtime task back to its accepted plan snapshot."""

    execution_plan_id: UUID
    plan_task_id: UUID
    source_workflow_stage_id: UUID
    resolved_node_spec_id: UUID
    package_id: str
    package_version: str
    package_content_digest: str
    resolved_node_digest: str


class MockTaskDefinition(BaseModel):
    id: UUID
    key: MockTaskKey
    name: str
    task_type: str
    dependencies: list[MockTaskKey]
    executor: Literal["mock"] = "mock"
    predetermined_output: dict[str, Any]
    artifact: MockArtifactSpec
    approval_gate: GateType | None = None


class AdlcTaskDefinition(BaseModel):
    """Runtime task definition produced by legacy normalization or plan materialization."""

    id: UUID
    key: str
    name: str
    task_type: str
    dependencies: list[str]
    dependency_conditions: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    required_resources: list[str] = Field(default_factory=list)
    waits_for: list[str] = Field(default_factory=list)
    emits_events: list[str] = Field(default_factory=list)
    executor: Literal["mock"] = "mock"
    predetermined_output: dict[str, Any]
    artifact: MockArtifactSpec
    approval_gate: GateType | None = None
    objective: str = ""
    direct_inputs: dict[str, Any] = Field(default_factory=dict)
    input_bindings: list[dict[str, Any]] = Field(default_factory=list)
    executor_target: ExecutorTarget | None = None
    request_context: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    simulate_failure: bool = False
    delay_ms: int | None = Field(default=None, ge=0, le=5000)
    approval_message: str | None = None
    approval_required_role: str | None = None
    plan_traceability: PlanTaskTraceability | None = None


class MockWorkflowDefinition(BaseModel):
    key: Literal["adlc_mock_v0_1"] = "adlc_mock_v0_1"
    name: Literal["ADLC Mock Workflow"] = "ADLC Mock Workflow"
    tasks: list[MockTaskDefinition]


class StartMockWorkflowRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    simulate_failure: bool = Field(default=False, alias="simulateFailure")
    failure_task: MockTaskKey = Field(default=MockTaskKey.VERIFY, alias="failureTask")
    delay_ms: int = Field(default=50, ge=0, le=2000, alias="delayMs")


class CreateWorkflowRunRequest(BaseModel):
    """Start an ADLC run from the current persisted Langflow graph."""

    model_config = ConfigDict(populate_by_name=True)

    flow_id: UUID = Field(alias="flowId")
    execution_mode: WorkflowExecutionMode = Field(alias="executionMode")
    simulate_failure: bool = Field(default=False, alias="simulateFailure")
    failure_task_id: str | None = Field(default=None, alias="failureTaskId")
    delay_ms: int = Field(default=50, ge=0, le=2000, alias="delayMs")
    max_concurrency: int | None = Field(default=None, ge=1, le=64, alias="maxConcurrency", exclude_if=_is_none)
    sla_seconds: int | None = Field(default=None, ge=1, le=30 * 24 * 3600, alias="slaSeconds", exclude_if=_is_none)


class MaterializeExecutionPlanRequest(BaseModel):
    """Create a runtime once for an accepted plan and caller idempotency key."""

    model_config = ConfigDict(populate_by_name=True)

    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255, pattern=r"\S")


class RegenerateExecutionPlanRequest(BaseModel):
    """Create a successor plan exactly once for a caller request."""

    model_config = ConfigDict(populate_by_name=True)

    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=255, pattern=r"\S")


class PlanApprovalCommand(BaseModel):
    comment: str | None = Field(default=None, max_length=4096)


class ApprovalDecisionCommand(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    comment: str | None = Field(default=None, max_length=4096)


class ApprovalComment(BaseModel):
    comment: str | None = Field(default=None, max_length=4096)


class EmitRunEventCommand(BaseModel):
    """Emit one external runtime event onto a workflow run."""

    model_config = ConfigDict(populate_by_name=True)

    event_name: str = Field(alias="eventName", min_length=1, max_length=128, pattern=r"^[a-z0-9._-]+$")
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskRun(BaseModel):
    id: UUID
    workflow_run_id: UUID
    task_definition_id: UUID
    key: MockTaskKey | str
    name: str
    task_type: str
    status: TaskRunStatus
    dependency_task_run_ids: list[UUID]
    executor: ExecutorTarget
    simulate_failure: bool = False
    current_attempt_id: UUID | None = None
    request: TaskRequest | None = None
    pending_result: TaskResult | None = None
    result: TaskResult | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    deadline_at: datetime | None = None
    worker_id: str | None = None
    plan_traceability: PlanTaskTraceability | None = None


class WorkflowRun(BaseModel):
    id: UUID
    # Immutable server binding. It never comes from CreateWorkflowRunRequest.
    project_id: UUID | None = Field(default=None, exclude_if=_is_none)
    initiated_by: str | None = Field(default=None, exclude_if=_is_none)
    workflow_key: str
    execution_mode: WorkflowExecutionMode
    flow_id: UUID | None = None
    execution_plan_id: UUID | None = None
    run_number: int | None = None
    name: str
    status: WorkflowRunStatus
    tasks: list[TaskRun]
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    sla_deadline_at: datetime | None = None
    sla_breached_at: datetime | None = None
    # Coordinator-owned metadata (e.g. the post-run ReflectionReport).
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdlcDeadLetter(BaseModel):
    """Read-only projection of one task that exhausted its retry budget."""

    workflow_run_id: UUID
    run_name: str
    run_status: WorkflowRunStatus
    task_run_id: UUID
    task_key: str
    task_name: str
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    failed_at: datetime | None = None


class RunEventsResponse(BaseModel):
    workflow_run_id: UUID
    events: list[RunEvent]


class AdlcRunSummary(BaseModel):
    """Read-only projection of one workflow run for history listings."""

    id: UUID
    workflow_key: str
    name: str
    status: WorkflowRunStatus
    execution_mode: WorkflowExecutionMode
    flow_id: UUID | None = None
    execution_plan_id: UUID | None = None
    run_number: int | None = None
    created_at: datetime
    completed_at: datetime | None = None
    task_total: int
    task_succeeded: int
    task_failed: int
    pending_approval: bool


class WorkflowRunSummary(BaseModel):
    id: UUID
    name: str
    execution_mode: WorkflowExecutionMode
    flow_id: UUID | None = None
    execution_plan_id: UUID | None = None
    status: WorkflowRunStatus
    task_count: int
    completed_task_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class WorkflowRunListResponse(BaseModel):
    runs: list[WorkflowRunSummary]
    total: int
    limit: int
    offset: int


class RunRecoveryReport(BaseModel):
    inspected: int = 0
    reattached: int = 0
    restored_approvals: int = 0

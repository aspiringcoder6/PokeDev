"""Typed authoring and planning models for ADLC workflow contract v0.1."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, NoReturn
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AUTHORING_CONTRACT_VERSION = "0.1"

NonEmptyString = Annotated[str, Field(min_length=1)]
RegistryKey = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$"),
]
ErrorCode = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")]
SemanticVersion = Annotated[
    str,
    Field(
        min_length=5,
        max_length=128,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
SlotName = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")]
JsonPointer = Annotated[str, Field(min_length=1, pattern=r"^/(configuration|policies|execution_profile)(/.*)?$")]


def _invalid(message: str) -> NoReturn:
    raise ValueError(message)


def _is_none(value: object) -> bool:
    return value is None


def _require_unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        _invalid(f"{label} must be unique")


def _validate_dag(node_ids: set[UUID], dependencies: dict[UUID, set[UUID]], label: str) -> None:
    if node_ids and not any(not dependencies[node_id] for node_id in node_ids):
        _invalid(f"{label} must contain at least one starting node")

    indegree = {node_id: len(dependencies[node_id]) for node_id in node_ids}
    dependents: dict[UUID, list[UUID]] = {node_id: [] for node_id in node_ids}
    for node_id, node_dependencies in dependencies.items():
        for dependency in node_dependencies:
            dependents[dependency].append(node_id)

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        node_id = queue.popleft()
        visited += 1
        for dependent in dependents[node_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if visited != len(node_ids):
        _invalid(f"{label} must be acyclic")


class ClosedModel(BaseModel):
    """Base for closed authoring-contract objects."""

    model_config = ConfigDict(extra="forbid")


class NodePackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


class NodePackageKind(str, Enum):
    AGENT = "AGENT"
    TESTING = "TESTING"
    REVIEW = "REVIEW"
    APPROVAL = "APPROVAL"
    ROUTER = "ROUTER"
    JOIN = "JOIN"


class PackageAdapterType(str, Enum):
    AGENT_PROVIDER = "AGENT_PROVIDER"
    TESTING_PROVIDER = "TESTING_PROVIDER"
    REVIEW_PROVIDER = "REVIEW_PROVIDER"
    CONTROL = "CONTROL"


class WorkflowDefinitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    INVALID = "INVALID"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlanValidationStatus(str, Enum):
    NOT_VALIDATED = "NOT_VALIDATED"
    VALID = "VALID"
    INVALID = "INVALID"


class PackageReference(ClosedModel):
    package_id: RegistryKey
    version: SemanticVersion
    content_digest: Sha256Digest | None = Field(default=None, exclude_if=_is_none)


class InterfaceSlot(ClosedModel):
    name: SlotName
    schema_ref: NonEmptyString
    required: bool
    multiple: bool
    description: str = ""


class NodePackageInterface(ClosedModel):
    inputs: list[InterfaceSlot]
    outputs: list[InterfaceSlot]

    @model_validator(mode="after")
    def validate_unique_slot_names(self) -> NodePackageInterface:
        _require_unique([slot.name for slot in self.inputs], "input slot names")
        _require_unique([slot.name for slot in self.outputs], "output slot names")
        return self


class CapabilityReferences(ClosedModel):
    tool_refs: list[NonEmptyString] = Field(default_factory=list)
    skill_refs: list[NonEmptyString] = Field(default_factory=list)
    plugin_refs: list[NonEmptyString] = Field(default_factory=list)
    mcp_server_refs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_references(self) -> CapabilityReferences:
        for field_name in ("tool_refs", "skill_refs", "plugin_refs", "mcp_server_refs"):
            _require_unique(list(getattr(self, field_name)), field_name)
        return self


class ExecutionProfile(ClosedModel):
    provider_ref: NonEmptyString
    model_ref: NonEmptyString
    system_prompt_ref: NonEmptyString
    rule_set_refs: list[NonEmptyString] = Field(default_factory=list)
    hook_refs: list[NonEmptyString] = Field(default_factory=list)
    capabilities: CapabilityReferences = Field(default_factory=CapabilityReferences)
    memory_policy_ref: NonEmptyString
    sandbox_policy_ref: NonEmptyString
    secret_refs: dict[str, NonEmptyString] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_references(self) -> ExecutionProfile:
        _require_unique(list(self.rule_set_refs), "rule_set_refs")
        _require_unique(list(self.hook_refs), "hook_refs")
        return self


class NodeImplementation(ClosedModel):
    adapter_type: PackageAdapterType
    adapter_ref: NonEmptyString
    entrypoint: NonEmptyString


class RetryPolicy(ClosedModel):
    max_attempts: int = Field(ge=1, le=100)


class ApprovalPolicy(ClosedModel):
    gate_type: Literal["BEFORE_TASK", "ACTION", "AFTER_TASK"] | None = None


class PermissionPolicy(ClosedModel):
    mode: Literal["PACKAGE_ALLOWLIST"] = "PACKAGE_ALLOWLIST"


class NodeDefaultPolicies(ClosedModel):
    retry: RetryPolicy
    timeout_ms: int = Field(ge=1)
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    permissions: PermissionPolicy = Field(default_factory=PermissionPolicy)
    resources: dict[str, Any] = Field(default_factory=dict)
    runtime_overridable: list[JsonPointer] = Field(default_factory=list)

    @field_validator("runtime_overridable")
    @classmethod
    def validate_unique_runtime_overrides(cls, values: list[str]) -> list[str]:
        _require_unique(list(values), "runtime_overridable paths")
        return values


class EngineCompatibility(ClosedModel):
    minimum_version: SemanticVersion


class PackageCompatibility(ClosedModel):
    engine: EngineCompatibility
    execution_contract_versions: list[Literal["0.1"]]

    @field_validator("execution_contract_versions")
    @classmethod
    def validate_contract_versions(cls, values: list[str]) -> list[str]:
        if not values:
            _invalid("execution_contract_versions must not be empty")
        _require_unique(list(values), "execution_contract_versions")
        return values


class NodePackageDefinition(ClosedModel):
    schema_version: Literal["0.1"]
    package_id: RegistryKey
    version: SemanticVersion
    status: NodePackageStatus
    name: NonEmptyString
    description: str
    kind: NodePackageKind
    interface: NodePackageInterface
    configuration_schema: dict[str, Any]
    defaults: dict[str, Any]
    override_allowlist: list[JsonPointer]
    implementation: NodeImplementation
    execution_profile: ExecutionProfile | None
    default_policies: NodeDefaultPolicies
    compatibility: PackageCompatibility
    metadata: dict[str, Any]

    @field_validator("override_allowlist")
    @classmethod
    def validate_unique_override_paths(cls, values: list[str]) -> list[str]:
        _require_unique(list(values), "override_allowlist paths")
        return values

    @model_validator(mode="after")
    def validate_kind_shape(self) -> NodePackageDefinition:
        executable = {NodePackageKind.AGENT, NodePackageKind.TESTING, NodePackageKind.REVIEW}
        if self.kind in executable and self.execution_profile is None:
            _invalid(f"{self.kind.value} packages require execution_profile")
        if (
            self.kind is NodePackageKind.AGENT
            and self.implementation.adapter_type is not PackageAdapterType.AGENT_PROVIDER
        ):
            _invalid("AGENT packages require implementation.adapter_type=AGENT_PROVIDER")
        if (
            self.kind is NodePackageKind.TESTING
            and self.implementation.adapter_type is not PackageAdapterType.TESTING_PROVIDER
        ):
            _invalid("TESTING packages require implementation.adapter_type=TESTING_PROVIDER")
        if (
            self.kind is NodePackageKind.REVIEW
            and self.implementation.adapter_type is not PackageAdapterType.REVIEW_PROVIDER
        ):
            _invalid("REVIEW packages require implementation.adapter_type=REVIEW_PROVIDER")
        if (
            self.kind in {NodePackageKind.APPROVAL, NodePackageKind.ROUTER, NodePackageKind.JOIN}
            and self.implementation.adapter_type is not PackageAdapterType.CONTROL
        ):
            _invalid(f"{self.kind.value} packages require implementation.adapter_type=CONTROL")
        return self


class StagePosition(ClosedModel):
    x: float
    y: float


class WorkflowStage(ClosedModel):
    stage_id: UUID
    stage_type: NonEmptyString
    name: NonEmptyString
    objective: NonEmptyString
    inputs: dict[SlotName, Any]
    expected_outputs: list[SlotName]
    package_ref: PackageReference
    configuration_overrides: dict[str, Any]
    execution_profile_overrides: dict[str, Any]
    policy_overrides: dict[str, Any]
    secret_refs: dict[str, NonEmptyString]
    position: StagePosition
    metadata: dict[str, Any]

    @field_validator("expected_outputs")
    @classmethod
    def validate_unique_expected_outputs(cls, values: list[str]) -> list[str]:
        _require_unique(list(values), "expected_outputs")
        return values


class SlotBinding(ClosedModel):
    source_output: SlotName
    target_input: SlotName


EdgeCondition = Literal["ON_SUCCESS", "ON_FAILURE", "ALWAYS", "ON_DONE"]
EDGE_CONDITIONS = ("ON_SUCCESS", "ON_FAILURE", "ALWAYS", "ON_DONE")


class WorkflowEdge(ClosedModel):
    edge_id: UUID
    source_stage_id: UUID
    target_stage_id: UUID
    condition: EdgeCondition
    bindings: list[SlotBinding]
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def validate_edge(self) -> WorkflowEdge:
        if self.source_stage_id == self.target_stage_id:
            _invalid("workflow edge source and target must differ")
        pairs = [(binding.source_output, binding.target_input) for binding in self.bindings]
        _require_unique(pairs, "edge bindings")
        return self


class WorkflowDefinition(ClosedModel):
    schema_version: Literal["0.1"]
    workflow_definition_id: UUID
    project_id: UUID
    name: NonEmptyString
    description: str = ""
    version: int = Field(ge=1)
    status: WorkflowDefinitionStatus
    stages: list[WorkflowStage]
    edges: list[WorkflowEdge]
    default_policies: dict[str, Any]
    created_by: NonEmptyString
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def validate_workflow_graph(self) -> WorkflowDefinition:
        if not self.stages:
            _invalid("workflow definition must contain at least one stage")
        if self.updated_at < self.created_at:
            _invalid("updated_at cannot precede created_at")

        stage_ids = [stage.stage_id for stage in self.stages]
        edge_ids = [edge.edge_id for edge in self.edges]
        _require_unique(stage_ids, "stage IDs")
        _require_unique(edge_ids, "edge IDs")
        stage_id_set = set(stage_ids)

        dependency_pairs: list[tuple[UUID, UUID]] = []
        dependencies = {stage_id: set() for stage_id in stage_id_set}
        for edge in self.edges:
            if edge.source_stage_id not in stage_id_set:
                _invalid(f"edge source stage {edge.source_stage_id} does not exist")
            if edge.target_stage_id not in stage_id_set:
                _invalid(f"edge target stage {edge.target_stage_id} does not exist")
            pair = (edge.source_stage_id, edge.target_stage_id)
            dependency_pairs.append(pair)
            dependencies[edge.target_stage_id].add(edge.source_stage_id)
        _require_unique(dependency_pairs, "workflow dependency pairs")
        _validate_dag(stage_id_set, dependencies, "workflow definition")
        return self


class PlanValidationIssue(ClosedModel):
    code: ErrorCode
    message: NonEmptyString
    path: str | None = Field(default=None, exclude_if=_is_none)
    details: dict[str, Any] = Field(default_factory=dict)


class ResolvedNodeSpec(ClosedModel):
    schema_version: Literal["0.1"]
    resolved_node_spec_id: UUID
    workflow_definition_id: UUID
    workflow_definition_version: int = Field(ge=1)
    source_stage_id: UUID
    package_ref: PackageReference
    kind: NodePackageKind
    implementation: NodeImplementation
    interface: NodePackageInterface
    configuration: dict[str, Any]
    execution_profile: ExecutionProfile | None
    policies: NodeDefaultPolicies
    secret_refs: dict[str, NonEmptyString]
    resolved_digest: Sha256Digest
    resolver_version: SemanticVersion
    resolved_at: datetime
    validation_evidence: list[NonEmptyString]
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def validate_package_digest(self) -> ResolvedNodeSpec:
        if self.package_ref.content_digest is None:
            _invalid("resolved package_ref requires content_digest")
        return self


class ResolvedInputBinding(ClosedModel):
    source_plan_task_id: UUID
    source_output: SlotName
    target_input: SlotName


class PlanTask(ClosedModel):
    plan_task_id: UUID
    source_workflow_stage_id: UUID
    resolved_node_spec_id: UUID
    resolved_node_digest: Sha256Digest
    name: NonEmptyString
    objective: NonEmptyString
    task_type: NonEmptyString
    dependency_task_ids: list[UUID] = Field(default_factory=list)
    dependency_conditions: list[EdgeCondition] = Field(default_factory=list)
    input_bindings: list[ResolvedInputBinding] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[NonEmptyString] = Field(default_factory=list)
    assigned_capability: NonEmptyString | None = Field(default=None, exclude_if=_is_none)
    required_environment: NonEmptyString | None = Field(default=None, exclude_if=_is_none)
    effective_policies: NodeDefaultPolicies
    planning_rationale: str = ""
    priority: int = Field(default=50, ge=0, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task_lists(self) -> PlanTask:
        _require_unique(list(self.dependency_task_ids), "dependency_task_ids")
        _require_unique(list(self.expected_artifacts), "expected_artifacts")
        if self.dependency_conditions and len(self.dependency_conditions) != len(self.dependency_task_ids):
            _invalid("dependency_conditions must align with dependency_task_ids")
        bindings = [
            (binding.source_plan_task_id, binding.source_output, binding.target_input)
            for binding in self.input_bindings
        ]
        _require_unique(bindings, "input bindings")
        return self


class ExecutionPlan(ClosedModel):
    schema_version: Literal["0.1"]
    execution_plan_id: UUID
    workflow_definition_id: UUID
    workflow_definition_version: int = Field(ge=1)
    plan_version: int = Field(ge=1)
    status: PlanStatus
    validation_status: PlanValidationStatus
    validation_errors: list[PlanValidationIssue]
    warnings: list[PlanValidationIssue]
    assumptions: list[NonEmptyString]
    approval_required: bool
    tasks: list[PlanTask]
    resolved_node_specs: list[ResolvedNodeSpec]
    generated_by: NonEmptyString
    generated_at: datetime
    approved_by: NonEmptyString | None = Field(default=None, exclude_if=_is_none)
    approved_at: datetime | None = Field(default=None, exclude_if=_is_none)
    supersedes_plan_id: UUID | None = Field(default=None, exclude_if=_is_none)
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def validate_plan(self) -> ExecutionPlan:
        if not self.tasks and self.status not in {PlanStatus.INVALID, PlanStatus.SUPERSEDED}:
            _invalid("execution plan must contain at least one task")
        task_ids = [task.plan_task_id for task in self.tasks]
        spec_ids = [spec.resolved_node_spec_id for spec in self.resolved_node_specs]
        task_stage_ids = [task.source_workflow_stage_id for task in self.tasks]
        spec_stage_ids = [spec.source_stage_id for spec in self.resolved_node_specs]
        _require_unique(task_ids, "plan task IDs")
        _require_unique(spec_ids, "resolved node spec IDs")
        _require_unique(task_stage_ids, "plan task source stage IDs")
        _require_unique(spec_stage_ids, "resolved node spec source stage IDs")
        task_id_set = set(task_ids)
        tasks = {task.plan_task_id: task for task in self.tasks}
        specs = {spec.resolved_node_spec_id: spec for spec in self.resolved_node_specs}
        dependencies = {task_id: set() for task_id in task_id_set}

        for spec in self.resolved_node_specs:
            if spec.workflow_definition_id != self.workflow_definition_id:
                _invalid(f"resolved node spec {spec.resolved_node_spec_id} belongs to another workflow")
            if spec.workflow_definition_version != self.workflow_definition_version:
                _invalid(f"resolved node spec {spec.resolved_node_spec_id} belongs to another workflow version")

        for task in self.tasks:
            spec = specs.get(task.resolved_node_spec_id)
            if spec is None:
                _invalid(f"task {task.plan_task_id} references a missing resolved node spec")
            if task.source_workflow_stage_id != spec.source_stage_id:
                _invalid(f"task {task.plan_task_id} source stage does not match its node spec")
            if spec.resolved_digest != task.resolved_node_digest:
                _invalid(f"task {task.plan_task_id} resolved digest does not match its node spec")
            input_slots = {slot.name: slot for slot in spec.interface.inputs}
            for input_name in task.inputs:
                if input_name not in input_slots:
                    _invalid(f"task {task.plan_task_id} supplies unknown input {input_name}")
            for dependency in task.dependency_task_ids:
                if dependency not in task_id_set:
                    _invalid(f"task dependency {dependency} does not exist")
                if dependency == task.plan_task_id:
                    _invalid("a plan task cannot depend on itself")
                dependencies[task.plan_task_id].add(dependency)
            binding_counts: dict[str, int] = {}
            for binding in task.input_bindings:
                if binding.source_plan_task_id not in dependencies[task.plan_task_id]:
                    _invalid("input binding source must be a declared task dependency")
                target_slot = input_slots.get(binding.target_input)
                if target_slot is None:
                    _invalid(f"input binding targets unknown input {binding.target_input}")
                source_task = tasks[binding.source_plan_task_id]
                source_spec = specs.get(source_task.resolved_node_spec_id)
                if source_spec is None:
                    _invalid(f"task {source_task.plan_task_id} references a missing resolved node spec")
                source_slots = {slot.name: slot for slot in source_spec.interface.outputs}
                source_slot = source_slots.get(binding.source_output)
                if source_slot is None:
                    _invalid(f"input binding references unknown output {binding.source_output}")
                if source_slot.schema_ref != target_slot.schema_ref:
                    _invalid("input binding source and target schemas must match")
                binding_counts[binding.target_input] = binding_counts.get(binding.target_input, 0) + 1
            for slot in spec.interface.inputs:
                source_count = int(slot.name in task.inputs) + binding_counts.get(slot.name, 0)
                if slot.required and source_count == 0:
                    _invalid(f"required task input {slot.name} has no source")
                if not slot.multiple and source_count > 1:
                    _invalid(f"non-multiple task input {slot.name} has more than one source")

        if self.tasks and set(task_stage_ids) != set(spec_stage_ids):
            _invalid("execution plan tasks and resolved node specs must cover the same source stages")

        _validate_dag(task_id_set, dependencies, "execution plan")

        valid_statuses = {PlanStatus.VALIDATED, PlanStatus.APPROVED, PlanStatus.EXECUTING}
        if self.status in valid_statuses and (
            self.validation_status is not PlanValidationStatus.VALID or self.validation_errors
        ):
            _invalid(f"{self.status.value} requires valid validation state and no errors")
        if self.status is PlanStatus.INVALID and self.validation_status is not PlanValidationStatus.INVALID:
            _invalid("INVALID plan status requires validation_status=INVALID")
        if self.status is PlanStatus.INVALID and not self.validation_errors:
            _invalid("INVALID plan status requires at least one validation error")
        if self.status is PlanStatus.INVALID and self.tasks:
            _invalid("INVALID plan status cannot contain executable tasks")
        if self.status is PlanStatus.SUPERSEDED:
            if self.validation_status is PlanValidationStatus.VALID and (self.validation_errors or not self.tasks):
                _invalid("a superseded valid plan requires executable tasks and no validation errors")
            if self.validation_status is PlanValidationStatus.INVALID and (not self.validation_errors or self.tasks):
                _invalid("a superseded invalid plan requires validation errors and no executable tasks")
        if (self.approved_by is None) != (self.approved_at is None):
            _invalid("approved_by and approved_at must be present or absent together")
        if self.approved_at is not None and self.approved_at < self.generated_at:
            _invalid("approved_at cannot precede generated_at")
        if self.status is PlanStatus.APPROVED and self.approved_at is None:
            _invalid("APPROVED plan status requires approval provenance")
        if self.status is PlanStatus.EXECUTING and self.approval_required and self.approved_at is None:
            _invalid("an approval-required plan cannot execute without approval provenance")
        return self

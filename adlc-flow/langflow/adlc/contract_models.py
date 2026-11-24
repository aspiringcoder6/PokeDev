"""Closed, versioned contracts for tool-authored documents (H5A)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, field_validator, model_validator

SKILLTREE_SCHEMA_REF = "adlc://schemas/skilltree-contract/0.1"
SKILLTREE_PLUGIN_REF = "plugin:vai-adlc-skilltree/0.1.0"
SKILLTREE_RENDERER_REF = "adlc-renderer:skilltree/0.1"
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_NODES = 128
MAX_DEPENDENCIES = 256
MAX_REVISIONS = 512
MAX_INPUT_DEPTH = 32
ASCII_CONTROL_LIMIT = 32
SURROGATE_START = 0xD800
SURROGATE_END = 0xDFFF

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
CommandKey = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
Revision = Annotated[int, Field(strict=True, ge=1, le=MAX_REVISIONS)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
ToolName = Literal[
    "skilltree_init",
    "skilltree_upsert_node",
    "skilltree_remove_node",
    "skilltree_set_dependency",
    "skilltree_get_status",
    "skilltree_validate",
]


class ClosedContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_unsafe_text(cls, value: Any, info: ValidationInfo) -> Any:
        if info.field_name in {"revision", "expected_revision"} and value is not None and type(value) is not int:
            msg = "Revisions must be exact integers, not booleans, floats or strings."
            raise ValueError(msg)

        def check(item: Any, depth: int = 0) -> None:
            if depth > MAX_INPUT_DEPTH:
                msg = "Contract input nesting is too deep."
                raise ValueError(msg)
            if isinstance(item, str) and any(
                (ord(char) < ASCII_CONTROL_LIMIT and char not in "\n\r\t")
                or SURROGATE_START <= ord(char) <= SURROGATE_END
                for char in item
            ):
                msg = "Text contains unsupported control characters."
                raise ValueError(msg)
            if isinstance(item, (list, dict)):
                for nested in item.values() if isinstance(item, dict) else item:
                    check(nested, depth + 1)

        check(value)
        return value


class ContractReference(ClosedContractModel):
    schema_ref: Literal["adlc://schemas/skilltree-contract/0.1"] = SKILLTREE_SCHEMA_REF
    contract_id: UUID
    revision: Revision
    content_digest: Digest


class ContractScope(ClosedContractModel):
    """Server-assigned ownership binding; never an agent tool argument."""

    workflow_run_id: UUID
    task_run_id: UUID
    request_id: UUID | None = None
    attempt_id: UUID | None = None
    session_id: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")] | None = None

    @model_validator(mode="after")
    def validate_attempt_binding(self) -> ContractScope:
        if any((self.request_id, self.attempt_id, self.session_id)) and not all(
            (self.request_id, self.attempt_id, self.session_id)
        ):
            msg = "Harness bindings require request, attempt and session identities together."
            raise ValueError(msg)
        return self


class RoadmapScope(ClosedContractModel):
    objective: Text
    in_scope: list[Text] = Field(default_factory=list, max_length=32)
    out_of_scope: list[Text] = Field(default_factory=list, max_length=32)


class RoadmapConstraints(ClosedContractModel):
    """Declared commitments, not execution permissions until the H5C policy adapter."""

    read_only: Annotated[bool, Field(strict=True)] = True
    allowed_paths: list[Annotated[str, StringConstraints(min_length=1, max_length=255)]] = Field(
        default_factory=lambda: ["*"], min_length=1, max_length=64
    )
    forbidden_actions: list[Title] = Field(default_factory=lambda: ["commit", "push"], max_length=32)

    @field_validator("allowed_paths")
    @classmethod
    def validate_relative_paths(cls, paths: list[str]) -> list[str]:
        for path in paths:
            if path == "*":
                continue
            if (
                path.startswith("/")
                or "\\" in path
                or ":" in path
                or any(part in {"", ".", ".."} for part in path.rstrip("/").split("/"))
                or any(ord(char) < ASCII_CONTROL_LIMIT for char in path)
                or any(SURROGATE_START <= ord(char) <= SURROGATE_END for char in path)
            ):
                msg = "Allowed paths must be bounded repository-relative paths or '*'."
                raise ValueError(msg)
        return paths


class AcceptanceCriterion(ClosedContractModel):
    description: Text
    verification: Literal["HUMAN", "TEST", "ARTIFACT"] = "HUMAN"
    verifier_ref: (
        Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9:._/@-]+$")] | None
    ) = None


class SkilltreeNodeSpec(ClosedContractModel):
    kind: Literal["MILESTONE", "TASK", "DECISION"] = "TASK"
    title: Title
    description: Annotated[str, StringConstraints(max_length=4000)] = ""
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list, max_length=16)


class SkilltreeNode(SkilltreeNodeSpec):
    node_id: UUID


class SkilltreeDependency(ClosedContractModel):
    source_id: UUID
    target_id: UUID
    relation: Literal["REQUIRES", "CONTAINS"] = "REQUIRES"


class SkilltreeDocument(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    document_type: Literal["skilltree"] = "skilltree"
    schema_ref: Literal["adlc://schemas/skilltree-contract/0.1"] = SKILLTREE_SCHEMA_REF
    producer_plugin: Literal["plugin:vai-adlc-skilltree/0.1.0"] = SKILLTREE_PLUGIN_REF
    renderer_ref: Literal["adlc-renderer:skilltree/0.1"] = SKILLTREE_RENDERER_REF
    contract_id: UUID
    revision: Revision
    title: Title
    scope: RoadmapScope
    constraints: RoadmapConstraints = Field(default_factory=RoadmapConstraints)
    supersedes: ContractReference | None = None
    nodes: list[SkilltreeNode] = Field(default_factory=list, max_length=MAX_NODES)
    dependencies: list[SkilltreeDependency] = Field(default_factory=list, max_length=MAX_DEPENDENCIES)


class ContractCheck(ClosedContractModel):
    check_id: str
    passed: bool
    summary: str


class ContractValidation(ClosedContractModel):
    validator_ref: Literal["adlc-validator:skilltree/0.1"] = "adlc-validator:skilltree/0.1"
    content_digest: Digest
    passed: bool
    checks: list[ContractCheck]
    checked_at: datetime
    # A declaration check must never be presented as successful execution of its criteria.
    criteria_executed: Literal[False] = False


class ContractApproval(ClosedContractModel):
    approval_id: UUID
    reference: ContractReference
    approved_by: str
    approved_at: datetime
    comment: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ContractRead(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    document: SkilltreeDocument
    reference: ContractReference
    binding: ContractScope
    status: Literal["DRAFT", "VALIDATED", "APPROVED"]
    validation: ContractValidation | None = None
    approval: ContractApproval | None = None
    created_at: datetime
    authored_by: str
    authored_via: Literal["HUMAN", "HARNESS_TOOL"]


class InitArguments(ClosedContractModel):
    idempotency_key: CommandKey
    expected_revision: Literal[0] = 0
    title: Title
    scope: RoadmapScope
    constraints: RoadmapConstraints = Field(default_factory=RoadmapConstraints)


class MutationArguments(ClosedContractModel):
    contract_id: UUID
    expected_revision: Revision
    idempotency_key: CommandKey


class UpsertArguments(MutationArguments):
    node_id: UUID | None = None
    node: SkilltreeNodeSpec


class RemoveArguments(MutationArguments):
    node_id: UUID


class DependencyArguments(MutationArguments):
    source_id: UUID
    target_id: UUID
    relation: Literal["REQUIRES", "CONTAINS"] = "REQUIRES"
    operation: Literal["ADD", "REMOVE"] = "ADD"


class StatusArguments(ClosedContractModel):
    contract_id: UUID
    revision: Revision | None = None


class ValidateArguments(MutationArguments):
    pass


TOOL_ARGUMENT_MODELS: dict[str, type[ClosedContractModel]] = {
    "skilltree_init": InitArguments,
    "skilltree_upsert_node": UpsertArguments,
    "skilltree_remove_node": RemoveArguments,
    "skilltree_set_dependency": DependencyArguments,
    "skilltree_get_status": StatusArguments,
    "skilltree_validate": ValidateArguments,
}


class ContractToolCommand(ClosedContractModel):
    tool: ToolName
    arguments: dict[str, Any]


class ContractToolResult(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    contract: ContractRead
    node_id: UUID | None = None
    replayed: bool = False


class ContractApprovalCommand(ClosedContractModel):
    reference: ContractReference
    idempotency_key: CommandKey
    comment: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ContractForkCommand(ClosedContractModel):
    reference: ContractReference
    idempotency_key: CommandKey


class ContractBridgeCommand(ContractToolCommand):
    session_id: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")]


class ContractPluginTool(ClosedContractModel):
    name: ToolName
    input_schema: str
    effect: Literal["CREATE", "EDIT", "READ", "VALIDATE"]


class ContractPluginManifest(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    plugin_id: Literal["vai-adlc-skilltree"] = "vai-adlc-skilltree"
    version: Literal["0.1.0"] = "0.1.0"
    document_type: Literal["skilltree"] = "skilltree"
    document_schema: str
    schema_ref: Literal["adlc://schemas/skilltree-contract/0.1"] = SKILLTREE_SCHEMA_REF
    renderer_ref: Literal["adlc-renderer:skilltree/0.1"] = SKILLTREE_RENDERER_REF
    renderer_available: Literal[False] = False
    approval_authority: Literal["ADLC_AUTHENTICATED_OWNER"] = "ADLC_AUTHENTICATED_OWNER"
    tools: list[ContractPluginTool] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_tool_inventory(self) -> ContractPluginManifest:
        if {tool.name for tool in self.tools} != set(TOOL_ARGUMENT_MODELS):
            msg = "The manifest must declare exactly the six versioned tools."
            raise ValueError(msg)
        return self

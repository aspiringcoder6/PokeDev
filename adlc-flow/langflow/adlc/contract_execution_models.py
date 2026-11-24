"""H5C separately versioned execution policy and kernel evidence projections."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from langflow.adlc.contract_models import ClosedContractModel, ContractRead, ContractReference, ContractScope, Digest

POLICY_REF = "policy:adlc-contract-repository/0.1.0"
EXECUTION_PROFILE = "harness-profile:adlc-contract-coding/0.1.0"
EXECUTION_PACKAGE = "coding-agent-contract-harness"
RECOVERY_REF = "plugin:vai-adlc-contract-recovery/0.1.0"
RECOVERY_PACKAGE_VERSION = "0.2.0"
PATCH_VERIFIER = "verifier:contract-source-patch/0.1.0"
UNCHANGED_VERIFIER = "verifier:contract-no-changes/0.1.0"
JSON_VERIFIER = "verifier:contract-json-syntax/0.1.0"


class ExecutionCriterion(ClosedContractModel):
    node_id: UUID
    criterion_index: Annotated[int, Field(strict=True, ge=0, le=15)]
    verifier_ref: Literal[
        "verifier:contract-source-patch/0.1.0",
        "verifier:contract-no-changes/0.1.0",
        "verifier:contract-json-syntax/0.1.0",
    ]


class ContractExecutionPolicy(ClosedContractModel):
    policy_ref: Literal["policy:adlc-contract-repository/0.1.0"] = POLICY_REF
    contract_reference: ContractReference
    read_only: Annotated[bool, Field(strict=True)]
    allowed_paths: list[str] = Field(min_length=1, max_length=64)
    denied_actions: list[str]
    criteria: list[ExecutionCriterion] = Field(min_length=1, max_length=256)
    natural_language_enforced: Literal[False] = False


class ContractExecutionBinding(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    scope: ContractScope
    execution_plan_id: UUID
    resolved_node_digest: Digest
    reference: ContractReference
    policy: ContractExecutionPolicy
    policy_digest: Digest
    bound_at: AwareDatetime

    @model_validator(mode="after")
    def full_attempt(self):
        if not all((self.scope.request_id, self.scope.attempt_id, self.scope.session_id)):
            message = "Execution bindings require a full registered attempt."
            raise ValueError(message)
        if self.policy.contract_reference != self.reference:
            message = "Policy and binding references must match."
            raise ValueError(message)
        return self


class CriterionEvidence(ExecutionCriterion):
    passed: Annotated[bool, Field(strict=True)]


class ContractExecutionProof(ClosedContractModel):
    reference: ContractReference
    policy_digest: Digest
    artifact_id: UUID
    artifact_checksum: Digest
    base_commit: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    changed_paths: list[str] = Field(max_length=128)
    checks: list[CriterionEvidence] = Field(min_length=1, max_length=256)
    checked_at: AwareDatetime
    criteria_executed: Literal[True] = True
    execution_policy_enforced: Literal[True] = True
    natural_language_enforced: Literal[False] = False

    @field_validator("criteria_executed", "execution_policy_enforced", "natural_language_enforced", mode="before")
    @classmethod
    def exact_flags(cls, value):
        if type(value) is not bool:
            message = "Evidence flags must be exact booleans."
            raise ValueError(message)
        return value


class ContractExecutionRead(ClosedContractModel):
    binding: ContractExecutionBinding
    contract: ContractRead
    proof: ContractExecutionProof | None = None


class ContractExecutionBridgeCommand(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    operation: Literal["bind", "report"]
    session_id: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")]
    proof: ContractExecutionProof | None = None

    @model_validator(mode="after")
    def operation_payload(self):
        if (self.operation == "report") != (self.proof is not None):
            message = "Only report requires evidence; bind must not supply evidence."
            raise ValueError(message)
        return self


class ContractRecoveryCommand(ClosedContractModel):
    """An empty command: caller cannot choose evidence, authority or a replacement run."""


class ContractExecutionOutputs(ClosedContractModel):
    contract_reference: ContractReference
    source_patch: Annotated[str, Field(min_length=1, max_length=512)]


class ContractExecutionOutcome(ClosedContractModel):
    summary: Literal["Contract-bound patch captured; only registered machine predicates were verified."] = (
        "Contract-bound patch captured; only registered machine predicates were verified."
    )
    outputs: ContractExecutionOutputs
    evidence: ContractExecutionProof

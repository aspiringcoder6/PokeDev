"""Closed human commands; never accept an owner, raw evidence or approval flag."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from langflow.adlc.blueprints.models import WorkflowEdge, WorkflowStage
from langflow.adlc.contract_models import ContractToolCommand
from langflow.adlc.verification_models import VerificationCase

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class HumanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_revision: int = Field(strict=True, ge=1)


class ResourceCommand(HumanCommand):
    expected_revision: int = Field(strict=True, ge=1)
    content_digest: Digest


class ToolCommand(HumanCommand, ContractToolCommand):
    pass


class DecisionCommand(ResourceCommand):
    decision: Literal["APPROVE", "REQUEST_CHANGES"]
    comment: Text


class WorkflowCommand(HumanCommand):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    contract_id: UUID
    contract_revision: int = Field(strict=True, ge=1)
    contract_digest: Digest
    stages: list[WorkflowStage] = Field(min_length=1, max_length=64)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=256)


class WorkflowUpdate(WorkflowCommand):
    expected_revision: int = Field(strict=True, ge=1)
    content_digest: Digest


class ImportRunCommand(HumanCommand):
    run_id: UUID
    content_digest: Digest
    confirm_share: Literal[True]

    @field_validator("confirm_share", mode="before")
    @classmethod
    def exact_consent(cls, value):
        if value is not True:
            message = "Explicit sharing consent is required"
            raise ValueError(message)
        return value


class SuiteCommand(HumanCommand):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    contract_id: UUID
    contract_revision: int = Field(strict=True, ge=1)
    contract_digest: Digest
    cases: list[VerificationCase] = Field(min_length=1, max_length=16)


class SuiteUpdate(SuiteCommand):
    expected_revision: int = Field(strict=True, ge=1)
    content_digest: Digest

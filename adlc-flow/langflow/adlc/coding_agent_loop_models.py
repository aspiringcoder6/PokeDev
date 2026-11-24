"""Kernel-owned evidence for approved contracts composed with behavioral task loops."""

from __future__ import annotations

from typing import Literal
from uuid import UUID  # noqa: TC003 - Pydantic field.

from pydantic import Field, model_validator

from langflow.adlc.contract_execution_models import CriterionEvidence  # noqa: TC001 - Pydantic field.
from langflow.adlc.contract_models import ContractReference  # noqa: TC001 - Pydantic field.
from langflow.adlc.task_loop_models import Digest, FileContent, LoopModel, validate_files


class ContractFileProposal(LoopModel):
    """Untrusted file replacements, never authority, paths, deletes, or executable commands."""

    files: dict[str, FileContent] = Field(max_length=64)

    @model_validator(mode="after")
    def bounded_files(self) -> ContractFileProposal:
        validate_files(self.files)
        return self


class CodingAgentContractVerification(LoopModel):
    schema_version: Literal["0.1"] = "0.1"
    contract_reference: ContractReference
    policy_digest: Digest
    spec_digest: Digest
    candidate_id: UUID
    candidate_digest: Digest
    changed_paths: tuple[str, ...] = Field(max_length=64)
    checks: tuple[CriterionEvidence, ...] = Field(min_length=1, max_length=256)
    execution_policy_enforced: Literal[True] = True
    natural_language_enforced: Literal[False] = False

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

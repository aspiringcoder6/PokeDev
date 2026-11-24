"""H5B host projections; the published H5A document schemas remain unchanged."""

from typing import Annotated, Literal

from pydantic import Field

from langflow.adlc.contract_models import ClosedContractModel, ContractReference

AUTHORING_SUMMARY = "Tool-authored roadmap saved in ADLC; contract approval and execution are separate."


class ContractReferenceOutput(ClosedContractModel):
    contract_reference: ContractReference


class SkilltreeAuthoringOutcome(ClosedContractModel):
    summary: Literal["Tool-authored roadmap saved in ADLC; contract approval and execution are separate."] = (
        AUTHORING_SUMMARY
    )
    outputs: ContractReferenceOutput
    contract_status: Literal["VALIDATED", "APPROVED"]
    criteria_executed: Literal[False] = False
    execution_policy_enforced: Literal[False] = False


class ContractAuthoringReadCommand(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    operation: Literal["read-authoring-result"]
    session_id: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")]


class ContractViewerCapabilities(ClosedContractModel):
    schema_version: Literal["0.1"] = "0.1"
    enabled: Literal[True] = True
    human_login_required: Literal[True] = True
    human_actions_configured: bool
    renderer_refs: list[str] = ["adlc-renderer:skilltree/0.1"]
    execution_policy_enforced: Literal[False] = False

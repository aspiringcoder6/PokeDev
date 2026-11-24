"""Stable error surface for the Planner Agent proposal slice."""

from __future__ import annotations

from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import PlanValidationIssue

PLANNER_PROPOSAL_NOT_FOUND = "PLANNER_PROPOSAL_NOT_FOUND"
PLANNER_PROPOSAL_STATE_CONFLICT = "PLANNER_PROPOSAL_STATE_CONFLICT"
PLANNER_UNAVAILABLE = "PLANNER_UNAVAILABLE"
PLANNER_TIMEOUT = "PLANNER_TIMEOUT"
PLANNER_MALFORMED_OUTPUT = "PLANNER_MALFORMED_OUTPUT"
PLANNER_DECOMPOSITION_FAILED = "PLANNER_DECOMPOSITION_FAILED"


class ProposalError(RuntimeError):
    """Base class carrying a stable machine-readable code."""

    code = "PLANNER_PROPOSAL_ERROR"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict = details or {}


class ProposalNotFoundError(ProposalError):
    code = PLANNER_PROPOSAL_NOT_FOUND


class ProposalStateError(ProposalError):
    code = PLANNER_PROPOSAL_STATE_CONFLICT


class PlannerGenerationError(ProposalError):
    """Raised when the planner itself fails (LLM unavailable, timeout, malformed)."""


class ProposalValidationError(ProposalError):
    """Raised when an invalid proposal is submitted to a state-forbidding command."""

    def __init__(
        self,
        message: str,
        *,
        issues: list[PlanValidationIssue] | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.issues = issues or []


def proposal_not_found(proposal_id: object) -> NoReturn:
    raise ProposalNotFoundError(f"Plan proposal {proposal_id} was not found")

"""Stable failures raised by ADLC blueprint parsing and plan storage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langflow.adlc.blueprints.errors import BLUEPRINT_INVALID, AuthoringContractError

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import PlanValidationIssue

PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
PLAN_NOT_ACCEPTED = "PLAN_NOT_ACCEPTED"
PLAN_INTEGRITY_MISMATCH = "PLAN_INTEGRITY_MISMATCH"
PLAN_STATE_CONFLICT = "PLAN_STATE_CONFLICT"
PLAN_GATE_UNSUPPORTED = "PLAN_GATE_UNSUPPORTED"
PLAN_NO_CAPABLE_PLUGIN = "NO_CAPABLE_PLUGIN"


class BlueprintParseError(AuthoringContractError):
    """A marked Langflow graph could not be normalized into a workflow definition."""

    def __init__(self, issues: list[PlanValidationIssue]) -> None:
        message = "The saved flow is not a valid ADLC blueprint"
        super().__init__(
            BLUEPRINT_INVALID,
            message,
            details={"issues": [issue.model_dump(mode="json", exclude_none=True) for issue in issues]},
        )
        self.issues = tuple(issues)


class ExecutionPlanNotFoundError(LookupError):
    """An execution plan is absent or is not visible to the caller."""


class ExecutionPlanStateError(RuntimeError):
    """A plan command conflicts with its lifecycle or immutable snapshot."""

    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

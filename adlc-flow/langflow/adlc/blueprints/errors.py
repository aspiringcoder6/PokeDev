"""Stable authoring and package-resolution errors."""

from __future__ import annotations

from typing import Any

CAPABILITY_NOT_REGISTERED = "CAPABILITY_NOT_REGISTERED"
CAPABILITY_NOT_AUTHORIZED = "CAPABILITY_NOT_AUTHORIZED"
BLUEPRINT_EDGE_INVALID = "BLUEPRINT_EDGE_INVALID"
BLUEPRINT_INVALID = "BLUEPRINT_INVALID"
BLUEPRINT_MARKER_INVALID = "BLUEPRINT_MARKER_INVALID"
BLUEPRINT_MARKER_MISSING = "BLUEPRINT_MARKER_MISSING"
BLUEPRINT_NODE_INVALID = "BLUEPRINT_NODE_INVALID"
BLUEPRINT_REQUIRES_EXECUTION_PLAN = "BLUEPRINT_REQUIRES_EXECUTION_PLAN"
PACKAGE_CONFIGURATION_INVALID = "PACKAGE_CONFIGURATION_INVALID"
PACKAGE_DEFINITION_INVALID = "PACKAGE_DEFINITION_INVALID"
PACKAGE_DEPRECATED = "PACKAGE_DEPRECATED"
PACKAGE_DIGEST_MISMATCH = "PACKAGE_DIGEST_MISMATCH"
PACKAGE_INCOMPATIBLE = "PACKAGE_INCOMPATIBLE"
PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
PACKAGE_NOT_VISIBLE = "PACKAGE_NOT_VISIBLE"
PACKAGE_NOT_PUBLISHED = "PACKAGE_NOT_PUBLISHED"
PACKAGE_OVERRIDE_FORBIDDEN = "PACKAGE_OVERRIDE_FORBIDDEN"
PACKAGE_PATH_MISMATCH = "PACKAGE_PATH_MISMATCH"
PACKAGE_REGISTRY_NOT_FOUND = "PACKAGE_REGISTRY_NOT_FOUND"
PACKAGE_SCHEMA_INVALID = "PACKAGE_SCHEMA_INVALID"
PACKAGE_VERSION_DUPLICATE = "PACKAGE_VERSION_DUPLICATE"
RAW_SECRET_FORBIDDEN = "RAW_SECRET_FORBIDDEN"  # noqa: S105 - stable validation error code
STAGE_BINDING_INCOMPATIBLE = "STAGE_BINDING_INCOMPATIBLE"
STAGE_DEPENDENCY_CYCLE = "STAGE_DEPENDENCY_CYCLE"
STAGE_DEPENDENCY_MISSING = "STAGE_DEPENDENCY_MISSING"
STAGE_GATE_UNSUPPORTED = "STAGE_GATE_UNSUPPORTED"
STAGE_ID_DUPLICATE = "STAGE_ID_DUPLICATE"
STAGE_INPUT_AMBIGUOUS = "STAGE_INPUT_AMBIGUOUS"
STAGE_INPUT_UNBOUND = "STAGE_INPUT_UNBOUND"
STAGE_INPUT_UNKNOWN = "STAGE_INPUT_UNKNOWN"
STAGE_ISOLATED = "STAGE_ISOLATED"
STAGE_OUTPUT_UNKNOWN = "STAGE_OUTPUT_UNKNOWN"
WORKFLOW_HAS_NO_ROOT = "WORKFLOW_HAS_NO_ROOT"


class AuthoringContractError(ValueError):
    """Base error exposed by the ADLC authoring boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        """Return an API-safe error projection."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }
        if self.path is not None:
            payload["path"] = self.path
        return payload


class PackageRegistryError(AuthoringContractError):
    """Package storage, parsing, or lookup failed."""


class PackageResolutionError(AuthoringContractError):
    """A stage could not be resolved into an executable snapshot."""


class PackageAccessError(AuthoringContractError):
    """Current package or capability authorization denied an operation."""

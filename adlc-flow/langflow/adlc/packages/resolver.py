"""Resolve workflow stages into immutable, execution-ready node snapshots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import NAMESPACE_URL, UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.errors import (
    CAPABILITY_NOT_REGISTERED,
    PACKAGE_CONFIGURATION_INVALID,
    PACKAGE_DEPRECATED,
    PACKAGE_INCOMPATIBLE,
    PACKAGE_OVERRIDE_FORBIDDEN,
    RAW_SECRET_FORBIDDEN,
    PackageAccessError,
    PackageRegistryError,
    PackageResolutionError,
)
from langflow.adlc.blueprints.models import (
    AUTHORING_CONTRACT_VERSION,
    ExecutionProfile,
    NodeDefaultPolicies,
    NodePackageStatus,
    PackageReference,
    ResolvedNodeSpec,
    WorkflowStage,
)
from langflow.adlc.blueprints.security import find_raw_secret_path
from langflow.adlc.coding_agent import coding_agent_document, is_unified_coding_agent
from langflow.adlc.observability import (
    NOOP_ADLC_OBSERVABILITY_SINK,
    AdlcObservabilitySink,
    AdlcObservationOutcome,
    AdlcObservationType,
    elapsed_milliseconds,
    observation_error_code,
    observation_outcome_for_exception,
    record_observation_safely,
)
from langflow.adlc.packages.access import (
    AllowAllPackageAccessPolicy,
    PackageAccessPolicy,
    execution_references,
)

if TYPE_CHECKING:
    from langflow.adlc.packages.registry import NodePackageRegistry, RegisteredNodePackage

RESOLVER_VERSION = "0.1.0"
ENGINE_VERSION = "0.1.0"
EXECUTION_CONTRACT_VERSION = "0.1"


@runtime_checkable
class ReferenceRegistry(Protocol):
    """Read-only view of trusted provider, policy, and capability references."""

    def contains(self, reference: str) -> bool:
        """Return whether an opaque reference is registered and visible."""
        ...


@dataclass(frozen=True, slots=True)
class StaticReferenceRegistry:
    """Small deterministic reference registry for mock execution and tests."""

    references: frozenset[str]

    def contains(self, reference: str) -> bool:
        return reference in self.references


class NodePackageResolver:
    """Apply trusted package defaults and authorized workflow-stage overrides."""

    def __init__(
        self,
        package_registry: NodePackageRegistry,
        reference_registry: ReferenceRegistry,
        *,
        engine_version: str = ENGINE_VERSION,
        execution_contract_version: str = EXECUTION_CONTRACT_VERSION,
        resolver_version: str = RESOLVER_VERSION,
        allow_deprecated: bool = False,
        access_policy: PackageAccessPolicy | None = None,
        observability_sink: AdlcObservabilitySink | None = None,
        configuration_validator=None,
    ) -> None:
        self._packages = package_registry
        self._references = reference_registry
        self._engine_version = engine_version
        self._execution_contract_version = execution_contract_version
        self._resolver_version = resolver_version
        self._allow_deprecated = allow_deprecated
        self._access_policy = access_policy if access_policy is not None else AllowAllPackageAccessPolicy()
        self._observability = observability_sink if observability_sink is not None else NOOP_ADLC_OBSERVABILITY_SINK
        self._configuration_validator = configuration_validator

    def resolve(
        self,
        stage: WorkflowStage,
        *,
        workflow_definition_id: UUID,
        workflow_definition_version: int,
        workflow_policy_overrides: dict[str, Any] | None = None,
        runtime_overrides: dict[str, Any] | None = None,
        resolved_at: datetime | None = None,
        access_subject: str | None = None,
    ) -> ResolvedNodeSpec:
        """Resolve one stage without invoking an executor or mutating runtime state."""
        started_at_ns = perf_counter_ns()
        try:
            resolved = self._resolve(
                stage,
                workflow_definition_id=workflow_definition_id,
                workflow_definition_version=workflow_definition_version,
                workflow_policy_overrides=workflow_policy_overrides,
                runtime_overrides=runtime_overrides,
                resolved_at=resolved_at,
                access_subject=access_subject,
            )
        except Exception as exc:
            record_observation_safely(
                self._observability,
                event_type=AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED,
                outcome=observation_outcome_for_exception(exc),
                duration_ms=elapsed_milliseconds(started_at_ns),
                error_code=observation_error_code(exc, "PACKAGE_RESOLUTION_FAILED"),
                workflow_definition_id=workflow_definition_id,
                workflow_definition_version=workflow_definition_version,
                source_workflow_stage_id=stage.stage_id,
            )
            raise

        record_observation_safely(
            self._observability,
            event_type=AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED,
            outcome=AdlcObservationOutcome.SUCCEEDED,
            duration_ms=elapsed_milliseconds(started_at_ns),
            workflow_definition_id=workflow_definition_id,
            workflow_definition_version=workflow_definition_version,
            source_workflow_stage_id=stage.stage_id,
            resolved_node_spec_id=resolved.resolved_node_spec_id,
            package_id=resolved.package_ref.package_id,
            package_version=resolved.package_ref.version,
            package_content_digest=resolved.package_ref.content_digest,
            resolved_node_digest=resolved.resolved_digest,
            resolved_node_count=1,
        )
        return resolved

    def _resolve(
        self,
        stage: WorkflowStage,
        *,
        workflow_definition_id: UUID,
        workflow_definition_version: int,
        workflow_policy_overrides: dict[str, Any] | None = None,
        runtime_overrides: dict[str, Any] | None = None,
        resolved_at: datetime | None = None,
        access_subject: str | None = None,
    ) -> ResolvedNodeSpec:
        registered = self._get_package(stage.package_ref)
        package = registered.definition
        if access_subject is not None:
            try:
                self._access_policy.ensure_package_visible(access_subject, stage.package_ref)
            except PackageAccessError as exc:
                raise _resolution_error_from_access(exc) from exc
        package_status = self._access_policy.package_status(stage.package_ref, package.status)
        if package_status is NodePackageStatus.DEPRECATED and not self._allow_deprecated:
            message = f"Node package {package.package_id}@{package.version} is deprecated"
            raise PackageResolutionError(
                PACKAGE_DEPRECATED,
                message,
                details={"package_id": package.package_id, "version": package.version},
            )
        self._validate_compatibility(registered)

        workflow_policy_overrides = workflow_policy_overrides or {}
        runtime_overrides = runtime_overrides or {}
        stage_overrides = {
            "configuration": stage.configuration_overrides,
            "execution_profile": stage.execution_profile_overrides,
            "policies": stage.policy_overrides,
        }
        workflow_overrides = {"policies": workflow_policy_overrides}
        self._reject_raw_secrets(stage_overrides, source="stage overrides")
        self._reject_raw_secrets(workflow_overrides, source="workflow defaults")
        self._reject_raw_secrets(runtime_overrides, source="runtime overrides")
        self._reject_raw_secrets(stage.metadata, source="stage metadata")

        document: dict[str, Any] = {
            "configuration": deepcopy(package.defaults),
            "execution_profile": (
                package.execution_profile.model_dump(mode="json", exclude_none=False)
                if package.execution_profile is not None
                else None
            ),
            "policies": package.default_policies.model_dump(mode="json", exclude_none=False),
        }
        implementation = package.implementation
        interface = package.interface
        unified = is_unified_coding_agent(package.package_id, package.version)
        coding_mode = None
        if unified:
            _merge_authorized(
                document,
                {"configuration": stage.configuration_overrides},
                allowlist=package.override_allowlist,
                source="stage overrides",
            )
            public_configuration = self._validate_configuration(document["configuration"], registered)
            document, implementation, interface, coding_mode = coding_agent_document(
                package, public_configuration, stage.inputs
            )
            stage_overrides.pop("configuration")
        _merge_authorized(
            document,
            workflow_overrides,
            allowlist=package.override_allowlist,
            source="workflow defaults",
        )
        _merge_authorized(
            document,
            stage_overrides,
            allowlist=package.override_allowlist,
            source="stage overrides",
        )

        policies = self._parse_policies(document["policies"], registered)
        _merge_authorized(
            document,
            runtime_overrides,
            allowlist=policies.runtime_overridable,
            source="runtime overrides",
        )
        policies = self._parse_policies(document["policies"], registered)
        configuration = (
            deepcopy(document["configuration"])
            if unified
            else self._validate_configuration(document["configuration"], registered)
        )
        if package.package_id == "coding-agent-contract-harness" or (
            unified and configuration.get("approved_contract_ref") is not None
        ):
            if self._configuration_validator is None:
                raise PackageResolutionError(PACKAGE_CONFIGURATION_INVALID, "Contract execution validator is required.")
            self._configuration_validator(package.package_id, configuration, access_subject)
        execution_profile = self._parse_execution_profile(document["execution_profile"], registered)
        reference_count = self._validate_references(
            registered,
            execution_profile,
            access_subject=access_subject,
            implementation=implementation,
        )

        secret_refs = dict(execution_profile.secret_refs) if execution_profile is not None else {}
        secret_refs.update(stage.secret_refs)
        package_ref = PackageReference(
            package_id=package.package_id,
            version=package.version,
            content_digest=registered.content_digest,
        )
        digest_payload = {
            "schema_version": AUTHORING_CONTRACT_VERSION,
            "workflow_definition_id": workflow_definition_id,
            "workflow_definition_version": workflow_definition_version,
            "source_stage_id": stage.stage_id,
            "package_ref": package_ref,
            "kind": package.kind,
            "implementation": implementation,
            "interface": interface,
            "configuration": configuration,
            "execution_profile": execution_profile,
            "policies": policies,
            "secret_refs": secret_refs,
        }
        resolved_digest = sha256_digest(digest_payload)
        spec_id = uuid5(
            NAMESPACE_URL,
            f"adlc:resolved-node-spec:{workflow_definition_id}:{workflow_definition_version}:{stage.stage_id}:{resolved_digest}",
        )
        timestamp = resolved_at or datetime.now(timezone.utc)
        if timestamp.utcoffset() is None:
            message = "resolved_at must include a timezone"
            raise ValueError(message)

        return ResolvedNodeSpec(
            schema_version=AUTHORING_CONTRACT_VERSION,
            resolved_node_spec_id=spec_id,
            workflow_definition_id=workflow_definition_id,
            workflow_definition_version=workflow_definition_version,
            source_stage_id=stage.stage_id,
            package_ref=package_ref,
            kind=package.kind,
            implementation=implementation,
            interface=interface,
            configuration=configuration,
            execution_profile=execution_profile,
            policies=policies,
            secret_refs=secret_refs,
            resolved_digest=resolved_digest,
            resolver_version=self._resolver_version,
            resolved_at=timestamp,
            validation_evidence=[
                f"package-digest:{registered.content_digest}",
                "configuration-schema:draft-2020-12",
                f"trusted-references:{reference_count}",
            ],
            metadata={
                "package_status": package_status.value,
                "stage_type": stage.stage_type,
                "stage_metadata": deepcopy(stage.metadata),
                **({"coding_agent_features": coding_mode} if coding_mode is not None else {}),
            },
        )

    def _get_package(self, package_ref: PackageReference) -> RegisteredNodePackage:
        try:
            return self._packages.get(package_ref)
        except PackageRegistryError as exc:
            raise PackageResolutionError(
                exc.code,
                exc.message,
                path=exc.path,
                details=exc.details,
            ) from exc

    def _validate_compatibility(self, registered: RegisteredNodePackage) -> None:
        compatibility = registered.definition.compatibility
        engine_supported = _semver_key(self._engine_version) >= _semver_key(compatibility.engine.minimum_version)
        contract_supported = self._execution_contract_version in compatibility.execution_contract_versions
        if engine_supported and contract_supported:
            return
        package = registered.definition
        message = f"Node package {package.package_id}@{package.version} is incompatible with this engine"
        raise PackageResolutionError(
            PACKAGE_INCOMPATIBLE,
            message,
            details={
                "engine_version": self._engine_version,
                "minimum_engine_version": compatibility.engine.minimum_version,
                "execution_contract_version": self._execution_contract_version,
                "supported_execution_contract_versions": compatibility.execution_contract_versions,
            },
        )

    @staticmethod
    def _validate_configuration(
        configuration: object,
        registered: RegisteredNodePackage,
    ) -> dict[str, Any]:
        errors = sorted(
            Draft202012Validator(
                registered.definition.configuration_schema,
                format_checker=FormatChecker(),
            ).iter_errors(configuration),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            pointer = "/configuration/" + "/".join(str(part) for part in error.absolute_path)
            package = registered.definition
            message = f"Configuration for {package.package_id}@{package.version} is invalid: {error.message}"
            raise PackageResolutionError(
                PACKAGE_CONFIGURATION_INVALID,
                message,
                path=pointer.rstrip("/"),
                details={"package_id": package.package_id, "version": package.version},
            )
        if not isinstance(configuration, dict):
            message = "Node-package configuration must resolve to an object"
            raise PackageResolutionError(PACKAGE_CONFIGURATION_INVALID, message)
        return deepcopy(configuration)

    @staticmethod
    def _parse_policies(value: object, registered: RegisteredNodePackage) -> NodeDefaultPolicies:
        try:
            return NodeDefaultPolicies.model_validate(value)
        except ValidationError as exc:
            package = registered.definition
            message = f"Policies for {package.package_id}@{package.version} are invalid"
            raise PackageResolutionError(
                PACKAGE_CONFIGURATION_INVALID,
                message,
                path="/policies",
                details={"reason": str(exc)},
            ) from exc

    @staticmethod
    def _parse_execution_profile(
        value: object,
        registered: RegisteredNodePackage,
    ) -> ExecutionProfile | None:
        if value is None:
            return None
        try:
            return ExecutionProfile.model_validate(value)
        except ValidationError as exc:
            package = registered.definition
            message = f"Execution profile for {package.package_id}@{package.version} is invalid"
            raise PackageResolutionError(
                PACKAGE_CONFIGURATION_INVALID,
                message,
                path="/execution_profile",
                details={"reason": str(exc)},
            ) from exc

    def _validate_references(
        self,
        registered: RegisteredNodePackage,
        execution_profile: ExecutionProfile | None,
        *,
        access_subject: str | None,
        implementation=None,
    ) -> int:
        unique_references = execution_references(
            implementation or registered.definition.implementation, execution_profile
        )
        for reference in unique_references:
            if not self._references.contains(reference):
                package = registered.definition
                message = f"Unregistered reference {reference} in {package.package_id}@{package.version}"
                raise PackageResolutionError(
                    CAPABILITY_NOT_REGISTERED,
                    message,
                    details={
                        "package_id": package.package_id,
                        "version": package.version,
                        "reference": reference,
                    },
                )
        if access_subject is not None:
            package = registered.definition
            package_ref = PackageReference(package_id=package.package_id, version=package.version)
            try:
                self._access_policy.ensure_references_authorized(
                    access_subject,
                    package_ref,
                    unique_references,
                )
            except PackageAccessError as exc:
                raise _resolution_error_from_access(exc) from exc
        return len(unique_references)

    @staticmethod
    def _reject_raw_secrets(value: object, *, source: str) -> None:
        path = find_raw_secret_path(value)
        if path is None:
            return
        message = f"Raw secret-like field in {source} is forbidden at {path}"
        raise PackageResolutionError(RAW_SECRET_FORBIDDEN, message, path=path)


def _merge_authorized(
    target: dict[str, Any],
    overrides: dict[str, Any],
    *,
    allowlist: list[str],
    source: str,
) -> None:
    for pointer in _leaf_pointers(overrides):
        if not _path_is_allowed(pointer, allowlist):
            message = f"{source} cannot override {pointer}"
            raise PackageResolutionError(
                PACKAGE_OVERRIDE_FORBIDDEN,
                message,
                path=pointer,
                details={"source": source},
            )
    _deep_merge(target, overrides)


def _leaf_pointers(value: dict[str, Any], *, prefix: str = "") -> tuple[str, ...]:
    pointers: list[str] = []
    for key, item in value.items():
        escaped_key = key.replace("~", "~0").replace("/", "~1")
        pointer = f"{prefix}/{escaped_key}"
        if isinstance(item, dict):
            if item:
                pointers.extend(_leaf_pointers(item, prefix=pointer))
            continue
        pointers.append(pointer)
    return tuple(pointers)


def _path_is_allowed(pointer: str, allowlist: list[str]) -> bool:
    return any(pointer == allowed or pointer.startswith(f"{allowed}/") for allowed in allowlist)


def _deep_merge(target: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and not value:
            continue
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge(current, value)
        else:
            target[key] = deepcopy(value)


def _semver_key(value: str) -> tuple[int, int, int, int, str]:
    without_build = value.split("+", maxsplit=1)[0]
    core, separator, prerelease = without_build.partition("-")
    major, minor, patch = (int(part) for part in core.split("."))
    return major, minor, patch, int(not separator), prerelease


def _resolution_error_from_access(exc: PackageAccessError) -> PackageResolutionError:
    return PackageResolutionError(
        exc.code,
        exc.message,
        path=exc.path,
        details=exc.details,
    )

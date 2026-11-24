"""Caller-scoped package visibility, capability authorization, and lifecycle overlay."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from langflow.adlc.blueprints.errors import (
    CAPABILITY_NOT_AUTHORIZED,
    PACKAGE_NOT_VISIBLE,
    PackageAccessError,
)
from langflow.adlc.blueprints.models import NodePackageStatus, PackageReference

if TYPE_CHECKING:
    from collections.abc import Iterable

    from langflow.adlc.blueprints.models import ExecutionPlan, ExecutionProfile, NodeImplementation, ResolvedNodeSpec

PackageIdentity = tuple[str, str]


@dataclass(frozen=True, slots=True)
class PackageAccessGrants:
    """Exact package versions and opaque execution references granted to one subject."""

    visible_packages: frozenset[PackageIdentity]
    authorized_references: frozenset[str]


@runtime_checkable
class PackageAccessPolicy(Protocol):
    """Authorization seam used by catalogue, compiler, and materializer boundaries."""

    def can_view_package(self, subject_id: str, package_ref: PackageReference) -> bool:
        """Return whether an exact package version is discoverable by the subject."""
        ...

    def ensure_package_visible(self, subject_id: str, package_ref: PackageReference) -> None:
        """Reject use of an exact package version that is not visible."""
        ...

    def ensure_references_authorized(
        self,
        subject_id: str,
        package_ref: PackageReference,
        references: Iterable[str],
    ) -> None:
        """Reject execution references not granted to the subject."""
        ...

    def ensure_plan_authorized(self, subject_id: str, plan: ExecutionPlan) -> None:
        """Recheck current grants for an accepted immutable plan snapshot."""
        ...

    def package_status(
        self,
        package_ref: PackageReference,
        declared_status: NodePackageStatus,
    ) -> NodePackageStatus:
        """Project lifecycle metadata without rewriting immutable package bytes."""
        ...


class AllowAllPackageAccessPolicy:
    """Compatibility policy for isolated resolver use outside the authenticated API."""

    def can_view_package(self, subject_id: str, package_ref: PackageReference) -> bool:  # noqa: ARG002
        return True

    def ensure_package_visible(self, subject_id: str, package_ref: PackageReference) -> None:  # noqa: ARG002
        return

    def ensure_references_authorized(
        self,
        subject_id: str,  # noqa: ARG002
        package_ref: PackageReference,  # noqa: ARG002
        references: Iterable[str],  # noqa: ARG002
    ) -> None:
        return

    def ensure_plan_authorized(self, subject_id: str, plan: ExecutionPlan) -> None:  # noqa: ARG002
        return

    def package_status(
        self,
        package_ref: PackageReference,  # noqa: ARG002
        declared_status: NodePackageStatus,
    ) -> NodePackageStatus:
        return declared_status


class InMemoryPackageAccessPolicy:
    """Thread-safe allow-list policy for the mock slice and deterministic tests."""

    def __init__(
        self,
        *,
        default_visible_packages: Iterable[PackageIdentity],
        default_authorized_references: Iterable[str],
        deprecated_packages: Iterable[PackageIdentity] = (),
    ) -> None:
        self._default_grants = PackageAccessGrants(
            visible_packages=frozenset(default_visible_packages),
            authorized_references=frozenset(default_authorized_references),
        )
        self._subject_grants: dict[str, PackageAccessGrants] = {}
        self._deprecated_packages = set(deprecated_packages)
        self._lock = RLock()

    def set_subject_grants(
        self,
        subject_id: str,
        *,
        visible_packages: Iterable[PackageIdentity],
        authorized_references: Iterable[str],
    ) -> None:
        """Replace one subject's grants atomically."""
        with self._lock:
            self._subject_grants[subject_id] = PackageAccessGrants(
                visible_packages=frozenset(visible_packages),
                authorized_references=frozenset(authorized_references),
            )

    def clear_subject_grants(self, subject_id: str) -> None:
        """Return one subject to the process-wide default grants."""
        with self._lock:
            self._subject_grants.pop(subject_id, None)

    def deprecate_package(self, package_id: str, version: str) -> None:
        """Mark an immutable package version deprecated in catalogue metadata."""
        with self._lock:
            self._deprecated_packages.add((package_id, version))

    def restore_package(self, package_id: str, version: str) -> None:
        """Remove the process-local deprecation overlay."""
        with self._lock:
            self._deprecated_packages.discard((package_id, version))

    def can_view_package(self, subject_id: str, package_ref: PackageReference) -> bool:
        with self._lock:
            return _package_identity(package_ref) in self._grants_for(subject_id).visible_packages

    def ensure_package_visible(self, subject_id: str, package_ref: PackageReference) -> None:
        if self.can_view_package(subject_id, package_ref):
            return
        raise PackageAccessError(
            PACKAGE_NOT_VISIBLE,
            "The requested node package is not visible to this caller.",
            details={"package_id": package_ref.package_id, "version": package_ref.version},
        )

    def ensure_references_authorized(
        self,
        subject_id: str,
        package_ref: PackageReference,
        references: Iterable[str],
    ) -> None:
        with self._lock:
            authorized = self._grants_for(subject_id).authorized_references
            denied = sorted(set(references) - authorized)
        if not denied:
            return
        raise PackageAccessError(
            CAPABILITY_NOT_AUTHORIZED,
            f"The caller is not authorized to use {denied[0]}.",
            details={
                "package_id": package_ref.package_id,
                "version": package_ref.version,
                "reference": denied[0],
                "unauthorized_references": denied,
            },
        )

    def ensure_plan_authorized(self, subject_id: str, plan: ExecutionPlan) -> None:
        with self._lock:
            for spec in sorted(plan.resolved_node_specs, key=lambda item: str(item.source_stage_id)):
                self.ensure_package_visible(subject_id, spec.package_ref)
                self.ensure_references_authorized(
                    subject_id,
                    spec.package_ref,
                    resolved_spec_references(spec),
                )

    def package_status(
        self,
        package_ref: PackageReference,
        declared_status: NodePackageStatus,
    ) -> NodePackageStatus:
        with self._lock:
            deprecated = _package_identity(package_ref) in self._deprecated_packages
        return NodePackageStatus.DEPRECATED if deprecated else declared_status

    def _grants_for(self, subject_id: str) -> PackageAccessGrants:
        return self._subject_grants.get(subject_id, self._default_grants)


def execution_references(
    implementation: NodeImplementation,
    execution_profile: ExecutionProfile | None,
) -> tuple[str, ...]:
    """Return the deterministic set of opaque references required by a resolved node."""
    references = [implementation.adapter_ref]
    if execution_profile is not None:
        references.extend(
            [
                execution_profile.provider_ref,
                execution_profile.model_ref,
                execution_profile.system_prompt_ref,
                execution_profile.memory_policy_ref,
                execution_profile.sandbox_policy_ref,
                *execution_profile.rule_set_refs,
                *execution_profile.hook_refs,
                *execution_profile.capabilities.tool_refs,
                *execution_profile.capabilities.skill_refs,
                *execution_profile.capabilities.plugin_refs,
                *execution_profile.capabilities.mcp_server_refs,
            ]
        )
    return tuple(dict.fromkeys(references))


def resolved_spec_references(spec: ResolvedNodeSpec) -> tuple[str, ...]:
    """Read required references only from an accepted resolved-node snapshot."""
    return execution_references(spec.implementation, spec.execution_profile)


def _package_identity(package_ref: PackageReference) -> PackageIdentity:
    return package_ref.package_id, package_ref.version

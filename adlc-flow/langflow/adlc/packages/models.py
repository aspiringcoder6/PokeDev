"""HTTP-safe package-registry projections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langflow.adlc.blueprints.models import NodePackageDefinition, NodePackageStatus, Sha256Digest

if TYPE_CHECKING:
    from langflow.adlc.packages.registry import RegisteredNodePackage


class NodePackageRead(NodePackageDefinition):
    """Immutable package definition plus digest and external lifecycle projection."""

    content_digest: Sha256Digest
    lifecycle_status: NodePackageStatus

    @classmethod
    def from_registered(
        cls,
        registered: RegisteredNodePackage,
        *,
        effective_status: NodePackageStatus | None = None,
    ) -> NodePackageRead:
        return cls(
            **registered.definition.model_dump(mode="python", exclude_none=False),
            content_digest=registered.content_digest,
            lifecycle_status=effective_status or registered.definition.status,
        )

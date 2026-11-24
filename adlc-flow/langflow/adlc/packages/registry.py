"""Immutable repository-backed registry for versioned ADLC node packages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import canonical_json_bytes, package_content_digest
from langflow.adlc.blueprints.errors import (
    PACKAGE_CONFIGURATION_INVALID,
    PACKAGE_DEFINITION_INVALID,
    PACKAGE_DIGEST_MISMATCH,
    PACKAGE_NOT_FOUND,
    PACKAGE_NOT_PUBLISHED,
    PACKAGE_PATH_MISMATCH,
    PACKAGE_REGISTRY_NOT_FOUND,
    PACKAGE_SCHEMA_INVALID,
    PACKAGE_VERSION_DUPLICATE,
    RAW_SECRET_FORBIDDEN,
    PackageRegistryError,
)
from langflow.adlc.blueprints.models import NodePackageDefinition, NodePackageStatus, PackageReference
from langflow.adlc.blueprints.security import find_raw_secret_path

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class RegisteredNodePackage:
    """One caller-owned view of a registered immutable package version."""

    definition: NodePackageDefinition
    content_digest: str
    source_path: Path


@runtime_checkable
class NodePackageRegistry(Protocol):
    """Exact-version package lookup used by the blueprint resolver."""

    def get(self, package_ref: PackageReference) -> RegisteredNodePackage:
        """Return an exact package version or raise a stable registry error."""
        ...

    def list_packages(self) -> tuple[RegisteredNodePackage, ...]:
        """Return every registered package version in deterministic order."""
        ...


@dataclass(frozen=True, slots=True)
class _StoredNodePackage:
    payload: bytes
    content_digest: str
    source_path: Path

    def materialize(self) -> RegisteredNodePackage:
        definition = NodePackageDefinition.model_validate_json(self.payload)
        return RegisteredNodePackage(
            definition=definition,
            content_digest=self.content_digest,
            source_path=self.source_path,
        )


class RepositoryNodePackageRegistry:
    """Load package definitions from ``<root>/<id>/<version>/package.json``."""

    def __init__(self, root: Path, *, eager: bool = True) -> None:
        self._root = root.resolve()
        self._packages: dict[tuple[str, str], _StoredNodePackage] | None = None
        if eager:
            self.refresh()

    @property
    def root(self) -> Path:
        return self._root

    def refresh(self) -> None:
        """Atomically replace the in-memory view after validating every package."""
        if not self._root.is_dir():
            message = f"Node-package registry directory does not exist: {self._root}"
            raise PackageRegistryError(
                PACKAGE_REGISTRY_NOT_FOUND,
                message,
                details={"root": str(self._root)},
            )

        registered_packages: list[RegisteredNodePackage] = []
        identities: dict[tuple[str, str], Path] = {}
        for package_path in sorted(self._root.rglob("package.json")):
            registered = self._load_file(package_path)
            key = (registered.definition.package_id, registered.definition.version)
            if key in identities:
                message = f"Duplicate node-package version: {key[0]}@{key[1]}"
                raise PackageRegistryError(
                    PACKAGE_VERSION_DUPLICATE,
                    message,
                    details={
                        "package_id": key[0],
                        "version": key[1],
                        "paths": [str(identities[key]), str(package_path)],
                    },
                )
            identities[key] = package_path
            registered_packages.append(registered)

        loaded: dict[tuple[str, str], _StoredNodePackage] = {}
        for registered in registered_packages:
            self._validate_repository_path(registered)
            key = (registered.definition.package_id, registered.definition.version)
            loaded[key] = _StoredNodePackage(
                payload=canonical_json_bytes(registered.definition),
                content_digest=registered.content_digest,
                source_path=registered.source_path,
            )
        if self._packages is not None:
            for key, stored in loaded.items():
                previous = self._packages.get(key)
                if previous is not None and previous.content_digest != stored.content_digest:
                    message = f"Published node package {key[0]}@{key[1]} changed during registry lifetime"
                    raise PackageRegistryError(
                        PACKAGE_DIGEST_MISMATCH,
                        message,
                        details={
                            "package_id": key[0],
                            "version": key[1],
                            "expected": previous.content_digest,
                            "actual": stored.content_digest,
                        },
                    )
        self._packages = loaded

    def get(self, package_ref: PackageReference) -> RegisteredNodePackage:
        packages = self._ensure_loaded()
        key = (package_ref.package_id, package_ref.version)
        stored = packages.get(key)
        if stored is None:
            message = f"Node package {package_ref.package_id}@{package_ref.version} was not found"
            raise PackageRegistryError(
                PACKAGE_NOT_FOUND,
                message,
                details={"package_id": package_ref.package_id, "version": package_ref.version},
            )
        if package_ref.content_digest is not None and package_ref.content_digest != stored.content_digest:
            message = f"Digest mismatch for node package {package_ref.package_id}@{package_ref.version}"
            raise PackageRegistryError(
                PACKAGE_DIGEST_MISMATCH,
                message,
                details={
                    "package_id": package_ref.package_id,
                    "version": package_ref.version,
                    "expected": package_ref.content_digest,
                    "actual": stored.content_digest,
                },
            )
        return stored.materialize()

    def list_packages(self) -> tuple[RegisteredNodePackage, ...]:
        packages = self._ensure_loaded()
        return tuple(packages[key].materialize() for key in sorted(packages))

    def _ensure_loaded(self) -> dict[tuple[str, str], _StoredNodePackage]:
        if self._packages is None:
            self.refresh()
        if self._packages is None:  # pragma: no cover - refresh either loads or raises
            msg = "Node-package registry failed to initialize"
            raise RuntimeError(msg)
        return self._packages

    def _load_file(self, package_path: Path) -> RegisteredNodePackage:
        try:
            raw = json.loads(package_path.read_text(encoding="utf-8"))
            definition = NodePackageDefinition.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            message = f"Invalid node-package definition: {package_path}"
            raise PackageRegistryError(
                PACKAGE_DEFINITION_INVALID,
                message,
                details={"path": str(package_path), "reason": str(exc)},
            ) from exc

        if definition.status is NodePackageStatus.DRAFT:
            message = f"Draft package {definition.package_id}@{definition.version} cannot enter the runtime registry"
            raise PackageRegistryError(
                PACKAGE_NOT_PUBLISHED,
                message,
                details={"path": str(package_path)},
            )

        self._validate_configuration_schema(definition, package_path)
        raw_secret_path = find_raw_secret_path(definition.model_dump(mode="json"))
        if raw_secret_path is not None:
            message = f"Raw secret-like field is forbidden at {raw_secret_path}"
            raise PackageRegistryError(
                RAW_SECRET_FORBIDDEN,
                message,
                path=raw_secret_path,
                details={"path": str(package_path)},
            )
        return RegisteredNodePackage(
            definition=definition,
            content_digest=package_content_digest(definition),
            source_path=package_path.resolve(),
        )

    def _validate_repository_path(self, registered: RegisteredNodePackage) -> None:
        definition = registered.definition
        expected_parent = self._root / definition.package_id / definition.version
        if registered.source_path.parent != expected_parent.resolve():
            message = "Package identity must match its repository directory"
            raise PackageRegistryError(
                PACKAGE_PATH_MISMATCH,
                message,
                details={
                    "path": str(registered.source_path),
                    "expected_parent": str(expected_parent),
                },
            )

    @staticmethod
    def _validate_configuration_schema(definition: NodePackageDefinition, package_path: Path) -> None:
        try:
            Draft202012Validator.check_schema(definition.configuration_schema)
        except SchemaError as exc:
            message = f"Invalid configuration schema for {definition.package_id}@{definition.version}"
            raise PackageRegistryError(
                PACKAGE_SCHEMA_INVALID,
                message,
                details={"path": str(package_path), "reason": exc.message},
            ) from exc

        errors = sorted(
            Draft202012Validator(
                definition.configuration_schema,
                format_checker=FormatChecker(),
            ).iter_errors(definition.defaults),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            pointer = "/" + "/".join(str(part) for part in error.absolute_path)
            message = f"Package defaults violate the configuration schema: {error.message}"
            raise PackageRegistryError(
                PACKAGE_CONFIGURATION_INVALID,
                message,
                path=pointer,
                details={"package_id": definition.package_id, "version": definition.version},
            )

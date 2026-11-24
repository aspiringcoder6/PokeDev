# ruff: noqa: INP001, PLR2004, S101

import json
from copy import deepcopy
from pathlib import Path

import pytest

from langflow.adlc.blueprints import PackageReference, PackageRegistryError
from langflow.adlc.packages import RepositoryNodePackageRegistry

CODING_AGENT_DIGEST = "sha256:525f8a3b9f90502064e7315e504385c7c3684427cc4bdab99956b187f96d2305"
HARNESS_H2_CODING_AGENT_DIGEST = "sha256:11f2c5beac84a4483f33b99c0ddbb925f16d1245185b4ef60f80e72327eb839e"
HARNESS_H3_CODING_AGENT_DIGEST = "sha256:d7df8e8d87f4ece4fd2360f085471d095878267e1de8fbc393275427e7dbd5b1"
OPENCODE_CODING_AGENT_DIGEST = "sha256:03d848bec6351454a3c7f34307b592b9613de58a428c958c876b0085d04c3b39"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _package_root() -> Path:
    return _repository_root() / "adlc_components" / "packages"


def _coding_agent_payload() -> dict[str, object]:
    path = _package_root() / "coding-agent" / "0.1.0" / "package.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_package(root: Path, payload: dict[str, object], *path_parts: str) -> None:
    directory = root.joinpath(*path_parts)
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps(payload), encoding="utf-8")


def test_repository_registry_loads_exact_versions_in_stable_order() -> None:
    registry = RepositoryNodePackageRegistry(_package_root())

    assert [(item.definition.package_id, item.definition.version) for item in registry.list_packages()] == [
        ("agent-memory-context", "0.1.0"),
        ("approval", "0.1.0"),
        ("coding-agent", "0.1.0"),
        ("coding-agent", "0.2.0"),
        ("coding-agent", "0.2.1"),
        ("coding-agent", "0.3.0"),
        ("coding-agent-contract-harness", "0.1.0"),
        ("coding-agent-contract-harness", "0.2.0"),
        ("coding-agent-deepseek-harness", "0.1.0"),
        ("coding-agent-deepseek-harness", "0.2.0"),
        ("coding-agent-deepseek-harness", "0.3.0"),
        ("coding-agent-deepseek-harness", "0.3.1"),
        ("coding-agent-deepseek-harness", "0.3.2"),
        ("coding-agent-opencode", "0.1.0"),
        ("harness-workflow-plan", "0.1.0"),
        ("harness-workflow-publish", "0.1.0"),
        ("harness-workflow-task", "0.1.0"),
        ("skilltree-authoring-deepseek-harness", "0.1.0"),
        ("task-loop", "0.1.0"),
        ("task-loop-opencode", "0.1.0"),
        ("testforge-replay", "0.1.0"),
        ("workflow-plugin-check", "0.1.0"),
    ]
    package = registry.get(PackageReference(package_id="coding-agent", version="0.1.0"))
    assert package.content_digest == CODING_AGENT_DIGEST

    harness_h2 = registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.1.0"))
    assert harness_h2.content_digest == HARNESS_H2_CODING_AGENT_DIGEST
    assert harness_h2.definition.implementation.adapter_ref == "agent-provider:deepseek-harness"
    assert harness_h2.definition.execution_profile.capabilities.plugin_refs == [
        "plugin:vai-adlc-driver-deepseek/0.1.0",
        "plugin:vai-adlc-runtime/0.1.0",
        "plugin:vai-adlc-verify-structured/0.1.0",
    ]

    harness_h3 = registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.2.0"))
    assert harness_h3.content_digest == HARNESS_H3_CODING_AGENT_DIGEST
    assert harness_h3.definition.execution_profile.capabilities.plugin_refs == [
        "plugin:vai-adlc-driver-deepseek/0.1.0",
        "plugin:vai-adlc-runtime/0.2.0",
        "plugin:vai-adlc-verify-structured/0.1.0",
    ]

    harness_h4 = registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.0"))
    assert harness_h4.definition.defaults["submission_mode"] == "MANUAL"
    assert harness_h4.definition.defaults["harness_profile_ref"] == "harness-profile:adlc-coding-artifacts/0.1.0"
    assert "plugin:vai-adlc-artifacts-git/0.1.0" in harness_h4.definition.execution_profile.capabilities.plugin_refs

    harness_h4_fix = registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.1"))
    assert harness_h4_fix.definition.defaults["submission_mode"] == "MANUAL"
    assert "plugin:vai-adlc-artifacts-git/0.1.1" in harness_h4_fix.definition.execution_profile.capabilities.plugin_refs
    assert harness_h4_fix.definition.defaults["plugin_lock"] != harness_h4.definition.defaults["plugin_lock"]

    harness_h4_wide = registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.2"))
    assert harness_h4_wide.definition.defaults["submission_mode"] == "MANUAL"
    assert (
        "plugin:vai-adlc-artifacts-git/0.2.0" in harness_h4_wide.definition.execution_profile.capabilities.plugin_refs
    )
    assert harness_h4_wide.definition.defaults["plugin_lock"] != harness_h4_fix.definition.defaults["plugin_lock"]

    opencode = registry.get(PackageReference(package_id="coding-agent-opencode", version="0.1.0"))
    assert opencode.content_digest == OPENCODE_CODING_AGENT_DIGEST
    assert opencode.definition.implementation.adapter_ref == "agent-provider:opencode"
    assert opencode.definition.execution_profile.sandbox_policy_ref == "sandbox:local-git-worktree/0.1.0"


def test_registry_checks_an_expected_digest() -> None:
    registry = RepositoryNodePackageRegistry(_package_root())
    reference = PackageReference(
        package_id="coding-agent",
        version="0.1.0",
        content_digest="sha256:" + ("0" * 64),
    )

    with pytest.raises(PackageRegistryError) as exc_info:
        registry.get(reference)

    assert exc_info.value.code == "PACKAGE_DIGEST_MISMATCH"
    assert exc_info.value.details["actual"] == CODING_AGENT_DIGEST


def test_registry_reports_a_missing_exact_version() -> None:
    registry = RepositoryNodePackageRegistry(_package_root())

    with pytest.raises(PackageRegistryError) as exc_info:
        registry.get(PackageReference(package_id="coding-agent", version="9.9.9"))

    assert exc_info.value.code == "PACKAGE_NOT_FOUND"


def test_registry_returns_a_copy_not_mutable_registry_state() -> None:
    registry = RepositoryNodePackageRegistry(_package_root())
    first = registry.get(PackageReference(package_id="coding-agent", version="0.1.0"))
    first.definition.defaults["delay_ms"] = 999

    second = registry.get(PackageReference(package_id="coding-agent", version="0.1.0"))

    assert second.definition.defaults["delay_ms"] == 25
    assert second.content_digest == CODING_AGENT_DIGEST


def test_registry_rejects_in_place_changes_to_a_loaded_published_version(tmp_path) -> None:
    payload = _coding_agent_payload()
    _write_package(tmp_path, payload, "coding-agent", "0.1.0")
    registry = RepositoryNodePackageRegistry(tmp_path)
    payload["description"] = "A changed published package."
    package_path = tmp_path / "coding-agent" / "0.1.0" / "package.json"
    package_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PackageRegistryError) as exc_info:
        registry.refresh()

    assert exc_info.value.code == "PACKAGE_DIGEST_MISMATCH"
    assert registry.get(PackageReference(package_id="coding-agent", version="0.1.0")).content_digest == (
        CODING_AGENT_DIGEST
    )


def test_registry_rejects_a_draft_package(tmp_path) -> None:
    payload = _coding_agent_payload()
    payload["status"] = "DRAFT"
    _write_package(tmp_path, payload, "coding-agent", "0.1.0")

    with pytest.raises(PackageRegistryError) as exc_info:
        RepositoryNodePackageRegistry(tmp_path)

    assert exc_info.value.code == "PACKAGE_NOT_PUBLISHED"


def test_registry_rejects_duplicate_package_identity_before_path_projection(tmp_path) -> None:
    payload = _coding_agent_payload()
    _write_package(tmp_path, payload, "coding-agent", "0.1.0")
    _write_package(tmp_path, payload, "duplicate", "0.1.0")

    with pytest.raises(PackageRegistryError) as exc_info:
        RepositoryNodePackageRegistry(tmp_path)

    assert exc_info.value.code == "PACKAGE_VERSION_DUPLICATE"


def test_registry_validates_package_defaults_against_configuration_schema(tmp_path) -> None:
    payload = deepcopy(_coding_agent_payload())
    payload["defaults"]["delay_ms"] = -1
    _write_package(tmp_path, payload, "coding-agent", "0.1.0")

    with pytest.raises(PackageRegistryError) as exc_info:
        RepositoryNodePackageRegistry(tmp_path)

    assert exc_info.value.code == "PACKAGE_CONFIGURATION_INVALID"
    assert exc_info.value.path == "/delay_ms"


def test_registry_rejects_raw_secret_fields(tmp_path) -> None:
    payload = deepcopy(_coding_agent_payload())
    payload["metadata"]["api_key"] = "do-not-store-this"
    _write_package(tmp_path, payload, "coding-agent", "0.1.0")

    with pytest.raises(PackageRegistryError) as exc_info:
        RepositoryNodePackageRegistry(tmp_path)

    assert exc_info.value.code == "RAW_SECRET_FORBIDDEN"
    assert exc_info.value.path == "/metadata/api_key"

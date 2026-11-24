# ruff: noqa: INP001, S101

from __future__ import annotations

import pytest

from langflow.adlc.blueprints.errors import (
    CAPABILITY_NOT_AUTHORIZED,
    PACKAGE_NOT_VISIBLE,
    PackageAccessError,
)
from langflow.adlc.blueprints.models import NodePackageStatus, PackageReference
from langflow.adlc.packages.defaults import (
    DEFAULT_PACKAGE_IDENTITIES,
    HARNESS_PACKAGE_IDENTITIES,
    HARNESS_REFERENCE_IDS,
    MOCK_REFERENCE_IDS,
    OPENCODE_PACKAGE_IDENTITIES,
    OPENCODE_REFERENCE_IDS,
    create_default_package_access_policy,
    create_default_package_registry,
)


def test_subject_grants_control_exact_package_visibility_and_capability_use() -> None:
    policy = create_default_package_access_policy()
    coding = PackageReference(package_id="coding-agent", version="0.1.0")
    approval = PackageReference(package_id="approval", version="0.1.0")
    policy.set_subject_grants(
        "limited-owner",
        visible_packages={("approval", "0.1.0")},
        authorized_references={"control:approval"},
    )

    assert policy.can_view_package("limited-owner", approval)
    assert not policy.can_view_package("limited-owner", coding)
    with pytest.raises(PackageAccessError) as hidden:
        policy.ensure_package_visible("limited-owner", coding)
    assert hidden.value.code == PACKAGE_NOT_VISIBLE

    with pytest.raises(PackageAccessError) as denied:
        policy.ensure_references_authorized(
            "limited-owner",
            approval,
            {"control:approval", "tool:mock-artifact"},
        )
    assert denied.value.code == CAPABILITY_NOT_AUTHORIZED
    assert denied.value.details["reference"] == "tool:mock-artifact"


def test_default_mock_grants_hide_the_opt_in_opencode_package(monkeypatch) -> None:
    monkeypatch.delenv("ADLC_OPENCODE_ENABLED", raising=False)
    monkeypatch.delenv("ADLC_HARNESS_ENABLED", raising=False)
    policy = create_default_package_access_policy()

    assert {
        ("approval", "0.1.0"),
        ("coding-agent", "0.1.0"),
    } == DEFAULT_PACKAGE_IDENTITIES
    assert "agent-provider:mock" in MOCK_REFERENCE_IDS
    for package_id, version in DEFAULT_PACKAGE_IDENTITIES:
        package_ref = PackageReference(package_id=package_id, version=version)
        assert policy.can_view_package("any-authenticated-owner", package_ref)
    assert not policy.can_view_package(
        "any-authenticated-owner",
        PackageReference(package_id="coding-agent-opencode", version="0.1.0"),
    )
    assert not policy.can_view_package(
        "any-authenticated-owner",
        PackageReference(package_id="coding-agent-deepseek-harness", version="0.1.0"),
    )


def test_opencode_package_and_references_are_granted_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ADLC_OPENCODE_ENABLED", "true")
    policy = create_default_package_access_policy()
    package_ref = PackageReference(package_id="coding-agent-opencode", version="0.1.0")

    assert {("coding-agent-opencode", "0.1.0")} == OPENCODE_PACKAGE_IDENTITIES
    assert policy.can_view_package("any-authenticated-owner", package_ref)
    policy.ensure_references_authorized(
        "any-authenticated-owner",
        package_ref,
        set(OPENCODE_REFERENCE_IDS),
    )


def test_harness_package_and_references_are_granted_only_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ADLC_HARNESS_ENABLED", "true")
    policy = create_default_package_access_policy()
    package_ref = PackageReference(package_id="coding-agent-deepseek-harness", version="0.2.0")

    assert {
        ("coding-agent-deepseek-harness", "0.1.0"),
        ("coding-agent-deepseek-harness", "0.2.0"),
        ("coding-agent-deepseek-harness", "0.3.0"),
        ("coding-agent-deepseek-harness", "0.3.1"),
        ("coding-agent-deepseek-harness", "0.3.2"),
    } == HARNESS_PACKAGE_IDENTITIES
    assert "plugin:vai-adlc-driver-deepseek/0.1.0" in HARNESS_REFERENCE_IDS
    assert "plugin:vai-adlc-artifacts-git/0.1.1" in HARNESS_REFERENCE_IDS
    assert "plugin:vai-adlc-artifacts-git/0.2.0" in HARNESS_REFERENCE_IDS
    assert policy.can_view_package(
        "any-authenticated-owner", PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.2")
    )
    assert policy.can_view_package(
        "any-authenticated-owner", PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.1")
    )
    assert policy.can_view_package("any-authenticated-owner", package_ref)
    policy.ensure_references_authorized(
        "any-authenticated-owner",
        package_ref,
        set(HARNESS_REFERENCE_IDS),
    )


def test_deprecation_overlay_does_not_mutate_published_package_bytes_or_digest() -> None:
    registry = create_default_package_registry()
    policy = create_default_package_access_policy()
    package_ref = PackageReference(package_id="coding-agent", version="0.1.0")
    before = registry.get(package_ref)

    policy.deprecate_package(package_ref.package_id, package_ref.version)
    after = registry.get(package_ref)

    assert policy.package_status(package_ref, before.definition.status) is NodePackageStatus.DEPRECATED
    assert before.definition.status is NodePackageStatus.PUBLISHED
    assert after.definition == before.definition
    assert after.content_digest == before.content_digest

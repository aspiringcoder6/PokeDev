"""H5B package activation/constant capability boundary, without a live model."""

# ruff: noqa: INP001, S101, PLR2004
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from langflow.adlc.blueprints.models import PackageReference, WorkflowStage
from langflow.adlc.packages.defaults import (
    CONTRACT_AUTHORING_REFERENCE_IDS,
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)


@pytest.mark.parametrize(
    ("harness", "contracts", "authoring", "visible"),
    [
        (False, True, True, False),
        (True, False, True, False),
        (True, True, False, False),
        (True, True, True, True),
    ],
)
def test_authoring_package_is_explicitly_opt_in(monkeypatch, harness, contracts, authoring, visible):
    for name, enabled in (
        ("ADLC_HARNESS_ENABLED", harness),
        ("ADLC_CONTRACTS_ENABLED", contracts),
        ("ADLC_CONTRACT_AUTHORING_ENABLED", authoring),
    ):
        monkeypatch.setenv(name, str(enabled))
    policy = create_default_package_access_policy()
    ref = PackageReference(package_id="skilltree-authoring-deepseek-harness", version="0.1.0")
    assert policy.can_view_package("owner", ref) is visible
    if visible:
        policy.ensure_references_authorized("owner", ref, CONTRACT_AUTHORING_REFERENCE_IDS)


def test_authoring_recipe_pins_tools_model_manual_submission_and_lock(monkeypatch):
    registered = create_default_package_registry().get(
        PackageReference(package_id="skilltree-authoring-deepseek-harness", version="0.1.0")
    )
    recipe = registered.definition
    assert recipe.implementation.entrypoint == "skilltree-authoring"
    assert recipe.defaults["submission_mode"] == "MANUAL"
    assert recipe.configuration_schema["properties"]["submission_mode"] == {"const": "MANUAL"}
    assert recipe.override_allowlist == ["/policies/timeout_ms"]
    assert len(recipe.execution_profile.capabilities.tool_refs) == 6
    assert recipe.execution_profile.capabilities.mcp_server_refs == []
    assert recipe.execution_profile.model_ref == "model:my-codex/cx/gpt-5.6-luna"
    assert recipe.defaults["plugin_lock"] == recipe.configuration_schema["properties"]["plugin_lock"]["const"]
    root = next(parent for parent in Path(__file__).resolve().parents if (parent / "adlc_components").is_dir())
    deployment = json.loads(
        (root / "agent-harness-server/deepseek-harness/plugins/adlc-skilltree.plugin-lock.json").read_text()
    )
    assert deployment == recipe.defaults["plugin_lock"]
    assert len(deployment) == 5
    # Resolution proves every opaque capability is known. Authoring refs are not
    # silently added to the coding package's capability surface.
    for name in ("ADLC_HARNESS_ENABLED", "ADLC_CONTRACTS_ENABLED", "ADLC_CONTRACT_AUTHORING_ENABLED"):
        monkeypatch.setenv(name, "true")
    stage = WorkflowStage.model_validate(
        {
            "stage_id": "22222222-2222-4222-8222-222222222222",
            "stage_type": "PLANNING",
            "name": "Author roadmap",
            "objective": "Create and validate one roadmap, not execute it.",
            "inputs": {"requirement": "Two milestones with human review criteria."},
            "expected_outputs": ["contract_reference"],
            "package_ref": PackageReference(package_id=recipe.package_id, version=recipe.version),
            "configuration_overrides": {},
            "execution_profile_overrides": {},
            "policy_overrides": {},
            "secret_refs": {},
            "position": {"x": 0, "y": 0},
            "metadata": {},
        }
    )
    spec = create_default_package_resolver().resolve(
        stage,
        workflow_definition_id=UUID("11111111-1111-4111-8111-111111111111"),
        workflow_definition_version=1,
        access_subject="owner",
    )
    assert spec.configuration == recipe.defaults
    assert spec.execution_profile == recipe.execution_profile
    assert spec.package_ref.content_digest == registered.content_digest

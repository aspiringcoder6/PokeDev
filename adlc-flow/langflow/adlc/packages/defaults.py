"""Default repository paths and trusted references for the mock planning slice."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from langflow.adlc.harness_workflow import PACKAGES as HARNESS_WORKFLOW_PACKAGES
from langflow.adlc.harness_workflow import REFERENCES as HARNESS_WORKFLOW_REFERENCES
from langflow.adlc.packages.access import InMemoryPackageAccessPolicy, PackageAccessPolicy
from langflow.adlc.packages.registry import RepositoryNodePackageRegistry
from langflow.adlc.packages.resolver import NodePackageResolver, StaticReferenceRegistry
from langflow.adlc.workflow_plugins import REFERENCES as WORKFLOW_PLUGIN_REFERENCES

if TYPE_CHECKING:
    from langflow.adlc.observability import AdlcObservabilitySink

NODE_PACKAGE_ROOT_ENV = "ADLC_NODE_PACKAGE_ROOT"

MOCK_REFERENCE_IDS = frozenset(
    {
        "agent-provider:mock",
        "control:approval",
        "hook:task-lifecycle/0.1.0",
        "memory:mock-task-context/0.1.0",
        "model:mock/deterministic",
        "prompt:coding-agent/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "sandbox:mock-workspace/0.1.0",
        "tool:mock-artifact",
    }
)

TASK_LOOP_MOCK_REFERENCE_IDS = frozenset(
    {
        "agent-provider:task-loop-mock",
        "model:mock/deterministic",
        "prompt:task-loop-full-spec/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "hook:task-lifecycle/0.1.0",
        "memory:task-loop-fresh-context/0.1.0",
        "sandbox:task-loop-in-memory/0.1.0",
        "tool:task-loop-mock-files/0.1.0",
    }
)
TASK_LOOP_MOCK_PACKAGE_IDENTITIES = frozenset({("task-loop", "0.1.0")})

TASK_LOOP_LIVE_REFERENCE_IDS = frozenset(
    {
        "agent-provider:task-loop-opencode",
        "model:aigateway/MiniMax/MiniMax-M3",
        "prompt:task-loop-full-spec/0.2.0",
        "rules:adlc-safe-execution/0.1.0",
        "hook:task-lifecycle/0.1.0",
        "memory:task-loop-fresh-context/0.1.0",
        "sandbox:task-loop-pinned-worktrees/0.1.0",
        "tool:opencode-vcs-diff",
        "verifier:python-unittest/0.1.0",
    }
)
TASK_LOOP_LIVE_PACKAGE_IDENTITIES = frozenset({("task-loop-opencode", "0.1.0")})
UNIFIED_CODING_PACKAGE_IDENTITIES = frozenset({("coding-agent", "0.2.0"), ("coding-agent", "0.2.1")})
HARNESS_LOOP_PACKAGE_IDENTITIES = frozenset({("coding-agent", "0.3.0")})
HARNESS_LOOP_REFERENCE_IDS = frozenset(
    {
        "agent-provider:task-loop-harness",
        "agent-provider:coding-agent-harness-contract-loop",
        "model:my-codex/cx/gpt-5.6-luna",
        "prompt:harness-loop-proposal/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "rules:adlc-contract-repository/0.1.0",
        "hook:task-lifecycle/0.1.0",
        "memory:task-loop-fresh-context/0.1.0",
        "sandbox:harness-loop-no-tools/0.1.0",
        "tool:kernel-apply-file-proposal/0.1.0",
        "verifier:python-unittest/0.1.0",
        "plugin:vai-adlc-task-loop/0.1.0",
        "plugin:vai-adlc-runtime/0.3.0",
    }
)
CONTRACT_LOOP_REFERENCE_IDS = frozenset(
    {
        "agent-provider:coding-agent-contract-loop",
        "model:aigateway/MiniMax/MiniMax-M3",
        "prompt:coding-agent-contract-loop/0.1.0",
        "rules:adlc-contract-repository/0.1.0",
        "hook:task-lifecycle/0.1.0",
        "memory:task-loop-fresh-context/0.1.0",
        "sandbox:coding-agent-contract-proposals/0.1.0",
        "tool:coding-agent-apply-proposal/0.1.0",
        "verifier:python-unittest/0.1.0",
    }
)

OPENCODE_REFERENCE_IDS = frozenset(
    {
        "agent-provider:opencode",
        "hook:task-lifecycle/0.1.0",
        "memory:mock-task-context/0.1.0",
        "model:aigateway/MiniMax/MiniMax-M3",
        "prompt:opencode-coding-agent/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "sandbox:local-git-worktree/0.1.0",
        "tool:opencode-vcs-diff",
    }
)

HARNESS_REFERENCE_IDS = frozenset(
    {
        "agent-provider:deepseek-harness",
        "hook:task-lifecycle/0.1.0",
        "memory:dsh-session/0.1.0",
        "model:deepseek-harness/configured",
        "plugin:vai-adlc-driver-deepseek/0.1.0",
        "plugin:vai-adlc-driver-deepseek/0.2.0",
        "plugin:vai-adlc-runtime/0.1.0",
        "plugin:vai-adlc-runtime/0.2.0",
        "plugin:vai-adlc-runtime/0.3.0",
        "plugin:vai-adlc-artifacts-git/0.1.0",
        "plugin:vai-adlc-artifacts-git/0.1.1",
        "plugin:vai-adlc-artifacts-git/0.2.0",
        "plugin:vai-adlc-local-projects/0.1.0",
        "plugin:vai-adlc-verify-structured/0.1.0",
        "prompt:deepseek-harness-coding-agent/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "sandbox:vai-sandbox/1.0.0",
        "sandbox:harness-isolated-git/0.1.0",
        "tool:deepseek-harness-default",
    }
)

CONTRACT_AUTHORING_REFERENCE_IDS = frozenset(
    {
        "agent-provider:deepseek-harness",
        "hook:task-lifecycle/0.1.0",
        "memory:dsh-session/0.1.0",
        "model:my-codex/cx/gpt-5.6-luna",
        "plugin:vai-adlc-contract-authoring/0.1.0",
        "plugin:vai-adlc-contract-ui/0.1.0",
        "plugin:vai-adlc-skilltree/0.1.0",
        "plugin:vai-adlc-driver-deepseek/0.2.0",
        "plugin:vai-adlc-runtime/0.3.0",
        "prompt:adlc-skilltree-authoring/0.1.0",
        "rules:adlc-contract-authoring/0.1.0",
        "sandbox:harness-authoring-no-workspace-tools/0.1.0",
        *(
            f"tool:{name}/0.1.0"
            for name in (
                "skilltree_init",
                "skilltree_upsert_node",
                "skilltree_remove_node",
                "skilltree_set_dependency",
                "skilltree_get_status",
                "skilltree_validate",
            )
        ),
    }
)
CONTRACT_AUTHORING_PACKAGE_IDENTITIES = frozenset({("skilltree-authoring-deepseek-harness", "0.1.0")})
CONTRACT_EXECUTION_REFERENCE_IDS = frozenset(
    {
        "agent-provider:deepseek-harness",
        "hook:task-lifecycle/0.1.0",
        "memory:dsh-session/0.1.0",
        "model:my-codex/cx/gpt-5.6-luna",
        "plugin:vai-adlc-driver-deepseek/0.2.0",
        "plugin:vai-adlc-runtime/0.3.0",
        "plugin:vai-adlc-artifacts-git/0.2.0",
        "plugin:vai-adlc-contract-execution/0.1.0",
        "plugin:vai-adlc-contract-recovery/0.1.0",
        "prompt:adlc-contract-coding/0.1.0",
        "rules:adlc-contract-repository/0.1.0",
        "sandbox:harness-contract-tools-only/0.1.0",
        *(
            f"tool:{name}/0.1.0"
            for name in ("contract_get_context", "contract_list_files", "contract_read_file", "contract_write_file")
        ),
    }
)
CONTRACT_EXECUTION_PACKAGE_IDENTITIES = frozenset({("coding-agent-contract-harness", "0.1.0")})
CONTRACT_RECOVERY_PACKAGE_IDENTITIES = frozenset({("coding-agent-contract-harness", "0.2.0")})
KNOWN_REFERENCE_IDS = (
    MOCK_REFERENCE_IDS
    | OPENCODE_REFERENCE_IDS
    | HARNESS_REFERENCE_IDS
    | CONTRACT_AUTHORING_REFERENCE_IDS
    | CONTRACT_EXECUTION_REFERENCE_IDS
    | TASK_LOOP_MOCK_REFERENCE_IDS
    | TASK_LOOP_LIVE_REFERENCE_IDS
    | CONTRACT_LOOP_REFERENCE_IDS
    | HARNESS_LOOP_REFERENCE_IDS
    | HARNESS_WORKFLOW_REFERENCES
    | WORKFLOW_PLUGIN_REFERENCES
)

DEFAULT_PACKAGE_IDENTITIES = frozenset(
    {
        ("approval", "0.1.0"),
        ("coding-agent", "0.1.0"),
    }
)

OPENCODE_PACKAGE_IDENTITIES = frozenset({("coding-agent-opencode", "0.1.0")})

HARNESS_PACKAGE_IDENTITIES = frozenset(
    {
        ("coding-agent-deepseek-harness", "0.1.0"),
        ("coding-agent-deepseek-harness", "0.2.0"),
        ("coding-agent-deepseek-harness", "0.3.0"),
        ("coding-agent-deepseek-harness", "0.3.1"),
        ("coding-agent-deepseek-harness", "0.3.2"),
    }
)


def default_node_package_root() -> Path:
    """Locate the repository registry or honor an explicit deployment override."""
    configured = os.getenv(NODE_PACKAGE_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "adlc_components" / "packages"
        if candidate.is_dir():
            return candidate
    return Path.cwd() / "adlc_components" / "packages"


def create_default_package_registry() -> RepositoryNodePackageRegistry:
    """Create a fresh repository-backed registry."""
    return RepositoryNodePackageRegistry(default_node_package_root())


def create_default_package_access_policy() -> InMemoryPackageAccessPolicy:
    """Grant mock packages plus explicitly enabled external executors."""
    from langflow.adlc.contract_authoring import contract_authoring_enabled
    from langflow.adlc.contract_execution import execution_enabled, recovery_enabled
    from langflow.adlc.harness_runtime import harness_execution_enabled
    from langflow.adlc.opencode_runtime import opencode_execution_enabled
    from langflow.adlc.task_loop import task_loop_mock_enabled
    from langflow.adlc.task_loop_harness import harness_loop_enabled
    from langflow.adlc.task_loop_live import task_loop_live_enabled

    opencode_enabled = opencode_execution_enabled()
    harness_enabled = harness_execution_enabled()
    visible_packages = set(DEFAULT_PACKAGE_IDENTITIES)
    authorized_references = set(MOCK_REFERENCE_IDS)
    from langflow.adlc.workflow_plugins import PACKAGES as PLUGIN_PACKAGES
    from langflow.adlc.workflow_plugins import REFERENCES as PLUGIN_REFERENCES
    from langflow.adlc.workflow_plugins import enabled as workflow_plugins_enabled

    if workflow_plugins_enabled():
        visible_packages.update((package_id, "0.1.0") for package_id in PLUGIN_PACKAGES.values())
        authorized_references.update(PLUGIN_REFERENCES)
    from langflow.adlc.harness_workflow import workflow_enabled

    if workflow_enabled():
        visible_packages.update((package_id, "0.1.0") for package_id in HARNESS_WORKFLOW_PACKAGES.values())
        authorized_references.update(HARNESS_WORKFLOW_REFERENCES)
    if harness_enabled or task_loop_live_enabled():
        visible_packages.update(UNIFIED_CODING_PACKAGE_IDENTITIES)
    if harness_loop_enabled():
        visible_packages.update(HARNESS_LOOP_PACKAGE_IDENTITIES)
        contract_loop_service = "agent-provider:coding-agent-harness-contract-loop"
        authorized_references.update(HARNESS_LOOP_REFERENCE_IDS - {contract_loop_service})
        if execution_enabled():
            authorized_references.add(contract_loop_service)
    if task_loop_live_enabled() and execution_enabled():
        authorized_references.update(CONTRACT_LOOP_REFERENCE_IDS)
    if task_loop_mock_enabled():
        visible_packages.update(TASK_LOOP_MOCK_PACKAGE_IDENTITIES)
        authorized_references.update(TASK_LOOP_MOCK_REFERENCE_IDS)
    if task_loop_live_enabled():
        visible_packages.update(TASK_LOOP_LIVE_PACKAGE_IDENTITIES)
        authorized_references.update(TASK_LOOP_LIVE_REFERENCE_IDS)
    if opencode_enabled:
        visible_packages.update(OPENCODE_PACKAGE_IDENTITIES)
        authorized_references.update(OPENCODE_REFERENCE_IDS)
    if harness_enabled:
        visible_packages.update(HARNESS_PACKAGE_IDENTITIES)
        authorized_references.update(HARNESS_REFERENCE_IDS)
        if contract_authoring_enabled():
            visible_packages.update(CONTRACT_AUTHORING_PACKAGE_IDENTITIES)
            authorized_references.update(CONTRACT_AUTHORING_REFERENCE_IDS)
        if execution_enabled():
            visible_packages.update(CONTRACT_EXECUTION_PACKAGE_IDENTITIES)
            authorized_references.update(CONTRACT_EXECUTION_REFERENCE_IDS)
            if recovery_enabled():
                visible_packages.update(CONTRACT_RECOVERY_PACKAGE_IDENTITIES)
    return InMemoryPackageAccessPolicy(
        default_visible_packages=visible_packages,
        default_authorized_references=authorized_references,
    )


def create_default_package_resolver(
    registry: RepositoryNodePackageRegistry | None = None,
    access_policy: PackageAccessPolicy | None = None,
    observability_sink: AdlcObservabilitySink | None = None,
) -> NodePackageResolver:
    """Resolve packages only against known opaque execution references."""
    from langflow.adlc.blueprints.errors import PackageResolutionError
    from langflow.adlc.contract_execution import validate_configuration
    from langflow.adlc.contract_repository import ContractError

    def validate_contract_configuration(package_id, configuration, owner_id):
        try:
            validate_configuration(package_id, configuration, owner_id)
        except ContractError as exc:
            raise PackageResolutionError(exc.code, exc.code, path="/configuration/approved_contract_ref") from None

    package_registry = registry or create_default_package_registry()
    policy = access_policy if access_policy is not None else create_default_package_access_policy()
    return NodePackageResolver(
        package_registry,
        StaticReferenceRegistry(KNOWN_REFERENCE_IDS),
        access_policy=policy,
        observability_sink=observability_sink,
        configuration_validator=validate_contract_configuration,
    )

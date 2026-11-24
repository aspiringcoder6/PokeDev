"""One immutable coding package with independently composable execution options."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from langflow.adlc.blueprints.errors import PACKAGE_CONFIGURATION_INVALID, PackageResolutionError
from langflow.adlc.blueprints.models import NodeImplementation, NodePackageInterface
from langflow.adlc.task_loop_live_models import LiveLoopSpec

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import NodePackageDefinition

CODING_AGENT_PACKAGE = "coding-agent"
CODING_AGENT_VERSION = "0.3.0"
CONTRACT_LOOP_SERVICE = "agent-provider:coding-agent-contract-loop"
LEGACY_CODING_PACKAGES = frozenset(
    {"coding-agent-deepseek-harness", "coding-agent-contract-harness", "task-loop-opencode"}
)


def is_unified_coding_agent(package_id: str, version: str) -> bool:
    return package_id == CODING_AGENT_PACKAGE and version in {"0.2.0", "0.2.1", "0.3.0"}


def coding_agent_document(package: NodePackageDefinition, configuration: dict, inputs: dict) -> tuple:
    """Select publisher-owned internals before policy overrides and reference authorization."""
    has_contract = configuration.get("approved_contract_ref") is not None
    has_loop = configuration.get("task_loop_enabled") is True or "task_loop_spec" in inputs
    if (has_contract or has_loop) and configuration.get("submission_mode") != "MANUAL":
        message = "Contract execution and task loops require human review (MANUAL submission)."
        raise PackageResolutionError(PACKAGE_CONFIGURATION_INVALID, message, path="/configuration/submission_mode")
    mode = (
        "contract_task_loop"
        if has_contract and has_loop
        else "contract"
        if has_contract
        else "task_loop"
        if has_loop
        else "simple"
    )
    variant = deepcopy(package.metadata["execution_variants"][mode])
    if has_loop and package.version == "0.3.0" and configuration.get("loop_runtime") == "HARNESS":
        variant = deepcopy(package.metadata["execution_variants"][f"harness_{mode}"])
    effective_configuration = {**variant["defaults"], **configuration, "task_loop_enabled": has_loop}
    policies = variant["default_policies"]
    if has_loop and "task_loop_spec" in inputs:
        try:
            spec = LiveLoopSpec.model_validate(inputs["task_loop_spec"])
        except ValueError as exc:
            message = "Supply a valid task loop specification with a pinned commit and registered checks."
            raise PackageResolutionError(PACKAGE_CONFIGURATION_INVALID, message, path="/inputs/task_loop_spec") from exc
        policies["retry"]["max_attempts"] = spec.max_iterations
    interface = package.interface.model_dump(mode="json")
    for slot in interface["inputs"]:
        slot["required"] = has_loop if slot["name"] == "task_loop_spec" else not has_loop
    return (
        {
            "configuration": effective_configuration,
            "execution_profile": variant["execution_profile"],
            "policies": policies,
        },
        NodeImplementation.model_validate(variant["implementation"]),
        NodePackageInterface.model_validate(interface),
        mode,
    )


def is_contract_coding_release(package_id: str, version: str, configuration: dict) -> bool:
    """Keep original releases exact while accepting the new package's pinned contract variant."""
    from langflow.adlc.contract_execution import execution_release_matches

    if package_id == "coding-agent-contract-harness":
        return execution_release_matches(configuration, version)
    return (
        is_unified_coding_agent(package_id, version)
        and configuration.get("approved_contract_ref") is not None
        and configuration.get("task_loop_enabled") is False
        and execution_release_matches(configuration, "0.2.0")
    )


def coding_package_in_catalogue(package_id: str, version: str, *, unified_visible: bool) -> bool:
    """Hide replaced picker entries while exact-version access preserves saved workflows."""
    if not unified_visible:
        return True
    return package_id not in LEGACY_CODING_PACKAGES and (package_id, version) != (CODING_AGENT_PACKAGE, "0.1.0")

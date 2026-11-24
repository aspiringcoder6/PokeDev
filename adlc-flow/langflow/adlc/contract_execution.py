"""Fail-closed supported policy compilation, never prompt-only permission enforcement."""

import hashlib
import json
import os
import re

from pydantic import ValidationError

from langflow.adlc.contract_execution_models import (
    EXECUTION_PACKAGE,
    JSON_VERIFIER,
    PATCH_VERIFIER,
    RECOVERY_PACKAGE_VERSION,
    RECOVERY_REF,
    UNCHANGED_VERIFIER,
    ContractExecutionOutcome,
    ContractExecutionPolicy,
    ContractExecutionProof,
    ExecutionCriterion,
)
from langflow.adlc.contract_models import ContractRead, ContractReference
from langflow.adlc.contract_repository import ContractError, get_contract_repository

DENIED_ACTIONS = ["commit", "push", "deploy", "network", "shell", "subagent", "delete"]
KNOWN_ACTIONS = frozenset([*DENIED_ACTIONS, "write"])
MAX_PATH_LENGTH = 255
MAX_CRITERIA = 256
SENSITIVE = re.compile(
    r"^(\.(git|ssh|aws|codex|agents|dsh)|\.env(?:\..*)?|(?:credentials|secrets)(?:\..*)?)$|\.(pem|key|p12|pfx|ovpn)$",
    re.IGNORECASE,
)


def execution_enabled() -> bool:
    return all(
        os.getenv(name, "").strip().lower() in {"true", "1", "yes", "on"}
        for name in ("ADLC_CONTRACTS_ENABLED", "ADLC_CONTRACT_EXECUTION_ENABLED")
    )


def recovery_enabled() -> bool:
    return execution_enabled() and os.getenv("ADLC_CONTRACT_RECOVERY_ENABLED", "").strip().lower() in {
        "true",
        "1",
        "yes",
        "on",
    }


def execution_release_matches(configuration: dict, version: str) -> bool:
    """Exact recovery release; never infer a new policy from a newer/latest version."""
    if version == "0.1.0":
        return "recovery_ref" not in configuration
    return (
        version == RECOVERY_PACKAGE_VERSION
        and configuration.get("recovery_ref") == RECOVERY_REF
        and isinstance(configuration.get("plugin_lock"), list)
        and any(
            isinstance(entry, dict)
            and entry.get("plugin_id") == "vai-adlc-contract-recovery"
            and entry.get("version") == "0.1.0"
            and entry.get("required") is True
            and re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry.get("content_digest", "")))
            for entry in configuration["plugin_lock"]
        )
    )


def model_digest(value) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def safe_relative_path(path: str) -> bool:
    return bool(
        path
        and len(path) <= MAX_PATH_LENGTH
        and not re.search(r"[:\\\x00-\x1f\x7f*?\[\]<>|]", path)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and not re.match(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", part, re.IGNORECASE)
            and not SENSITIVE.search(part)
            for part in path.split("/")
        )
    )


def path_allowed(path: str, allowed: list[str]) -> bool:
    return safe_relative_path(path) and any(
        item == "*" or (path.startswith(item) if item.endswith("/") else path == item) for item in allowed
    )


def compile_policy(contract: ContractRead) -> ContractExecutionPolicy:
    if contract.status != "APPROVED" or contract.approval is None or contract.approval.reference != contract.reference:
        msg = "CONTRACT_EXECUTION_REQUIRES_APPROVAL"
        raise ContractError(msg)
    constraints = contract.document.constraints
    if set(constraints.forbidden_actions) - KNOWN_ACTIONS:
        msg = "CONTRACT_EXECUTION_ACTION_UNSUPPORTED"
        raise ContractError(msg, 422)
    if any(path != "*" and not safe_relative_path(path.removesuffix("/")) for path in constraints.allowed_paths):
        msg = "CONTRACT_EXECUTION_PATH_UNSUPPORTED"
        raise ContractError(msg, 422)
    read_only = constraints.read_only or "write" in constraints.forbidden_actions
    criteria = []
    for node in contract.document.nodes:
        for index, criterion in enumerate(node.acceptance_criteria):
            expected = "TEST" if criterion.verifier_ref == JSON_VERIFIER else "ARTIFACT"
            if (
                criterion.verifier_ref not in {PATCH_VERIFIER, UNCHANGED_VERIFIER, JSON_VERIFIER}
                or criterion.verification != expected
            ):
                msg = "CONTRACT_EXECUTION_CRITERION_UNSUPPORTED"
                raise ContractError(msg, 422)
            if read_only and criterion.verifier_ref in {PATCH_VERIFIER, JSON_VERIFIER}:
                msg = "CONTRACT_EXECUTION_POLICY_CONFLICT"
                raise ContractError(msg, 422)
            criteria.append(
                ExecutionCriterion(node_id=node.node_id, criterion_index=index, verifier_ref=criterion.verifier_ref)
            )
    if not criteria or len(criteria) > MAX_CRITERIA:
        msg = "CONTRACT_EXECUTION_CRITERION_UNSUPPORTED"
        raise ContractError(msg, 422)
    if any(c.verifier_ref == UNCHANGED_VERIFIER for c in criteria) and any(
        c.verifier_ref != UNCHANGED_VERIFIER for c in criteria
    ):
        msg = "CONTRACT_EXECUTION_POLICY_CONFLICT"
        raise ContractError(msg, 422)
    return ContractExecutionPolicy(
        contract_reference=contract.reference,
        read_only=read_only,
        allowed_paths=constraints.allowed_paths,
        denied_actions=[*DENIED_ACTIONS, *(["write"] if read_only else [])],
        criteria=criteria,
    )


def approved_policy(configuration: dict, owner_id: str):
    if not execution_enabled():
        msg = "CONTRACT_EXECUTION_DISABLED"
        raise ContractError(msg, 403)
    try:
        reference = ContractReference.model_validate(configuration.get("approved_contract_ref"))
    except ValidationError:
        msg = "CONTRACT_EXECUTION_REFERENCE_REQUIRED"
        raise ContractError(msg, 422) from None
    contract = get_contract_repository().approved_reference(reference, owner_id=owner_id)
    return contract, compile_policy(contract)


def validate_configuration(package_id: str, configuration: dict, owner_id: str | None) -> None:
    from langflow.adlc.coding_agent import CODING_AGENT_PACKAGE

    if package_id != EXECUTION_PACKAGE and not (
        package_id == CODING_AGENT_PACKAGE and configuration.get("approved_contract_ref") is not None
    ):
        return
    if not owner_id:
        msg = "CONTRACT_EXECUTION_OWNER_REQUIRED"
        raise ContractError(msg, 403)
    if "recovery_ref" in configuration and (
        not recovery_enabled() or not execution_release_matches(configuration, RECOVERY_PACKAGE_VERSION)
    ):
        msg = "CONTRACT_RECOVERY_DISABLED"
        raise ContractError(msg, 403)
    approved_policy(configuration, owner_id)


def validate_plan_contracts(plan, owner_id: str) -> None:
    from langflow.adlc.planning.errors import ExecutionPlanStateError

    try:
        for spec in plan.resolved_node_specs:
            validate_configuration(spec.package_ref.package_id, spec.configuration, owner_id)
    except ContractError as exc:
        raise ExecutionPlanStateError(exc.code, exc.code) from None


def validate_proof(policy: ContractExecutionPolicy, proof: ContractExecutionProof) -> None:
    if proof.reference != policy.contract_reference or proof.policy_digest != model_digest(policy):
        msg = "CONTRACT_EXECUTION_BINDING_MISMATCH"
        raise ContractError(msg)
    if len(set(proof.changed_paths)) != len(proof.changed_paths) or any(
        not path_allowed(p, policy.allowed_paths) for p in proof.changed_paths
    ):
        msg = "CONTRACT_EXECUTION_PATH_REJECTED"
        raise ContractError(msg, 422)
    if policy.read_only and proof.changed_paths:
        msg = "CONTRACT_EXECUTION_READ_ONLY"
        raise ContractError(msg, 422)
    if [
        ExecutionCriterion.model_validate(check.model_dump(include={"node_id", "criterion_index", "verifier_ref"}))
        for check in proof.checks
    ] != policy.criteria:
        msg = "CONTRACT_EXECUTION_EVIDENCE_INCOMPLETE"
        raise ContractError(msg, 422)
    for check in proof.checks:
        if check.verifier_ref == PATCH_VERIFIER and check.passed != bool(proof.changed_paths):
            msg = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
            raise ContractError(msg, 422)
        if check.verifier_ref == UNCHANGED_VERIFIER and check.passed != (not proof.changed_paths):
            msg = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
            raise ContractError(msg, 422)
        if (
            check.verifier_ref == JSON_VERIFIER
            and check.passed
            and not any(p.lower().endswith(".json") for p in proof.changed_paths)
        ):
            msg = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
            raise ContractError(msg, 422)


def validate_task_outcome(request, result, *, owner_id: str, trace, repository=None) -> None:
    """Final coordinator gate, also used by callback-to-task recovery. No live model data is trusted."""
    from langflow.adlc.coding_agent import is_contract_coding_release
    from langflow.adlc.contract_execution_repository import get_contract_execution_repository

    if request is None or request.executor.operation != "contract-coding":
        message = "CONTRACT_EXECUTION_BINDING_MISMATCH"
        raise ContractError(message, 422)
    configuration = request.metadata.get("resolved_configuration", {})
    if not isinstance(configuration, dict):
        message = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
        raise ContractError(message, 422)
    try:
        reference = ContractReference.model_validate(configuration.get("approved_contract_ref"))
        outcome = ContractExecutionOutcome.model_validate(result.output)
    except ValidationError:
        message = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
        raise ContractError(message, 422) from None
    source = get_contract_repository().approved_reference(reference, owner_id=owner_id)
    policy = compile_policy(source)
    store = repository if repository is not None else get_contract_execution_repository()
    row = store.get_by_attempt(request.attempt_id, owner_id=owner_id)
    if row is None:
        message = "CONTRACT_EXECUTION_EVIDENCE_MISSING"
        raise ContractError(message, 422)
    binding, proof = row
    if (
        proof is None
        or trace is None
        or not is_contract_coding_release(trace.package_id, trace.package_version, configuration)
        or request.executor.service != "agent-provider:deepseek-harness"
        or configuration.get("harness_profile_ref") != "harness-profile:adlc-contract-coding/0.1.0"
        or configuration.get("submission_mode") != "MANUAL"
        or result.status != "SUCCEEDED"
        or binding.reference != reference
        or binding.policy != policy
        or binding.execution_plan_id != trace.execution_plan_id
        or binding.resolved_node_digest != trace.resolved_node_digest
        or binding.scope.workflow_run_id != request.workflow_run_id
        or binding.scope.task_run_id != request.task_run_id
        or binding.scope.request_id != request.request_id
        or binding.scope.attempt_id != request.attempt_id
        or result.request_id != request.request_id
        or result.workflow_run_id != request.workflow_run_id
        or result.task_run_id != request.task_run_id
        or result.attempt_id != request.attempt_id
        or binding.scope.session_id != result.metadata.get("harness_session_id")
        or outcome.evidence != proof
        or outcome.outputs.contract_reference != reference
        or not all(check.passed for check in proof.checks)
        or result.metadata.get("harness_plugin_lock") != configuration.get("plugin_lock")
        or len(result.artifacts) != 1
    ):
        message = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
        raise ContractError(message, 422)
    artifact = result.artifacts[0]
    if (
        artifact.artifact_id != proof.artifact_id
        or artifact.kind != "SOURCE_PATCH"
        or artifact.uri != outcome.outputs.source_patch
        or artifact.checksum is None
        or artifact.checksum.algorithm != "SHA256"
        or "sha256:" + artifact.checksum.value != proof.artifact_checksum
        or artifact.metadata.get("base_commit") != proof.base_commit
        or artifact.metadata.get("file_count") != len(proof.changed_paths)
        or artifact.workflow_run_id != request.workflow_run_id
        or artifact.task_run_id != request.task_run_id
        or artifact.attempt_id != request.attempt_id
    ):
        message = "CONTRACT_EXECUTION_EVIDENCE_INVALID"
        raise ContractError(message, 422)

"""H5C policy, immutable evidence, exact reference and plan boundaries. No live model."""
# ruff: noqa: INP001, S101, SLF001

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from langflow.adlc import contract_execution as execution
from langflow.adlc.blueprints.models import PackageReference, WorkflowStage
from langflow.adlc.contract_execution_models import ContractExecutionBridgeCommand, ContractExecutionProof
from langflow.adlc.contract_execution_repository import ContractExecutionRepository
from langflow.adlc.contract_models import ContractApprovalCommand, ContractForkCommand, ContractScope
from langflow.adlc.contract_repository import ContractError, ContractRepository
from langflow.adlc.packages.defaults import create_default_package_access_policy, create_default_package_resolver
from langflow.adlc.planning.errors import ExecutionPlanStateError

OWNER = "contract-owner"


def checked_contract(repository, *, owner=OWNER, read_only=False, paths=None, criteria=None, actions=None):
    scope = ContractScope(workflow_run_id=uuid4(), task_run_id=uuid4())

    def call(tool, **arguments):
        return repository.execute(
            tool, arguments, owner_id=owner, scope=scope, actor_id=owner, authored_via="HUMAN"
        ).contract

    created = call(
        "skilltree_init",
        idempotency_key="init",
        title="Bound execution",
        scope={"objective": "Edit scoped JSON"},
        constraints={
            "read_only": read_only,
            "allowed_paths": paths or ["demo.json", "docs/"],
            "forbidden_actions": actions or ["commit", "push"],
        },
    )
    added = call(
        "skilltree_upsert_node",
        idempotency_key="node",
        expected_revision=1,
        contract_id=str(created.reference.contract_id),
        node={
            "title": "Scoped work",
            "acceptance_criteria": criteria
            or [
                {
                    "description": "Capture a nonempty patch",
                    "verification": "ARTIFACT",
                    "verifier_ref": execution.PATCH_VERIFIER,
                },
                {"description": "Changed JSON parses", "verification": "TEST", "verifier_ref": execution.JSON_VERIFIER},
            ],
        },
    )
    return call(
        "skilltree_validate",
        idempotency_key="validate",
        expected_revision=added.reference.revision,
        contract_id=str(added.reference.contract_id),
    )


def approved_contract(repository, **kwargs):
    checked = checked_contract(repository, **kwargs)
    return repository.approve(
        ContractApprovalCommand(reference=checked.reference, idempotency_key="approve"),
        owner_id=kwargs.get("owner", OWNER),
        run_id=checked.binding.workflow_run_id,
    ).contract


@pytest.fixture
def source(tmp_path, monkeypatch):
    repository = ContractRepository(tmp_path / "source.sqlite3")
    store = ContractExecutionRepository(tmp_path / "execution.sqlite3")
    contract = approved_contract(repository)
    monkeypatch.setattr(execution, "get_contract_repository", lambda: repository)
    for name in ("ADLC_CONTRACTS_ENABLED", "ADLC_CONTRACT_EXECUTION_ENABLED", "ADLC_HARNESS_ENABLED"):
        monkeypatch.setenv(name, "true")
    yield SimpleNamespace(repository=repository, store=store, contract=contract)
    repository.close()
    store.close()


def proof_for(binding, *, paths=None):
    return ContractExecutionProof(
        reference=binding.reference,
        policy_digest=binding.policy_digest,
        artifact_id=uuid4(),
        artifact_checksum="sha256:" + "b" * 64,
        base_commit="c" * 40,
        changed_paths=paths or ["demo.json"],
        checks=[{**c.model_dump(), "passed": True} for c in binding.policy.criteria],
        checked_at=datetime.now(timezone.utc),
    )


def bind(source):
    return source.store.bind(
        owner_id=OWNER,
        scope=ContractScope(
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
            request_id=uuid4(),
            attempt_id=uuid4(),
            session_id="execution-session",
        ),
        execution_plan_id=uuid4(),
        resolved_node_digest="sha256:" + "a" * 64,
        contract=source.contract,
        policy=execution.compile_policy(source.contract),
    )[0]


@pytest.mark.parametrize(
    "path",
    [
        "../demo.json",
        "/root/x",
        ".git/config",
        "src/.env",
        "keys/token.pem",
        "NUL",
        "docs/.git ",
        "docs/x.",
        "docs//x",
        "*.json",
        "a\\b",
        "secret.ovpn",
        "docs/a|b",
    ],
)
def test_sensitive_and_ambiguous_paths_never_allowed(path):
    assert not execution.path_allowed(path, ["*"])


def test_exact_owned_approved_reference_required_and_fork_does_not_revoke(source):
    ref = source.contract.reference
    assert source.repository.approved_reference(ref, owner_id=OWNER) == source.contract
    for owner, reference, code in [
        ("other", ref, "CONTRACT_NOT_FOUND"),
        (OWNER, ref.model_copy(update={"content_digest": "sha256:" + "0" * 64}), "REVISION_CONFLICT"),
    ]:
        with pytest.raises(ContractError, match=code):
            source.repository.approved_reference(reference, owner_id=owner)
    fork = source.repository.fork(
        ContractForkCommand(reference=ref, idempotency_key="fork"),
        owner_id=OWNER,
        run_id=source.contract.binding.workflow_run_id,
    ).contract
    assert source.repository.approved_reference(ref, owner_id=OWNER).approval == source.contract.approval
    with pytest.raises(ContractError, match="REQUIRES_APPROVAL"):
        source.repository.approved_reference(fork.reference, owner_id=OWNER)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"paths": ["src/*.json"]}, "PATH_UNSUPPORTED"),
        ({"paths": ["src///"]}, "PATH_UNSUPPORTED"),
        ({"actions": ["magic-permission"]}, "ACTION_UNSUPPORTED"),
        ({"criteria": [{"description": "Human reviews"}]}, "CRITERION_UNSUPPORTED"),
        (
            {
                "criteria": [
                    {"description": "Unknown test", "verification": "TEST", "verifier_ref": "verifier:unknown/1"}
                ]
            },
            "CRITERION_UNSUPPORTED",
        ),
        ({"read_only": True}, "POLICY_CONFLICT"),
    ],
)
def test_unsupported_declarations_fail_closed(tmp_path, change, code):
    repository = ContractRepository(tmp_path / "source.sqlite3")
    try:
        contract = approved_contract(repository, **change)
        with pytest.raises(ContractError, match=code):
            execution.compile_policy(contract)
    finally:
        repository.close()


def test_readonly_nochange_policy_and_contradictory_predicates(tmp_path):
    repository = ContractRepository(tmp_path / "source.sqlite3")
    try:
        contract = approved_contract(
            repository,
            read_only=True,
            criteria=[
                {
                    "description": "No changed files",
                    "verification": "ARTIFACT",
                    "verifier_ref": execution.UNCHANGED_VERIFIER,
                }
            ],
        )
        policy = execution.compile_policy(contract)
        assert policy.read_only
        assert "write" in policy.denied_actions
        assert policy.natural_language_enforced is False
    finally:
        repository.close()


def test_binding_proof_immutable_idempotent_and_owner_scoped(source, tmp_path):
    binding = bind(source)
    proof = proof_for(binding)
    args = {"owner_id": OWNER, "binding": binding, "proof": proof}
    assert source.store.report(**args) == proof
    assert source.store.report(**args) == proof
    with pytest.raises(ContractError, match="EVIDENCE_CONFLICT"):
        source.store.report(**{**args, "proof": proof.model_copy(update={"artifact_id": uuid4()})})
    assert source.store.list_for_run(binding.scope.workflow_run_id, owner_id="other") == []
    second = ContractExecutionRepository(tmp_path / "execution.sqlite3")
    try:
        assert second.get_by_attempt(binding.scope.attempt_id, owner_id=OWNER) == (binding, proof)
    finally:
        second.close()
    source.store._db.execute("UPDATE adlc_contract_executions SET proof_digest=?", ("sha256:" + "0" * 64,))
    source.store._db.commit()
    with pytest.raises(ContractError, match="STORE_INVALID"):
        source.store.get_by_attempt(binding.scope.attempt_id, owner_id=OWNER)


@pytest.mark.parametrize(
    "change",
    [
        {"changed_paths": ["outside.txt"]},
        {"changed_paths": ["demo.json", "demo.json"]},
        {"changed_paths": []},
        {"changed_paths": ["docs/a.md"]},
        {"checks": []},
        {"policy_digest": "sha256:" + "0" * 64},
    ],
)
def test_invalid_machine_evidence_rejected(source, change):
    binding = bind(source)
    raw = proof_for(binding).model_dump()
    raw.update(change)
    with pytest.raises((ContractError, ValidationError)):
        source.store.report(owner_id=OWNER, binding=binding, proof=ContractExecutionProof.model_validate(raw))


def test_bridge_cannot_supply_owner_contract_or_fake_enforcement_flags(source):
    with pytest.raises(ValidationError):
        ContractExecutionBridgeCommand.model_validate({"operation": "bind", "session_id": "x", "owner_id": OWNER})
    with pytest.raises(ValidationError):
        ContractExecutionBridgeCommand.model_validate({"operation": "report", "session_id": "x"})
    raw = proof_for(bind(source)).model_dump()
    raw["natural_language_enforced"] = True
    with pytest.raises(ValidationError):
        ContractExecutionProof.model_validate(raw)


def test_binding_quota_and_attempt_replay(source):
    binding = bind(source)
    args = {
        "owner_id": OWNER,
        "scope": binding.scope,
        "execution_plan_id": binding.execution_plan_id,
        "resolved_node_digest": binding.resolved_node_digest,
        "contract": source.contract,
        "policy": binding.policy,
    }
    assert source.store.bind(**args)[0] == binding
    with pytest.raises(ContractError, match="BINDING_MISMATCH"):
        source.store.bind(**{**args, "owner_id": "other"})
    source.store._max_bytes = 1
    with pytest.raises(ContractError, match="QUOTA_EXCEEDED"):
        source.store.report(owner_id=OWNER, binding=binding, proof=proof_for(binding))


def test_package_resolution_freezes_exact_ref_and_optin_gates(source, monkeypatch):
    ref = PackageReference(package_id="coding-agent-contract-harness", version="0.1.0")
    stage = WorkflowStage.model_validate(
        {
            "stage_id": uuid4(),
            "stage_type": "IMPLEMENTATION",
            "name": "Bound coding",
            "objective": "Edit JSON under approved scope",
            "inputs": {"requirement": "Edit demo.json"},
            "expected_outputs": ["source_patch", "contract_reference"],
            "package_ref": ref,
            "configuration_overrides": {"approved_contract_ref": source.contract.reference.model_dump(mode="json")},
            "execution_profile_overrides": {},
            "policy_overrides": {},
            "secret_refs": {},
            "metadata": {},
            "position": {"x": 0, "y": 0},
        }
    )
    spec = create_default_package_resolver().resolve(
        stage, workflow_definition_id=uuid4(), workflow_definition_version=1, access_subject=OWNER
    )
    assert spec.configuration["approved_contract_ref"] == source.contract.reference.model_dump(mode="json")
    assert spec.execution_profile.model_ref == "model:my-codex/cx/gpt-5.6-luna"
    assert spec.configuration["submission_mode"] == "MANUAL"
    execution.validate_plan_contracts(SimpleNamespace(resolved_node_specs=[spec]), OWNER)
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    assert not create_default_package_access_policy().can_view_package(OWNER, ref)
    with pytest.raises(ExecutionPlanStateError, match="DISABLED"):
        execution.validate_plan_contracts(SimpleNamespace(resolved_node_specs=[spec]), OWNER)


@pytest.mark.parametrize("unified", [False, True])
def test_final_coordinator_outcome_requires_stored_kernel_proof_and_actual_artifact_identity(source, unified):
    binding = bind(source)
    proof = proof_for(binding)
    source.store.report(owner_id=OWNER, binding=binding, proof=proof)
    configuration = {
        "approved_contract_ref": binding.reference.model_dump(mode="json"),
        "plugin_lock": ["fixture-lock"],
        "harness_profile_ref": "harness-profile:adlc-contract-coding/0.1.0",
        "submission_mode": "MANUAL",
    }
    if unified:
        configuration.update(
            task_loop_enabled=False,
            recovery_ref=execution.RECOVERY_REF,
            plugin_lock=[
                {
                    "plugin_id": "vai-adlc-contract-recovery",
                    "version": "0.1.0",
                    "required": True,
                    "content_digest": "sha256:" + "c" * 64,
                }
            ],
        )
    request = SimpleNamespace(
        executor=SimpleNamespace(operation="contract-coding", service="agent-provider:deepseek-harness"),
        metadata={"resolved_configuration": configuration},
        request_id=binding.scope.request_id,
        workflow_run_id=binding.scope.workflow_run_id,
        task_run_id=binding.scope.task_run_id,
        attempt_id=binding.scope.attempt_id,
    )
    artifact = SimpleNamespace(
        artifact_id=proof.artifact_id,
        kind="SOURCE_PATCH",
        uri="adlc://captured-patch",
        checksum=SimpleNamespace(algorithm="SHA256", value=proof.artifact_checksum[7:]),
        metadata={"base_commit": proof.base_commit, "file_count": len(proof.changed_paths)},
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        attempt_id=request.attempt_id,
    )
    result = SimpleNamespace(
        status="SUCCEEDED",
        output={
            "outputs": {"contract_reference": binding.reference.model_dump(mode="json"), "source_patch": artifact.uri},
            "evidence": proof.model_dump(mode="json"),
        },
        attempt_id=request.attempt_id,
        request_id=request.request_id,
        workflow_run_id=request.workflow_run_id,
        task_run_id=request.task_run_id,
        artifacts=[artifact],
        metadata={"harness_session_id": binding.scope.session_id, "harness_plugin_lock": configuration["plugin_lock"]},
    )
    trace = SimpleNamespace(
        execution_plan_id=binding.execution_plan_id,
        resolved_node_digest=binding.resolved_node_digest,
        package_id="coding-agent" if unified else "coding-agent-contract-harness",
        package_version="0.2.0" if unified else "0.1.0",
    )
    execution.validate_task_outcome(request, result, owner_id=OWNER, trace=trace, repository=source.store)
    artifact.checksum.value = "0" * 64
    with pytest.raises(ContractError, match="EVIDENCE_INVALID"):
        execution.validate_task_outcome(request, result, owner_id=OWNER, trace=trace, repository=source.store)
    artifact.checksum.value = proof.artifact_checksum[7:]
    result.output["evidence"]["artifact_id"] = str(uuid4())
    with pytest.raises(ContractError, match="EVIDENCE_INVALID"):
        execution.validate_task_outcome(request, result, owner_id=OWNER, trace=trace, repository=source.store)
    with pytest.raises(ContractError, match="BINDING_MISMATCH"):
        execution.validate_task_outcome(None, result, owner_id=OWNER, trace=trace, repository=source.store)


@pytest.mark.parametrize(
    "change",
    [
        {"criteria_executed": 1},
        {"execution_policy_enforced": "true"},
        {"natural_language_enforced": 0},
        {"checked_at": "2026-10-08T12:00:00"},
        {"base_commit": "a" * 41},
    ],
)
def test_evidence_flags_timestamps_and_git_identifiers_are_exact(source, change):
    raw = proof_for(bind(source)).model_dump(mode="json")
    raw.update(change)
    with pytest.raises(ValidationError):
        ContractExecutionProof.model_validate(raw)


async def test_real_compile_approval_and_materialization_revalidate_before_new_run(source, monkeypatch):
    from unittest.mock import AsyncMock

    from langflow.adlc.planning.compiler import BlueprintCompiler
    from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
    from langflow.adlc.planning.service import ExecutionPlanService
    from tests.unit.adlc.planning.test_blueprint_planning import _context
    from tests.unit.adlc.planning.test_plan_materialization import _graph

    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"] = [graph["nodes"][0], graph["nodes"][-1]]
    graph["edges"] = [{"source": "stage-1", "target": "stage-5"}]
    stage = graph["nodes"][0]["data"]["adlc"]
    stage["package_ref"] = {"package_id": "coding-agent-contract-harness", "version": "0.1.0"}
    stage["configuration_overrides"] = {"approved_contract_ref": source.contract.reference.model_dump(mode="json")}
    service = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = service.create_plan_from_graph(graph, context=_context(flow_id), owner_id=OWNER, generated_by=OWNER)
    assert not plan.validation_errors
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    with pytest.raises(ExecutionPlanStateError, match="DISABLED"):
        service.approve_plan(plan.execution_plan_id, owner_id=OWNER, approved_by=OWNER)
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "true")
    service.approve_plan(plan.execution_plan_id, owner_id=OWNER, approved_by=OWNER)
    access = create_default_package_access_policy()
    run_service = SimpleNamespace(start_run=AsyncMock())
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    with pytest.raises(ExecutionPlanStateError, match="DISABLED"):
        await ExecutionPlanMaterializer().materialize(
            plan.execution_plan_id,
            idempotency_key="new-run",
            owner_id=OWNER,
            plan_service=service,
            run_service=run_service,
            access_policy=access,
        )
    run_service.start_run.assert_not_called()

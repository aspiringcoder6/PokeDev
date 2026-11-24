"""Unified compilation and real, guarded contract + task-loop execution. Only the model is simulated."""
# ruff: noqa: INP001, S101, PLR2004, F811, PLC0414

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from langflow.adlc import contract_execution as execution
from langflow.adlc.blueprints.errors import PackageResolutionError
from langflow.adlc.blueprints.models import PackageReference, WorkflowStage
from langflow.adlc.coding_agent import CONTRACT_LOOP_SERVICE, coding_package_in_catalogue
from langflow.adlc.coding_agent_loop import ContractTaskLoopExecutor
from langflow.adlc.contract_repository import ContractError, ContractRepository
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, CreateWorkflowRunRequest, ExecutorTarget, TaskResultStatus, WorkflowRunStatus
from langflow.adlc.opencode_client import (
    OpenCodeClientError,
    OpenCodeHttpClient,
    OpenCodePromptResult,
    OpenCodeServerSettings,
)
from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.proposals import LLMPlannerAgent, MockPlannerAgent, ProposalService, ProposalValidator
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE, TASK_LOOP_MODEL
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from scripts.demo_adlc_task_loop import demo_workflow
from tests.unit.adlc.test_contract_execution import approved_contract, checked_contract
from tests.unit.adlc.test_task_loop_live import FIX, Client, _git, _ignore, _request, _spec, _wait_status
from tests.unit.adlc.test_task_loop_live import repository as repository

TESTS = """import unittest
from pathlib import Path
from math_utils import add
class Acceptance(unittest.TestCase):
    def test_add(self): self.assertEqual(add(2, 3), 5)
    def test_documentation(self): self.assertIn('add(a, b)', Path('README.md').read_text())
"""


@pytest.fixture
def contracts(tmp_path, monkeypatch):
    store = ContractRepository(tmp_path / "contracts.sqlite3")
    monkeypatch.setattr(execution, "get_contract_repository", lambda: store)
    for name in (
        "ADLC_HARNESS_ENABLED",
        "ADLC_CONTRACTS_ENABLED",
        "ADLC_CONTRACT_EXECUTION_ENABLED",
        "ADLC_CONTRACT_RECOVERY_ENABLED",
        "ADLC_TASK_LOOP_OPENCODE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    yield store
    store.close()


@pytest.fixture
def spec(repository):
    (repository / "test_acceptance.py").write_text(TESTS, encoding="utf-8")
    (repository / "private.txt").write_text("PRIVATE_FILE_MUST_NOT_REACH_MODEL", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Protected checks and private file")
    return _spec(
        repository, writable_paths=["math_utils.py", "README.md"], specification="Implement add(a, b) and document it."
    )


def contract_for(store, **kwargs):
    return approved_contract(
        store,
        owner="owner",
        paths=["math_utils.py", "README.md"],
        criteria=[
            {"description": "Captured changes", "verification": "ARTIFACT", "verifier_ref": execution.PATCH_VERIFIER}
        ],
        **kwargs,
    )


def stage_for(*, contract=None, spec=None, **configuration):
    return WorkflowStage(
        stage_id=uuid4(),
        stage_type="IMPLEMENTATION",
        name="Coding Agent",
        objective="Implement addition and its documentation.",
        package_ref=PackageReference(package_id="coding-agent", version="0.2.0"),
        inputs={
            "requirement": "FULL_REQUIREMENT_EVERY_ITERATION",
            **({"task_loop_spec": spec.model_dump(mode="json")} if spec else {}),
        },
        expected_outputs=["source_patch"],
        execution_profile_overrides={},
        policy_overrides={},
        secret_refs={},
        position={"x": 0, "y": 0},
        metadata={},
        configuration_overrides={
            **({"approved_contract_ref": contract.reference.model_dump(mode="json")} if contract else {}),
            **configuration,
        },
    )


def request_for(spec, contract, previous=None):
    return _request(
        spec,
        previous=previous,
        executor=ExecutorTarget(service=CONTRACT_LOOP_SERVICE, operation="coding-task-loop"),
        input={
            "namedInputs": {
                "task_loop_spec": spec.model_dump(mode="json"),
                "requirement": "FULL_REQUIREMENT_EVERY_ITERATION",
            }
        },
        metadata={
            "resolved_configuration": {
                "approved_contract_ref": contract.reference.model_dump(mode="json"),
                "task_loop_enabled": True,
                "submission_mode": "MANUAL",
            },
            "plan_traceability": {"package_id": "coding-agent", "package_version": "0.2.0"},
            "coding_agent_owner_id": "owner",
        },
    )


class ProposalClient(Client):
    async def create_restricted_session(self, *, directory, **kwargs):
        # Real HTTP transport coverage below verifies the deny-all permission acknowledgement.
        assert sorted(item.name for item in Path(directory).iterdir()) == [".git"]
        return await self.create_session(directory=directory, **kwargs)

    async def prompt(self, session_id, *, prompt, **_kwargs):
        self.prompts.append((session_id, prompt))
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        step = self.steps[min(len(self.prompts) - 1, len(self.steps) - 1)]
        provider, _, model = TASK_LOOP_MODEL.partition("/")
        return OpenCodePromptResult(
            message_id="answer", text=json.dumps({"files": step}), provider_id=provider, model_id=model
        )


def executor_for(tmp_path, repository, client=None, verifier=None):
    return ContractTaskLoopExecutor(
        workspace=TaskLoopWorkspace(repository, tmp_path / "worktrees"),
        store=TaskLoopStore(tmp_path / "loops.sqlite3"),
        client=client or ProposalClient(),
        verifier=verifier,
    )


@pytest.mark.parametrize(
    ("use_contract", "use_loop", "service", "sandbox"),
    [
        (False, False, "agent-provider:deepseek-harness", "sandbox:harness-isolated-git/0.1.0"),
        (True, False, "agent-provider:deepseek-harness", "sandbox:harness-contract-tools-only/0.1.0"),
        (False, True, TASK_LOOP_LIVE_SERVICE, "sandbox:task-loop-pinned-worktrees/0.1.0"),
        (True, True, CONTRACT_LOOP_SERVICE, "sandbox:coding-agent-contract-proposals/0.1.0"),
    ],
)
@pytest.mark.parametrize("version", ["0.2.0", "0.2.1"])
def test_one_package_selects_exact_capabilities_for_composable_options(
    contracts, spec, use_contract, use_loop, service, sandbox, version
):
    contract = contract_for(contracts) if use_contract else None
    stage = stage_for(contract=contract, spec=spec if use_loop else None)
    stage.package_ref = PackageReference(package_id="coding-agent", version=version)
    resolved = create_default_package_resolver().resolve(
        stage,
        workflow_definition_id=uuid4(),
        workflow_definition_version=1,
        access_subject="owner",
    )
    assert resolved.package_ref.package_id == "coding-agent"
    assert resolved.implementation.adapter_ref == service
    assert resolved.execution_profile.sandbox_policy_ref == sandbox
    assert resolved.configuration["task_loop_enabled"] == use_loop
    assert resolved.policies.retry.max_attempts == (spec.max_iterations if use_loop else 1)
    assert resolved.policies.approval.gate_type == ("AFTER_TASK" if use_loop else None)
    assert next(slot for slot in resolved.interface.inputs if slot.name == "task_loop_spec").required == use_loop
    assert next(slot for slot in resolved.interface.inputs if slot.name == "requirement").required == (not use_loop)
    assert not ("tool:deepseek-harness-default" in resolved.execution_profile.capabilities.tool_refs and use_contract)


@pytest.mark.usefixtures("contracts")
def test_simple_defaults_require_no_contract_or_loop_configuration():
    result = create_default_package_resolver().resolve(
        stage_for(), workflow_definition_id=uuid4(), workflow_definition_version=1, access_subject="owner"
    )
    assert result.configuration["approved_contract_ref"] is None
    assert result.configuration["task_loop_enabled"] is False
    assert result.configuration["harness_profile_ref"] == "harness-profile:adlc-coding-artifacts/0.1.0"


@pytest.mark.parametrize(
    "configuration",
    [{"plugin_lock": []}, {"harness_profile_ref": "anything"}, {"submission_mode": "AUTO", "task_loop_enabled": True}],
)
@pytest.mark.usefixtures("contracts")
def test_public_options_cannot_replace_guarded_internals(configuration):
    with pytest.raises(PackageResolutionError):
        create_default_package_resolver().resolve(
            stage_for(**configuration),
            workflow_definition_id=uuid4(),
            workflow_definition_version=1,
            access_subject="owner",
        )


def test_disabled_contract_and_unauthorized_loop_do_not_fall_back_to_simple(contracts, spec, monkeypatch):
    contract = contract_for(contracts)
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    with pytest.raises(PackageResolutionError, match="CONTRACT_EXECUTION_DISABLED"):
        create_default_package_resolver().resolve(
            stage_for(contract=contract, spec=spec),
            workflow_definition_id=uuid4(),
            workflow_definition_version=1,
            access_subject="owner",
        )
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "true")
    policy = create_default_package_access_policy()
    policy.set_subject_grants(
        "owner", visible_packages={("coding-agent", "0.2.0")}, authorized_references={"agent-provider:deepseek-harness"}
    )
    with pytest.raises(PackageResolutionError):
        create_default_package_resolver(access_policy=policy).resolve(
            stage_for(spec=spec), workflow_definition_id=uuid4(), workflow_definition_version=1, access_subject="owner"
        )


@pytest.mark.usefixtures("contracts")
def test_catalogue_consolidates_entries_without_changing_exact_old_packages():
    registry = create_default_package_registry()
    identities = [(item.definition.package_id, item.definition.version) for item in registry.list_packages()]
    filtered = [item for item in identities if coding_package_in_catalogue(*item, unified_visible=True)]
    assert ("coding-agent", "0.2.0") in filtered
    assert not any(
        item[0] in {"coding-agent-deepseek-harness", "coding-agent-contract-harness", "task-loop-opencode"}
        for item in filtered
    )
    assert registry.get(PackageReference(package_id="coding-agent-deepseek-harness", version="0.3.2"))
    assert create_default_package_access_policy().can_view_package(
        "owner", PackageReference(package_id="coding-agent-contract-harness", version="0.2.0")
    )


@pytest.mark.parametrize("llm", [False, True])
async def test_generated_plan_preserves_combined_options_and_one_loop_task(contracts, spec, llm):
    contract = contract_for(contracts)
    workflow = demo_workflow(spec)
    workflow.stages = [stage_for(contract=contract, spec=spec)]
    workflow.stages[0].inputs.pop("requirement")
    workflow.edges = []
    registry = create_default_package_registry()
    planner = MockPlannerAgent()
    if llm:
        payload = {
            "tasks": [
                {
                    "task_id": "T1",
                    "stage_ref": "S1",
                    "name": "Coding Agent",
                    "objective": "Implement the full scoped specification.",
                    "package_id": "coding-agent",
                    "expected_outputs": ["source_patch"],
                    "inputs": {},
                }
            ]
        }
        planner = LLMPlannerAgent(
            base_url="http://planner.test/v1",
            api_key="test-key",
            model="test-model",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
            ),
        )
    service = ProposalService(
        planner, registry, ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    )
    proposed = await service.generate_proposal(workflow, owner_id="owner", generated_by="owner")
    assert len(proposed.tasks) == 1
    validated = service.validate_proposal(proposed.proposal_id, owner_id="owner")
    assert not validated.validation_errors
    _, plan = await service.approve_proposal(proposed.proposal_id, owner_id="owner", approved_by="owner")
    assert len(plan.tasks) == 1
    resolved = plan.resolved_node_specs[0]
    assert resolved.implementation.adapter_ref == CONTRACT_LOOP_SERVICE
    assert resolved.configuration["approved_contract_ref"] == contract.reference.model_dump(mode="json")
    assert resolved.configuration["task_loop_enabled"] is True
    validator = ProposalValidator(registry)
    split = proposed.model_copy(
        update={"tasks": [*proposed.tasks, proposed.tasks[0].model_copy(update={"task_id": "split"})]}
    )
    assert "CODING_AGENT_LOOP_REQUIRES_ONE_TASK" in {issue.code for issue in validator.validate(workflow, split)[0]}
    downgraded_task = proposed.tasks[0].model_copy(
        update={"assigned_package": PackageReference(package_id="coding-agent", version="0.1.0")}
    )
    downgraded = proposed.model_copy(update={"tasks": [downgraded_task]})
    assert "CODING_AGENT_OPTIONS_MUST_BE_PRESERVED" in {
        issue.code for issue in validator.validate(workflow, downgraded)[0]
    }


async def test_combined_run_repeats_full_requirement_and_contract_then_verifies_real_files(
    contracts, spec, repository, tmp_path
):
    contract = contract_for(contracts)
    client = ProposalClient((FIX, {"README.md": "Use add(a, b).\n"}))
    first = request_for(spec, contract)
    executor = executor_for(tmp_path, repository, client)
    failed = await executor.execute(first, _ignore)
    assert failed.error.code == "TASK_LOOP_CHECKS_FAILED"
    assert failed.error.retryable
    second = request_for(spec, contract, previous=first)
    executor = executor_for(tmp_path, repository, client)
    passed = await executor.execute(second, _ignore)
    assert passed.status is TaskResultStatus.SUCCEEDED
    assert len(client.sessions) == 2
    assert client.sessions[0].session_id != client.sessions[1].session_id
    for _, prompt in client.prompts:
        data = json.loads(prompt)
        assert data["requirement"] == "FULL_REQUIREMENT_EVERY_ITERATION"
        assert data["approved_contract"] == contract.document.model_dump(mode="json")
        assert data["specification"] == spec.model_dump(mode="json")
        assert "PRIVATE_FILE_MUST_NOT_REACH_MODEL" not in prompt
        assert "OLD_TRANSCRIPT_DO_NOT_FORWARD" not in prompt
        assert "test_acceptance.py" not in data["files"]
    outputs = passed.output["outputs"]
    assert outputs["contract_reference"] == contract.reference.model_dump(mode="json")
    assert outputs["candidate"]["changes"]["math_utils.py"]["content"] == FIX["math_utils.py"]
    assert outputs["contract_verification_report"]["candidate_digest"] == outputs["candidate"]["content_digest"]
    assert outputs["verification_report"]["checks"][0]["executed_tests"] == 2
    assert outputs["source_patch"] == passed.artifacts[0].uri
    executor.validate_result(second, passed, owner_id="owner")
    await executor.resume(second, _ignore)
    assert len(client.sessions) == 2
    assert (repository / "README.md").read_text() == "Pending.\n"
    assert (repository / "legacy.txt").is_file()
    assert not list((tmp_path / "worktrees").glob("*-session"))
    with pytest.raises(ContractError):
        executor.validate_result(
            second, passed.model_copy(update={"output": {"outputs": {"source_patch": "fake"}}}), owner_id="owner"
        )
    with pytest.raises(ContractError):
        executor.validate_result(second, passed, owner_id="another-owner")


@pytest.mark.parametrize(
    ("proposal", "code"),
    [
        ({"private.txt": "escape"}, "CODING_AGENT_CONTRACT_PATH_DENIED"),
        ({"test_acceptance.py": "pass"}, "CODING_AGENT_CONTRACT_PATH_DENIED"),
        ({"README.md": None}, "TASK_LOOP_EXECUTION_INVALID"),
    ],
)
async def test_combined_model_cannot_edit_protected_or_out_of_scope_files(
    contracts, spec, repository, tmp_path, proposal, code
):
    client = ProposalClient((proposal,))
    executor = executor_for(tmp_path, repository, client)
    result = await executor.execute(request_for(spec, contract_for(contracts)), _ignore)
    assert result.status is TaskResultStatus.FAILED
    assert result.error.code == code
    assert not result.error.retryable
    assert not result.artifacts


async def test_read_only_contract_blocks_model_writes_before_any_apply(contracts, spec, repository, tmp_path):
    contract = approved_contract(
        contracts,
        owner="owner",
        read_only=True,
        paths=spec.writable_paths,
        criteria=[
            {"description": "No changes", "verification": "ARTIFACT", "verifier_ref": execution.UNCHANGED_VERIFIER}
        ],
    )
    client = ProposalClient((FIX,))
    result = await executor_for(tmp_path, repository, client).execute(request_for(spec, contract), _ignore)
    assert result.error.code == "CODING_AGENT_CONTRACT_READ_ONLY"
    assert (repository / "math_utils.py").read_text().endswith("return 0\n")


async def test_contract_predicate_failure_repeats_even_when_behavioral_checks_pass(
    contracts, spec, repository, tmp_path
):
    (repository / "math_utils.py").write_text(FIX["math_utils.py"], encoding="utf-8")
    (repository / "README.md").write_text("Use add(a, b).\n", encoding="utf-8")
    (repository / "demo.json").write_text('{"version": 0}\n', encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-qm", "Passing protected behavior and scoped JSON")
    spec = spec.model_copy(
        update={"base_commit": _git(repository, "rev-parse", "HEAD"), "writable_paths": ("demo.json",)}
    )
    contract = approved_contract(contracts, owner="owner", paths=["demo.json"])
    client = ProposalClient(({"demo.json": "invalid JSON"}, {"demo.json": '{"version": 1}\n'}))
    executor = executor_for(tmp_path, repository, client)
    first = request_for(spec, contract)
    failed = await executor.execute(first, _ignore)
    checkpoint = executor.store.attempt(first)
    assert checkpoint.verification.passed
    assert not checkpoint.additional_evidence["checks"][1]["passed"]
    assert failed.error.retryable
    second = request_for(spec, contract, previous=first)
    passed = await executor.execute(second, _ignore)
    assert passed.status is TaskResultStatus.SUCCEEDED
    feedback = json.loads(client.prompts[1][1])["previous_contract_findings"]
    assert feedback == checkpoint.additional_evidence["checks"]
    executor.validate_result(second, passed, owner_id="owner")


async def test_scope_owner_and_unapproved_contract_fail_before_any_session(contracts, spec, repository, tmp_path):
    contract = contract_for(contracts)
    executor = executor_for(tmp_path, repository)
    conflicting = spec.model_copy(update={"writable_paths": (*spec.writable_paths, "private.txt")})
    result = await executor.execute(request_for(conflicting, contract), _ignore)
    assert result.error.code == "CODING_AGENT_CONTRACT_SCOPE_CONFLICT"
    request = request_for(spec, contract)
    request.metadata["coding_agent_owner_id"] = "other-owner"
    assert (await executor.execute(request, _ignore)).status is TaskResultStatus.FAILED
    draft = checked_contract(contracts, owner="owner", paths=spec.writable_paths)
    assert (await executor.execute(request_for(spec, draft), _ignore)).status is TaskResultStatus.FAILED
    assert not executor.client.sessions


async def test_combined_verified_checkpoint_recovers_without_model_or_test_replay(
    contracts, spec, repository, tmp_path, monkeypatch
):
    contract = contract_for(contracts)
    client = ProposalClient(({**FIX, "README.md": "Use add(a, b).\n"},))
    request = request_for(spec, contract)
    executor = executor_for(tmp_path, repository, client)

    def crash(*_args):
        message = "crash after both proofs"
        raise SystemExit(message)

    monkeypatch.setattr(executor.store, "finish", crash)
    with pytest.raises(SystemExit):
        await executor.execute(request, _ignore)
    checkpoint = executor.store.attempt(request)
    assert checkpoint.phase == "VERIFIED"
    assert checkpoint.additional_evidence["contract_reference"] == contract.reference.model_dump(mode="json")

    class DoNotRepeatTests:
        async def verify(self, *_args):
            pytest.fail("Passing protected checks must not replay")

    restored = executor_for(tmp_path, repository, client, DoNotRepeatTests())
    result = await restored.resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    restored.validate_result(request, result, owner_id="owner")
    assert len(client.prompts) == 1


async def test_combined_coordinator_keeps_one_task_and_waits_for_final_human_review(
    contracts, spec, repository, tmp_path
):
    contract = contract_for(contracts)
    workflow = demo_workflow(spec)
    workflow.stages = [stage_for(contract=contract, spec=spec)]
    workflow.edges = []
    plan = BlueprintCompiler(create_default_package_resolver()).compile(workflow, plan_version=1, generated_by="owner")
    assert plan.validation_status == "VALID"
    plan = plan.model_copy(update={"approval_required": False})
    definitions = materialize_task_definitions(plan)
    definitions[0].constraints["retry_backoff_ms"] = 0
    definitions[0].request_metadata["coding_agent_owner_id"] = "FORGED_WORKFLOW_OWNER"
    executor = executor_for(tmp_path, repository, ProposalClient((FIX, {"README.md": "Use add(a, b).\n"})))
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={CONTRACT_LOOP_SERVICE: executor}),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    run = await service.start_run(
        flow_id=workflow.workflow_definition_id,
        flow_name="Unified agent",
        definitions=definitions,
        execution_plan_id=plan.execution_plan_id,
        request=CreateWorkflowRunRequest(
            flowId=workflow.workflow_definition_id, executionMode="EXECUTION_PLAN", delayMs=0
        ),
        owner_id="owner",
    )
    run = await _wait_status(service, run.id, WorkflowRunStatus.WAITING_APPROVAL)
    assert len(run.tasks) == 1
    assert run.tasks[0].retry_count == 1
    assert run.tasks[0].request.metadata["coding_agent_owner_id"] == "owner"
    assert run.tasks[0].pending_result.status is TaskResultStatus.SUCCEEDED
    assert len(executor.client.prompts) == 2

    restored_executor = executor_for(tmp_path, repository, executor.client)
    restored_service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={CONTRACT_LOOP_SERVICE: restored_executor}),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=restored_executor.artifact_payloads,
    )
    restored = await restored_service.get_run(run.id, owner_id="owner")
    assert restored.status is WorkflowRunStatus.WAITING_APPROVAL
    approved = await restored_service.approve(
        restored.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(type="USER", id="owner"),
        comment="Approve the exact checked candidate.",
    )
    approved = await _wait_status(restored_service, approved.id, WorkflowRunStatus.SUCCEEDED)
    assert approved.tasks[0].id == run.tasks[0].id
    assert len(executor.client.prompts) == 2


@pytest.mark.parametrize("acknowledge", [True, False])
async def test_real_http_client_requires_exact_deny_all_acknowledgement(acknowledge):
    calls = []

    def transport(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/abort"):
            return httpx.Response(200, json=True)
        data = json.loads(request.content)
        assert data["permission"] == [{"permission": "*", "pattern": "*", "action": "deny"}]
        return httpx.Response(
            200,
            json={
                "id": "session-guarded",
                "directory": "D:/isolated",
                **({"permission": data["permission"]} if acknowledge else {}),
            },
        )

    client = OpenCodeHttpClient(OpenCodeServerSettings(), transport=httpx.MockTransport(transport))
    if acknowledge:
        assert (
            await client.create_restricted_session(directory="D:/isolated", title="Guarded", timeout_ms=1000)
        ).session_id == "session-guarded"
    else:
        with pytest.raises(OpenCodeClientError, match="OPENCODE_CONTRACT_PERMISSIONS_UNAVAILABLE"):
            await client.create_restricted_session(directory="D:/isolated", title="Guarded", timeout_ms=1000)
        assert calls[-1].endswith("/abort")

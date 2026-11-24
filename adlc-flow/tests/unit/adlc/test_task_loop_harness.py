"""Real Python -> native Node wire/capture/tests; only native model execution is simulated."""
# ruff: noqa: INP001, S101, PLR2004, PLC0414, F811

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.errors import PackageResolutionError
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.harness_client import HarnessServerSettings
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, CreateWorkflowRunRequest, ExecutorTarget, TaskResultStatus, WorkflowRunStatus
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunService
from langflow.adlc.task_loop_harness import (
    HARNESS_CONTRACT_LOOP_SERVICE,
    HARNESS_LOOP_SERVICE,
    HarnessTaskLoopRuntime,
    harness_binding,
)
from langflow.adlc.task_loop_harness_executor import (
    HarnessContractTaskLoopExecutor,
    HarnessProposalTaskLoopExecutor,
)
from langflow.adlc.task_loop_harness_release import PLUGIN_DIGEST
from langflow.adlc.task_loop_live_models import LiveLoopCandidate
from langflow.adlc.task_loop_runtime import LoopRuntimeError
from langflow.adlc.task_loop_runtime_v2 import LoopIterationRequestV2, LoopRuntimeUsageV2
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from scripts.demo_adlc_task_loop import demo_workflow
from scripts.generate_adlc_task_loop_harness_schemas import generated
from tests.unit.adlc.test_coding_agent import contract_for, stage_for
from tests.unit.adlc.test_coding_agent import contracts as contracts
from tests.unit.adlc.test_coding_agent import spec as spec
from tests.unit.adlc.test_task_loop_live import FIX, SimulatedCrash, _git, _ignore, _request, _wait_status
from tests.unit.adlc.test_task_loop_live import repository as repository

ROOT_REPO = Path(__file__).resolve().parents[4]
PLUGIN = ROOT_REPO / "agent-harness-server/deepseek-harness/plugins/vai-adlc-task-loop"
TOKEN = "offline-fixture-token-at-least-thirty-two-bytes"  # noqa: S105 - offline fixture only.


@pytest.fixture
async def bridge(tmp_path, request):
    """Start an ephemeral native HTTP fixture without inheriting configured provider credentials."""
    node = shutil.which("node")
    assert node, "Node is required for cross-language adapter conformance"
    fixture_root = tmp_path / "native-fixture"
    fixture_root.mkdir()
    environment = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
    environment.update(
        ADLC_ITERATION_FIXTURE_ROOT=str(fixture_root),
        ADLC_ITERATION_FIXTURE_MODE=getattr(request, "param", "loop"),
    )
    process = subprocess.Popen(  # noqa: S603, ASYNC220 - fixed fixture; all process waits run in a thread.
        [node, str(PLUGIN / "tests/server.mjs")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    try:
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), timeout=10)
        assert line, process.stderr.read() if process.poll() is not None else "Fixture did not start"
        url = json.loads(line)["url"]
        runtime = HarnessTaskLoopRuntime(
            HarnessServerSettings(base_url=url, api_token=TOKEN), plugin_digest=PLUGIN_DIGEST
        )
        async with httpx.AsyncClient(base_url=url) as observer:
            yield SimpleNamespace(runtime=runtime, observer=observer, root=fixture_root, url=url)
        await runtime.aclose()
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
        except TimeoutError:
            process.kill()  # Only the exact child process created by this test.
            await asyncio.to_thread(process.wait)
        process.stdout.close()
        diagnostic = process.stderr.read()
        process.stderr.close()
        assert not diagnostic, diagnostic


def executor(tmp_path, source, runtime, *, contract=False):
    cls = HarnessContractTaskLoopExecutor if contract else HarnessProposalTaskLoopExecutor
    return cls(
        workspace=TaskLoopWorkspace(source, tmp_path / "worktrees"),
        store=TaskLoopStore(tmp_path / "state/task-loop.sqlite3"),
        runtime=runtime,
    )


def task_request(spec, contract=None, previous=None):
    return _request(
        spec,
        previous,
        executor=ExecutorTarget(
            service=HARNESS_CONTRACT_LOOP_SERVICE if contract else HARNESS_LOOP_SERVICE,
            operation="coding-task-loop",
        ),
        input={
            "namedInputs": {
                "task_loop_spec": spec.model_dump(mode="json"),
                "requirement": "FULL_REQUIREMENT_EVERY_ITERATION",
            }
        },
        metadata={
            "resolved_configuration": {
                "approved_contract_ref": contract.reference.model_dump(mode="json") if contract else None,
                "task_loop_enabled": True,
                "submission_mode": "MANUAL",
                "loop_runtime": "HARNESS",
            },
            "plan_traceability": {"package_id": "coding-agent", "package_version": "0.3.0"},
            "coding_agent_owner_id": "owner",
        },
    )


def stage(spec, contract=None, **configuration):
    item = stage_for(spec=spec, contract=contract, loop_runtime="HARNESS", task_loop_enabled=True, **configuration)
    item.package_ref.version = "0.3.0"
    return item


async def stats(bridge):
    return (await bridge.observer.get("/fixture-stats")).json()


@pytest.mark.parametrize("combined", [False, True])
async def test_both_harness_loops_fail_then_pass_real_checks_and_capture_cumulative_patch(
    bridge, contracts, spec, repository, tmp_path, combined
):
    contract = contract_for(contracts) if combined else None
    kernel = executor(tmp_path, repository, bridge.runtime, contract=combined)
    first = task_request(spec, contract)
    failure = await kernel.execute(first, _ignore)
    assert failure.error.code == "TASK_LOOP_CHECKS_FAILED"
    saved = kernel.store.attempt(first)
    assert saved.runtime_checkpoint.schema_version == "0.2"
    assert saved.runtime_checkpoint.session.tools_disabled is True
    assert saved.runtime_checkpoint.usage.cost is None
    second = task_request(spec, contract, first)
    restored = executor(tmp_path, repository, bridge.runtime, contract=combined)
    result = await restored.execute(second, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    proof = result.output["outputs"]["verification_report"]
    candidate = result.output["outputs"]["candidate"]
    assert proof["candidate_digest"] == candidate["content_digest"]
    assert candidate["parent_candidate_id"] == str(saved.candidate.candidate_id)
    assert candidate["changes"]["math_utils.py"]["content"] == FIX["math_utils.py"]
    assert proof["checks"][0]["executed_tests"] == 2
    assert result.metadata["task_loop"]["runtime"]["family"] == "HARNESS"
    assert result.metadata["task_loop"]["total_tokens"] == 36
    assert result.metadata["task_loop"]["total_cost"] is None
    if combined:
        assert result.output["outputs"]["contract_verification_report"]["candidate_digest"] == proof["candidate_digest"]
    assert await restored.execute(second, _ignore) == result
    view = await restored.inspect_loop(second)
    assert [i.status for i in view.iterations] == ["CHECKS_FAILED", "PASSED"]
    assert view.total_cost is None
    assert view.total_tokens == 36
    assert len({i.session_id for i in view.iterations}) == 2
    assert await stats(bridge) == {"creates": 2, "prompts": 2, "disposed": 2}
    assert _git(repository, "status", "--porcelain") == ""


@pytest.mark.parametrize("combined", [False, True])
async def test_compiled_harness_loop_preserves_manual_gate_patches_owner_and_passive_history(
    bridge, contracts, spec, repository, tmp_path, monkeypatch, combined
):
    monkeypatch.setenv("ADLC_TASK_LOOP_HARNESS_ENABLED", "true")
    monkeypatch.setenv("ADLC_TASK_LOOP_OPENCODE_ENABLED", "false")
    contract = contract_for(contracts) if combined else None
    workflow = demo_workflow(spec)
    workflow.stages, workflow.edges = [stage(spec, contract)], []
    plans = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = plans.create_plan(workflow, owner_id="owner", generated_by="owner")
    plan = plans.approve_plan(plan.execution_plan_id, owner_id="owner", approved_by="owner")
    definitions = materialize_task_definitions(plan)
    service_ref = HARNESS_CONTRACT_LOOP_SERVICE if combined else HARNESS_LOOP_SERVICE
    assert definitions[0].executor_target.service == service_ref
    definitions[0].constraints["retry_backoff_ms"] = 0
    kernel = executor(tmp_path, repository, bridge.runtime, contract=combined)
    monkeypatch.setenv("ADLC_TASK_LOOP_STATE_ROOT", str(kernel.store.path.parent))
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={service_ref: kernel}),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=kernel.artifact_payloads,
    )
    flow_id = workflow.workflow_definition_id
    started = await service.start_run(
        flow_id=flow_id,
        flow_name="Harness iterations",
        definitions=definitions,
        execution_plan_id=plan.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="owner",
    )
    waiting = await _wait_status(service, started.id, WorkflowRunStatus.WAITING_APPROVAL)
    task = waiting.tasks[0]
    assert task.pending_result.status is TaskResultStatus.SUCCEEDED
    view = await service.get_task_loop(waiting.id, task.id, owner_id="owner")
    native_view = await service.get_task_loop_runtime(waiting.id, task.id, owner_id="owner")
    assert native_view.schema_version == "0.2"
    assert native_view.runtime.family == "HARNESS"
    assert native_view.runtime.cost_reporting == "UNAVAILABLE"
    assert native_view.execution_unified_with_harness is False
    assert "PRIVATE_FILE_MUST_NOT_REACH_MODEL" not in native_view.model_dump_json()
    with pytest.raises(AdlcRunNotFoundError):
        await service.get_task_loop_runtime(waiting.id, task.id, owner_id="foreign")
    for item in view.iterations:
        patch = await service.get_source_patch(waiting.id, item.patch_artifact_id, owner_id="owner")
        assert patch.artifact.metadata["candidate_digest"] == item.candidate_digest
    before = kernel.store.path.read_bytes()
    from fastapi import FastAPI

    from langflow.api.v1 import adlc as api
    from langflow.services.auth.utils import get_current_active_user

    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_adlc_run_service] = lambda: service
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(id="owner", username="owner")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/adlc/runs/{waiting.id}/tasks/{task.id}/task-loop-runtime")
        assert response.status_code == 200
        assert response.json()["schema_version"] == "0.2"
        assert response.json()["runtime"]["cost_reporting"] == "UNAVAILABLE"
    restored = AdlcRunService(
        TaskExecutorRouter(MockExecutor()),
        repository=SqliteRunRepository(tmp_path / "runs.sqlite3"),
        artifact_payloads=kernel.artifact_payloads,
    )
    assert await restored.get_task_loop_runtime(waiting.id, task.id, owner_id="owner") == native_view
    assert await restored.get_task_loop(waiting.id, task.id, owner_id="owner") == view
    assert kernel.store.path.read_bytes() == before
    approved = await service.approve(
        waiting.approval_requests[0].approval_request_id,
        owner_id="owner",
        actor=Actor(id="owner", type="USER"),
        comment="Offline fixture approval of the exact candidate",
    )
    assert (await _wait_status(service, approved.id, WorkflowRunStatus.SUCCEEDED)).status is WorkflowRunStatus.SUCCEEDED
    assert (await stats(bridge))["prompts"] == 2
    assert _git(repository, "status", "--porcelain") == ""


@pytest.mark.parametrize("bridge", ["passing"], indirect=True)
@pytest.mark.parametrize("phase", ["CANDIDATE_CAPTURED", "VERIFIED"])
async def test_harness_checkpoint_recovery_does_not_recreate_or_reprompt(
    bridge, spec, repository, tmp_path, monkeypatch, phase
):
    kernel = executor(tmp_path, repository, bridge.runtime)
    request = task_request(spec)
    if phase == "CANDIDATE_CAPTURED":

        async def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.verifier, "verify", crash)
    else:

        def crash(*_args):
            raise SimulatedCrash

        monkeypatch.setattr(kernel.store, "finish", crash)
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    assert kernel.store.attempt(request).runtime_checkpoint.phase == phase
    result = await executor(tmp_path, repository, bridge.runtime).resume(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert await stats(bridge) == {"creates": 1, "prompts": 1, "disposed": 1}


@pytest.mark.parametrize("bridge", ["passing"], indirect=True)
async def test_duplicate_python_dispatch_has_only_one_native_prompt(bridge, spec, repository, tmp_path):
    request = task_request(spec)
    kernels = [executor(tmp_path, repository, bridge.runtime) for _ in range(2)]
    results = await asyncio.gather(*(k.execute(request, _ignore) for k in kernels))
    assert results[0] == results[1]
    assert await stats(bridge) == {"creates": 1, "prompts": 1, "disposed": 1}


@pytest.mark.parametrize("combined", [False, True])
async def test_monetary_budget_blocks_before_any_harness_session(
    bridge, contracts, spec, repository, tmp_path, combined
):
    contract = contract_for(contracts) if combined else None
    spec = spec.model_copy(update={"max_total_cost": 1.0})
    result = await executor(tmp_path, repository, bridge.runtime, contract=combined).execute(
        task_request(spec, contract), _ignore
    )
    assert result.error.code == "HARNESS_ITERATION_COST_BUDGET_UNSUPPORTED"
    assert await stats(bridge) == {"creates": 0, "prompts": 0, "disposed": 0}


@pytest.mark.parametrize(
    ("bridge", "code"),
    [
        ("missing-usage", "HARNESS_ITERATION_USAGE_UNAVAILABLE"),
        ("wrong-model", "HARNESS_ITERATION_MODEL_MISMATCH"),
        ("out-of-scope", "TASK_LOOP_WRITE_SCOPE_VIOLATION"),
    ],
    indirect=["bridge"],
)
async def test_invalid_native_execution_is_not_proof_and_never_touches_tests(bridge, spec, repository, tmp_path, code):
    request = task_request(spec)
    kernel = executor(tmp_path, repository, bridge.runtime)
    result = await kernel.execute(request, _ignore)
    assert result.error.code == code
    attempt = kernel.store.attempt(request)
    assert attempt.candidate is None
    assert attempt.verification is None
    assert (await stats(bridge))["prompts"] == 1
    if bridge.root and code != "HARNESS_ITERATION_USAGE_UNAVAILABLE":
        assert attempt.total_tokens == 18
    else:
        view = await kernel.inspect_loop(request)
        assert view.total_tokens is None
        assert view.iterations[0].total_tokens is None
    assert _git(repository, "status", "--porcelain") == ""


def command(spec):
    return LoopIterationRequestV2(
        runtime=harness_binding(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        request_id=uuid4(),
        iteration=1,
        policy_digest="sha256:" + "b" * 64,
        specification=spec,
        parent_candidate=LiveLoopCandidate(
            candidate_id=uuid4(),
            parent_candidate_id=None,
            iteration=0,
            base_commit=spec.base_commit,
            changes={},
            content_digest=LiveLoopCandidate.digest(spec.base_commit, {}),
        ),
        mode="FILE_PROPOSAL",
        prompt="Đề xuất một vòng; không có lịch sử. 😀",
        system="One iteration",
        timeout_ms=1000,
    )


@pytest.mark.parametrize("body", [[], {"ready": True}, {"ready": False}, {"ready": True, "runtime": "other"}])
async def test_invalid_health_cannot_allocate_or_prompt(spec, tmp_path, body):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    runtime = HarnessTaskLoopRuntime(
        HarnessServerSettings(api_token=TOKEN), transport=httpx.MockTransport(transport), plugin_digest=PLUGIN_DIGEST
    )
    try:
        with pytest.raises(LoopRuntimeError, match="RELEASE_MISMATCH"):
            await runtime.open_iteration(command(spec), directory=tmp_path)
        assert len(calls) == 1
        assert calls[0].method == "GET"
    finally:
        await runtime.aclose()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"ready":true,"ready":false}', "RESPONSE_INVALID"),
        (b'{"ready":NaN}', "RESPONSE_INVALID"),
        (b"x" * 524_289, "RESPONSE_TOO_LARGE"),
    ],
    ids=["duplicate", "nonfinite", "oversized"],
)
async def test_bounded_json_and_no_duplicate_properties(spec, tmp_path, payload, code):
    runtime = HarnessTaskLoopRuntime(
        HarnessServerSettings(api_token=TOKEN),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload)),
        plugin_digest=PLUGIN_DIGEST,
    )
    try:
        with pytest.raises(LoopRuntimeError, match=code):
            await runtime.open_iteration(command(spec), directory=tmp_path)
    finally:
        await runtime.aclose()


@pytest.mark.parametrize(("status", "code"), [(401, "UNAUTHENTICATED"), (302, "UNAVAILABLE"), (503, "UNAVAILABLE")])
async def test_http_auth_errors_and_redirects_never_forward_credentials(spec, tmp_path, status, code):
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://foreign.invalid/health"})

    runtime = HarnessTaskLoopRuntime(
        HarnessServerSettings(api_token=TOKEN), transport=httpx.MockTransport(reply), plugin_digest=PLUGIN_DIGEST
    )
    try:
        with pytest.raises(LoopRuntimeError, match=code):
            await runtime.open_iteration(command(spec), directory=tmp_path)
        assert len(calls) == 1
        assert calls[0].url.host == "127.0.0.1"
        assert calls[0].headers["authorization"] == "Bearer " + TOKEN
    finally:
        await runtime.aclose()


def test_v2_and_native_schema_parity_and_no_fake_zero_price():
    assert json.loads((PLUGIN / "schemas/contracts.json").read_text(encoding="utf-8")) == generated()
    assert LoopRuntimeUsageV2(input_tokens=11, output_tokens=7, total_tokens=18, cost=None).cost is None
    with pytest.raises(ValidationError):
        LoopRuntimeUsageV2(input_tokens=True, output_tokens=7, total_tokens=18, cost=None)
    with pytest.raises(ValidationError):
        LoopRuntimeUsageV2(input_tokens=11, output_tokens=7, total_tokens=18, cost=0.0)


def test_package_runtime_choice_is_explicit_and_old_versions_are_unchanged(contracts, spec, monkeypatch):
    monkeypatch.setenv("ADLC_TASK_LOOP_HARNESS_ENABLED", "true")
    resolver = create_default_package_resolver()

    def resolve(item):
        return resolver.resolve(
            item, workflow_definition_id=uuid4(), workflow_definition_version=1, access_subject="owner"
        )

    harness = resolve(stage(spec))
    assert harness.implementation.adapter_ref == HARNESS_LOOP_SERVICE
    old = resolve(stage_for(spec=spec, task_loop_enabled=True))
    assert old.implementation.adapter_ref == "agent-provider:task-loop-opencode"
    native_contract = resolve(stage(spec, contract_for(contracts)))
    assert native_contract.implementation.adapter_ref == HARNESS_CONTRACT_LOOP_SERVICE
    opencode = stage(spec)
    opencode.configuration_overrides["loop_runtime"] = "OPENCODE"
    assert resolve(opencode).implementation.adapter_ref == old.implementation.adapter_ref
    monkeypatch.setenv("ADLC_TASK_LOOP_OPENCODE_ENABLED", "false")
    resolver = create_default_package_resolver()
    with pytest.raises(PackageResolutionError):
        resolve(opencode)
    assert resolve(stage(spec)).implementation.adapter_ref == HARNESS_LOOP_SERVICE
    monkeypatch.setenv("ADLC_TASK_LOOP_HARNESS_ENABLED", "false")
    resolver = create_default_package_resolver()
    with pytest.raises(PackageResolutionError):
        resolve(stage(spec))


async def test_rehashed_but_misbound_harness_checkpoint_cannot_be_recovered(
    bridge, spec, repository, tmp_path, monkeypatch
):
    kernel = executor(tmp_path, repository, bridge.runtime)
    request = task_request(spec)

    async def crash(*_args):
        raise SimulatedCrash

    monkeypatch.setattr(kernel.verifier, "verify", crash)
    with pytest.raises(SimulatedCrash):
        await kernel.execute(request, _ignore)
    with sqlite3.connect(kernel.store.path) as connection:
        row = json.loads(connection.execute("SELECT payload FROM task_loop_attempts").fetchone()[0])
        row["runtime_checkpoint"]["runtime"]["model_id"] = "foreign-model"
        connection.execute("UPDATE task_loop_attempts SET payload=?,digest=?", (json.dumps(row), sha256_digest(row)))
    result = await executor(tmp_path, repository, bridge.runtime).resume(request, _ignore)
    assert result.error.code == "TASK_LOOP_CHECKPOINT_CORRUPT"
    assert (await stats(bridge))["prompts"] == 1


async def test_token_budget_stops_before_second_native_session(bridge, spec, repository, tmp_path):
    limited = spec.model_copy(update={"max_total_tokens": 18})
    kernel = executor(tmp_path, repository, bridge.runtime)
    request = task_request(limited)
    result = await kernel.execute(request, _ignore)
    assert result.error.code == "TASK_LOOP_TOKEN_BUDGET_EXHAUSTED"
    assert result.metadata["task_loop"]["total_tokens"] == 18
    assert result.metadata["task_loop"]["total_cost"] is None
    assert (await kernel.inspect_loop(request)).stopped
    assert (await stats(bridge))["prompts"] == 1


@pytest.mark.parametrize(("field", "value"), [("loop_runtime", "OPENCODE"), ("submission_mode", "AUTO")])
async def test_incompatible_public_binding_stops_before_any_native_call(
    bridge, spec, repository, tmp_path, field, value
):
    request = task_request(spec)
    request.metadata["resolved_configuration"][field] = value
    result = await executor(tmp_path, repository, bridge.runtime).execute(request, _ignore)
    assert result.status is TaskResultStatus.FAILED
    assert await stats(bridge) == {"creates": 0, "prompts": 0, "disposed": 0}


def test_independent_token_cannot_fall_back_to_provider_or_one_shot_credentials(monkeypatch):
    monkeypatch.delenv("ADLC_HARNESS_ITERATION_API_TOKEN", raising=False)
    monkeypatch.setenv("ADLC_HARNESS_API_TOKEN", TOKEN)
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", TOKEN)
    with pytest.raises(ValueError, match="independent Harness iteration token"):
        HarnessTaskLoopRuntime.from_environment()
    monkeypatch.setenv("ADLC_HARNESS_ITERATION_API_TOKEN", "short")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        HarnessTaskLoopRuntime.from_environment()


@pytest.mark.parametrize("bridge", ["hold"], indirect=True)
@pytest.mark.parametrize("combined", [False, True])
async def test_unknown_native_usage_at_timeout_is_terminal_not_a_retry_budget_loophole(
    bridge, contracts, spec, repository, tmp_path, combined
):
    kernel = executor(tmp_path, repository, bridge.runtime, contract=combined)
    task = task_request(spec, contract_for(contracts) if combined else None)
    task.constraints["timeout_ms"] = 1500
    result = await kernel.execute(task, _ignore)
    assert result.status is TaskResultStatus.FAILED
    assert not result.error.retryable
    view = await kernel.inspect_loop(task)
    assert view.stopped
    assert not view.can_retry
    assert view.total_tokens is None
    assert kernel.store.attempt(task).candidate is None
    assert (await stats(bridge))["prompts"] == 1

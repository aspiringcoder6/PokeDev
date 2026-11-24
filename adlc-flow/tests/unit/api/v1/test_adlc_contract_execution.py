"""H5C bridge and historical owner reads, isolated from production state."""

# ruff: noqa: S101, SLF001, PLR2004
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from langflow.adlc.contract_bridge import EXECUTION_DOMAIN
from langflow.adlc.contract_execution_repository import ContractExecutionRepository
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.models import (
    ExecutorTarget,
    PlanTaskTraceability,
    TaskRequest,
    TaskResult,
    TaskRunStatus,
    WorkflowRunStatus,
)
from langflow.api.v1 import adlc_contracts as contract_api
from langflow.services.auth.utils import get_current_active_user
from tests.unit.adlc.test_contract_execution import approved_contract, proof_for
from tests.unit.api.v1 import test_adlc_contracts as fixture_module
from tests.unit.api.v1.test_adlc_contracts import signed

api_fixture = fixture_module.api_fixture  # Register the explicit-login/source-only fixture, without duplicating it.


@pytest.fixture
async def execution_fixture(api_fixture, tmp_path, monkeypatch):
    f = api_fixture
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "true")
    f.contract = approved_contract(f.repository, owner=str(f.user.id))
    f.executions = ContractExecutionRepository(tmp_path / "executions.sqlite3")
    f.app.dependency_overrides[contract_api.get_contract_execution_repository] = lambda: f.executions
    task = f.service._runs[f.run.id].run.tasks[0]
    run = f.service._runs[f.run.id].run
    run.status = WorkflowRunStatus.RUNNING
    run.execution_plan_id = uuid4()
    task.plan_traceability = PlanTaskTraceability(
        execution_plan_id=run.execution_plan_id,
        plan_task_id=uuid4(),
        source_workflow_stage_id=uuid4(),
        resolved_node_spec_id=uuid4(),
        package_id="coding-agent-contract-harness",
        package_version="0.1.0",
        package_content_digest="sha256:" + "a" * 64,
        resolved_node_digest="sha256:" + "b" * 64,
    )
    f.request = TaskRequest(
        request_id=uuid4(),
        workflow_run_id=run.id,
        task_run_id=task.id,
        attempt_id=uuid4(),
        task_definition_id=task.task_definition_id,
        task_type="implementation",
        name="Contract coding",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="contract-coding"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=str(uuid4()),
        requested_at=datetime.now(timezone.utc),
        metadata={
            "resolved_configuration": {
                "harness_profile_ref": "harness-profile:adlc-contract-coding/0.1.0",
                "approved_contract_ref": f.contract.reference.model_dump(mode="json"),
                "plugin_lock": [
                    {
                        "plugin_id": "vai-adlc-contract-execution",
                        "version": "0.1.0",
                        "required": True,
                        "content_digest": "sha256:" + "c" * 64,
                    }
                ],
            }
        },
    )
    task.request = f.request
    task.executor = f.request.executor
    task.current_attempt_id = f.request.attempt_id
    task.status = TaskRunStatus.RUNNING
    f.session = "contract-session"
    await f.callbacks.register_attempt(f.request)
    await f.callbacks.bind_session(f.request.attempt_id, f.session)
    await f.callbacks.attempts.update_status(f.request.attempt_id, TaskAttemptStatus.RUNNING)
    yield f
    f.executions.close()


async def bridge(f, operation="bind", *, domain=EXECUTION_DOMAIN, **payload):
    body, headers = signed(
        {"schema_version": "0.1", "operation": operation, "session_id": f.session, **payload}, domain=domain
    )
    return await f.client.post("/api/v1/adlc/contract-execution", content=body, headers=headers)


async def test_unified_package_uses_exact_contract_bridge_and_rejects_loop_route_confusion(
    execution_fixture, monkeypatch
):
    from langflow.adlc.contract_execution import RECOVERY_REF

    monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "true")
    f = execution_fixture
    task = f.service._runs[f.run.id].run.tasks[0]
    task.plan_traceability = task.plan_traceability.model_copy(
        update={"package_id": "coding-agent", "package_version": "0.2.0"}
    )
    configuration = f.request.metadata["resolved_configuration"]
    configuration.update(task_loop_enabled=False, submission_mode="MANUAL", recovery_ref=RECOVERY_REF)
    configuration["plugin_lock"].append(
        {
            "plugin_id": "vai-adlc-contract-recovery",
            "version": "0.1.0",
            "required": True,
            "content_digest": "sha256:" + "d" * 64,
        }
    )
    assert (await bridge(f)).status_code == 200
    binding = f.executions.get_by_attempt(f.request.attempt_id, owner_id=str(f.user.id))[0]
    assert binding.reference == f.contract.reference
    configuration["task_loop_enabled"] = True
    assert (await bridge(f)).status_code in {403, 409, 422}


async def test_kernel_binding_pins_source_from_another_owned_run_and_records_immutable_proof(
    execution_fixture, monkeypatch
):
    f = execution_fixture
    response = await bridge(f)
    assert response.status_code == 200
    binding = f.executions.get_by_attempt(f.request.attempt_id, owner_id=str(f.user.id))[0]
    assert binding.reference == f.contract.reference
    assert binding.scope.workflow_run_id != f.contract.binding.workflow_run_id
    proof = proof_for(binding)
    reported = await bridge(f, "report", proof=proof.model_dump(mode="json"))
    assert reported.status_code == 200
    assert (await bridge(f, "report", proof=proof.model_dump(mode="json"))).status_code == 200
    assert (
        await bridge(f, "report", proof=proof.model_copy(update={"artifact_id": uuid4()}).model_dump(mode="json"))
    ).status_code == 409
    # Historical reads remain available when execution is disabled or the run finishes.
    monkeypatch.setenv("ADLC_CONTRACT_EXECUTION_ENABLED", "false")
    f.service._runs[f.run.id].run.status = WorkflowRunStatus.SUCCEEDED
    f.service._runs[f.run.id].run.tasks[0].status = TaskRunStatus.SUCCEEDED
    rows = await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contract-executions")
    assert rows.status_code == 200
    assert rows.json()[0]["proof"]["artifact_checksum"] == proof.artifact_checksum
    assert rows.headers["cache-control"] == "no-store"
    session_rows = await f.client.get(f"/api/v1/adlc/harness-sessions/{f.session}/contract-executions")
    assert session_rows.status_code == 200
    assert session_rows.json()[0]["binding"]["reference"] == f.contract.reference.model_dump(mode="json")


@pytest.mark.parametrize(
    "case", ["writer-domain", "owner", "contract", "inactive", "stale", "wrong-profile", "wrong-attempt"]
)
async def test_bridge_rejects_authority_confusion_before_execution(execution_fixture, case):
    f = execution_fixture
    if case == "writer-domain":
        response = await bridge(f, domain=b"adlc-contract-tools-v1\n")
    elif case in {"owner", "contract"}:
        response = await bridge(f, **{case: "caller-selected"})
    else:
        task = f.service._runs[f.run.id].run.tasks[0]
        if case == "inactive":
            task.status = TaskRunStatus.FAILED
        if case == "stale":
            task.request.metadata["resolved_configuration"]["approved_contract_ref"]["content_digest"] = (
                "sha256:" + "0" * 64
            )
        if case == "wrong-profile":
            task.request.metadata["resolved_configuration"]["harness_profile_ref"] = (
                "harness-profile:adlc-skilltree/0.1.0"
            )
        if case == "wrong-attempt":
            task.current_attempt_id = uuid4()
        response = await bridge(f)
    assert response.status_code in {401, 403, 409, 422}
    assert f.executions.list_for_run(f.run.id, owner_id=str(f.user.id)) == []


async def test_other_user_cannot_read_bound_contract_or_historical_evidence(execution_fixture):
    f = execution_fixture
    assert (await bridge(f)).status_code == 200
    f.app.dependency_overrides[get_current_active_user] = lambda: type("User", (), {"id": uuid4()})()
    assert (await f.client.get(f"/api/v1/adlc/runs/{f.run.id}/contract-executions")).status_code == 404
    assert (await f.client.get(f"/api/v1/adlc/harness-sessions/{f.session}/contract-executions")).status_code == 404


async def test_coordinator_rejects_forged_success_before_task_transition(execution_fixture, monkeypatch):
    from langflow.adlc import contract_execution

    f = execution_fixture
    monkeypatch.setattr(contract_execution, "get_contract_repository", lambda: f.repository)
    assert (await bridge(f)).status_code == 200
    binding = f.executions.get_by_attempt(f.request.attempt_id, owner_id=str(f.user.id))[0]
    proof = proof_for(binding)
    assert (await bridge(f, "report", proof=proof.model_dump(mode="json"))).status_code == 200
    record = f.service._runs[f.run.id]
    task = record.run.tasks[0]
    result = TaskResult(
        request_id=f.request.request_id,
        workflow_run_id=f.request.workflow_run_id,
        task_run_id=f.request.task_run_id,
        attempt_id=f.request.attempt_id,
        status="SUCCEEDED",
        output={"summary": "forged success", "evidence": proof.model_dump(mode="json")},
        artifacts=[],
        error=None,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    f.service._on_executor_state(
        record, record.run, task, record.definitions[str(task.key)], TaskRunStatus.SUCCEEDED, result
    )
    assert task.status == TaskRunStatus.FAILED
    assert task.result.error.code == "CONTRACT_EXECUTION_EVIDENCE_INVALID"
    assert task.result.output is None
    assert task.artifacts == []
    assert record.run.events[-1].event_type == "task_run.failed"

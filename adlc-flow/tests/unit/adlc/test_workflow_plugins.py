"""Real compiler/coordinator with deterministic HTTP fixtures; no external jobs or memory writes."""

# ruff: noqa: S101, PLR2004, PT018, INP001 - assertions and fixed HTTP fixture values.

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import CreateWorkflowRunRequest
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.workflow_plugin_client import MemoryConnection, PluginError, WorkflowPluginClient
from langflow.adlc.workflow_plugin_starter import starter
from langflow.adlc.workflow_plugins import (
    PACKAGES,
    SERVICE,
    PluginLedger,
    WorkflowPluginExecutor,
    WorkflowPluginService,
    bindings,
)


def compiled(monkeypatch, *, check_only=False):
    owner, flow_id = str(uuid4()), uuid4()
    monkeypatch.setenv("ADLC_WORKFLOW_PLUGINS_ENABLED", "true")
    data = starter(check_only=check_only)
    data["data"]["adlc"]["workflow_definition_id"] = str(flow_id)
    date = datetime.now(timezone.utc)
    workflow = parse_blueprint_flow(
        data["data"],
        BlueprintParseContext(
            flow_id=flow_id,
            project_id=uuid4(),
            name=data["name"],
            description=data["description"],
            created_by=owner,
            created_at=date,
            updated_at=date,
        ),
    )
    planning = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = planning.create_plan(workflow, owner_id=owner, generated_by=owner)
    assert plan.validation_status.value == "VALID", plan.validation_errors
    if plan.approval_required:
        plan = planning.approve_plan(plan.execution_plan_id, owner_id=owner, approved_by=owner, comment=None)
    return owner, workflow, plan


def configure(tmp_path, monkeypatch, owner, flow_id):
    path = tmp_path / "private-connections.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "bindings": [
                    {
                        "owner_id": owner,
                        "flow_id": str(flow_id),
                        "connection": "project",
                        "memory": {"tenant_id": "tenant-project-a", "dataset": "pokedev-project-a"},
                        "replay": {
                            "session": "EXP-project-a.json",
                            "api_url": "https://staging.example.test",
                            "email": "test-actor@example.test",
                            "token": "private-fixture-token",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ADLC_WORKFLOW_PLUGIN_REGISTRY", str(path))
    return path


class Backend:
    def __init__(self, *, lose_create=False, scope_supported=True, running=False):
        self.requests = []
        self.lose_create, self.scope_supported, self.running = lose_create, scope_supported, running

    def response(self, request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok", "version": "fixture"})
        if request.url.path == "/api/v1/replay":
            assert request.headers["authorization"] == "Bearer private-fixture-token"
            assert body["heal"] is False and body["cleanup_template"] == "" and body["headed"] is False
            if self.lose_create:
                raise httpx.ReadTimeout(request=request)
            return httpx.Response(200, json={"job_id": "job-project-a"})
        if request.url.path == "/api/v1/result/job-project-a":
            return httpx.Response(
                200,
                json={
                    "job_id": "job-project-a",
                    "status": "running" if self.running else "completed",
                    "exit_code": 0,
                    "metrics": {"checks": 2},
                    "log_tail": "never retained",
                },
            )
        assert request.url.path == "/mcp"
        method = body["method"]
        if method == "notifications/initialized":
            assert request.headers["Mcp-Session-Id"] == "fixture-mcp-session"
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "Cognee fixture", "version": "test"},
                "capabilities": {},
            }
        elif method == "tools/list":
            names = ["query", "search_type", "datasets", "top_k"] + (["tenant_id"] if self.scope_supported else [])
            result = {
                "tools": [
                    {"name": "recall", "inputSchema": {"type": "object", "properties": {key: {} for key in names}}}
                ]
            }
        else:
            assert method == "tools/call" and body["params"]["name"] == "recall"
            args = body["params"]["arguments"]
            assert args["datasets"] == "pokedev-project-a"
            if self.scope_supported:
                assert args["tenant_id"] == "tenant-project-a"
            else:
                assert "tenant_id" not in args
            assert args["search_type"] == "CHUNKS"
            result = {"content": [{"type": "text", "text": "Project-specific context fixture"}], "isError": False}
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": body["id"], "result": result},
            headers={"Mcp-Session-Id": "fixture-mcp-session"},
        )


async def wait_for(coordinator, run_id, owner):
    async with asyncio.timeout(10):
        while True:
            run = await coordinator.get_run(run_id, owner_id=owner)
            if run.status.value in {"SUCCEEDED", "FAILED", "PAUSED", "CANCELLED"}:
                return run
            await asyncio.sleep(0.01)


async def start(tmp_path, owner, workflow, plan, backend):
    service = WorkflowPluginService(
        PluginLedger(tmp_path / "calls.sqlite3"),
        client=WorkflowPluginClient(transport=httpx.MockTransport(backend.response)),
    )
    executor = WorkflowPluginExecutor(service)
    coordinator = AdlcRunService(TaskExecutorRouter(MockExecutor(), routes={SERVICE: executor}))
    run = await coordinator.start_run(
        flow_id=workflow.workflow_definition_id,
        flow_name=workflow.name,
        definitions=materialize_task_definitions(plan),
        request=CreateWorkflowRunRequest(flowId=workflow.workflow_definition_id, execution_mode="EXECUTION_PLAN"),
        owner_id=owner,
        execution_plan_id=plan.execution_plan_id,
    )
    return coordinator, executor, run


async def test_compiled_workflow_calls_both_backends_and_retains_bound_results(tmp_path, monkeypatch):
    owner, workflow, plan = compiled(monkeypatch)
    configure(tmp_path, monkeypatch, owner, workflow.workflow_definition_id)
    backend = Backend()
    coordinator, _, run = await start(tmp_path, owner, workflow, plan, backend)
    final = await wait_for(coordinator, run.id, owner)
    assert final.status.value == "SUCCEEDED", [
        (task.status, task.result.error if task.result else None) for task in final.tasks
    ]
    assert {task.plan_traceability.package_id for task in final.tasks} == set(PACKAGES.values())
    memory = next(task for task in final.tasks if task.executor.operation == "MEMORY_CONTEXT")
    assert memory.result.output["outputs"]["context"]["context"] == "Project-specific context fixture"
    replay = next(task for task in final.tasks if task.executor.operation == "TESTFORGE_REPLAY")
    record = replay.result.output["outputs"]["plugin_result"]
    assert record["job_id"] == "job-project-a" and record["verification_verdict"] == "NOT_ATTESTED"
    assert record["verification_evidence"] is False and "log_tail" not in record["data"]
    retained = PluginLedger(tmp_path / "calls.sqlite3")
    assert len(retained.list(owner=owner, run_id=run.id)) == 3
    assert retained.list(owner=str(uuid4()), run_id=run.id) == []
    assert len([request for request in backend.requests if request[1] == "/api/v1/replay"]) == 1
    public = json.dumps(retained.list(owner=owner, run_id=run.id))
    assert "private-fixture-token" not in public
    await coordinator.shutdown()


async def test_uncertain_create_is_not_retried_by_restart_or_concurrent_delivery(tmp_path, monkeypatch):
    owner, workflow, plan = compiled(monkeypatch)
    configure(tmp_path, monkeypatch, owner, workflow.workflow_definition_id)
    backend = Backend(lose_create=True)
    coordinator, executor, run = await start(tmp_path, owner, workflow, plan, backend)
    final = await wait_for(coordinator, run.id, owner)
    assert final.status.value in {"FAILED", "PAUSED"}
    task = next(task for task in final.tasks if task.executor.operation == "TESTFORGE_REPLAY")
    assert task.result.output["outputs"]["plugin_result"]["state"] == "UNKNOWN"
    executor.bind_plugin_workflow_authority(
        lambda _: {"owner_id": owner, "flow_id": str(workflow.workflow_definition_id)}
    )

    async def state(*_args):
        pass

    await asyncio.gather(executor.resume(task.request, state), executor.execute(task.request, state))
    assert len([request for request in backend.requests if request[1] == "/api/v1/replay"]) == 1
    await coordinator.shutdown()


async def test_scope_missing_never_reads_global_memory():
    backend = Backend(scope_supported=False)
    client = WorkflowPluginClient(transport=httpx.MockTransport(backend.response))
    with pytest.raises(PluginError, match="WORKFLOW_PLUGIN_MEMORY_SCOPE_UNSUPPORTED"):
        await client.memory(MemoryConnection(tenant_id="tenant-project-a", dataset="pokedev-project-a"), query="query")
    assert not any(body and body.get("method") == "tools/call" for _, _, body in backend.requests)


async def test_plain_cognee_is_scoped_to_one_backend_bound_dataset():
    backend = Backend(scope_supported=False)
    client = WorkflowPluginClient(transport=httpx.MockTransport(backend.response))
    result = await client.memory(MemoryConnection(dataset="pokedev-project-a"), query="query")
    assert result["context"] == "Project-specific context fixture"
    assert result["backend_tenant_enforced"] is False
    assert result["scope_mode"] == "ADLC_OWNER_FLOW_DATASET"


def test_connection_registry_is_owner_and_workflow_scoped(tmp_path, monkeypatch):
    owner, flow_id = str(uuid4()), uuid4()
    configure(tmp_path, monkeypatch, owner, flow_id)
    assert len(bindings(owner, flow_id)) == 1
    assert bindings(str(uuid4()), flow_id) == []
    assert bindings(owner, uuid4()) == []


async def test_health_workflow_works_without_dataset_or_replay_credentials(tmp_path, monkeypatch):
    owner, workflow, plan = compiled(monkeypatch, check_only=True)
    monkeypatch.delenv("ADLC_WORKFLOW_PLUGIN_REGISTRY", raising=False)
    backend = Backend()
    coordinator, _, run = await start(tmp_path, owner, workflow, plan, backend)
    final = await wait_for(coordinator, run.id, owner)
    assert final.status.value == "SUCCEEDED"
    assert not any(
        path == "/api/v1/replay" or (body and body.get("method") == "tools/call") for _, path, body in backend.requests
    )
    await coordinator.shutdown()


async def test_cancel_does_not_claim_broker_job_cancelled_or_post_a_second_job(tmp_path, monkeypatch):
    owner, workflow, _ = compiled(monkeypatch)
    configure(tmp_path, monkeypatch, owner, workflow.workflow_definition_id)
    backend = Backend(running=True)
    service = WorkflowPluginService(
        PluginLedger(tmp_path / "cancel.sqlite3"),
        client=WorkflowPluginClient(transport=httpx.MockTransport(backend.response)),
    )
    connection = service.connection(owner, workflow.workflow_definition_id, "project", "TESTFORGE_REPLAY")
    record, _, _ = service.ledger.begin(
        call_id=uuid4(),
        owner=owner,
        run_id=uuid4(),
        flow_id=workflow.workflow_definition_id,
        task_id=uuid4(),
        operation="TESTFORGE_REPLAY",
        request_digest="fixture",
        connection_digest=connection.digest(),
    )
    task = asyncio.create_task(service.perform(record, connection, {}, fresh=True))
    while not any(path.startswith("/api/v1/result/") for _, path, _ in backend.requests):
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    saved, _ = service.ledger.get(record["id"], owner=owner, run_id=record["run_id"])
    assert saved["state"] == "CANCEL_REQUESTED" and saved["job_id"] == "job-project-a"
    assert not any("cancel" in path for _, path, _ in backend.requests)

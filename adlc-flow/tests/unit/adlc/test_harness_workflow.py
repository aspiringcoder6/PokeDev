"""Real workflow planning/Git, explicit offline model and remote-publish fixtures."""

# ruff: noqa: S101, INP001, PLR2004
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.harness_demo_models import DemoError
from langflow.adlc.harness_workflow import SERVICE, HarnessWorkflowExecutor, session_id
from langflow.adlc.harness_workflow_starter import starter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, CreateWorkflowRunRequest
from langflow.adlc.packages.defaults import create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunService
from tests.unit.adlc.test_harness_demo import service as fixture_service


def compiled(monkeypatch):
    owner, flow_id = str(uuid4()), uuid4()
    monkeypatch.setenv("ADLC_HARNESS_DEMO_ENABLED", "true")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_ENABLED", "true")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_OWNER_ID", owner)
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "aspiringcoder6/vanguard")
    monkeypatch.delenv("ADLC_DEMO_MEMORY_PROJECT_ID", raising=False)
    data = starter()
    data["data"]["adlc"]["workflow_definition_id"] = str(flow_id)
    now = datetime.now(timezone.utc)
    workflow = parse_blueprint_flow(
        data["data"],
        BlueprintParseContext(
            flow_id=flow_id,
            project_id=uuid4(),
            name=data["name"],
            description=data["description"],
            created_by=owner,
            created_at=now,
            updated_at=now,
        ),
    )
    planning = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))
    plan = planning.create_plan(workflow, owner_id=owner, generated_by=owner)
    assert str(plan.validation_status.value) == "VALID", plan.validation_errors
    plan = planning.approve_plan(plan.execution_plan_id, owner_id=owner, approved_by=owner, comment=None)
    return owner, workflow, plan


async def wait_for(coordinator, run_id, owner, state):
    async with asyncio.timeout(30):
        while True:
            run = await coordinator.get_run(run_id, owner_id=owner)
            if run.status.value == state:
                return run
            if run.status.value in {"FAILED", "PAUSED", "CANCELLED"}:
                raise AssertionError([(t.status.value, t.result.error if t.result else None) for t in run.tasks])
            await asyncio.sleep(0.02)


async def test_workflow_requires_both_exact_owner_gates_before_publication(tmp_path, monkeypatch):
    owner, workflow, plan = compiled(monkeypatch)
    native = fixture_service(tmp_path)
    prepare, publish = native.prepare, native.publish
    publications = []

    async def local_source(run_id):
        await native.update(run_id, github=False)
        try:
            return await prepare(run_id)
        finally:
            await native.update(run_id, github=True)

    async def fixture_remote(run_id):
        publications.append(str(run_id))
        await native.update(run_id, github=False)
        await publish(run_id)  # Actual local bare push; the remote acknowledgement below is explicitly a fixture.
        record = native.ledger.get(run_id)
        await native.update(
            run_id,
            github=True,
            publish_receipt={
                **record["publish_receipt"],
                "github_pushed": True,
                "repository": "aspiringcoder6/vanguard",
                "branch": record["remote_branch"],
                "remote_evidence": "TEST_FIXTURE_NOT_GITHUB",
            },
        )

    native.prepare, native.publish = local_source, fixture_remote
    executor = HarnessWorkflowExecutor(native)
    coordinator = AdlcRunService(TaskExecutorRouter(MockExecutor(), routes={SERVICE: executor}))
    run = await coordinator.start_run(
        flow_id=workflow.workflow_definition_id,
        flow_name=workflow.name,
        definitions=materialize_task_definitions(plan),
        request=CreateWorkflowRunRequest(flowId=workflow.workflow_definition_id, execution_mode="EXECUTION_PLAN"),
        owner_id=owner,
        execution_plan_id=plan.execution_plan_id,
    )
    first = await wait_for(coordinator, run.id, owner, "WAITING_APPROVAL")
    approval = next(a for a in first.approval_requests if a.status.value == "PENDING")
    assert approval.context.payload["harness_workflow_review"]["kind"] == "PLAN"
    assert [c["stage"] for c in native.client.commands] == ["PLAN"]
    assert not publications
    with pytest.raises(AdlcRunNotFoundError):
        await coordinator.approve(
            approval.approval_request_id,
            owner_id="another-owner",
            actor=Actor(type="USER", id="another-owner"),
            comment=None,
        )
    await coordinator.approve(
        approval.approval_request_id, owner_id=owner, actor=Actor(type="USER", id=owner), comment=None
    )
    second = await wait_for(coordinator, run.id, owner, "WAITING_APPROVAL")
    approval = next(a for a in second.approval_requests if a.status.value == "PENDING")
    assert approval.context.payload["harness_workflow_review"]["kind"] == "COMMIT"
    assert not publications
    assert [c["stage"] for c in native.client.commands] == ["PLAN", "ITERATE", "HANDOFF"]
    await coordinator.approve(
        approval.approval_request_id, owner_id=owner, actor=Actor(type="USER", id=owner), comment=None
    )
    final = await wait_for(coordinator, run.id, owner, "SUCCEEDED")
    assert len(final.tasks) == 5
    assert len(publications) == 1
    assert all(t.status.value == "SUCCEEDED" for t in final.tasks)
    record = native.ledger.get(session_id(run.id), owner)
    assert record["workflow_run_id"] == str(run.id)
    assert record["publish_receipt"]["remote_evidence"] == "TEST_FIXTURE_NOT_GITHUB"
    await coordinator.shutdown()


def test_starter_does_not_execute_and_has_exact_published_packages(monkeypatch):
    _, workflow, plan = compiled(monkeypatch)
    assert len(workflow.stages) == len(plan.tasks) == 5
    assert all(s.package_ref.content_digest for s in workflow.stages)
    assert all("demo" not in s.name.lower() for s in workflow.stages)


def test_unobserved_intent_is_not_replayed(tmp_path):
    executor = HarnessWorkflowExecutor(fixture_service(tmp_path))
    from types import SimpleNamespace

    request = SimpleNamespace(workflow_run_id=uuid4(), model_dump=lambda **_: {"id": "same-request"})
    assert executor.saved(request, "PLAN", reserve=True) is None
    with pytest.raises(DemoError, match="HARNESS_WORKFLOW_STAGE_INTERRUPTED"):
        executor.saved(request, "PLAN", reserve=True)

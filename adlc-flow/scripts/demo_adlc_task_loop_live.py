"""Compile or run the unified Coding Agent task loop against a committed local repository."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from langflow.adlc.blueprints.models import WorkflowDefinition
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import CreateWorkflowRunRequest, WorkflowRunStatus
from langflow.adlc.opencode_client import OpenCodeHttpClient, OpenCodeServerSettings
from langflow.adlc.packages.access import InMemoryPackageAccessPolicy
from langflow.adlc.packages.defaults import (
    TASK_LOOP_LIVE_REFERENCE_IDS,
    UNIFIED_CODING_PACKAGE_IDENTITIES,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_repository import SqliteRunRepository
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE, LiveTaskLoopExecutor
from langflow.adlc.task_loop_live_models import LiveLoopSpec
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import TaskLoopWorkspace
from scripts.demo_adlc_task_loop import demo_workflow


def live_definitions(spec: LiveLoopSpec) -> tuple[WorkflowDefinition, list]:
    payload = demo_workflow(spec).model_dump(mode="json")
    payload.update(
        workflow_definition_id="db000002-0000-4000-8000-000000000002",
        name="Verified task loop",
        description="Coding Agent: fresh OpenCode sessions and protected behavioral checks.",
        metadata={"delivery": "B"},
    )
    stage = payload["stages"][0]
    stage.update(
        stage_id="db000004-0000-4000-8000-000000000004",
        name="Coding Agent",
        package_ref={"package_id": "coding-agent", "version": "0.2.0"},
        configuration_overrides={"task_loop_enabled": True},
        metadata={"delivery": "B"},
    )
    workflow = WorkflowDefinition.model_validate(payload)
    policy = InMemoryPackageAccessPolicy(
        default_visible_packages=UNIFIED_CODING_PACKAGE_IDENTITIES,
        default_authorized_references=TASK_LOOP_LIVE_REFERENCE_IDS,
    )
    plans = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver(access_policy=policy)))
    plan = plans.create_plan(workflow, owner_id="task-loop-demo", generated_by="task-loop-demo")
    approved = plans.approve_plan(plan.execution_plan_id, owner_id="task-loop-demo", approved_by="task-loop-demo")
    return workflow, materialize_task_definitions(approved)


async def run_live(spec: LiveLoopSpec, *, source: Path, state_root: Path) -> dict:
    client = OpenCodeHttpClient(OpenCodeServerSettings.from_environment())
    await client.health()
    executor = LiveTaskLoopExecutor(
        workspace=TaskLoopWorkspace(source, state_root / "worktrees"),
        store=TaskLoopStore(state_root / "task-loop.sqlite3"),
        client=client,
    )
    workflow, definitions = live_definitions(spec)
    service = AdlcRunService(
        TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_LIVE_SERVICE: executor}),
        repository=SqliteRunRepository(state_root / "runs.sqlite3"),
        artifact_payloads=executor.artifact_payloads,
    )
    run = await service.start_run(
        flow_id=workflow.workflow_definition_id,
        flow_name=workflow.name,
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(
            flowId=workflow.workflow_definition_id, executionMode="EXECUTION_PLAN", delayMs=0
        ),
        owner_id="task-loop-demo",
    )
    while run.status in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.QUEUED}:
        await asyncio.sleep(0.1)
        run = await service.get_run(run.id, owner_id="task-loop-demo")
    return {
        "provider_simulated": False,
        "verification_mode": "COMMAND",
        "approval_simulated": False,
        "status": run.status.value,
        "workflow_run_id": str(run.id),
        "task": run.tasks[0].model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--export-workflow", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = LiveLoopSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    if args.export_workflow:
        payload = live_definitions(spec)[0].model_dump(mode="json")
        args.export_workflow.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return
    if args.source is None or args.state_root is None:
        parser.error("Live execution requires --source and --state-root; use --export-workflow for a read-only export.")
    report = asyncio.run(run_live(spec, source=args.source.resolve(), state_root=args.state_root.resolve()))
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

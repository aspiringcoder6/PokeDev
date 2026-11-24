"""Run Delivery A offline: fail, fail, pass, then await or simulate final approval."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from langflow.adlc.blueprints.models import WorkflowDefinition
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import Actor, CreateWorkflowRunRequest, WorkflowRunStatus
from langflow.adlc.packages.access import InMemoryPackageAccessPolicy
from langflow.adlc.packages.defaults import (
    TASK_LOOP_MOCK_PACKAGE_IDENTITIES,
    TASK_LOOP_MOCK_REFERENCE_IDS,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_repository import InMemoryRunRepository
from langflow.adlc.run_service import AdlcRunService
from langflow.adlc.task_loop import TASK_LOOP_MOCK_SERVICE, MockTaskLoopExecutor
from langflow.adlc.task_loop_models import TaskLoopSpec

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "adlc-contracts/task-loop/v0.1/examples/task-loop-spec.json"


def demo_workflow(spec: TaskLoopSpec | None = None) -> WorkflowDefinition:
    """Build one high-level stage backed by the exact mock package."""
    specification = spec or TaskLoopSpec.model_validate_json(SPEC_PATH.read_text(encoding="utf-8"))
    timestamp = datetime(2026, 10, 10, tzinfo=timezone.utc)
    return WorkflowDefinition.model_validate(
        {
            "schema_version": "0.1",
            "workflow_definition_id": str(UUID("da000002-0000-4000-8000-000000000002")),
            "project_id": str(UUID("da000003-0000-4000-8000-000000000003")),
            "name": "Deterministic task loop",
            "description": "Delivery A: three fresh mock sessions build one cumulative addition artifact.",
            "version": 1,
            "status": "PUBLISHED",
            "stages": [
                {
                    "stage_id": str(UUID("da000004-0000-4000-8000-000000000004")),
                    "stage_type": "IMPLEMENTATION",
                    "name": "Task Loop (Mock)",
                    "objective": specification.specification,
                    "inputs": {"task_loop_spec": specification.model_dump(mode="json")},
                    "expected_outputs": ["candidate", "verification_report"],
                    "package_ref": {"package_id": "task-loop", "version": "0.1.0"},
                    "configuration_overrides": {},
                    "execution_profile_overrides": {},
                    "policy_overrides": {"retry": {"max_attempts": specification.max_iterations}},
                    "secret_refs": {},
                    "position": {"x": 80, "y": 120},
                    "metadata": {"mock": True},
                }
            ],
            "edges": [],
            "default_policies": {},
            "created_by": "task-loop-demo",
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata": {"mock": True},
        }
    )


def demo_definitions(spec: TaskLoopSpec | None = None) -> tuple[WorkflowDefinition, list]:
    """Exercise package resolution, plan approval, and materialization offline."""
    policy = InMemoryPackageAccessPolicy(
        default_visible_packages=TASK_LOOP_MOCK_PACKAGE_IDENTITIES,
        default_authorized_references=TASK_LOOP_MOCK_REFERENCE_IDS,
    )
    plans = ExecutionPlanService(BlueprintCompiler(create_default_package_resolver(access_policy=policy)))
    workflow = demo_workflow(spec)
    plan = plans.create_plan(workflow, owner_id="task-loop-demo", generated_by="task-loop-demo")
    approved = plans.approve_plan(plan.execution_plan_id, owner_id="task-loop-demo", approved_by="task-loop-demo")
    return workflow, materialize_task_definitions(approved)


async def run_demo(*, simulate_approval: bool = False) -> dict:
    workflow, definitions = demo_definitions()
    executor = MockTaskLoopExecutor()
    router = TaskExecutorRouter(MockExecutor(), routes={TASK_LOOP_MOCK_SERVICE: executor})
    service = AdlcRunService(router, repository=InMemoryRunRepository())
    flow_id = uuid4()
    run = await service.start_run(
        flow_id=flow_id,
        flow_name=workflow.name,
        definitions=definitions,
        execution_plan_id=definitions[0].plan_traceability.execution_plan_id,
        request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="EXECUTION_PLAN", delayMs=0),
        owner_id="task-loop-demo",
    )
    if run.status is not WorkflowRunStatus.WAITING_APPROVAL:
        message = f"Mock loop did not reach final approval: {run.status.value}"
        raise RuntimeError(message)
    status_before_approval = run.status.value
    if simulate_approval:
        run = await service.approve(
            run.approval_requests[-1].approval_request_id,
            owner_id="task-loop-demo",
            actor=Actor(type="SYSTEM", id="task-loop-demo", display_name="Simulated demo reviewer"),
            comment="Simulated approval of deterministic mock evidence; no human or live sign-off.",
        )
    history = executor.history(run.id, run.tasks[0].id)
    return {
        "mode": "MOCK",
        "status_before_approval": status_before_approval,
        "approval_simulated": simulate_approval,
        "status": run.status.value,
        "task_run_id": str(run.tasks[0].id),
        "spec_digest": history[0].prompt.spec_digest,
        "iteration_count": len(history),
        "iterations": [record.summary() for record in history],
        "sessions": [
            {"session_id": str(session.session_id), "message_count": len(session.messages)}
            for session in executor.agent.sessions
        ],
        "candidates": [record.candidate.model_dump(mode="json") for record in history],
        "events": [{"sequence": event.sequence, "event_type": event.event_type} for event in run.events],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulate-approval", action="store_true", help="Simulate the demo reviewer after mock checks pass."
    )
    parser.add_argument("--output", type=Path, help="Save a reviewable mock evidence report.")
    parser.add_argument(
        "--export-workflow", type=Path, help="Export the demo WorkflowDefinition instead of running it."
    )
    args = parser.parse_args()
    if args.export_workflow:
        args.export_workflow.parent.mkdir(parents=True, exist_ok=True)
        args.export_workflow.write_text(demo_workflow().model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"Exported mock workflow: {args.export_workflow}")
        return
    report = asyncio.run(run_demo(simulate_approval=args.simulate_approval))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for iteration in report["iterations"]:
        checks = iteration["verification"]["checks"]
        passed = sum(check["passed"] for check in checks)
        verdict = "PASS" if passed == len(checks) else "FAIL"
        print(
            f"Iteration {iteration['iteration']}: {verdict} ({passed}/{len(checks)} mock checks), "
            f"fresh session {iteration['session_id']}"
        )
    print(f"Run: {report['status']} (approval simulated: {report['approval_simulated']}). Model calls: 0.")


if __name__ == "__main__":
    main()

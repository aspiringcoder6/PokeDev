# ruff: noqa: PLR2004, S101

"""Unit coverage for the Planner Agent proposal slice."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from langflow.adlc.packages.defaults import (
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.proposals import (
    GeneratePlanProposalConfig,
    LLMPlannerAgent,
    MockPlannerAgent,
    ProposalService,
    ProposalStateError,
    ProposalValidator,
)
from langflow.adlc.planning.proposals.errors import (
    PLANNER_MALFORMED_OUTPUT,
    PLANNER_TIMEOUT,
    PLANNER_UNAVAILABLE,
    PlannerGenerationError,
    ProposalNotFoundError,
    ProposalStateError,
)
from langflow.adlc.planning.proposals.models import (
    GeneratePlanProposalConfig,
    PlanProposalLimits,
    PlannerMode,
    ProposedTask,
)
from langflow.adlc.planning.proposals.planner import ProposedTaskDraft
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.run_service import AdlcRunService
from pydantic import BaseModel

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import WorkflowDefinition

STAGE_IDS = {
    "req": UUID("00000000-0000-4000-8000-000000000001"),
    "impl_a": UUID("00000000-0000-4000-8000-000000000002"),
    "impl_b": UUID("00000000-0000-4000-8000-000000000003"),
    "verify": UUID("00000000-0000-4000-8000-000000000004"),
}


class _TaskDraft(BaseModel):
    pass


def _stage_adlc(stage_id: UUID, stage_type: str, name: str, objective: str, package: str) -> dict:
    inputs = {"approval_context": "Review."} if package == "approval" else {"requirement": objective}
    return {
        "document_type": "WORKFLOW_STAGE",
        "schema_version": "0.1",
        "stage_id": str(stage_id),
        "stage_type": stage_type,
        "name": name,
        "objective": objective,
        "inputs": inputs,
        "expected_outputs": ["approval_decision"] if package == "approval" else ["source_patch"],
        "package_ref": {"package_id": package, "version": "0.1.0"},
    }


def _graph(workflow_id: UUID) -> dict:
    """Parallel fixture: Requirements -> (Implement A, Implement B) -> Verify -> Approval."""
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(workflow_id),
            "version": 1,
        },
        "nodes": [
            {
                "id": "req",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": _stage_adlc(
                        STAGE_IDS["req"], "REQUIREMENTS", "Requirements", "Gather requirements.", "coding-agent"
                    )
                },
            },
            {
                "id": "impl_a",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": _stage_adlc(
                        STAGE_IDS["impl_a"], "IMPLEMENTATION", "Implement A", "Implement scope A.", "coding-agent"
                    )
                },
            },
            {
                "id": "impl_b",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": _stage_adlc(
                        STAGE_IDS["impl_b"], "IMPLEMENTATION", "Implement B", "Implement scope B.", "coding-agent"
                    )
                },
            },
            {
                "id": "verify",
                "type": "genericNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "adlc": _stage_adlc(STAGE_IDS["verify"], "TESTING", "Verify", "Verify the result.", "coding-agent")
                },
            },
        ],
        "edges": [
            {"source": "req", "target": "impl_a"},
            {"source": "req", "target": "impl_b"},
            {"source": "impl_a", "target": "verify"},
            {"source": "impl_b", "target": "verify"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _workflow() -> WorkflowDefinition:
    workflow_id = uuid4()
    context = BlueprintParseContext(
        flow_id=workflow_id,
        project_id=workflow_id,
        name="Parallel Fixture",
        description="",
        created_by="tester",
        created_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    return parse_blueprint_flow(_graph(workflow_id), context)


def _registry():
    return create_default_package_registry()


def _plan_service():
    resolver = create_default_package_resolver(
        create_default_package_registry(),
        create_default_package_access_policy(),
    )
    return ExecutionPlanService(BlueprintCompiler(resolver))


def _service(planner=None) -> ProposalService:
    return ProposalService(
        planner or MockPlannerAgent(),
        _registry(),
        _plan_service(),
    )


async def test_simple_linear_workflow_decomposes_atomically() -> None:
    service = _service()
    workflow = _workflow()
    proposal = await service.generate_proposal(workflow, owner_id="o", generated_by="t")
    assert proposal.status.value == "GENERATED"
    assert proposal.planner_mode is PlannerMode.MOCK
    assert all(task.task_id for task in proposal.tasks)
    # IMPLEMENTATION stage decomposes into 3 parallel tasks; others 1-2.
    assert len(proposal.tasks) >= len(workflow.stages)


async def test_owners_can_propose_the_same_workflow_without_overwriting_each_other() -> None:
    service = _service()
    workflow = _workflow()
    first = await service.generate_proposal(workflow, owner_id="first", generated_by="first")
    second = await service.generate_proposal(workflow, owner_id="second", generated_by="second")
    assert first.proposal_id != second.proposal_id
    assert service.get_proposal(first.proposal_id, owner_id="first") == first
    assert service.get_proposal(second.proposal_id, owner_id="second") == second
    with pytest.raises(ProposalNotFoundError):
        service.get_proposal(first.proposal_id, owner_id="second")


async def test_regeneration_rejects_an_unconfigured_planner_mode() -> None:
    service = _service()
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    with pytest.raises(ProposalStateError, match="configured planner"):
        await service.regenerate_proposal(
            proposal.proposal_id,
            owner_id="o",
            generated_by="t",
            config=GeneratePlanProposalConfig(mode=PlannerMode.LLM),
        )
    assert service.get_proposal(proposal.proposal_id, owner_id="o") == proposal


async def test_parallel_stages_propose_independent_tasks() -> None:
    service = _service()
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    assert validated.status.value == "VALIDATED", [e.code for e in validated.validation_errors]

    backend = next(t for t in validated.tasks if t.name.startswith("Backend"))
    frontend = next(t for t in validated.tasks if t.name.startswith("Frontend"))
    database = next(t for t in validated.tasks if t.name.startswith("Database"))
    unit = next(t for t in validated.tasks if t.name.startswith("Unit"))
    # Siblings in the same stage do not depend on each other...
    assert frontend.task_id not in backend.dependency_task_ids
    assert database.task_id not in backend.dependency_task_ids
    # ...and downstream joins wait for every sibling.
    assert {backend.task_id, frontend.task_id, database.task_id} <= set(unit.dependency_task_ids)


async def test_duplicate_task_ids_are_rejected() -> None:
    class DuplicatePlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            output = await super().generate(workflow, packages, limits)
            tasks = list(output.tasks)
            tasks[-1] = replace(tasks[0], task_id=tasks[0].task_id)
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=tasks)

    service = _service(DuplicatePlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert validated.status.value == "REVISION_REQUIRED"
    assert "DUPLICATE_TASK_ID" in codes


async def test_dependency_to_unknown_task_is_rejected() -> None:
    class BadDepPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            output = await super().generate(workflow, packages, limits)
            first = output.tasks[0]
            patched = replace(first, dependency_task_ids=["T99"])
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=[patched, *output.tasks[1:]])

    service = _service(BadDepPlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert "INVALID_DEPENDENCY" in codes


async def test_circular_dependency_is_rejected() -> None:
    class CyclePlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            req = str(STAGE_IDS["req"])
            drafts = [
                ProposedTaskDraft(
                    task_id="T1",
                    source_stage_id=req,
                    stage_type="REQUIREMENTS",
                    name="T1 name",
                    objective="objective one",
                    package_id="coding-agent",
                    package_version="0.1.0",
                    expected_outputs=["source_patch"],
                    inputs={"requirement": "value"},
                    dependency_task_ids=["T2"],
                ),
                ProposedTaskDraft(
                    task_id="T2",
                    source_stage_id=req,
                    stage_type="REQUIREMENTS",
                    name="T2 name",
                    objective="objective two",
                    package_id="coding-agent",
                    package_version="0.1.0",
                    expected_outputs=["source_patch"],
                    inputs={"requirement": "value"},
                    dependency_task_ids=["T1"],
                ),
            ]
            return PlannerOutput(tasks=drafts)

    service = _service(CyclePlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert "CIRCULAR_DEPENDENCY" in codes


async def test_unknown_package_assignment_is_rejected() -> None:
    class GhostAgentPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            output = await super().generate(workflow, packages, limits)
            first = output.tasks[0]
            patched = replace(first, package_id="ghost-agent", package_version="9.9.9")
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=[patched, *output.tasks[1:]])

    service = _service(GhostAgentPlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert "UNKNOWN_PACKAGE" in codes


async def test_missing_expected_outputs_is_rejected() -> None:
    class NoOutputPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            output = await super().generate(workflow, packages, limits)
            first = output.tasks[0]
            patched = replace(first, expected_outputs=[])
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=[patched, *output.tasks[1:]])

    service = _service(NoOutputPlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert "MISSING_EXPECTED_OUTPUTS" in codes


async def test_missing_required_package_input_is_rejected() -> None:
    class NoInputPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            output = await super().generate(workflow, packages, limits)
            first = output.tasks[0]
            patched = replace(first, inputs={})
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=[patched, *output.tasks[1:]])

    service = _service(NoInputPlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    codes = {issue.code for issue in validated.validation_errors}
    assert "MISSING_REQUIRED_INPUT" in codes


async def test_valid_proposal_approves_and_materializes_end_to_end() -> None:
    registry = _registry()
    plan_service = _plan_service()
    service = ProposalService(MockPlannerAgent(), registry, plan_service)
    owner = "owner-1"
    proposal = await service.generate_proposal(_workflow(), owner_id=owner, generated_by=owner)
    validated = service.validate_proposal(proposal.proposal_id, owner_id=owner)
    approved, plan = await service.approve_proposal(validated.proposal_id, owner_id=owner, approved_by=owner)
    assert approved.status.value == "APPROVED"
    assert str(approved.materialized_plan_id) == str(plan.execution_plan_id)
    # Plans with an approval gate are auto-approved; plain plans stay VALIDATED
    # and are accepted by the existing materializer directly.
    assert plan.status.value in {"VALIDATED", "APPROVED"}
    assert len(plan.tasks) == len(validated.tasks)
    assert all(task.plan_task_id for task in plan.tasks)

    run_service = AdlcRunService()
    materializer = ExecutionPlanMaterializer()
    run = await materializer.materialize(
        plan.execution_plan_id,
        idempotency_key="proposal-e2e",
        owner_id=owner,
        plan_service=plan_service,
        run_service=run_service,
        access_policy=create_default_package_access_policy(),
    )
    assert run.status.value in {"WAITING_APPROVAL", "RUNNING", "SUCCEEDED"}
    statuses = {task.status.value for task in run.tasks}
    assert "SUCCEEDED" in statuses


async def test_approve_requires_validation_first() -> None:
    service = _service()
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    with pytest.raises(ProposalStateError):
        await service.approve_proposal(proposal.proposal_id, owner_id="o", approved_by="o")


async def test_invalid_proposal_cannot_be_approved() -> None:
    class BadPlanner(MockPlannerAgent):
        async def generate(self, workflow, packages, limits):
            from langflow.adlc.planning.proposals.planner import PlannerOutput

            return PlannerOutput(tasks=[])

    service = _service(BadPlanner())
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    validated = service.validate_proposal(proposal.proposal_id, owner_id="o")
    assert validated.status.value == "REVISION_REQUIRED"
    assert validated.validation_errors[0].code == "EMPTY_PROPOSAL"


async def test_revision_flow_creates_superseding_proposal() -> None:
    service = _service()
    proposal = await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    successor = await service.regenerate_proposal(proposal.proposal_id, owner_id="o", generated_by="t")
    assert successor.proposal_id != proposal.proposal_id
    assert successor.proposal_version == proposal.proposal_version + 1
    assert str(successor.supersedes_proposal_id) == str(proposal.proposal_id)


async def test_task_limit_blocks_unbounded_decomposition() -> None:
    service = ProposalService(
        MockPlannerAgent(),
        _registry(),
        _plan_service(),
        limits=PlanProposalLimits(max_tasks=4),
    )
    with pytest.raises(Exception) as exc:  # noqa: PT011 - planner raises domain error
        await service.generate_proposal(_workflow(), owner_id="o", generated_by="t")
    assert "exceeds" in str(exc.value) or "decomposition" in str(exc.value).lower()


def _mock_response(content: object):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    return _response_payload(content)


def _response_payload(content: str):
    import httpx

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )
    return transport


async def test_llm_planner_parses_structured_output() -> None:
    import httpx

    payload = {
        "tasks": [
            {
                "task_id": "T1",
                "stage_ref": "S1",
                "name": "Requirements Analysis",
                "objective": "Analyze requirements.",
                "package_id": "coding-agent",
                "expected_outputs": ["source_patch"],
                "inputs": {"requirement": "value"},
                "dependency_task_ids": [],
            },
            {
                "task_id": "T2",
                "stage_ref": "S1",
                "name": "Design",
                "objective": "Design the system.",
                "package_id": "coding-agent",
                "expected_outputs": ["source_patch"],
                "inputs": {"requirement": "value"},
                "dependency_task_ids": ["T1"],
            },
        ],
        "assumptions": ["single stage"],
        "clarifications": [],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": _json_text(payload)}}]})
    )
    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=transport,
    )
    output = await planner.generate(
        _workflow(),
        list(create_default_package_registry().list_packages())[0:0]
        or [registered.definition for registered in create_default_package_registry().list_packages()],
        PlanProposalLimits(),
    )
    assert [task.task_id for task in output.tasks] == ["T1", "T2"]
    assert output.tasks[1].dependency_task_ids == ["T1"]


def _json_text(payload: dict) -> str:
    import json

    return json.dumps(payload)


async def test_llm_planner_timeout_maps_to_stable_error() -> None:
    import httpx

    def handler(request):
        raise httpx.ReadTimeout("boom", request=request)

    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handler),
    )
    packages = [registered.definition for registered in create_default_package_registry().list_packages()]
    from langflow.adlc.planning.proposals.errors import PlannerGenerationError

    with pytest.raises(PlannerGenerationError) as exc:
        await planner.generate(_workflow(), packages, PlanProposalLimits())
    assert exc.value.details.get("code") == PLANNER_TIMEOUT


async def test_llm_planner_marks_unavailable_endpoint() -> None:
    import httpx

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(handler),
    )
    packages = [registered.definition for registered in create_default_package_registry().list_packages()]
    from langflow.adlc.planning.proposals.errors import PlannerGenerationError

    with pytest.raises(PlannerGenerationError) as exc:
        await planner.generate(_workflow(), packages, PlanProposalLimits())
    assert exc.value.details.get("code") == PLANNER_UNAVAILABLE


async def test_llm_planner_rejects_malformed_output() -> None:
    import httpx

    planner = LLMPlannerAgent(
        base_url="http://planner.test/v1",
        api_key="k",
        model="m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})
        ),
    )
    packages = [registered.definition for registered in create_default_package_registry().list_packages()]
    from langflow.adlc.planning.proposals.errors import PlannerGenerationError

    with pytest.raises(PlannerGenerationError) as exc:
        await planner.generate(_workflow(), packages, PlanProposalLimits())
    assert exc.value.details.get("code") == PLANNER_MALFORMED_OUTPUT


async def test_owner_isolation_between_proposals() -> None:
    from langflow.adlc.planning.proposals.errors import ProposalNotFoundError

    service = _service()
    proposal = await service.generate_proposal(_workflow(), owner_id="alice", generated_by="a")
    with pytest.raises(ProposalNotFoundError):
        service.get_proposal(proposal.proposal_id, owner_id="bob")

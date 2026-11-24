"""H8C SQL/compiler boundaries. Fake transport, real Git fixture; no paid calls."""

# ruff: noqa: S101, PLR2004, F811, INP001, S603, S607, PT018 - isolated fixtures, fixed Git commands/assertions.
import asyncio
import json
import subprocess
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import select

from langflow.adlc import cycle_planning as p
from langflow.adlc import delivery as d
from langflow.adlc.blueprints.models import ExecutionPlan, PackageReference
from langflow.adlc.cycle_planning_client import ROUTE, PlanningRead
from langflow.adlc.packages.defaults import create_default_package_access_policy, create_default_package_registry
from langflow.adlc.planning.proposals.models import PlanProposalLimits
from langflow.adlc.task_loop_live_models import LiveLoopSpec
from langflow.api.v1 import adlc_cycle_planning as api
from langflow.api.v1 import adlc_delivery as delivery
from langflow.services.database.models.adlc_product_cycle import AdlcCycleOperation
from tests.unit.adlc.planning.test_plan_materialization import _plan_service
from tests.unit.adlc.test_delivery import accept_plan, db, read, service, work  # noqa: F401
from tests.unit.adlc.test_product_cycles import prepare, selected


@pytest.fixture
def repository(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()

    git("init")
    git("config", "user.email", "isolated-test@example.invalid")
    git("config", "user.name", "Isolated fixture")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "test_acceptance.py").write_text("import unittest\n", encoding="utf-8")
    git("add", "app.py", "test_acceptance.py")
    git("commit", "-m", "pinned fixture")
    monkeypatch.setenv("ADLC_TASK_LOOP_SOURCE_REPOSITORY", str(repo))
    return SimpleNamespace(path=repo, commit=git("rev-parse", "HEAD"), git=git)


def proof(row, cls=p.SpecCommand, **extra):
    return cls(
        expected_revision=row["revision"],
        workflow_digest=row["workflow_digest"],
        cycle_id=UUID(row["cycle"]["id"]),
        spec_digest=row["cycle"]["spec_digest"],
        command_id=uuid4(),
        **extra,
    )


async def frozen(work, repository):
    first = await accept_plan(work)
    async with work.sessions() as session:
        result = await delivery.prepare_cycle(work.delivery_id, prepare(first), session, work.actor)
    row = await selected(work, result["cycle_id"])
    async with work.sessions() as session:
        await api.freeze_spec(
            work.delivery_id,
            result["cycle_id"],
            proof(row, p.FreezeCommand, base_commit=repository.commit),
            session,
            work.actor,
            create_default_package_registry(),
        )
    return await selected(work, result["cycle_id"])


class FakeHarness:
    def __init__(self, work, *, uncertain=False, invalid=False):
        self.work = work
        self.uncertain = uncertain
        self.invalid = invalid
        self.creates = self.observes = 0
        self.remote = None

    async def readiness(self):
        return None

    async def aclose(self):
        return None

    async def create(self, command):
        self.creates += 1
        self.remote = command
        # Another SQL reader sees exact frozen input/intent before the remote call.
        async with self.work.sessions() as session:
            records = (await session.exec(select(AdlcCycleOperation).where(AdlcCycleOperation.kind == p.KIND))).all()
            matching = [
                record
                for record in records
                if record.input_snapshot["remote_command"]["generation_id"] == command["generation_id"]
            ]
            assert len(matching) == 1 and matching[0].status == "RESERVED"
            assert matching[0].input_snapshot["remote_command"] == command
        if self.uncertain:
            raise HTTPException(503, {"code": "ack lost"})
        return PlanningRead(
            generation_id=command["generation_id"],
            request_digest=command["request_digest"],
            route=ROUTE,
            state="RUNNING",
            released=False,
        )

    async def observe(self, command):
        self.observes += 1
        assert command == self.remote
        data = json.loads(command["prompt"].split("\nFROZEN_INPUT:\n")[1])
        stage = data["workflow"]["stages"][0]
        result = {
            "tasks": [
                {
                    "task_id": "release_gate",
                    "source_stage_id": stage["stage_id"],
                    "name": "Review the proposed increment",
                    "objective": "Inspect outputs before release",
                    "criterion_ids": [item["criterion_id"] for item in data["acceptance_criteria"]],
                }
            ]
        }
        if self.invalid:
            result["tasks"][0]["policy_overrides"] = {"approval": None}
        return PlanningRead(
            generation_id=command["generation_id"],
            request_digest=command["request_digest"],
            route=ROUTE,
            state="COMPLETED",
            released=True,
            proposal_text=json.dumps(result),
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30, "cost": None},
        )


async def generate(work, row, client, command=None):
    async with work.sessions() as session:
        return await api.generate_plan(
            work.delivery_id,
            UUID(row["cycle"]["id"]),
            command or proof(row),
            session,
            work.actor,
            create_default_package_registry(),
            create_default_package_access_policy(),
            work.plans,
            lambda: client,
        )


async def reconcile(work, row, operation, client):
    async with work.sessions() as session:
        return await api.reconcile_plan(
            work.delivery_id,
            UUID(row["cycle"]["id"]),
            UUID(operation["id"]),
            session,
            work.actor,
            create_default_package_registry(),
            work.plans,
            lambda: client,
        )


@pytest.mark.asyncio
async def test_exact_preview_acceptance_survives_restart_without_touching_first_cycle(work, repository):
    row = await frozen(work, repository)
    original = await read(work)
    assert row["workflow_approved"] and not row["plan_approved"]
    assert row["cycle"]["spec"]["planning_ready"]
    client = FakeHarness(work)
    command = proof(row)
    operation = await generate(work, row, client, command)
    work.plans = service()
    assert (await generate(work, row, client, command))["id"] == operation["id"]
    assert client.creates == 1
    completed = await reconcile(work, row, operation, client)
    assert completed["phase"] == "VALIDATED"
    assert completed["preview_plan"]["tasks"][0]["metadata"]["source_workflow_stage_id"]
    assert not completed["preview_plan"].get("approved_by")
    row = await selected(work, UUID(row["cycle"]["id"]))
    assert row["plan"] is None  # preview is not an accepted graph
    accepted_command = proof(row, p.AcceptCommand, generation_id=operation["id"], plan_digest=completed["plan_digest"])
    async with work.sessions() as session:
        await api.accept_graph(
            work.delivery_id,
            UUID(row["cycle"]["id"]),
            accepted_command,
            session,
            work.actor,
            work.plans,
            create_default_package_access_policy(),
        )
    accepted = await selected(work, UUID(row["cycle"]["id"]))
    assert accepted["plan_approved"]
    assert accepted["plan_digest"] == completed["plan_digest"]
    assert accepted["plan"]["execution_plan_id"] == completed["preview_plan"]["execution_plan_id"]
    assert accepted["cycle"]["plan_revisions"][0]["plan_digest"] == completed["plan_digest"]
    assert accepted["run"] is None and not accepted["cycle_capabilities"]["execute"]
    # H8C acceptance is not successor execution/baseline handoff authority.
    async with work.sessions() as session:
        with pytest.raises(HTTPException):
            await d.ensure_run_authority(
                session,
                (await delivery.source(session, work.delivery_id, work.actor))[1],
                work.actor,
                ExecutionPlan.model_validate(accepted["plan"]),
                materializing=True,
            )
        await api.accept_graph(
            work.delivery_id,
            UUID(row["cycle"]["id"]),
            accepted_command,
            session,
            work.actor,
            work.plans,
            create_default_package_access_policy(),
        )
    after = await read(work)
    for key in ("plan_id", "plan_digest", "plan_approved", "workflow_approved_by", "run", "dispatch_plan_id"):
        assert after[key] == original[key]
    assert client.creates == 1 and client.observes == 1


@pytest.mark.asyncio
async def test_unknown_ack_blocks_new_calls_and_only_observes_existing_generation(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work, uncertain=True)
    operation = await generate(work, row, client)
    assert operation["status"] == "UNCONFIRMED"
    current_row = await selected(work, UUID(row["cycle"]["id"]))
    assert client.observes == 0  # snapshot GET is SQL-only
    with pytest.raises(HTTPException) as error:
        await generate(work, current_row, client)
    assert error.value.detail["code"] == "CYCLE_GENERATION_UNCONFIRMED"
    completed = await reconcile(work, row, operation, client)
    assert completed["phase"] == "VALIDATED"
    assert client.creates == 1 and client.observes == 1
    await reconcile(work, row, operation, client)
    assert client.observes == 1  # completed SQL receipt is replayed


@pytest.mark.asyncio
async def test_untrusted_control_fields_cannot_be_accepted(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work, invalid=True)
    operation = await generate(work, row, client)
    result = await reconcile(work, row, operation, client)
    assert result["phase"] == "REVISION_REQUIRED"
    assert result["error_code"] == "CYCLE_PROPOSAL_INVALID"
    assert not result.get("preview_plan")
    assert (await selected(work, UUID(row["cycle"]["id"])))["plan"] is None


@pytest.mark.asyncio
async def test_concurrent_generations_cannot_spend_twice(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work)

    async def one():
        try:
            return await generate(work, row, client)
        except HTTPException as error:
            return error

    results = await asyncio.gather(one(), one())
    assert sum(isinstance(item, dict) for item in results) == 1
    assert client.creates == 1


@pytest.mark.asyncio
async def test_spec_edits_cannot_cross_pending_generation_or_inherit_approval(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work)
    operation = await generate(work, row, client)
    current_row = await selected(work, UUID(row["cycle"]["id"]))
    command = cycles_update(current_row)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await delivery.update_cycle_spec(work.delivery_id, UUID(row["cycle"]["id"]), command, session, work.actor)
    assert error.value.detail["code"] == "CYCLE_GENERATION_UNCONFIRMED"
    await reconcile(work, row, operation, client)
    current_row = await selected(work, UUID(row["cycle"]["id"]))
    async with work.sessions() as session:
        await delivery.update_cycle_spec(
            work.delivery_id, UUID(row["cycle"]["id"]), cycles_update(current_row), session, work.actor
        )
    edited = await selected(work, UUID(row["cycle"]["id"]))
    assert not edited["workflow_approved"] and not edited["cycle"]["spec"]["planning_ready"]
    assert edited["cycle"]["spec_digest"] != row["cycle"]["spec_digest"]
    assert edited["cycle"]["planning_operations"][0]["spec_digest"] == row["cycle"]["spec_digest"]


def cycles_update(row):
    from langflow.adlc.delivery_cycles import UpdateCycleCommand

    return proof(row, UpdateCycleCommand, goal="Different increment")


def branch_proposal(workflow):
    # 5 process stages, 7 concrete tasks. Two independent branches join before Verify.
    stage_ids = [str(stage.stage_id) for stage in workflow.stages]
    shapes = [
        ("scope", 0, []),
        ("backend_a", 1, ["scope"]),
        ("backend_b", 1, ["scope"]),
        ("ui", 2, ["scope"]),
        ("verify", 3, ["backend_a", "backend_b", "ui"]),
        ("gate", 4, ["verify"]),
    ]
    return {
        "tasks": [
            {
                "task_id": key,
                "source_stage_id": stage_ids[index],
                "name": key,
                "objective": f"Implement {key}",
                "dependency_task_ids": dependencies,
                "criterion_ids": [f"{stage_ids[index]}:completion"],
            }
            for key, index, dependencies in shapes
        ]
    }


def compile_proposal(raw, workflow):
    return p.validate_and_expand(
        raw,
        workflow,
        identity=uuid4(),
        version=1,
        owner="owner-1",
        limits=PlanProposalLimits(),
        criteria=p.criteria_for(workflow),
        registry=create_default_package_registry(),
    )


def test_detailed_parallel_join_preserves_source_policies_bindings_and_stage_lineage():
    plans, plan = _plan_service(uuid4())
    _, workflow = plans.get_materialization_snapshot(plan.execution_plan_id, owner_id="owner-1")
    proposal, expanded = compile_proposal(branch_proposal(workflow), workflow)
    assert not proposal.validation_errors and len(expanded.stages) == 6
    actual = service().compile_snapshot(expanded, owner_id="owner-1", generated_by="test", plan_version=1)
    assert actual.validation_status == "VALID"
    verify = next(task for task in actual.tasks if task.name == "verify")
    assert len(verify.dependency_task_ids) == 3
    for task in proposal.tasks:
        source = next(stage for stage in workflow.stages if stage.stage_id == task.source_stage_id)
        target = next(stage for stage in expanded.stages if stage.metadata["proposal_task_id"] == task.task_id)
        assert target.policy_overrides == source.policy_overrides
        assert target.configuration_overrides == source.configuration_overrides


@pytest.mark.parametrize("violation", ["join", "coverage", "criterion", "gate", "cycle", "package"])
def test_unsafe_proposals_fail_closed(violation):
    plans, plan = _plan_service(uuid4())
    _, workflow = plans.get_materialization_snapshot(plan.execution_plan_id, owner_id="owner-1")
    raw = branch_proposal(workflow)
    if violation == "join":
        raw["tasks"][-2]["dependency_task_ids"].remove("backend_b")
    elif violation == "coverage":
        raw["tasks"] = [task for task in raw["tasks"] if task["task_id"] != "ui"]
    elif violation == "criterion":
        raw["tasks"][0]["criterion_ids"] = ["made_up"]
    elif violation == "gate":
        raw["tasks"].append({**raw["tasks"][-1], "task_id": "gate2"})
    elif violation == "cycle":
        raw["tasks"][0]["dependency_task_ids"] = ["gate"]
    else:
        raw["tasks"][0]["package_id"] = "root-shell"
        with pytest.raises(ValidationError):
            compile_proposal(raw, workflow)
        return
    proposal, expanded = compile_proposal(raw, workflow)
    assert proposal.validation_errors and expanded is None


@pytest.mark.parametrize("base", ["main", "--help", "a" * 39, "a" * 40 + "^{commit}"])
def test_freeze_only_accepts_immutable_commit_ids(base):
    with pytest.raises(ValidationError):
        p.FreezeCommand(
            expected_revision=1,
            workflow_digest="sha256:" + "a" * 64,
            spec_digest="sha256:" + "b" * 64,
            command_id=uuid4(),
            base_commit=base,
        )


@pytest.mark.asyncio
async def test_locked_loop_scope_uses_committed_files_and_cannot_be_decomposed(repository):
    plans, plan = _plan_service(uuid4())
    _, workflow = plans.get_materialization_snapshot(plan.execution_plan_id, owner_id="owner-1")
    loop = LiveLoopSpec(
        spec_id=uuid4(),
        specification="Old task",
        base_commit=repository.commit,
        writable_paths=("app.py",),
        acceptance_criteria=({"criterion_id": "value", "description": "Value is correct", "check_refs": ["unit"]},),
        verification_commands=({"check_id": "unit", "test_path": "test_acceptance.py"},),
    )
    stage = workflow.stages[0].model_copy(
        update={
            "package_ref": PackageReference(package_id="coding-agent", version="0.3.0"),
            "configuration_overrides": {
                "task_loop_enabled": True,
                "loop_runtime": "HARNESS",
                "submission_mode": "MANUAL",
            },
            "inputs": {"task_loop_spec": loop.model_dump(mode="json")},
        }
    )
    workflow = workflow.model_copy(update={"stages": [stage], "edges": []})
    (repository.path / "app.py").write_text("UNCOMMITTED = True\n", encoding="utf-8")
    context = await p.repository_context(workflow, repository.commit)
    assert context["files"]["app.py"]["content"] == "VALUE = 1\n"
    assert context["files"]["test_acceptance.py"]["digest"]
    cycle = SimpleNamespace(id=uuid4(), goal="A new fixed increment")
    scoped = p.scoped_workflow(workflow, cycle, context)
    actual = LiveLoopSpec.model_validate(scoped.stages[0].inputs["task_loop_spec"])
    assert actual.specification == cycle.goal
    assert actual.spec_id != loop.spec_id
    assert actual.writable_paths == loop.writable_paths
    assert actual.acceptance_criteria == loop.acceptance_criteria
    assert actual.verification_commands == loop.verification_commands
    raw = {
        "tasks": [
            {"task_id": "part1", "source_stage_id": str(stage.stage_id), "name": "Part one", "objective": "Part one"},
            {"task_id": "part2", "source_stage_id": str(stage.stage_id), "name": "Part two", "objective": "Part two"},
        ]
    }
    proposal, expanded = compile_proposal(raw, scoped)
    assert expanded is None
    assert "CODING_AGENT_LOOP_REQUIRES_ONE_TASK" in {issue.code for issue in proposal.validation_errors}


@pytest.mark.asyncio
async def test_terminal_remote_error_without_release_cannot_unblock_new_generation(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work)
    operation = await generate(work, row, client)

    async def unreleased(command):
        return PlanningRead(
            generation_id=command["generation_id"],
            request_digest=command["request_digest"],
            route=ROUTE,
            state="FAILED",
            released=False,
            error_code="HARNESS_PLANNER_TURN_FAILED",
        )

    client.observe = unreleased
    result = await reconcile(work, row, operation, client)
    assert result["status"] == "UNCONFIRMED"
    latest = await selected(work, UUID(row["cycle"]["id"]))
    with pytest.raises(HTTPException) as error:
        await generate(work, latest, client)
    assert error.value.detail["code"] == "CYCLE_GENERATION_UNCONFIRMED"
    assert client.creates == 1


@pytest.mark.asyncio
async def test_reproposal_receives_previous_keys_and_diff_ignores_new_execution_ids(work, repository):
    row = await frozen(work, repository)
    client = FakeHarness(work)
    first = await generate(work, row, client)
    one = await reconcile(work, row, first, client)
    row = await selected(work, UUID(row["cycle"]["id"]))
    second = await generate(work, row, client)
    sent = json.loads(client.remote["prompt"].split("\nFROZEN_INPUT:\n")[1])
    assert sent["previous_proposal"]["proposal_id"] == one["proposal"]["proposal_id"]
    two = await reconcile(work, row, second, client)
    assert two["preview_plan"]["execution_plan_id"] != one["preview_plan"]["execution_plan_id"]
    assert two["diff"]["added"] == []
    assert two["diff"]["removed"] == []
    assert two["diff"]["changed"] == []
    assert len(two["diff"]["unchanged"]) == 1
    assert client.creates == 2

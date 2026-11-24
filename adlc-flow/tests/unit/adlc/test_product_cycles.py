"""Durable cycle boundaries with real SQL/compiler/control gates, no AI or Git."""

# ruff: noqa: S101, PLR2004, INP001, F811 - isolated assertions and imported pytest fixtures.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from sqlmodel import select
from starlette.requests import Request

from langflow.adlc import delivery as d
from langflow.adlc import delivery_cycles as c
from langflow.adlc.models import PlanApprovalCommand, RegenerateExecutionPlanRequest
from langflow.adlc.packages.defaults import create_default_package_access_policy
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.api.v1 import adlc_delivery as api
from langflow.services.database.models.adlc_product_cycle import (
    AdlcCycleFeedback,
    AdlcCycleHead,
    AdlcCycleOperation,
    AdlcCycleSpec,
    AdlcProductCycle,
)
from langflow.services.database.models.flow.model import Flow
from tests.unit.adlc.planning.test_plan_materialization import _graph, _stage
from tests.unit.adlc.test_delivery import (  # noqa: F401 - pytest fixtures.
    accept_plan,
    compile_plan,
    db,
    proof,
    read,
    service,
    work,
)


def prepare(row, goal="Add export as a later increment", **changes):
    return c.PrepareCycleCommand(
        expected_revision=row["revision"],
        workflow_digest=row["workflow_digest"],
        predecessor_id=UUID(row["cycle"]["id"]),
        command_id=uuid4(),
        goal=goal,
        **changes,
    )


async def selected(work, identity):
    async with work.sessions() as session:
        return await api.get_delivery(work.delivery_id, session, work.actor, Response(), work.runs, identity)


@pytest.mark.asyncio
async def test_successor_draft_preserves_accepted_plan_and_existing_run(work):
    accepted = await accept_plan(work)
    async with work.sessions() as session:
        await api.start_delivery(
            work.delivery_id,
            proof(accepted, plan=True),
            session,
            work.actor,
            Request({"type": "http"}),
            work.plans,
            work.runs,
            ExecutionPlanMaterializer(),
            create_default_package_access_policy(),
        )
    original = await read(work)
    command = prepare(original)
    async with work.sessions() as session:
        result = await api.prepare_cycle(work.delivery_id, command, session, work.actor)
    after = await read(work)
    assert after["plan_id"] == original["plan_id"]
    assert after["run"]["id"] == original["run"]["id"]
    assert after["plan_approved"]
    assert after["plan_digest"] == original["plan_digest"]
    assert after["workflow_approved_by"] == original["workflow_approved_by"]
    assert after["run"]["status"] == "WAITING_APPROVAL"
    draft = await selected(work, result["cycle_id"])
    assert draft["cycle"]["number"] == 2
    assert draft["cycle"]["predecessor_id"] == original["cycle"]["id"]
    assert draft["workflow_digest"] == original["workflow_digest"]
    assert draft["cycle"]["spec"]["baseline"] is None
    assert draft["plan"] is None
    assert draft["run"] is None
    assert not draft["plan_approved"]
    assert not draft["workflow_approved"]
    assert draft["cycle"]["plan_revisions"] == []
    assert not draft["cycle_capabilities"]["execute"]
    assert draft["requirement"] == command.goal


@pytest.mark.asyncio
async def test_prepare_is_idempotent_across_restart_and_rejects_payload_reuse(work):
    row = await compile_plan(work)
    command = prepare(row)
    async with work.sessions() as session:
        first = await api.prepare_cycle(work.delivery_id, command, session, work.actor)
    work.plans = service()  # no process-local cycle cache participates.
    async with work.sessions() as session:
        again = await api.prepare_cycle(work.delivery_id, command, session, work.actor)
        assert str(first["cycle_id"]) == str(again["cycle_id"])
        assert len((await session.exec(select(AdlcProductCycle))).all()) == 2
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.prepare_cycle(
                work.delivery_id, command.model_copy(update={"goal": "A different scope"}), session, work.actor
            )
    assert error.value.detail["code"] == "DELIVERY_COMMAND_CONFLICT"


@pytest.mark.asyncio
async def test_two_workers_cannot_create_two_successors_for_one_revision(work):
    row = await compile_plan(work)
    commands = [prepare(row), prepare(row)]

    async def apply(command):
        try:
            async with work.sessions() as session:
                return await api.prepare_cycle(work.delivery_id, command, session, work.actor)
        except HTTPException as error:
            return error

    results = await asyncio.gather(*(apply(command) for command in commands))
    assert sum(isinstance(result, dict) for result in results) == 1
    failures = [result for result in results if isinstance(result, HTTPException)]
    assert len(failures) == 1
    assert failures[0].status_code == 409
    async with work.sessions() as session:
        assert len((await session.exec(select(AdlcProductCycle))).all()) == 2
        assert (await session.get(AdlcCycleHead, work.delivery_id)).next_number == 3


@pytest.mark.asyncio
async def test_draft_spec_revisions_are_append_only_and_do_not_edit_cycle_one(work):
    row = await accept_plan(work)
    async with work.sessions() as session:
        result = await api.prepare_cycle(work.delivery_id, prepare(row), session, work.actor)
    draft = await selected(work, result["cycle_id"])
    command = c.UpdateCycleCommand(
        expected_revision=draft["revision"],
        workflow_digest=draft["workflow_digest"],
        command_id=uuid4(),
        cycle_id=result["cycle_id"],
        spec_digest=draft["cycle"]["spec_digest"],
        goal="Export CSV only",
    )
    for _ in range(2):
        async with work.sessions() as session:
            await api.update_cycle_spec(work.delivery_id, result["cycle_id"], command, session, work.actor)
    updated = await selected(work, result["cycle_id"])
    assert updated["cycle"]["spec_revision"] == 2
    assert updated["cycle"]["goal"] == "Export CSV only"
    assert (await read(work))["requirement"] == row["requirement"]
    assert (await read(work))["plan_digest"] == row["plan_digest"]
    async with work.sessions() as session:
        specs = (
            await session.exec(
                select(AdlcCycleSpec)
                .where(AdlcCycleSpec.cycle_id == result["cycle_id"])
                .order_by(AdlcCycleSpec.revision)
            )
        ).all()
        assert [spec.revision for spec in specs] == [1, 2]
        assert specs[0].digest == draft["cycle"]["spec_digest"]
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.update_cycle_spec(
                work.delivery_id,
                result["cycle_id"],
                command.model_copy(update={"command_id": uuid4()}),
                session,
                work.actor,
            )
    assert error.value.detail["code"] == "DELIVERY_CYCLE_SPEC_CHANGED"


@pytest.mark.asyncio
async def test_draft_cannot_borrow_first_cycle_compile_approval_or_dispatch(work):
    row = await accept_plan(work)
    async with work.sessions() as session:
        result = await api.prepare_cycle(work.delivery_id, prepare(row), session, work.actor)
    draft = await selected(work, result["cycle_id"])
    command = d.PlanCommand(
        expected_revision=draft["revision"],
        workflow_digest=draft["workflow_digest"],
        cycle_id=result["cycle_id"],
        plan_digest=row["plan_digest"],
    )
    for action in ("compile", "approve", "start"):
        with pytest.raises(HTTPException) as error:  # noqa: PT012 - probe three independently guarded routes.
            async with work.sessions() as session:
                if action == "compile":
                    await api.compile_delivery(work.delivery_id, command, session, work.actor, work.plans)
                elif action == "approve":
                    await api.approve_plan(work.delivery_id, command, session, work.actor, work.plans)
                else:
                    await api.start_delivery(
                        work.delivery_id,
                        command,
                        session,
                        work.actor,
                        Request({"type": "http"}),
                        work.plans,
                        work.runs,
                        ExecutionPlanMaterializer(),
                        create_default_package_access_policy(),
                    )
        assert error.value.detail["code"] == "DELIVERY_CYCLE_PLANNING_NOT_READY"
    assert not (await read(work))["dispatch_plan_id"]


@pytest.mark.asyncio
async def test_cycle_notes_are_attributed_deduplicated_and_separate(work):
    row = await compile_plan(work)
    async with work.sessions() as session:
        result = await api.prepare_cycle(work.delivery_id, prepare(row), session, work.actor)
    draft = await selected(work, result["cycle_id"])
    command = d.NoteCommand(
        expected_revision=draft["revision"],
        command_id=uuid4(),
        cycle_id=result["cycle_id"],
        text="Discuss CSV format",
        kind="QUESTION",
    )
    for _ in range(2):
        async with work.sessions() as session:
            await api.add_note(work.delivery_id, command, session, work.actor)
    assert (await read(work))["notes"] == []
    saved = await selected(work, result["cycle_id"])
    assert len(saved["notes"]) == 1
    assert saved["notes"][0]["actor_id"] == str(work.actor.id)
    assert saved["cycle"]["spec"]["selected_feedback_ids"] == []
    async with work.sessions() as session:
        assert len((await session.exec(select(AdlcCycleFeedback))).all()) == 1


@pytest.mark.asyncio
async def test_sql_versions_and_command_results_survive_empty_compiler_caches(work):
    first = await compile_plan(work)
    command = d.DeliveryCommand(**{**proof(first).model_dump(), "command_id": uuid4()})
    work.plans = service()
    async with work.sessions() as session:
        second = await api.compile_delivery(work.delivery_id, command, session, work.actor, work.plans)
    assert second["plan"]["plan_version"] == first["plan"]["plan_version"] + 1
    work.plans = service()
    async with work.sessions() as session:
        repeat = await api.compile_delivery(work.delivery_id, command, session, work.actor, work.plans)
    assert repeat["plan"]["execution_plan_id"] == second["plan"]["execution_plan_id"]
    after = await read(work)
    assert len(after["cycle"]["plan_revisions"]) == 2
    assert not after["plan_approved"]
    assert after["plan_id"] != first["plan_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route",
    [
        "create",
        "regenerate",
        "approve",
        "proposal-approve",
        "proposal-generate",
        "proposal-regenerate",
        "prepare-subtasks",
    ],
)
async def test_advanced_mutations_cannot_supersede_workspace_plan(work, route):
    row = await accept_plan(work)
    before = work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)).model_dump(mode="json")
    pending = SimpleNamespace(
        get_proposal=lambda *_args, **_kwargs: SimpleNamespace(workflow_definition_id=work.identity),
        approve_proposal=AsyncMock(),
    )
    with pytest.raises(HTTPException) as error:  # noqa: PT012 - each advanced boundary must reject before mutation.
        async with work.sessions() as session:
            if route == "create":
                await api.runtime.create_execution_plan(work.identity, work.actor, session, work.plans)
            elif route == "regenerate":
                await api.runtime.regenerate_execution_plan(
                    UUID(row["plan_id"]),
                    RegenerateExecutionPlanRequest(idempotency_key="blocked"),
                    work.actor,
                    work.plans,
                    session,
                )
            elif route == "approve":
                await api.runtime.approve_execution_plan(
                    UUID(row["plan_id"]), work.actor, work.plans, PlanApprovalCommand(), session
                )
            elif route == "proposal-approve":
                await api.runtime.approve_plan_proposal(uuid4(), work.actor, pending, work.plans, None, session)
            elif route == "proposal-generate":
                await api.runtime.generate_plan_proposal(work.identity, work.actor, session, pending)
            elif route == "proposal-regenerate":
                await api.runtime.regenerate_plan_proposal(uuid4(), work.actor, pending, None, session)
            else:
                await api.runtime.prepare_execution_plan_subtasks(
                    UUID(row["plan_id"]), work.actor, work.plans, work.runs, session
                )
    assert error.value.detail["code"] == "DELIVERY_USE_WORKSPACE"
    assert work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)).model_dump(mode="json") == before
    assert (await read(work))["plan_digest"] == row["plan_digest"]
    pending.approve_proposal.assert_not_awaited()


@pytest.mark.asyncio
async def test_cycle_isolation_owner_and_foreign_selection_fail_closed(work):
    row = await compile_plan(work)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.prepare_cycle(work.delivery_id, prepare(row), session, work.people["other"])
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await selected(work, uuid4())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_stale_prepare_cannot_move_head_or_modify_active_binding(work):
    row = await compile_plan(work)
    async with work.sessions() as session:
        await api.add_note(
            work.delivery_id,
            d.NoteCommand(expected_revision=row["revision"], command_id=uuid4(), text="A new note", kind="NOTE"),
            session,
            work.actor,
        )
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.prepare_cycle(work.delivery_id, prepare(row), session, work.actor)
    assert error.value.detail["code"] == "DELIVERY_REVISION_CONFLICT"
    async with work.sessions() as session:
        head = await session.get(AdlcCycleHead, work.delivery_id)
        assert head.latest_cycle_id == c.initial_cycle_id(work.delivery_id)
        assert head.next_number == 2
        assert len((await session.exec(select(AdlcProductCycle))).all()) == 1


@pytest.mark.asyncio
async def test_two_workers_reserve_only_one_execution_slot_and_dispatch(work):
    row = await accept_plan(work)

    async def start():
        try:
            async with work.sessions() as session:
                return await api.start_delivery(
                    work.delivery_id,
                    proof(row, plan=True),
                    session,
                    work.actor,
                    Request({"type": "http"}),
                    service(),
                    work.runs,
                    ExecutionPlanMaterializer(),
                    create_default_package_access_policy(),
                )
        except HTTPException as error:
            return error

    results = await asyncio.gather(start(), start())
    assert any(isinstance(result, dict) for result in results)
    assert all(isinstance(result, dict) or result.status_code == 409 for result in results)
    runs = await work.runs.list_runs(owner_id=str(work.actor.id))
    assert runs.total == 1
    saved = await read(work)
    async with work.sessions() as session:
        head = await session.get(AdlcCycleHead, work.delivery_id)
        assert head.execution_cycle_id == c.initial_cycle_id(work.delivery_id)
        operations = (await session.exec(select(AdlcCycleOperation).where(AdlcCycleOperation.kind == "DISPATCH"))).all()
        assert len(operations) == 1
        assert operations[0].status == "SUCCEEDED"
        assert operations[0].result["run_id"] == saved["run"]["id"]


@pytest.mark.asyncio
async def test_nonworkspace_plan_read_preserves_existing_supersession_lifecycle(work):
    identity = uuid4()
    graph = _graph(identity, include_approval=False)
    graph["nodes"] = [_stage(1, name="Standalone approval", package_id="approval")]
    graph["edges"] = []
    async with work.sessions() as session:
        session.add(Flow(id=identity, name="Standalone workflow", user_id=work.actor.id, data=graph))
        await session.commit()
        first = await api.runtime.create_execution_plan(identity, work.actor, session, work.plans)
        await session.commit()
        successor = await api.runtime.regenerate_execution_plan(
            first.execution_plan_id,
            RegenerateExecutionPlanRequest(idempotency_key="standalone-successor"),
            work.actor,
            work.plans,
            session,
        )
        await session.commit()
        previous = await api.runtime.get_execution_plan(first.execution_plan_id, work.actor, work.plans, session)
    assert successor.execution_plan_id != first.execution_plan_id
    assert previous.status == "SUPERSEDED"


@pytest.mark.asyncio
async def test_workspace_materialization_and_read_cannot_trigger_legacy_paid_decomposition(work):
    accepted = await accept_plan(work)
    work.runs.prepare_plan_subtasks = AsyncMock()
    work.runs.get_task_subtasks = AsyncMock()
    async with work.sessions() as session:
        result = await api.start_delivery(
            work.delivery_id,
            proof(accepted, plan=True),
            session,
            work.actor,
            Request({"type": "http"}),
            work.plans,
            work.runs,
            ExecutionPlanMaterializer(),
            create_default_package_access_policy(),
        )
    work.runs.prepare_plan_subtasks.assert_not_called()
    run = await work.runs.get_run(result["run_id"], owner_id=str(work.actor.id))
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.runtime.get_adlc_task_subtasks(run.id, run.tasks[0].id, work.actor, work.runs, session)
    assert error.value.detail["code"] == "DELIVERY_USE_WORKSPACE"
    work.runs.get_task_subtasks.assert_not_awaited()

"""Product journey against SQLite and the real compiler/coordinator, without AI calls."""

# ruff: noqa: S101, PLR2004, INP001 - isolated pytest assertions.

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlmodel import SQLModel, select
from starlette.requests import Request

from langflow.adlc import delivery as d
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.packages.defaults import create_default_package_access_policy, create_default_package_resolver
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService
from langflow.api.v1 import adlc_delivery as api
from langflow.services.database.models.adlc_delivery import AdlcDelivery
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_product_cycle import (
    AdlcCycleFeedback,
    AdlcCycleHead,
    AdlcCycleOperation,
    AdlcCyclePlanRevision,
    AdlcCycleSpec,
    AdlcProductCycle,
)
from langflow.services.database.models.auth import AuthzAuditLog
from langflow.services.database.models.flow.model import Flow
from tests.unit.adlc.planning.test_plan_materialization import _graph, _stage
from tests.unit.services.authorization.test_team_access import db  # noqa: F401 - isolated SQL fixture.


def service():
    return ExecutionPlanService(BlueprintCompiler(create_default_package_resolver()))


@pytest_asyncio.fixture
async def work(db):  # noqa: F811 - pytest resolves imported fixture.
    async with db.sessions.kw["bind"].begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[
                    AdlcDelivery.__table__,
                    AdlcExecutionPlan.__table__,
                    AdlcProductCycle.__table__,
                    AdlcCycleHead.__table__,
                    AdlcCycleSpec.__table__,
                    AdlcCyclePlanRevision.__table__,
                    AdlcCycleFeedback.__table__,
                    AdlcCycleOperation.__table__,
                ],
            )
        )
    actor = db.people["developer"]
    identity = uuid4()
    graph = _graph(identity, include_approval=False)
    # A real control gate lets the coordinator be exercised without a model or simulator.
    graph["nodes"] = [_stage(1, name="Human release decision", package_id="approval")]
    graph["edges"] = []
    async with db.sessions() as session:
        flow = Flow(id=identity, name="Delivery integration", user_id=actor.id, data=graph)
        session.add(flow)
        await session.commit()
        row = await api.create_delivery(
            d.CreateDelivery(flow_id=identity, title=flow.name, requirement="Keep release human-approved."),
            session,
            actor,
        )
    db.actor, db.identity, db.delivery_id = actor, identity, UUID(row["id"])
    db.plans, db.runs = service(), AdlcRunService(MockExecutor())
    return db


async def read(work, actor=None):
    async with work.sessions() as session:
        return await api.get_delivery(work.delivery_id, session, actor or work.actor, Response(), work.runs)


def proof(row, *, plan=False):
    value = {"expected_revision": row["revision"], "workflow_digest": row["workflow_digest"]}
    return d.PlanCommand(**value, plan_digest=row["plan_digest"]) if plan else d.DeliveryCommand(**value)


async def compile_plan(work):
    row = await read(work)
    async with work.sessions() as session:
        await api.approve_workflow(work.delivery_id, proof(row), session, work.actor)
    row = await read(work)
    async with work.sessions() as session:
        await api.compile_delivery(work.delivery_id, proof(row), session, work.actor, work.plans)
    return await read(work)


async def accept_plan(work):
    row = await compile_plan(work)
    async with work.sessions() as session:
        await api.approve_plan(work.delivery_id, proof(row, plan=True), session, work.actor, work.plans)
    return await read(work)


@pytest.mark.asyncio
async def test_two_real_reviews_persist_then_coordinator_stops_at_real_human_gate(work):
    initial = await read(work)
    assert not initial["workflow_approved"]
    assert not initial["plan_approved"]
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.compile_delivery(work.delivery_id, proof(initial), session, work.actor, work.plans)
    assert error.value.detail["code"] == "DELIVERY_WORKFLOW_APPROVAL_REQUIRED"
    row = await compile_plan(work)
    assert row["plan"]["approval_required"]
    assert not row["plan_approved"]
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await d.ensure_run_authority(
                session,
                await session.get(Flow, work.identity),
                work.actor,
                work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)),
            )
    assert error.value.detail["code"] == "DELIVERY_PLAN_APPROVAL_REQUIRED"
    # Drop the process-local service: the SQL archive must restore the exact reviewed plan.
    work.plans = service()
    async with work.sessions() as session:
        await api.approve_plan(work.delivery_id, proof(row, plan=True), session, work.actor, work.plans)
    accepted = await read(work)
    assert accepted["plan_approved"]
    assert accepted["plan_digest"] == row["plan_digest"]
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
    stored = await read(work)
    assert str(result["run_id"]) == stored["run"]["id"]
    assert stored["run"]["status"] == "WAITING_APPROVAL"
    assert stored["run"]["tasks"][0]["status"] == "WAITING_APPROVAL"
    assert all(not task.get("result") for task in stored["run"]["tasks"])
    async with work.sessions() as session:
        actions = (await session.exec(select(AuthzAuditLog).where(AuthzAuditLog.resource_id == work.identity))).all()
    assert {item.action for item in actions} >= {
        "delivery:created",
        "delivery:workflow_approved",
        "delivery:plan_compiled",
        "delivery:plan_approved",
        "delivery:run_linked",
    }
    assert all(item.user_id == work.actor.id for item in actions)
    # A lost HTTP acknowledgement can re-link, but cannot dispatch a second run.
    async with work.sessions() as session:
        delivery = await session.get(AdlcDelivery, work.delivery_id)
        delivery.run_id = None
        session.add(delivery)
        await session.commit()
    missing = await read(work)
    async with work.sessions() as session:
        reconciled = await api.reconcile_delivery(
            work.delivery_id, proof(missing, plan=True), session, work.actor, work.runs
        )
    assert reconciled["run_id"] == result["run_id"]


@pytest.mark.asyncio
async def test_stale_review_cannot_overwrite_a_newer_revision(work):
    stale = await read(work)
    async with work.sessions() as session:
        await api.approve_workflow(work.delivery_id, proof(stale), session, work.actor)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.approve_workflow(work.delivery_id, proof(stale), session, work.actor)
    assert error.value.detail["code"] == "DELIVERY_REVISION_CONFLICT"


@pytest.mark.asyncio
async def test_semantic_graph_change_revokes_both_reviews_and_legacy_start(work):
    row = await accept_plan(work)
    async with work.sessions() as session:
        flow = await session.get(Flow, work.identity)
        graph = deepcopy(flow.data)
        graph["nodes"][0]["data"]["adlc"]["objective"] = "Different release scope"
        flow.data = graph
        session.add(flow)
        await session.commit()
    changed = await read(work)
    assert not changed["workflow_approved"]
    assert not changed["plan_approved"]
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await d.ensure_run_authority(
                session,
                await session.get(Flow, work.identity),
                work.actor,
                work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)),
            )
    assert error.value.detail["code"] == "DELIVERY_WORKFLOW_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_canvas_position_does_not_revoke_review_but_node_inputs_do(work):
    row = await read(work)
    graph = deepcopy(row["workflow"])
    graph["adlc"]["version"] += 1
    graph["nodes"][0]["position"] = {"x": 900, "y": 700}
    assert d.graph_digest(graph) == row["workflow_digest"]
    graph["nodes"][0]["data"]["adlc"]["inputs"]["approval_context"] = "changed"
    assert d.graph_digest(graph) != row["workflow_digest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("person", ["other", "ba", "tester"])
async def test_foreign_delivery_hidden_even_for_legacy_superuser(work, person):
    with pytest.raises(HTTPException) as error:
        await read(work, work.people[person])
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_notes_are_idempotent_stamped_and_do_not_modify_execution_scope(work):
    row = await read(work)
    command = d.NoteCommand(
        expected_revision=row["revision"],
        command_id=uuid4(),
        kind="CHANGE_REQUEST",
        text="Add export in the next iteration.",
    )
    for _ in range(2):
        async with work.sessions() as session:
            await api.add_note(work.delivery_id, command, session, work.actor)
    updated = await read(work)
    assert updated["workflow_digest"] == row["workflow_digest"]
    assert updated["revision"] == row["revision"] + 1
    assert len(updated["notes"]) == 1
    assert updated["notes"][0]["actor_id"] == str(work.actor.id)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.add_note(work.delivery_id, command.model_copy(update={"text": "tampered"}), session, work.actor)
    assert error.value.detail["code"] == "DELIVERY_COMMAND_CONFLICT"


@pytest.mark.asyncio
async def test_legacy_start_without_reviewed_plan_is_denied(work):
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await d.ensure_run_authority(session, await session.get(Flow, work.identity), work.actor, None)
    assert error.value.detail["code"] == "DELIVERY_WORKFLOW_APPROVAL_REQUIRED"


@pytest.mark.asyncio
async def test_legacy_run_key_cannot_create_a_second_agent_after_human_approval(work):
    row = await accept_plan(work)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await d.ensure_run_authority(
                session,
                await session.get(Flow, work.identity),
                work.actor,
                work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)),
                materializing=True,
                dispatch_key="arbitrary-legacy-key",
            )
    assert error.value.detail["code"] == "DELIVERY_USE_WORKSPACE"


@pytest.mark.asyncio
async def test_mock_success_is_not_a_production_delivery(work):
    async with work.sessions() as session:
        flow = await session.get(Flow, work.identity)
        flow.data = _graph(flow.id, include_approval=False)
        session.add(flow)
        await session.commit()
    row = await accept_plan(work)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await d.ensure_run_authority(
                session,
                await session.get(Flow, work.identity),
                work.actor,
                work.plans.get_plan(UUID(row["plan_id"]), owner_id=str(work.actor.id)),
            )
    assert error.value.detail["code"] == "DELIVERY_MOCK_EXECUTION_NOT_ALLOWED"


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"approved_by": str(uuid4())}, {"expected_revision": True}])
def test_commands_never_accept_browser_asserted_authority(extra):
    with pytest.raises(ValidationError):
        d.DeliveryCommand(**({"expected_revision": 1, "workflow_digest": "sha256:" + "a" * 64} | extra))


@pytest.mark.asyncio
async def test_unconfirmed_dispatch_is_frozen_not_automatically_retried(work, monkeypatch):
    row = await accept_plan(work)
    from unittest.mock import AsyncMock

    dispatch = AsyncMock(side_effect=RuntimeError("Unknown acknowledgement"))
    monkeypatch.setattr(api.runtime, "create_run_from_execution_plan", dispatch)
    with pytest.raises(RuntimeError, match="Unknown acknowledgement"):
        async with work.sessions() as session:
            await api.start_delivery(
                work.delivery_id,
                proof(row, plan=True),
                session,
                work.actor,
                Request({"type": "http"}),
                work.plans,
                work.runs,
                ExecutionPlanMaterializer(),
                create_default_package_access_policy(),
            )
    frozen = await read(work)
    assert frozen["dispatch_plan_id"] == frozen["plan_id"]
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.start_delivery(
                work.delivery_id,
                proof(frozen, plan=True),
                session,
                work.actor,
                Request({"type": "http"}),
                work.plans,
                work.runs,
                ExecutionPlanMaterializer(),
                create_default_package_access_policy(),
            )
    assert error.value.detail["code"] == "DELIVERY_RUN_START_UNCONFIRMED"
    assert dispatch.await_count == 1
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.compile_delivery(work.delivery_id, proof(frozen), session, work.actor, work.plans)
    assert error.value.detail["code"] == "DELIVERY_RUN_ALREADY_STARTED"


@pytest.mark.asyncio
async def test_team_owner_cannot_use_private_adapter_to_bypass_collaboration(work):
    async with work.sessions() as session:
        flow = Flow(name="Managed source", user_id=work.people["operator"].id, folder_id=work.project, data={})
        session.add(flow)
        await session.commit()
        with pytest.raises(HTTPException):
            await api.create_delivery(
                d.CreateDelivery(flow_id=flow.id, title="Not private", requirement="Never borrow the owner identity."),
                session,
                work.people["operator"],
            )
        assert not (await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == flow.id))).first()


@pytest.mark.asyncio
async def test_execute_denial_does_not_reserve_or_dispatch_a_run(work, monkeypatch):
    from unittest.mock import AsyncMock

    row = await accept_plan(work)
    monkeypatch.setattr(api, "permission", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.start_delivery(
                work.delivery_id,
                proof(row, plan=True),
                session,
                work.actor,
                Request({"type": "http"}),
                work.plans,
                work.runs,
                ExecutionPlanMaterializer(),
                create_default_package_access_policy(),
            )
    assert error.value.status_code == 403
    assert not (await read(work))["dispatch_plan_id"]


@pytest.mark.asyncio
async def test_runtime_not_ready_does_not_freeze_or_dispatch_a_run(work, monkeypatch):
    from unittest.mock import AsyncMock

    row = await accept_plan(work)
    preflight = AsyncMock(side_effect=HTTPException(503, {"code": "DELIVERY_HARNESS_LOOP_NOT_READY"}))
    dispatch = AsyncMock()
    monkeypatch.setattr(d, "check_runtime_readiness", preflight)
    monkeypatch.setattr(api.runtime, "create_run_from_execution_plan", dispatch)
    with pytest.raises(HTTPException) as error:
        async with work.sessions() as session:
            await api.start_delivery(
                work.delivery_id,
                proof(row, plan=True),
                session,
                work.actor,
                Request({"type": "http"}),
                work.plans,
                work.runs,
                ExecutionPlanMaterializer(),
                create_default_package_access_policy(),
            )
    assert error.value.detail["code"] == "DELIVERY_HARNESS_LOOP_NOT_READY"
    stored = await read(work)
    assert stored["revision"] == row["revision"]
    assert stored["plan_approved"]
    assert not stored["dispatch_plan_id"]
    assert not stored["run_id"]
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "available"), [(False, False), (True, False), (True, True)])
async def test_harness_preflight_is_read_only_and_fails_closed(monkeypatch, enabled, available):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from langflow.adlc import task_loop_harness as harness
    from langflow.adlc.task_loop_runtime import LoopRuntimeError

    monkeypatch.setenv("ADLC_TASK_LOOP_HARNESS_ENABLED", str(enabled))
    plan = SimpleNamespace(
        resolved_node_specs=[SimpleNamespace(implementation=SimpleNamespace(adapter_ref=harness.HARNESS_LOOP_SERVICE))]
    )
    runtime = SimpleNamespace(
        check_readiness=AsyncMock(side_effect=None if available else LoopRuntimeError("unavailable")),
        aclose=AsyncMock(),
    )
    factory = Mock(return_value=runtime)
    monkeypatch.setattr(harness.HarnessTaskLoopRuntime, "from_environment", factory)
    if enabled and available:
        await d.check_runtime_readiness(plan)
    else:
        with pytest.raises(HTTPException) as error:
            await d.check_runtime_readiness(plan)
        assert error.value.detail["code"] == "DELIVERY_HARNESS_LOOP_NOT_READY"
    assert factory.call_count == int(enabled)
    assert runtime.check_readiness.await_count == int(enabled)
    assert runtime.aclose.await_count == int(enabled)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "not_ready", "wrong_release"])
async def test_native_readiness_only_reads_health_and_checks_release(change):
    import httpx

    from langflow.adlc.harness_client import HarnessServerSettings
    from langflow.adlc.task_loop_harness import HarnessTaskLoopRuntime, harness_binding
    from langflow.adlc.task_loop_harness_release import PLUGIN_DIGEST
    from langflow.adlc.task_loop_runtime import LoopRuntimeError

    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "ready": change != "not_ready",
                "runtime": harness_binding().model_dump(mode="json"),
                "plugin_digest": "sha256:" + "0" * 64 if change == "wrong_release" else PLUGIN_DIGEST,
            },
        )

    runtime = HarnessTaskLoopRuntime(
        HarnessServerSettings(
            base_url="http://127.0.0.1:3080",
            api_token="offline-fixture-bearer-not-a-real-credential",  # noqa: S106 - offline MockTransport fixture.
        ),
        plugin_digest=PLUGIN_DIGEST,
        transport=httpx.MockTransport(respond),
    )
    try:
        if change is None:
            await runtime.check_readiness()
        else:
            with pytest.raises(LoopRuntimeError, match="HARNESS_ITERATION_RELEASE_MISMATCH"):
                await runtime.check_readiness()
    finally:
        await runtime.aclose()
    assert calls == [("GET", "/api/v1/adlc-harness-iterations/health")]

"""Simple product journey using ADLC's real compiler, approvals and coordinator."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, update
from sqlmodel import select

from langflow.adlc import delivery as d
from langflow.adlc import delivery_cycles as cycles
from langflow.adlc.blueprints.models import ExecutionPlan, WorkflowDefinition
from langflow.adlc.models import MaterializeExecutionPlanRequest
from langflow.adlc.planning.parser import parse_blueprint_flow
from langflow.api.utils import DbSession
from langflow.api.v1 import adlc as runtime
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.api.v1.authz_route_dependencies import get_authorized_flow_for_read, get_authorized_flow_for_write
from langflow.services.authorization import FlowAction, ensure_flow_permission
from langflow.services.database.models.adlc_delivery import AdlcDelivery
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_product_cycle import (
    AdlcCycleFeedback,
    AdlcCycleOperation,
    AdlcCyclePlanRevision,
    AdlcCycleSpec,
    AdlcProductCycle,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess

router = APIRouter(prefix="/adlc/deliveries", tags=["Delivery workspace"])
MAX_DELIVERY_NOTES = 200
MAX_PRODUCT_CYCLES = 100


async def source(session, identity, actor, *, write=False):
    row = await d.owned(session, identity, actor)
    resolve = get_authorized_flow_for_write if write else get_authorized_flow_for_read
    flow = await resolve(flow_id=row.flow_id, current_user=actor, session=session)
    if flow.folder_id and await session.get(AdlcProjectAccess, flow.folder_id):
        d.fail("DELIVERY_TEAM_ADAPTER_REQUIRED", 403)
    return row, flow


async def permission(actor, flow, action):
    try:
        await ensure_flow_permission(
            actor,
            action,
            flow_id=flow.id,
            flow_user_id=flow.user_id,
            folder_id=flow.folder_id,
            workspace_id=flow.workspace_id,
        )
    except HTTPException as exc:
        if exc.status_code not in {403, 404}:
            raise
        return False
    return True


async def snapshot(session, row, flow, actor, run_service, cycle_id=None):
    history = await cycles.summaries(session, row, run_service)
    selected_id = cycle_id or cycles.initial_cycle_id(row.id)
    cycle = await cycles.owned_cycle(session, row, selected_id)
    spec = (
        await session.exec(
            select(AdlcCycleSpec).where(
                AdlcCycleSpec.cycle_id == cycle.id,
                AdlcCycleSpec.revision == cycle.spec_revision,
            )
        )
    ).one()
    revisions = (
        await session.exec(
            select(AdlcCyclePlanRevision)
            .where(
                AdlcCyclePlanRevision.cycle_id == cycle.id,
            )
            .order_by(AdlcCyclePlanRevision.ordinal.desc())
        )
    ).all()
    feedback = (
        await session.exec(
            select(AdlcCycleFeedback)
            .where(
                AdlcCycleFeedback.delivery_id == row.id,
                AdlcCycleFeedback.source_cycle_id == cycle.id,
            )
            .order_by(AdlcCycleFeedback.created_at)
        )
    ).all()
    if cycle.number != 1:
        # Selecting a draft never borrows the first cycle's plan, approval or run.
        row = AdlcDelivery.model_validate(
            {
                **row.model_dump(mode="python"),
                "requirement": cycle.goal,
                "plan_id": cycle.plan_id,
                "run_id": cycle.run_id,
                "dispatch_plan_id": cycle.dispatch_plan_id,
                **{key: cycle.authority.get(key) for key in cycles.AUTHORITY_FIELDS},
            }
        )
        flow = flow.model_copy(update={"data": spec.payload["workflow_snapshot"]})
    archived = await session.get(AdlcExecutionPlan, row.plan_id) if row.plan_id else None
    if archived and (archived.owner_id != str(actor.id) or archived.workflow_definition_id != row.flow_id):
        d.fail("DELIVERY_BINDING_INVALID", 503)
    plan = ExecutionPlan.model_validate(archived.plan_payload) if archived else None
    run = await run_service.get_run(row.run_id, owner_id=str(actor.id)) if row.run_id else None
    if run and (run.flow_id != row.flow_id or run.execution_plan_id != row.plan_id):
        d.fail("DELIVERY_BINDING_INVALID", 503)
    writable = await permission(actor, flow, FlowAction.WRITE)
    planning_operations = []
    if cycle.number != 1:
        from langflow.api.v1.adlc_cycle_planning import active_operations, public_operation

        planning_operations = [public_operation(item) for item in await active_operations(session, cycle)]
    return {
        **row.model_dump(mode="json"),
        "workflow": flow.data or {},
        "workflow_digest": d.graph_digest(flow.data or {}),
        "workflow_approved": d.workflow_accepted(row, flow.data or {}),
        "plan": plan.model_dump(mode="json") if plan else None,
        "plan_digest": d.plan_digest(plan) if plan else None,
        "plan_approved": bool(
            plan
            and d.workflow_accepted(row, flow.data or {})
            and row.plan_approved_by
            and row.plan_approved_digest == d.plan_digest(plan)
        ),
        "run": run.model_dump(mode="json") if run else None,
        "permissions": {"write": writable, "execute": await permission(actor, flow, FlowAction.EXECUTE)},
        "scope": "PRIVATE",
        "folder_id": flow.folder_id,
        "notes": [entry.payload for entry in feedback],
        "cycle": {
            **next(item for item in history if item["id"] == str(selected_id)),
            "spec": spec.payload,
            "spec_digest": spec.digest,
            "planning_operations": planning_operations,
            "plan_revisions": [
                {
                    **item.model_dump(mode="json", exclude={"plan_snapshot", "workflow_snapshot"}),
                    "plan_version": item.plan_snapshot.get("plan_version"),
                }
                for item in revisions
            ],
        },
        "cycles": history,
        "cycle_capabilities": {
            "prepare": writable,
            "execute": cycle.number == 1,
            "edit_workflow": cycle.number == 1,
            "plan_detailed": cycle.number != 1 and not cycle.run_id and not cycle.dispatch_plan_id,
        },
    }


@router.get("")
async def list_deliveries(
    session: DbSession,
    actor: TeamUser,
    response: Response,
    run_service: runtime.AdlcRunServiceDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    candidates = (
        await session.exec(
            select(AdlcDelivery).where(AdlcDelivery.owner_id == actor.id).order_by(AdlcDelivery.updated_at.desc())
        )
    ).all()
    visible = []
    for row in candidates:
        try:
            _, flow = await source(session, row.id, actor)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        visible.append((row, flow))
    return {
        "items": [
            await snapshot(session, row, flow, actor, run_service) for row, flow in visible[offset : offset + limit]
        ],
        "total": len(visible),
        "limit": limit,
        "offset": offset,
    }


@router.post("", status_code=201)
async def create_delivery(command: d.CreateDelivery, session: DbSession, actor: TeamUser):
    flow = await get_authorized_flow_for_write(flow_id=command.flow_id, current_user=actor, session=session)
    if flow.user_id != actor.id:
        d.fail("DELIVERY_TEAM_ADAPTER_REQUIRED", 403)
    if flow.folder_id and await session.get(AdlcProjectAccess, flow.folder_id):
        d.fail("DELIVERY_TEAM_ADAPTER_REQUIRED", 403)
    existing = (await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == flow.id))).first()
    if existing:
        if existing.owner_id == actor.id and existing.requirement == command.requirement:
            return existing.model_dump(mode="json")
        d.fail("DELIVERY_ALREADY_EXISTS")
    row = AdlcDelivery(flow_id=flow.id, owner_id=actor.id, title=command.title, requirement=command.requirement)
    session.add(row)
    await session.flush()
    await cycles.initialize(session, row, flow)
    d.audit(session, row, actor, "created")
    await session.commit()
    return row.model_dump(mode="json")


@router.get("/{identity}")
async def get_delivery(
    identity: UUID,
    session: DbSession,
    actor: TeamUser,
    response: Response,
    run_service: runtime.AdlcRunServiceDep,
    cycle_id: UUID | None = None,
):
    response.headers["Cache-Control"] = "no-store"
    row, flow = await source(session, identity, actor)
    return await snapshot(session, row, flow, actor, run_service, cycle_id)


@router.post("/{identity}/approve-workflow")
async def approve_workflow(identity: UUID, command: d.DeliveryCommand, session: DbSession, actor: TeamUser):
    row, flow = await source(session, identity, actor, write=True)
    await cycles.require_initial_command(session, row, command)
    if not any(
        node.get("data", {}).get("adlc", {}).get("document_type") == "WORKFLOW_STAGE"
        for node in (flow.data or {}).get("nodes", [])
    ):
        d.fail("DELIVERY_WORKFLOW_EMPTY")
    row = await d.lock(session, row, actor, command, flow.data or {})
    if row.run_id or row.dispatch_plan_id:
        d.fail("DELIVERY_RUN_ALREADY_STARTED")
    row.workflow_approved_digest = command.workflow_digest
    row.workflow_approved_by, row.workflow_approved_at = actor.id, datetime.now(timezone.utc)
    row.plan_id, row.plan_approved_digest, row.plan_approved_by, row.plan_approved_at = None, None, None, None
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    d.audit(session, row, actor, "workflow_approved")
    await session.commit()
    return {"revision": row.revision, "approved": True}


@router.post("/{identity}/cycles", status_code=201)
async def prepare_cycle(identity: UUID, command: cycles.PrepareCycleCommand, session: DbSession, actor: TeamUser):
    """Prepare one draft. Do not supersede a plan, inherit approval or dispatch."""
    row, flow = await source(session, identity, actor, write=True)
    predecessor = await cycles.owned_cycle(session, row, command.predecessor_id)
    inputs = {"predecessor_id": str(predecessor.id), "goal": command.goal, "workflow_digest": command.workflow_digest}
    existing = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == "PREPARE_CYCLE",
                AdlcCycleOperation.command_key == str(command.command_id),
            )
        )
    ).first()
    if existing:
        if existing.input_snapshot != inputs:
            d.fail("DELIVERY_COMMAND_CONFLICT")
        return {"revision": row.revision, "cycle_id": existing.result["cycle_id"]}
    _, head = await cycles.initial(session, row)
    if predecessor.id != head.latest_cycle_id:
        d.fail("DELIVERY_CYCLE_HEAD_CHANGED")
    if predecessor.number > 1 and predecessor.state == "DRAFT":
        d.fail("DELIVERY_CYCLE_DRAFT_EXISTS")
    if head.next_number > MAX_PRODUCT_CYCLES:
        d.fail("DELIVERY_CYCLE_LIMIT")
    if not any(
        node.get("data", {}).get("adlc", {}).get("document_type") == "WORKFLOW_STAGE"
        for node in (flow.data or {}).get("nodes", [])
    ):
        d.fail("DELIVERY_WORKFLOW_EMPTY")
    row = await d.lock(session, row, actor, command, flow.data or {})
    await cycles.sync_initial(session, row, flow)
    head = await session.get(type(head), row.id, populate_existing=True)
    cycle = AdlcProductCycle(
        delivery_id=row.id,
        number=head.next_number,
        predecessor_id=predecessor.id,
        goal=command.goal,
        created_by=actor.id,
    )
    session.add(cycle)
    await session.flush()
    payload = cycles.spec_payload(row, flow.data or {}, cycle.id, command.goal, predecessor.id)
    session.add(
        AdlcCycleSpec(cycle_id=cycle.id, digest=cycles.sha256_digest(payload), payload=payload, created_by=actor.id)
    )
    head.latest_cycle_id, head.next_number = cycle.id, cycle.number + 1
    session.add(head)
    receipt, _ = await cycles.operation(session, row, cycle, actor, "PREPARE_CYCLE", str(command.command_id), inputs)
    receipt.status, receipt.result = "SUCCEEDED", {"cycle_id": str(cycle.id)}
    session.add(receipt)
    d.audit(session, row, actor, "cycle_prepared")
    await session.commit()
    return {"revision": row.revision, "cycle_id": cycle.id}


@router.post("/{identity}/cycles/{cycle_id}/spec")
async def update_cycle_spec(
    identity: UUID, cycle_id: UUID, command: cycles.UpdateCycleCommand, session: DbSession, actor: TeamUser
):
    row, _flow = await source(session, identity, actor, write=True)
    cycle = await cycles.owned_cycle(session, row, cycle_id)
    inputs = {"cycle_id": str(cycle_id), "spec_digest": command.spec_digest, "goal": command.goal}
    existing = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == "UPDATE_SPEC",
                AdlcCycleOperation.command_key == str(command.command_id),
            )
        )
    ).first()
    if existing:
        if existing.input_snapshot != inputs:
            d.fail("DELIVERY_COMMAND_CONFLICT")
        return {"revision": row.revision, "cycle_id": cycle.id}
    if cycle.number == 1 or cycle.state != "DRAFT" or cycle.plan_id or cycle.run_id or cycle.dispatch_plan_id:
        d.fail("DELIVERY_CYCLE_SPEC_FROZEN")
    from langflow.api.v1.adlc_cycle_planning import active_operations, editable

    editable(cycle, await active_operations(session, cycle))
    spec = (
        await session.exec(
            select(AdlcCycleSpec).where(
                AdlcCycleSpec.cycle_id == cycle.id,
                AdlcCycleSpec.revision == cycle.spec_revision,
            )
        )
    ).one()
    if spec.digest != command.spec_digest:
        d.fail("DELIVERY_CYCLE_SPEC_CHANGED")
    row = await d.lock(session, row, actor, command, spec.payload["workflow_snapshot"])
    cycle.goal, cycle.revision, cycle.spec_revision = command.goal, cycle.revision + 1, cycle.spec_revision + 1
    cycle.updated_at = datetime.now(timezone.utc)
    payload = {**spec.payload, "goal": command.goal, "planning_ready": False, "execution_ready": False}
    payload.pop("planning", None)
    cycle.authority = {}
    session.add(
        AdlcCycleSpec(
            cycle_id=cycle.id,
            revision=cycle.spec_revision,
            payload=payload,
            digest=cycles.sha256_digest(payload),
            created_by=actor.id,
        )
    )
    session.add(cycle)
    # Do not rewrite the first cycle's scope while editing a successor draft.
    _, head = await cycles.initial(session, row)
    head.revision = row.revision
    session.add(head)
    receipt, _ = await cycles.operation(session, row, cycle, actor, "UPDATE_SPEC", str(command.command_id), inputs)
    receipt.status, receipt.result = "SUCCEEDED", {"cycle_id": str(cycle.id), "spec_revision": cycle.spec_revision}
    session.add(receipt)
    d.audit(session, row, actor, "cycle_spec_updated")
    await session.commit()
    return {"revision": row.revision, "cycle_id": cycle.id}


@router.post("/{identity}/compile")
async def compile_delivery(
    identity: UUID,
    command: d.DeliveryCommand,
    session: DbSession,
    actor: TeamUser,
    plan_service: runtime.ExecutionPlanServiceDep,
):
    row, flow = await source(session, identity, actor, write=True)
    cycle = await cycles.require_initial_command(session, row, command)
    key = str(command.command_id) if command.command_id else f"revision:{command.expected_revision}"
    inputs = {"cycle_id": str(cycle.id), "workflow_digest": command.workflow_digest}
    # Check durable idempotency before consulting a process-local compiler cache.
    previous = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == "COMPILE",
                AdlcCycleOperation.command_key == key,
            )
        )
    ).first()
    if previous:
        if previous.input_snapshot != inputs:
            d.fail("DELIVERY_COMMAND_CONFLICT")
        if previous.status != "SUCCEEDED":
            d.fail("DELIVERY_GENERATION_UNCONFIRMED")
        archived = await session.get(AdlcExecutionPlan, UUID(previous.result["plan_id"]))
        if not archived or archived.owner_id != str(actor.id) or archived.workflow_definition_id != row.flow_id:
            d.fail("DELIVERY_PLAN_ARCHIVE_UNAVAILABLE", 503)
        return {"revision": row.revision, "plan": archived.plan_payload}
    d.require_workflow(row, flow.data or {})
    if row.run_id or row.dispatch_plan_id:
        d.fail("DELIVERY_RUN_ALREADY_STARTED")
    if row.revision != command.expected_revision or d.graph_digest(flow.data or {}) != command.workflow_digest:
        d.fail("DELIVERY_REVISION_CONFLICT")
    row = await d.lock(session, row, actor, command, flow.data or {})
    d.require_workflow(row, flow.data or {})
    await cycles.sync_initial(session, row, flow)
    receipt, _ = await cycles.operation(session, row, cycle, actor, "COMPILE", key, inputs)
    workflow = parse_blueprint_flow(flow.data or {}, await runtime._local_definition_context(flow, actor, session))  # noqa: SLF001 - same planning boundary.
    version = (
        await session.exec(
            select(func.max(AdlcExecutionPlan.plan_version)).where(
                AdlcExecutionPlan.owner_id == str(actor.id),
                AdlcExecutionPlan.workflow_definition_id == row.flow_id,
            )
        )
    ).one() or 0
    # SQL serializes the head/version; the compiler does not mutate any cache yet.
    plan = plan_service.compile_snapshot(
        workflow,
        owner_id=str(actor.id),
        generated_by=str(actor.id),
        plan_version=version + 1,
        supersedes_plan_id=row.plan_id,
    ).model_copy(update={"approval_required": True})
    if row.plan_id:
        old = await session.get(AdlcExecutionPlan, row.plan_id, populate_existing=True)
        old.status = "SUPERSEDED"
        old.plan_payload = {**old.plan_payload, "status": "SUPERSEDED"}
        session.add(old)
    await runtime.archive_execution_plan(session, owner_id=str(actor.id), plan=plan, workflow=workflow, strict=True)
    row.plan_id = plan.execution_plan_id
    row.plan_approved_digest, row.plan_approved_by, row.plan_approved_at = None, None, None
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    receipt.status, receipt.result = "SUCCEEDED", {"plan_id": str(plan.execution_plan_id)}
    session.add(receipt)
    d.audit(session, row, actor, "plan_compiled")
    await session.commit()
    plan_service.restore_plan(workflow=workflow, plan=plan, owner_id=str(actor.id), replace_existing=True)
    return {"revision": row.revision, "plan": plan.model_dump(mode="json")}


@router.post("/{identity}/approve-plan")
async def approve_plan(
    identity: UUID,
    command: d.PlanCommand,
    session: DbSession,
    actor: TeamUser,
    plan_service: runtime.ExecutionPlanServiceDep,
):
    row, flow = await source(session, identity, actor, write=True)
    await cycles.require_initial_command(session, row, command)
    d.require_workflow(row, flow.data or {})
    if not row.plan_id or row.run_id or row.dispatch_plan_id:
        d.fail("DELIVERY_PLAN_REQUIRED")
    archived = await session.get(AdlcExecutionPlan, row.plan_id, populate_existing=True)
    if not archived or archived.owner_id != str(actor.id) or archived.workflow_definition_id != row.flow_id:
        d.fail("DELIVERY_PLAN_ARCHIVE_UNAVAILABLE", 503)
    plan = ExecutionPlan.model_validate(archived.plan_payload)
    if d.plan_digest(plan) != command.plan_digest:
        d.fail("DELIVERY_PLAN_CHANGED")
    row = await d.lock(session, row, actor, command, flow.data or {})
    # An isolated lifecycle store prevents an uncommitted approval becoming a
    # multi-worker source of authority. The archive and receipt commit together.
    workflow = WorkflowDefinition.model_validate(archived.workflow_payload)
    accepted = plan_service.approve_snapshot(
        workflow, plan, owner_id=str(actor.id), approved_by=str(actor.id), comment="Reviewed in the delivery workspace"
    )
    await runtime.archive_execution_plan(session, owner_id=str(actor.id), plan=accepted, workflow=workflow, strict=True)
    archive = await session.get(AdlcExecutionPlan, row.plan_id, populate_existing=True)
    if not archive or archive.plan_payload != accepted.model_dump(mode="json"):
        d.fail("DELIVERY_PLAN_ARCHIVE_UNAVAILABLE", 503)
    row.plan_approved_digest, row.plan_approved_by = d.plan_digest(accepted), actor.id
    row.plan_approved_at = datetime.now(timezone.utc)
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    d.audit(session, row, actor, "plan_approved")
    await session.commit()
    plan_service.restore_plan(workflow=workflow, plan=accepted, owner_id=str(actor.id), replace_existing=True)
    return {"revision": row.revision, "approved": True}


@router.post("/{identity}/start")
async def start_delivery(
    identity: UUID,
    command: d.PlanCommand,
    session: DbSession,
    actor: TeamUser,
    request: Request,
    plan_service: runtime.ExecutionPlanServiceDep,
    run_service: runtime.AdlcRunServiceDep,
    materializer: runtime.ExecutionPlanMaterializerDep,
    access_policy: runtime.PackageAccessPolicyDep,
):
    row, flow = await source(session, identity, actor, write=True)
    cycle = await cycles.require_initial_command(session, row, command)
    if row.run_id:
        return {"run_id": row.run_id}
    if row.dispatch_plan_id:
        # An unknown acknowledgement is not permission to dispatch a second agent.
        d.fail("DELIVERY_RUN_START_UNCONFIRMED")
    if not await permission(actor, flow, FlowAction.EXECUTE):
        d.fail("DELIVERY_EXECUTION_DENIED", 403)
    archived = await session.get(AdlcExecutionPlan, row.plan_id, populate_existing=True) if row.plan_id else None
    if archived and (archived.owner_id != str(actor.id) or archived.workflow_definition_id != row.flow_id):
        d.fail("DELIVERY_BINDING_INVALID", 503)
    plan = ExecutionPlan.model_validate(archived.plan_payload) if archived else None
    if not plan or plan.status != "APPROVED" or d.plan_digest(plan) != command.plan_digest:
        d.fail("DELIVERY_PLAN_CHANGED")
    await d.ensure_run_authority(session, flow, actor, plan)
    await d.check_runtime_readiness(plan)
    row = await d.lock(session, row, actor, command, flow.data or {})
    flow_id, plan_id = row.flow_id, row.plan_id
    row.dispatch_plan_id = plan_id
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    receipt, repeated = await cycles.operation(
        session,
        row,
        cycle,
        actor,
        "DISPATCH",
        str(plan_id),
        {"plan_id": str(plan_id), "plan_digest": command.plan_digest},
    )
    if repeated:
        d.fail("DELIVERY_RUN_START_UNCONFIRMED")
    d.audit(session, row, actor, "run_requested")
    await session.commit()
    plan_service.restore_plan(
        workflow=WorkflowDefinition.model_validate(archived.workflow_payload),
        plan=plan,
        owner_id=str(actor.id),
        replace_existing=True,
    )
    run = await runtime.create_run_from_execution_plan(
        plan_id,
        MaterializeExecutionPlanRequest(idempotency_key=f"delivery:{identity}:{plan_id}"),
        actor,
        session,
        plan_service,
        run_service,
        materializer,
        access_policy,
        request,
    )
    row, flow = await source(session, identity, actor, write=True)
    if flow.id != flow_id or row.plan_id != plan_id:
        d.fail("DELIVERY_BINDING_INVALID", 503)
    row.run_id = run.id
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    receipt = await session.get(AdlcCycleOperation, receipt.id, populate_existing=True)
    receipt.status, receipt.result = "SUCCEEDED", {"run_id": str(run.id)}
    session.add(receipt)
    d.audit(session, row, actor, "run_linked")
    await session.commit()
    return {"run_id": run.id}


@router.post("/{identity}/notes")
async def add_note(identity: UUID, command: d.NoteCommand, session: DbSession, actor: TeamUser):
    row, _flow = await source(session, identity, actor, write=True)
    cycle = await cycles.owned_cycle(session, row, command.cycle_id or cycles.initial_cycle_id(row.id))
    existing = next((note for note in row.notes if note["id"] == str(command.command_id)), None)
    if existing:
        if (
            existing["text"] != command.text
            or existing["kind"] != command.kind
            or existing.get("cycle_id", str(cycles.initial_cycle_id(row.id))) != str(cycle.id)
        ):
            d.fail("DELIVERY_COMMAND_CONFLICT")
        return {"revision": row.revision}
    if len(row.notes) >= MAX_DELIVERY_NOTES:
        d.fail("DELIVERY_NOTE_LIMIT")
    result = await session.exec(
        update(AdlcDelivery)
        .where(
            AdlcDelivery.id == row.id,
            AdlcDelivery.owner_id == actor.id,
            AdlcDelivery.revision == command.expected_revision,
        )
        .values(revision=AdlcDelivery.revision + 1)
    )
    if result.rowcount != 1:
        d.fail("DELIVERY_REVISION_CONFLICT")
    row = await d.owned(session, identity, actor)
    note = {**d.new_note(command, actor), "cycle_id": str(cycle.id)}
    row.notes = [*row.notes, note]
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await cycles.add_feedback(session, row, note, cycle.id)
    await cycles.sync_initial(session, row, _flow)
    d.audit(session, row, actor, "note_added")
    await session.commit()
    return {"revision": row.revision}


@router.post("/{identity}/reconcile")
async def reconcile_delivery(
    identity: UUID,
    command: d.PlanCommand,
    session: DbSession,
    actor: TeamUser,
    run_service: runtime.AdlcRunServiceDep,
):
    """Link a unique canonical run after an unknown acknowledgement. Never dispatch."""
    row, flow = await source(session, identity, actor, write=True)
    await cycles.require_initial_command(session, row, command)
    if row.run_id:
        return {"run_id": row.run_id}
    if (
        not row.dispatch_plan_id
        or row.dispatch_plan_id != row.plan_id
        or row.plan_approved_digest != command.plan_digest
    ):
        d.fail("DELIVERY_PLAN_CHANGED")
    found = await run_service.list_runs(
        owner_id=str(actor.id), flow_id=row.flow_id, execution_plan_id=row.plan_id, limit=2
    )
    if found.total != 1:
        d.fail("DELIVERY_RUN_START_UNCONFIRMED")
    row = await d.lock(session, row, actor, command, flow.data or {})
    row.run_id = found.runs[0].id
    session.add(row)
    await cycles.sync_initial(session, row, flow)
    receipt = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == "DISPATCH",
                AdlcCycleOperation.command_key == str(row.plan_id),
            )
        )
    ).first()
    if receipt:
        receipt.status, receipt.result = "SUCCEEDED", {"run_id": str(row.run_id)}
        session.add(receipt)
    d.audit(session, row, actor, "run_reconciled")
    await session.commit()
    return {"run_id": row.run_id}

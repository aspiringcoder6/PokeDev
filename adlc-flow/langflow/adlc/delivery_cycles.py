"""SQL-owned cycle heads, immutable snapshots and command receipts for Delivery.

No generation, approval or dispatch is implied by creating a successor draft.
The legacy Delivery columns remain the first cycle's authority during H8B.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field
from sqlmodel import select

from langflow.adlc import delivery as d
from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.models import ExecutionPlan
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

AUTHORITY_FIELDS = (
    "workflow_approved_digest",
    "workflow_approved_by",
    "workflow_approved_at",
    "plan_approved_digest",
    "plan_approved_by",
    "plan_approved_at",
)


def normalized_authority(value):
    result = dict(value)
    for key in ("workflow_approved_at", "plan_approved_at"):
        if result.get(key):
            stamp = datetime.fromisoformat(result[key])
            result[key] = (
                stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
            ).isoformat()
    return result


class PrepareCycleCommand(d.DeliveryCommand):
    command_id: UUID
    predecessor_id: UUID
    goal: Annotated[d.Text, Field(max_length=20000)]


class UpdateCycleCommand(d.DeliveryCommand):
    command_id: UUID
    spec_digest: d.Digest
    goal: Annotated[d.Text, Field(max_length=20000)]


def initial_cycle_id(delivery_id):
    return uuid5(NAMESPACE_URL, f"adlc:{delivery_id}:cycle:1")


def spec_payload(row, graph, cycle_id, goal, predecessor_id=None):
    return {
        "schema_version": "0.1",
        "delivery_id": str(row.id),
        "cycle_id": str(cycle_id),
        "predecessor_id": str(predecessor_id) if predecessor_id else None,
        "goal": goal,
        "workflow_id": str(row.flow_id),
        "workflow_version": graph.get("adlc", {}).get("version"),
        "workflow_digest": d.graph_digest(graph),
        "workflow_snapshot": deepcopy(graph),
        "baseline": None,
        "acceptance_criteria": [],
        "selected_feedback_ids": [],
        "execution_ready": False,
        "source": "LEGACY_IMPORT" if predecessor_id is None else "USER_DRAFT",
    }


async def initialize(session, row, flow):
    """Create the first cycle in the same transaction as a new Delivery."""
    identity = initial_cycle_id(row.id)
    cycle = AdlcProductCycle(
        id=identity,
        delivery_id=row.id,
        number=1,
        state="PLANNING",
        goal=row.requirement,
        created_by=row.owner_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    session.add(cycle)
    await session.flush()
    payload = spec_payload(row, flow.data or {}, identity, row.requirement)
    session.add(
        AdlcCycleSpec(
            cycle_id=identity,
            payload=payload,
            digest=sha256_digest(payload),
            created_by=row.owner_id,
            created_at=row.created_at,
        )
    )
    session.add(AdlcCycleHead(delivery_id=row.id, latest_cycle_id=identity))
    await session.flush()
    return cycle


async def initial(session, row):
    cycle = await session.get(AdlcProductCycle, initial_cycle_id(row.id), populate_existing=True)
    head = await session.get(AdlcCycleHead, row.id, populate_existing=True)
    if cycle is None or head is None or cycle.delivery_id != row.id:
        d.fail("DELIVERY_CYCLE_ARCHIVE_UNAVAILABLE", 503)
    return cycle, head


async def owned_cycle(session, row, identity):
    cycle = await session.get(AdlcProductCycle, identity, populate_existing=True)
    if cycle is None or cycle.delivery_id != row.id:
        d.fail("DELIVERY_CYCLE_NOT_FOUND", 404)
    return cycle


async def require_initial_command(session, row, command):
    identity = command.cycle_id or initial_cycle_id(row.id)
    cycle = await owned_cycle(session, row, identity)
    if cycle.number != 1:
        d.fail("DELIVERY_CYCLE_PLANNING_NOT_READY")
    return cycle


async def sync_initial(session, row, flow):
    """Called only in a CAS-protected mutation, never a GET or another cycle."""
    cycle, head = await initial(session, row)
    payload = spec_payload(row, flow.data or {}, cycle.id, row.requirement)
    digest = sha256_digest(payload)
    current = (
        await session.exec(
            select(AdlcCycleSpec).where(
                AdlcCycleSpec.cycle_id == cycle.id,
                AdlcCycleSpec.revision == cycle.spec_revision,
            )
        )
    ).one()
    # A dispatched cycle's frozen scope is never replaced by edits to the canvas.
    if not cycle.dispatch_plan_id and digest != current.digest:
        cycle.spec_revision += 1
        session.add(
            AdlcCycleSpec(
                cycle_id=cycle.id,
                revision=cycle.spec_revision,
                digest=digest,
                payload=payload,
                created_by=row.owner_id,
            )
        )
    authority = normalized_authority({key: row.model_dump(mode="json")[key] for key in AUTHORITY_FIELDS})
    cycle.authority = authority
    cycle.plan_id, cycle.run_id, cycle.dispatch_plan_id = row.plan_id, row.run_id, row.dispatch_plan_id
    cycle.revision = row.revision
    cycle.state = "LINKED" if row.run_id else "DISPATCH_RESERVED" if row.dispatch_plan_id else "PLANNING"
    cycle.updated_at = row.updated_at
    head.revision = row.revision
    if row.dispatch_plan_id or row.run_id:
        if head.execution_cycle_id not in {None, cycle.id}:
            d.fail("DELIVERY_ACTIVE_CYCLE_EXISTS")
        head.execution_cycle_id = cycle.id
    session.add_all([cycle, head])
    if row.plan_id:
        archive = await session.get(AdlcExecutionPlan, row.plan_id, populate_existing=True)
        if not archive or archive.owner_id != str(row.owner_id) or archive.workflow_definition_id != row.flow_id:
            d.fail("DELIVERY_PLAN_ARCHIVE_UNAVAILABLE", 503)
        plan = ExecutionPlan.model_validate(archive.plan_payload)
        binding = (
            await session.exec(
                select(AdlcCyclePlanRevision).where(
                    AdlcCyclePlanRevision.plan_id == row.plan_id,
                )
            )
        ).first()
        if binding is None:
            prior = (
                await session.exec(
                    select(AdlcCyclePlanRevision)
                    .where(
                        AdlcCyclePlanRevision.cycle_id == cycle.id,
                    )
                    .order_by(AdlcCyclePlanRevision.ordinal.desc())
                )
            ).first()
            binding = AdlcCyclePlanRevision(
                cycle_id=cycle.id,
                ordinal=prior.ordinal + 1 if prior else 1,
                plan_id=row.plan_id,
                predecessor_plan_id=prior.plan_id if prior else plan.supersedes_plan_id,
                plan_digest=d.plan_digest(plan),
                plan_snapshot=archive.plan_payload,
                workflow_snapshot=archive.workflow_payload,
                created_at=archive.generated_at,
            )
        if binding.cycle_id != cycle.id or binding.plan_digest != d.plan_digest(plan):
            d.fail("DELIVERY_BINDING_INVALID", 503)
        if row.plan_approved_digest:
            receipt = {key: authority[key] for key in AUTHORITY_FIELDS if key.startswith("plan_")}
            if binding.approval and normalized_authority(binding.approval) != receipt:
                d.fail("DELIVERY_BINDING_INVALID", 503)
            if not binding.approval:
                binding.approval = receipt
        session.add(binding)
    await session.flush()
    return cycle


async def operation(session, row, cycle, actor, kind, key, inputs):
    digest = sha256_digest(inputs)
    existing = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == kind,
                AdlcCycleOperation.command_key == key,
            )
        )
    ).first()
    if existing:
        if existing.cycle_id != cycle.id or existing.input_digest != digest:
            d.fail("DELIVERY_COMMAND_CONFLICT")
        return existing, True
    receipt = AdlcCycleOperation(
        delivery_id=row.id,
        cycle_id=cycle.id,
        actor_id=actor.id,
        kind=kind,
        command_key=key,
        input_digest=digest,
        input_snapshot=deepcopy(inputs),
    )
    session.add(receipt)
    return receipt, False


async def add_feedback(session, row, note, cycle_id):
    session.add(
        AdlcCycleFeedback(
            delivery_id=row.id,
            source_cycle_id=cycle_id,
            source_key=f"note:{note['id']}",
            payload=deepcopy(note),
        )
    )


async def summaries(session, row, run_service):
    cycles = (
        await session.exec(
            select(AdlcProductCycle)
            .where(
                AdlcProductCycle.delivery_id == row.id,
            )
            .order_by(AdlcProductCycle.number.desc())
        )
    ).all()
    head = await session.get(AdlcCycleHead, row.id)
    if not head or not cycles:
        d.fail("DELIVERY_CYCLE_ARCHIVE_UNAVAILABLE", 503)
    result = []
    for cycle in cycles:
        run = await run_service.get_run(cycle.run_id, owner_id=str(row.owner_id)) if cycle.run_id else None
        if run and (run.flow_id != row.flow_id or run.execution_plan_id != cycle.plan_id):
            d.fail("DELIVERY_BINDING_INVALID", 503)
        archived = await session.get(AdlcExecutionPlan, cycle.plan_id) if cycle.plan_id else None
        result.append(
            {
                **cycle.model_dump(mode="json", exclude={"authority"}),
                "run_status": run.status if run else None,
                "is_initial": cycle.number == 1,
                "is_latest": cycle.id == head.latest_cycle_id,
                "is_execution_cycle": cycle.id == head.execution_cycle_id,
                "plan_version": archived.plan_version if archived else None,
            }
        )
    return result


async def reject_external_planning(session, workflow_id, actor):
    """Advanced planning must not supersede/approve a workspace-bound plan."""
    if session is None:
        return
    row = (await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == workflow_id))).first()
    if row:
        if row.owner_id != actor.id:
            d.fail("DELIVERY_NOT_FOUND", 404)
        d.fail("DELIVERY_USE_WORKSPACE")

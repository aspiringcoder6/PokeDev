"""Selected-cycle planning. SQL is authority; Harness is only a proposal generator."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import func
from sqlmodel import select

from langflow.adlc import cycle_planning as p
from langflow.adlc import delivery as d
from langflow.adlc import delivery_cycles as cycles
from langflow.adlc.blueprints.models import ExecutionPlan, WorkflowDefinition
from langflow.adlc.cycle_planning_client import planner_client
from langflow.adlc.planning.parser import parse_blueprint_flow
from langflow.adlc.task_loop_harness import _closed_object, _nonfinite
from langflow.api.utils import DbSession
from langflow.api.v1 import adlc as runtime
from langflow.api.v1 import adlc_delivery as delivery
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_product_cycle import (
    AdlcCycleOperation,
    AdlcCyclePlanRevision,
    AdlcCycleSpec,
)

router = APIRouter(prefix="/adlc/deliveries/{identity}/cycles/{cycle_id}/planning", tags=["Cycle planning"])


async def current(session, identity, cycle_id, actor, *, write=False):
    row, flow = await delivery.source(session, identity, actor, write=write)
    cycle = await cycles.owned_cycle(session, row, cycle_id)
    spec = (
        await session.exec(
            select(AdlcCycleSpec).where(
                AdlcCycleSpec.cycle_id == cycle.id, AdlcCycleSpec.revision == cycle.spec_revision
            )
        )
    ).one()
    if cycle.number == 1:
        d.fail("CYCLE_USE_SUCCESSOR_DRAFT")
    return row, flow, cycle, spec


async def workflow_for(flow, spec, actor, session):
    return parse_blueprint_flow(
        spec.payload["workflow_snapshot"],
        await runtime._local_definition_context(flow, actor, session),  # noqa: SLF001
    )


async def active_operations(session, cycle):
    return (
        await session.exec(
            select(AdlcCycleOperation)
            .where(AdlcCycleOperation.cycle_id == cycle.id, AdlcCycleOperation.kind == p.KIND)
            .order_by(AdlcCycleOperation.created_at.desc(), AdlcCycleOperation.id)
        )
    ).all()


def editable(cycle, operations):
    if cycle.run_id or cycle.dispatch_plan_id or cycle.plan_id:
        d.fail("DELIVERY_CYCLE_SPEC_FROZEN")
    if any(op.status in {"RESERVED", "UNCONFIRMED"} for op in operations):
        d.fail("CYCLE_GENERATION_UNCONFIRMED")


def require_spec(command, cycle, spec):
    if command.cycle_id != cycle.id or command.spec_digest != spec.digest:
        d.fail("DELIVERY_CYCLE_SPEC_CHANGED")


async def duplicate(session, row, cycle, key, kind, inputs):
    old = (
        await session.exec(
            select(AdlcCycleOperation).where(
                AdlcCycleOperation.delivery_id == row.id,
                AdlcCycleOperation.kind == kind,
                AdlcCycleOperation.command_key == str(key),
            )
        )
    ).first()
    if old and (old.cycle_id != cycle.id or old.input_snapshot.get("command") != inputs):
        d.fail("DELIVERY_COMMAND_CONFLICT")
    return old


def public_operation(op):
    return {
        "id": str(op.id),
        "cycle_id": str(op.cycle_id),
        "status": op.status,
        "spec_digest": op.input_snapshot["spec_digest"],
        "input_digest": op.input_digest,
        "created_at": op.created_at.isoformat(),
        "updated_at": op.updated_at.isoformat(),
        **{
            key: value
            for key, value in op.result.items()
            if key
            in {
                "phase",
                "error_code",
                "proposal",
                "preview_plan",
                "plan_digest",
                "diff",
                "usage",
                "validation_errors",
                "accepted_at",
            }
        },
    }


@router.get("/context")
async def planning_context(identity: UUID, cycle_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    _row, flow, cycle, spec = await current(session, identity, cycle_id, actor)
    workflow = await workflow_for(flow, spec, actor, session)
    context = await p.repository_context(workflow)
    return {
        "cycle_id": str(cycle.id),
        "spec_digest": spec.digest,
        "repository_key": context["repository_key"],
        "base_commit": context["base_commit"],
        "paths": sorted(context["files"]),
        "acceptance_criteria": p.criteria_for(workflow),
        "limits": p.PlanProposalLimits().model_dump(),
        "workflow_digest": spec.payload["workflow_digest"],
    }


@router.post("/freeze")
async def freeze_spec(
    identity: UUID,
    cycle_id: UUID,
    command: p.FreezeCommand,
    session: DbSession,
    actor: TeamUser,
    registry: runtime.NodePackageRegistryDep,
):
    row, _flow, cycle, spec = await current(session, identity, cycle_id, actor, write=True)
    inputs = command.model_dump(mode="json", exclude={"expected_revision", "command_id"})
    old = await duplicate(session, row, cycle, command.command_id, "FREEZE_PLANNING", inputs)
    if old:
        return {"revision": row.revision, "cycle_id": str(cycle.id)}
    require_spec(command, cycle, spec)
    editable(cycle, await active_operations(session, cycle))
    workflow = await workflow_for(_flow, spec, actor, session)
    baseline = await p.repository_context(workflow, command.base_commit)
    scoped = p.scoped_workflow(workflow, cycle, baseline)
    scoped = scoped.model_copy(
        update={
            "stages": [
                stage.model_copy(
                    update={
                        "package_ref": stage.package_ref.model_copy(
                            update={"content_digest": registry.get(stage.package_ref).content_digest}
                        ),
                    }
                )
                for stage in scoped.stages
            ]
        }
    )
    criteria = p.criteria_for(scoped)
    row = await d.lock(session, row, actor, command, spec.payload["workflow_snapshot"])
    cycle.spec_revision += 1
    cycle.revision += 1
    cycle.updated_at = datetime.now(timezone.utc)
    payload = {
        **spec.payload,
        "baseline": {k: v for k, v in baseline.items() if k != "files"},
        "acceptance_criteria": criteria,
        "planning_ready": True,
        "execution_ready": False,
        "planning": {
            "workflow": scoped.model_dump(mode="json"),
            "context": baseline,
            "limits": command.limits.model_dump(mode="json"),
        },
    }
    sealed = AdlcCycleSpec(
        cycle_id=cycle.id,
        revision=cycle.spec_revision,
        payload=payload,
        digest=p.sha256_digest(payload),
        created_by=actor.id,
    )
    cycle.authority = {
        "workflow_approved_digest": command.workflow_digest,
        "workflow_approved_by": str(actor.id),
        "workflow_approved_at": datetime.now(timezone.utc).isoformat(),
    }
    session.add_all([cycle, sealed])
    receipt, _ = await cycles.operation(
        session, row, cycle, actor, "FREEZE_PLANNING", str(command.command_id), {"command": inputs}
    )
    receipt.status, receipt.result = "SUCCEEDED", {"spec_digest": sealed.digest}
    session.add(receipt)
    d.audit(session, row, actor, "cycle_planning_frozen")
    await session.commit()
    return {"revision": row.revision, "cycle_id": str(cycle.id)}


async def verify_baseline(spec):
    frozen = spec.payload["planning"]
    workflow = WorkflowDefinition.model_validate(frozen["workflow"])
    context = await p.repository_context(workflow, frozen["context"]["base_commit"])
    if context != frozen["context"]:
        d.fail("CYCLE_BASELINE_CHANGED")
    return workflow


@router.post("/generate", status_code=202)
async def generate_plan(
    identity: UUID,
    cycle_id: UUID,
    command: p.SpecCommand,
    session: DbSession,
    actor: TeamUser,
    registry: runtime.NodePackageRegistryDep,
    access: runtime.PackageAccessPolicyDep,
    plan_service: runtime.ExecutionPlanServiceDep,
    client_factory=Depends(lambda: planner_client),
):
    row, _flow, cycle, spec = await current(session, identity, cycle_id, actor, write=True)
    inputs = command.model_dump(mode="json", exclude={"expected_revision", "command_id"})
    old = await duplicate(session, row, cycle, command.command_id, p.KIND, inputs)
    if old:
        # A repeated browser request is only a SQL read, never another remote POST.
        return public_operation(old)
    require_spec(command, cycle, spec)
    operations = await active_operations(session, cycle)
    editable(cycle, operations)
    if len(operations) >= p.MAX_GENERATIONS:
        d.fail("CYCLE_GENERATION_BUDGET_EXHAUSTED")
    if not spec.payload.get("planning_ready") or not spec.payload.get("planning"):
        d.fail("CYCLE_SPEC_FREEZE_REQUIRED")
    if spec.payload.get("selected_feedback_ids"):
        d.fail("CYCLE_FEEDBACK_SELECTION_NOT_ENABLED")
    workflow = await verify_baseline(spec)
    preflight = plan_service.compile_snapshot(
        workflow, owner_id=str(actor.id), generated_by=str(actor.id), plan_version=1
    )
    if preflight.validation_status != "VALID":
        d.fail("CYCLE_SOURCE_PLAN_INVALID", 422)
    # Compile the fixed stage inputs before spending model budget; no unsupported executor/policy fallback.
    if not any(registry.get(stage.package_ref).definition.kind.value == "APPROVAL" for stage in workflow.stages):
        d.fail("CYCLE_HUMAN_GATE_REQUIRED", 422)
    for stage in workflow.stages:
        registered = registry.get(stage.package_ref)
        access.ensure_package_visible(str(actor.id), stage.package_ref)
        if "mock" in registered.definition.implementation.adapter_ref.casefold():
            d.fail("CYCLE_EXECUTOR_UNSUPPORTED", 422)
        if registered.definition.kind.value == "TESTING" and (
            registered.definition.implementation.adapter_ref,
            registered.definition.implementation.entrypoint,
        ) != ("integration:workflow-plugins", "TESTFORGE_REPLAY"):
            d.fail("CYCLE_EXECUTOR_UNSUPPORTED", 422)
    client = client_factory()
    try:
        await client.readiness()  # read-only preflight, before reserving the single paid call
        row = await d.lock(session, row, actor, command, spec.payload["workflow_snapshot"])
        # Frozen identity and exact prompt are committed BEFORE talking to the remote generator.
        previous = next((op.result.get("proposal") for op in operations if op.result.get("proposal")), None)
        remote = {
            "generation_id": str(uuid4()),
            "prompt": p.prompt_for(
                {
                    "cycle_id": str(cycle.id),
                    "spec_digest": spec.digest,
                    "goal": cycle.goal,
                    "workflow": spec.payload["planning"]["workflow"],
                    "repository_context": spec.payload["planning"]["context"],
                    "acceptance_criteria": spec.payload["acceptance_criteria"],
                    "selected_feedback": [],
                    "previous_proposal": previous,
                    "limits": spec.payload["planning"]["limits"],
                }
            ),
            "timeout_ms": 600_000,
        }
        if len(remote["prompt"].encode()) > p.MAX_PROMPT_BYTES:
            d.fail("CYCLE_CONTEXT_LIMIT", 422)
        remote["request_digest"] = p.sha256_digest(remote)
        remote["schema_version"] = "0.1"
        receipt, _ = await cycles.operation(
            session,
            row,
            cycle,
            actor,
            p.KIND,
            str(command.command_id),
            {
                "command": inputs,
                "spec_digest": spec.digest,
                "spec_revision": cycle.spec_revision,
                "frozen_spec": spec.payload,
                "remote_command": remote,
            },
        )
        receipt.result = {"phase": "RESERVED"}
        session.add(receipt)
        d.audit(session, row, actor, "cycle_plan_requested")
        await session.commit()
        try:
            observed = await client.create(remote)
            receipt.result = {"phase": observed.state}
            receipt.status = "UNCONFIRMED" if observed.state == "UNCONFIRMED" else "RESERVED"
        except (HTTPException, ValueError, OSError):
            receipt.status, receipt.result = (
                "UNCONFIRMED",
                {"phase": "UNCONFIRMED", "error_code": "CYCLE_GENERATION_UNCONFIRMED"},
            )
        receipt.updated_at = datetime.now(timezone.utc)
        session.add(receipt)
        await session.commit()
        return public_operation(receipt)
    finally:
        await client.aclose()


@router.post("/generations/{generation_id}/reconcile")
async def reconcile_plan(
    identity: UUID,
    cycle_id: UUID,
    generation_id: UUID,
    session: DbSession,
    actor: TeamUser,
    registry: runtime.NodePackageRegistryDep,
    plan_service: runtime.ExecutionPlanServiceDep,
    client_factory=Depends(lambda: planner_client),
):
    row, _flow, cycle, spec = await current(session, identity, cycle_id, actor, write=True)
    receipt = await session.get(AdlcCycleOperation, generation_id, populate_existing=True)
    if not receipt or receipt.delivery_id != row.id or receipt.cycle_id != cycle.id or receipt.kind != p.KIND:
        d.fail("CYCLE_GENERATION_NOT_FOUND", 404)
    if receipt.status in {"SUCCEEDED", "FAILED"}:
        return public_operation(receipt)
    remote = receipt.input_snapshot["remote_command"]
    client = client_factory()
    try:
        observed = await client.observe(remote)  # GET only. Never create/retry here.
    finally:
        await client.aclose()
    release_unknown = observed.state in {"FAILED", "CANCELLED"} and not observed.released
    if observed.state in {"RESERVED", "RUNNING", "UNCONFIRMED"} or release_unknown:
        phase = "UNCONFIRMED" if release_unknown else observed.state
        receipt.result = {"phase": phase}
        receipt.status = "UNCONFIRMED" if phase == "UNCONFIRMED" else "RESERVED"
        receipt.updated_at = datetime.now(timezone.utc)
        session.add(receipt)
        await session.commit()
        return public_operation(receipt)
    # Serialize completion against spec edits, competing reconciliations and new graph allocation.
    command = d.DeliveryCommand(expected_revision=row.revision, workflow_digest=spec.payload["workflow_digest"])
    row = await d.lock(session, row, actor, command, spec.payload["workflow_snapshot"])
    await session.refresh(receipt)
    if receipt.status in {"SUCCEEDED", "FAILED"}:
        return public_operation(receipt)
    if receipt.input_snapshot["spec_digest"] != spec.digest or cycle.plan_id:
        d.fail("DELIVERY_CYCLE_SPEC_CHANGED")
    result = {
        "phase": "FAILED",
        "error_code": observed.error_code,
        "usage": observed.usage.model_dump(mode="json") if observed.usage else None,
    }
    if observed.state == "COMPLETED":
        workflow = await verify_baseline(spec)
        try:
            raw = json.loads(observed.proposal_text, object_pairs_hook=_closed_object, parse_constant=_nonfinite)
            proposal, expanded = p.validate_and_expand(
                raw,
                workflow,
                identity=UUID(remote["generation_id"]),
                version=len(await active_operations(session, cycle)),
                owner=str(actor.id),
                limits=p.PlanProposalLimits.model_validate(spec.payload["planning"]["limits"]),
                criteria=spec.payload["acceptance_criteria"],
                registry=registry,
            )
            result.update(
                phase="REVISION_REQUIRED",
                proposal=proposal.model_dump(mode="json"),
                validation_errors=[error.model_dump(mode="json") for error in proposal.validation_errors],
            )
            if expanded:
                version = (
                    await session.exec(
                        select(func.max(AdlcExecutionPlan.plan_version)).where(
                            AdlcExecutionPlan.owner_id == str(actor.id),
                            AdlcExecutionPlan.workflow_definition_id == row.flow_id,
                        )
                    )
                ).one() or 0
                plan = plan_service.compile_snapshot(
                    expanded, owner_id=str(actor.id), generated_by="harness-planner", plan_version=version + 1
                )
                task_by_stage = {
                    str(p.proposal_stage_id(proposal.proposal_id, task.task_id)): task for task in proposal.tasks
                }
                plan = plan.model_copy(
                    update={
                        "approval_required": True,
                        "tasks": [
                            task.model_copy(
                                update={
                                    "planning_rationale": task_by_stage[
                                        str(task.source_workflow_stage_id)
                                    ].planning_rationale,
                                    "metadata": {
                                        **task.metadata,
                                        **task_by_stage[str(task.source_workflow_stage_id)].metadata,
                                        "source_workflow_stage_id": str(
                                            task_by_stage[str(task.source_workflow_stage_id)].source_stage_id
                                        ),
                                        "dependency_keys": task_by_stage[
                                            str(task.source_workflow_stage_id)
                                        ].dependency_task_ids,
                                    },
                                }
                            )
                            for task in plan.tasks
                        ],
                        "metadata": {
                            **plan.metadata,
                            "cycle_id": str(cycle.id),
                            "cycle_spec_digest": spec.digest,
                            "planning_operation_id": str(receipt.id),
                        },
                    }
                )
                result.update(
                    preview_plan=plan.model_dump(mode="json"),
                    plan_digest=d.plan_digest(plan),
                    validation_errors=[error.model_dump(mode="json") for error in plan.validation_errors],
                )
                if plan.validation_status == "VALID":
                    await runtime.archive_execution_plan(
                        session, owner_id=str(actor.id), plan=plan, workflow=expanded, strict=True
                    )
                    result["phase"] = "VALIDATED"
                    previous = next(
                        (
                            op.result.get("preview_plan")
                            for op in await active_operations(session, cycle)
                            if op.id != receipt.id and op.result.get("preview_plan")
                        ),
                        None,
                    )
                    result["diff"] = p.task_diff(ExecutionPlan.model_validate(previous) if previous else None, proposal)
        except (ValueError, ValidationError, RecursionError):
            result.update(
                phase="REVISION_REQUIRED",
                error_code="CYCLE_PROPOSAL_INVALID",
                validation_errors=[
                    {
                        "code": "CYCLE_PROPOSAL_INVALID",
                        "message": "Harness did not return a valid task graph.",
                        "path": "/",
                        "details": {},
                    }
                ],
            )
    receipt.status = "SUCCEEDED" if observed.state == "COMPLETED" else "FAILED"
    receipt.result, receipt.updated_at = result, datetime.now(timezone.utc)
    session.add(receipt)
    await session.commit()
    return public_operation(receipt)


@router.post("/accept")
async def accept_graph(
    identity: UUID,
    cycle_id: UUID,
    command: p.AcceptCommand,
    session: DbSession,
    actor: TeamUser,
    plan_service: runtime.ExecutionPlanServiceDep,
    access: runtime.PackageAccessPolicyDep,
):
    row, _flow, cycle, spec = await current(session, identity, cycle_id, actor, write=True)
    inputs = command.model_dump(mode="json", exclude={"expected_revision", "command_id"})
    old = await duplicate(session, row, cycle, command.command_id, "ACCEPT_GRAPH", inputs)
    if old:
        return {"revision": row.revision, "approved": True}
    require_spec(command, cycle, spec)
    receipt = await session.get(AdlcCycleOperation, command.generation_id, populate_existing=True)
    if (
        not receipt
        or receipt.delivery_id != row.id
        or receipt.cycle_id != cycle.id
        or receipt.kind != p.KIND
        or receipt.status != "SUCCEEDED"
        or receipt.result.get("phase") != "VALIDATED"
        or receipt.input_snapshot["spec_digest"] != spec.digest
        or cycle.plan_id
        or cycle.run_id
        or cycle.dispatch_plan_id
    ):
        d.fail("CYCLE_GRAPH_NOT_ACCEPTABLE")
    operations = await active_operations(session, cycle)
    if any(op.status in {"RESERVED", "UNCONFIRMED"} for op in operations) or operations[0].id != receipt.id:
        d.fail("CYCLE_GRAPH_CHANGED")
    await verify_baseline(spec)
    plan = ExecutionPlan.model_validate(receipt.result["preview_plan"])
    if d.plan_digest(plan) != command.plan_digest or plan.metadata.get("cycle_spec_digest") != spec.digest:
        d.fail("DELIVERY_PLAN_CHANGED")
    archive = await session.get(AdlcExecutionPlan, plan.execution_plan_id, populate_existing=True)
    if not archive or archive.owner_id != str(actor.id) or archive.plan_payload != plan.model_dump(mode="json"):
        d.fail("DELIVERY_PLAN_ARCHIVE_UNAVAILABLE", 503)
    access.ensure_plan_authorized(str(actor.id), plan)  # current grants, not the generation-time grant
    row = await d.lock(session, row, actor, command, spec.payload["workflow_snapshot"])
    workflow = WorkflowDefinition.model_validate(archive.workflow_payload)
    accepted = plan_service.approve_snapshot(
        workflow,
        plan,
        owner_id=str(actor.id),
        approved_by=str(actor.id),
        comment="Reviewed exact selected-cycle task graph",
    )
    if d.plan_digest(accepted) != command.plan_digest:
        d.fail("DELIVERY_PLAN_CHANGED")
    await runtime.archive_execution_plan(session, owner_id=str(actor.id), plan=accepted, workflow=workflow, strict=True)
    stamp = datetime.now(timezone.utc)
    cycle.plan_id, cycle.state = accepted.execution_plan_id, "PLANNING"
    cycle.authority = {
        **cycle.authority,
        "plan_approved_digest": command.plan_digest,
        "plan_approved_by": str(actor.id),
        "plan_approved_at": stamp.isoformat(),
        "cycle_spec_digest": spec.digest,
    }
    cycle.revision += 1
    cycle.updated_at = stamp
    session.add(cycle)
    session.add(
        AdlcCyclePlanRevision(
            cycle_id=cycle.id,
            ordinal=1,
            plan_id=accepted.execution_plan_id,
            plan_digest=command.plan_digest,
            plan_snapshot=accepted.model_dump(mode="json"),
            workflow_snapshot=workflow.model_dump(mode="json"),
            approval=cycle.authority,
        )
    )
    receipt.result = {**receipt.result, "phase": "ACCEPTED", "accepted_at": stamp.isoformat()}
    session.add(receipt)
    approval, _ = await cycles.operation(
        session, row, cycle, actor, "ACCEPT_GRAPH", str(command.command_id), {"command": inputs}
    )
    approval.status, approval.result = (
        "SUCCEEDED",
        {"plan_id": str(accepted.execution_plan_id), "plan_digest": command.plan_digest},
    )
    session.add(approval)
    d.audit(session, row, actor, "cycle_graph_accepted")
    await session.commit()
    plan_service.restore_plan(workflow=workflow, plan=accepted, owner_id=str(actor.id), replace_existing=True)
    return {"revision": row.revision, "approved": True}

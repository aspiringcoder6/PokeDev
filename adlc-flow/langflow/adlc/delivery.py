"""Persistent product navigation, not a second scheduler or permission engine.

Private workspaces use the existing flow authorization and coordinator. Shared
projects retain H7B's independent decisions and may not use this owner adapter.
"""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import update
from sqlmodel import select

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.services.database.models.adlc_delivery import AdlcDelivery
from langflow.services.database.models.auth import AuthzAuditLog

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
MAX_REQUIREMENT_CHARS = 80000


class CreateDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_id: UUID
    title: Annotated[Text, Field(max_length=200)]
    requirement: Annotated[Text, Field(max_length=MAX_REQUIREMENT_CHARS)]


class DeliveryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    workflow_digest: Digest
    command_id: UUID | None = None
    cycle_id: UUID | None = None


class PlanCommand(DeliveryCommand):
    plan_digest: Digest


class NoteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    command_id: UUID
    kind: Literal["CHANGE_REQUEST", "QUESTION", "NOTE"]
    text: Annotated[Text, Field(max_length=4000)]
    cycle_id: UUID | None = None


def fail(code, status=409):
    raise HTTPException(status, {"code": code})


def graph_digest(graph):
    # Canvas positioning and publish counters are not execution semantics.
    # All node inputs, policies, packages, code and edge bindings remain bound.
    return sha256_digest(
        {
            "definition": {
                key: value for key, value in graph.get("adlc", {}).items() if key not in {"version", "status"}
            },
            "nodes": [{key: node.get(key) for key in ("id", "type", "data")} for node in graph.get("nodes", [])],
            "edges": [
                {key: edge.get(key) for key in ("id", "source", "target", "sourceHandle", "targetHandle", "data")}
                for edge in graph.get("edges", [])
            ],
        }
    )


def plan_digest(plan):
    payload = plan.model_dump(mode="json", exclude={"status", "approved_by", "approved_at"})
    payload["metadata"] = {key: value for key, value in payload["metadata"].items() if key != "plan_approval"}
    return sha256_digest(payload)


async def owned(session, identity, actor):
    row = await session.get(AdlcDelivery, identity, populate_existing=True)
    if row is None or row.owner_id != actor.id:
        fail("DELIVERY_NOT_FOUND", 404)
    return row


async def lock(session, row, actor, command, graph):
    if graph_digest(graph) != command.workflow_digest:
        fail("DELIVERY_WORKFLOW_CHANGED")
    result = await session.exec(
        update(AdlcDelivery)
        .where(
            AdlcDelivery.id == row.id,
            AdlcDelivery.owner_id == actor.id,
            AdlcDelivery.revision == command.expected_revision,
        )
        .values(revision=AdlcDelivery.revision + 1, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        fail("DELIVERY_REVISION_CONFLICT")
    return await owned(session, row.id, actor)


def workflow_accepted(row, graph):
    return bool(row.workflow_approved_by and row.workflow_approved_digest == graph_digest(graph))


def require_workflow(row, graph):
    if not workflow_accepted(row, graph):
        fail("DELIVERY_WORKFLOW_APPROVAL_REQUIRED")


def audit(session, row, actor, action):
    session.add(
        AuthzAuditLog(
            user_id=actor.id,
            actor_type="USER",
            actor_id=actor.id,
            action=f"delivery:{action}",
            resource_type="flow",
            resource_id=row.flow_id,
            result="allow",
            details={"delivery_id": str(row.id), "revision": row.revision},
        )
    )


async def ensure_run_authority(session, flow, actor, plan, *, materializing=False, dispatch_key=None):
    row = (await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == flow.id))).first()
    if row is None:
        return
    if row.owner_id != actor.id:
        fail("DELIVERY_NOT_FOUND", 404)
    require_workflow(row, flow.data or {})
    if plan is None or row.plan_id != plan.execution_plan_id or row.plan_approved_digest != plan_digest(plan):
        fail("DELIVERY_PLAN_APPROVAL_REQUIRED")
    if not row.plan_approved_by or plan.status not in {"APPROVED", "EXECUTING"}:
        fail("DELIVERY_PLAN_APPROVAL_REQUIRED")
    from langflow.adlc import delivery_cycles as cycles

    cycle, head = await cycles.initial(session, row)
    if cycle.plan_id != row.plan_id:
        fail("DELIVERY_BINDING_INVALID", 503)
    if materializing and (
        row.dispatch_plan_id != plan.execution_plan_id
        or dispatch_key != f"delivery:{row.id}:{plan.execution_plan_id}"
        or head.execution_cycle_id != cycle.id
        or cycle.dispatch_plan_id != plan.execution_plan_id
    ):
        fail("DELIVERY_USE_WORKSPACE")
    # A successful simulator must never be presented as a delivered application.
    for spec in plan.resolved_node_specs:
        profile = spec.execution_profile
        if "mock" in spec.implementation.adapter_ref.casefold() or (
            profile and (profile.model_ref.startswith("model:mock/") or "mock" in profile.provider_ref.casefold())
        ):
            fail("DELIVERY_MOCK_EXECUTION_NOT_ALLOWED")


def new_note(command, actor):
    return {
        "id": str(command.command_id),
        "kind": command.kind,
        "text": command.text,
        "actor_id": str(actor.id),
        "actor_name": actor.username,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
    }


async def check_runtime_readiness(plan):
    """Reject a known-unavailable Harness loop before reserving dispatch authority."""
    from langflow.adlc.task_loop_harness import (
        HARNESS_CONTRACT_LOOP_SERVICE,
        HARNESS_LOOP_SERVICE,
        HarnessTaskLoopRuntime,
        harness_loop_enabled,
    )
    from langflow.adlc.task_loop_runtime import LoopRuntimeError

    services = {spec.implementation.adapter_ref for spec in plan.resolved_node_specs}
    if not services.intersection({HARNESS_LOOP_SERVICE, HARNESS_CONTRACT_LOOP_SERVICE}):
        return
    if not harness_loop_enabled():
        fail("DELIVERY_HARNESS_LOOP_NOT_READY", 503)
    try:
        runtime = HarnessTaskLoopRuntime.from_environment()
    except ValueError:
        fail("DELIVERY_HARNESS_LOOP_NOT_READY", 503)
    try:
        await runtime.check_readiness()
    except LoopRuntimeError:
        fail("DELIVERY_HARNESS_LOOP_NOT_READY", 503)
    finally:
        await runtime.aclose()

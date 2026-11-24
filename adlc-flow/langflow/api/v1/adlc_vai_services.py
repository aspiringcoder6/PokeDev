"""Explicit-login, owner/cycle scoped service diagnostics for Delivery results."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from langflow.adlc import delivery_cycles as cycles
from langflow.adlc.vai_services import ACTIVE, ServiceCheckError, service_checks
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source
from langflow.api.v1.adlc_team_access import TeamUser

router = APIRouter(prefix="/adlc/deliveries/{identity}/services", tags=["vAI services"])


class CheckCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: UUID
    cycle_id: UUID
    service: Literal["sandbox", "memory", "testforge"]


async def scope(session, identity, cycle_id, actor, *, write=False):
    row, _flow = await source(session, identity, actor, write=write)
    cycle = await cycles.owned_cycle(session, row, cycle_id)
    return str(actor.id), str(row.id), str(cycle.id)


@router.get("")
async def list_checks(identity: UUID, cycle_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    owner, delivery, cycle = await scope(session, identity, cycle_id, actor)
    await session.commit()  # finish SQL authority reads before contacting the remote platform
    service = service_checks()
    rows = service.store.list(owner, delivery, cycle)
    # Restart reconciliation observes known identities; it never repeats the POST.
    for row in rows:
        if row["state"] in ACTIVE:
            service.spawn(row)
    try:
        capabilities = await service.client.capabilities()
        error = None
    except ServiceCheckError as exc:
        capabilities, error = None, exc.code
    return {"capabilities": capabilities, "error_code": error, "checks": rows, "verification_evidence": False}


@router.post("/checks", status_code=202)
async def create_check(identity: UUID, command: CheckCommand, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    owner, delivery, cycle = await scope(session, identity, command.cycle_id, actor, write=True)
    await session.commit()
    service = service_checks()
    try:
        # Readiness failure has no external side effect and does not reserve a create intent.
        capabilities = await service.client.capabilities()
        if capabilities.get("services", {}).get(command.service, {}).get("available") is not True:
            raise ServiceCheckError("VAI_SERVICE_TOOL_UNAVAILABLE", 503)
        row, fresh = service.store.reserve(owner, delivery, cycle, command.service, str(command.check_id))
        service.spawn(row, create=fresh)
        return row
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

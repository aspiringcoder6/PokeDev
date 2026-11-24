"""Authenticated TNQD planning and execution, bound to an owned delivery and cycle."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from langflow.adlc import delivery as d, delivery_cycles as cycles
from langflow.adlc.tnqd_demo import tnqd_service, public_run
from langflow.adlc.vai_services import ServiceCheckError,settings
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source, permission
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction

router = APIRouter(prefix="/adlc/deliveries/{identity}/tnqd-demo", tags=["TNQD Workloop"])
class PlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_id: UUID
    run_id: UUID
class ExecuteCommand(PlanCommand):
    plan_digest: str

async def ensure_agents_stopped(runs):
    ids = {n["session_id"] for row in runs for n in row.get("nodes", []) if n.get("session_id") and not n.get("native_end_at")}
    if not ids:
        return
    from dsh_web_sdk import DshClient, RetryConfig
    base, token = settings()
    try:
        async with DshClient(base, token, timeout=15, retry=RetryConfig(max_attempts=1)) as client:
            active = await client.list_sessions()
        if any(s.get("sessionId") in ids and s.get("running") for s in active):
            raise ServiceCheckError("TNQD_AGENT_STILL_RUNNING")
    except ServiceCheckError:
        raise
    except Exception:
        raise ServiceCheckError("TNQD_AGENT_STATE_UNCONFIRMED") from None

@router.get("")
async def listing(identity: UUID, cycle_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    row, _ = await source(session, identity, actor)
    cycle = await cycles.owned_cycle(session, row, cycle_id)
    await session.commit()
    service = tnqd_service()
    return {"runs": [public_run(service.observe(r)) for r in service.store.list(str(actor.id), str(identity), str(cycle.id))]}

@router.post("/plan", status_code=202)
async def plan(identity: UUID, command: PlanCommand, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    row, flow = await source(session, identity, actor, write=True)
    cycle = await cycles.owned_cycle(session, row, command.cycle_id)
    if not await permission(actor, flow, FlowAction.EXECUTE):
        d.fail("TNQD_EXECUTION_DENIED", 403)
    await session.commit()
    service = tnqd_service()
    try:
        value, fresh = service.store.create(str(actor.id), str(identity), str(cycle.id), str(command.run_id), row.requirement)
        if fresh:
            service.spawn(value)
        return public_run(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

@router.post("/resume",status_code=202)
async def resume(identity:UUID,command:PlanCommand,session:DbSession,actor:TeamUser,response:Response):
    response.headers["Cache-Control"]="no-store"
    row,flow=await source(session,identity,actor,write=True)
    cycle=await cycles.owned_cycle(session,row,command.cycle_id)
    if not await permission(actor,flow,FlowAction.EXECUTE):d.fail("TNQD_EXECUTION_DENIED",403)
    await session.commit()
    service=tnqd_service()
    try:
        value=service.observe(service.store.get(str(actor.id),str(identity),str(cycle.id),str(command.run_id)))
        if value["run_id"] in service.tasks:return public_run(value)
        if value["state"] not in {"FAILED","UNCONFIRMED"}:raise ServiceCheckError("TNQD_RESUME_STATE_INVALID")
        # An orphaned remote agent may still be writing. Never start a duplicate.
        ids={n["session_id"] for n in value.get("nodes",[]) if n.get("session_id") and not n.get("native_end_at")}
        if ids:
            from dsh_web_sdk import DshClient,RetryConfig
            base,token=settings()
            try:
                async with DshClient(base,token,retry=RetryConfig(max_attempts=1)) as client:
                    active=await client.list_sessions()
                if any(s.get("sessionId") in ids and s.get("running") for s in active):raise ServiceCheckError("TNQD_AGENT_STILL_RUNNING")
            except ServiceCheckError:raise
            except Exception:raise ServiceCheckError("TNQD_AGENT_STATE_UNCONFIRMED") from None
        value=service.store.update(value["run_id"],{"state":"PLANNING" if value["phase"]=="planning" else "RUNNING","error_code":None,"resume_count":value.get("resume_count",0)+1})
        service.spawn(value,resume=True)
        return public_run(value)
    except ServiceCheckError as exc:raise HTTPException(exc.status,{"code":exc.code}) from None

@router.post("/execute", status_code=202)
async def execute(identity: UUID, command: ExecuteCommand, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    row, flow = await source(session, identity, actor, write=True)
    cycle = await cycles.owned_cycle(session, row, command.cycle_id)
    if not await permission(actor, flow, FlowAction.EXECUTE):
        d.fail("TNQD_EXECUTION_DENIED", 403)
    await session.commit()
    service = tnqd_service()
    try:
        value = service.observe(service.store.get(str(actor.id), str(identity), str(cycle.id), str(command.run_id)))
        if value["phase"] == "execution":
            if value.get("approved_plan_digest") != command.plan_digest:
                raise ServiceCheckError("TNQD_PLAN_CHANGED")
            return public_run(value)
        if value["state"] != "PLAN_READY" or value.get("plan", {}).get("digest") != command.plan_digest:
            raise ServiceCheckError("TNQD_PLAN_NOT_READY_OR_CHANGED")
        if value["run_id"] in service.tasks:
            raise ServiceCheckError("TNQD_PLANNING_DRAINING")
        value = service.store.update(value["run_id"], {"state": "RUNNING", "phase": "execution",
            "approved_plan_digest": command.plan_digest, "approved_by": str(actor.id), "planning_nodes": value["nodes"],
            "nodes": [], "events": [], "error_code": None})
        service.spawn(value)
        return public_run(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

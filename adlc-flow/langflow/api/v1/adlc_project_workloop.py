"""All Workloop access is authorized locally before contacting shared services."""
from uuid import UUID
import asyncio
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.live_workflows import live_service
from langflow.adlc.project_workloop import workloop_service, job_summary
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction, ensure_flow_permission

router = APIRouter(tags=["Project Workloop"])


@router.get("/workloop/attention")
async def attention(session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    service, owner = workloop_service(), str(actor.id)
    allowed = []
    for project in service.projects(owner):
        try:
            await authorize_project(live_service(), session, actor, project)
            allowed.append(project)
        except ServiceCheckError as exc:
            if exc.status not in {403, 404}:
                raise HTTPException(exc.status, {"code": exc.code}) from None
    await session.commit()
    results = await asyncio.gather(*(service.index(owner, project) for project in allowed))
    items = [row for result in results for row in result["items"]]
    return {"items": [{k: row.get(k) for k in ("job_id", "project_id", "title", "workflow", "state", "checked_at", "stale", "requests")} for row in items],
            "partial": any(row.get("stale") for row in items)}


async def authorized(project_id, session, actor, write=False):
    project = await authorize_project(live_service(), session, actor, str(project_id), write=write)
    if write:
        await ensure_flow_permission(actor, FlowAction.EXECUTE, folder_id=project_id, flow_user_id=actor.id)
    await session.commit()
    return project


class LinkCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(pattern=r"^job-[a-zA-Z0-9-]{1,80}$")
    title: str = Field(min_length=1, max_length=200)
    confirm_repository: str = Field(min_length=1, max_length=300)


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    action: str = Field(pattern="^(PAUSE|STOP|RESUME|ANSWER)$")
    request_id: str | None = Field(default=None, max_length=200)
    source_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    response: dict | None = None


@router.get("/projects/{project_id}/workloop/candidates")
async def candidates(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        await authorized(project_id, session, actor)
        if not actor.is_superuser:
            raise ServiceCheckError("WORKLOOP_LINK_ADMIN_REQUIRED", 403)
        service = workloop_service()
        raw = await service.client.request("GET", "/monitor/jobs?limit=100")
        return {"items": [job_summary(j) for j in raw.get("jobs", [])], "limit": 100}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/projects/{project_id}/workloop/links")
async def link(project_id: UUID, command: LinkCommand, session: DbSession, actor: TeamUser):
    try:
        project = await authorized(project_id, session, actor, write=True)
        if not actor.is_superuser:
            raise ServiceCheckError("WORKLOOP_LINK_ADMIN_REQUIRED", 403)
        if command.confirm_repository != project["repository"]:
            raise ServiceCheckError("WORKLOOP_PROJECT_CONFIRMATION_REQUIRED", 422)
        return await workloop_service().bind(str(actor.id), project, command.job_id, command.title)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/projects/{project_id}/workloop/jobs")
async def jobs(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        await authorized(project_id, session, actor)
        return await workloop_service().index(str(actor.id), str(project_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/projects/{project_id}/workloop/jobs/{job_id}")
async def job(project_id: UUID, job_id: str, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        await authorized(project_id, session, actor)
        return await workloop_service().read(str(actor.id), str(project_id), job_id)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/projects/{project_id}/workloop/jobs/{job_id}/reports")
async def reports(project_id: UUID, job_id: str, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        await authorized(project_id, session, actor)
        return await workloop_service().reports(str(actor.id), str(project_id), job_id)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/projects/{project_id}/workloop/jobs/{job_id}/commands")
async def command_job(project_id: UUID, job_id: str, command: JobCommand, session: DbSession, actor: TeamUser):
    try:
        await authorized(project_id, session, actor, write=True)
        return await workloop_service().command(str(actor.id), str(project_id), job_id, str(command.command_id), command.action, command.request_id, command.source_digest, command.response)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

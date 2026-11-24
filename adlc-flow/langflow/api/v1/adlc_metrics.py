"""Project evidence, owned-session usage and explicit user pricing."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.live_workflows import live_service
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_team_access import TeamUser

router = APIRouter(prefix="/projects", tags=["Project metrics"])


class PricingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    rates: list[dict] = Field(max_length=10)


@router.get("/{project_id}/metrics")
async def project_metrics(project_id: UUID, session: DbSession, actor: TeamUser, response: Response, days: int = Query(default=30, ge=1, le=90)):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        await session.commit()
        service.metrics.schedule(str(actor.id), str(project_id))
        return service.metrics.summary(str(actor.id), str(project_id), days)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/metrics/refresh", status_code=202)
async def refresh_metrics(project_id: UUID, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        await session.commit()
        service.metrics.schedule(str(actor.id), str(project_id), force=True)
        return {"scheduled": True}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.put("/{project_id}/metrics/pricing")
async def save_pricing(project_id: UUID, command: PricingCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        return service.metrics.save_pricing(str(actor.id), str(project_id), command.expected_revision, command.rates)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

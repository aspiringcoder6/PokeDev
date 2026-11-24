"""Project environment, recovery and PR operations using the normal project/flow permissions."""
from uuid import UUID
import asyncio

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.live_workflows import live_service, public_run
from langflow.adlc.project_environment import public_environment
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source, permission
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction

router = APIRouter(tags=["Project environment, recovery and handover"])


@router.get("/projects/{project_id}/files")
async def project_files(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        from langflow.adlc.project_source import project_file_index
        service = live_service()
        project = await authorize_project(service, session, actor, str(project_id))
        await session.commit()
        return await asyncio.to_thread(project_file_index, project)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


class EnvironmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=0)
    profile: dict


class EnvironmentCheckCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: UUID
    environment_digest: str = Field(pattern="^[a-f0-9]{64}$")


class RecoveryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    expected_generation: int = Field(default=0, strict=True, ge=0, le=1000)
    plan_digest: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")


class PullCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    head_commit: str = Field(pattern="^[a-f0-9]{40}(?:[a-f0-9]{24})?$")


class MergeCommand(PullCommand):
    base_commit: str = Field(pattern="^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
    accept_no_ci: bool = False
    close_issue: bool = False


async def authorized_run(service, session, actor, identity, *, write=False):
    row = service.store.get(str(actor.id), str(identity))
    _, flow = await source(session, UUID(row["delivery_id"]), actor, write=write)
    if write and not await permission(actor, flow, FlowAction.EXECUTE):
        raise ServiceCheckError("LIVE_EXECUTION_DENIED", 403)
    await session.commit()
    return row


@router.get("/projects/{project_id}/environment")
async def environment(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        return {**public_environment(service.environments.read(str(actor.id), str(project_id))), "last_check": service.environments.latest_check(str(actor.id), str(project_id))}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.put("/projects/{project_id}/environment")
async def save_environment(project_id: UUID, command: EnvironmentCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        await session.commit()
        return await service.environments.save(str(actor.id), str(project_id), command.expected_revision, command.profile)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/projects/{project_id}/environment/checks", status_code=202)
async def check_environment(project_id: UUID, command: EnvironmentCheckCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        from langflow.services.authorization import ensure_flow_permission
        await ensure_flow_permission(actor, FlowAction.EXECUTE, folder_id=project_id, flow_user_id=actor.id)
        await session.commit()
        return await service.environments.begin_check(str(actor.id), str(project_id), str(command.check_id), command.environment_digest)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/projects/{project_id}/environment/checks/{check_id}")
async def read_environment_check(project_id: UUID, check_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        await session.commit()
        return await service.environments.refresh_check(str(actor.id), str(project_id), str(check_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/recover", status_code=202)
async def recover_run(identity: UUID, command: RecoveryCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorized_run(service, session, actor, identity, write=True)
        return public_run(await service.recovery.resume(str(actor.id), str(identity), str(command.command_id), command.expected_generation, command.plan_digest))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/runs/{identity}/handover")
async def read_handover(identity: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorized_run(service, session, actor, identity)
        return await service.handover.refresh(str(actor.id), str(identity))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/recovery/stop")
async def stop_interrupted_run(identity: UUID, command: RecoveryCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorized_run(service, session, actor, identity, write=True)
        return public_run(await service.recovery.stop(str(actor.id), str(identity), str(command.command_id), command.expected_generation))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/runs/{identity}/handover/preview")
async def preview_handover(identity: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        row = await authorized_run(service, session, actor, identity)
        if row["state"] != "SUCCEEDED" or not row.get("published"):
            raise ServiceCheckError("LIVE_PR_VERIFIED_BRANCH_REQUIRED")
        return {"title": row["title"], "body": service.handover.description(row)}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/handover/pull-request", status_code=201)
async def create_pull_request(identity: UUID, command: PullCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorized_run(service, session, actor, identity, write=True)
        return await service.handover.create(str(actor.id), str(identity), command.head_commit, str(command.command_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/handover/merge")
async def merge_pull_request(identity: UUID, command: MergeCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorized_run(service, session, actor, identity, write=True)
        return await service.handover.merge(str(actor.id), str(identity), str(command.command_id), command.head_commit, command.base_commit, accept_no_ci=command.accept_no_ci, close_issue=command.close_issue)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

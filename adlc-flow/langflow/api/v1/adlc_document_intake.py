"""Owned project inbox for documents produced by the existing Slack bot."""

import asyncio
from uuid import UUID
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.document_intake import document_intake, public_document, start_document_plan
from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.live_workflows import live_service, public_run
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction, ensure_flow_permission

router = APIRouter(tags=["Slack document intake"])


class AssignDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    instructions: str = Field(default="", max_length=16000)
    automatic_channel: bool = False
    share_progress: bool | None = None


class ProgressCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.post("/intake/{document_id}/notifications", status_code=202)
async def document_notifications(document_id: int, command: ProgressCommand, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        if not getattr(actor, "is_superuser", False):
            raise ServiceCheckError("WORKSPACE_INTEGRATION_ADMIN_REQUIRED", 403)
        await access(service.get(owner, document_id), session, actor, write=True)
        result = service.notifications.configure(owner, document_id, command.enabled)
        service.progress.wake.set()
        return public_document(result)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


class DecideDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: str = Field(pattern="^(approve|reject)$")


class ReviseDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: UUID
    feedback: str = Field(min_length=10, max_length=6000)


@router.post("/intake/{document_id}/revision", status_code=202)
async def revise_document(document_id: int, command: ReviseDocument, session: DbSession, actor: TeamUser):
    from langflow.adlc.document_revision import request_revision

    try:
        service, owner = document_intake(), str(actor.id)
        source = service.get(owner, document_id)
        await access(source, session, actor, write=True, execute=bool(source.get("project_id")))
        row = await request_revision(
            service, owner, document_id, command.digest, command.request_id, command.feedback.strip()
        )
        return public_document(row)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


class DocumentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    command_id: UUID
    workflow_id: UUID | None = None
    workflow_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CheckRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    invocation_id: str | None = Field(default=None, pattern=r"^ag-[A-Za-z0-9-]{1,100}$")


@router.post("/intake/{document_id}/revision/check")
async def check_document_revision(document_id: int, command: CheckRevision, session: DbSession, actor: TeamUser):
    from langflow.adlc.document_revision import check_revision

    try:
        service, owner = document_intake(), str(actor.id)
        source = service.get(owner, document_id)
        await access(source, session, actor, write=True, execute=bool(source.get("project_id")))
        row = await check_revision(service, owner, document_id, str(command.request_id), command.invocation_id)
        service.progress.wake.set()
        return public_document(row)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


async def access(row, session, actor, *, write=False, execute=False):
    if not row.get("project_id"):
        if not actor.is_superuser or execute:
            raise ServiceCheckError("INTAKE_PROJECT_REQUIRED", 403)
        await session.commit()
        return
    await authorize_project(live_service(), session, actor, row["project_id"], write=write)
    if execute:
        await ensure_flow_permission(
            actor, FlowAction.EXECUTE, folder_id=UUID(row["project_id"]), flow_user_id=actor.id
        )
    await session.commit()


@router.get("/intake")
async def inbox(
    session: DbSession, actor: TeamUser, response: Response, project_id: UUID | None = None, include_archived: bool = False
):
    response.headers["Cache-Control"] = "no-store"
    service, live, owner = document_intake(), live_service(), str(actor.id)
    try:
        if project_id:
            await authorize_project(live, session, actor, str(project_id))
        await session.commit()
        source = await service.sync(owner) if actor.is_superuser else {"stale": False}
        allowed = set()
        rows = service.rows(owner, str(project_id) if project_id else None, include_archived=include_archived)
        rules = [r for r in service.rules(owner) if not project_id or r["project_id"] == str(project_id)]
        projects = {r.get("project_id") for r in [*rows, *rules] if r.get("project_id")}
        for project in projects:
            try:
                await authorize_project(live, session, actor, project)
                allowed.add(project)
            except (ServiceCheckError, HTTPException) as exc:
                if getattr(exc, "status", getattr(exc, "status_code", 0)) not in {403, 404}:
                    raise
        await session.commit()
        items = [
            public_document(r)
            for r in rows
            if r.get("project_id") in allowed or (not r.get("project_id") and actor.is_superuser)
        ]
        for item in items:
            if item.get("run_id"):
                try:
                    run = live.observe(live.store.get(owner, item["run_id"]))
                    item["run_state"] = run["state"]
                except ServiceCheckError:
                    item["run_state"] = "UNAVAILABLE"
        rules = [r for r in rules if r["project_id"] in allowed]
        return {**source, "items": items, "rules": rules, "can_manage": actor.is_superuser, "bot_url": service.bot_url}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/intake/{document_id}")
async def read_document(document_id: int, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service, owner = document_intake(), str(actor.id)
        row = service.get(owner, document_id, include_archived=True)
        await access(row, session, actor)
        if row.get("archived_at"):
            return {**public_document(row, body=True), "stale": False}
        try:
            row = await service.refresh(owner, document_id)
        except ServiceCheckError as exc:
            return {
                **public_document(service.get(owner, document_id), body=True),
                "stale": True,
                "error_code": exc.code,
            }
        return {**public_document(row, body=True), "digest": service.contract_digest(row), "stale": False}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.delete("/intake/{document_id}")
async def archive_document(document_id: int, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        row = service.get(owner, document_id, include_archived=True)
        await access(row, session, actor, write=True)
        completed_run = None
        if row.get("run_id") and not row.get("archived_at"):
            run = live_service().observe(live_service().store.get(owner, row["run_id"]))
            if run["state"] not in {"SUCCEEDED", "FAILED"}:
                raise ServiceCheckError("INTAKE_ARCHIVE_ACTIVE", 409)
            completed_run = row["run_id"]
        result = service.archive(owner, document_id, completed_run=completed_run)
        service.progress.wake.set()
        return public_document(result)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/intake/{document_id}/restore")
async def restore_document(document_id: int, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        await access(service.get(owner, document_id, include_archived=True), session, actor, write=True)
        return public_document(service.restore(owner, document_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.put("/intake/{document_id}/project")
async def assign_document(document_id: int, command: AssignDocument, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        row = service.get(owner, document_id)
        await access(row, session, actor, write=True)
        if command.automatic_channel and not actor.is_superuser:
            raise ServiceCheckError("WORKSPACE_INTEGRATION_ADMIN_REQUIRED", 403)
        if (
            command.share_progress is not None
            and command.share_progress != bool(row.get("progress", {}).get("enabled"))
            and not actor.is_superuser
        ):
            raise ServiceCheckError("WORKSPACE_INTEGRATION_ADMIN_REQUIRED", 403)
        project = await authorize_project(live_service(), session, actor, str(command.project_id), write=True)
        await session.commit()
        return public_document(
            service.assign(
                owner, document_id, project, command.instructions, command.automatic_channel, command.share_progress
            )
        )
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/intake/{document_id}/progress", status_code=202)
async def progress_document(document_id: int, command: ProgressCommand, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        await access(service.get(owner, document_id), session, actor, write=True)
        if not actor.is_superuser:
            raise ServiceCheckError("WORKSPACE_INTEGRATION_ADMIN_REQUIRED", 403)
        return public_document(service.progress.configure(owner, document_id, command.enabled))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/intake/{document_id}/decision")
async def decide_document(document_id: int, command: DecideDocument, session: DbSession, actor: TeamUser):
    try:
        service, owner = document_intake(), str(actor.id)
        row = service.get(owner, document_id)
        await access(row, session, actor, write=True)
        if not row.get("project_id"):
            raise ServiceCheckError("INTAKE_PROJECT_REQUIRED", 409)
        if (await service.sync(owner, force=True)).get("stale"):
            raise ServiceCheckError("INTAKE_SYNC_UNAVAILABLE", 503)
        await service.validate_source(owner, document_id)
        return public_document(await service.decide(owner, document_id, command.digest, command.decision))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/intake/{document_id}/plan", status_code=202)
async def plan_document(document_id: int, command: DocumentPlan, session: DbSession, actor: TeamUser):
    try:
        service, live, owner = document_intake(), live_service(), str(actor.id)
        row = service.get(owner, document_id)
        await access(row, session, actor, write=True, execute=True)
        if bool(command.workflow_id) != bool(command.workflow_digest):
            raise ServiceCheckError("LIVE_WORKFLOW_DIGEST_REQUIRED", 422)
        if command.workflow_id:
            workflow = live.store.workflow(owner, str(command.workflow_id))
            if workflow["project_id"] != row["project_id"] or workflow["digest"] != command.workflow_digest:
                raise ServiceCheckError("LIVE_WORKFLOW_PROJECT_MISMATCH", 409)
        if (await service.sync(owner, force=True)).get("stale"):
            raise ServiceCheckError("INTAKE_SYNC_UNAVAILABLE", 503)
        await service.validate_source(owner, document_id)
        async with service.locks.setdefault("start:" + owner + ":" + str(document_id), asyncio.Lock()):
            row = service.get(owner, document_id)
            allow_revision = False
            if row.get("run_id"):
                try:
                    previous = live.observe(live.store.get(owner, row["run_id"]))
                    allow_revision = previous["state"] in {"SUCCEEDED", "FAILED"}
                except ServiceCheckError as exc:
                    if exc.status != 404:
                        raise
            row = await service.reserve(
                owner,
                document_id,
                command.digest,
                str(command.command_id),
                str(command.workflow_id) if command.workflow_id else None,
                command.workflow_digest,
                allow_revision=allow_revision,
            )
            try:
                return public_run(await start_document_plan(live, service, row, session, actor))
            except (ServiceCheckError, HTTPException) as exc:
                service.command_result(
                    owner,
                    document_id,
                    str(command.command_id),
                    state="RETRYABLE",
                    error_code=getattr(exc, "code", "INTAKE_START_FAILED"),
                )
                raise
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.delete("/intake/{document_id}/plan")
async def clear_reservation(document_id: int, session: DbSession, actor: TeamUser):
    try:
        service, live, owner = document_intake(), live_service(), str(actor.id)
        await access(service.get(owner, document_id), session, actor, write=True, execute=True)
        async with service.locks.setdefault("start:" + owner + ":" + str(document_id), asyncio.Lock()):

            def clear(row):
                if row.get("run_id"):
                    try:
                        live.store.get(owner, row["run_id"])
                    except ServiceCheckError as exc:
                        if exc.status != 404:
                            raise
                    else:
                        raise ServiceCheckError("INTAKE_RUN_ALREADY_EXISTS", 409)
                for key in ("command", "execution_snapshot", "run_id", "flow_id", "run_started_at"):
                    row.pop(key, None)

            return public_document(service.change(owner, document_id, clear))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.delete("/intake/channels/{channel}")
async def remove_channel(channel: str, session: DbSession, actor: TeamUser):
    if not actor.is_superuser:
        raise HTTPException(403, {"code": "WORKSPACE_INTEGRATION_ADMIN_REQUIRED"})
    await session.commit()
    service = document_intake()
    with service.db() as db, db:
        db.execute("DELETE FROM intake_channels WHERE owner=? AND channel=?", (str(actor.id), channel))
    return {"removed": True}

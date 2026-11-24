"""Project-scoped issue inbox and explicit delegation of automatic execution."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.issue_store import public_proposal
from langflow.adlc.issue_policy import AUTOMATIC_MODES, POLICY_DEFAULTS
from langflow.adlc.live_workflows import live_service
from langflow.adlc.project_workflows import workflow_snapshot
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_team_access import TeamUser

router = APIRouter(prefix="/projects", tags=["Project issues and automation"])


class IssueSettingsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    watch_issues: bool
    mode: str = Field(pattern="^(review|auto|risk)$")
    labels: list[str] = Field(default_factory=list, max_length=20)
    workflow_id: UUID | None = None
    auto_confirmed: bool = False
    auto_allowed_paths: list[str] = Field(
        default_factory=lambda: list(POLICY_DEFAULTS["auto_allowed_paths"]), max_length=20
    )
    auto_max_runs_per_day: int = Field(default=3, strict=True, ge=1, le=50)
    auto_max_active_minutes: int = Field(default=20, strict=True, ge=5, le=60)


class ProposalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_digest: str = Field(pattern="^[a-f0-9]{64}$")


class ClarificationCommand(ProposalCommand):
    answers: dict[str, str]
    approach: str = Field(default="implement", pattern="^(implement|spec_first)$")


@router.get("/{project_id}/settings")
async def get_issue_settings(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        return service.issue_service.store.settings(str(actor.id), str(project_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.put("/{project_id}/settings")
async def set_issue_settings(project_id: UUID, command: IssueSettingsCommand, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        if command.workflow_id:
            workflow = service.store.workflow(str(actor.id), str(command.workflow_id))
            if workflow["project_id"] != str(project_id):
                raise ServiceCheckError("LIVE_WORKFLOW_PROJECT_MISMATCH")
            try:
                workflow_snapshot(workflow)
            except ValueError as exc:
                raise ServiceCheckError(str(exc), 422) from None
        if command.watch_issues and command.mode in AUTOMATIC_MODES:
            from langflow.services.authorization import FlowAction, ensure_flow_permission

            await ensure_flow_permission(actor, FlowAction.CREATE, folder_id=project_id, flow_user_id=actor.id)
            await ensure_flow_permission(actor, FlowAction.EXECUTE, folder_id=project_id, flow_user_id=actor.id)
        value = service.issue_service.store.save_settings(
            str(actor.id),
            str(project_id),
            expected_revision=command.expected_revision,
            watch_issues=command.watch_issues,
            mode=command.mode,
            labels=command.labels,
            workflow_id=str(command.workflow_id) if command.workflow_id else None,
            auto_confirmed=command.auto_confirmed,
            auto_allowed_paths=command.auto_allowed_paths,
            auto_max_runs_per_day=command.auto_max_runs_per_day,
            auto_max_active_minutes=command.auto_max_active_minutes,
        )
        service.issue_service.last_scan.pop(str(project_id), None)
        return value
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/{project_id}/issues")
async def get_project_issues(project_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        return service.issue_service.list(str(actor.id), str(project_id))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/issues/scan")
async def scan_project_issues(project_id: UUID, session: DbSession, actor: TeamUser):
    try:
        service = live_service()
        project = await authorize_project(service, session, actor, str(project_id))
        await session.commit()
        return await service.issue_service.scan(project)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/issues/{proposal_id}/plan", status_code=202)
async def plan_issue(
    project_id: UUID, proposal_id: UUID, command: ProposalCommand, session: DbSession, actor: TeamUser
):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        await session.commit()
        return await service.issue_service.prepare(
            str(actor.id), str(project_id), str(proposal_id), command.source_digest
        )
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/issues/{proposal_id}/clarification")
async def clarify_issue(
    project_id: UUID, proposal_id: UUID, command: ClarificationCommand, session: DbSession, actor: TeamUser
):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        await session.commit()
        return await service.issue_service.clarify(
            str(actor.id), str(project_id), str(proposal_id), command.source_digest, command.answers, command.approach
        )
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/{project_id}/issues/{proposal_id}/audit")
async def issue_audit(project_id: UUID, proposal_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id))
        return {"items": service.issue_service.store.audit(str(actor.id), str(project_id), str(proposal_id))}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/issues/{proposal_id}/ignore")
async def ignore_issue(
    project_id: UUID, proposal_id: UUID, command: ProposalCommand, session: DbSession, actor: TeamUser
):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        return public_proposal(
            service.issue_service.store.ignore(str(actor.id), str(project_id), str(proposal_id), command.source_digest)
        )
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/{project_id}/issues/{proposal_id}/restore")
async def restore_issue(
    project_id: UUID, proposal_id: UUID, command: ProposalCommand, session: DbSession, actor: TeamUser
):
    try:
        service = live_service()
        await authorize_project(service, session, actor, str(project_id), write=True)
        return public_proposal(
            service.issue_service.store.ignore(
                str(actor.id), str(project_id), str(proposal_id), command.source_digest, restore=True
            )
        )
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

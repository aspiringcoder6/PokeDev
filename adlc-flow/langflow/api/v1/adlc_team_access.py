"""Authenticated project administration. No shared workflow execution in H7A."""

from datetime import timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from langflow.api.utils import DbSession
from langflow.services.authorization import team_access as service
from langflow.services.authorization.team_catalog import VERSION
from langflow.services.database.models.auth import AuthzAuditLog
from langflow.services.database.models.user.model import User
from langflow.services.deps import get_auth_service, get_authorization_service, get_settings_service

router = APIRouter(prefix="/adlc/team-access", tags=["ADLC team access"])


async def explicit_team_user(request: Request, session: DbSession):
    if get_settings_service().auth_settings.AUTO_LOGIN:
        raise HTTPException(status_code=403, detail={"code": "TEAM_EXPLICIT_LOGIN_REQUIRED"})
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else request.cookies.get("access_token_lf")
    if not token:
        raise HTTPException(status_code=401, detail={"code": "TEAM_USER_TOKEN_REQUIRED"})
    try:
        auth = get_auth_service()
        user = await auth.get_current_active_user(await auth.get_current_user_from_access_token(token, session))
    except Exception:  # noqa: BLE001 - never expose credential/transport exceptions.
        raise HTTPException(status_code=401, detail={"code": "TEAM_USER_TOKEN_INVALID"}) from None
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "TEAM_USER_TOKEN_INVALID"})
    if getattr(get_authorization_service(), "TEAM_POLICY_VERSION", None) != VERSION:
        raise HTTPException(status_code=503, detail={"code": "TEAM_ENFORCEMENT_PROVIDER_REQUIRED"})
    return user


TeamUser = Annotated[object, Depends(explicit_team_user)]


class ProjectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=80)


async def checked(session, operation, *, actor=None, project_id=None, action=None):
    actor_id = actor.id if actor is not None else None
    try:
        return await operation
    except service.TeamAccessError as exc:
        await session.rollback()
        if actor_id is not None and action is not None:
            try:
                session.add(
                    AuthzAuditLog(
                        user_id=actor_id,
                        actor_type="USER",
                        actor_id=actor_id,
                        action="team_access:denied",
                        resource_type="project",
                        resource_id=project_id,
                        result="deny",
                        details={"reason": exc.code, "requested_action": action},
                    )
                )
                await session.commit()
            except Exception:  # noqa: BLE001 - a failed audit cannot open the protected action.
                await session.rollback()
                raise HTTPException(status_code=503, detail={"code": "TEAM_POLICY_STORE_UNAVAILABLE"}) from None
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": "TEAM_WRITE_CONFLICT"}) from None
    except Exception:  # noqa: BLE001 - fail closed and roll back the complete administrative transaction.
        await session.rollback()
        raise HTTPException(status_code=503, detail={"code": "TEAM_POLICY_STORE_UNAVAILABLE"}) from None


@router.get("/projects")
async def projects(session: DbSession, user: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {
        "phase": "H7A",
        "can_create": bool(user.is_superuser),
        "projects": await checked(session, service.visible_projects(session, user)),
    }


@router.post("/projects", status_code=201)
async def create_project(command: ProjectCommand, session: DbSession, user: TeamUser):
    async def operation():
        project_id = await service.create_project(session, user, command.name)
        await service.commit(session)
        return await service.project_view(session, project_id, user)

    return await checked(session, operation(), actor=user, action="project:create")


@router.get("/projects/{project_id}")
async def read_project(project_id: UUID, session: DbSession, user: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await checked(session, service.project_view(session, project_id, user))


@router.put("/projects/{project_id}/policy")
async def update_policy(project_id: UUID, command: service.PolicyCommand, session: DbSession, user: TeamUser):
    async def operation():
        await service.update_policy(session, project_id, user, command)
        await service.commit(session)
        return {"revision": command.expected_revision + 1}

    return await checked(session, operation(), actor=user, project_id=project_id, action="policy:manage")


@router.put("/projects/{project_id}/members")
async def set_member(project_id: UUID, command: service.MemberCommand, session: DbSession, user: TeamUser):
    async def operation():
        await service.set_member(session, project_id, user, command)
        await service.commit(session)
        return {"revision": command.expected_revision + 1}

    return await checked(session, operation(), actor=user, project_id=project_id, action="membership:manage")


@router.post("/projects/{project_id}/members/{subject_id}/revoke")
async def revoke_member(
    project_id: UUID, subject_id: UUID, command: service.RevisionCommand, session: DbSession, user: TeamUser
):
    async def operation():
        await service.remove_member(session, project_id, user, subject_id, command)
        await service.commit(session)
        # A user can remove themself when another active Admin exists.
        return {"revoked": True, "revision": command.expected_revision + 1}

    return await checked(session, operation(), actor=user, project_id=project_id, action="membership:manage")


@router.get("/projects/{project_id}/effective/{subject_id}")
async def member_effective(project_id: UUID, subject_id: UUID, session: DbSession, user: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"

    async def operation():
        row = await service.require_permission(
            session, project_id, user, "policy:read" if subject_id == user.id else "membership:manage"
        )
        return await service.effective(session, row, subject_id)

    return await checked(session, operation())


@router.get("/projects/{project_id}/audit")
async def audit(project_id: UUID, session: DbSession, user: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"

    async def operation():
        await service.require_permission(session, project_id, user, "audit:read")
        rows = (
            await session.exec(
                select(AuthzAuditLog, User.username)
                .outerjoin(User, User.id == AuthzAuditLog.actor_id)
                .where(
                    AuthzAuditLog.resource_type == "project",
                    AuthzAuditLog.resource_id == project_id,
                    AuthzAuditLog.action.startswith("team_access:"),
                )
                .order_by(AuthzAuditLog.timestamp.desc(), AuthzAuditLog.id)
                .limit(100)
            )
        ).all()
        return [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "actor_username": username,
                "action": row.action,
                "details": row.details,
                "occurred_at": row.timestamp if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=timezone.utc),
            }
            for row, username in rows
        ]

    return await checked(session, operation())

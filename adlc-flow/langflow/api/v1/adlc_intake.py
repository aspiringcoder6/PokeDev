"""Authenticated, owner-private requirement intake; no agent/execution side effects."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError

from langflow.adlc import intake
from langflow.adlc.intake_models import CancelIntake, CreateIntake, UpdateIntake
from langflow.api.utils import CurrentActiveUser, DbSession


async def intake_actor(user: CurrentActiveUser) -> intake.IntakeActor:
    return intake.IntakeActor(id=user.id)


CurrentIntakeActor = Annotated[intake.IntakeActor, Depends(intake_actor)]


async def require_enabled():
    if not intake.enabled():
        raise HTTPException(status_code=404, detail={"code": "INTAKE_DISABLED"}, headers={"Cache-Control": "no-store"})


router = APIRouter(prefix="/adlc/intake", tags=["Requirement intake"], dependencies=[Depends(require_enabled)])


async def read(operation, session, response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await operation
    except intake.IntakeError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=exc.status, detail={"code": exc.code}, headers={"Cache-Control": "no-store"}
        ) from None


async def write(operation, session, response):
    response.headers["Cache-Control"] = "no-store"
    for attempt in range(2):
        try:
            result = await operation()
            await session.commit()
            return result
        except (IntegrityError, intake.IntakeError) as exc:
            await session.rollback()
            # A concurrent retry may have committed this exact command. Replay
            # only after ending the old transaction; conflicting input stays 409.
            if attempt == 0 and (isinstance(exc, IntegrityError) or exc.code == "INTAKE_REVISION_CONFLICT"):
                continue
            code, status = (
                (exc.code, exc.status) if isinstance(exc, intake.IntakeError) else ("INTAKE_WRITE_CONFLICT", 409)
            )
            raise HTTPException(
                status_code=status, detail={"code": code}, headers={"Cache-Control": "no-store"}
            ) from None


@router.get("/projects")
async def projects(session: DbSession, user: CurrentIntakeActor, response: Response):
    return await read(intake.projects(session, user), session, response)


@router.get("/requests")
async def listing(
    session: DbSession,
    user: CurrentIntakeActor,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await read(intake.listing(session, user, limit=limit, offset=offset), session, response)


@router.post("/requests", status_code=201)
async def create(command: CreateIntake, session: DbSession, user: CurrentIntakeActor, response: Response):
    return await write(lambda: intake.create(session, user, command), session, response)


@router.get("/requests/{request_id}")
async def get(request_id: UUID, session: DbSession, user: CurrentIntakeActor, response: Response):
    async def operation():
        return intake.snapshot(await intake.owned(session, user, request_id))

    return await read(operation(), session, response)


@router.put("/requests/{request_id}")
async def update(
    request_id: UUID, command: UpdateIntake, session: DbSession, user: CurrentIntakeActor, response: Response
):
    return await write(lambda: intake.change(session, user, request_id, command), session, response)


@router.post("/requests/{request_id}/cancel")
async def cancel(
    request_id: UUID, command: CancelIntake, session: DbSession, user: CurrentIntakeActor, response: Response
):
    return await write(lambda: intake.change(session, user, request_id, command), session, response)


@router.get("/requests/{request_id}/history")
async def history(
    request_id: UUID,
    session: DbSession,
    user: CurrentIntakeActor,
    response: Response,
    before_revision: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return await read(
        intake.history(session, user, request_id, before_revision=before_revision, limit=limit), session, response
    )

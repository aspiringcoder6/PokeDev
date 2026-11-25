import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from langflow.adlc.requirement_readiness.models import Closed, NormalizedInput
from langflow.adlc.requirement_readiness.runtime import build_runtime, service_bindings
from langflow.adlc.requirement_readiness.service_auth import authenticate_bearer


@asynccontextmanager
async def lifespan(app):
    owned = False
    if os.environ.get("ADLC_REQUIREMENT_READINESS_ENABLED", "false").lower() == "true" and not getattr(
        app.state, "readiness_service", None
    ):
        app.state.readiness_service = build_runtime()
        owned = True
        await app.state.readiness_service.start_worker()
    try:
        yield
    finally:
        if owned:
            await app.state.readiness_service.close()
            app.state.readiness_service = None


router = APIRouter(prefix="/adlc/requirement-readiness", tags=["requirement-readiness"], lifespan=lifespan)


def fail(exc):
    code = str(exc)
    status = (
        401
        if code == "READINESS_UNAUTHENTICATED"
        else 403
        if code in {"READINESS_FORBIDDEN", "SOURCE_SCOPE_DENIED"}
        else 404
        if code == "READINESS_NOT_FOUND"
        else 409
    )
    raise HTTPException(
        status_code=status, detail=code if code.startswith(("READINESS_", "SOURCE_")) else "READINESS_REQUEST_INVALID"
    ) from None


def authenticate(request: Request):
    try:
        return authenticate_bearer(request.headers.get("authorization"), service_bindings())
    except ValueError as exc:
        fail(exc)


Principal = Annotated[object, Depends(authenticate)]


def service(request):
    result = getattr(request.app.state, "readiness_service", None)
    if result is None:
        raise HTTPException(status_code=503, detail="READINESS_DISABLED")
    return result


class AnswerCommand(Closed):
    round_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    expected_revision: int = Field(strict=True, ge=0)
    response: dict


class SelectionCommand(Closed):
    assessment_digest: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    expected_revision: int = Field(strict=True, ge=0)


@router.post("/runs", status_code=202)
async def start(body: NormalizedInput, request: Request, principal: Principal):
    try:
        return service(request).start(principal, body).model_dump(include={"id", "status", "revision"})
    except ValueError as exc:
        fail(exc)


@router.get("/runs/{run_id}")
async def get(run_id: str, request: Request, principal: Principal):
    try:
        return service(request).get(principal, run_id)
    except ValueError as exc:
        fail(exc)


@router.post("/runs/{run_id}/answers")
async def answer(run_id: str, body: AnswerCommand, request: Request, principal: Principal):
    try:
        return service(request).answer(
            principal, run_id, body.round_id, body.response, body.command_id, body.expected_revision
        )
    except ValueError as exc:
        fail(exc)


@router.post("/runs/{run_id}/selection")
async def select(run_id: str, body: SelectionCommand, request: Request, principal: Principal):
    try:
        return service(request).select(
            principal, run_id, body.assessment_digest, body.option_id, body.command_id, body.expected_revision
        )
    except ValueError as exc:
        fail(exc)


@router.get("/runs/{run_id}/handoff")
async def handoff(run_id: str, request: Request, principal: Principal):
    try:
        return service(request).handoff(principal, run_id)
    except ValueError as exc:
        fail(exc)

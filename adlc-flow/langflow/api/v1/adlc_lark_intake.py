"""LI-02 user linking and app-scoped connector endpoints."""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pokedev_lark_contracts import DeliveryBatch, DeliveryResult, InboundMessage, IngestReceipt
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from langflow.adlc import intake
from langflow.adlc import lark_intake as service
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_intake import CurrentIntakeActor, read, write
from langflow.services.auth.utils import verify_password

router = APIRouter(prefix="/adlc/intake/lark", tags=["Lark intake"])


def configured():
    try:
        return service.settings()
    except intake.IntakeError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code}, headers={"Cache-Control": "no-store"}) from None


Config = Annotated[service.Settings, Depends(configured)]


def connector(request: Request, config: Config):
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), ("Bearer " + config.secret).encode()):
        raise HTTPException(
            401, detail={"code": "LARK_CONNECTOR_UNAUTHENTICATED"}, headers={"Cache-Control": "no-store"}
        )
    return config


Connector = Annotated[service.Settings, Depends(connector)]


class LinkCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=1024)
    project_id: UUID | None = None


class UnlinkCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=1024)


def password_check(password):
    def check(hashed):
        try:
            return verify_password(password.get_secret_value(), hashed)
        except (ValueError, TypeError):
            return False

    return check


@router.get("/link")
async def status(session: DbSession, user: CurrentIntakeActor, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        config = service.settings()
    except intake.IntakeError as exc:
        if exc.code == "LARK_DISABLED":
            return {"enabled": False}
        raise HTTPException(exc.status, detail={"code": exc.code}) from None
    return await read(service.link_status(session, user, config), session, response)


@router.post("/link")
async def start(command: LinkCommand, session: DbSession, user: CurrentIntakeActor, response: Response, config: Config):
    return await write(
        lambda: service.start_link(session, user, config, command.project_id, password_check(command.password)),
        session,
        response,
    )


@router.post("/unlink")
async def unlink(
    command: UnlinkCommand, session: DbSession, user: CurrentIntakeActor, response: Response, config: Config
):
    return await write(
        lambda: service.unlink(session, user, config, password_check(command.password)), session, response
    )


@router.post("/events", response_model=IngestReceipt)
async def receive(command: InboundMessage, session: DbSession, response: Response, config: Connector):
    return await write(lambda: service.ingest(session, command, config), session, response)


@router.post("/deliveries/claim", response_model=DeliveryBatch)
async def claim(session: DbSession, response: Response, config: Connector):
    return await write(lambda: service.claim(session, config), session, response)


@router.post("/deliveries/{delivery_id}/result")
async def result(delivery_id: UUID, command: DeliveryResult, session: DbSession, response: Response, config: Connector):
    return await write(lambda: service.delivery_result(session, config, delivery_id, command), session, response)

"""Human project authoring/review; execution brokers remain disabled until H7C."""

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.responses import StreamingResponse

from langflow.adlc import collaboration as service
from langflow.adlc.collaboration_models import (
    DecisionCommand,
    HumanCommand,
    ImportRunCommand,
    ResourceCommand,
    SuiteCommand,
    SuiteUpdate,
    ToolCommand,
    WorkflowCommand,
    WorkflowUpdate,
)
from langflow.adlc.contract_repository import get_contract_repository
from langflow.adlc.verification_repository import get_verification_repository
from langflow.api.utils import DbSession
from langflow.api.v1.adlc import get_adlc_artifact_payload_store, get_blueprint_compiler
from langflow.api.v1.adlc_team_access import TeamUser as FoundationUser
from langflow.api.v1.adlc_team_access import checked, explicit_team_user
from langflow.services.authorization import team_access as access
from langflow.services.deps import session_scope

router = APIRouter(prefix="/adlc/collaboration", tags=["Project collaboration"])


async def collaboration_user(actor: FoundationUser):
    from langflow.services.deps import get_authorization_service

    if getattr(get_authorization_service(), "COLLABORATION_PROTOCOL_VERSION", None) != "0.1":
        raise HTTPException(status_code=503, detail={"code": "TEAM_COLLABORATION_PROVIDER_REQUIRED"})
    return actor


TeamUser = Annotated[object, Depends(collaboration_user)]


async def write(session, actor, project_id, operation, action):
    async def transaction():
        result = await operation
        await access.commit(session)
        return result

    return await checked(session, transaction(), actor=actor, project_id=project_id, action=action)


@router.get("/projects")
async def projects(session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await checked(session, access.visible_projects(session, actor))


@router.post("/projects/{project_id}/enable")
async def enable(project_id: UUID, command: HumanCommand, session: DbSession, actor: TeamUser):
    return await write(session, actor, project_id, service.enable(session, project_id, actor, command), "policy:manage")


@router.get("/projects/{project_id}")
async def overview(
    project_id: UUID,
    session: DbSession,
    actor: TeamUser,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    return await checked(session, service.overview(session, project_id, actor, limit=limit, offset=offset))


@router.get("/projects/{project_id}/resources/{resource_id}")
async def read_resource(
    project_id: UUID,
    resource_id: UUID,
    session: DbSession,
    actor: TeamUser,
    response: Response,
    revision: Annotated[int | None, Query(ge=1, le=512)] = None,
):
    response.headers["Cache-Control"] = "no-store"
    return await checked(session, service.view(session, project_id, resource_id, actor, revision=revision))


@router.post("/projects/{project_id}/contracts/tools")
async def contract_tool(project_id: UUID, command: ToolCommand, session: DbSession, actor: TeamUser):
    return await write(
        session, actor, project_id, service.contract_tool(session, project_id, actor, command), "requirement:write"
    )


@router.post("/projects/{project_id}/resources/{resource_id}/submit")
async def submit(project_id: UUID, resource_id: UUID, command: ResourceCommand, session: DbSession, actor: TeamUser):
    async def operation():
        await service.submit(session, project_id, resource_id, actor, command)
        await session.flush()
        return await service.view(session, project_id, resource_id, actor)

    return await write(session, actor, project_id, operation(), "resource:submit")


@router.post("/projects/{project_id}/resources/{resource_id}/decisions")
async def decision(project_id: UUID, resource_id: UUID, command: DecisionCommand, session: DbSession, actor: TeamUser):
    return await write(
        session,
        actor,
        project_id,
        service.decide_resource(session, project_id, resource_id, actor, command),
        "resource:decide",
    )


@router.post("/projects/{project_id}/resources/{resource_id}/revise")
async def revise(project_id: UUID, resource_id: UUID, command: ResourceCommand, session: DbSession, actor: TeamUser):
    return await write(
        session, actor, project_id, service.revise(session, project_id, resource_id, actor, command), "resource:revise"
    )


@router.post("/projects/{project_id}/workflows", status_code=201)
async def create_workflow(project_id: UUID, command: WorkflowCommand, session: DbSession, actor: TeamUser):
    return await write(
        session, actor, project_id, service.write_workflow(session, project_id, actor, command), "flow:create"
    )


@router.put("/projects/{project_id}/workflows/{workflow_id}")
async def update_workflow(
    project_id: UUID, workflow_id: UUID, command: WorkflowUpdate, session: DbSession, actor: TeamUser
):
    return await write(
        session,
        actor,
        project_id,
        service.write_workflow(session, project_id, actor, command, resource_id=workflow_id),
        "flow:write",
    )


@router.post("/projects/{project_id}/workflows/{workflow_id}/compile")
async def compile_plan(
    project_id: UUID, workflow_id: UUID, command: ResourceCommand, session: DbSession, actor: TeamUser
):
    return await write(
        session,
        actor,
        project_id,
        service.compile_plan(session, project_id, workflow_id, actor, command, get_blueprint_compiler()),
        "flow:write",
    )


@router.post("/projects/{project_id}/plans/{plan_id}/prepare")
async def prepare_run(project_id: UUID, plan_id: UUID, command: ResourceCommand, session: DbSession, actor: TeamUser):
    return await write(
        session, actor, project_id, service.prepare_run(session, project_id, plan_id, actor, command), "flow:write"
    )


@router.post("/projects/{project_id}/suites", status_code=201)
async def create_suite(project_id: UUID, command: SuiteCommand, session: DbSession, actor: TeamUser):
    return await write(
        session, actor, project_id, service.create_suite(session, project_id, actor, command), "test_suite:write"
    )


@router.put("/projects/{project_id}/suites/{suite_id}")
async def update_suite(project_id: UUID, suite_id: UUID, command: SuiteUpdate, session: DbSession, actor: TeamUser):
    return await write(
        session,
        actor,
        project_id,
        service.create_suite(session, project_id, actor, command, resource_id=suite_id),
        "test_suite:write",
    )


@router.get("/projects/{project_id}/imports/runs/{run_id}")
async def import_preview(project_id: UUID, run_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await checked(
        session,
        service.import_preview(
            session,
            project_id,
            run_id,
            actor,
            verification_repository=get_verification_repository(),
            contract_repository=get_contract_repository(),
        ),
    )


@router.post("/projects/{project_id}/imports/runs")
async def import_run(project_id: UUID, command: ImportRunCommand, session: DbSession, actor: TeamUser):
    return await write(
        session,
        actor,
        project_id,
        service.import_run(
            session,
            project_id,
            actor,
            command,
            artifact_store=get_adlc_artifact_payload_store(),
            verification_repository=get_verification_repository(),
            contract_repository=get_contract_repository(),
        ),
        "run:share",
    )


@router.get("/projects/{project_id}/runs/{run_id}/events")
async def events(project_id: UUID, run_id: UUID, session: DbSession, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"

    async def operation():
        await service.resource(session, project_id, run_id, kind="RUN")
        item = await service.view(session, project_id, run_id, actor)
        return {"run_id": run_id, "events": item["payload"]["events"]}

    return await checked(session, operation())


@router.get("/projects/{project_id}/runs/{run_id}/events/stream")
async def event_stream(project_id: UUID, run_id: UUID, request: Request, session: DbSession, actor: TeamUser):
    async def initial():
        await service.resource(session, project_id, run_id, kind="RUN")
        return await service.view(session, project_id, run_id, actor)

    await checked(session, initial())

    async def frames():
        last = None
        # Bounded connection; every frame reauthenticates the JWT and the current
        # membership in a fresh transaction. No stale permission/session cache.
        for _ in range(6):
            if await request.is_disconnected():
                return
            try:
                async with session_scope() as fresh:
                    user = await explicit_team_user(request, fresh)
                    await service.resource(fresh, project_id, run_id, kind="RUN")
                    item = await service.view(fresh, project_id, run_id, user)
                    payload = item["payload"]["events"]
                    current = service.sha256_digest(payload)
                    if current != last:
                        yield (
                            "event: run_events\ndata: "
                            + json.dumps({"run_id": str(run_id), "events": payload})
                            + "\n\n"
                        )
                        last = current
                    else:
                        yield ": scope revalidated\n\n"
            except Exception:  # noqa: BLE001 - any failed revalidation closes the stream without leaking diagnostics.
                yield 'event: access_revoked\ndata: {"code":"TEAM_ACCESS_REVALIDATION_FAILED"}\n\n'
                return
            await asyncio.sleep(5)

    return StreamingResponse(
        frames(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )

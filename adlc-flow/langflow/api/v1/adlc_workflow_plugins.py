"""Authenticated, owner-scoped observations for actual workflow plugin steps."""

import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunStateError
from langflow.adlc.workflow_plugin_client import Closed, PluginError
from langflow.adlc.workflow_plugin_starter import starter
from langflow.adlc.workflow_plugins import WorkflowPluginService, bindings, enabled, fingerprint, get_plugin_service
from langflow.api.utils import CurrentActiveUser
from langflow.api.v1.adlc import AdlcRunServiceDep
from langflow.api.v1.adlc_verification import Owner

router = APIRouter(prefix="/adlc", tags=["ADLC workflow plugins"])
Plugins = Annotated[WorkflowPluginService, Depends(get_plugin_service)]


async def owned(service, run_id, user):
    try:
        return await service.get_run(run_id, owner_id=str(user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError):
        raise HTTPException(404, {"code": "WORKFLOW_PLUGIN_NOT_FOUND"}) from None


def reject(exc):
    raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/workflow-plugins/starter")
async def get_starter(_user: CurrentActiveUser, response: Response, mode: Literal["full", "check"] = "full"):
    response.headers["Cache-Control"] = "no-store"
    if not enabled():
        raise HTTPException(409, {"code": "WORKFLOW_PLUGINS_DISABLED"})
    return starter(check_only=mode == "check")


@router.get("/runs/{run_id}/workflow-plugins")
async def view(run_id: UUID, user: CurrentActiveUser, service: AdlcRunServiceDep, plugins: Plugins, response: Response):
    response.headers["Cache-Control"] = "no-store"
    run = await owned(service, run_id, user)
    error_code = None
    try:
        connections = [item.public() for item in bindings(str(user.id), run.flow_id)] if run.flow_id else []
    except PluginError as exc:
        connections, error_code = [], exc.code
    return {
        "enabled": enabled(),
        "connections": connections,
        "configuration_error": error_code,
        "records": await asyncio.to_thread(plugins.ledger.list, owner=str(user.id), run_id=run_id),
    }


class HealthCommand(Closed):
    call_id: UUID


@router.post("/runs/{run_id}/workflow-plugins/health")
async def health(run_id: UUID, command: HealthCommand, user: Owner, service: AdlcRunServiceDep, plugins: Plugins):
    run = await owned(service, run_id, user)
    if not enabled():
        raise HTTPException(409, {"code": "WORKFLOW_PLUGINS_DISABLED"})
    try:
        async with plugins.lock(command.call_id):
            record, _, fresh = plugins.ledger.begin(
                call_id=command.call_id,
                owner=str(user.id),
                run_id=run_id,
                flow_id=run.flow_id,
                task_id=None,
                operation="HEALTH",
                request_digest=fingerprint({"owner": str(user.id), "run": str(run_id), "operation": "HEALTH"}),
                connection_digest=None,
            )
            return await plugins.perform(record, None, {}, fresh=fresh)
    except PluginError as exc:
        reject(exc)

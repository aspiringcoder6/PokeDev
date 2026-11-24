"""H6C owner-protected and signed session tools; optional context, never authority."""

# ruff: noqa: EM101, TRY300 - guarded returns; stable codes, never upstream text.
import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError

from langflow.adlc.contract_bridge import ContractBridgeSettings
from langflow.adlc.contract_repository import ContractError
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.models import WorkflowExecutionMode
from langflow.adlc.project_memory_client import MemoryClients, get_memory_clients, load_binding
from langflow.adlc.project_memory_models import (
    MEMORY_DOMAIN,
    MemoryBinding,
    MemoryBridgeCommand,
    MemoryCapabilities,
    MemoryQuery,
    MemoryRead,
    MemoryRecord,
    MemoryView,
    ProjectMemoryError,
    scope_names,
)
from langflow.adlc.project_memory_repository import MemoryRepository, get_memory_repository
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunStateError
from langflow.api.utils import CurrentActiveUser
from langflow.api.v1.adlc import AdlcRunServiceDep, HarnessCallbackReceiverDep
from langflow.api.v1.adlc_verification import Owner

router = APIRouter(prefix="/adlc", tags=["ADLC advisory project memory"])
Repository = Annotated[MemoryRepository, Depends(get_memory_repository)]
Clients = Annotated[MemoryClients, Depends(get_memory_clients)]
MAX_BRIDGE_BYTES = 8192


def enabled():
    return os.getenv("ADLC_MEMORY_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}


def reject(exc):
    raise HTTPException(exc.status, {"code": exc.code}) from None


async def bounded_query(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BRIDGE_BYTES:
            reject(ProjectMemoryError("MEMORY_REQUEST_TOO_LARGE", 413))
        raw.extend(chunk)
    try:
        return MemoryQuery.model_validate_json(raw)
    except (ValidationError, ValueError, RecursionError):
        reject(ProjectMemoryError("MEMORY_ARGUMENTS_INVALID", 422))


async def owned_run(service, run_id, user):
    try:
        return await service.get_run(run_id, owner_id=str(user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError):
        raise ProjectMemoryError("MEMORY_NOT_FOUND", 404) from None


def resolve_scope(run, *, task_id=None, attempt_id=None, session_id=None):
    """Use compiler-pinned request context, not current folder or caller dataset."""
    if run.execution_mode != WorkflowExecutionMode.EXECUTION_PLAN or run.execution_plan_id is None:
        raise ProjectMemoryError("MEMORY_PROJECT_UNBOUND")
    candidates = []
    for task in run.tasks:
        if task_id and task.id != task_id:
            continue
        if (
            not task.request
            or not task.plan_traceability
            or task.plan_traceability.execution_plan_id != run.execution_plan_id
        ):
            continue
        ref = (task.request.context or {}).get("adlc_local_project")
        if not ref:
            continue
        try:
            if task.request.workflow_run_id != run.id or task.request.task_run_id != task.id:
                raise ValueError
            if attempt_id and (task.current_attempt_id != attempt_id or task.request.attempt_id != attempt_id):
                raise ValueError
            candidates.append(
                MemoryBinding(
                    workflow_run_id=run.id,
                    project_id=ref["project_id"],
                    base_commit=ref["base_commit"],
                    source_ref=ref["source_ref"],
                    source_task_id=task.id if session_id else None,
                    source_attempt_id=attempt_id,
                    source_session_id=session_id,
                )
            )
        except (ValueError, TypeError, KeyError):
            raise ProjectMemoryError("MEMORY_PROJECT_UNBOUND") from None
    if not candidates or len({(c.project_id, c.base_commit, c.source_ref) for c in candidates}) != 1:
        raise ProjectMemoryError("MEMORY_PROJECT_UNBOUND")
    return candidates[0]


def capabilities(owner, binding):
    blockers, configured = [], False
    if not enabled():
        blockers.append("MEMORY_DISABLED")
    if not binding:
        blockers.append("MEMORY_PROJECT_UNBOUND")
    else:
        try:
            load_binding(owner, binding.project_id)
            configured = True
        except ProjectMemoryError as exc:
            blockers.append(exc.code)
    return MemoryCapabilities(enabled=enabled(), configured=configured, blockers=blockers)


async def view(run, owner, repository, *, task_id=None, attempt_id=None, session_id=None, limit=100, offset=0):
    try:
        binding = resolve_scope(run, task_id=task_id, attempt_id=attempt_id, session_id=session_id)
    except ProjectMemoryError:
        binding = None  # History is readable even if a newer attempt lacks live context.
    tenant, dataset = scope_names(owner, binding.project_id) if binding else (None, None)
    records = await asyncio.to_thread(
        repository.list,
        owner=owner,
        run_id=run.id,
        session_id=session_id,
        project_id=binding.project_id if binding else None,
        limit=limit,
        offset=offset,
    )
    return MemoryView(
        capabilities=capabilities(owner, binding), binding=binding, tenant_id=tenant, dataset=dataset, records=records
    )


async def operation(op, *, owner, binding, clients, repository, command=None):
    if not enabled():
        raise ProjectMemoryError("MEMORY_DISABLED")
    # Lookup retained idempotent result BEFORE gateway readiness: backend loss
    # must not hide a completed context read. The original project is still bound.
    intent = (
        await asyncio.to_thread(repository.begin, owner=owner, binding=binding, command=command)
        if op == "context"
        else None
    )
    if isinstance(intent, MemoryRead):
        return intent
    try:
        config = load_binding(owner, binding.project_id)
        client = clients.get(config)
        if op != "context":
            return await client.operation(op)
        result = await client.operation("context", query=command.query, top_k=command.top_k)
        record = MemoryRecord(
            record_id=intent,
            binding=binding,
            query=command.query,
            top_k=command.top_k,
            tenant_id=result.tenant_id,
            dataset=result.dataset,
            backend_revision=config.backend_revision,
            retrieved_at=datetime.now(timezone.utc),
            chunks=result.chunks,
        )
        return await asyncio.to_thread(repository.complete, record, owner=owner)
    except (ValueError, ProjectMemoryError) as exc:
        error = exc if isinstance(exc, ProjectMemoryError) else ProjectMemoryError("MEMORY_RESPONSE_INVALID", 502)
        if intent:
            await asyncio.to_thread(repository.fail, intent, owner=owner, code=error.code)
        raise error from None


@router.get("/runs/{run_id}/project-memory", response_model=MemoryView)
async def run_memory(
    run_id: UUID,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: Repository,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await view(await owned_run(service, run_id, user), str(user.id), repository, limit=limit, offset=offset)
    except ProjectMemoryError as exc:
        reject(exc)


@router.get("/harness-sessions/{session_id}/project-memory", response_model=MemoryView)
async def session_memory(
    session_id: str,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    repository: Repository,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
        run = await owned_run(service, attempt.workflow_run_id, user)
        return await view(
            run,
            str(user.id),
            repository,
            task_id=attempt.task_run_id,
            attempt_id=attempt.attempt_id,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
    except HarnessAttemptError:
        reject(ProjectMemoryError("MEMORY_NOT_FOUND", 404))
    except ProjectMemoryError as exc:
        reject(exc)


@router.post("/runs/{run_id}/project-memory/context", response_model=MemoryRead)
async def query_memory(
    run_id: UUID,
    command: Annotated[MemoryQuery, Depends(bounded_query)],
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    clients: Clients,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        binding = resolve_scope(await owned_run(service, run_id, user))
        return await operation(
            "context", owner=str(user.id), binding=binding, clients=clients, repository=repository, command=command
        )
    except ProjectMemoryError as exc:
        reject(exc)


@router.post("/runs/{run_id}/project-memory/{op}")
async def memory_status(
    run_id: UUID,
    op: str,
    request: Request,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    clients: Clients,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    if op not in {"health", "status"}:
        reject(ProjectMemoryError("MEMORY_OPERATION_NOT_ALLOWED", 403))
    # Reject caller-supplied datasets/scopes, including on status/health.
    async for chunk in request.stream():
        if chunk:
            reject(ProjectMemoryError("MEMORY_ARGUMENTS_INVALID", 422))
    try:
        binding = resolve_scope(await owned_run(service, run_id, user))
        return await operation(op, owner=str(user.id), binding=binding, clients=clients, repository=repository)
    except ProjectMemoryError as exc:
        reject(exc)


@router.post("/project-memory-tools")
async def harness_memory_tools(
    request: Request,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: Repository,
    clients: Clients,
):
    response.headers["Cache-Control"] = "no-store"
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BRIDGE_BYTES:
            reject(ProjectMemoryError("MEMORY_REQUEST_TOO_LARGE", 413))
        body.extend(chunk)
    try:
        ContractBridgeSettings(secret=os.getenv("ADLC_MEMORY_TOOL_SECRET")).authenticate(
            request.headers.get("X-ADLC-Memory-Timestamp", ""),
            request.headers.get("X-ADLC-Memory-Signature", ""),
            bytes(body),
            domain=MEMORY_DOMAIN,
        )
        command = MemoryBridgeCommand.model_validate_json(body)
        attempt = await callbacks.attempts.find_by_session(command.session_id)
        if attempt.result or attempt.status not in {
            TaskAttemptStatus.DISPATCHED,
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.WAITING_INTERACTION,
            TaskAttemptStatus.VERIFYING,
            TaskAttemptStatus.READY_TO_SUBMIT,
        }:
            raise ProjectMemoryError("MEMORY_ATTEMPT_INACTIVE", 403)
        owner, run = service.memory_session_context(
            run_id=attempt.workflow_run_id,
            task_id=attempt.task_run_id,
            attempt_id=attempt.attempt_id,
            request_id=attempt.request_id,
        )
        binding = resolve_scope(
            run, task_id=attempt.task_run_id, attempt_id=attempt.attempt_id, session_id=command.session_id
        )
        result = await operation(
            command.operation,
            owner=owner,
            binding=binding,
            clients=clients,
            repository=repository,
            command=command.arguments,
        )
        return {
            "schema_version": "0.1",
            "profile_ref": "memory-profile:project-context/0.1.0",
            "operation": command.operation,
            "binding": binding,
            "result": result,
        }
    except ContractError as exc:
        reject(ProjectMemoryError("MEMORY_BRIDGE_UNAUTHENTICATED", exc.http_status))
    except (ValidationError, ValueError) as exc:
        reject(exc if isinstance(exc, ProjectMemoryError) else ProjectMemoryError("MEMORY_ARGUMENTS_INVALID", 422))
    except HarnessAttemptError:
        reject(ProjectMemoryError("MEMORY_SESSION_NOT_BOUND", 403))

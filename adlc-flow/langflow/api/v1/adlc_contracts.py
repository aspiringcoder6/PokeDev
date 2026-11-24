"""H5A: owner-scoped contract APIs and a separately authenticated six-tool bridge."""

from __future__ import annotations

import os
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError

from langflow.adlc.contract_authoring_models import ContractAuthoringReadCommand, ContractViewerCapabilities
from langflow.adlc.contract_bridge import (
    AUTHORING_READ_DOMAIN,
    BRIDGE_MAX_BODY_BYTES,
    EXECUTION_DOMAIN,
    ContractBridgeSettings,
)
from langflow.adlc.contract_execution import compile_policy, execution_enabled, model_digest
from langflow.adlc.contract_execution_models import ContractExecutionBridgeCommand, ContractExecutionRead
from langflow.adlc.contract_execution_repository import ContractExecutionRepository, get_contract_execution_repository
from langflow.adlc.contract_models import (
    ContractApprovalCommand,
    ContractBridgeCommand,
    ContractForkCommand,
    ContractRead,
    ContractReference,
    ContractScope,
    ContractToolCommand,
    ContractToolResult,
)
from langflow.adlc.contract_presentation import contract_markdown
from langflow.adlc.contract_repository import (
    ContractError,
    ContractRepository,
    get_contract_repository,
)
from langflow.adlc.contract_validation import document_bytes
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.run_service import AdlcRunNotFoundError, AdlcRunStateError
from langflow.api.utils import CurrentActiveUser, DbSession  # noqa: TC001 - FastAPI runtime dependency aliases.
from langflow.api.v1.adlc import (  # noqa: TC001 - FastAPI runtime dependency aliases.
    AdlcRunServiceDep,
    HarnessCallbackReceiverDep,
)
from langflow.services.deps import get_auth_service, get_settings_service


def require_contracts_enabled() -> None:
    if os.getenv("ADLC_CONTRACTS_ENABLED", "").strip().lower() not in {"true", "1", "yes", "on"}:
        raise HTTPException(status_code=404, detail="Not found")


router = APIRouter(prefix="/adlc", tags=["ADLC contracts"], dependencies=[Depends(require_contracts_enabled)])


ContractRepositoryDep = Annotated[ContractRepository, Depends(get_contract_repository)]
ContractExecutionRepositoryDep = Annotated[ContractExecutionRepository, Depends(get_contract_execution_repository)]


def _raise(exc: ContractError) -> NoReturn:
    # Fixed messages/codes only: validation/transport exceptions can contain secrets or agent inputs.
    raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.code}) from None


async def get_contract_approver(request: Request, session: DbSession):
    """Require an explicit user access token, never auto-login, API keys or tool HMAC."""
    if get_settings_service().auth_settings.AUTO_LOGIN:
        raise HTTPException(status_code=403, detail={"code": "CONTRACT_EXPLICIT_LOGIN_REQUIRED"})
    authorization = request.headers.get("authorization", "")
    token = request.cookies.get("access_token_lf")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(status_code=401, detail={"code": "CONTRACT_USER_TOKEN_REQUIRED"})
    try:
        auth = get_auth_service()
        user = await auth.get_current_user_from_access_token(token, session)
        active_user = await auth.get_current_active_user(user)
    except Exception:  # noqa: BLE001 - Authentication errors must not expose supplied tokens.
        raise HTTPException(status_code=401, detail={"code": "CONTRACT_USER_TOKEN_INVALID"}) from None
    if active_user is None:
        raise HTTPException(status_code=401, detail={"code": "CONTRACT_USER_TOKEN_INVALID"})
    return active_user


ContractApproverDep = Annotated[object, Depends(get_contract_approver)]


async def _authorize_run(run_id: UUID, user, service):
    try:
        return await service.get_run(run_id, owner_id=str(user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError):
        raise HTTPException(status_code=404, detail={"code": "CONTRACT_NOT_FOUND"}) from None


@router.get("/contract-viewer", response_model=ContractViewerCapabilities)
async def contract_viewer_capabilities(
    _current_user: CurrentActiveUser, response: Response
) -> ContractViewerCapabilities:
    response.headers["Cache-Control"] = "no-store"
    return ContractViewerCapabilities(human_actions_configured=not get_settings_service().auth_settings.AUTO_LOGIN)


def _attempt_scope(attempt, session_id: str) -> ContractScope:
    return ContractScope(
        workflow_run_id=attempt.workflow_run_id,
        task_run_id=attempt.task_run_id,
        request_id=attempt.request_id,
        attempt_id=attempt.attempt_id,
        session_id=session_id,
    )


@router.get("/harness-sessions/{session_id}/contracts", response_model=list[ContractRead])
async def harness_session_contracts(
    session_id: str,
    current_user: CurrentActiveUser,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContractRead]:
    """Human-only, owner-authorized viewer read, including completed/older attempts.

    No HMAC/Bearer service token is exposed to the browser. Unknown sessions and
    another user's session are indistinguishable. There is no 'latest' fallback.
    """
    response.headers["Cache-Control"] = "no-store"
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
    except HarnessAttemptError:
        raise HTTPException(status_code=404, detail={"code": "CONTRACT_NOT_FOUND"}) from None
    await _authorize_run(attempt.workflow_run_id, current_user, service)
    try:
        return repository.list_for_run(
            attempt.workflow_run_id,
            owner_id=str(current_user.id),
            scope=_attempt_scope(attempt, session_id),
            limit=limit,
            offset=offset,
        )
    except ContractError as exc:
        _raise(exc)


@router.post("/contract-execution", response_model=ContractExecutionRead)
async def harness_contract_execution(
    request: Request,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    executions: ContractExecutionRepositoryDep,
) -> ContractExecutionRead:
    """Purpose-bound kernel bridge. No caller-selected contract, owner or policy."""
    response.headers["Cache-Control"] = "no-store"
    if not execution_enabled():
        _raise(ContractError("CONTRACT_EXECUTION_DISABLED", 403))
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > BRIDGE_MAX_BODY_BYTES:
            _raise(ContractError("CONTRACT_REQUEST_TOO_LARGE", 413))
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        ContractBridgeSettings.from_environment().authenticate(
            request.headers.get("X-ADLC-Contract-Timestamp", ""),
            request.headers.get("X-ADLC-Contract-Signature", ""),
            body,
            domain=EXECUTION_DOMAIN,
        )
        try:
            command = ContractExecutionBridgeCommand.model_validate_json(body)
        except (ValidationError, ValueError, RecursionError):
            msg = "CONTRACT_COMMAND_INVALID"
            raise ContractError(msg, 422) from None
        try:
            attempt = await callbacks.attempts.find_by_session(command.session_id)
        except HarnessAttemptError:
            msg = "CONTRACT_SESSION_NOT_BOUND"
            raise ContractError(msg, 409) from None
        if attempt.result is not None or attempt.status not in {
            TaskAttemptStatus.DISPATCHED,
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.WAITING_INTERACTION,
            TaskAttemptStatus.VERIFYING,
            TaskAttemptStatus.READY_TO_SUBMIT,
        }:
            msg = "CONTRACT_ATTEMPT_INACTIVE"
            raise ContractError(msg, 403)
        try:
            owner, configuration, trace = service.contract_execution_context(
                run_id=attempt.workflow_run_id,
                task_id=attempt.task_run_id,
                attempt_id=attempt.attempt_id,
                request_id=attempt.request_id,
            )
        except (AdlcRunNotFoundError, AdlcRunStateError):
            msg = "CONTRACT_EXECUTION_NOT_AUTHORIZED"
            raise ContractError(msg, 403) from None
        try:
            reference = ContractReference.model_validate(configuration.get("approved_contract_ref"))
        except ValidationError:
            msg = "CONTRACT_EXECUTION_REFERENCE_REQUIRED"
            raise ContractError(msg, 422) from None
        contract = repository.approved_reference(reference, owner_id=owner)
        policy = compile_policy(contract)
        binding, proof = executions.bind(
            owner_id=owner,
            scope=_attempt_scope(attempt, command.session_id),
            execution_plan_id=trace.execution_plan_id,
            resolved_node_digest=trace.resolved_node_digest,
            contract=contract,
            policy=policy,
        )
        if command.operation == "report":
            proof = executions.report(owner_id=owner, binding=binding, proof=command.proof)
        return ContractExecutionRead(binding=binding, contract=contract, proof=proof)
    except ContractError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/contract-executions", response_model=list[ContractExecutionRead])
async def run_contract_executions(
    run_id: UUID,
    current_user: CurrentActiveUser,
    response: Response,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    executions: ContractExecutionRepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContractExecutionRead]:
    """Historical owner read, independent of execution feature flag and patch TTL."""
    response.headers["Cache-Control"] = "no-store"
    await _authorize_run(run_id, current_user, service)
    try:
        result = []
        for binding, proof in executions.list_for_run(
            run_id, owner_id=str(current_user.id), limit=limit, offset=offset
        ):
            contract = repository.approved_reference(binding.reference, owner_id=str(current_user.id))
            if model_digest(compile_policy(contract)) != binding.policy_digest:
                msg = "CONTRACT_EXECUTION_STORE_INVALID"
                raise ContractError(msg, 503)
            result.append(ContractExecutionRead(binding=binding, contract=contract, proof=proof))
    except ContractError as exc:
        _raise(exc)
    else:
        return result


@router.get("/harness-sessions/{session_id}/contract-executions", response_model=list[ContractExecutionRead])
async def session_contract_executions(
    session_id: str,
    current_user: CurrentActiveUser,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    executions: ContractExecutionRepositoryDep,
) -> list[ContractExecutionRead]:
    response.headers["Cache-Control"] = "no-store"
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
    except HarnessAttemptError:
        raise HTTPException(status_code=404, detail={"code": "CONTRACT_NOT_FOUND"}) from None
    await _authorize_run(attempt.workflow_run_id, current_user, service)
    try:
        row = executions.get_by_attempt(attempt.attempt_id, owner_id=str(current_user.id))
        if not row:
            return []
        binding, proof = row
        if binding.scope != _attempt_scope(attempt, session_id):
            msg = "CONTRACT_EXECUTION_STORE_INVALID"
            raise ContractError(msg, 503)
        source = repository.approved_reference(binding.reference, owner_id=str(current_user.id))
        if model_digest(compile_policy(source)) != binding.policy_digest:
            msg = "CONTRACT_EXECUTION_STORE_INVALID"
            raise ContractError(msg, 503)
        return [ContractExecutionRead(binding=binding, contract=source, proof=proof)]
    except ContractError as exc:
        _raise(exc)


@router.post("/contract-authoring-result", response_model=ContractToolResult)
async def harness_authoring_result(
    request: Request,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
) -> ContractToolResult:
    """Trusted driver's read-only selection, not an agent tool or approval API."""
    response.headers["Cache-Control"] = "no-store"
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > BRIDGE_MAX_BODY_BYTES:
            _raise(ContractError("CONTRACT_REQUEST_TOO_LARGE", 413))
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        ContractBridgeSettings.from_environment().authenticate(
            request.headers.get("X-ADLC-Contract-Timestamp", ""),
            request.headers.get("X-ADLC-Contract-Signature", ""),
            body,
            domain=AUTHORING_READ_DOMAIN,
        )
        try:
            command = ContractAuthoringReadCommand.model_validate_json(body)
        except (ValidationError, ValueError, RecursionError):
            code = "CONTRACT_COMMAND_INVALID"
            raise ContractError(code, 422) from None
        try:
            attempt = await callbacks.attempts.find_by_session(command.session_id)
            if attempt.result is not None or attempt.status not in {
                TaskAttemptStatus.DISPATCHED,
                TaskAttemptStatus.RUNNING,
                TaskAttemptStatus.WAITING_INTERACTION,
                TaskAttemptStatus.VERIFYING,
                TaskAttemptStatus.READY_TO_SUBMIT,
            }:
                code = "CONTRACT_ATTEMPT_INACTIVE"
                raise ContractError(code, 403)
            owner_id = service.contract_authoring_owner(
                run_id=attempt.workflow_run_id,
                task_id=attempt.task_run_id,
                attempt_id=attempt.attempt_id,
                request_id=attempt.request_id,
            )
        except HarnessAttemptError:
            code = "CONTRACT_SESSION_NOT_BOUND"
            raise ContractError(code, 409) from None
        except (AdlcRunNotFoundError, AdlcRunStateError):
            code = "CONTRACT_AUTHORING_NOT_AUTHORIZED"
            raise ContractError(code, 403) from None
        # Two candidates are enough to reject ambiguous or model-chosen final output.
        contracts = repository.list_for_run(
            attempt.workflow_run_id, owner_id=owner_id, scope=_attempt_scope(attempt, command.session_id), limit=2
        )
        if len(contracts) != 1:
            code = "CONTRACT_AUTHORING_RESULT_AMBIGUOUS"
            raise ContractError(code, 409)
        contract = contracts[0]
        if (
            contract.status not in {"VALIDATED", "APPROVED"}
            or not contract.validation
            or not contract.validation.passed
        ):
            code = "CONTRACT_NOT_VALIDATED"
            raise ContractError(code, 409)
        return ContractToolResult(contract=contract)
    except ContractError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/contracts", response_model=list[ContractRead])
async def list_contracts(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContractRead]:
    response.headers["Cache-Control"] = "no-store"
    await _authorize_run(run_id, current_user, service)
    try:
        return repository.list_for_run(run_id, owner_id=str(current_user.id), limit=limit, offset=offset)
    except ContractError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/contracts/{contract_id}", response_model=ContractRead)
async def get_contract(
    run_id: UUID,
    contract_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
    revision: Annotated[int | None, Query(ge=1, le=512)] = None,
) -> ContractRead:
    response.headers["Cache-Control"] = "no-store"
    await _authorize_run(run_id, current_user, service)
    try:
        return repository.get(contract_id, owner_id=str(current_user.id), run_id=run_id, revision=revision)
    except ContractError as exc:
        _raise(exc)


@router.get("/runs/{run_id}/contracts/{contract_id}/file")
async def export_contract(
    run_id: UUID,
    contract_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    revision: Annotated[int | None, Query(ge=1, le=512)] = None,
) -> Response:
    await _authorize_run(run_id, current_user, service)
    try:
        contract = repository.get(contract_id, owner_id=str(current_user.id), run_id=run_id, revision=revision)
    except ContractError as exc:
        _raise(exc)
    return Response(
        content=document_bytes(contract.document),
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{contract_id}.r{contract.document.revision}.roadmap.json"',
            "X-ADLC-Content-Digest": contract.reference.content_digest,
        },
    )


@router.get("/runs/{run_id}/contracts/{contract_id}/summary")
async def export_contract_summary(
    run_id: UUID,
    contract_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    revision: Annotated[int | None, Query(ge=1, le=512)] = None,
) -> Response:
    await _authorize_run(run_id, current_user, service)
    try:
        contract = repository.get(contract_id, owner_id=str(current_user.id), run_id=run_id, revision=revision)
    except ContractError as exc:
        _raise(exc)
    return Response(
        content=contract_markdown(contract),
        media_type="text/markdown",
        headers={"Cache-Control": "no-store", "X-ADLC-Content-Digest": contract.reference.content_digest},
    )


@router.post("/runs/{run_id}/tasks/{task_id}/contract-tools", response_model=ContractToolResult)
async def human_contract_tool(
    run_id: UUID,
    task_id: UUID,
    command: ContractToolCommand,
    user: ContractApproverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
) -> ContractToolResult:
    response.headers["Cache-Control"] = "no-store"
    run = await _authorize_run(run_id, user, service)
    if not any(task.id == task_id for task in run.tasks):
        raise HTTPException(status_code=404, detail={"code": "CONTRACT_NOT_FOUND"})
    scope = ContractScope(workflow_run_id=run_id, task_run_id=task_id)
    try:
        if command.tool != "skilltree_init":
            try:
                contract_id = UUID(str(command.arguments.get("contract_id", "")))
            except ValueError:
                msg = "CONTRACT_ARGUMENTS_INVALID"
                raise ContractError(msg, 422) from None
            current = repository.get(contract_id, owner_id=str(user.id), run_id=run_id)
            if current.binding.task_run_id != task_id:
                msg = "CONTRACT_NOT_FOUND"
                raise ContractError(msg, 404)
            scope = current.binding
        return repository.execute(
            command.tool,
            command.arguments,
            owner_id=str(user.id),
            scope=scope,
            actor_id=str(user.id),
            authored_via="HUMAN",
        )
    except ContractError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/contracts/{contract_id}/approve", response_model=ContractToolResult)
async def approve_contract(
    run_id: UUID,
    contract_id: UUID,
    command: ContractApprovalCommand,
    user: ContractApproverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
) -> ContractToolResult:
    response.headers["Cache-Control"] = "no-store"
    await _authorize_run(run_id, user, service)
    if command.reference.contract_id != contract_id:
        raise HTTPException(status_code=409, detail={"code": "REVISION_CONFLICT"})
    try:
        return repository.approve(command, owner_id=str(user.id), run_id=run_id)
    except ContractError as exc:
        _raise(exc)


@router.post("/runs/{run_id}/contracts/{contract_id}/fork", response_model=ContractToolResult)
async def fork_contract(
    run_id: UUID,
    contract_id: UUID,
    command: ContractForkCommand,
    user: ContractApproverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
    response: Response,
) -> ContractToolResult:
    response.headers["Cache-Control"] = "no-store"
    await _authorize_run(run_id, user, service)
    if command.reference.contract_id != contract_id:
        raise HTTPException(status_code=409, detail={"code": "REVISION_CONFLICT"})
    try:
        return repository.fork(command, owner_id=str(user.id), run_id=run_id)
    except ContractError as exc:
        _raise(exc)


@router.post("/contract-tools", response_model=ContractToolResult)
async def harness_contract_tool(
    request: Request,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: ContractRepositoryDep,
) -> ContractToolResult:
    response.headers["Cache-Control"] = "no-store"
    chunks, length = [], 0
    async for chunk in request.stream():
        length += len(chunk)
        if length > BRIDGE_MAX_BODY_BYTES:
            _raise(ContractError("CONTRACT_REQUEST_TOO_LARGE", 413))
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        ContractBridgeSettings.from_environment().authenticate(
            request.headers.get("X-ADLC-Contract-Timestamp", ""),
            request.headers.get("X-ADLC-Contract-Signature", ""),
            body,
        )
        try:
            command = ContractBridgeCommand.model_validate_json(body)
        except (ValidationError, ValueError, RecursionError):
            msg = "CONTRACT_COMMAND_INVALID"
            raise ContractError(msg, 422) from None
        try:
            attempt = await callbacks.attempts.find_by_session(command.session_id)
        except HarnessAttemptError:
            msg = "CONTRACT_SESSION_NOT_BOUND"
            raise ContractError(msg, 409) from None
        if attempt.result is not None or attempt.status not in {
            TaskAttemptStatus.DISPATCHED,
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.WAITING_INTERACTION,
            TaskAttemptStatus.VERIFYING,
            TaskAttemptStatus.READY_TO_SUBMIT,
        }:
            msg = "CONTRACT_ATTEMPT_INACTIVE"
            raise ContractError(msg, 403)
        try:
            owner_id = service.contract_authoring_owner(
                run_id=attempt.workflow_run_id,
                task_id=attempt.task_run_id,
                attempt_id=attempt.attempt_id,
                request_id=attempt.request_id,
            )
        except (AdlcRunNotFoundError, AdlcRunStateError):
            msg = "CONTRACT_AUTHORING_NOT_AUTHORIZED"
            raise ContractError(msg, 403) from None
        scope = ContractScope(
            workflow_run_id=attempt.workflow_run_id,
            task_run_id=attempt.task_run_id,
            request_id=attempt.request_id,
            attempt_id=attempt.attempt_id,
            session_id=command.session_id,
        )
        return repository.execute(
            command.tool,
            command.arguments,
            owner_id=owner_id,
            scope=scope,
            actor_id=f"harness-session:{command.session_id}",
            authored_via="HARNESS_TOOL",
        )
    except ContractError as exc:
        _raise(exc)

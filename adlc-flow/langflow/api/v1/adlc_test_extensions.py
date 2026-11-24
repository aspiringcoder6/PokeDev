"""H6D protected proposal tools and supplementary raster archive, not a broker proxy."""

# ruff: noqa: EM101 - fixed codes only.
import json
import os
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import TypeAdapter, ValidationError

from langflow.adlc.contract_bridge import ContractBridgeSettings
from langflow.adlc.contract_execution import path_allowed
from langflow.adlc.contract_repository import ContractError
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_models import TaskAttemptStatus
from langflow.adlc.project_memory_models import ProjectMemoryError
from langflow.adlc.replay_models import ReplayPlan, suite_bytes
from langflow.adlc.replay_repository import ReplayRepository, get_replay_repository
from langflow.adlc.test_extension_models import (
    DOMAIN,
    MAX_COMMAND_BYTES,
    ExtensionCapabilities,
    ProposalBridgeCommand,
    ProposalCommand,
    ProposalDecision,
    ProposalRead,
    ScreenshotRead,
    ScreenshotUpload,
)
from langflow.adlc.test_extension_repository import (
    TestExtensionRepository,
    bytes_digest,
    get_test_extension_repository,
    replay_source,
)
from langflow.adlc.verification_models import VerificationError, digest
from langflow.api.utils import CurrentActiveUser
from langflow.api.v1.adlc import AdlcRunServiceDep, HarnessCallbackReceiverDep
from langflow.api.v1.adlc_project_memory import resolve_scope
from langflow.api.v1.adlc_replay import enabled as replay_enabled
from langflow.api.v1.adlc_verification import Contracts, Owner, fail, fresh, owned_run
from langflow.services.deps import get_settings_service

router = APIRouter(prefix="/adlc", tags=["ADLC test proposals and supplementary evidence"])
Repository = Annotated[TestExtensionRepository, Depends(get_test_extension_repository)]
Replays = Annotated[ReplayRepository, Depends(get_replay_repository)]
CommandAdapter = TypeAdapter(ProposalCommand)


def enabled():
    return os.getenv("ADLC_TEST_EXTENSIONS_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}


def require_enabled():
    if not enabled():
        fail(VerificationError("TEST_EXTENSIONS_DISABLED"))


async def read_body(request, *, limit=MAX_COMMAND_BYTES):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > limit:
            fail(VerificationError("TEST_REQUEST_TOO_LARGE", 413))
        raw.extend(chunk)
    return bytes(raw)


def parse(raw, adapter):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError
            obj[key] = value
        return obj

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return adapter.validate_python(value) if isinstance(adapter, TypeAdapter) else adapter.model_validate(value)
    except (ValueError, TypeError, ValidationError, RecursionError, UnicodeError):
        fail(VerificationError("TEST_PROPOSAL_ARGUMENTS_INVALID", 422))


def validate_document(document, source, contracts, owner):
    if document.source != replay_source(source):
        raise VerificationError("TEST_PROPOSAL_SOURCE_MISMATCH")
    contract = contracts.approved_reference(source.plan.contract_reference, owner_id=owner)
    if not path_allowed(source.plan.candidate.file, contract.document.constraints.allowed_paths):
        raise VerificationError("VERIFICATION_FILE_NOT_ALLOWED", 422)
    for case in document.cases:
        node = next((n for n in contract.document.nodes if n.node_id == case.criterion_node_id), None)
        if not node or case.criterion_index >= len(node.acceptance_criteria):
            raise VerificationError("VERIFICATION_CRITERION_NOT_IN_CONTRACT", 422)


def author(command, *, owner, run, repository, replays, contracts, session_id=None, project_id=None):
    record = (
        None
        if command.operation == "init"
        else repository.get(
            command.proposal_id if command.operation == "get_status" else command.reference.proposal_id,
            owner=owner,
            run_id=run.id,
        )
    )
    source_id = command.source_plan_id if record is None else record.document.source.plan_id
    source = replays.get(source_id, owner=owner, run_id=run.id)
    if project_id is not None and source.plan.candidate.project_id != project_id:
        raise VerificationError("TEST_PROPOSAL_NOT_FOUND", 404)
    if command.operation != "get_status":
        fresh(source, run)
    if record and record.document.source != replay_source(source):
        raise VerificationError("TEST_PROPOSAL_SOURCE_MISMATCH")
    return repository.command(
        command,
        owner=owner,
        run_id=run.id,
        source=source,
        session_id=session_id,
        validate=lambda doc: validate_document(doc, source, contracts, owner),
    )


@router.get("/test-extension-capabilities", response_model=ExtensionCapabilities)
async def capabilities(_user: CurrentActiveUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ExtensionCapabilities(
        enabled=enabled(), human_actions_configured=not get_settings_service().auth_settings.AUTO_LOGIN
    )


@router.get("/runs/{run_id}/test-proposals", response_model=list[ProposalRead])
async def proposals(
    run_id: UUID,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: Repository,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    await owned_run(service, run_id, user)
    try:
        return repository.list(owner=str(user.id), run_id=run_id, limit=limit, offset=offset)
    except VerificationError as exc:
        fail(exc)


@router.get("/harness-sessions/{session_id}/test-proposals", response_model=list[ProposalRead])
async def session_proposals(
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
        await owned_run(service, attempt.workflow_run_id, user)
        return repository.list(
            owner=str(user.id), run_id=attempt.workflow_run_id, session_id=session_id, limit=limit, offset=offset
        )
    except HarnessAttemptError:
        fail(VerificationError("TEST_PROPOSAL_NOT_FOUND", 404))
    except VerificationError as exc:
        fail(exc)


@router.post("/runs/{run_id}/test-proposals/tools", response_model=ProposalRead)
async def proposal_tool(
    run_id: UUID,
    request: Request,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
    contracts: Contracts,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    require_enabled()
    command = parse(await read_body(request), CommandAdapter)
    run = await owned_run(service, run_id, user)
    try:
        return author(command, owner=str(user.id), run=run, repository=repository, replays=replays, contracts=contracts)
    except (VerificationError, ContractError) as exc:
        fail(exc)
    except ValidationError:
        fail(VerificationError("TEST_PROPOSAL_ARGUMENTS_INVALID", 422))


@router.post("/runs/{run_id}/test-proposals/{proposal_id}/{operation}", response_model=ProposalRead)
async def proposal_action(
    run_id: UUID,
    proposal_id: UUID,
    operation: str,
    request: Request,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
    contracts: Contracts,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    require_enabled()
    decision = parse(await read_body(request), ProposalDecision)
    run = await owned_run(service, run_id, user)
    args = {"owner": str(user.id), "run_id": run_id}
    try:
        record = repository.get(proposal_id, **args)
        repository.exact(record, decision.reference)
        if record.reference.proposal_id != proposal_id:
            raise VerificationError("TEST_PROPOSAL_REFERENCE_CONFLICT")
        if operation == "execute":
            # Deliberately no client, URL, POST retry or model route to TestForge.
            # Even an owner-approved proposal is not an executable profile.
            raise VerificationError("TEST_EXTENSION_EXECUTION_NOT_AVAILABLE")
        if operation == "materialize" and record.state == "MATERIALIZED":
            materialized = replays.get(record.materialized_plan_id, **args)
            if materialized.plan.cases != record.document.cases:
                raise VerificationError("TEST_PROPOSAL_SOURCE_MISMATCH")
            return record  # Observe the same stored draft, never create a job.
        source, content = replays.payload(record.document.source.plan_id, **args)
        fresh(source, run)
        validate_document(record.document, source, contracts, str(user.id))
        if operation == "approve":
            return repository.approve(decision.reference, **args)
        if operation != "materialize" or record.state != "APPROVED" or record.document.kind != "suite-revision":
            raise VerificationError("TEST_PROPOSAL_MATERIALIZATION_NOT_ALLOWED")
        if not replay_enabled():
            raise VerificationError("REPLAY_DISABLED")
        # Cross-store recovery is idempotent: deterministic ID + persistent command
        # key. A crash after saving the new suite cannot duplicate it on retry.
        key = f"proposal:{proposal_id}:{record.reference.document_digest[7:]}"
        plan_id = uuid5(NAMESPACE_URL, "adlc-test-proposal/0.1\n" + str(user.id) + "\n" + str(run_id) + "\n" + key)
        plan = ReplayPlan(
            plan_id=plan_id,
            workflow_run_id=run_id,
            contract_reference=source.plan.contract_reference,
            candidate=source.plan.candidate,
            cases=record.document.cases,
            suite_digest=bytes_digest(suite_bytes(record.document.cases)),
            timeout_seconds=record.document.permissions.max_duration_seconds,
        )
        replay = replays.create(plan, content, command_key=key, command_digest=digest(decision), owner=str(user.id))
        return repository.materialized(decision.reference, replay.plan.plan_id, **args)
    except (VerificationError, ContractError) as exc:
        fail(exc)


@router.post("/test-proposal-tools")
async def bridge(
    request: Request,
    response: Response,
    callbacks: HarnessCallbackReceiverDep,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
    contracts: Contracts,
):
    response.headers["Cache-Control"] = "no-store"
    require_enabled()
    raw = await read_body(request)
    try:
        ContractBridgeSettings(secret=os.getenv("ADLC_TEST_PROPOSAL_TOOL_SECRET")).authenticate(
            request.headers.get("X-ADLC-Test-Proposal-Timestamp", ""),
            request.headers.get("X-ADLC-Test-Proposal-Signature", ""),
            raw,
            domain=DOMAIN,
        )
        envelope = parse(raw, ProposalBridgeCommand)
        attempt = await callbacks.attempts.find_by_session(envelope.session_id)
        if attempt.result or attempt.status not in {
            TaskAttemptStatus.DISPATCHED,
            TaskAttemptStatus.RUNNING,
            TaskAttemptStatus.WAITING_INTERACTION,
            TaskAttemptStatus.VERIFYING,
            TaskAttemptStatus.READY_TO_SUBMIT,
        }:
            raise VerificationError("TEST_PROPOSAL_ATTEMPT_INACTIVE", 403)
        owner, run = service.memory_session_context(
            run_id=attempt.workflow_run_id,
            task_id=attempt.task_run_id,
            attempt_id=attempt.attempt_id,
            request_id=attempt.request_id,
        )
        binding = resolve_scope(
            run, task_id=attempt.task_run_id, attempt_id=attempt.attempt_id, session_id=envelope.session_id
        )
        result = author(
            envelope.command,
            owner=owner,
            run=run,
            repository=repository,
            replays=replays,
            contracts=contracts,
            session_id=envelope.session_id,
            project_id=binding.project_id,
        )
    except ContractError as exc:
        fail(VerificationError("TEST_PROPOSAL_BRIDGE_UNAUTHENTICATED", exc.http_status))
    except HarnessAttemptError:
        fail(VerificationError("TEST_PROPOSAL_SESSION_NOT_BOUND", 403))
    except ProjectMemoryError as exc:
        fail(
            VerificationError(
                "TEST_PROPOSAL_ATTEMPT_INACTIVE"
                if exc.code == "MEMORY_ATTEMPT_INACTIVE"
                else "TEST_PROPOSAL_PROJECT_UNBOUND",
                403,
            )
        )
    except (VerificationError, ValidationError, ValueError) as exc:
        fail(exc if isinstance(exc, VerificationError) else VerificationError("TEST_PROPOSAL_ARGUMENTS_INVALID", 422))
    else:
        return {
            "schema_version": "0.1",
            "profile_ref": "test-extension-profile:proposals/0.1.0",
            "session_id": envelope.session_id,
            "operation": envelope.command.operation,
            "result": result,
        }


@router.get("/runs/{run_id}/replay-screenshots/{plan_id}", response_model=list[ScreenshotRead])
async def screenshots(
    run_id: UUID,
    plan_id: UUID,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    await owned_run(service, run_id, user)
    try:
        replay = replays.get(plan_id, owner=str(user.id), run_id=run_id)
        return repository.screenshots(replay, owner=str(user.id))
    except VerificationError as exc:
        fail(exc)


@router.post("/runs/{run_id}/replay-screenshots/{plan_id}", response_model=ScreenshotRead, status_code=201)
async def attach_screenshot(
    run_id: UUID,
    plan_id: UUID,
    request: Request,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    require_enabled()
    command = parse(await read_body(request, limit=352 * 1024), ScreenshotUpload)
    await owned_run(service, run_id, user)
    try:
        # Attaching a reference to old retained evidence is allowed; it grants no
        # verification/execute/publication authority and never changes that report.
        replay = replays.get(plan_id, owner=str(user.id), run_id=run_id)
        return repository.attach(command, replay, owner=str(user.id))
    except VerificationError as exc:
        fail(exc)


@router.get("/runs/{run_id}/replay-screenshots/{plan_id}/{attachment_id}")
async def screenshot(
    run_id: UUID,
    plan_id: UUID,
    attachment_id: UUID,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: Repository,
    replays: Replays,
):
    await owned_run(service, run_id, user)
    try:
        replay = replays.get(plan_id, owner=str(user.id), run_id=run_id)
        record, body = repository.screenshot(attachment_id, replay, owner=str(user.id))
        return Response(
            body,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-ADLC-Content-Digest": record.content_digest,
                "Content-Disposition": f'attachment; filename="{attachment_id}.png"',
                "Content-Security-Policy": "default-src 'none'; sandbox",
            },
        )
    except VerificationError as exc:
        fail(exc)

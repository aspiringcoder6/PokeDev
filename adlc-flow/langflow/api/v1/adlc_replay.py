"""Owner-controlled H6B replay pilot; no scheduler/callback/TaskResult mutation."""

# ruff: noqa: EM101 - fixed codes only.
import asyncio
import hashlib
import os
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from langflow.adlc.contract_repository import ContractError
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.local_projects import LocalProjectError
from langflow.adlc.replay_client import ReplayWorkerClient, get_replay_worker
from langflow.adlc.replay_models import CreateReplayPlan, ReplayCapabilities, ReplayPlan, ReplayRead, suite_bytes
from langflow.adlc.replay_repository import ReplayRepository, get_replay_repository
from langflow.adlc.run_service import AdlcArtifactUnavailableError, AdlcRunNotFoundError, AdlcRunStateError
from langflow.adlc.verification_models import ExactVerificationCommand, VerificationError, canonical, digest
from langflow.api.utils import CurrentActiveUser
from langflow.api.v1.adlc import AdlcRunServiceDep, HarnessCallbackReceiverDep
from langflow.api.v1.adlc_verification import Contracts, Owner, authorize_candidate, fail, fresh, owned_run
from langflow.services.deps import get_settings_service

router = APIRouter(prefix="/adlc", tags=["ADLC frozen replay"])
Repository = Annotated[ReplayRepository, Depends(get_replay_repository)]
Worker = Annotated[ReplayWorkerClient, Depends(get_replay_worker)]


def enabled():
    return os.getenv("ADLC_REPLAY_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}


def require_enabled():
    if not enabled():
        raise HTTPException(409, {"code": "REPLAY_DISABLED"})


async def adopt_result(record, result, repository, worker, owner):
    args = {"owner": owner, "run_id": record.plan.workflow_run_id}
    if result["state"] == "READY":
        return repository.accept(record.plan.plan_id, worker.receipt(result), **args)
    if result["state"] == "CANCELLED":
        worker.confirm_state(record, result)
        return repository.confirm_cancel(record.plan.plan_id, execution_id=record.execution_id, **args)
    if result["state"] in {"NOT_VERIFIED", "DISPATCH_UNCERTAIN", "CANCEL_REQUESTED"}:
        return repository.diagnostic(
            record.plan.plan_id,
            code="REPLAY_CANCELLATION_UNCONFIRMED"
            if result["state"] == "CANCEL_REQUESTED"
            else "REPLAY_REPRODUCTION_UNCONFIRMED",
            uncertain=result["state"] != "NOT_VERIFIED",
            **args,
        )
    return record


async def observe(record, repository, worker, owner):
    if not enabled() or record.state not in repository.active_states or not record.execution_id:
        return record
    try:
        return await adopt_result(record, await worker.read(record.execution_id), repository, worker, owner)
    except VerificationError as exc:
        return repository.diagnostic(
            record.plan.plan_id,
            owner=owner,
            run_id=record.plan.workflow_run_id,
            code=exc.code,
            uncertain=exc.code
            in {
                "VERIFICATION_EXECUTION_UNCONFIRMED",
                "VERIFICATION_WORKER_UNAVAILABLE",
                "REPLAY_CANCELLATION_UNCONFIRMED",
            },
        )


async def observe_batch(rows, repository, worker, owner):
    active = [r for r in rows if r.state in repository.active_states][:3]
    results = await asyncio.gather(*(observe(r, repository, worker, owner) for r in active))
    changed = {r.plan.plan_id: result for r, result in zip(active, results, strict=True)}
    return [changed.get(r.plan.plan_id, r) for r in rows]


@router.get("/replay-capabilities", response_model=ReplayCapabilities)
async def capabilities(_user: CurrentActiveUser, worker: Worker, response: Response):
    response.headers["Cache-Control"] = "no-store"
    ready, provider = False, None
    if enabled():
        try:
            health = await worker.health()
            ready, provider = health.get("ready") is True, health.get("provider")
        except VerificationError:
            pass
    return ReplayCapabilities(
        enabled=enabled(),
        worker_ready=ready,
        provider=provider,
        human_actions_configured=not get_settings_service().auth_settings.AUTO_LOGIN,
    )


@router.get("/runs/{run_id}/replays", response_model=list[ReplayRead])
async def list_replays(
    run_id: UUID,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    repository: Repository,
    worker: Worker,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    await owned_run(service, run_id, user)
    try:
        rows = repository.list(owner=str(user.id), run_id=run_id, limit=limit, offset=offset)
        return await observe_batch(rows, repository, worker, str(user.id))
    except VerificationError as exc:
        fail(exc)


@router.get("/harness-sessions/{session_id}/replays", response_model=list[ReplayRead])
async def session_replays(
    session_id: str,
    user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    repository: Repository,
    worker: Worker,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=200)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
    except HarnessAttemptError:
        raise HTTPException(404, {"code": "VERIFICATION_NOT_FOUND"}) from None
    await owned_run(service, attempt.workflow_run_id, user)
    try:
        rows = repository.list(
            owner=str(user.id),
            run_id=attempt.workflow_run_id,
            attempt_id=attempt.attempt_id,
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return await observe_batch(rows, repository, worker, str(user.id))
    except VerificationError as exc:
        fail(exc)


@router.post("/runs/{run_id}/replays", response_model=ReplayRead, status_code=201)
async def create_replay(
    run_id: UUID,
    command: CreateReplayPlan,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    contracts: Contracts,
):
    require_enabled()
    run = await owned_run(service, run_id, user)
    try:
        candidate, content = await authorize_candidate(command, run, user, service, contracts)
        plan = ReplayPlan(
            plan_id=uuid4(),
            workflow_run_id=run_id,
            contract_reference=command.contract_reference,
            candidate=candidate,
            cases=command.cases,
            suite_digest="sha256:" + hashlib.sha256(suite_bytes(command.cases)).hexdigest(),
            timeout_seconds=command.timeout_seconds,
        )
        return repository.create(
            plan, content, owner=str(user.id), command_key=command.idempotency_key, command_digest=digest(command)
        )
    except (VerificationError, ContractError, LocalProjectError) as exc:
        fail(exc)
    except (AdlcArtifactUnavailableError, AdlcRunNotFoundError, AdlcRunStateError, ValueError, OSError, RecursionError):
        fail(VerificationError("VERIFICATION_CANDIDATE_UNAVAILABLE", 422))


@router.post("/runs/{run_id}/replays/{plan_id}/{operation}", response_model=ReplayRead)
async def replay_action(
    run_id: UUID,
    plan_id: UUID,
    operation: str,
    command: ExactVerificationCommand,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    worker: Worker,
):
    require_enabled()
    run = await owned_run(service, run_id, user)
    args = {"owner": str(user.id), "run_id": run_id}
    try:
        record = repository.get(plan_id, **args)
        if record.plan_digest != command.plan_digest:
            raise VerificationError("VERIFICATION_REFERENCE_CONFLICT")
        # Cancelling an old job / observing its archive must remain possible after
        # the coding attempt changes; publication/approval/execute require freshness.
        if operation not in {"cancel", "reconcile"}:
            fresh(record, run)
        if operation in {"approve", "submit"}:
            return repository.action(plan_id, plan_digest=command.plan_digest, operation=operation, **args)[0]
        if operation == "execute":
            if not (await worker.health()).get("ready"):
                raise VerificationError("REPLAY_WORKER_UNAVAILABLE", 503)
            record, content = repository.action(plan_id, plan_digest=command.plan_digest, operation="execute", **args)
            try:
                await worker.create(record, content)
            except VerificationError as exc:
                return repository.diagnostic(plan_id, code=exc.code, uncertain=True, **args)
            return record
        if operation == "reconcile":
            return await observe(record, repository, worker, str(user.id))
        if operation == "cancel":
            record = repository.action(plan_id, plan_digest=command.plan_digest, operation="cancel", **args)[0]
            if record.state == "CANCELLED":
                return record
            try:
                return await adopt_result(record, await worker.cancel(record), repository, worker, str(user.id))
            except VerificationError as exc:
                return repository.diagnostic(plan_id, code=exc.code, uncertain=True, **args)
        raise VerificationError("VERIFICATION_OPERATION_INVALID", 422)
    except VerificationError as exc:
        fail(exc)


@router.get("/runs/{run_id}/replays/{plan_id}/evidence/{kind}")
async def replay_evidence(
    run_id: UUID, plan_id: UUID, kind: str, user: CurrentActiveUser, service: AdlcRunServiceDep, repository: Repository
):
    await owned_run(service, run_id, user)
    try:
        record = repository.get(plan_id, owner=str(user.id), run_id=run_id)
        if not record.receipt or not record.report or kind not in {"json", "junit"}:
            raise VerificationError("VERIFICATION_EVIDENCE_UNAVAILABLE", 404)
        if kind == "junit":
            body = record.receipt.junit_xml.encode("utf-8")
            checksum, media = record.receipt.junit_digest, "application/xml"
            name = f"{plan_id}.junit.xml"
        else:
            body = canonical(
                {
                    "plan": record.plan.model_dump(mode="json"),
                    "receipt": record.receipt.model_dump(mode="json"),
                    "report": record.report.model_dump(mode="json"),
                }
            )
            checksum, media, name = record.evidence_digest, "application/json", f"{plan_id}.replay.json"
        return Response(
            body,
            media_type=media,
            headers={
                "Cache-Control": "no-store",
                "X-ADLC-Content-Digest": checksum,
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'attachment; filename="{name}"',
            },
        )
    except VerificationError as exc:
        fail(exc)

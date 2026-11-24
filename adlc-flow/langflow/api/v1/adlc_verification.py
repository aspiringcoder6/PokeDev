"""Owner-authorized H6A verification of an accepted, captured JSON candidate.

This foundation adds independent evidence; it never retroactively rewrites a
coding task's status, changes a published H5 proof or grants action authority.
"""

# ruff: noqa: EM101 - all service errors expose fixed codes, never external response text.

import asyncio
import os
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from langflow.adlc.contract_execution import path_allowed
from langflow.adlc.contract_models import ContractReference
from langflow.adlc.contract_repository import ContractError, ContractRepository, get_contract_repository
from langflow.adlc.harness_artifacts import CAPTURE_KIND, CAPTURE_PRODUCERS
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.local_projects import LocalProjectError
from langflow.adlc.run_service import AdlcArtifactUnavailableError, AdlcRunNotFoundError, AdlcRunStateError
from langflow.adlc.verification_candidate import freeze_candidate
from langflow.adlc.verification_client import VerificationWorkerClient, get_verification_worker
from langflow.adlc.verification_models import (
    CreateVerificationPlan,
    ExactVerificationCommand,
    VerificationCapabilities,
    VerificationError,
    VerificationPlan,
    VerificationRead,
    canonical,
    digest,
)
from langflow.adlc.verification_repository import VerificationRepository, get_verification_repository
from langflow.api.utils import CurrentActiveUser, DbSession
from langflow.api.v1.adlc import AdlcRunServiceDep, HarnessCallbackReceiverDep
from langflow.api.v1.adlc_contracts import get_contract_approver
from langflow.services.deps import get_settings_service

router = APIRouter(prefix="/adlc", tags=["ADLC verification"])
Repository = Annotated[VerificationRepository, Depends(get_verification_repository)]
Worker = Annotated[VerificationWorkerClient, Depends(get_verification_worker)]
Contracts = Annotated[ContractRepository, Depends(get_contract_repository)]
OBSERVATION_BATCH = 3


def enabled():
    return os.getenv("ADLC_VERIFICATION_ENABLED", "").strip().lower() in {"true", "1", "yes", "on"}


def require_enabled():
    if not enabled():
        raise HTTPException(409, {"code": "VERIFICATION_DISABLED"})


async def explicit_owner(request: Request, session: DbSession):
    return await get_contract_approver(request, session)


Owner = Annotated[object, Depends(explicit_owner)]


def fail(exc):
    raise HTTPException(
        exc.status if isinstance(exc, VerificationError) else 422,
        {"code": exc.code if hasattr(exc, "code") else "VERIFICATION_INVALID"},
    ) from None


async def owned_run(service, run_id, user):
    try:
        return await service.get_run(run_id, owner_id=str(user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError):
        raise HTTPException(404, {"code": "VERIFICATION_NOT_FOUND"}) from None


def fresh(record, run):
    source = record.plan.candidate
    task = next((t for t in run.tasks if t.id == source.source_task_id), None)
    artifact = next(
        (a for a in (task.result.artifacts if task and task.result else []) if a.artifact_id == source.artifact_id),
        None,
    )
    if (
        not task
        or task.current_attempt_id != source.source_attempt_id
        or not artifact
        or artifact.checksum.value != source.artifact_digest[7:]
        or task.result.metadata.get("harness_session_id") != source.source_session_id
    ):
        raise VerificationError("VERIFICATION_CANDIDATE_STALE")


async def observe(record, repository, worker, owner):
    """Read/adopt the existing execution only. No create, retry or publication."""
    if not enabled() or record.state not in {"RUNNING", "DISPATCH_UNCERTAIN"} or not record.execution_id:
        return record
    args = {"owner": owner, "run_id": record.plan.workflow_run_id}
    try:
        result = await worker.read(record.execution_id)
        if result.get("state") == "READY":
            return repository.accept(record.plan.plan_id, worker.receipt(result), **args)
        if result.get("state") in {"NOT_VERIFIED", "DISPATCH_UNCERTAIN"}:
            return repository.diagnostic(
                record.plan.plan_id,
                code="VERIFICATION_REPRODUCTION_FAILED",
                uncertain=result["state"] == "DISPATCH_UNCERTAIN",
                **args,
            )
    except VerificationError as exc:
        return repository.diagnostic(
            record.plan.plan_id,
            code=exc.code,
            uncertain=exc.code in {"VERIFICATION_WORKER_UNAVAILABLE", "VERIFICATION_EXECUTION_UNCONFIRMED"},
            **args,
        )
    else:
        return record


async def observe_batch(rows, repository, worker, owner):
    active = [r for r in rows if r.state in {"RUNNING", "DISPATCH_UNCERTAIN"}][:OBSERVATION_BATCH]
    results = await asyncio.gather(*(observe(r, repository, worker, owner) for r in active))
    observed = {r.plan.plan_id: result for r, result in zip(active, results, strict=True)}
    return [observed.get(r.plan.plan_id, r) for r in rows]


@router.get("/verification-capabilities", response_model=VerificationCapabilities)
async def capabilities(_user: CurrentActiveUser, worker: Worker, response: Response):
    response.headers["Cache-Control"] = "no-store"
    ready, provider = False, None
    if enabled():
        try:
            health = await worker.health()
            ready, provider = health.get("ready") is True, health.get("provider")
        except VerificationError:
            pass
    return VerificationCapabilities(
        enabled=enabled(),
        human_actions_configured=not get_settings_service().auth_settings.AUTO_LOGIN,
        worker_ready=ready,
        provider=provider,
    )


@router.get("/runs/{run_id}/verification-candidates")
async def candidates(
    run_id: UUID, user: CurrentActiveUser, service: AdlcRunServiceDep, contracts: Contracts, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    run = await owned_run(service, run_id, user)
    repository = contracts
    contracts = {
        str(c.reference.contract_id): c.model_dump(mode="json")
        for c in repository.list_for_run(run_id, owner_id=str(user.id))
        if c.status == "APPROVED"
    }
    patches = []
    for task in run.tasks:
        configuration = task.request.metadata.get("resolved_configuration", {}) if task.request else {}
        ref = configuration.get("approved_contract_ref")
        if ref:
            try:
                contract = repository.approved_reference(ContractReference.model_validate(ref), owner_id=str(user.id))
                contracts[str(contract.reference.contract_id)] = contract.model_dump(mode="json")
            except (ContractError, ValueError):
                pass
        for artifact in task.result.artifacts if task.result else []:
            if artifact.kind != "SOURCE_PATCH" or artifact.attempt_id != task.current_attempt_id:
                continue
            try:
                snapshot = await service.get_source_patch(run_id, artifact.artifact_id, owner_id=str(user.id))
                files = [f.file for f in snapshot.files if f.file.endswith(".json")]
                if files:
                    patches.append(
                        {
                            "source_task_id": str(task.id),
                            "artifact_id": str(artifact.artifact_id),
                            "task_name": task.name,
                            "files": files,
                        }
                    )
            except (AdlcArtifactUnavailableError, AdlcRunNotFoundError, AdlcRunStateError):
                # Expired/unavailable patches cannot become new candidates.
                continue
    return {"contracts": list(contracts.values()), "patches": patches}


@router.get("/runs/{run_id}/verifications", response_model=list[VerificationRead])
async def list_verifications(
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
        # A bounded observation batch; completed archives require no live worker.
        return await observe_batch(rows, repository, worker, str(user.id))
    except VerificationError as exc:
        fail(exc)


@router.get("/harness-sessions/{session_id}/verifications", response_model=list[VerificationRead])
async def session_verifications(
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


async def authorize_candidate(command, run, user, service, contracts):
    """Shared H6A/H6B source authorization, not a new permission surface."""
    run_id = run.id
    contract = contracts.approved_reference(command.contract_reference, owner_id=str(user.id))
    if not path_allowed(command.file, contract.document.constraints.allowed_paths):
        raise VerificationError("VERIFICATION_FILE_NOT_ALLOWED", 422)
    for case in command.cases:
        node = next((n for n in contract.document.nodes if n.node_id == case.criterion_node_id), None)
        if not node or case.criterion_index >= len(node.acceptance_criteria):
            raise VerificationError("VERIFICATION_CRITERION_NOT_IN_CONTRACT", 422)
    task = next((t for t in run.tasks if t.id == command.source_task_id), None)
    if not task:
        raise VerificationError("VERIFICATION_NOT_FOUND", 404)
    snapshot = await service.get_source_patch(run_id, command.artifact_id, owner_id=str(user.id))
    descriptor = next(
        (a for a in (task.result.artifacts if task.result else []) if a.artifact_id == command.artifact_id), None
    )
    if (
        not descriptor
        or descriptor != snapshot.artifact
        or descriptor.task_run_id != task.id
        or descriptor.workflow_run_id != run_id
        or descriptor.attempt_id != task.current_attempt_id
        or descriptor.producer not in CAPTURE_PRODUCERS
        or descriptor.metadata.get("capture") != CAPTURE_KIND
        or snapshot.format != "harness-git-diff-v1"
    ):
        raise VerificationError("VERIFICATION_SOURCE_MISMATCH")
    candidate, content = await asyncio.to_thread(freeze_candidate, task, snapshot, command.file)
    return candidate, content


@router.post("/runs/{run_id}/verifications", response_model=VerificationRead, status_code=201)
async def create_verification(
    run_id: UUID,
    command: CreateVerificationPlan,
    user: Owner,
    service: AdlcRunServiceDep,
    repository: Repository,
    contracts: Contracts,
):
    require_enabled()
    run = await owned_run(service, run_id, user)
    try:
        candidate, content = await authorize_candidate(command, run, user, service, contracts)
        plan = VerificationPlan(
            plan_id=uuid4(),
            workflow_run_id=run_id,
            contract_reference=command.contract_reference,
            candidate=candidate,
            cases=command.cases,
            timeout_seconds=command.timeout_seconds,
        )
        return repository.create(
            plan, content, owner=str(user.id), command_key=command.idempotency_key, command_digest=digest(command)
        )
    except (VerificationError, ContractError, LocalProjectError) as exc:
        fail(exc)
    except (AdlcArtifactUnavailableError, AdlcRunNotFoundError, AdlcRunStateError, ValueError, OSError, RecursionError):
        fail(VerificationError("VERIFICATION_CANDIDATE_UNAVAILABLE", 422))


@router.post("/runs/{run_id}/verifications/{plan_id}/{operation}", response_model=VerificationRead)
async def verification_action(
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
    try:
        record = repository.get(plan_id, owner=str(user.id), run_id=run_id)
        fresh(record, run)
        if record.plan_digest != command.plan_digest:
            raise VerificationError("VERIFICATION_REFERENCE_CONFLICT")
        if operation in {"approve", "submit"}:
            return repository.action(
                plan_id, owner=str(user.id), run_id=run_id, plan_digest=command.plan_digest, operation=operation
            )[0]
        if operation == "execute":
            if not (await worker.health()).get("ready"):
                raise VerificationError("VERIFICATION_WORKER_UNAVAILABLE", 503)
            record, content = repository.action(
                plan_id, owner=str(user.id), run_id=run_id, plan_digest=command.plan_digest, operation="execute"
            )
            try:
                await worker.create(record, content)
            except VerificationError as exc:
                return repository.diagnostic(plan_id, owner=str(user.id), run_id=run_id, code=exc.code, uncertain=True)
            return record
        if operation == "reconcile":
            if record.state not in {"RUNNING", "DISPATCH_UNCERTAIN"} or not record.execution_id:
                return record
            try:
                result = await worker.read(record.execution_id)
                if result.get("state") == "READY":
                    return repository.accept(plan_id, worker.receipt(result), owner=str(user.id), run_id=run_id)
                if result.get("state") in {"NOT_VERIFIED", "DISPATCH_UNCERTAIN"}:
                    return repository.diagnostic(
                        plan_id,
                        owner=str(user.id),
                        run_id=run_id,
                        code="VERIFICATION_EXECUTION_UNCONFIRMED"
                        if result["state"] == "DISPATCH_UNCERTAIN"
                        else "VERIFICATION_REPRODUCTION_FAILED",
                        uncertain=result["state"] == "DISPATCH_UNCERTAIN",
                    )
            except VerificationError as exc:
                return repository.diagnostic(
                    plan_id,
                    owner=str(user.id),
                    run_id=run_id,
                    code=exc.code,
                    uncertain=exc.code in {"VERIFICATION_WORKER_UNAVAILABLE", "VERIFICATION_EXECUTION_UNCONFIRMED"},
                )
            else:
                return record
        raise VerificationError("VERIFICATION_OPERATION_INVALID", 422)
    except VerificationError as exc:
        fail(exc)


@router.get("/runs/{run_id}/verifications/{plan_id}/evidence")
async def verification_evidence(
    run_id: UUID, plan_id: UUID, user: CurrentActiveUser, service: AdlcRunServiceDep, repository: Repository
):
    await owned_run(service, run_id, user)
    try:
        record = repository.get(plan_id, owner=str(user.id), run_id=run_id)
        if not record.receipt or not record.report:
            raise VerificationError("VERIFICATION_EVIDENCE_UNAVAILABLE", 404)
        body = canonical(
            {
                "plan": record.plan.model_dump(mode="json"),
                "receipt": record.receipt.model_dump(mode="json"),
                "report": record.report.model_dump(mode="json"),
            }
        )
        return Response(
            body,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "X-ADLC-Content-Digest": record.evidence_digest,
                "Content-Disposition": f'attachment; filename="{plan_id}.verification.json"',
            },
        )
    except VerificationError as exc:
        fail(exc)

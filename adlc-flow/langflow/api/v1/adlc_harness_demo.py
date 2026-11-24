"""Dedicated real-demo UI endpoints and purpose-separated native/GitHub ingress."""

# ruff: noqa: EM101, PLR2004, TRY300 - stable error codes, bounded ingress, guarded HTTP returns.

import hashlib
import hmac
import json
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError

from langflow.adlc.contract_bridge import ContractBridgeSettings
from langflow.adlc.contract_repository import ContractError
from langflow.adlc.harness_demo import DOMAIN, GITHUB_LABEL, HarnessDemoService, get_demo_service, github_repository
from langflow.adlc.harness_demo_models import Approval, CreateDemo, DemoError, ToolCommand, digest
from langflow.api.utils import CurrentActiveUser
from langflow.api.v1.adlc_verification import Owner

router = APIRouter(prefix="/adlc/harness-demo", tags=["ADLC Agent Harness"])


def service_enabled():
    if os.getenv("ADLC_HARNESS_DEMO_ENABLED", "").lower() != "true":
        raise HTTPException(503, {"code": "DEMO_DISABLED"})
    return get_demo_service()


Service = Annotated[HarnessDemoService, Depends(service_enabled)]


async def body(request, limit=32768):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, {"code": "DEMO_REQUEST_TOO_LARGE"})
    return bytes(data)


def reject(exc):
    raise HTTPException(
        exc.status if isinstance(exc, DemoError) else 422,
        {"code": exc.code if hasattr(exc, "code") else "DEMO_ARGUMENTS_INVALID"},
    ) from None


def require_standalone(record):
    if record.get("workflow_run_id"):
        raise DemoError("HARNESS_WORKFLOW_USE_RUN_CONTROLS", 409)


@router.get("/capabilities")
async def capabilities(service: Service, _user: CurrentActiveUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await service.capabilities()


@router.get("/runs")
async def runs(service: Service, user: CurrentActiveUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.ledger.list(str(user.id))


@router.post("/runs", status_code=201)
async def create(request: Request, user: Owner, service: Service):
    try:
        command = CreateDemo.model_validate_json(await body(request))
        return await service.create(str(user.id), command.requirement)
    except (ValidationError, DemoError) as exc:
        reject(exc)


@router.get("/runs/{run_id}")
async def run(run_id: UUID, user: CurrentActiveUser, service: Service, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        record = service.ledger.get(run_id, str(user.id))
        # A restart never replays model calls/commits/push. Operator must start a new demo.
        if record["status"] in {"PLANNING", "RUNNING", "PUBLISHING"} and str(run_id) not in service.jobs:
            record["interrupted"] = True
        return record
    except DemoError as exc:
        reject(exc)


@router.post("/runs/{run_id}/plan", status_code=202)
async def plan(run_id: UUID, request: Request, user: Owner, service: Service):
    try:
        require_standalone(service.ledger.get(run_id, str(user.id)))
        if await body(request, 256) not in {b"", b"{}"}:
            raise DemoError("DEMO_ARGUMENTS_INVALID", 422)
        if not (await service.capabilities())["ready"]:
            raise DemoError("DEMO_PREFLIGHT_FAILED", 503)
        record = service.ledger.transition(run_id, str(user.id), "DRAFT", "PLANNING")
        service.launch(run_id, lambda: service.plan(run_id))
        return record
    except DemoError as exc:
        reject(exc)


@router.post("/runs/{run_id}/restart", status_code=201)
async def restart(run_id: UUID, request: Request, user: Owner, service: Service):
    try:
        require_standalone(service.ledger.get(run_id, str(user.id)))
        if await body(request, 256) not in {b"", b"{}"}:
            raise DemoError("DEMO_ARGUMENTS_INVALID", 422)
        return await service.restart(run_id, str(user.id))
    except DemoError as exc:
        reject(exc)


@router.post("/runs/{run_id}/{action}", status_code=202)
async def approve(run_id: UUID, action: str, request: Request, user: Owner, service: Service):
    try:
        command = Approval.model_validate_json(await body(request, 1024))
        record = service.ledger.get(run_id, str(user.id))
        require_standalone(record)
        if action == "approve-plan":
            expected, state, target = record.get("plan_digest"), "AWAITING_PLAN_APPROVAL", "RUNNING"

            async def operation():
                await service.execute(run_id)
        elif action == "approve-merge":
            expected, state, target = record.get("handoff_digest"), "AWAITING_MERGE_APPROVAL", "PUBLISHING"

            async def operation():
                await service.publish(run_id)
        else:
            raise DemoError("DEMO_ACTION_DENIED", 404)
        if command.digest != expected:
            raise DemoError("DEMO_APPROVAL_DIGEST_MISMATCH")
        if action == "approve-plan" and not (await service.capabilities())["ready"]:
            raise DemoError("DEMO_PREFLIGHT_FAILED", 503)
        service.ledger.transition(run_id, str(user.id), state, target)
        await service.event(run_id, action, {"approved_by": str(user.id), "digest": command.digest})
        service.launch(run_id, operation)
        return service.ledger.get(run_id, str(user.id))
    except (DemoError, ValidationError) as exc:
        reject(exc)


@router.post("/tools")
async def tools(request: Request, service: Service, response: Response):
    response.headers["Cache-Control"] = "no-store"
    raw = await body(request)
    try:
        ContractBridgeSettings(secret=os.getenv("ADLC_DEMO_TOOL_SECRET")).authenticate(
            request.headers.get("X-ADLC-Demo-Timestamp", ""),
            request.headers.get("X-ADLC-Demo-Signature", ""),
            raw,
            domain=DOMAIN,
        )
        return await service.tool(ToolCommand.model_validate_json(raw))
    except ContractError as exc:
        raise HTTPException(exc.http_status, {"code": "DEMO_BRIDGE_UNAUTHENTICATED"}) from None
    except (ValidationError, DemoError) as exc:
        reject(exc)


@router.post("/github/issues", status_code=201)
async def issue(request: Request, user: Owner, _service: Service):
    try:
        if os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true":
            raise DemoError("DEMO_GITHUB_DISABLED")
        if str(user.id) != os.getenv("ADLC_DEMO_GITHUB_OWNER_ID"):
            raise DemoError("DEMO_GITHUB_OWNER_UNBOUND", 403)
        command = CreateDemo.model_validate_json(await body(request))
        from langflow.adlc.harness_demo_sandbox import process

        repository = github_repository()
        code, out, _ = await process(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                repository,
                "--title",
                "[ADLC] Pagination task",
                "--label",
                GITHUB_LABEL,
                "--body",
                command.requirement,
            ],
            timeout=30,
            credential_context=True,
        )
        if code or not out.strip().startswith("https://github.com/" + repository + "/issues/"):
            raise DemoError("DEMO_GITHUB_ISSUE_CREATE_UNKNOWN", 502)
        # Issue POST is never retried. Its signed webhook creates the owner-scoped demo run.
        return {"issue_url": out.strip(), "awaiting_webhook": True, "repository": repository}
    except (ValidationError, DemoError) as exc:
        reject(exc)


@router.post("/github/webhook", status_code=202)
async def webhook(request: Request, service: Service):
    raw = await body(request, 65536)
    secret = os.getenv("ADLC_DEMO_GITHUB_WEBHOOK_SECRET", "")
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if len(secret.encode()) < 32 or not hmac.compare_digest(signature, expected):
        raise HTTPException(401, {"code": "DEMO_WEBHOOK_UNAUTHENTICATED"})
    if os.getenv("ADLC_DEMO_GITHUB_ENABLED", "").lower() != "true":
        raise HTTPException(409, {"code": "DEMO_GITHUB_DISABLED"})
    try:
        payload = json.loads(raw)
        repo = payload["repository"]
        if repo["full_name"] != github_repository() or str(repo["id"]) != os.getenv("ADLC_DEMO_GITHUB_REPOSITORY_ID"):
            raise DemoError("DEMO_WEBHOOK_REPOSITORY_DENIED", 403)
        if request.headers.get("X-GitHub-Event") != "issues" or payload.get("action") not in {"opened", "labeled"}:
            return {"ignored": True}
        item = payload["issue"]
        if not {GITHUB_LABEL, "adlc-harness-demo"}.intersection(x["name"] for x in item["labels"]):
            return {"ignored": True}
        owner = str(UUID(os.getenv("ADLC_DEMO_GITHUB_OWNER_ID", "")))
        requirement = CreateDemo(requirement=item["body"]).requirement
        # Stable issue identity dedupes both opened/labeled events and redelivery with a new delivery ID.
        identity = str(repo["id"]) + ":issue:" + str(item["number"])
        with service.ledger.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT run_id FROM demo_deliveries WHERE id=?", (identity,)).fetchone()
            if old:
                return {"duplicate": True, "run_id": old[0]}
            db.execute("INSERT INTO demo_deliveries VALUES (?,?,NULL)", (identity, digest(requirement)))
        run = await service.create(
            owner,
            requirement,
            github=True,
            issue={
                "source": "GITHUB_WEBHOOK",
                "number": item["number"],
                "title": item["title"][:256],
                "repository": repo["full_name"],
                "delivery_id": request.headers.get("X-GitHub-Delivery", "")[:80],
            },
        )
        with service.ledger.db() as db:
            db.execute("UPDATE demo_deliveries SET run_id=? WHERE id=?", (run["id"], identity))
        if os.getenv("ADLC_DEMO_WEBHOOK_AUTO_PLAN", "").lower() == "true":
            service.ledger.transition(run["id"], owner, "DRAFT", "PLANNING")
            service.launch(run["id"], lambda: service.plan(run["id"]))
        return {"run_id": run["id"], "assigned_runtime": "HARNESS", "human_plan_gate": True}
    except (KeyError, TypeError, ValueError, DemoError) as exc:
        reject(exc)

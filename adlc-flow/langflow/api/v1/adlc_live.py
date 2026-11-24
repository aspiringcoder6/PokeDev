"""Authenticated Gitea selection, requirement planning, execution and immutable history."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from uuid import UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from langflow.adlc.gitea_projects import Gitea, checkout, git, DATA, ROOT
from langflow.adlc.live_workflows import live_service, public_project, public_run, safe_path
from langflow.adlc.project_workflows import validate_draft, workflow_snapshot, workflow_status
from langflow.adlc.vai_services import ServiceCheckError, settings
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source, permission
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.api.v1.adlc_issues import router as issue_router
from langflow.api.v1.adlc_metrics import router as metrics_router
from langflow.api.v1.adlc_project_lifecycle import router as lifecycle_router
from langflow.api.v1.adlc_workspace import router as workspace_router
from langflow.api.v1.adlc_integrations import router as integrations_router
from langflow.api.v1.adlc_project_workloop import router as project_workloop_router
from langflow.api.v1.adlc_document_intake import router as document_intake_router
from langflow.services.authorization import FlowAction, ProjectAction, ensure_project_permission
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.adlc_local_project import AdlcLocalProject

router = APIRouter(prefix="/adlc/live", tags=["Live project workflows"])
router.include_router(issue_router)
router.include_router(metrics_router)
router.include_router(lifecycle_router)
router.include_router(workspace_router)
router.include_router(integrations_router)
router.include_router(project_workloop_router)
router.include_router(document_intake_router)


@router.get("/readiness")
async def readiness(actor: TeamUser, response: Response, session: DbSession):
    response.headers["Cache-Control"] = "no-store"
    await session.commit()
    try:
        from dsh_web_sdk import DshClient, RetryConfig
        base, token = settings()
        async with DshClient(base, token, timeout=12, retry=RetryConfig(max_attempts=1)) as client:
            capabilities = await client.http_get("/api/v1/pokedev-services/projects/capabilities", timeout=12)
        ready = capabilities.get("version") == "1.0" and capabilities.get("sandbox") is True and capabilities.get("testforge") is True
        return {"ready": ready, "endpoint": base, "error_code": None if ready else "LIVE_AI_OR_SANDBOX_UNAVAILABLE"}
    except Exception as exc:
        return {"ready": False, "error_code": getattr(exc, "code", None) or "LIVE_AI_OR_SANDBOX_UNAVAILABLE"}


class ConnectProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: int | None = Field(default=None, gt=0)
    new_repository_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$")
    description: str = Field(default="", max_length=500)


class PlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    project_id: UUID
    delivery_id: UUID
    workflow_id: UUID | None = None
    workflow_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class WorkflowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID
    project_id: UUID
    name: str = Field(min_length=1, max_length=120)
    graph: dict
    expected_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ApplyWorkflowCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID
    workflow_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def public_workflow(value):
    _, error = workflow_status(value["graph"])
    return {**value, "ready": error is None, "error_code": error}


def selected_workflow(service, owner, project_id, identity, expected_digest):
    if bool(identity) != bool(expected_digest):
        raise ServiceCheckError("LIVE_WORKFLOW_CHANGED")
    if not identity:
        return None
    value = service.store.workflow(owner, str(identity))
    if value["project_id"] != str(project_id):
        raise ServiceCheckError("LIVE_WORKFLOW_PROJECT_MISMATCH")
    if value["digest"] != expected_digest:
        raise ServiceCheckError("LIVE_WORKFLOW_CHANGED")
    try:
        return workflow_snapshot(value)
    except ValueError as exc:
        raise ServiceCheckError(str(exc), 422) from None


@router.get("/workflows")
async def list_workflows(actor: TeamUser, response: Response, project_id: UUID | None = None):
    response.headers["Cache-Control"] = "no-store"
    return {"items": [public_workflow(w) for w in live_service().store.workflows(str(actor.id), str(project_id) if project_id else None)]}


@router.get("/workflows/{identity}")
async def read_workflow(identity: UUID, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return public_workflow(live_service().store.workflow(str(actor.id), str(identity)))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.put("/workflows/{identity}")
async def save_workflow(identity: UUID, command: WorkflowCommand, actor: TeamUser):
    if identity != command.workflow_id or not command.name.strip() or len(json.dumps(command.graph)) > 400000:
        raise HTTPException(422, {"code": "LIVE_WORKFLOW_INVALID"})
    try:
        try:
            validate_draft(command.graph)
        except ValueError as exc:
            raise HTTPException(422, {"code": str(exc)}) from None
        value = live_service().store.save_workflow(str(actor.id), str(identity), str(command.project_id), command.name.strip(), command.graph, command.expected_digest)
        return public_workflow(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


class NativeModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    model: str = Field(min_length=1, max_length=200)


class ExecuteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_route: NativeModelRoute | None = None


async def validated_execution_model(route):
    if route is None:
        return None
    from dsh_web_sdk import DshClient, RetryConfig

    base, token = settings()
    try:
        async with DshClient(base, token, timeout=20, retry=RetryConfig(max_attempts=1)) as client:
            catalog = await client.rpc("session/modelCatalog", {})
        groups = catalog["groups"]
    except Exception:
        raise ServiceCheckError("LIVE_MODEL_CATALOG_UNAVAILABLE", 503) from None
    if not any(group.get("id") == route.provider and any(model.get("id") == route.model
            for model in group.get("models", [])) for group in groups):
        raise ServiceCheckError("LIVE_MODEL_NOT_AVAILABLE", 422)
    return route.model_dump()


class RetryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    model_route: NativeModelRoute | None = None


class HumanResponseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    response: dict


@router.get("/attention")
async def attention(actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    service = live_service()
    monitor = service.human_input
    monitor.start()
    rows = [service.observe(row) for row in service.store.runs(str(actor.id))]
    reviews = [{"request_id": "plan:" + row["run_id"] + ":" + row["plan"]["digest"], "run_id": row["run_id"],
                "project_id": row["project_id"], "run_title": row["title"], "kind": "plan", "title": "Kế hoạch đang chờ bạn duyệt"}
               for row in rows if row["state"] == "PLAN_READY" and row.get("plan")]
    reviews.extend(await monitor.legacy_reviews(str(actor.id)))
    reviews.extend(service.issue_service.attention(str(actor.id)))
    reviews.extend({"request_id": "recovery:" + row["run_id"], "run_id": row["run_id"], "project_id": row["project_id"],
                    "run_title": row["title"], "kind": "recovery", "title": "Lượt bị gián đoạn có tiến trình để tiếp tục"}
                   for row in rows if row["state"] == "UNCONFIRMED" and service.recovery.inspect(row).get("available"))
    return {
        "connected": monitor.connected.is_set(),
        "active_runs": sum(row["state"] in {"PLANNING", "RUNNING"} for row in rows),
        "requests": monitor.pending(str(actor.id)),
        "reviews": reviews,
    }


@router.post("/runs/{identity}/human-input/{request_id}")
async def answer_human_input(identity: UUID, request_id: str, command: HumanResponseCommand, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.observe(service.store.get(str(actor.id), str(identity)))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        return await service.human_input.answer(str(actor.id), row, request_id, str(command.command_id), command.response)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


async def scoped_contracts(client, row):
    """Inspect only this run's accepted tasks; never enumerate the whole Harness."""
    known = [n for n in row.get("nodes", []) if n.get("session_id")]
    if not known:
        return []
    bridge = str(uuid5(UUID(row["run_id"]), row["phase"]))
    receipt = await client.http_get("/api/v1/pokedev-services/tnqd/runs/" + bridge + "?scope_id=" + row["scope_id"])
    bindings = {n["id"]: n["workspace"] for n in receipt["nodes"]}
    return await asyncio.gather(*(client.get_task(bindings[n["id"]], "1") for n in known))


def legacy_runs(owner):
    path = ROOT / "adlc-flow/data/tnqd-demo/runs.sqlite3"
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        records = db.execute("SELECT payload FROM tnqd_runs WHERE owner=? ORDER BY rowid DESC", (owner,)).fetchall()
    result = []
    registered = {p["repository"]: p["project_id"] for p in live_service().store.projects(owner)}
    for (payload,) in records:
        row = json.loads(payload)
        row.update(project_id=registered.get("admin/tnqd-sut"), delivery_id=row["delivery"], title="TNQD — cải thiện tìm kiếm", repository="admin/tnqd-sut", legacy=True)
        row["changed_files"] = row.get("handover", {}).get("changed_files", [])
        from langflow.adlc.tnqd_demo import public_run as legacy_public
        result.append(legacy_public(row))
    return result


@router.get("/repositories")
async def repositories(actor: TeamUser, response: Response, session: DbSession):
    response.headers["Cache-Control"] = "no-store"
    await session.commit()
    try:
        return {"items": await Gitea().repositories()}
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/projects")
async def projects(actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"items": [public_project(p) for p in live_service().store.projects(str(actor.id))]}


@router.post("/projects", status_code=201)
async def connect_project(command: ConnectProject, session: DbSession, actor: TeamUser):
    await ensure_project_permission(actor, ProjectAction.CREATE)
    owner = str(actor.id)
    await session.commit()
    if bool(command.repository_id) == bool(command.new_repository_name):
        raise HTTPException(422, {"code": "LIVE_SELECT_EXISTING_OR_NEW_REPOSITORY"})
    try:
        gitea = Gitea()
        repo = await gitea.repository(command.repository_id) if command.repository_id else await gitea.create(command.new_repository_name, command.description)
        service = live_service()
        existing = next((p for p in service.store.projects(owner) if p["repository_id"] == repo["id"]), None)
        if existing:
            return public_project(existing)
        identity = uuid4()
        source_path, commit = await asyncio.to_thread(checkout, owner, str(identity), repo)
        session.add(Folder(id=identity, name=repo["name"] + " · " + str(identity)[:6], description="Gitea: " + repo["full_name"], user_id=actor.id))
        await session.flush()
        session.add(AdlcLocalProject(project_id=identity, owner_id=owner, source_path=source_path))
        await session.commit()
        return public_project(service.store.save_project(owner, str(identity), repo, source_path, commit))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/runs")
async def history(actor: TeamUser, response: Response, project_id: UUID | None = None, delivery_id: UUID | None = None):
    response.headers["Cache-Control"] = "no-store"
    service = live_service()
    rows = [public_run(service.observe(r)) for r in service.store.runs(str(actor.id), str(project_id) if project_id else None, str(delivery_id) if delivery_id else None)]
    rows += [r for r in legacy_runs(str(actor.id)) if (not project_id or r["project_id"] == str(project_id)) and (not delivery_id or r["delivery_id"] == str(delivery_id))]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"items": rows}


@router.get("/runs/{identity}")
async def read_run(identity: UUID, actor: TeamUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    service = live_service()
    try:
        return public_run(service.observe(service.store.get(str(actor.id), str(identity))))
    except ServiceCheckError as exc:
        old = next((r for r in legacy_runs(str(actor.id)) if r["run_id"] == str(identity)), None)
        if old:
            return old
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs", status_code=202)
async def plan(command: PlanCommand, session: DbSession, actor: TeamUser):
    row, flow = await source(session, command.delivery_id, actor, write=True)
    if not await permission(actor, flow, FlowAction.EXECUTE):
        raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
    if flow.folder_id != command.project_id:
        raise HTTPException(409, {"code": "LIVE_PROJECT_DELIVERY_MISMATCH"})
    owner, requirement, title = str(actor.id), row.requirement, row.title
    await session.commit()
    service = live_service()
    try:
        try:
            existing = service.store.get(owner, str(command.run_id))
        except ServiceCheckError as exc:
            if exc.status != 404:
                raise
        else:
            previous_workflow = existing.get("workflow") or {}
            if existing["project_id"] != str(command.project_id) or existing["delivery_id"] != str(command.delivery_id) or existing["requirement"] != requirement or previous_workflow.get("workflow_id") != (str(command.workflow_id) if command.workflow_id else None) or previous_workflow.get("digest") != command.workflow_digest:
                raise ServiceCheckError("LIVE_RUN_ID_CONFLICT")
            return public_run(service.observe(existing))
        project = service.store.project(owner, str(command.project_id))
        workflow = selected_workflow(service, owner, command.project_id, command.workflow_id, command.workflow_digest)
        repo = await Gitea().repository(project["repository_id"])
        _, commit = await asyncio.to_thread(checkout, owner, project["project_id"], repo)
        environment = service.environments.freeze(owner, str(command.project_id))
        value, fresh = service.store.create(owner, project, str(command.delivery_id), str(command.run_id), requirement, title, commit, workflow, environment=environment)
        if fresh:
            service.spawn(value)
        return public_run(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/workflow")
async def apply_workflow(identity: UUID, command: ApplyWorkflowCommand, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.observe(service.store.get(str(actor.id), str(identity)))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        if row["run_id"] in service.tasks:
            raise ServiceCheckError("LIVE_PLANNING_FINISHING")
        workflow = selected_workflow(service, str(actor.id), row["project_id"], command.workflow_id, command.workflow_digest)
        return public_run(service.store.revise_plan(str(actor.id), row["run_id"], command.plan_digest, workflow))
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/reconcile")
async def reconcile(identity: UUID, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.observe(service.store.get(str(actor.id), str(identity)))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        if row["state"] != "UNCONFIRMED" or row["run_id"] in service.tasks:
            return public_run(row)
        import psutil
        pid = row.get("worker_pid")
        if pid and psutil.pid_exists(pid):
            try:
                if any("project_worker.py" in part for part in psutil.Process(pid).cmdline()):
                    return public_run(row)
            except psutil.Error:
                raise ServiceCheckError("LIVE_WORKER_STATE_UNCONFIRMED") from None
        from dsh_web_sdk import DshClient, RetryConfig
        base, token = settings()
        async with DshClient(base, token, timeout=20, retry=RetryConfig(max_attempts=1)) as client:
            contracts = await asyncio.wait_for(scoped_contracts(client, row), timeout=30)
        if any(c.get("status") not in {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"} for c in contracts):
            return public_run(row)
        if service.recovery.inspect(row).get("available"):
            return public_run(row)
        # No agent is replayed. Preserve the interrupted receipt and permit a fresh run.
        row = service.store.update(row["run_id"], {"state": "FAILED", "error_code": "LIVE_INTERRUPTED_RUN_CLOSED"})
        return public_run(row)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/execute", status_code=202)
async def execute(identity: UUID, command: ExecuteCommand, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.observe(service.store.get(str(actor.id), str(identity)))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        if row["phase"] == "execution":
            if row.get("approved_plan_digest") != command.plan_digest:
                raise ServiceCheckError("LIVE_APPROVED_PLAN_CHANGED")
            if command.model_route and command.model_route.model_dump() != row.get("model_route"):
                raise ServiceCheckError("LIVE_MODEL_ROUTE_CHANGED")
            return public_run(row)
        if row["state"] != "PLAN_READY" or row["plan"]["digest"] != command.plan_digest:
            raise ServiceCheckError("LIVE_PLAN_NOT_READY_OR_CHANGED")
        if row["run_id"] in service.tasks:
            raise ServiceCheckError("LIVE_PLANNING_FINISHING")
        route = await validated_execution_model(command.model_route)
        row, fresh = service.store.begin_execution(str(actor.id), row["run_id"], command.plan_digest, model_route=route)
        if fresh:
            if row.get("issue", {}).get("proposal_id"):
                service.issue_service.store.record_event(str(actor.id), row["project_id"], row["issue"]["proposal_id"], "manual_approved", {"actor": str(actor.id), "run_id": row["run_id"], "plan_digest": command.plan_digest})
            service.spawn(row)
        return public_run(row)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/retry", status_code=202)
async def retry_run(identity: UUID, command: RetryCommand, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.observe(service.store.get(str(actor.id), str(identity)))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        if row["state"] != "FAILED" or not row.get("approved_plan_digest") or row["run_id"] in service.tasks:
            raise ServiceCheckError("LIVE_RETRY_REQUIRES_STOPPED_APPROVED_RUN")
        route = await validated_execution_model(command.model_route) or row.get("model_route")
        from dsh_web_sdk import DshClient, RetryConfig
        base, token = settings()
        owned = {n.get("session_id") for n in row.get("nodes", []) if n.get("session_id")}
        if owned:
            async with DshClient(base, token, timeout=20, retry=RetryConfig(max_attempts=1)) as client:
                accepted = await asyncio.wait_for(asyncio.gather(*(client.session(identity).cancel() for identity in owned)), timeout=30)
            if not all(accepted):
                raise ServiceCheckError("LIVE_OWNED_AGENT_STOP_UNCONFIRMED")
        project = service.store.project(str(actor.id), row["project_id"])
        value, fresh = service.store.create(str(actor.id), project, row["delivery_id"], str(command.run_id), row["requirement"], row["title"], row["base_commit"], row.get("workflow"), environment=row.get("environment"))
        if fresh:
            value = service.store.update(value["run_id"], {"parent_run_id": row["run_id"], "phase": "execution", "state": "RUNNING", "plan": row["plan"], "documents": row["documents"], "approved_plan_digest": row["approved_plan_digest"], "approved_by": str(actor.id), "model_route": route, **({"origin_document": row["origin_document"]} if row.get("origin_document") else {})})
            service.spawn(value)
        elif value.get("parent_run_id") != row["run_id"] or value.get("approved_plan_digest") != row["approved_plan_digest"]:
            raise ServiceCheckError("LIVE_RUN_ID_CONFLICT")
        elif command.model_route and value.get("model_route") != route:
            raise ServiceCheckError("LIVE_MODEL_ROUTE_CHANGED")
        if value.get("origin_document"):
            from langflow.adlc.document_intake import document_intake
            try:
                document_intake().follow_retry(str(actor.id), value["origin_document"]["document_id"], row["run_id"], value["run_id"])
            except ServiceCheckError:
                # The native retry remains valid if its inbox record was removed.
                pass
        return public_run(value)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.get("/runs/{identity}/patch")
async def patch(identity: UUID, actor: TeamUser):
    try:
        row = live_service().store.get(str(actor.id), str(identity))
        return PlainTextResponse(row.get("diff", ""), headers={"Content-Disposition": f'attachment; filename="pokedev-{identity}.patch"'})
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None


@router.post("/runs/{identity}/publish")
async def publish(identity: UUID, session: DbSession, actor: TeamUser):
    service = live_service()
    try:
        row = service.store.get(str(actor.id), str(identity))
        _, flow = await source(session, UUID(row["delivery_id"]), actor, write=True)
        if not await permission(actor, flow, FlowAction.EXECUTE):
            raise HTTPException(403, {"code": "LIVE_EXECUTION_DENIED"})
        await session.commit()
        if row.get("published"):
            return row["published"]
        if row["state"] != "SUCCEEDED":
            raise ServiceCheckError("LIVE_VERIFIED_RESULT_REQUIRED")
        from langflow.adlc.project_recovery import candidate_path
        candidate = candidate_path(row)
        if not row.get("file_hashes") or set(row["file_hashes"]) != set(row.get("changed_files", [])):
            raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
        for path, expected in row["file_hashes"].items():
            file = candidate / path
            actual = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() and not file.is_symlink() else None
            if not safe_path(path) or actual != expected or (expected is None and file.exists()):
                raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
        branch = "codex/pokedev-" + str(identity)[:12]
        project = service.store.project(str(actor.id), row["project_id"])
        # Publish to the trusted Gitea remote, never to the local source cache.
        from langflow.adlc.gitea_projects import configuration
        remote = configuration()[0] + "/" + project["repository"] + ".git"
        def push():
            with service.publish_locks.setdefault(row["run_id"], threading.Lock()):
                current = service.store.get(str(actor.id), row["run_id"])
                intent = current.get("publish_intent")
                if not intent:
                    intent = {"branch": branch, "commit": None}
                    service.store.update(row["run_id"], {"publish_intent": intent})
                if not intent.get("commit"):
                    if not git(candidate, "branch", "--list", branch):
                        git(candidate, "switch", "-c", branch)
                    if git(candidate, "branch", "--show-current") != branch:
                        raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
                    head = git(candidate, "rev-parse", "HEAD")
                    if head == row["base_commit"]:
                        git(candidate, "add", "--", *row["changed_files"])
                        git(candidate, "-c", "user.name=PokeDev", "-c", "user.email=pokedev@localhost", "commit", "-m", row["title"][:120])
                    else:
                        parents = git(candidate, "rev-list", "--parents", "-n", "1", "HEAD").split()
                        changed = set(git(candidate, "diff", "--name-only", "-z", row["base_commit"], "HEAD", raw=True).strip("\0").split("\0"))
                        if parents[1:] != [row["base_commit"]] or changed != set(row["changed_files"]) or git(candidate, "status", "--porcelain"):
                            raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
                    intent = {"branch": branch, "commit": git(candidate, "rev-parse", "HEAD")}
                    service.store.update(row["run_id"], {"publish_intent": intent})
                commit = intent["commit"]
                if git(candidate, "rev-parse", "HEAD") != commit or intent["branch"] != branch:
                    raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
                git(candidate, "push", "--", remote, commit + ":refs/heads/" + branch, network=True)
                return commit
        commit = await asyncio.to_thread(push)
        published = {"branch": branch, "commit": commit, "url": project["repository_url"] + "/src/branch/" + branch}
        service.store.update(row["run_id"], {"published": published})
        return published
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

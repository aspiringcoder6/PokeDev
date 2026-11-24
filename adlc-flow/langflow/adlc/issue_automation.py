"""Detect Gitea issues and run only work authorized by a project's own policy."""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import time
from uuid import UUID, uuid4, uuid5

from langflow.adlc.gitea_projects import Gitea
from langflow.adlc.issue_store import IssueStore, eligible, issue_requirement, public_proposal
from langflow.adlc.issue_policy import AUTOMATIC_MODES
from langflow.adlc.live_workflows import ACTIVE
from langflow.adlc.vai_services import ServiceCheckError


async def authorize_project(live, session, actor, identity, *, write=False):
    from langflow.services.authorization import ProjectAction, ensure_project_permission
    from langflow.services.database.models.folder.model import Folder
    from langflow.services.database.models.auth.team_access import AdlcProjectAccess

    project = live.store.project(str(actor.id), str(identity))
    folder = await session.get(Folder, UUID(project["project_id"]))
    if not getattr(actor, "is_active", False) or folder is None or folder.user_id != actor.id:
        raise ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404)
    if await session.get(AdlcProjectAccess, folder.id):
        raise ServiceCheckError("DELIVERY_TEAM_ADAPTER_REQUIRED", 403)
    await ensure_project_permission(
        actor,
        ProjectAction.WRITE if write else ProjectAction.READ,
        project_id=folder.id,
        project_user_id=folder.user_id,
        workspace_id=folder.workspace_id,
    )
    return project


class IssueRunner:
    """Reuse the normal flow, delivery, planning and verification path."""

    def __init__(self, live):
        self.live = live

    async def actor(self, session, owner):
        from langflow.services.database.models.user.model import User

        actor = await session.get(User, UUID(owner))
        if actor is None or not actor.is_active:
            raise ServiceCheckError("ISSUE_OWNER_UNAVAILABLE", 403)
        return actor

    async def start_plan(self, proposal, policy):
        from langflow.api.v1 import adlc_live, adlc_delivery
        from langflow.api.v1.authz_route_dependencies import require_flow_create_permission
        from langflow.api.v1.flows_helpers import _new_flow
        from langflow.adlc.delivery import CreateDelivery
        from langflow.services.database.models.flow.model import Flow, FlowCreate
        from langflow.services.deps import get_storage_service, session_scope

        async with session_scope() as session:
            actor = await self.actor(session, proposal["owner"])
            project = await authorize_project(self.live, session, actor, proposal["project_id"], write=True)
            title, requirement = issue_requirement(
                project, proposal["issue"], proposal.get("clarification"), policy if proposal.get("automatic") else None
            )
            flow_id = uuid5(UUID(proposal["run_id"]), "issue-flow")
            flow = await session.get(Flow, flow_id)
            if flow is None:
                definition = FlowCreate(
                    name=f"{title[:120]} · {str(flow_id)[:8]}",
                    description=requirement,
                    folder_id=UUID(project["project_id"]),
                    is_component=False,
                    mcp_enabled=False,
                    data={
                        "nodes": [],
                        "edges": [],
                        "viewport": {"x": 0, "y": 0, "zoom": 1},
                        "adlc": {
                            "document_type": "WORKFLOW_DEFINITION",
                            "schema_version": "0.1",
                            "workflow_definition_id": "",
                            "version": 1,
                            "status": "DRAFT",
                            "default_policies": {},
                            "metadata": {},
                        },
                    },
                )
                destination = await require_flow_create_permission(actor, definition, session)
                definition.workspace_id, definition.folder_id = destination
                await _new_flow(
                    session=session,
                    flow=definition,
                    user_id=actor.id,
                    storage_service=get_storage_service(),
                    flow_id=flow_id,
                    validate_folder=True,
                    widen_for_authz=True,
                    propagate_unhandled_errors=True,
                )
                flow = await session.get(Flow, flow_id)
            if flow is None or flow.user_id != actor.id or str(flow.folder_id) != project["project_id"]:
                raise ServiceCheckError("ISSUE_FLOW_BINDING_CHANGED")
            delivery = await adlc_delivery.create_delivery(
                CreateDelivery(flow_id=flow_id, title=title, requirement=requirement), session, actor
            )
            workflow = (
                self.live.store.workflow(proposal["owner"], policy["workflow_id"])
                if policy.get("workflow_id")
                else None
            )
            command = adlc_live.PlanCommand(
                run_id=UUID(proposal["run_id"]),
                project_id=UUID(project["project_id"]),
                delivery_id=UUID(delivery["id"]),
                workflow_id=UUID(workflow["workflow_id"]) if workflow else None,
                workflow_digest=workflow["digest"] if workflow else None,
            )
            await adlc_live.plan(command, session, actor)
            metadata = {
                "issue_triage": proposal["triage"],
                "issue_risk": proposal["risk"],
            }
            if proposal.get("automatic"):
                metadata["auto_timing"] = {"limit_seconds": policy["auto_max_active_minutes"] * 60, "active_seconds": 0}
            return self.live.store.update(
                proposal["run_id"],
                {
                    "issue": {
                        "proposal_id": proposal["proposal_id"],
                        "number": proposal["issue"]["number"],
                        "url": proposal["issue"]["url"],
                        "title": proposal["issue"]["title"],
                        "source_digest": proposal["source_digest"],
                        "revision": proposal["revision"],
                        "triage_digest": proposal["triage"]["input_digest"],
                    },
                    "issue_policy_revision": policy["revision"],
                    **metadata,
                },
            )

    async def execute(self, proposal, store):
        from langflow.api.v1.adlc_delivery import source, permission
        from langflow.services.authorization import FlowAction
        from langflow.services.deps import session_scope

        async with session_scope() as session:
            actor = await self.actor(session, proposal["owner"])
            await authorize_project(self.live, session, actor, proposal["project_id"], write=True)
            run = self.live.observe(self.live.store.get(proposal["owner"], proposal["run_id"]))
            _, flow = await source(session, UUID(run["delivery_id"]), actor, write=True)
            if not await permission(actor, flow, FlowAction.EXECUTE):
                raise ServiceCheckError("LIVE_EXECUTION_DENIED", 403)
            await session.commit()
            if run["run_id"] in self.live.tasks:
                raise ServiceCheckError("LIVE_PLANNING_FINISHING")
            policy = store.settings(proposal["owner"], proposal["project_id"])
            if policy.get("workflow_id"):
                workflow = self.live.store.workflow(proposal["owner"], policy["workflow_id"])
                if (run.get("workflow") or {}).get("digest") != workflow["digest"]:
                    raise ServiceCheckError("ISSUE_WORKFLOW_CHANGED")
            row, fresh = self.live.store.begin_execution(
                proposal["owner"],
                run["run_id"],
                run["plan"]["digest"],
                guard=lambda db, value: store.guard_auto_execution(db, proposal, value),
            )
            if fresh:
                self.live.spawn(row)
            return row


class IssueService:
    def __init__(self, live, *, gitea=None, runner=None):
        self.live = live
        self.store = IssueStore(live.store)
        self.gitea = gitea or Gitea()
        self.runner = runner or IssueRunner(live)
        self.instance = str(uuid4())
        self.task = None
        self.locks = {}
        self.last_scan = {}

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def projects(self):
        with closing(self.live.store.db()) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM projects")]

    def has_active_run(self, owner, project):
        return any(self.live.observe(row)["state"] in ACTIVE for row in self.live.store.runs(owner, project))

    async def scan(self, project):
        owner, identity = project["owner"], project["project_id"]
        async with self.locks.setdefault(identity, asyncio.Lock()):
            policy = self.store.settings(owner, identity)
            seen, truncated = set(), False
            try:
                repo = await self.gitea.repository(project["repository_id"])
                if repo["full_name"] != project["repository"]:
                    raise ServiceCheckError("ISSUE_REPOSITORY_CHANGED")
                for page in range(1, 21):
                    rows = await self.gitea.request(
                        "GET", f"/repos/{project['repository']}/issues?state=open&type=issues&limit=50&page={page}"
                    )
                    if not isinstance(rows, list):
                        raise ServiceCheckError("ISSUE_SOURCE_INVALID", 503)
                    for issue in rows:
                        value = self.store.ingest(owner, project, issue, policy)
                        if value:
                            seen.add(value["issue"]["number"])
                    if len(rows) < 50:
                        break
                    if page == 20:
                        truncated = True
                if not truncated:
                    self.store.mark_missing_closed(owner, identity, seen)
                self.store.scan_status(owner, identity, truncated=truncated)
                self.last_scan[identity] = time.monotonic()
            except ServiceCheckError as exc:
                self.store.scan_status(owner, identity, error=exc.code)
                self.last_scan[identity] = time.monotonic()
                raise
        return self.list(owner, identity)

    async def refresh(self, project, proposal):
        raw = await self.gitea.request("GET", f"/repos/{project['repository']}/issues/{proposal['issue']['number']}")
        value = self.store.ingest(
            project["owner"], project, raw, self.store.settings(project["owner"], project["project_id"])
        )
        if value is None:
            raise ServiceCheckError("ISSUE_SOURCE_INVALID")
        return value

    def list(self, owner, project):
        self.live.store.project(owner, project)
        values = []
        for row in self.store.proposals(owner, project):
            plan = None
            if row.get("run_id"):
                try:
                    run = self.live.observe(self.live.store.get(owner, row["run_id"]))
                except ServiceCheckError:
                    run = None
                if run:
                    plan = run.get("plan")
                    state = "CLOSED" if row["issue"]["state"] != "open" else run["state"]
                    if row["state"] != state:
                        row = self.store.update(owner, project, row["proposal_id"], state=state)
            assessed = self.store.assess(owner, project, row["proposal_id"], plan)
            row = {
                **assessed,
                **(
                    {"run_state": run["state"], "run_error": run.get("error_code")} if row.get("run_id") and run else {}
                ),
            }
            values.append(public_proposal(row))
        return {
            "items": values,
            "settings": self.store.settings(owner, project),
            "automation_usage": self.store.usage(owner, project),
        }

    async def prepare(self, owner, project_id, proposal_id, expected_digest, *, automatic=False):
        project = self.live.store.project(owner, project_id)
        async with self.locks.setdefault(project_id, asyncio.Lock()):
            before = self.store.get(owner, project_id, proposal_id)
            if before.get("run_id"):
                try:
                    self.live.store.get(owner, before["run_id"])
                    return public_proposal(before)
                except ServiceCheckError as exc:
                    if exc.status != 404:
                        raise
                if before.get("lease_until", 0) > time.time():
                    raise ServiceCheckError("ISSUE_PREPARING")
                # No run was ever created: deterministic flow/run identities make
                # recovery of an interrupted metadata transaction safe.
                before = self.store.update(owner, project_id, proposal_id, state="DETECTED", run_id=None, lease_until=0)
            if before["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            current = await self.refresh(project, before)
            current = self.store.assess(owner, project_id, proposal_id)
            policy = self.store.settings(owner, project_id)
            if current["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            if not eligible(current["issue"], policy):
                raise ServiceCheckError("ISSUE_NOT_ELIGIBLE")
            if self.has_active_run(owner, project_id):
                raise ServiceCheckError("LIVE_PROJECT_RUN_ACTIVE")
            if current["triage"]["action"] != "ready":
                raise ServiceCheckError(current["auto_decision"]["code"])
            issue_requirement(project, current["issue"], current.get("clarification"), policy if automatic else None)
            claimed, fresh = self.store.claim(
                owner, project_id, proposal_id, expected_digest, self.instance, policy, automatic=automatic
            )
            if not fresh:
                return public_proposal(claimed)
            try:
                run = await self.runner.start_plan(claimed, policy)
                value = self.store.update(
                    owner,
                    project_id,
                    proposal_id,
                    expected_digest=expected_digest,
                    state=run["state"],
                    lease_until=0,
                    lease_owner=None,
                    error_code=None,
                )
                self.store.record_event(
                    owner,
                    project_id,
                    proposal_id,
                    "planned",
                    {"run_id": run["run_id"], "automatic": automatic, "triage_digest": claimed["triage_digest"]},
                )
                return public_proposal(value)
            except Exception as exc:
                code = getattr(exc, "code", None)
                detail = getattr(exc, "detail", None)
                if not code and isinstance(detail, dict):
                    code = detail.get("code")
                code = code or "ISSUE_PREPARATION_FAILED"
                try:
                    run = self.live.store.get(owner, claimed["run_id"])
                except ServiceCheckError:
                    run = None
                self.store.update(
                    owner,
                    project_id,
                    proposal_id,
                    expected_digest=expected_digest,
                    state=run["state"] if run else "ERROR",
                    run_id=claimed["run_id"] if run else None,
                    lease_until=0,
                    lease_owner=None,
                    error_code=code,
                )
                if isinstance(exc, ServiceCheckError):
                    raise
                raise ServiceCheckError(code, 503) from None

    async def clarify(self, owner, project_id, proposal_id, expected_digest, answers, approach):
        project = self.live.store.project(owner, project_id)
        async with self.locks.setdefault(project_id, asyncio.Lock()):
            before = self.store.get(owner, project_id, proposal_id)
            current = await self.refresh(project, before)
            if current["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            return public_proposal(
                self.store.clarify(owner, project_id, proposal_id, expected_digest, answers, approach)
            )

    async def advance(self, project):
        owner, identity = project["owner"], project["project_id"]
        policy = self.store.settings(owner, identity)
        if not policy["watch_issues"] or policy["mode"] not in AUTOMATIC_MODES:
            return
        for raw in self.store.proposals(owner, identity):
            if not raw.get("run_id"):
                continue
            try:
                run = self.live.observe(self.live.store.get(owner, raw["run_id"]))
            except ServiceCheckError:
                continue
            if run["state"] != "PLAN_READY" or raw.get("review_reason"):
                continue
            if self.has_active_run(owner, identity):
                return
            if raw.get("policy_revision") != policy["revision"] or not raw.get("automatic"):
                self.store.update(
                    owner,
                    identity,
                    raw["proposal_id"],
                    review_reason="ISSUE_AUTO_POLICY_CHANGED" if raw.get("automatic") else "ISSUE_MANUAL_PLAN_REVIEW",
                )
                continue
            try:
                current = await self.refresh(project, raw)
                if current["source_digest"] != raw["source_digest"] or not eligible(current["issue"], policy):
                    raise ServiceCheckError("ISSUE_CHANGED")
                current = self.store.assess(owner, identity, raw["proposal_id"], run["plan"])
                await self.runner.execute(current, self.store)
            except ServiceCheckError as exc:
                if exc.code not in {"LIVE_PLANNING_FINISHING", "LIVE_PROJECT_RUN_ACTIVE"}:
                    self.store.update(owner, identity, raw["proposal_id"], review_reason=exc.code)
            return
        if self.has_active_run(owner, identity):
            return
        candidates = []
        for row in self.store.proposals(owner, identity):
            if row["state"] == "STARTING" and row.get("run_id") and row.get("lease_until", 0) < time.time():
                try:
                    self.live.store.get(owner, row["run_id"])
                except ServiceCheckError as exc:
                    if exc.status == 404:
                        row = self.store.update(
                            owner, identity, row["proposal_id"], run_id=None, state="DETECTED", lease_until=0
                        )
            if row["state"] != "DETECTED" or row.get("run_id") or not eligible(row["issue"], policy):
                continue
            row = self.store.assess(owner, identity, row["proposal_id"])
            if row["auto_decision"]["allowed"]:
                candidates.append(row)
        if candidates:
            row = min(candidates, key=lambda r: r["issue"]["number"])
            if self.store.usage(owner, identity)["next_available_at"]:
                self.store.update(owner, identity, row["proposal_id"], review_reason="ISSUE_AUTO_BUDGET_EXHAUSTED")
                return
            try:
                await self.prepare(owner, identity, row["proposal_id"], row["source_digest"], automatic=True)
            except ServiceCheckError as exc:
                if exc.code == "ISSUE_AUTO_BUDGET_EXHAUSTED":
                    self.store.update(owner, identity, row["proposal_id"], review_reason=exc.code)
                elif exc.code not in {
                    "LIVE_PROJECT_RUN_ACTIVE",
                    "ISSUE_PREPARING",
                    "ISSUE_PROPOSAL_NOT_READY",
                    "ISSUE_AUTO_POLICY_CHANGED",
                }:
                    self.store.update(owner, identity, row["proposal_id"], state="ERROR", error_code=exc.code)

    async def loop(self):
        from langflow.services.deps import session_scope

        while True:
            for project in self.projects():
                try:
                    policy = self.store.settings(project["owner"], project["project_id"])
                    if not policy["watch_issues"]:
                        continue
                    async with session_scope() as session:
                        actor = await self.runner.actor(session, project["owner"])
                        await authorize_project(self.live, session, actor, project["project_id"])
                    if time.monotonic() - self.last_scan.get(project["project_id"], -60) >= 60:
                        await self.scan(project)
                    await self.advance(project)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.store.scan_status(
                        project["owner"], project["project_id"], error=getattr(exc, "code", "ISSUE_WATCH_UNAVAILABLE")
                    )
            await asyncio.sleep(5)

    def attention(self, owner):
        result = []
        for project in self.live.store.projects(owner):
            for row in self.list(owner, project["project_id"])["items"]:
                if row["state"] in {"DETECTED", "NEEDS_CONTEXT", "NEEDS_SPEC", "ERROR"} and not row.get("run_id"):
                    result.append(
                        {
                            "request_id": "issue:" + row["proposal_id"] + ":" + row["triage"]["input_digest"],
                            "run_id": "",
                            "project_id": row["project_id"],
                            "proposal_id": row["proposal_id"],
                            "run_title": f"#{row['issue']['number']}: {row['issue']['title']}",
                            "kind": "issue",
                            "title": "Issue Gitea cần bạn bổ sung thông tin"
                            if row["state"] in {"NEEDS_CONTEXT", "NEEDS_SPEC"}
                            else "Issue Gitea đang chờ bạn xem",
                        }
                    )
        return result

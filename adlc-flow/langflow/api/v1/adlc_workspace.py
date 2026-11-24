"""Read-only, permission-filtered workspace statistics and action inbox."""
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from langflow.adlc.issue_automation import authorize_project
from langflow.adlc.live_workflows import live_service
from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.workspace_dashboard import metadata, project_rows, summarize
from langflow.api.utils import DbSession
from langflow.api.v1.adlc_delivery import source, permission
from langflow.api.v1.adlc_team_access import TeamUser
from langflow.services.authorization import FlowAction

router = APIRouter(tags=["Workspace dashboard"])


def denied(exc):
    return getattr(exc, "status_code", getattr(exc, "status", None)) in {403, 404}


@router.get("/dashboard")
async def dashboard(session: DbSession, actor: TeamUser, response: Response, days: int = 28, project_id: UUID | None = None):
    response.headers["Cache-Control"] = "no-store"
    if days not in {7, 28}:
        raise HTTPException(422, {"code": "LIVE_DASHBOARD_RANGE_INVALID"})
    service, owner = live_service(), str(actor.id)
    allowed, projects, capabilities, flows = set(), [], {}, {}
    selected = str(project_id) if project_id else None
    try:
        candidates = service.store.projects(owner)
        if selected:
            service.store.project(owner, selected)  # Unknown selection must not fall back to all projects.
        for project in candidates:
            identity = project["project_id"]
            try:
                await authorize_project(service, session, actor, identity)
            except (ServiceCheckError, HTTPException) as exc:
                if not denied(exc) or selected == identity:
                    raise
                continue
            projects.append(project)
            allowed.add(identity)
            try:
                await authorize_project(service, session, actor, identity, write=True)
                capabilities["project:" + identity] = True
            except (ServiceCheckError, HTTPException) as exc:
                if not denied(exc):
                    raise
                capabilities["project:" + identity] = False
        rows = []
        async def accept(raw):
            pid = raw.get("project_id")
            if (pid and pid not in allowed) or (selected and pid != selected):
                return
            delivery = raw.get("delivery_id")
            if not delivery:
                return
            if delivery not in flows:
                try:
                    _, flow = await source(session, UUID(delivery), actor)
                    writable = await permission(actor, flow, FlowAction.WRITE)
                    executable = await permission(actor, flow, FlowAction.EXECUTE)
                    flows[delivery] = (flow, writable and executable)
                except (ServiceCheckError, HTTPException) as exc:
                    if not denied(exc):
                        raise
                    flows[delivery] = None
                except ValueError:
                    flows[delivery] = None
            binding = flows[delivery]
            if binding is None:
                return
            if not raw.get("legacy") and str(binding[0].folder_id) != str(pid):
                return
            current = raw if raw.get("legacy") else service.observe(raw)
            capabilities[current["run_id"]] = binding[1]
            value = metadata(current)
            if value["state"] == "UNCONFIRMED" and not value.get("legacy"):
                value["recovery_status"] = service.recovery.inspect(current)
            rows.append(value)
        for row in project_rows(service.store, owner, allowed):
            await accept(row)
        # Keep the existing legacy history visible without exposing any other owner's records.
        from langflow.api.v1.adlc_live import legacy_runs
        for row in legacy_runs(owner):
            await accept(row)
        await session.commit()
        monitor = service.human_input
        monitor.start()
        sources = {"native_connected": monitor.connected.is_set(), "errors": []}
        if not sources["native_connected"] and any(row["state"] in {"RUNNING", "PLANNING"} for row in rows):
            sources["errors"].append("questions_disconnected")
        try:
            requests = monitor.pending(owner)
        except Exception:
            requests = []
            sources["errors"].append("questions")
        try:
            reviews = await monitor.legacy_reviews(owner)
        except Exception:
            reviews = []
            sources["errors"].append("advanced_reviews")
        try:
            issue_reviews = service.issue_service.attention(owner)
            for review in issue_reviews:
                if review.get("project_id") not in allowed:
                    continue
                try:
                    proposal = service.issue_service.store.get(owner, review["project_id"], review["proposal_id"])
                    review = {**review, "created_at": proposal.get("created_at")}
                except (ServiceCheckError, KeyError):
                    pass
                reviews.append(review)
        except Exception:
            sources["errors"].append("issues")
        workflows = [w for w in service.store.workflows(owner) if w["project_id"] in allowed]
        return summarize(projects, rows, workflows, requests, reviews, days=days, project_id=selected, permissions=capabilities, sources=sources)
    except ServiceCheckError as exc:
        raise HTTPException(exc.status, {"code": exc.code}) from None

"""Project-scoped views and durable commands for the existing shared Workloop.

Old Workloop jobs do not retain their repository context. Only an administrator
may explicitly bind one; listing a project never exposes other shared jobs.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import os
import re
import sqlite3
import time
from urllib.parse import quote

import httpx
import yaml

from langflow.adlc.gitea_projects import DATA, Gitea
from langflow.adlc.human_inputs import normalize_request, validate_answer
from langflow.adlc.vai_services import ServiceCheckError, now, redact
from langflow.adlc.workloop_integration import checked_url

JOB_ID = re.compile(r"^job-[a-zA-Z0-9-]{1,80}$")
ACTIVE = {"in_progress", "running", "suspended"}
JOB_STATES = {"in_progress": "RUNNING", "running": "RUNNING", "completed": "COMPLETED", "failed": "FAILED", "interrupted": "INTERRUPTED", "suspended": "SUSPENDED"}
NODE_STATES = {"PENDING", "IN_PROGRESS", "DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT", "SKIPPED", "FAILED"}


def obj(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def text(value, limit=4000):
    # Reports can include shell output or pasted credentials. Never return raw events.
    value = str(redact(value if isinstance(value, (dict, list)) else str(value or "")))[:limit]
    value = re.sub(r"(?i)\b(?:ghp_|gitea_|xox[baprs]-)[A-Za-z0-9_-]+", "[redacted]", value)
    value = re.sub(r"(?i)((?:password|secret|api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", value)
    return value


def job_summary(job):
    return {"job_id": job["job_id"], "workflow": text(job.get("wf_name"), 160), "version": job.get("wf_version"),
            "state": JOB_STATES.get(str(job.get("status", "")).lower(), "UNKNOWN"),
            "created_at": job.get("created_at"), "updated_at": job.get("updated_at")}


def missing_snapshot(job):
    meta = obj(job.get("meta"))
    ids = meta.get("nodes", [])
    ids = [n for n in ids if isinstance(n, str)][:200] if isinstance(ids, (dict, list)) else []
    sha = meta.get("sha", "")
    return {"commit": sha if re.fullmatch(r"[a-f0-9]{40,64}", str(sha)) else None,
            "state": "unavailable", "tasks": [{"id": n, "title": n, "role": "Agent"} for n in ids], "edges": []}


class WorkloopClient:
    def __init__(self):
        self.base = checked_url(os.getenv("VAI_WORKLOOP_URL", "http://10.0.10.195:8903"))

    async def request(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, self.base + "/api/v1" + path, json=body)
            if response.status_code == 404:
                raise ServiceCheckError("WORKLOOP_JOB_NOT_FOUND", 404)
            if response.status_code in {400, 409, 422}:
                raise ServiceCheckError("WORKLOOP_ACTION_REJECTED", 409)
            response.raise_for_status()
            if len(response.content) > 8_000_000:
                raise ValueError()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError()
            return body
        except (httpx.HTTPError, ValueError):
            raise ServiceCheckError("WORKLOOP_UNAVAILABLE", 503) from None

    async def snapshot(self, job):
        """Read the workflow at the job's recorded Factory commit, never latest."""
        meta = obj(job.get("meta"))
        sha, name = meta.get("sha", ""), job.get("wf_name", "")
        fallback = missing_snapshot(job)
        ids = [n["id"] for n in fallback["tasks"]]
        if not fallback["commit"] or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", name):
            return fallback
        repo = os.getenv("VAI_WORKLOOP_FACTORY_REPOSITORY", "admin/factory-wilson")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            return fallback
        for suffix in ("yaml", "txt"):
            try:
                result = await Gitea().request("GET", f"/repos/{repo}/contents/workflows/{name}.spec.{suffix}?ref={sha}")
                raw = base64.b64decode(result["content"])
                if len(raw) > 500_000:
                    return fallback
                spec = yaml.safe_load(raw)
                if not isinstance(spec, dict):
                    return fallback
                nodes = spec.get("nodes", {})
                if not isinstance(nodes, dict) or set(nodes) != set(ids):
                    return fallback
                tasks = [{"id": n, "title": text(obj(v).get("title") or n, 200), "role": text(obj(v).get("role"), 80),
                          "brief": text(obj(v).get("brief"), 10000)} for n, v in nodes.items()]
                edges = []
                for edge in spec.get("edges", [])[:500]:
                    if isinstance(edge, str):
                        match = re.search(r"([\w-]+)\.[\w-]+\s*->\s*([\w-]+)\.[\w-]+", edge)
                        if match and match[1] in nodes and match[2] in nodes:
                            edges.append({"source": match[1], "target": match[2]})
                return {"commit": sha, "state": "pinned", "tasks": tasks, "edges": edges}
            except (ServiceCheckError, ValueError, KeyError, TypeError, yaml.YAMLError):
                continue
        return fallback


def approval_request(payload, binding, can_respond=True):
    """Recognize only the native request contract; unsupported gates remain visible."""
    event_id = payload.get("event_id")
    native = obj(payload.get("raw"))
    request = payload.get("request") or native.get("request") or obj(payload.get("data")).get("request")
    kind = payload.get("event") or native.get("event") or payload.get("event_type")
    if kind not in {"user-questions/request", "approval/request"}:
        kind = "user-questions/request" if isinstance(request, dict) and "questions" in request else None
    try:
        normalized = normalize_request({"event": kind, "request": request})
    except ValueError:
        return {"request_id": str(event_id), "supported": False, "title": "Yêu cầu cần xử lý tại Workloop", "node_id": text(payload.get("node"), 120)}
    digest = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    return {**redact(normalized), "request_id": str(event_id), "source_digest": digest, "supported": True,
            "run_id": binding["job_id"], "project_id": binding["project_id"], "run_title": binding["title"],
            "node_id": text(payload.get("node"), 120), "node_title": text(payload.get("node"), 200),
            "status": "PENDING", "can_respond": can_respond, "created_at": payload.get("created_at") or binding["linked_at"]}


def project_snapshot(raw, binding, snapshot, pending, reviews=None):
    job = raw["job"]
    tasks = {t["id"]: {**t, "state": "PENDING"} for t in snapshot.get("tasks", [])}
    events = []
    for i, event in enumerate(raw.get("events", [])[-5000:]):
        payload = obj(event.get("payload"))
        node = text(payload["node"], 160) if isinstance(payload.get("node"), str) else ""
        kind = event.get("event_type")
        if kind == "node_review_pending" and payload.get("gate") in tasks:
            node = payload["gate"]
        attempt = node
        original = re.sub(r"--r\d+$", "", node)
        if original != node and original in tasks:
            node = original
        if node == "?":
            node = ""
        at = event.get("created_at") or event.get("ts")
        if node and (node in tasks or len(tasks) < 200):
            task = tasks.setdefault(node, {"id": node, "title": node, "state": "PENDING"})
            if attempt != node and attempt != "?":
                attempts = task.setdefault("attempts", [])
                if attempt not in attempts:
                    attempts.append(attempt)
            if kind in {"node_started", "task_started"}:
                task.update(state="IN_PROGRESS", started_at=at)
            elif kind in {"node_terminal", "node_done", "task_terminal"}:
                state = str(payload.get("status", "")).upper()
                if state in NODE_STATES:
                    task["source_state"] = state
                    # Workloop's final summary may retain an older IN_PROGRESS
                    # after node_terminal already recorded a terminal result.
                    if not (kind != "node_terminal" and state == "IN_PROGRESS" and task["state"] in {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "SKIPPED", "NEEDS_CONTEXT"}):
                        task["state"] = state
                task["completed_at"] = at
                if payload.get("session_ref"):
                    task["session_id"] = text(payload["session_ref"], 200)
            elif kind == "node_review_pending":
                task["state"] = "WAITING_INPUT"
            elif kind in {"node_review_rejected", "node_review_exhausted"}:
                task.update(state="DONE_WITH_CONCERNS", summary=text(payload.get("reason"), 2000))
        if kind in {"node_started", "node_terminal", "node_done", "approval_requested", "approval_answered", "node_review_pending", "node_review_rejected", "node_review_exhausted", "run_start", "run_end", "run_completed", "run_failed", "signal_consumed", "run_suspended", "run_interrupted"}:
            events.append({"id": str(event.get("seq", i)), "kind": kind, "node_id": node, "attempt_id": attempt if attempt != node else None, "at": at, "state": text(payload.get("status"), 60)})
    requests = [approval_request(p, binding, job.get("status") in ACTIVE) for p in pending if p.get("event_id")]
    for review in reviews or []:
        gate, state = review["node_id"], review["state"]
        if gate in tasks:
            tasks[gate]["state"] = {"approved": "DONE", "rejected": "BLOCKED", "pending": "WAITING_INPUT"}.get(state, "NEEDS_CONTEXT")
        if state == "pending":
            request = {"request_id": "gate:" + review["id"], "source_digest": review["digest"], "supported": True,
                       "origin": "workflow_gate", "gate_round": review.get("round"), "kind": "permission", "title": "Cổng duyệt cần quyết định",
                       "tool_name": gate, "prompt": review["prompt"], "details": {"Báo cáo": review["report"]},
                       "run_id": binding["job_id"], "project_id": binding["project_id"], "run_title": binding["title"],
                       "node_id": gate, "node_title": gate, "status": "PENDING", "can_respond": True, "created_at": review["created_at"]}
            requests.append(request)
        elif state == "unknown":
            requests.append({"request_id": "gate:" + review["id"], "supported": False, "title": "Chưa đọc được trạng thái cổng duyệt", "node_id": gate})
    for request in requests:
        if request.get("node_id") in tasks:
            tasks[request["node_id"]]["state"] = "WAITING_INPUT"
    if str(job.get("status", "")).lower() not in ACTIVE:
        for task in tasks.values():
            if task["state"] == "IN_PROGRESS":
                task.update(state="UNCONFIRMED", summary="Lượt đã kết thúc nhưng nguồn vẫn ghi task đang chạy. Cần đối chiếu báo cáo; chưa xác nhận kết quả task.")
    return {**job_summary(job), "project_id": binding["project_id"], "repository": binding["repository"], "title": binding["title"],
            "linked_at": binding["linked_at"], "checked_at": now(), "topology": {k: snapshot.get(k) for k in ("state", "commit", "edges")},
            "tasks": list(tasks.values()), "events": events[-300:], "requests": requests,
            "error": text(job.get("error"), 2000), "verification": "unverified"}


class ProjectWorkloop:
    def __init__(self, path=None, client=None):
        self.path = path or DATA / "workloop.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.client = client or WorkloopClient()
        self.locks = {}
        with self.db() as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS workloop_links(job TEXT PRIMARY KEY, owner TEXT NOT NULL, project TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS workloop_commands(id TEXT PRIMARY KEY, owner TEXT, project TEXT, job TEXT, digest TEXT, payload TEXT)")
            db.execute("CREATE INDEX IF NOT EXISTS workloop_commands_scope ON workloop_commands(owner,project,job)")

    def db(self):
        return closing(sqlite3.connect(self.path, timeout=15))

    def links(self, owner, project):
        with self.db() as db:
            rows = db.execute("SELECT payload FROM workloop_links WHERE owner=? AND project=? ORDER BY rowid DESC", (owner, project)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def projects(self, owner):
        with self.db() as db:
            return [r[0] for r in db.execute("SELECT DISTINCT project FROM workloop_links WHERE owner=?", (owner,)).fetchall()]

    def link(self, owner, project, job):
        if not JOB_ID.fullmatch(job):
            raise ServiceCheckError("WORKLOOP_JOB_NOT_FOUND", 404)
        row = next((r for r in self.links(owner, project) if r["job_id"] == job), None)
        if not row:
            raise ServiceCheckError("WORKLOOP_JOB_NOT_FOUND", 404)
        return row

    def save(self, row):
        with self.db() as db, db:
            db.execute("UPDATE workloop_links SET payload=? WHERE job=? AND owner=? AND project=?", (json.dumps(row), row["job_id"], row["owner"], row["project_id"]))

    async def bind(self, owner, project, job, title):
        if not JOB_ID.fullmatch(job):
            raise ServiceCheckError("WORKLOOP_JOB_NOT_FOUND", 404)
        raw = await self.client.request("GET", "/monitor/jobs/" + job)
        if not isinstance(raw.get("job"), dict) or raw["job"].get("job_id") != job:
            raise ServiceCheckError("WORKLOOP_RESPONSE_INVALID", 502)
        try:
            snapshot = await asyncio.wait_for(self.client.snapshot(raw["job"]), timeout=8)
        except TimeoutError:
            snapshot = missing_snapshot(raw["job"])
        row = {"owner": owner, "project_id": project["project_id"], "repository": project["repository"], "job_id": job,
               "title": text(title, 200), "linked_at": now(), "snapshot": snapshot, "snapshot_checked_at": time.time()}
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT owner,project FROM workloop_links WHERE job=?", (job,)).fetchone()
            if old and old != (owner, project["project_id"]):
                raise ServiceCheckError("WORKLOOP_JOB_ALREADY_LINKED", 409)
            if not old:
                db.execute("INSERT INTO workloop_links VALUES(?,?,?,?)", (job, owner, project["project_id"], json.dumps(row)))
        return await self.read(owner, project["project_id"], job)

    def commands(self, owner, project, job):
        with self.db() as db:
            rows = db.execute("SELECT payload FROM workloop_commands WHERE owner=? AND project=? AND job=? ORDER BY rowid DESC LIMIT 30", (owner, project, job)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_command(self, row):
        with self.db() as db, db:
            db.execute("UPDATE workloop_commands SET payload=? WHERE id=?", (json.dumps(row), row["command_id"]))

    async def reviews(self, raw):
        sources = {}
        for event in raw.get("events", []):
            payload = obj(event.get("payload"))
            if event.get("event_type") == "node_review_pending" and isinstance(payload.get("request_id"), str) and isinstance(payload.get("gate"), str):
                sources[payload["request_id"]] = payload
        result = []
        for identity, source in list(sources.items())[-30:]:
            try:
                record = await self.client.request("GET", "/reviews/" + quote(identity, safe=""))
                event = obj(record.get("event"))
                # Job's own event is the association. A shared review record has
                # no job_id, so check its exact ID and immutable gate/contract.
                if record.get("id") != identity or event.get("kind") != "node_review" or event.get("gate") != source["gate"] or event.get("contract_n") != source.get("contract_n"):
                    raise ServiceCheckError("WORKLOOP_REQUEST_CHANGED", 409)
                result.append({"id": identity, "node_id": source["gate"], "state": record.get("state"),
                               "digest": hashlib.sha256(json.dumps({"id": identity, "event": event, "state": record.get("state")}, sort_keys=True).encode()).hexdigest(),
                               "round": event.get("round"), "prompt": text(event.get("criteria"), 8000), "report": text(event.get("report_summary"), 12000), "created_at": record.get("submitted_at")})
            except ServiceCheckError:
                result.append({"id": identity, "node_id": source["gate"], "state": "unknown"})
        return result

    async def read(self, owner, project, job, *, fresh=False):
        binding = self.link(owner, project, job)
        async with self.locks.setdefault(job, asyncio.Lock()):
            binding = self.link(owner, project, job)
            if not fresh and binding.get("cached") and time.time() - binding.get("fetched_at", 0) < 2:
                return {**binding["cached"], "commands": self.commands(owner, project, job)}
            try:
                raw, approvals = await asyncio.gather(self.client.request("GET", "/monitor/jobs/" + job), self.client.request("GET", f"/monitor/jobs/{job}/approvals"))
                if not isinstance(raw.get("job"), dict) or raw["job"].get("job_id") != job:
                    raise ServiceCheckError("WORKLOOP_RESPONSE_INVALID", 502)
                if binding["snapshot"]["state"] != "pinned" and time.time() - binding.get("snapshot_checked_at", 0) > 300:
                    try:
                        binding["snapshot"] = await asyncio.wait_for(self.client.snapshot(raw["job"]), timeout=8)
                    except TimeoutError:
                        pass
                    binding["snapshot_checked_at"] = time.time()
                # Older Workloop hides even a rejected answer from /approvals.
                # Preserve the original request unless delivery was acknowledged.
                pending = {p["event_id"]: p for p in approvals.get("pending", []) if p.get("event_id")}
                asked, accepted = {}, set()
                for event in raw.get("events", []):
                    payload = obj(event.get("payload"))
                    identity = payload.get("event_id")
                    if event.get("event_type") == "approval_requested" and identity:
                        asked[identity] = payload
                    elif event.get("event_type") == "approval_answered" and identity and payload.get("ok") is True:
                        accepted.add(identity)
                pending.update({k: v for k, v in asked.items() if k not in accepted})
                for identity in accepted:
                    pending.pop(identity, None)
                view = project_snapshot(raw, binding, binding["snapshot"], list(pending.values()), await self.reviews(raw))
                binding["cached"] = view
                binding["fetched_at"] = time.time()
                self.save(binding)
            except ServiceCheckError as exc:
                if exc.status == 404 or not binding.get("cached"):
                    raise
                view = {**binding["cached"], "stale": True, "error_code": exc.code}
                binding.update(cached=view, fetched_at=time.time())
                self.save(binding)
            commands = self.commands(owner, project, job)
            for command in commands:
                if command["state"] == "SENDING" and time.time() - command.get("sent_at", 0) > 30:
                    command.update(state="UNCERTAIN")
                    self.save_command(command)
                target = {"PAUSE": "SUSPENDED", "STOP": "INTERRUPTED", "RESUME": "RUNNING"}.get(command["action"])
                if not view.get("stale") and command["state"] in {"REQUESTED", "UNCERTAIN", "SENDING"} and target == view["state"]:
                    command.update(state="CONFIRMED")
                    self.save_command(command)
                if command["action"] == "ANSWER" and command["state"] in {"CONFIRMED", "UNCERTAIN", "SENDING"}:
                    for request in view.get("requests", []):
                        if request["request_id"] == command.get("request_id"):
                            request["can_respond"] = False
                            request["status"] = "ANSWERED" if command["state"] == "CONFIRMED" else "UNCERTAIN"
            return {**view, "commands": commands}

    async def index(self, owner, project):
        # Read only locally bound jobs. Their details carry pending requests and cache age.
        links = self.links(owner, project)
        semaphore = asyncio.Semaphore(4)
        async def one(link):
            async with semaphore:
                try:
                    return await self.read(owner, project, link["job_id"])
                except ServiceCheckError as exc:
                    return {"job_id": link["job_id"], "project_id": project, "title": link["title"], "state": "UNKNOWN", "stale": True, "error_code": exc.code, "requests": []}
        return {"items": await asyncio.gather(*(one(link) for link in links))}

    async def command(self, owner, project, job, command_id, action, request_id=None, digest=None, response=None):
        self.link(owner, project, job)
        body_hash = hashlib.sha256(json.dumps([project, job, action, request_id, digest, response], sort_keys=True).encode()).hexdigest()
        with self.db() as db:
            old = db.execute("SELECT owner,digest,payload FROM workloop_commands WHERE id=?", (command_id,)).fetchone()
        if old:
            if old[:2] != (owner, body_hash):
                raise ServiceCheckError("WORKLOOP_COMMAND_CONFLICT", 409)
            return json.loads(old[2])
        view = await self.read(owner, project, job, fresh=True)
        if view.get("stale"):
            raise ServiceCheckError("WORKLOOP_REFRESH_REQUIRED", 409)
        body, path = {}, f"/monitor/jobs/{job}"
        if action == "ANSWER":
            request = next((r for r in view["requests"] if r["request_id"] == request_id and r.get("supported")), None)
            if not request or not request["can_respond"] or request["source_digest"] != digest:
                raise ServiceCheckError("WORKLOOP_REQUEST_CHANGED", 409)
            answer = validate_answer(request, response)
            if request.get("origin") == "workflow_gate":
                decision = "approve" if answer == "allowed-once" else "reject"
                path = "/reviews/" + quote(request_id.removeprefix("gate:"), safe="") + "/" + decision
                body = {"actor": "vaiplatform:" + owner, **({"reason": "Không duyệt từ vAIPlatform"} if decision == "reject" else {"note": "Duyệt từ project vAIPlatform"})}
            else:
                body = {"answers": answer, "by": "vaiplatform:" + owner} if isinstance(answer, dict) else {"decision": "approved" if answer == "allowed-once" else "rejected", "by": "vaiplatform:" + owner}
                path += "/approvals/" + quote(request_id, safe="") + "/answer"
        elif action in {"PAUSE", "STOP"} and view["state"] == "RUNNING":
            body, path = {"action": action}, path + "/signal"
        elif action == "RESUME" and view["state"] == "SUSPENDED":
            path += "/resume"
        else:
            raise ServiceCheckError("WORKLOOP_ACTION_NOT_AVAILABLE", 409)
        row = {"command_id": command_id, "action": action, "request_id": request_id, "state": "SENDING", "created_at": now(), "sent_at": time.time()}
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT owner,digest,payload FROM workloop_commands WHERE id=?", (command_id,)).fetchone()
            if previous:
                if previous[:2] != (owner, body_hash):
                    raise ServiceCheckError("WORKLOOP_COMMAND_CONFLICT", 409)
                return json.loads(previous[2])
            records = db.execute("SELECT payload FROM workloop_commands WHERE owner=? AND project=? AND job=?", (owner, project, job)).fetchall()
            for record in records:
                prior = json.loads(record[0])
                if prior["state"] in {"SENDING", "UNCERTAIN", "REQUESTED"} and (prior.get("request_id") == request_id or action != "ANSWER"):
                    raise ServiceCheckError("WORKLOOP_COMMAND_PENDING", 409)
            db.execute("INSERT INTO workloop_commands VALUES(?,?,?,?,?,?)", (command_id, owner, project, job, body_hash, json.dumps(row)))
        try:
            result = await self.client.request("POST", path, body)
            row["state"] = "CONFIRMED" if action == "ANSWER" and result.get("ok") is True else "REQUESTED" if result.get("ok") is True else "REJECTED"
        except asyncio.CancelledError:
            row["state"] = "UNCERTAIN"
            self.save_command(row)
            raise
        except ServiceCheckError as exc:
            row["state"] = "REJECTED" if exc.status in {404, 409, 422} else "UNCERTAIN"
            row["error_code"] = exc.code
        self.save_command(row)
        return row

    async def reports(self, owner, project, job):
        self.link(owner, project, job)
        raw = await self.client.request("GET", f"/monitor/jobs/{job}/reports")
        return {"job_id": job, "nodes": [{"id": text(n.get("node"), 120), "state": text(n.get("status"), 60), "message": text(n.get("last_message"), 12000)} for n in raw.get("nodes", [])[:200]], "checked_at": now()}


@lru_cache(maxsize=1)
def workloop_service():
    return ProjectWorkloop()

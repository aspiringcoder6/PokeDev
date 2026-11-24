"""Durable project requirements and approved Workloop runs, independent of demo fixtures."""
from __future__ import annotations

import asyncio
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time

from langflow.adlc.gitea_projects import DATA, ROOT
from langflow.adlc.vai_services import ServiceCheckError, now, settings
from langflow.adlc.atomic_data import read_json_atomic

ACTIVE = {"PLANNING", "RUNNING", "UNCONFIRMED"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def safe_path(path):
    if not isinstance(path, str) or not path or len(path) > 300 or "\\" in path or ":" in path or path.startswith("/") or any(ord(c) < 32 for c in path):
        return False
    return all(p not in {"", ".", "..", ".git", "node_modules", ".venv"} and not p.startswith(".env") for p in path.split("/"))


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise ValueError("LIVE_PLAN_INVALID")
    tasks = plan.get("tasks", [])
    if plan.get("control_flow") is not None:
        from langflow.adlc.workflow_controls import validate_controls
        validate_controls(plan)
    elif any(isinstance(t, dict) and t.get("control") for t in tasks):
        raise ValueError("LIVE_CONTROL_VERSION_REQUIRED")
    if not 2 <= len(tasks) <= 20:
        raise ValueError("LIVE_PLAN_TASK_LIMIT")
    known, completed = {}, set()
    for task in tasks:
        identity = task.get("id", "")
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,30}", identity) or identity.startswith("SYS_") or identity in known:
            raise ValueError("LIVE_PLAN_TASK_ID")
        if task.get("kind") not in {"implement", "test", "review"}:
            raise ValueError("LIVE_PLAN_TASK_KIND")
        if not isinstance(task.get("title"), str) or not 12 <= len(task["title"]) <= 300 or any(not isinstance(task.get(key), list) or not 1 <= len(task[key]) <= 30 or any(not isinstance(s, str) or not 5 <= len(s) <= 3000 for s in task[key]) for key in ("steps", "acceptance")):
            raise ValueError("LIVE_PLAN_TASK_DETAIL")
        if not isinstance(task.get("depends_on"), list) or len(set(task["depends_on"])) != len(task["depends_on"]):
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        if not isinstance(task.get("write_paths"), list) or len(task["write_paths"]) > 40 or (task["kind"] != "review" and not task["write_paths"]):
            raise ValueError("LIVE_PLAN_WRITE_PATH")
        task["role"] = {"implement": "coder", "test": "tester", "review": "reviewer"}[task["kind"]]
        if any(not safe_path(p) for p in task.get("write_paths", [])):
            raise ValueError("LIVE_PLAN_WRITE_PATH")
        if task["kind"] == "review" and task.get("write_paths"):
            raise ValueError("LIVE_REVIEW_READ_ONLY")
        known[identity] = task
    while len(completed) < len(tasks):
        ready = [t for t in tasks if t["id"] not in completed and set(t.get("depends_on", [])) <= completed]
        if not ready:
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        completed.update(t["id"] for t in ready)
    def ancestors(identity):
        found, todo = set(), list(known[identity].get("depends_on", []))
        while todo:
            p = todo.pop()
            if p not in found:
                found.add(p); todo.extend(known[p].get("depends_on", []))
        return found
    writers = {}
    for task in tasks:
        for path in task.get("write_paths", []):
            for other in writers.get(path, []):
                if other not in ancestors(task["id"]) and task["id"] not in ancestors(other):
                    raise ValueError("LIVE_PLAN_PARALLEL_WRITE_CONFLICT")
            writers.setdefault(path, []).append(task["id"])
    if not any(t["kind"] == "implement" for t in tasks) or not any(t["kind"] == "test" for t in tasks):
        raise ValueError("LIVE_PLAN_IMPLEMENTATION_AND_TEST_REQUIRED")
    commands = plan.get("commands", [])
    if not commands or len(commands) > 8:
        raise ValueError("LIVE_PLAN_TEST_COMMAND_REQUIRED")
    for command in commands:
        argv = command.get("argv", [])
        if not isinstance(argv, list) or not argv or len(argv) > 40 or any(not isinstance(a, str) or not a or len(a) > 500 or "\0" in a for a in argv) or not isinstance(command.get("timeout", 180), (int, float)) or not 5 <= command.get("timeout", 180) <= 600:
            raise ValueError("LIVE_PLAN_COMMAND_INVALID")
    preview = plan.get("preview")
    if preview is not None:
        if not isinstance(preview, dict) or bool(preview.get("argv")) == bool(preview.get("path")):
            raise ValueError("LIVE_PLAN_PREVIEW_INVALID")
        if preview.get("path") and preview["path"] != "." and not safe_path(preview["path"]):
            raise ValueError("LIVE_PLAN_PREVIEW_INVALID")
        if preview.get("argv") and (not isinstance(preview["argv"], list) or not 1 <= len(preview["argv"]) <= 40 or any(not isinstance(a, str) or not a or len(a) > 500 or "\0" in a for a in preview["argv"])):
            raise ValueError("LIVE_PLAN_PREVIEW_INVALID")
    browser = plan.get("browser_checks", [])
    if not isinstance(browser, list) or len(browser) > 15 or (browser and not preview):
        raise ValueError("LIVE_PLAN_BROWSER_CHECK_INVALID")
    for check in browser:
        if not isinstance(check.get("label"), str) or not check["label"] or not isinstance(check.get("steps"), list) or not 1 <= len(check["steps"]) <= 30:
            raise ValueError("LIVE_PLAN_BROWSER_CHECK_INVALID")
        for step in check["steps"]:
            action = step.get("action")
            keys = {"goto": ["path"], "text": ["text"], "visible": ["selector"], "fill": ["selector", "value"], "click": ["selector"]}.get(action)
            if not keys or any(not isinstance(step.get(k), str) or len(step[k]) > 2000 for k in keys):
                raise ValueError("LIVE_PLAN_BROWSER_CHECK_INVALID")
            if action == "goto" and (not step["path"].startswith("/") or step["path"].startswith("//") or "\\" in step["path"]):
                raise ValueError("LIVE_PLAN_BROWSER_CHECK_INVALID")
    plan = {**plan, "max_parallel": 2}
    plan.pop("digest", None)
    plan["digest"] = digest(plan)
    return plan


def execution_definitions(plan):
    """Run independent verification before final reviews without cycling early gates."""
    if plan.get("control_flow"):
        from langflow.adlc.workflow_controls import control_definitions
        return control_definitions(plan)
    tasks = plan["tasks"]
    by_id = {task["id"]: task for task in tasks}
    upstream_of_writers, pending = set(), [dependency for task in tasks if task["kind"] != "review" for dependency in task["depends_on"]]
    while pending:
        identity = pending.pop()
        if identity not in upstream_of_writers:
            upstream_of_writers.add(identity)
            pending.extend(by_id[identity]["depends_on"])
    final_reviews = {task["id"] for task in tasks if task["kind"] == "review" and task["id"] not in upstream_of_writers}
    before = [{**task, "depends_on": list(task["depends_on"])} for task in tasks if task["id"] not in final_reviews]
    after = [{**task, "depends_on": [*task["depends_on"], "SYS_VERIFY"], "verification_required": True}
             for task in tasks if task["id"] in final_reviews]
    return [*before,
            {"id": "SYS_VERIFY", "title": "Build, kiểm thử và TestForge trong Sandbox", "role": "runner", "depends_on": [task["id"] for task in before]},
            *after,
            {"id": "SYS_HANDOVER", "title": "Bàn giao diff và lưu tài liệu cho vòng sau", "role": "runner", "depends_on": [*[task["id"] for task in tasks], "SYS_VERIFY"]}]


def completed_native_nodes(nodes):
    """A finished native contract can still have failed its application-level check."""
    return {node["id"]: node for node in nodes if node.get("state") == "DONE" and node.get("session_id")}


class LiveStore:
    def __init__(self, path=DATA / "live.sqlite3"):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, owner TEXT, repo INTEGER, payload TEXT, UNIQUE(owner,repo))")
            db.execute("CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, owner TEXT, project TEXT, delivery TEXT, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, owner TEXT, project TEXT, payload TEXT)")

    def db(self):
        return sqlite3.connect(self.path, timeout=15)

    def projects(self, owner):
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM projects WHERE owner=? ORDER BY rowid DESC", (owner,))]

    def project(self, owner, identity):
        with self.db() as db:
            row = db.execute("SELECT payload FROM projects WHERE owner=? AND id=?", (owner, identity)).fetchone()
        if not row:
            raise ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404)
        return json.loads(row[0])

    def save_project(self, owner, identity, repo, source_path, commit):
        value = {"project_id": identity, "owner": owner, "name": repo["name"], "repository_id": repo["id"], "repository": repo["full_name"],
                 "repository_url": repo["html_url"], "branch": repo.get("default_branch") or "main", "source_path": source_path, "base_commit": commit, "created_at": now()}
        with self.db() as db:
            db.execute("INSERT INTO projects VALUES(?,?,?,?)", (identity, owner, repo["id"], json.dumps(value, ensure_ascii=False)))
        return value

    def runs(self, owner, project=None, delivery=None, limit=100):
        conditions, args = ["owner=?"], [owner]
        for key, value in (("project", project), ("delivery", delivery)):
            if value:
                conditions.append(key + "=?"); args.append(value)
        with self.db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM runs WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT ?", (*args, limit))]

    def get(self, owner, identity):
        with self.db() as db:
            row = db.execute("SELECT payload FROM runs WHERE owner=? AND id=?", (owner, identity)).fetchone()
        if not row:
            raise ServiceCheckError("LIVE_RUN_NOT_FOUND", 404)
        return json.loads(row[0])

    def workflows(self, owner, project=None):
        with self.db() as db:
            rows = db.execute("SELECT payload FROM workflows WHERE owner=?" + (" AND project=?" if project else "") + " ORDER BY rowid DESC", (owner, project) if project else (owner,))
            return [json.loads(row[0]) for row in rows]

    def workflow(self, owner, identity):
        with self.db() as db:
            row = db.execute("SELECT payload FROM workflows WHERE owner=? AND id=?", (owner, identity)).fetchone()
        if not row:
            raise ServiceCheckError("LIVE_WORKFLOW_NOT_FOUND", 404)
        return json.loads(row[0])

    def save_workflow(self, owner, identity, project, name, graph, expected_digest=None):
        # Drafts may be incomplete. Compilation is mandatory before use in a run.
        self.project(owner, project)
        content_digest = digest([project, name, graph])
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT owner,payload FROM workflows WHERE id=?", (identity,)).fetchone()
            if old and old[0] != owner:
                raise ServiceCheckError("LIVE_WORKFLOW_NOT_FOUND", 404)
            previous = json.loads(old[1]) if old else None
            if (previous and previous["digest"] != expected_digest) or (not previous and expected_digest):
                raise ServiceCheckError("LIVE_WORKFLOW_CHANGED")
            value = {"workflow_id": identity, "project_id": project, "name": name, "graph": graph,
                     "digest": content_digest, "revision": previous["revision"] + 1 if previous else 1,
                     "created_at": previous["created_at"] if previous else now(), "updated_at": now()}
            if previous:
                db.execute("UPDATE workflows SET project=?,payload=? WHERE owner=? AND id=?", (project, json.dumps(value, ensure_ascii=False), owner, identity))
            else:
                db.execute("INSERT INTO workflows VALUES(?,?,?,?)", (identity, owner, project, json.dumps(value, ensure_ascii=False)))
        return value

    def revise_plan(self, owner, identity, expected_digest, workflow):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM runs WHERE owner=? AND id=?", (owner, identity)).fetchone()
            if not row:
                raise ServiceCheckError("LIVE_RUN_NOT_FOUND", 404)
            value = json.loads(row[0])
            if value["state"] != "PLAN_READY" or value["phase"] != "planning" or value["plan"]["digest"] != expected_digest:
                raise ServiceCheckError("LIVE_PLAN_NOT_READY_OR_CHANGED")
            if workflow["project_id"] != value["project_id"]:
                raise ServiceCheckError("LIVE_WORKFLOW_PROJECT_MISMATCH")
            from langflow.adlc.project_environment import apply_environment
            plan = apply_environment(workflow["plan"], value.get("environment"))
            value.update(plan=plan, plan_override=plan, workflow=workflow, updated_at=now())
            db.execute("UPDATE runs SET payload=? WHERE owner=? AND id=?", (json.dumps(value, ensure_ascii=False), owner, identity))
        return value

    def begin_execution(self, owner, identity, plan_digest, *, guard=None, model_route=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute("SELECT payload FROM runs WHERE owner=? AND id=?", (owner, identity)).fetchone()
            if not record:
                raise ServiceCheckError("LIVE_RUN_NOT_FOUND", 404)
            value = json.loads(record[0])
            if value["phase"] == "execution":
                if value.get("approved_plan_digest") != plan_digest:
                    raise ServiceCheckError("LIVE_APPROVED_PLAN_CHANGED")
                if model_route is not None and model_route != value.get("model_route"):
                    raise ServiceCheckError("LIVE_MODEL_ROUTE_CHANGED")
                return value, False
            if value["state"] != "PLAN_READY" or value["plan"]["digest"] != plan_digest:
                raise ServiceCheckError("LIVE_PLAN_NOT_READY_OR_CHANGED")
            if guard is not None:
                guard(db, value)
            if model_route is not None:
                value.update(planning_model_route=value.get("model_route"), model_route=model_route,
                    execution_model_selected_at=now(), execution_model_selected_by=owner)
            value.update(phase="execution", state="RUNNING", approved_plan_digest=plan_digest, approved_by=owner,
                         planning_nodes=value["nodes"], nodes=[], events=[], error_code=None, completed_at=None, execution_started_at=time.time(), updated_at=now())
            db.execute("UPDATE runs SET payload=? WHERE owner=? AND id=?", (json.dumps(value, ensure_ascii=False), owner, identity))
        return value, True

    def create(self, owner, project, delivery, identity, requirement, title, source_commit, workflow=None, *, environment=None):
        binding = digest([owner, project["project_id"], delivery, requirement, source_commit, workflow.get("digest") if workflow else None, environment.get("digest") if environment else None])
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM runs WHERE id=?", (identity,)).fetchone()
            if old:
                old = json.loads(old[0])
                if old["request_digest"] != binding:
                    raise ServiceCheckError("LIVE_RUN_ID_CONFLICT")
                return old, False
            current = db.execute("SELECT payload FROM runs WHERE owner=? AND project=?", (owner, project["project_id"])).fetchall()
            if any(json.loads(r[0])["state"] in ACTIVE for r in current):
                raise ServiceCheckError("LIVE_PROJECT_RUN_ACTIVE")
            row = {"run_id": identity, "owner": owner, "project_id": project["project_id"], "delivery_id": delivery,
                   "scope_id": digest([owner, project["project_id"]]), "request_digest": binding, "title": title, "requirement": requirement,
                   "repository": project["repository"], "source_path": project["source_path"], "base_commit": source_commit,
                   "created_at": now(), "phase": "planning", "state": "PLANNING", "nodes": [], "documents": [], "checks": [], "events": []}
            if workflow:
                row["workflow"] = workflow
            if environment:
                row["environment"] = environment
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (identity, owner, project["project_id"], delivery, json.dumps(row, ensure_ascii=False)))
        return row, True

    def update(self, identity, change, expected_phase=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = json.loads(db.execute("SELECT payload FROM runs WHERE id=?", (identity,)).fetchone()[0])
            if expected_phase and row["phase"] != expected_phase:
                return row
            if row.get("plan_override") and row["phase"] == "planning" and "plan" in change:
                change = {**change, "plan": row["plan_override"]}
            row.update(change, updated_at=now())
            db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity))
        return row


def public_project(row):
    return {k: v for k, v in row.items() if k not in {"owner", "source_path"}}


def public_run(row):
    result = {k: v for k, v in row.items() if k not in {"owner", "source_path", "scope_id", "request_digest", "worker_pid", "plan_override"}}
    if row.get("preview"):
        from langflow.adlc.live_preview import live_relays
        preview = row["preview"].copy()
        preview["url"] = live_relays.url(preview, row["scope_id"])
        result["preview"] = preview
    if row.get("environment"):
        from langflow.adlc.project_environment import public_environment
        result["environment"] = public_environment(row["environment"])
    if row.get("state") == "UNCONFIRMED":
        from langflow.adlc.project_recovery import ProjectRecovery
        result["recovery_status"] = ProjectRecovery(None).inspect(row)
    return result


class LiveService:
    def __init__(self, store=None):
        self.store, self.tasks = store or LiveStore(), {}
        self.publish_locks = {}
        self._human_input = None
        self._issue_service = None
        self._metrics = None
        self._environments = self._recovery = self._handover = None

    @property
    def environments(self):
        if self._environments is None:
            from langflow.adlc.project_environment import ProjectEnvironment
            self._environments = ProjectEnvironment(self)
        return self._environments

    @property
    def recovery(self):
        if self._recovery is None:
            from langflow.adlc.project_recovery import ProjectRecovery
            self._recovery = ProjectRecovery(self)
        return self._recovery

    @property
    def handover(self):
        if self._handover is None:
            from langflow.adlc.project_handover import ProjectHandover
            self._handover = ProjectHandover(self)
        return self._handover

    @property
    def metrics(self):
        if self._metrics is None:
            from langflow.adlc.project_metrics import ProjectMetrics
            self._metrics = ProjectMetrics(self)
        return self._metrics

    @property
    def issue_service(self):
        if self._issue_service is None:
            from langflow.adlc.issue_automation import IssueService
            self._issue_service = IssueService(self)
        return self._issue_service

    @property
    def human_input(self):
        if self._human_input is None:
            from langflow.adlc.human_inputs import HumanInputMonitor
            self._human_input = HumanInputMonitor(self)
        return self._human_input

    def observe(self, row):
        if row.get("error_code") in {"LIVE_INTERRUPTED_RUN_CLOSED", "LIVE_AUTO_TIME_LIMIT", "LIVE_AUTO_TIME_LIMIT_UNCONFIRMED"}:
            return row
        path = DATA / "runs" / row["run_id"] / row["phase"] / "result.json"
        if not path.exists():
            from datetime import datetime
            if row["state"] in {"PLANNING", "RUNNING"} and row["run_id"] not in self.tasks and time.time() - datetime.fromisoformat(row["created_at"]).timestamp() > 120:
                return self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_WORKER_INTERRUPTED"})
            return row
        try:
            result = read_json_atomic(path)
            if any(result.get(k) != row[k] for k in ("run_id", "scope_id", "phase")):
                raise ValueError("binding")
            if (row.get("recovery") or {}).get("generation", 0) > result.get("recovery_generation", 0):
                return row
            if result.get("state") == "PLAN_READY":
                if validate_plan(result["plan"])["digest"] != result["plan"]["digest"] or not result.get("documents"):
                    raise ValueError("plan")
            if result.get("state") == "SUCCEEDED":
                proof = result.get("verification", {})
                if not result.get("changed_files") or set(result["changed_files"]) != set(result.get("file_hashes", {})) or proof.get("passed") is not True or proof.get("protected_intact") is not True or proof.get("binding_verified") is not True or proof.get("source_sha256") != result.get("source_sha256") or proof.get("plan_digest") != row.get("approved_plan_digest") or not result.get("nodes") or not all(n["state"] in ({"DONE", "SKIPPED"} if row.get("plan", {}).get("control_flow") else {"DONE"}) for n in result["nodes"]):
                    raise ValueError("proof")
                if row.get("plan", {}).get("control_flow"):
                    from langflow.adlc.workflow_controls import verify_control_result
                    verify_control_result(row, result, self.human_input.store)
            allowed = {k: result[k] for k in ("state", "plan", "documents", "memory", "nodes", "checks", "events", "parallel", "verification", "preview", "changed_files", "file_hashes", "diff", "source_sha256", "test_suite_sha256", "error_code", "completed_at", "engine_status", "job_id", "control_receipts") if k in result}
            if result.get("state") == "PLAN_READY":
                if row.get("plan_override"):
                    allowed["plan"] = row["plan_override"]
                elif row.get("workflow"):
                    from langflow.adlc.project_environment import apply_environment
                    if result["plan"]["digest"] != apply_environment(row["workflow"]["plan"], row.get("environment"))["digest"]:
                        raise ValueError("workflow binding")
            for key in ("candidate_directory", "active_seconds"):
                if key in result:
                    allowed[key] = result[key]
            if result.get("worker_pid") and result.get("state") in {"PLANNING", "RUNNING"}:
                from langflow.adlc.project_recovery import worker_alive
                if worker_alive({**row, "worker_pid": result["worker_pid"]}):
                    allowed["worker_pid"] = result["worker_pid"]
            if row.get("auto_timing") and isinstance(result.get("active_seconds"), (int, float)):
                allowed["auto_timing"] = {**row["auto_timing"], "active_seconds": max(row["auto_timing"].get("active_seconds", 0), result["active_seconds"])}
            allowed["error_code"] = result.get("error_code")
            if result.get("state") == "PLAN_READY":
                allowed["planning_completed_at"] = result.get("completed_at")
            if result.get("state") in {"PLANNING", "RUNNING"} and time.time() - result.get("heartbeat_at", time.time()) > 120:
                allowed.update(state="UNCONFIRMED", error_code="LIVE_WORKER_INTERRUPTED")
            return self.store.update(row["run_id"], allowed, expected_phase=row["phase"])
        except (OSError, ValueError, KeyError, TypeError):
            return self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_RESULT_UNCONFIRMED"})

    def spawn(self, row):
        if row["run_id"] in self.tasks:
            return
        task = asyncio.create_task(self.execute(row))
        self.tasks[row["run_id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(row["run_id"], None))

    async def execute(self, row):
        phase = row["phase"]
        row = self.store.get(row["owner"], row["run_id"])
        if row["phase"] != phase:
            return
        directory = DATA / "runs" / row["run_id"] / row["phase"]
        child = None
        try:
            timing = row.get("auto_timing")
            spent = float((timing or {}).get("active_seconds", 0))
            if (row.get("recovery") or {}).get("generation"):
                from langflow.adlc.project_recovery import WorkerCheckpoint
                saved = WorkerCheckpoint(directory, row).read()["state"]
                spent = max(spent, float(saved.get("snapshot", {}).get("active_seconds", 0)))
            remaining = min(3600, float(timing["limit_seconds"]) - spent) if timing else 3600
            if remaining <= 0:
                raise TimeoutError("Automatic active time budget exhausted")
            recovering = bool((row.get("recovery") or {}).get("generation"))
            directory.mkdir(parents=True, exist_ok=recovering)
            if not row.get("model_route"):
                row["model_route"] = {"provider": os.getenv("ADLC_BLUEPRINT_PROVIDER", "netmind"), "model": os.getenv("ADLC_BLUEPRINT_MODEL", "zai-org/GLM-5.3-Flash")}
                self.store.update(row["run_id"], {"model_route": row["model_route"]})
            (directory / "manifest.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf8")
            base, token = settings()
            # Register the native event listener before any agent can ask a
            # question. A disconnected question channel must not start a run.
            await self.human_input.ready()
            env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE"}}
            env.update(DSH_URL=base, DSH_TOKEN=token, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            log_name = "worker-recovery-" + str(row["recovery"]["generation"]) + ".log" if recovering else "worker.log"
            with (directory / log_name).open("wb") as log:
                child = await asyncio.create_subprocess_exec(sys.executable, "-X", "utf8", str(ROOT / "integration-sources/workloop/project_worker.py"), str(directory / "manifest.json"), cwd=ROOT, env=env, stdout=log, stderr=log)
                self.store.update(row["run_id"], {"worker_pid": child.pid})
                from langflow.adlc.human_inputs import wait_worker
                def progress(elapsed):
                    self.store.update(row["run_id"], {"auto_timing": {**timing, "active_seconds": spent + elapsed}})
                await wait_worker(child, lambda: self.human_input.store.waiting(row["run_id"]), timeout_s=remaining,
                                  progress=progress if timing else None)
            value = self.observe(row)
            if value["state"] in {"PLANNING", "RUNNING"}:
                self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_WORKER_STOPPED"})
        except TimeoutError:
            if child and child.returncode is None:
                if not await self.stop_worker_child(child, row):
                    self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_WORKER_STATE_UNCONFIRMED"})
                    return
            if row.get("auto_timing"):
                latest = self.observe(self.store.get(row["owner"], row["run_id"]))
                confirmed = await self.cancel_auto_sessions(latest)
                code = "LIVE_AUTO_TIME_LIMIT" if confirmed else "LIVE_AUTO_TIME_LIMIT_UNCONFIRMED"
                self.store.update(row["run_id"], {"state": "FAILED" if confirmed else "UNCONFIRMED", "error_code": code})
                issue = row.get("issue") or {}
                if issue.get("proposal_id"):
                    self.issue_service.store.record_event(row["owner"], row["project_id"], issue["proposal_id"], "auto_time_limit", {"run_id": row["run_id"], "native_cancel_confirmed": confirmed})
            else:
                self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_EXECUTION_INTERRUPTED"})
        except Exception:
            if child and child.returncode is None:
                if not await self.stop_worker_child(child, row):
                    self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_WORKER_STATE_UNCONFIRMED"})
                    return
            self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_EXECUTION_INTERRUPTED"})

    async def stop_worker_child(self, child, row):
        from langflow.adlc.project_recovery import terminate_worker
        try:
            if not await terminate_worker(self.store.get(row["owner"], row["run_id"])):
                return False
            await asyncio.wait_for(child.wait(), timeout=10)
            return True
        except (TimeoutError, ServiceCheckError):
            return False

    async def cancel_auto_sessions(self, row):
        """Cancel only native sessions recorded on this run's live nodes."""
        identities = {node["session_id"] for node in row.get("nodes", []) if node.get("session_id") and node.get("state") not in {"DONE", "FAILED", "BLOCKED"}}
        if not identities:
            return True
        try:
            from dsh_web_sdk import DshClient, RetryConfig
            base, token = settings()
            async with DshClient(base, token, timeout=12, retry=RetryConfig(max_attempts=1)) as client:
                answers = await asyncio.wait_for(asyncio.gather(*(client.session(identity).cancel() for identity in identities), return_exceptions=True), timeout=20)
            return all(answer is True for answer in answers)
        except Exception:
            return False


@lru_cache(maxsize=1)
def live_service():
    return LiveService()

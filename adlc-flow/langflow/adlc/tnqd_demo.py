"""Owned, durable TNQD demo runs. These do not approve or replace canonical cycle execution."""
from __future__ import annotations
import asyncio
from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from langflow.adlc.tnqd_plan import digest
from langflow.adlc.vai_services import now, settings, ServiceCheckError

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "adlc-flow/data/tnqd-demo"
ACTIVE = {"PLANNING", "RUNNING", "RESERVED", "UNCONFIRMED"}
RESETTABLE = {"PLAN_READY", "SUCCEEDED", "FAILED"}

class TnqdStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS tnqd_runs (id TEXT PRIMARY KEY, owner TEXT, delivery TEXT, cycle TEXT, payload TEXT)")
    def list(self, owner, delivery, cycle, limit=10):
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM tnqd_runs WHERE owner=? AND delivery=? AND cycle=? AND json_extract(payload, '$.archived_at') IS NULL ORDER BY rowid DESC LIMIT ?", (owner, delivery, cycle, -1 if limit is None else limit)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def get(self, owner, delivery, cycle, identity):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM tnqd_runs WHERE id=? AND owner=? AND delivery=? AND cycle=?", (identity, owner, delivery, cycle)).fetchone()
        if not row:
            raise ServiceCheckError("TNQD_RUN_NOT_FOUND", 404)
        value = json.loads(row[0])
        if value.get("archived_at"):
            raise ServiceCheckError("TNQD_RUN_ARCHIVED")
        return value
    def create(self, owner, delivery, cycle, identity, requirement):
        scope = digest([owner, delivery, "TNQD_PROJECT_DOCUMENTS"])
        request_digest = digest([owner, delivery, cycle, requirement])
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM tnqd_runs WHERE id=?", (identity,)).fetchone()
            if old:
                row = json.loads(old[0])
                if row["request_digest"] != request_digest:
                    raise ServiceCheckError("TNQD_RUN_ID_CONFLICT")
                if row.get("archived_at"):
                    raise ServiceCheckError("TNQD_RUN_ARCHIVED")
                return row, False
            active = db.execute("SELECT payload FROM tnqd_runs WHERE owner=? AND delivery=?", (owner, delivery)).fetchall()
            if any(json.loads(r[0])["state"] in ACTIVE for r in active):
                raise ServiceCheckError("TNQD_RUN_ALREADY_ACTIVE")
            row = {"run_id": identity, "scope_id": scope, "request_digest": request_digest,
                   "owner": owner, "delivery": delivery, "cycle": cycle, "requirement": requirement,
                   "state": "PLANNING", "phase": "planning", "created_at": now(),
                   "nodes": [], "events": [], "documents": [], "canonical_cycle_execution": False}
            db.execute("INSERT INTO tnqd_runs VALUES (?,?,?,?,?)", (identity, owner, delivery, cycle, json.dumps(row, ensure_ascii=False)))
        return row, True
    def reset(self, owner, delivery, cycle, expected_run):
        """Archive visible terminal runs; preserve receipts, source workspaces and Memory."""
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            records = db.execute("SELECT payload FROM tnqd_runs WHERE owner=? AND delivery=? ORDER BY rowid DESC", (owner, delivery)).fetchall()
            rows = [json.loads(r[0]) for r in records]
            expected = next((r for r in rows if r["run_id"] == expected_run and r["cycle"] == cycle), None)
            if expected is None:
                raise ServiceCheckError("TNQD_RUN_NOT_FOUND", 404)
            visible = [r for r in rows if r["cycle"] == cycle and not r.get("archived_at")]
            if visible and visible[0]["run_id"] != expected_run:
                raise ServiceCheckError("TNQD_RESET_RUN_CHANGED")
            if any(not r.get("archived_at") and r["state"] in ACTIVE for r in rows):
                raise ServiceCheckError("TNQD_RESET_RUN_ACTIVE")
            if any(r["state"] not in RESETTABLE for r in visible):
                raise ServiceCheckError("TNQD_RESET_STATE_INVALID")
            stamp = now()
            for row in visible:
                row.update(archived_at=stamp, archived_by=owner)
                db.execute("UPDATE tnqd_runs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), row["run_id"]))
        return {"status": "READY", "archived_run_ids": [r["run_id"] for r in visible], "memory_preserved": True}
    def update(self, identity, change):
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = json.loads(db.execute("SELECT payload FROM tnqd_runs WHERE id=?", (identity,)).fetchone()[0])
            row.update(change, updated_at=now())
            db.execute("UPDATE tnqd_runs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity))
        return row

class TnqdService:
    def __init__(self, store, directory=DATA / "runs"):
        self.store, self.directory, self.tasks = store, Path(directory), {}
    def observe(self, row):
        if row.get("archived_at"):
            return row
        path = self.directory / row["run_id"] / row["phase"] / "result.json"
        if not path.exists():
            return row
        try:
            value = json.loads(path.read_text(encoding="utf8"))
            if value.get("run_id") != row["run_id"] or value.get("scope_id") != row["scope_id"] or value.get("phase") != row["phase"]:
                raise ValueError("binding")
            if value.get("state")=="PLAN_READY":
                plan=value.get("plan",{})
                if len(plan.get("tasks",[]))!=17 or not value.get("spec_digest") or len(value.get("documents",[]))!=3 or any(n.get("state")!="DONE" for n in value.get("nodes",[])):
                    raise ValueError("planning receipt")
            if value.get("state")=="SUCCEEDED":
                expected={t["id"] for t in row["plan"]["tasks"]}
                complete={n["id"] for n in value.get("nodes",[]) if n.get("state")=="DONE"}
                groups={g["id"]:g for g in value.get("checks",[])}
                preview=value.get("preview",{})
                if (not expected<=complete or not value.get("parallel",{}).get("verified")
                    or not value.get("handover",{}).get("changed_files") or preview.get("scope_id")!=row["scope_id"]
                    or preview.get("binding_verified") is not True or not preview.get("artifact_sha256")
                    or not all(groups.get(k,{}).get("total",0)>0 for k in ("baseline","candidate","testforge"))
                    or groups["baseline"]["passed"]>=groups["baseline"]["total"]
                    or any(groups[k]["passed"]!=groups[k]["total"] for k in ("candidate","testforge"))
                    or not all(d.get("previous_body") and d.get("revision","").startswith("verified-") for d in value.get("documents",[]))):
                    raise ValueError("execution proof")
            allowed = {k: value[k] for k in ("state", "nodes", "events", "plan", "followup_tasks", "documents", "memory", "memory_backend", "checks", "preview", "parallel", "handover", "error_code", "engine_status", "completed_at", "spec_digest") if k in value}
            if value.get("state") in {"RUNNING","PLANNING","PLAN_READY","SUCCEEDED"}:allowed["error_code"]=value.get("error_code")
            if value.get("state") in {"RUNNING","PLANNING"} and value.get("worker_alive_at") and time.time()-value["worker_alive_at"]>90:
                allowed.update(state="UNCONFIRMED",error_code="TNQD_WORKER_HEARTBEAT_LOST")
            return self.store.update(row["run_id"], allowed)
        except (ValueError, KeyError, OSError, TypeError):
            return self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "TNQD_RECEIPT_INVALID"})
    def spawn(self, row, resume=False):
        if row.get("archived_at"):
            raise ServiceCheckError("TNQD_RUN_ARCHIVED")
        if row["run_id"] in self.tasks:
            raise ServiceCheckError("TNQD_WORKER_ALREADY_ACTIVE")
        task = asyncio.create_task(self.execute(row,resume))
        self.tasks[row["run_id"]] = task
        task.add_done_callback(lambda _: self.tasks.pop(row["run_id"], None))
    async def execute(self, row,resume=False):
        directory = self.directory / row["run_id"] / row["phase"]
        child = None
        try:
            directory.mkdir(parents=True, exist_ok=resume)
            if resume:
                old=json.loads((directory/"manifest.json").read_text(encoding="utf8"))
                if any(old[k]!=row[k] for k in ("run_id","scope_id","phase","owner","delivery","cycle")):
                    raise ServiceCheckError("TNQD_RESUME_BINDING_INVALID")
            else:(directory / "manifest.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf8")
            base, token = settings()
            env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE"}}
            env.update(DSH_URL=base, DSH_TOKEN=token, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            with (directory / ("resume-"+str(row.get("resume_count",0))+".log" if resume else "worker.log")).open("wb") as log:
                child = await asyncio.create_subprocess_exec(sys.executable, "-X", "utf8", str(ROOT / "integration-sources/workloop/tnqd_worker.py"),
                    str(directory / "manifest.json"), *(["--resume"] if resume else []), cwd=str(ROOT), env=env, stdout=log, stderr=log)
                self.store.update(row["run_id"], {"worker_pid": child.pid})
                await asyncio.wait_for(child.wait(), timeout=3600)
            value = self.observe(row)
            if value["state"] in {"PLANNING", "RUNNING", "RESERVED"}:
                self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "TNQD_WORKER_STOPPED"})
        except Exception:
            if child and child.returncode is None:
                child.terminate()
                await child.wait()
            self.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "TNQD_EXECUTION_INTERRUPTED"})

def public_run(row):
    result={k: v for k, v in row.items() if k not in {"owner", "scope_id", "request_digest", "worker_pid"}}
    if row.get("preview"):
        from langflow.adlc.tnqd_relay import tnqd_relays
        preview=dict(row["preview"])
        preview["url"]=tnqd_relays.url(preview,row["scope_id"])
        if not preview["url"] and preview.get("state")=="LIVE":preview["state"]="EXPIRED"
        preview.pop("scope_id",None)
        result["preview"]=preview
    return result

@lru_cache(maxsize=1)
def tnqd_service():
    return TnqdService(TnqdStore(DATA / "runs.sqlite3"))

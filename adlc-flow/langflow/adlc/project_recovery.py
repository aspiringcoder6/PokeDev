"""Bound worker checkpoints and explicit, idempotent recovery of project runs."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from langflow.adlc.gitea_projects import DATA, ROOT
from langflow.adlc.live_workflows import digest
from langflow.adlc.vai_services import ServiceCheckError, now
from langflow.adlc.atomic_data import SnapshotBusyError, read_json_atomic, write_json_atomic


def checkpoint_binding(row):
    return digest({k: row.get(k) for k in ("run_id", "owner", "scope_id", "project_id", "phase", "base_commit", "request_digest", "approved_plan_digest", "model_route")} | {"environment": (row.get("environment") or {}).get("digest")})


class WorkerCheckpoint:
    def __init__(self, directory, manifest):
        self.path = Path(directory) / "checkpoint.json"
        self.binding = checkpoint_binding(manifest)

    def write(self, state):
        value = {"version": 1, "binding": self.binding, "saved_at": time.time(), "state": state}
        value["sha256"] = digest(value)
        write_json_atomic(self.path, value)

    def read(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size > 24000000:
                raise ValueError("limit")
            value = read_json_atomic(self.path)
            checksum = value.pop("sha256")
            if value.get("version") != 1 or value.get("binding") != self.binding or digest(value) != checksum:
                raise ValueError("binding")
            return value
        except (OSError, ValueError, KeyError, TypeError):
            raise ServiceCheckError("LIVE_RECOVERY_CHECKPOINT_INVALID") from None


def worker_alive(row):
    """PID reuse or another project's worker never counts as this run's process."""
    import psutil
    pid = row.get("worker_pid")
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        command = process.cmdline()
        expected_script = str((ROOT / "integration-sources/workloop/project_worker.py").resolve()).casefold()
        expected_manifest = str((DATA / "runs" / row["run_id"] / row["phase"] / "manifest.json").resolve()).casefold()
        paths = {str(Path(part).resolve()).casefold() for part in command if part.endswith(("project_worker.py", "manifest.json"))}
        return process.is_running() and expected_script in paths and expected_manifest in paths
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError):
        raise ServiceCheckError("LIVE_WORKER_STATE_UNCONFIRMED") from None


async def terminate_worker(row):
    """Terminate the verified worker tree, including the Windows venv launcher child."""
    import psutil
    if not worker_alive(row):
        return True
    try:
        parent = psutil.Process(row["worker_pid"])
        processes = [*reversed(parent.children(recursive=True)), parent]
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = await asyncio.to_thread(psutil.wait_procs, processes, timeout=5)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        _, alive = await asyncio.to_thread(psutil.wait_procs, alive, timeout=3)
        return not alive
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return False


def candidate_path(row):
    root = (DATA / "runs" / row["run_id"]).resolve()
    name = row.get("candidate_directory", "candidate")
    import re
    if not re.fullmatch(r"candidate(?:-recovered-[1-9][0-9]{0,4})?", name):
        raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ServiceCheckError("LIVE_CANDIDATE_CHANGED")
    return path


def recoverable_error(error):
    import httpx
    # Both SDK copies wrap network timeouts and HTTP 5xx in their own hierarchy.
    return isinstance(error, (httpx.HTTPError, TimeoutError, ConnectionError, SnapshotBusyError)) or type(error).__name__ in {"DshHttpError", "DshTransportError", "DshTimeoutError", "WebSocketDisconnect", "ConnectionClosedError"} or getattr(error, "code", None) in {"dsh/transport", "dsh/timeout", "http/408", "http/429", "http/500", "http/502", "http/503", "http/504"}


class ProjectRecovery:
    def __init__(self, live):
        self.live = live

    def inspect(self, row):
        if row.get("legacy") or row["state"] in {"SUCCEEDED", "PLAN_READY"} or row.get("error_code") in {"LIVE_AUTO_TIME_LIMIT", "LIVE_AUTO_TIME_LIMIT_UNCONFIRMED", "LIVE_INTERRUPTED_RUN_CLOSED"}:
            return {"available": False}
        try:
            checkpoint = WorkerCheckpoint(DATA / "runs" / row["run_id"] / row["phase"], row).read()
        except ServiceCheckError:
            return {"available": False, "error_code": "LIVE_RECOVERY_CHECKPOINT_INVALID"}
        state = checkpoint["state"]
        stopping = bool((row.get("recovery") or {}).get("stop_intent"))
        return {"available": row["state"] == "UNCONFIRMED" and not stopping, "stopping": stopping, "generation": (row.get("recovery") or {}).get("generation", 0),
                "saved_at": checkpoint["saved_at"], "completed_tasks": len(state.get("outputs", {})),
                "waiting_tasks": [n["id"] for n in state.get("snapshot", {}).get("nodes", []) if n.get("state") == "WAITING_INPUT"]}

    def claim(self, owner, identity, command, expected_generation, plan_digest):
        with self.live.store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute("SELECT payload FROM runs WHERE owner=? AND id=?", (owner, identity)).fetchone()
            if not record:
                raise ServiceCheckError("LIVE_RUN_NOT_FOUND", 404)
            row = json.loads(record[0])
            old = row.get("recovery") or {}
            if old.get("command_id") == command:
                return row, False
            if old.get("stop_intent"):
                raise ServiceCheckError("LIVE_RECOVERY_STOP_UNCONFIRMED")
            if row["state"] != "UNCONFIRMED" or old.get("generation", 0) != expected_generation or row.get("approved_plan_digest") != plan_digest:
                raise ServiceCheckError("LIVE_RECOVERY_CHANGED")
            if row.get("error_code") in {"LIVE_AUTO_TIME_LIMIT", "LIVE_AUTO_TIME_LIMIT_UNCONFIRMED", "LIVE_INTERRUPTED_RUN_CLOSED"}:
                raise ServiceCheckError("LIVE_RECOVERY_CHANGED")
            timing = row.get("auto_timing") or {}
            if timing and max(timing.get("active_seconds", 0), row.get("active_seconds", 0)) >= timing["limit_seconds"]:
                raise ServiceCheckError("LIVE_RECOVERY_CHANGED")
            checkpoint = WorkerCheckpoint(DATA / "runs" / identity / row["phase"], row).read()
            if checkpoint["state"].get("snapshot", {}).get("state") in {"PLAN_READY", "SUCCEEDED"}:
                raise ServiceCheckError("LIVE_RECOVERY_RECONCILE_FIRST")
            # A new run cannot begin while another run of the same project is active.
            for (payload,) in db.execute("SELECT payload FROM runs WHERE owner=? AND project=? AND id<>?", (owner, row["project_id"], identity)):
                if json.loads(payload)["state"] in {"PLANNING", "RUNNING", "UNCONFIRMED"}:
                    raise ServiceCheckError("LIVE_PROJECT_RUN_ACTIVE")
            row.update(state="PLANNING" if row["phase"] == "planning" else "RUNNING", error_code=None, completed_at=None,
                       recovery={"generation": expected_generation + 1, "command_id": command, "requested_at": now(), "checkpoint_at": checkpoint["saved_at"]}, updated_at=now())
            db.execute("UPDATE runs SET payload=? WHERE owner=? AND id=?", (json.dumps(row, ensure_ascii=False), owner, identity))
        return row, True

    async def resume(self, owner, identity, command, expected_generation, plan_digest):
        row = self.live.observe(self.live.store.get(owner, identity))
        if (row.get("recovery") or {}).get("command_id") == command:
            return row
        if identity in self.live.tasks or worker_alive(row):
            if identity not in self.live.tasks:
                self.adopt(row)
            raise ServiceCheckError("LIVE_RECOVERY_WORKER_ACTIVE")
        if row["state"] != "UNCONFIRMED":
            raise ServiceCheckError("LIVE_RECOVERY_CHANGED")
        await self.live.human_input.ready()
        value, fresh = self.claim(owner, identity, command, expected_generation, plan_digest)
        if fresh:
            self.live.spawn(value)
        return value

    def adopt(self, row):
        identity = row["run_id"]
        if identity in self.live.tasks:
            return
        task = asyncio.create_task(self.watch(row))
        self.live.tasks[identity] = task
        task.add_done_callback(lambda _: self.live.tasks.pop(identity, None))

    async def stop(self, owner, identity, command, expected_generation):
        row = self.live.observe(self.live.store.get(owner, identity))
        recovery = row.get("recovery") or {}
        if row.get("error_code") == "LIVE_INTERRUPTED_RUN_CLOSED" and recovery.get("stop_intent", {}).get("command_id") == command:
            return row
        if row["state"] != "UNCONFIRMED" or recovery.get("generation", 0) != expected_generation:
            raise ServiceCheckError("LIVE_RECOVERY_CHANGED")
        recovery["stop_intent"] = {"command_id": command, "at": now()}
        self.live.store.update(identity, {"recovery": recovery})
        if not await terminate_worker(row):
            raise ServiceCheckError("LIVE_RECOVERY_STOP_UNCONFIRMED")
        confirmed = await self.live.cancel_auto_sessions(row)
        if not confirmed:
            raise ServiceCheckError("LIVE_RECOVERY_STOP_UNCONFIRMED")
        return self.live.store.update(identity, {"state": "FAILED", "error_code": "LIVE_INTERRUPTED_RUN_CLOSED", "completed_at": time.time(), "recovery": recovery})

    async def watch(self, row):
        """A live orphan is observed, never replaced with a second worker."""
        row = self.live.observe(self.live.store.get(row["owner"], row["run_id"]))
        while worker_alive(row):
            latest = self.live.observe(self.live.store.get(row["owner"], row["run_id"]))
            if latest["state"] in {"SUCCEEDED", "FAILED", "PLAN_READY"}:
                return
            timing = latest.get("auto_timing") or {}
            if timing and timing.get("active_seconds", 0) >= timing["limit_seconds"]:
                await terminate_worker(latest)
                confirmed = await self.live.cancel_auto_sessions(latest)
                self.live.store.update(row["run_id"], {"state": "FAILED" if confirmed else "UNCONFIRMED", "error_code": "LIVE_AUTO_TIME_LIMIT" if confirmed else "LIVE_AUTO_TIME_LIMIT_UNCONFIRMED"})
                return
            row = latest
            await asyncio.sleep(3)
        latest = self.live.observe(self.live.store.get(row["owner"], row["run_id"]))
        if latest["state"] in {"RUNNING", "PLANNING"}:
            self.live.store.update(row["run_id"], {"state": "UNCONFIRMED", "error_code": "LIVE_WORKER_INTERRUPTED"})

    def restore(self):
        with self.live.store.db() as db:
            rows = [json.loads(row[0]) for row in db.execute("SELECT payload FROM runs")]
        for row in rows:
            if row["state"] in {"PLANNING", "RUNNING", "UNCONFIRMED"}:
                try:
                    if worker_alive(row):
                        self.adopt(row)
                    else:
                        observed = self.live.observe(row)
                        if observed["state"] in {"PLANNING", "RUNNING", "UNCONFIRMED"} and worker_alive(observed):
                            self.adopt(observed)
                except ServiceCheckError:
                    pass

"""Owner-scoped run evidence and measured Harness usage; prices stay explicit."""
from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
import math
import time

from langflow.adlc.vai_services import ServiceCheckError, now, settings

TOKEN_KEYS = ("uncachedInputTokens", "cacheReadTokens", "cacheWriteTokens", "outputTokens")
RATE_KEYS = ("input", "cache_read", "cache_write", "output")


def epoch(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def union_seconds(intervals):
    merged = []
    for start, end in sorted((a, b) for a, b in intervals if a is not None and b is not None and b >= a):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(b-a for a, b in merged)


def run_timing(run, questions, clock=None):
    clock = time.time() if clock is None else clock
    start = epoch(run.get("created_at"))
    terminal = run["state"] in {"SUCCEEDED", "FAILED", "UNCONFIRMED"}
    finish = epoch(run.get("completed_at") or run.get("updated_at")) if terminal else clock
    finish = finish or clock
    waits = [(epoch(q.get("created_at")), min(epoch(q.get("responded_at") or q.get("resolved_at")) or finish, finish)) for q in questions]
    human = union_seconds(waits)
    planned = epoch(run.get("planning_completed_at")) or max((epoch(n.get("completed_at")) or 0 for n in run.get("planning_nodes", [])), default=0) or None
    execution = (epoch(run.get("execution_started_at")) or min((epoch(n.get("started_at")) or finish for n in run.get("nodes", [])), default=finish)) if run.get("phase") == "execution" else None
    approval = max(0, (execution or finish)-planned) if planned else (max(0, finish-(epoch(run.get("completed_at")) or finish)) if run["state"] == "PLAN_READY" else 0)
    total = max(0, finish-start) if start else None
    active = run.get("auto_timing", {}).get("active_seconds")
    measured = active is not None
    if active is None and total is not None and run["state"] != "UNCONFIRMED":
        active = max(0, total-human-approval)
    repairs = len({n["id"] for n in run.get("nodes", []) if n["id"].startswith("FIX") or n.get("repair") is True})
    return {"total_seconds": total, "active_seconds": active, "active_source": "active_clock" if measured else "derived_from_timestamps",
            "human_wait_seconds": human, "approval_wait_seconds": approval, "human_interventions": len(questions),
            "repair_rounds": repairs, "verification_attempts": len([c for c in run.get("checks", []) if c.get("id", "").startswith("verify-")])}


def session_bindings(runs):
    found = {}
    for run in runs:
        for node in [*run.get("planning_nodes", []), *run.get("nodes", [])]:
            if node.get("session_id") and not node.get("reused_from"):
                found.setdefault(node["session_id"], {"run_id": run["run_id"], "route": run.get("model_route") or {}})
    return found


def measured_usage(item):
    usage = ((item.get("projections") or {}).get("values") or {}).get("tokenUsage")
    if not isinstance(usage, dict) or not {"uncachedInputTokens", "outputTokens"} <= usage.keys():
        return None
    if any(key in usage and (type(usage[key]) is not int or not 0 <= usage[key] <= 10**13) for key in TOKEN_KEYS):
        return None
    return {key: usage.get(key, 0) for key in TOKEN_KEYS}


class ProjectMetrics:
    def __init__(self, live):
        self.live = live
        self.tasks = {}
        self.last_attempt = {}
        with closing(live.store.db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS project_metrics_settings(project TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS project_usage(owner TEXT,project TEXT,session TEXT,payload TEXT,PRIMARY KEY(owner,project,session))")
            db.execute("CREATE TABLE IF NOT EXISTS project_metric_refresh(project TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL)")

    def pricing(self, owner, project):
        self.live.store.project(owner, project)
        with closing(self.live.store.db()) as db:
            row = db.execute("SELECT payload FROM project_metrics_settings WHERE owner=? AND project=?", (owner, project)).fetchone()
        return json.loads(row[0]) if row else {"revision": 1, "rates": [], "updated_at": None}

    def save_pricing(self, owner, project, expected_revision, rates):
        current = self.pricing(owner, project)
        if not isinstance(rates, list) or len(rates) > 10 or any(not isinstance(r, dict) for r in rates):
            raise ServiceCheckError("LIVE_PRICING_INVALID", 422)
        for rate in rates:
            if any(not isinstance(rate.get(key), str) or not 1 <= len(rate[key].strip()) <= 300 for key in ("provider", "model", "source")) or any(type(rate.get(key)) not in {int, float} or not math.isfinite(rate[key]) or not 0 <= rate[key] <= 10000 for key in RATE_KEYS):
                raise ServiceCheckError("LIVE_PRICING_INVALID", 422)
        rates = [{**{key: rate[key].strip() for key in ("provider", "model", "source")}, **{key: rate[key] for key in RATE_KEYS}} for rate in rates]
        if len({(r["provider"], r["model"]) for r in rates}) != len(rates):
            raise ServiceCheckError("LIVE_PRICING_INVALID", 422)
        with closing(self.live.store.db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT payload FROM project_metrics_settings WHERE owner=? AND project=?", (owner, project)).fetchone()
            revision = json.loads(previous[0])["revision"] if previous else current["revision"]
            if revision != expected_revision:
                raise ServiceCheckError("LIVE_PRICING_CHANGED")
            value = {"revision": revision+1, "rates": rates, "updated_at": now(), "updated_by": owner}
            db.execute("INSERT OR REPLACE INTO project_metrics_settings VALUES(?,?,?)", (project, owner, json.dumps(value)))
        return value

    def runs(self, owner, project):
        self.live.store.project(owner, project)
        with closing(self.live.store.db()) as db:
            rows = db.execute("SELECT payload FROM runs WHERE owner=? AND project=? ORDER BY rowid DESC", (owner, project)).fetchall()
        return [self.live.observe(json.loads(r[0])) for r in rows]

    async def refresh(self, owner, project, client=None):
        bindings = session_bindings(self.runs(owner, project))
        try:
            if client is None:
                from dsh_web_sdk import DshClient, RetryConfig
                base, token = settings()
                async with DshClient(base, token, timeout=20, retry=RetryConfig(max_attempts=1)) as native:
                    raw = await native.rpc("session/list", {"_request": {"sessionIds": list(bindings)}}) if bindings else {"items": []}
            else:
                raw = await client.rpc("session/list", {"_request": {"sessionIds": list(bindings)}}) if bindings else {"items": []}
            counted = 0
            with closing(self.live.store.db()) as db, db:
                for item in raw.get("items", []):
                    identity = item.get("sessionId")
                    if identity not in bindings:
                        continue  # Never persist or expose another project's projections.
                    usage = measured_usage(item)
                    if usage is None:
                        continue
                    payload = {"session_id": identity, **bindings[identity], "tokens": usage, "source": "harness_session_projection", "collected_at": now()}
                    db.execute("INSERT OR REPLACE INTO project_usage VALUES(?,?,?,?)", (owner, project, identity, json.dumps(payload)))
                    counted += 1
                state = {"updated_at": now(), "requested_sessions": len(bindings), "measured_sessions": counted, "error_code": None}
                db.execute("INSERT OR REPLACE INTO project_metric_refresh VALUES(?,?,?)", (project, owner, json.dumps(state)))
            return state
        except Exception:
            state = {"updated_at": now(), "error_code": "LIVE_METRICS_SOURCE_UNAVAILABLE"}
            with closing(self.live.store.db()) as db, db:
                db.execute("INSERT OR REPLACE INTO project_metric_refresh VALUES(?,?,?)", (project, owner, json.dumps(state)))
            return state

    def schedule(self, owner, project, *, force=False):
        self.live.store.project(owner, project)
        if project not in self.tasks or self.tasks[project].done():
            if force or time.monotonic()-self.last_attempt.get(project, -300) >= 300:
                self.last_attempt[project] = time.monotonic()
                self.tasks[project] = asyncio.create_task(self.refresh(owner, project))

    def summary(self, owner, project, days=30):
        all_runs = self.runs(owner, project)
        runs = [r for r in all_runs if (epoch(r.get("created_at")) or 0) >= time.time()-days*86400]
        with closing(self.live.store.db()) as db:
            usage = {r["session_id"]: r for r in [json.loads(row[0]) for row in db.execute("SELECT payload FROM project_usage WHERE owner=? AND project=?", (owner, project))]}
            questions = [json.loads(row[0]) for row in db.execute("SELECT payload FROM human_inputs WHERE owner=?", (owner,))] if db.execute("SELECT 1 FROM sqlite_master WHERE name='human_inputs'").fetchone() else []
            refresh = db.execute("SELECT payload FROM project_metric_refresh WHERE owner=? AND project=?", (owner, project)).fetchone()
        pricing = self.pricing(owner, project)
        for run in all_runs:
            for node in [*run.get("planning_nodes", []), *run.get("nodes", [])]:
                if node.get("session_id") and not node.get("reused_from") and node.get("usage"):
                    item = {"session_id": node["session_id"], "route": run.get("model_route") or {}, **node["usage"]}
                    if item["session_id"] not in usage or (epoch(item.get("collected_at")) or 0) > (epoch(usage[item["session_id"]].get("collected_at")) or 0):
                        usage[item["session_id"]] = item
        rates = {(r["provider"], r["model"]): r for r in pricing["rates"]}
        def aggregate(owned):
            ids = session_bindings(owned)
            measured = [usage[sid] for sid in ids if sid in usage]
            tokens = sum(sum(row["tokens"].values()) for row in measured) if measured else None
            priced, cost = 0, 0.0
            for row in measured:
                rate = rates.get((row["route"].get("provider"), row["route"].get("model")))
                if rate:
                    cost += sum(row["tokens"][key]*rate[price] for key, price in zip(TOKEN_KEYS, RATE_KEYS, strict=True))/1000000
                    priced += 1
            return {"tokens": tokens, "sessions": len(ids), "measured_sessions": len(measured), "priced_sessions": priced,
                    "last_measured_at": max((row["collected_at"] for row in measured), default=None),
                    "cost_usd": round(cost, 8) if priced else None, "cost_kind": "estimate_from_configured_rates" if priced else "unavailable",
                    "partial": len(measured) < len(ids) or priced < len(ids)}
        details = [{"run_id": r["run_id"], "title": r["title"], "state": r["state"], "created_at": r["created_at"], "issue": r.get("issue"),
                    "workflow": {k: r.get("workflow", {}).get(k) for k in ("name", "revision", "workflow_id")},
                    "timing": run_timing(r, [q for q in questions if q["run_id"] == r["run_id"]]), "usage": aggregate([r])} for r in runs]
        finished = [r for r in runs if r["state"] in {"SUCCEEDED", "FAILED"}]
        successes = sum(r["state"] == "SUCCEEDED" for r in finished)
        active = [r["timing"]["active_seconds"] for r in details if r["timing"]["active_seconds"] is not None]
        models = sorted({((r.get("model_route") or {}).get("provider"), (r.get("model_route") or {}).get("model")) for r in all_runs if (r.get("model_route") or {}).get("provider") and (r.get("model_route") or {}).get("model")})
        return {"project_id": project, "days": days, "runs": details, "models": [{"provider": p, "model": m} for p, m in models], "totals": {"runs": len(runs), "finished": len(finished), "succeeded": successes,
                "success_rate": successes/len(finished) if finished else None, "unconfirmed": sum(r["state"] == "UNCONFIRMED" for r in runs),
                "average_active_seconds": sum(active)/len(active) if active else None, "human_wait_seconds": sum(r["timing"]["human_wait_seconds"] for r in details),
                "human_interventions": sum(r["timing"]["human_interventions"] for r in details), "repair_rounds": sum(r["timing"]["repair_rounds"] for r in details)},
                "usage": aggregate(runs), "pricing": {k:v for k,v in pricing.items() if k != "updated_by"},
                "refresh": {**(json.loads(refresh[0]) if refresh else {"updated_at": None, "error_code": None}), "running": project in self.tasks and not self.tasks[project].done()}}

    async def stop(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

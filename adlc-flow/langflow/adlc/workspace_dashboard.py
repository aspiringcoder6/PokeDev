"""Read-only workspace projections. Runs, native sessions and tasks are distinct units."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, quote

LOCAL = timezone(timedelta(hours=7))
ACTIVE = {"PLANNING", "RUNNING"}


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def run_href(run, tab=None, focus=None):
    params = {"run": run["run_id"]}
    if run.get("project_id"):
        params["project"] = run["project_id"]
    if tab:
        params["tab"] = tab
    if focus:
        params["focus"] = focus
    return "/work?" + urlencode(params)


def project_rows(store, owner, allowed):
    """Stream owned payloads once, without silently limiting totals to the latest 100."""
    with store.db() as db:
        identities = db.execute("SELECT id,project FROM runs WHERE owner=? ORDER BY rowid DESC", (owner,)).fetchall()
    # Finish the read cursor before observe() reconciles a snapshot in another
    # connection; holding a cursor across that write would lock SQLite.
    for identity, project in identities:
        if not project or project in allowed:
            yield store.get(owner, identity)


def metadata(row):
    fields = ("run_id", "project_id", "delivery_id", "title", "repository", "created_at", "completed_at", "planning_completed_at", "state", "phase", "published", "handover", "error_code", "legacy", "recovery_status", "parent_run_id")
    return {**{key: row[key] for key in fields if key in row}, "nodes": [{key: node[key] for key in ("id", "state", "kind", "role", "control", "reused_from") if key in node} for node in row.get("nodes", [])]}


def summarize(projects, runs, workflows, requests, reviews, *, days=28, project_id=None, now=None, permissions=None, sources=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(LOCAL).date()
    first = today - timedelta(days=days - 1)
    names = {p["project_id"]: p["name"] for p in projects}
    permissions = permissions or {}
    known = {}
    for row in runs:
        if not project_id or row.get("project_id") == project_id:
            known.setdefault(row["run_id"], row)
    rows = list(known.values())
    superseded = {r["parent_run_id"] for r in rows if r.get("parent_run_id")}
    def project_name(identity):
        return names.get(identity, "Chưa gắn project" if not identity else "Project")
    pending = [r for r in requests if r.get("run_id") in known and r.get("status") in {"PENDING", "SENDING", "UNCERTAIN"} and known[r["run_id"]]["state"] in ACTIVE]
    waiting_ids = {r["run_id"] for r in pending}
    waiting_ids.update(r["run_id"] for r in rows if r["state"] == "PLAN_READY" or (r["state"] in ACTIVE and any(n.get("state") == "WAITING_INPUT" for n in r.get("nodes", []))))
    def category(row):
        if row["run_id"] in waiting_ids:
            return "waiting"
        return {"SUCCEEDED": "succeeded", "FAILED": "failed", "UNCONFIRMED": "unconfirmed", "PLANNING": "running", "RUNNING": "running", "PLAN_READY": "waiting"}.get(row["state"], "other")
    in_range, invalid_dates = [], 0
    daily = {str(first + timedelta(days=i)): {"date": str(first + timedelta(days=i)), "total": 0, "succeeded": 0, "failed": 0, "other": 0} for i in range(days)}
    for row in rows:
        created = timestamp(row.get("created_at"))
        if created is None:
            invalid_dates += 1
            continue
        date = str(created.astimezone(LOCAL).date())
        if date not in daily:
            continue
        in_range.append(row)
        daily[date]["total"] += 1
        daily[date][row["state"].lower() if row["state"] in {"SUCCEEDED", "FAILED"} else "other"] += 1
    states = Counter(category(row) for row in in_range)
    finished = states["succeeded"] + states["failed"]
    roles = {key: {"role": key, "total": 0, "active": 0, "waiting": 0, "done": 0} for key in ("developer", "tester", "reviewer", "control", "other")}
    for row in in_range:
        if row.get("phase") != "execution":
            continue
        for node in row.get("nodes", []):
            if node.get("reused_from"):
                continue
            key = "control" if node.get("control") or node.get("role") == "runner" or node.get("id", "").startswith("SYS_") else {"implement": "developer", "test": "tester", "review": "reviewer", "coder": "developer", "tester": "tester", "reviewer": "reviewer"}.get(node.get("kind") or node.get("role"), "other")
            item = roles[key]
            item["total"] += 1
            item["active"] += node.get("state") in {"RUNNING", "IN_PROGRESS"}
            item["waiting"] += node.get("state") in {"PENDING", "WAITING_SLOT", "WAITING_INPUT"}
            item["done"] += node.get("state") in {"DONE", "SUCCEEDED"}
    items = {}
    def add(identity, kind, title, row, href, since=None, *, reason="", can_act=True, action="Xem", priority=1):
        pid = row.get("project_id")
        if project_id and pid != project_id:
            return
        can_act = can_act and permissions.get(row.get("run_id"), permissions.get("project:" + str(pid), True))
        parsed = timestamp(since)
        items.setdefault(identity, {"id": identity, "kind": kind, "title": title, "run_title": row.get("title", ""), "run_id": row.get("run_id", ""), "project_id": pid, "project_name": project_name(pid), "since": parsed.isoformat() if parsed else None, "reason": reason, "can_act": bool(can_act), "action_label": action if can_act else "Xem trạng thái", "href": href, "priority": priority})
    for request in pending:
        row = known[request["run_id"]]
        kind = "gate" if request.get("origin") == "workflow_gate" else request.get("kind", "question")
        uncertain = request["status"] in {"SENDING", "UNCERTAIN"}
        add("input:" + request["request_id"], kind, request.get("title") or "Agent đang chờ bạn phản hồi", row, run_href(row, focus=request["request_id"]), request.get("created_at"), reason="Phản hồi đang gửi hoặc cần đối soát; không gửi lại tự động." if uncertain else "Mở đúng yêu cầu để xem nội dung và trả lời.", can_act=request.get("can_respond", False) and not uncertain, action="Trả lời" if kind == "question" else "Xem yêu cầu duyệt", priority=0)
    for row in rows:
        identity = row["run_id"]
        if row["state"] == "PLAN_READY":
            add("plan:" + identity, "plan", "Kế hoạch đang chờ bạn duyệt", row, run_href(row, "spec"), row.get("planning_completed_at") or row.get("completed_at"), action="Xem kế hoạch")
        elif row["state"] == "UNCONFIRMED" and identity not in superseded:
            available = row.get("recovery_status", {}).get("available", False)
            add("recovery:" + identity, "recovery", "Lượt chạy cần đối soát", row, run_href(row, focus="recovery"), row.get("recovery_status", {}).get("saved_at") or row.get("completed_at"), reason="Có tiến trình đã lưu để xem xét tiếp tục." if available else "Cần kiểm tra trạng thái thực trước khi quyết định tiếp tục.", action="Xem phục hồi" if available else "Đối soát")
        elif row["state"] in {"FAILED", "BLOCKED"} and identity not in superseded and row.get("error_code") != "LIVE_INTERRUPTED_RUN_CLOSED":
            add("failed:" + identity, "failed", "Lượt chạy bị chặn" if row["state"] == "BLOCKED" else "Lượt chạy gặp lỗi", row, run_href(row), row.get("completed_at"), reason="Mở chi tiết để xem nguyên nhân, bằng chứng và cách xử lý.", action="Xem lỗi")
        elif identity in waiting_ids and not any(q["run_id"] == identity for q in pending):
            add("waiting:" + identity, "question", "Agent đang chờ thông tin", row, run_href(row), reason="Chưa nhận được nội dung yêu cầu hiện tại. Mở lượt chạy để kiểm tra.", can_act=False)
        if row["state"] == "SUCCEEDED" and not row.get("legacy"):
            handover = row.get("handover") or {}
            if handover.get("state") not in {"MERGED", "CLOSED"}:
                published = bool(row.get("published"))
                add("handover:" + identity, "handover", "Kết quả đang chờ bàn giao", row, run_href(row, "handover" if published else "changes"), row.get("completed_at"), reason="Mở để kiểm tra trạng thái PR và bằng chứng mới nhất." if published else "Xem thay đổi và xuất nhánh Gitea khi bạn sẵn sàng.", action="Xem PR" if published else "Xem bàn giao", priority=2)
    for review in reviews:
        kind = review.get("kind")
        if kind in {"plan", "recovery"}:
            continue  # Already derived from the complete owned history, without a 100-run cap.
        if kind == "issue" and review.get("project_id") in names:
            pid = review["project_id"]
            row = {"project_id": pid, "title": review.get("run_title", "")}
            href = "/work?" + urlencode({"project": pid, "view": "issues", "issue": review.get("proposal_id", "")})
            add("issue:" + str(review.get("proposal_id")), "issue", review.get("title", "Issue cần bạn xem"), row, href, review.get("created_at"), action="Xem issue", priority=2)
        elif kind == "advanced" and not project_id:
            rid = review["run_id"]
            add("advanced:" + rid, "advanced", review.get("title", "Workflow gói cần duyệt"), {"run_id": rid, "title": review.get("run_title", ""), "project_id": None}, "/runs/" + quote(rid, safe=""), review.get("created_at"), can_act=False)
    queue = sorted(items.values(), key=lambda item: (item["priority"], timestamp(item["since"]) or datetime.max.replace(tzinfo=timezone.utc), item["id"]))
    recent = sorted(in_range, key=lambda row: timestamp(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:6]
    return {"generated_at": now.isoformat(), "timezone": "Asia/Ho_Chi_Minh", "range": {"days": days, "from": str(first), "to": str(today)}, "project_id": project_id, "projects": [{"project_id": p["project_id"], "name": p["name"], "repository": p["repository"]} for p in projects],
        "totals": {"runs": len(in_range), "finished": finished, "succeeded": states["succeeded"], "failed": states["failed"], "success_rate": states["succeeded"] / finished if finished else None, "active_now": sum(r["state"] in ACTIVE for r in rows), "waiting_now": len(waiting_ids), "attention_now": len(queue), "projects": 1 if project_id else len(projects), "workflows": sum(not project_id or w["project_id"] == project_id for w in workflows)},
        "daily": list(daily.values()), "statuses": [{"state": key, "count": states[key]} for key in ("succeeded", "running", "waiting", "unconfirmed", "failed", "other")], "roles": list(roles.values()), "attention": queue,
        "history": [{"run_id": r["run_id"], "project_id": r.get("project_id"), "title": r["title"], "repository": r.get("repository", ""), "state": r["state"], "created_at": r.get("created_at"), "category": category(r)} for r in rows],
        "recent_runs": [{"run_id": r["run_id"], "project_id": r.get("project_id"), "project_name": project_name(r.get("project_id")), "title": r["title"], "state": r["state"], "created_at": r["created_at"], "href": run_href(r)} for r in recent], "sources": sources or {}, "quality": {"invalid_timestamps": invalid_dates}, "units": {"runs": "pokedev_run", "roles": "execution_task_without_reused_sessions"}}

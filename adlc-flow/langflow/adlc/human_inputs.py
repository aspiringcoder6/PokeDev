"""Durable, run-scoped Harness questions, permission decisions and paused clocks."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import sqlite3
import time
from contextlib import closing

from langflow.adlc.vai_services import ServiceCheckError, now, settings

WAITING = {"PENDING", "SENDING", "UNCERTAIN"}
ACTIVE_RUNS = {"PLANNING", "RUNNING", "UNCONFIRMED"}


def normalize_request(event):
    """Only supported native requests become actionable; text never grants permission."""
    request = event.get("request")
    if not isinstance(request, dict) or len(json.dumps(request)) > 100000:
        raise ValueError("LIVE_HUMAN_INPUT_INVALID")
    kind = event.get("event")
    if kind == "user-questions/request":
        questions = request.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 20:
            raise ValueError("LIVE_HUMAN_INPUT_INVALID")
        result, ids = [], set()
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError("LIVE_HUMAN_INPUT_INVALID")
            identity, prompt = question.get("id"), question.get("question")
            if (
                not isinstance(identity, str)
                or not identity
                or len(identity) > 200
                or identity in ids
                or not isinstance(prompt, str)
                or not prompt.strip()
                or len(prompt) > 16000
            ):
                raise ValueError("LIVE_HUMAN_INPUT_INVALID")
            ids.add(identity)
            options = question.get("options", [])
            if not isinstance(options, list) or len(options) > 40:
                raise ValueError("LIVE_HUMAN_INPUT_INVALID")
            choices = []
            for option in options:
                if not isinstance(option, dict):
                    raise ValueError("LIVE_HUMAN_INPUT_INVALID")
                label = option.get("label")
                if (
                    not isinstance(label, str)
                    or not label
                    or len(label) > 1000
                    or any(o["label"] == label for o in choices)
                ):
                    raise ValueError("LIVE_HUMAN_INPUT_INVALID")
                choices.append({"label": label, "description": str(option.get("description", ""))[:4000]})
            result.append(
                {
                    "id": identity,
                    "question": prompt,
                    "header": str(question.get("header") or "")[:300],
                    "options": choices,
                    "multi_select": question.get("multiSelect") is True,
                }
            )
        return {"kind": "question", "title": "Agent cần câu trả lời", "questions": result}
    if kind == "approval/request":
        reason = request.get("displayReason") or request.get("reason") or "Agent cần quyền để tiếp tục."
        if isinstance(reason, dict):
            reason = reason.get("vi") or reason.get("en") or next(iter(reason.values()), "")
        return {
            "kind": "permission",
            "title": "Agent cần bạn cho phép",
            "tool_name": str(request.get("toolName") or "Công cụ")[:300],
            "prompt": str(reason)[:16000],
            "details": {key: request[key] for key in ("command", "path", "args") if key in request},
        }
    raise ValueError("LIVE_HUMAN_INPUT_UNSUPPORTED")


def validate_answer(request, response):
    if not isinstance(response, dict):
        raise ServiceCheckError("LIVE_HUMAN_RESPONSE_INVALID", 422)
    if request["kind"] == "permission":
        if (
            set(response) != {"decision"}
            or not isinstance(response["decision"], str)
            or response["decision"] not in {"allowed-once", "rejected"}
        ):
            raise ServiceCheckError("LIVE_HUMAN_RESPONSE_INVALID", 422)
        return response["decision"]
    answers = response.get("answers")
    questions = {q["id"]: q for q in request["questions"]}
    if set(response) != {"answers"} or not isinstance(answers, list) or len(answers) != len(questions):
        raise ServiceCheckError("LIVE_HUMAN_RESPONSE_INVALID", 422)
    seen, result = set(), []
    for answer in answers:
        if (
            not isinstance(answer, dict)
            or set(answer) - {"id", "selected", "custom"}
            or not isinstance(answer.get("id"), str)
            or answer["id"] not in questions
            or answer["id"] in seen
        ):
            raise ServiceCheckError("LIVE_HUMAN_RESPONSE_INVALID", 422)
        seen.add(answer["id"])
        question = questions[answer["id"]]
        selected, custom = answer.get("selected", []), answer.get("custom", "")
        if (
            not isinstance(selected, list)
            or any(not isinstance(x, str) for x in selected)
            or len(set(selected)) != len(selected)
            or set(selected) - {o["label"] for o in question["options"]}
            or (not question["multi_select"] and len(selected) > 1)
            or not isinstance(custom, str)
            or len(custom) > 8000
            or (not selected and not custom.strip())
        ):
            raise ServiceCheckError("LIVE_HUMAN_RESPONSE_INVALID", 422)
        result.append(
            {"id": answer["id"], "selected": selected, **({"custom": custom.strip()} if custom.strip() else {})}
        )
    return {"answers": result}


class HumanInputStore:
    def __init__(self, path):
        self.path = path
        with self.db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS human_inputs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, run TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS human_inputs_owner_run ON human_inputs(owner,run)")

    def db(self):
        return closing(sqlite3.connect(self.path, timeout=15))

    def rows(self, owner=None, run=None):
        clauses, args = [], []
        for key, value in (("owner", owner), ("run", run)):
            if value is not None:
                clauses.append(key + "=?")
                args.append(value)
        with self.db() as db:
            rows = db.execute(
                "SELECT payload FROM human_inputs"
                + (" WHERE " + " AND ".join(clauses) if clauses else "")
                + " ORDER BY rowid",
                args,
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get(self, owner, run, identity):
        row = next((r for r in self.rows(owner, run) if r["request_id"] == identity), None)
        if not row:
            raise ServiceCheckError("LIVE_HUMAN_INPUT_NOT_FOUND", 404)
        return row

    def receive(self, event, run, node, endpoint):
        identity = hashlib.sha256(json.dumps([endpoint, event["eventId"]]).encode()).hexdigest()
        request = normalize_request(event)
        with self.db() as db, db:
            previous = db.execute("SELECT payload FROM human_inputs WHERE id=?", (identity,)).fetchone()
            if previous:
                row = json.loads(previous[0])
                if any(
                    row[k] != v
                    for k, v in {
                        "owner": run["owner"],
                        "run_id": run["run_id"],
                        "session_id": node["session_id"],
                    }.items()
                ):
                    raise ServiceCheckError("LIVE_HUMAN_INPUT_BINDING_CHANGED")
                # A replay after an uncertain HTTP acknowledgement proves the
                # native request is still waiting. An answered request stays final.
                if row["status"] == "UNCERTAIN":
                    row.update(status="PENDING", command_id=None, response=None)
            else:
                row = {
                    **request,
                    "request_id": identity,
                    "event_id": event["eventId"],
                    "endpoint": endpoint,
                    "owner": run["owner"],
                    "run_id": run["run_id"],
                    "project_id": run["project_id"],
                    "phase": run["phase"],
                    "run_title": run["title"],
                    "node_id": node["id"],
                    "node_title": node.get("title") or node["id"],
                    "session_id": node["session_id"],
                    "status": "PENDING",
                    "created_at": now(),
                }
            db.execute(
                "INSERT OR REPLACE INTO human_inputs VALUES(?,?,?,?)",
                (identity, row["owner"], row["run_id"], json.dumps(row, ensure_ascii=False)),
            )
        return row

    def update(self, identity, **change):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            value = db.execute("SELECT payload FROM human_inputs WHERE id=?", (identity,)).fetchone()
            if not value:
                return None
            row = {**json.loads(value[0]), **change}
            db.execute("UPDATE human_inputs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity))
        return row

    def claim(self, owner, run, identity, command, response):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            value = db.execute(
                "SELECT payload FROM human_inputs WHERE id=? AND owner=? AND run=?", (identity, owner, run)
            ).fetchone()
            if not value:
                raise ServiceCheckError("LIVE_HUMAN_INPUT_NOT_FOUND", 404)
            row = json.loads(value[0])
            if row["status"] == "ANSWERED" and row.get("command_id") == command and row.get("response") == response:
                return row, False
            if row["status"] != "PENDING":
                raise ServiceCheckError("LIVE_HUMAN_INPUT_CHANGED")
            row.update(
                status="SENDING",
                command_id=command,
                response=response,
                responded_by=owner,
                sender_pid=os.getpid(),
                send_started_at=time.time(),
            )
            db.execute("UPDATE human_inputs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity))
        return row, True

    def waiting(self, run, session=None):
        return any(
            row["status"] in WAITING and (session is None or row["session_id"] == session) for row in self.rows(run=run)
        )

    def open_gate(self, run, node, source_digest, round_number, *, exhausted=False, can_approve=False):
        binding = [run["run_id"], run["phase"], run["approved_plan_digest"], node["id"], source_digest, round_number]
        identity = hashlib.sha256(json.dumps(binding).encode()).hexdigest()
        options = ([{"label": "Duyệt kết quả", "description": "Tiếp tục sau khi đã xem diff và bằng chứng kiểm thử."}] if can_approve else [])
        if not exhausted:
            options.append({"label": "Yêu cầu sửa", "description": "Ghi rõ nội dung cần sửa trong phần thông tin bổ sung."})
        options.append({"label": "Dừng lượt này", "description": "Giữ bằng chứng và dừng công việc để xem lại."})
        title = "Đã hết số vòng sửa; cần bạn quyết định" if exhausted else "Workflow đang chờ bạn duyệt kết quả"
        row = {"request_id": identity, "origin": "workflow_gate", "event_id": "local:"+identity, "endpoint": "local",
               "owner": run["owner"], "run_id": run["run_id"], "project_id": run["project_id"], "phase": run["phase"],
               "plan_digest": run["approved_plan_digest"], "source_digest": source_digest, "gate_round": round_number,
               "node_id": node["id"], "node_title": node["title"], "session_id": "", "run_title": run["title"],
               "kind": "question", "title": title, "status": "PENDING", "created_at": now(),
               "questions": [{"id": "gate", "question": title+". "+" ".join(node.get("acceptance", [])), "header": node["title"], "multi_select": False, "options": options}]}
        with self.db() as db, db:
            db.execute("INSERT OR IGNORE INTO human_inputs VALUES(?,?,?,?)", (identity, run["owner"], run["run_id"], json.dumps(row, ensure_ascii=False)))
        return self.get(run["owner"], run["run_id"], identity)

    @staticmethod
    def gate_bound(row, run):
        return run["state"] == "RUNNING" and run["phase"] == row["phase"] and run.get("approved_plan_digest") == row["plan_digest"] and any(n["id"] == row["node_id"] and n.get("state") == "WAITING_INPUT" and n.get("candidate_digest") == row["source_digest"] for n in run.get("nodes", []))

    def answer_gate(self, owner, run, identity, command, response):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute("SELECT payload FROM human_inputs WHERE id=? AND owner=? AND run=?", (identity, owner, run["run_id"])).fetchone()
            if not saved:
                raise ServiceCheckError("LIVE_HUMAN_INPUT_NOT_FOUND", 404)
            row = json.loads(saved[0])
            value = validate_answer(row, response)
            if row["status"] == "ANSWERED" and row.get("command_id") == command and row.get("response") == value:
                return row
            if row.get("origin") != "workflow_gate" or row["status"] != "PENDING" or not self.gate_bound(row, run):
                raise ServiceCheckError("LIVE_HUMAN_INPUT_CHANGED")
            answer = value["answers"][0]
            if len(answer["selected"]) != 1 or (answer["selected"][0] == "Yêu cầu sửa" and len(answer.get("custom", "").strip()) < 5):
                raise ServiceCheckError("LIVE_GATE_FEEDBACK_REQUIRED", 422)
            decision = {"Duyệt kết quả": "approved", "Yêu cầu sửa": "changes_requested", "Dừng lượt này": "stopped"}[answer["selected"][0]]
            row.update(status="ANSWERED", response=value, command_id=command, responded_at=now(), responded_by=owner,
                       gate_decision=decision, feedback=answer.get("custom", ""))
            db.execute("UPDATE human_inputs SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity))
        return row


class HumanInputMonitor:
    def __init__(self, live):
        self.live = live
        self.store = HumanInputStore(live.store.path)
        # A process can exit after sending a reply and before saving its HTTP
        # acknowledgement. Keep that outcome uncertain until native replay proves
        # the question is still pending; never resend a decision during recovery.
        import psutil

        for row in self.store.rows():
            if row["status"] != "SENDING":
                continue
            try:
                sender = psutil.Process(row.get("sender_pid", -1))
                alive = sender.create_time() <= row.get("send_started_at", 0)
            except (psutil.Error, ValueError):
                alive = False
            if not alive:
                self.store.update(row["request_id"], status="UNCERTAIN")
        self.task = None
        self.stream = None
        self.endpoint = None
        self.current = {}
        self.locks = {}
        self.connected = asyncio.Event()
        self.stopping = False
        self.legacy_cache = {}

    def start(self):
        if self.task is None or self.task.done():
            self.stopping = False
            self.task = asyncio.create_task(self.listen())

    async def ready(self):
        self.start()
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=20)
        except TimeoutError:
            raise ServiceCheckError("LIVE_HUMAN_INPUT_UNAVAILABLE", 503) from None

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.connected.clear()

    def bind(self, session):
        # Worker snapshots register the session before its first prompt. Refresh
        # only local runs; never enumerate or expose another Harness user's work.
        with closing(self.live.store.db()) as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM runs")]
        for row in rows:
            if row["state"] not in ACTIVE_RUNS:
                continue
            row = self.live.observe(row)
            for node in row.get("nodes", []):
                if node.get("session_id") == session and not node.get("reused_from"):
                    return row, node
        return None

    def receive(self, event):
        eid = event.get("eventId")
        if not isinstance(eid, str) or not eid:
            return
        if event.get("type") == "cancel":
            identity = self.current.pop(eid, None)
            if identity:
                row = next((r for r in self.store.rows() if r["request_id"] == identity), None)
                if row and row["status"] == "PENDING":
                    self.store.update(identity, status="RESOLVED_ELSEWHERE", resolved_at=now())
            return
        if event.get("type") != "waterfall" or event.get("event") not in {"user-questions/request", "approval/request"}:
            return
        bound = self.bind(event.get("agentId") or event.get("sessionId"))
        if not bound:
            return
        try:
            row = self.store.receive(event, *bound, self.endpoint)
        except ValueError:
            return
        if row["status"] in WAITING:
            self.current[eid] = row["request_id"]

    async def listen(self):
        delay = 1
        while not self.stopping:
            try:
                from dsh_web_sdk import DshClient, RetryConfig
                from dsh_web_sdk.events import HarnessEvents

                self.endpoint, token = settings()
                async with DshClient(self.endpoint, token, timeout=15, retry=RetryConfig(max_attempts=1)) as client:
                    async with HarnessEvents(client) as stream:
                        self.current = {}
                        self.stream = stream
                        self.connected.set()
                        delay = 1
                        async for event in stream.events():
                            self.receive(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Credentials, raw native payloads and unrelated events never go
                # to application logs. The UI displays this connection state.
                pass
            finally:
                self.stream = None
                self.connected.clear()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15)

    def public(self, row):
        local = row.get("origin") == "workflow_gate"
        bound = self.store.gate_bound(row, self.live.observe(self.live.store.get(row["owner"], row["run_id"]))) if local else False
        return {
            **{
                k: v
                for k, v in row.items()
                if k not in {"owner", "endpoint", "event_id", "command_id", "sender_pid", "send_started_at"}
            },
            "can_respond": row["status"] == "PENDING" and (bound if local else self.connected.is_set() and row["event_id"] in self.current),
        }

    def pending(self, owner, run=None):
        rows = []
        for row in self.store.rows(owner, run):
            if row["status"] not in WAITING:
                continue
            # During a connection loss retain the visible question. On a fresh
            # connection only replayed native requests are actionable.
            if row.get("origin") != "workflow_gate" and self.connected.is_set() and row["event_id"] not in self.current:
                continue
            current = self.live.store.get(owner, row["run_id"])
            if current["state"] in ACTIVE_RUNS:
                rows.append(self.public(row))
        return rows

    async def legacy_reviews(self, owner):
        """Include the advanced view's existing human gates in the same inbox."""
        cached = self.legacy_cache.get(owner)
        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]
        from langflow.api.v1 import adlc as runtime

        service = await runtime.get_adlc_run_service()
        history = await service.list_runs(owner_id=owner, limit=100)
        summaries = list(history.runs)
        while len(summaries) < history.total:
            page = await service.list_runs(owner_id=owner, limit=100, offset=len(summaries))
            if not page.runs:
                raise RuntimeError("LIVE_ADVANCED_INBOX_HISTORY_INCOMPLETE")
            summaries.extend(page.runs)
        callbacks = runtime.get_harness_callback_receiver()
        result = []
        seen = set()
        for summary in summaries:
            if summary.id in seen:
                continue
            seen.add(summary.id)
            status = summary.status.value
            if status not in {"RUNNING", "WAITING_APPROVAL", "PAUSED"}:
                continue
            attempts = await callbacks.attempts.list_for_workflow_run(summary.id)
            pending = [a for a in attempts if a.status.value in {"WAITING_INTERACTION", "READY_TO_SUBMIT"}]
            if status in {"WAITING_APPROVAL", "PAUSED"} or pending:
                gate = status + ":" + ",".join(sorted(str(a.attempt_id) + ":" + a.status.value for a in pending))
                result.append(
                    {
                        "request_id": "advanced:" + str(summary.id) + ":" + gate,
                        "run_id": str(summary.id),
                        "project_id": "",
                        "run_title": summary.name,
                        "kind": "advanced",
                        "title": "Công việc cần bạn xác nhận",
                        "href": "/runs/" + str(summary.id),
                    }
                )
        self.legacy_cache[owner] = (time.monotonic(), result)
        return result

    async def answer(self, owner, run, identity, command, response):
        async with self.locks.setdefault(identity, asyncio.Lock()):
            row = self.store.get(owner, run["run_id"], identity)
            if row.get("origin") == "workflow_gate":
                return self.public(self.store.answer_gate(owner, run, identity, command, response))
            value = validate_answer(row, response)
            if row["status"] == "ANSWERED" and row.get("command_id") == command and row.get("response") == value:
                return self.public(row)
            await self.ready()
            if (
                row["endpoint"] != self.endpoint
                or run["state"] not in ACTIVE_RUNS
                or run["phase"] != row["phase"]
                or not any(n.get("session_id") == row["session_id"] and n["id"] == row["node_id"] for n in run["nodes"])
                or row["event_id"] not in self.current
            ):
                raise ServiceCheckError("LIVE_HUMAN_INPUT_CHANGED")
            row, fresh = self.store.claim(owner, run["run_id"], identity, command, value)
            if not fresh:
                return self.public(row)
            try:
                await self.stream.answer(row["event_id"], value)
            except Exception:
                self.store.update(identity, status="UNCERTAIN")
                # Reconnect replays only requests that genuinely remain pending.
                if self.stream and self.stream.socket:
                    await self.stream.socket.close()
                raise ServiceCheckError("LIVE_HUMAN_RESPONSE_UNCONFIRMED", 503) from None
            self.current.pop(row["event_id"], None)
            return self.public(self.store.update(identity, status="ANSWERED", responded_at=now()))


class ActiveClock:
    """Count execution time while allowing a human to take time to answer."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.previous = clock()
        self.elapsed = 0.0

    def tick(self, paused=False):
        current = self.clock()
        if not paused:
            self.elapsed += current - self.previous
        self.previous = current
        return self.elapsed


async def wait_native_contract(client, workspace, number, *, waiting, timeout_s, stall_s, poll_s, on_status=None):
    from dsh_web_sdk.taskloop import TERMINAL_STATUSES, get_task

    clock, activity_at, previous = ActiveClock(), 0, None
    while True:
        paused = waiting()
        elapsed = clock.tick(paused)
        task = await get_task(client, workspace, number)
        signature = json.dumps([task.get("status"), task.get("comments", [])], sort_keys=True)
        if signature != previous:
            previous, activity_at = signature, elapsed
            if on_status:
                result = on_status(task)
                if inspect.isawaitable(result):
                    await result
        if task.get("status") in TERMINAL_STATUSES:
            return task
        if not paused and (elapsed >= timeout_s or elapsed - activity_at >= stall_s):
            return {
                "status": task.get("status", "IN_PROGRESS"),
                "timeout": elapsed >= timeout_s,
                "stalled": elapsed - activity_at >= stall_s,
            }
        await asyncio.sleep(poll_s)


async def wait_worker(child, waiting, timeout_s=3600, *, progress=None, poll_s=3):
    return await wait_active(child.wait(), waiting, timeout_s, progress=progress, poll_s=poll_s)


async def wait_active(awaitable, waiting, timeout_s, *, progress=None, poll_s=3):
    clock = ActiveClock()
    task = asyncio.create_task(awaitable)
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=poll_s)
            elapsed = clock.tick(waiting())
            if progress is not None:
                progress(elapsed)
            if elapsed >= timeout_s:
                raise TimeoutError("Execution time limit reached")
        return await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

"""Owned Slack credentials and durable, bounded delivery to source threads."""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from langflow.adlc.document_progress import LABELS, authorized, facts, safe_line
from langflow.adlc.vai_services import ServiceCheckError, now


class SlackAPI:
    async def call(self, method, token, payload):
        if method not in {"auth.test", "chat.postMessage"}:
            raise ServiceCheckError("SLACK_METHOD_DENIED", 403)
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
                response = await client.post(
                    "https://slack.com/api/" + method, json=payload, headers={"Authorization": "Bearer " + token}
                )
            if response.status_code == 429:
                delay = response.headers.get("Retry-After", "60")
                return {
                    "delivery": "RETRY",
                    "delay": min(3600, max(1, int(delay) if delay.isdigit() else 60)),
                    "error": "SLACK_RATE_LIMITED",
                }
            if not response.is_success or len(response.content) > 128000:
                return {"delivery": "UNCONFIRMED", "error": "SLACK_DELIVERY_UNCONFIRMED"}
            result = response.json()
            if result.get("ok") is not True:
                code = result.get("error")
                return {
                    "delivery": "ERROR",
                    "error": "SLACK_" + code.upper()
                    if code
                    in {
                        "invalid_auth",
                        "token_revoked",
                        "missing_scope",
                        "not_in_channel",
                        "channel_not_found",
                        "account_inactive",
                    }
                    else "SLACK_REQUEST_REJECTED",
                }
            if method == "chat.postMessage" and (
                result.get("channel") != payload.get("channel")
                or not re.fullmatch(r"\d+\.\d+", str(result.get("ts") or ""))
                or (payload.get("thread_ts") and (result.get("message") or {}).get("thread_ts") != payload["thread_ts"])
            ):
                return {"delivery": "UNCONFIRMED", "error": "SLACK_DELIVERY_UNCONFIRMED"}
            return {**result, "delivery": "SENT"}
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # No connection was obtained: the message body was never sent.
            return {"delivery": "RETRY", "delay": 60, "error": "SLACK_CONNECTION_UNAVAILABLE"}
        except Exception:
            # A lost reply can follow an accepted send. Never automatically repeat it.
            return {"delivery": "UNCONFIRMED", "error": "SLACK_DELIVERY_UNCONFIRMED"}


def encrypt(value):
    from langflow.services.auth.utils import encrypt_api_key

    return encrypt_api_key(value)


def decrypt(value):
    from langflow.services.auth.utils import decrypt_api_key

    return decrypt_api_key(value)


def receipt_link(channel, thread, message_ts):
    from langflow.adlc.document_intake import public_document

    if not all(re.fullmatch(r"\d+\.\d+", str(v or "")) for v in (thread, message_ts)):
        return None
    base = public_document({"slack_channel": channel, "slack_thread": message_ts}).get("slack_url")
    return base + "?" + urlencode({"thread_ts": thread, "cid": channel}) if base else None


def notification_state(row, live):
    value = facts(row, live)
    if value.get("run_id") and value["run_state"] != "UNCONFIRMED":
        pending = live.human_input.pending(row["owner"], value["run_id"])
        value["attention"] = sorted(str(x.get("request_id") or x.get("id") or x.get("digest")) for x in pending)
    revision = row.get("revision_request") or {}
    value["revision"] = [revision.get("id"), revision.get("state")]
    value["notice_state"] = (
        "REVISING"
        if revision.get("state") == "PROCESSING"
        else "REVISION_FAILED"
        if revision.get("state") in {"FAILED", "ERROR"}
        else "NEEDS_CHANGES"
        if revision.get("state") in {"SENDING", "SENT", "UNCONFIRMED"}
        else "DOCUMENT_UPDATED"
        if revision.get("state") == "UPDATED" and not row.get("approval")
        else value["run_state"]
    )
    return value


def transition_key(snapshot):
    # Counts/heartbeat timestamps alone never produce more messages.
    return json.dumps(
        [snapshot.get(k) for k in ("run_id", "notice_state", "attention", "handover_url", "merged", "revision")],
        sort_keys=True,
    )


def message(row, snapshot, report_link):
    state = snapshot.get("notice_state")
    label = (
        "Tài liệu có phiên bản mới, cần xem lại"
        if state == "DOCUMENT_UPDATED"
        else LABELS.get(state, "Cập nhật tiến độ")
    )
    title = safe_line(row.get("title"), 180).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = ["vAIPlatform · " + title, label, "Yêu cầu: " + row["lifecycle_id"]]
    if snapshot.get("run_id"):
        lines += [
            "Lượt chạy: " + snapshot["run_id"],
            "Lượt chạy dùng tài liệu v" + str(snapshot.get("run_page_version") or "—"),
            f"Task: {snapshot.get('tasks_done', 0)}/{snapshot.get('tasks_total', 0)} · Chờ phản hồi: {snapshot.get('human_inputs', 0)}",
            f"Kiểm tra đạt: {snapshot.get('tests_passed', 0)}/{snapshot.get('tests_total', 0)}",
        ]
    if report_link:
        lines.append("Báo cáo: " + report_link)
    if snapshot.get("handover_url"):
        lines.append("Pull request: " + snapshot["handover_url"])
        lines.append("Đã hợp nhất: " + ("Có" if snapshot.get("merged") else "Chưa"))
    base = os.getenv("VAI_WORKSPACE_PUBLIC_URL", "http://127.0.0.1:7861").rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    ):
        lines.append(base + "/work?view=requests&document=" + row["document_id"])
    lines.append("Cập nhật (UTC): " + now())
    return "\n".join(lines)


class SlackNotifications:
    def __init__(self, intake, live=None, gateway=None, permission=None, seal=None, unseal=None):
        self.intake, self.live = intake, live
        self.gateway, self.permission = gateway or SlackAPI(), permission or authorized
        self.seal, self.unseal = seal or encrypt, unseal or decrypt
        with intake.db() as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS intake_slack_credentials(owner TEXT PRIMARY KEY, cipher TEXT, identity TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS intake_slack_outbox(id TEXT PRIMARY KEY, owner TEXT, document TEXT, channel TEXT, thread TEXT, payload TEXT, state TEXT, error TEXT, available REAL, created TEXT, delivered TEXT)"
            )
            if "message_ts" not in {r[1] for r in db.execute("PRAGMA table_info(intake_slack_outbox)")}:
                db.execute("ALTER TABLE intake_slack_outbox ADD COLUMN message_ts TEXT")
            # A previous process may have sent a message before losing its reply.
            db.execute(
                "UPDATE intake_slack_outbox SET state='UNCONFIRMED',error='SLACK_DELIVERY_UNCONFIRMED' WHERE state='SENDING'"
            )

    def credentials(self, owner):
        with self.intake.db() as db:
            row = db.execute("SELECT cipher,identity FROM intake_slack_credentials WHERE owner=?", (owner,)).fetchone()
        return row

    def settings(self, owner):
        row = self.credentials(owner)
        return {"configured": bool(row), "identity": json.loads(row[1]) if row else None}

    async def connect(self, owner, token):
        if not re.fullmatch(r"xoxb-[A-Za-z0-9-]{15,300}", token):
            raise ServiceCheckError("SLACK_BOT_TOKEN_REQUIRED", 422)
        response = await self.gateway.call("auth.test", token, {})
        expected = urlsplit(os.getenv("VAI_SLACK_WORKSPACE_URL", "https://adlcfactory.slack.com/"))
        if response.get("delivery") != "SENT" or not response.get("bot_id"):
            raise ServiceCheckError(response.get("error") or "SLACK_AUTH_UNCONFIRMED", 503)
        if urlsplit(response.get("url", "")).hostname != expected.hostname:
            raise ServiceCheckError("SLACK_WORKSPACE_MISMATCH", 409)
        identity = {k: safe_line(response.get(k), 100) for k in ("team", "team_id", "user", "user_id", "bot_id")}
        identity["verified_at"] = now()
        cipher = self.seal(token)
        if not cipher or cipher == token:
            raise ServiceCheckError("SLACK_SECRET_STORAGE_UNAVAILABLE", 503)
        with self.intake.db() as db, db:
            db.execute(
                "INSERT OR REPLACE INTO intake_slack_credentials VALUES(?,?,?)", (owner, cipher, json.dumps(identity))
            )
            failed = db.execute(
                "SELECT id,document,payload FROM intake_slack_outbox e WHERE owner=? AND state='ERROR' AND rowid=(SELECT MAX(rowid) FROM intake_slack_outbox WHERE owner=e.owner AND document=e.document)",
                (owner,),
            ).fetchall()
            for event_id, document_id, payload in failed:
                row = self.intake.get(owner, document_id)
                notification = row.get("notifications") or {}
                if notification.get("enabled") and notification.get("observed") == transition_key(
                    json.loads(payload)["snapshot"]
                ):
                    db.execute(
                        "UPDATE intake_slack_outbox SET state='PENDING',error=NULL,available=0 WHERE id=?", (event_id,)
                    )
        return self.settings(owner)

    def disconnect(self, owner):
        with self.intake.db() as db, db:
            db.execute("DELETE FROM intake_slack_credentials WHERE owner=?", (owner,))
            db.execute(
                "UPDATE intake_slack_outbox SET state='CANCELLED' WHERE owner=? AND state IN ('PENDING','RETRY')",
                (owner,),
            )
        return self.settings(owner)

    def configure(self, owner, identity, enabled):
        def change(row):
            if not row.get("slack_channel") or not row.get("slack_thread"):
                raise ServiceCheckError("INTAKE_CHANNEL_MISSING", 422)
            current = row.setdefault("notifications", {})
            if current.get("enabled") != enabled:
                current.update(generation=str(uuid4()), observed=None)
            current.update(
                enabled=enabled, state="READY" if self.settings(owner)["configured"] else "NEEDS_CONFIGURATION"
            )

        result = self.intake.change(owner, identity, change)
        if not enabled:
            with self.intake.db() as db, db:
                db.execute(
                    "UPDATE intake_slack_outbox SET state='CANCELLED' WHERE owner=? AND document=? AND state IN ('PENDING','RETRY')",
                    (owner, str(identity)),
                )
        return result

    def history(self, owner, identity):
        with self.intake.db() as db:
            rows = db.execute(
                "SELECT id,state,error,created,delivered,message_ts,channel,thread FROM intake_slack_outbox WHERE owner=? AND document=? ORDER BY rowid DESC LIMIT 5",
                (owner, str(identity)),
            ).fetchall()
        return [
            {
                "id": r[0],
                "state": r[1],
                "error_code": r[2],
                "created_at": r[3],
                "delivered_at": r[4],
                "message_url": receipt_link(r[6], r[7], r[5]) if r[1] == "SENT" else None,
            }
            for r in rows
        ]

    async def observe(self, owner, identity):
        row = self.intake.get(owner, identity)
        config = row.get("notifications") or {}
        if not config.get("enabled"):
            return
        await self.permission(row, self.live)
        if not self.settings(owner)["configured"]:
            self.intake.change(
                owner, identity, lambda current: current["notifications"].update(state="NEEDS_CONFIGURATION")
            )
            return
        snapshot = notification_state(row, self.live)
        key = transition_key(snapshot)
        old = config.get("observed")
        eligible = snapshot["notice_state"] in {
            "PLAN_READY",
            "PLANNING",
            "RUNNING",
            "WAITING_INPUT",
            "FAILED",
            "SUCCEEDED",
            "UNCONFIRMED",
            "DOCUMENT_UPDATED",
            "NEEDS_CHANGES",
            "REVISING",
            "REVISION_FAILED",
            "NOT_STARTED",
        }
        if old == key:
            if config.get("state") == "NEEDS_CONFIGURATION":
                self.intake.change(
                    owner, identity, lambda current: current["notifications"].update(state="READY", error_code=None)
                )
            return
        event_id = str(uuid5(NAMESPACE_URL, f"vai:{owner}:{identity}:{config.get('generation')}:{old}:{key}"))
        payload = {"text": message(row, snapshot, row.get("progress", {}).get("link")), "snapshot": snapshot}
        with self.intake.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            latest = json.loads(
                db.execute(
                    "SELECT payload FROM intake_documents WHERE owner=? AND id=?", (owner, str(identity))
                ).fetchone()[0]
            )
            notification = latest.get("notifications") or {}
            if not notification.get("enabled") or notification.get("observed") != old:
                return
            notification.update(observed=key, state="READY")
            db.execute(
                "UPDATE intake_slack_outbox SET state='SUPERSEDED' WHERE owner=? AND document=? AND state IN ('PENDING','RETRY')",
                (owner, str(identity)),
            )
            if eligible:
                db.execute(
                    "INSERT OR IGNORE INTO intake_slack_outbox(id,owner,document,channel,thread,payload,state,error,available,created,delivered) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        owner,
                        str(identity),
                        row["slack_channel"],
                        row["slack_thread"],
                        json.dumps(payload),
                        "PENDING",
                        None,
                        time.time(),
                        now(),
                        None,
                    ),
                )
            db.execute(
                "UPDATE intake_documents SET payload=? WHERE owner=? AND id=?",
                (json.dumps(latest), owner, str(identity)),
            )

    async def deliver(self):
        with self.intake.db() as db:
            rows = db.execute(
                "SELECT id,owner,document,channel,thread,payload FROM intake_slack_outbox WHERE state IN ('PENDING','RETRY') AND available<=? ORDER BY rowid LIMIT 3",
                (time.time(),),
            ).fetchall()
        sent_channels = set()
        for event_id, owner, identity, channel, thread, raw in rows:
            if channel in sent_channels:
                continue
            row = self.intake.get(owner, identity)
            if not row.get("notifications", {}).get("enabled"):
                with self.intake.db() as db, db:
                    db.execute("UPDATE intake_slack_outbox SET state='CANCELLED' WHERE id=?", (event_id,))
                continue
            try:
                await self.permission(row, self.live)
                await self.intake.validate_source(owner, identity)
            except ServiceCheckError as exc:
                if exc.status in {403, 404} or exc.code == "INTAKE_DOCUMENT_CHANGED":
                    with self.intake.db() as db, db:
                        db.execute(
                            "UPDATE intake_slack_outbox SET state='CANCELLED',error=? WHERE id=?", (exc.code, event_id)
                        )
                continue
            if (row.get("slack_channel"), row.get("slack_thread")) != (channel, thread):
                continue
            credential = self.credentials(owner)
            if not credential:
                continue
            try:
                token = self.unseal(credential[0])
            except Exception:
                with self.intake.db() as db, db:
                    db.execute(
                        "UPDATE intake_slack_outbox SET state='ERROR',error='SLACK_SECRET_STORAGE_UNAVAILABLE' WHERE id=?",
                        (event_id,),
                    )
                self.intake.change(
                    owner,
                    identity,
                    lambda current: current.setdefault("notifications", {}).update(
                        state="ERROR", error_code="SLACK_SECRET_STORAGE_UNAVAILABLE"
                    ),
                )
                continue
            with self.intake.db() as db, db:
                changed = db.execute(
                    "UPDATE intake_slack_outbox SET state='SENDING' WHERE id=? AND state IN ('PENDING','RETRY')",
                    (event_id,),
                ).rowcount
            if not changed:
                continue
            payload = json.loads(raw)
            result = await self.gateway.call(
                "chat.postMessage",
                token,
                {
                    "channel": channel,
                    "thread_ts": thread,
                    "text": payload["text"],
                    "mrkdwn": False,
                    "unfurl_links": False,
                    "unfurl_media": False,
                    "reply_broadcast": False,
                    "client_msg_id": event_id,
                    "metadata": {"event_type": "vai_progress", "event_payload": {"event_id": event_id}},
                },
            )
            state = result["delivery"]
            with self.intake.db() as db, db:
                db.execute(
                    "UPDATE intake_slack_outbox SET state=?,error=?,available=?,delivered=?,message_ts=? WHERE id=?",
                    (
                        state,
                        result.get("error"),
                        time.time() + result.get("delay", 0),
                        now() if state == "SENT" else None,
                        result.get("ts") if state == "SENT" else None,
                        event_id,
                    ),
                )
            receipt = next((r for r in self.history(owner, identity) if r["id"] == event_id), {})

            def record(current):
                notification = current.setdefault("notifications", {})
                notification.update(state=state, error_code=result.get("error"))
                if state == "SENT":
                    notification.update(
                        last_message_url=receipt.get("message_url"), last_sent_at=receipt.get("delivered_at")
                    )

            self.intake.change(owner, identity, record)
            sent_channels.add(channel)

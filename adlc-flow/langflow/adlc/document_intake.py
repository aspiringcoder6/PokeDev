"""Slack/Confluence inbox, versioned project decisions and native execution handoff."""

from __future__ import annotations

import asyncio
from contextlib import closing
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import json
import os
import re
import sqlite3
import time
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid5

from langflow.adlc.gitea_projects import DATA
from langflow.adlc.delivery import MAX_REQUIREMENT_CHARS
from langflow.adlc.project_workloop import WorkloopClient, text
from langflow.adlc.vai_services import ServiceCheckError, now
from langflow.adlc.workloop_integration import WorkloopIntegration, bot_link


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "tr", "br", "ul", "ol", "pre"}:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("\n- ")
        if re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        if tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "tr", "li", "pre"} or re.fullmatch(r"h[1-6]", tag):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def page_text(body):
    if len(str(body)) > 250000:
        raise ServiceCheckError("INTAKE_DOCUMENT_TOO_LARGE", 422)
    parser = PageText()
    parser.feed(str(body))
    value = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts)).strip()
    if len(value) > 60000:
        raise ServiceCheckError("INTAKE_DOCUMENT_TOO_LARGE", 422)
    # Redact in small pieces: the common log redactor intentionally truncates
    # long strings. A requirement must never be silently truncated.
    return "".join(text(value[i : i + 8000], 8000) for i in range(0, len(value), 8000))


def source_document(raw):
    identity = str(raw.get("id", ""))
    if not identity.isdigit():
        raise ServiceCheckError("INTAKE_SOURCE_INVALID", 503)
    channel, thread = str(raw.get("slack_channel") or ""), str(raw.get("slack_thread") or "")
    page = str(raw.get("confluence_page_id") or "")
    url = str(raw.get("confluence_link") or "")
    if not page.isdigit():
        match = re.search(r"/pages/(\d+)", url)
        page = match[1] if match else ""
    parsed = urlsplit(url)
    safe_url = (
        url if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None
    )
    return {
        "document_id": identity,
        "title": text(raw.get("title"), 300),
        "doc_type": text(raw.get("doc_type"), 80),
        "lifecycle_id": text(raw.get("lifecycle_id"), 150),
        "page_id": page,
        "confluence_url": safe_url,
        "slack_channel": channel if re.fullmatch(r"[CDG][A-Z0-9]{5,40}", channel) else "",
        "slack_thread": thread if re.fullmatch(r"\d+\.\d+", thread) else "",
        "source_status": str(raw.get("status") or "pending"),
        "created_at": raw.get("created_at"),
    }


def public_document(row, *, body=False):
    value = {k: v for k, v in row.items() if k not in {"owner", "page_body", "execution_snapshot", "command"}}
    if row.get("command"):
        value["plan_command"] = {
            k: row["command"].get(k) for k in ("id", "workflow_id", "workflow_digest", "state", "error_code", "digest")
        }
    if row.get("progress"):
        value["progress"] = {
            k: row["progress"].get(k) for k in ("enabled", "state", "page_id", "link", "synced_at", "error_code")
        }
    if row.get("notifications"):
        value["notifications"] = {
            k: row["notifications"].get(k)
            for k in ("enabled", "state", "error_code", "last_message_url", "last_sent_at")
        }
    if body:
        value["body"] = row.get("page_body", "")
    for key in ("revision_request", "revision_history"):
        if key in value:

            def visible(revision):
                return {k: v for k, v in revision.items() if k not in {"wire_comment", "page_digest", "actor"}}

            value[key] = [visible(r) for r in value[key]] if key == "revision_history" else visible(value[key])
    if value.get("slack_channel") and value.get("slack_thread"):
        workspace = urlsplit(os.getenv("VAI_SLACK_WORKSPACE_URL", "https://adlcfactory.slack.com/"))
        if (
            workspace.scheme == "https"
            and workspace.hostname
            and workspace.hostname.endswith(".slack.com")
            and not workspace.username
            and not workspace.password
            and workspace.path in {"", "/"}
            and not workspace.query
            and not workspace.fragment
        ):
            value["slack_url"] = (
                "https://"
                + workspace.hostname
                + "/archives/"
                + value["slack_channel"]
                + "/p"
                + value["slack_thread"].replace(".", "")
            )
    return value


def intake_requirement(row):
    requirement = (
        f"Nguồn: {row.get('confluence_url') or row['page_id']}\nPhiên bản: {row['page_version']}\nRepo: {row['repository']}\n"
        f"Lifecycle: {row['lifecycle_id']}\n\n{row.get('instructions') or ''}\n\nTÀI LIỆU ĐÃ DUYỆT:\n{row['page_body']}"
    )
    # Keep the normal delivery contract's limit. Never create an orphan flow
    # and never silently trim the approved requirement to fit the planner.
    if len(requirement) > MAX_REQUIREMENT_CHARS:
        raise ServiceCheckError("INTAKE_PLAN_TOO_LARGE", 422)
    return requirement


class ConfluencePages:
    async def read(self, identity):
        from langflow.adlc.document_progress import ConfluenceTools

        if not re.fullmatch(r"\d{1,30}", str(identity)):
            raise ServiceCheckError("INTAKE_PAGE_MISSING", 409)
        try:
            value = await ConfluenceTools().call("confluence_get_page", {"page_id": str(identity)})
            if str(value.get("id")) != str(identity) or not isinstance(value.get("body"), str):
                raise ValueError()
            version = value.get("version")
            if isinstance(version, dict):
                version = version.get("number")
            if type(version) is not int or version < 1:
                raise ValueError()
            body = page_text(value["body"])
            if not body:
                raise ValueError()
            return {
                "version": version,
                "title": text(value.get("title"), 300),
                "body": body,
                "digest": hashlib.sha256(
                    json.dumps([str(identity), version, body], ensure_ascii=False).encode()
                ).hexdigest(),
            }
        except ServiceCheckError as exc:
            if exc.code == "CONFLUENCE_PAGE_NOT_CURRENT":
                raise ServiceCheckError("INTAKE_PAGE_NOT_CURRENT", 409) from None
            raise ServiceCheckError("INTAKE_CONFLUENCE_UNAVAILABLE", 503) from None
        except Exception:
            raise ServiceCheckError("INTAKE_CONFLUENCE_UNAVAILABLE", 503) from None


class DocumentIntake:
    def __init__(self, path=None, client=None, pages=None):
        self.path = path or DATA / "intake.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.client, self.pages = client or WorkloopClient(), pages or ConfluencePages()
        self.bot_url = bot_link(os.getenv("VAI_SLACK_APP_ID", "A0CA54Q7FV3"), os.getenv("VAI_SLACK_TEAM_ID", ""))
        self.synced, self.locks = {}, {}
        self._progress = None
        self._notifications = None
        with self.db() as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS intake_documents(owner TEXT, id TEXT, project TEXT, payload TEXT, PRIMARY KEY(owner,id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS intake_channels(owner TEXT, channel TEXT, project TEXT, repository TEXT DEFAULT '', PRIMARY KEY(owner,channel))"
            )
            if "repository" not in {r[1] for r in db.execute("PRAGMA table_info(intake_channels)")}:
                db.execute("ALTER TABLE intake_channels ADD COLUMN repository TEXT DEFAULT ''")
            if "share_progress" not in {r[1] for r in db.execute("PRAGMA table_info(intake_channels)")}:
                db.execute("ALTER TABLE intake_channels ADD COLUMN share_progress INTEGER DEFAULT 0")
            if "notify_slack" not in {r[1] for r in db.execute("PRAGMA table_info(intake_channels)")}:
                db.execute("ALTER TABLE intake_channels ADD COLUMN notify_slack INTEGER DEFAULT 0")

    @property
    def notifications(self):
        if self._notifications is None:
            from langflow.adlc.slack_notifications import SlackNotifications

            self._notifications = SlackNotifications(self)
        return self._notifications

    @property
    def progress(self):
        if self._progress is None:
            from langflow.adlc.document_progress import ProgressPublisher

            self._progress = ProgressPublisher(self)
        return self._progress

    def db(self):
        return closing(sqlite3.connect(self.path, timeout=15))

    def rows(self, owner, project=None, *, include_archived=False):
        with self.db() as db:
            rows = db.execute(
                "SELECT payload FROM intake_documents WHERE owner=?"
                + (" AND project=?" if project else "")
                + " ORDER BY rowid DESC",
                (owner, project) if project else (owner,),
            ).fetchall()
        values = [json.loads(r[0]) for r in rows]
        if not include_archived:
            # Workloop also records failed Spec invocations with no page/link.
            # Those audit rows are not documents awaiting a project decision.
            # Keep them stored so a later valid source update is picked up.
            values = [row for row in values if not row.get("archived_at") and row.get("page_id")]
        return sorted(values, key=lambda row: (str(row.get("created_at") or ""), int(row["document_id"])), reverse=True)

    def get(self, owner, identity, *, include_archived=False):
        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM intake_documents WHERE owner=? AND id=?", (owner, str(identity))
            ).fetchone()
        if not row:
            raise ServiceCheckError("INTAKE_DOCUMENT_NOT_FOUND", 404)
        value = json.loads(row[0])
        if value.get("archived_at") and not include_archived:
            raise ServiceCheckError("INTAKE_DOCUMENT_ARCHIVED", 410)
        return value

    def save(self, row):
        with self.db() as db, db:
            db.execute(
                "INSERT OR REPLACE INTO intake_documents VALUES(?,?,?,?)",
                (row["owner"], row["document_id"], row.get("project_id") or "", json.dumps(row, ensure_ascii=False)),
            )
        return row

    def change(self, owner, identity, operation, *, allow_archived=False):
        """Merge against the latest row, never against a pre-network snapshot."""
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            stored = db.execute(
                "SELECT payload FROM intake_documents WHERE owner=? AND id=?", (owner, str(identity))
            ).fetchone()
            if not stored:
                raise ServiceCheckError("INTAKE_DOCUMENT_NOT_FOUND", 404)
            row = json.loads(stored[0])
            if row.get("archived_at") and not allow_archived:
                raise ServiceCheckError("INTAKE_DOCUMENT_ARCHIVED", 410)
            operation(row)
            db.execute(
                "UPDATE intake_documents SET project=?,payload=? WHERE owner=? AND id=?",
                (row.get("project_id") or "", json.dumps(row, ensure_ascii=False), owner, str(identity)),
            )
        return row

    def archive(self, owner, identity, *, completed_run=None):
        from langflow.adlc.document_revision import PENDING

        def apply(row):
            if row.get("archived_at"):
                return
            if (
                (row.get("revision_request") or {}).get("state") in PENDING
                or (row.get("command") and not row.get("run_started_at"))
                or (row.get("run_id") and row["run_id"] != completed_run)
            ):
                raise ServiceCheckError("INTAKE_ARCHIVE_ACTIVE", 409)
            row.update(archived_at=now(), state="ARCHIVED", approval=None)
            for key in ("progress", "notifications"):
                row.setdefault(key, {}).update(enabled=False, state="DISABLED")

        row = self.change(owner, identity, apply, allow_archived=True)
        with self.db() as db, db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='intake_slack_outbox'").fetchone():
                db.execute(
                    "UPDATE intake_slack_outbox SET state='CANCELLED' WHERE owner=? AND document=? AND state IN ('PENDING','RETRY')",
                    (owner, str(identity)),
                )
        return row

    def restore(self, owner, identity):
        def apply(row):
            if not row.get("archived_at"):
                return
            row.pop("archived_at")
            row.update(state="NEEDS_REVIEW" if row.get("project_id") else "NEEDS_PROJECT", approval=None)

        return self.change(owner, identity, apply, allow_archived=True)

    def rules(self, owner):
        with self.db() as db:
            return [
                {
                    "channel": r[0],
                    "project_id": r[1],
                    "repository": r[2],
                    "share_progress": bool(r[3]),
                    "notify_slack": bool(r[4]),
                }
                for r in db.execute(
                    "SELECT channel,project,repository,share_progress,notify_slack FROM intake_channels WHERE owner=?",
                    (owner,),
                )
            ]

    async def sync(self, owner, *, force=False):
        async with self.locks.setdefault("sync:" + owner, asyncio.Lock()):
            last = self.synced.get(owner, {})
            if not force and time.time() - last.get("time", 0) < 8:
                return last["result"]
            try:
                raw = await self.client.request("GET", "/lifecycle/spec-docs?limit=200")
                if not isinstance(raw.get("docs"), list):
                    raise ServiceCheckError("INTAKE_SOURCE_INVALID", 503)
                sources = [source_document(s) for s in raw["docs"] if isinstance(s, dict)]
                with self.db() as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    prior = [json.loads(r[0]) for r in db.execute("SELECT payload FROM intake_documents WHERE owner=?", (owner,))]
                    retired = {r["lifecycle_id"]: r["archived_at"] for r in prior if r.get("archived_at")}
                    for row in prior:
                        if not row.get("archived_at"):
                            retired.pop(row.get("lifecycle_id"), None)
                    rules = {
                        r[0]: (r[1], r[2], bool(r[3]), bool(r[4]))
                        for r in db.execute(
                            "SELECT channel,project,repository,share_progress,notify_slack FROM intake_channels WHERE owner=?",
                            (owner,),
                        )
                    }
                    for source in sources:
                        stored = db.execute(
                            "SELECT payload FROM intake_documents WHERE owner=? AND id=?",
                            (owner, source["document_id"]),
                        ).fetchone()
                        old = json.loads(stored[0]) if stored else {}
                        binding = rules.get(source["slack_channel"], ("", "", False, False))
                        row = {
                            "owner": owner,
                            "project_id": binding[0],
                            "repository": binding[1],
                            "state": "NEEDS_PROJECT",
                            "progress": {"enabled": binding[2]},
                            "notifications": {"enabled": binding[3]},
                            **old,
                            **source,
                            "synced_at": now(),
                        }
                        if not old and source["lifecycle_id"] in retired:
                            row.update(archived_at=retired[source["lifecycle_id"]])
                            for key in ("progress", "notifications"):
                                row.setdefault(key, {}).update(enabled=False, state="DISABLED")
                        if old and any(old.get(k) != row.get(k) for k in ("slack_channel", "slack_thread")):
                            row.setdefault("notifications", {}).update(enabled=False, state="TARGET_CHANGED")
                        if old.get("page_id") and old["page_id"] != source["page_id"]:
                            row.update(
                                page_digest=None, page_body="", page_checked_at=0, state="CHANGED", approval=None
                            )
                        if row.get("project_id") and row["state"] == "NEEDS_PROJECT":
                            row["state"] = "NEEDS_REVIEW"
                        if source["source_status"] in {"rejected", "cancelled"}:
                            row.update(state="REJECTED", approval=None)
                        if row.get("archived_at"):
                            row.update(state="ARCHIVED", approval=None)
                        db.execute(
                            "INSERT OR REPLACE INTO intake_documents VALUES(?,?,?,?)",
                            (
                                owner,
                                row["document_id"],
                                row.get("project_id") or "",
                                json.dumps(row, ensure_ascii=False),
                            ),
                        )
                result = {"checked_at": now(), "stale": False, "limit_reached": len(raw["docs"]) >= 200}
                self.synced[owner] = {"time": time.time(), "result": result}
                return result
            except ServiceCheckError:
                return {
                    "checked_at": last.get("result", {}).get("checked_at"),
                    "stale": True,
                    "error_code": "INTAKE_SYNC_UNAVAILABLE",
                }

    def assign(self, owner, identity, project, instructions, automatic=False, share_progress=None, notify_slack=None):
        if automatic and not self.get(owner, identity).get("slack_channel"):
            raise ServiceCheckError("INTAKE_CHANNEL_MISSING", 422)

        def apply(row):
            if row.get("run_id") and row.get("project_id") != project["project_id"]:
                raise ServiceCheckError("INTAKE_EXECUTION_BINDING_FIXED", 409)
            if row.get("command") and not row.get("run_started_at"):
                raise ServiceCheckError("INTAKE_START_PENDING", 409)
            changed = row.get("project_id") != project["project_id"] or row.get("instructions", "") != instructions
            row.update(project_id=project["project_id"], repository=project["repository"], instructions=instructions)
            if changed:
                row.update(state="NEEDS_REVIEW", approval=None)
            if share_progress is not None:
                row.setdefault("progress", {}).update(enabled=share_progress)
            if notify_slack is not None:
                row.setdefault("notifications", {}).update(enabled=notify_slack)

        row = self.change(owner, identity, apply)
        if automatic:
            if not row.get("slack_channel"):
                raise ServiceCheckError("INTAKE_CHANNEL_MISSING", 422)
            with self.db() as db, db:
                db.execute(
                    "INSERT OR REPLACE INTO intake_channels VALUES(?,?,?,?,?,?)",
                    (
                        owner,
                        row["slack_channel"],
                        project["project_id"],
                        project["repository"],
                        int(bool(row.get("progress", {}).get("enabled"))),
                        int(bool(row.get("notifications", {}).get("enabled"))),
                    ),
                )
        if self._progress:
            self._progress.wake.set()
        return row

    async def refresh(self, owner, identity, *, fresh=False):
        async with self.locks.setdefault("page:" + owner + ":" + str(identity), asyncio.Lock()):
            row = self.get(owner, identity)
            if not fresh and row.get("page_digest") and time.time() - row.get("page_checked_at", 0) < 20:
                return row
            try:
                page = await self.pages.read(row["page_id"])
            except ServiceCheckError as exc:
                if exc.code == "INTAKE_PAGE_NOT_CURRENT":
                    def unavailable(current):
                        if current["page_id"] == row["page_id"]:
                            current.update(state="SOURCE_UNAVAILABLE", approval=None, page_checked_at=0)
                    self.change(owner, identity, unavailable)
                raise

            def apply(current):
                if current["page_id"] != row["page_id"]:
                    raise ServiceCheckError("INTAKE_DOCUMENT_CHANGED", 409)
                changed = current.get("page_digest") and current["page_digest"] != page["digest"]
                current.update(
                    page_body=page["body"],
                    page_version=page["version"],
                    page_digest=page["digest"],
                    page_checked_at=time.time(),
                    page_checked_at_iso=now(),
                )
                if changed:
                    current.update(state="CHANGED", approval=None)
                elif current.get("state") == "SOURCE_UNAVAILABLE":
                    current.update(state="NEEDS_REVIEW" if current.get("project_id") else "NEEDS_PROJECT", approval=None)
                from langflow.adlc.document_revision import finish_revision

                finish_revision(current)

            return self.change(owner, identity, apply)

    def contract_digest(self, row):
        return hashlib.sha256(
            json.dumps(
                [
                    row.get("document_id"),
                    row.get("project_id"),
                    row.get("repository"),
                    row.get("page_digest"),
                    row.get("instructions", ""),
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()

    async def validate_source(self, owner, identity):
        row = self.get(owner, identity)
        if not row.get("lifecycle_id"):
            raise ServiceCheckError("INTAKE_SOURCE_INVALID", 409)
        raw = await self.client.request("GET", "/lifecycle/lifecycles/" + quote(row["lifecycle_id"], safe=""))
        source = next(
            (
                source_document(s)
                for s in raw.get("spec_docs", [])
                if isinstance(s, dict) and str(s.get("id")) == str(identity)
            ),
            None,
        )
        if source is None:
            raise ServiceCheckError("INTAKE_SOURCE_MISSING", 409)

        def apply(current):
            if any(
                source.get(k) != current.get(k) for k in ("lifecycle_id", "page_id", "slack_channel", "slack_thread")
            ):
                current.update(state="CHANGED", approval=None, page_checked_at=0)
                current.setdefault("notifications", {}).update(enabled=False, state="TARGET_CHANGED")
                return
            current.update(source_status=source["source_status"])
            if source["source_status"] in {"rejected", "cancelled"}:
                current.update(state="REJECTED", approval=None)

        result = self.change(owner, identity, apply)
        if any(source.get(k) != result.get(k) for k in ("lifecycle_id", "page_id", "slack_channel", "slack_thread")):
            raise ServiceCheckError("INTAKE_DOCUMENT_CHANGED", 409)
        return result

    async def decide(self, owner, identity, expected, decision):
        await self.refresh(owner, identity, fresh=True)

        def apply(row):
            from langflow.adlc.document_revision import PENDING

            if row.get("revision_request", {}).get("state") in PENDING:
                raise ServiceCheckError("INTAKE_REVISION_PENDING", 409)
            if not row.get("project_id") or self.contract_digest(row) != expected:
                raise ServiceCheckError("INTAKE_DOCUMENT_CHANGED", 409)
            if row.get("command", {}).get("digest") == expected:
                raise ServiceCheckError("INTAKE_EXECUTION_APPROVAL_FIXED", 409)
            if row.get("source_status") in {"cancelled", "rejected"} and decision == "approve":
                raise ServiceCheckError("INTAKE_SOURCE_REJECTED", 409)
            row.update(
                state="APPROVED" if decision == "approve" else "REJECTED",
                approval={
                    "actor": owner,
                    "at": now(),
                    "digest": expected,
                    "page_version": row["page_version"],
                    "decision": decision,
                    "scope": "vaiplatform_project",
                },
            )

        return self.change(owner, identity, apply)

    async def reserve(
        self, owner, identity, expected, command_id, workflow_id, workflow_digest=None, *, allow_revision=False
    ):
        await self.refresh(owner, identity, fresh=True)

        def apply(row):
            if (
                row.get("source_status") in {"cancelled", "rejected"}
                or row.get("state") != "APPROVED"
                or not row.get("approval")
                or row["approval"]["digest"] != expected
                or self.contract_digest(row) != expected
            ):
                raise ServiceCheckError("INTAKE_APPROVAL_REQUIRED", 409)
            intake_requirement(row)
            old = row.get("command") or {}
            if old.get("id") == command_id:
                if any(
                    old.get(k) != v
                    for k, v in {
                        "workflow_id": workflow_id,
                        "workflow_digest": workflow_digest,
                        "digest": expected,
                    }.items()
                ):
                    raise ServiceCheckError("INTAKE_COMMAND_CONFLICT", 409)
                return
            if row.get("run_id"):
                if not allow_revision or old.get("digest") == expected:
                    raise ServiceCheckError("INTAKE_RUN_ALREADY_EXISTS", 409)
                row["previous_runs"] = (
                    row.get("previous_runs", [])
                    + [
                        {
                            "run_id": row["run_id"],
                            "digest": old.get("digest"),
                            "page_version": row.get("execution_snapshot", {}).get("page_version"),
                        }
                    ]
                )[-100:]
            namespace = f"intake:{owner}:{identity}:"
            row.update(
                run_id=str(uuid5(UUID(command_id), namespace + "run")),
                flow_id=str(uuid5(UUID(command_id), namespace + "flow")),
                run_started_at=None,
                command={
                    "id": command_id,
                    "workflow_id": workflow_id,
                    "workflow_digest": workflow_digest,
                    "digest": expected,
                    "state": "STARTING",
                    "at": now(),
                },
            )
            row["execution_snapshot"] = {
                k: row.get(k)
                for k in (
                    "document_id",
                    "title",
                    "project_id",
                    "repository",
                    "page_id",
                    "page_body",
                    "page_version",
                    "confluence_url",
                    "lifecycle_id",
                    "slack_channel",
                    "slack_thread",
                    "instructions",
                    "approval",
                )
            }

        return self.change(owner, identity, apply)

    def command_result(self, owner, identity, command_id, **result):
        def apply(row):
            if row.get("command", {}).get("id") != command_id:
                raise ServiceCheckError("INTAKE_COMMAND_CONFLICT", 409)
            row["command"].update(result)
            if result.get("state") == "PLANNING":
                row["run_started_at"] = now()

        return self.change(owner, identity, apply)

    def follow_retry(self, owner, identity, parent, child):
        def apply(row):
            if row.get("run_id") != parent:
                return
            row["previous_runs"] = (
                row.get("previous_runs", [])
                + [{"run_id": parent, "page_version": row.get("execution_snapshot", {}).get("page_version")}]
            )[-100:]
            row.update(run_id=child, run_started_at=now())

        return self.change(owner, identity, apply)


async def start_document_plan(live, intake, row, session, actor):
    """Create the normal owned flow/delivery/run. Retries reuse the same IDs."""
    from langflow.adlc.delivery import CreateDelivery
    from langflow.api.v1 import adlc_delivery, adlc_live
    from langflow.api.v1.authz_route_dependencies import require_flow_create_permission
    from langflow.api.v1.flows_helpers import _new_flow
    from langflow.services.database.models.flow.model import Flow, FlowCreate
    from langflow.services.deps import get_storage_service

    owner, run_id = str(actor.id), row["run_id"]
    snapshot = row["execution_snapshot"]
    row = {**snapshot, "owner": owner, "run_id": run_id, "flow_id": row["flow_id"], "command": row["command"]}
    title = row["title"][:120]
    requirement = intake_requirement(row)
    origin = {
        "document_id": row["document_id"],
        "title": row["title"],
        "confluence_url": row["confluence_url"],
        "page_version": row["page_version"],
        "digest": row["approval"]["digest"],
        "lifecycle_id": row["lifecycle_id"],
        "slack_url": public_document(row).get("slack_url"),
        "approved_at": row["approval"]["at"],
    }
    try:
        existing = live.store.get(owner, run_id)
    except ServiceCheckError as exc:
        if exc.status != 404:
            raise
    else:
        if existing["project_id"] != row["project_id"] or existing["requirement"] != requirement:
            raise ServiceCheckError("INTAKE_COMMAND_CONFLICT", 409)
        intake.command_result(owner, row["document_id"], row["command"]["id"], state="PLANNING", error_code=None)
        return live.store.update(run_id, {"origin_document": origin})
    flow_id = UUID(row["flow_id"])
    flow = await session.get(Flow, flow_id)
    if flow is None:
        definition = FlowCreate(
            name=title + " · " + str(flow_id)[:8],
            description=requirement,
            folder_id=UUID(row["project_id"]),
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
        definition.workspace_id, definition.folder_id = await require_flow_create_permission(actor, definition, session)
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
    if flow is None or flow.user_id != actor.id or str(flow.folder_id) != row["project_id"]:
        raise ServiceCheckError("INTAKE_FLOW_BINDING_CHANGED", 409)
    delivery = await adlc_delivery.create_delivery(
        CreateDelivery(flow_id=flow_id, title=title, requirement=requirement), session, actor
    )
    workflow_id = row["command"].get("workflow_id")
    workflow = live.store.workflow(owner, workflow_id) if workflow_id else None
    if workflow and workflow["project_id"] != row["project_id"]:
        raise ServiceCheckError("LIVE_WORKFLOW_PROJECT_MISMATCH", 409)
    await adlc_live.plan(
        adlc_live.PlanCommand(
            run_id=UUID(run_id),
            project_id=UUID(row["project_id"]),
            delivery_id=UUID(delivery["id"]),
            workflow_id=UUID(workflow_id) if workflow else None,
            workflow_digest=row["command"].get("workflow_digest") if workflow else None,
        ),
        session,
        actor,
    )
    result = live.store.update(run_id, {"origin_document": origin})
    intake.command_result(owner, row["document_id"], row["command"]["id"], state="PLANNING", error_code=None)
    return result


@lru_cache(maxsize=1)
def document_intake():
    return DocumentIntake()

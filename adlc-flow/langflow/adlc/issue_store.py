"""Project policies and durable Gitea issue proposals, independent of agent execution."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
import time
from uuid import UUID, uuid5

from langflow.adlc.vai_services import ServiceCheckError, now
from langflow.adlc.issue_policy import (
    AUTOMATIC_MODES,
    POLICY_DEFAULTS,
    QUESTIONS,
    assess_issue,
    fingerprint,
    normalize_allowed_paths,
)


def issue_digest(issue):
    return hashlib.sha256(json.dumps([issue["title"], issue["body"]], ensure_ascii=False).encode()).hexdigest()


def issue_snapshot(project, issue):
    if issue.get("pull_request") or not isinstance(issue.get("number"), int) or issue["number"] < 1:
        return None
    return {
        "number": issue["number"],
        "title": str(issue.get("title") or "")[:1000],
        "body": str(issue.get("body") or ""),
        "state": issue.get("state", "open"),
        "url": project["repository_url"].rstrip("/") + "/issues/" + str(issue["number"]),
        "author": str((issue.get("user") or {}).get("login") or ""),
        "labels": [str(x.get("name", "")) for x in issue.get("labels", []) if isinstance(x, dict)],
        "updated_at": issue.get("updated_at"),
    }


def eligible(issue, policy):
    wanted = {x.casefold() for x in policy["labels"]}
    return issue["state"] == "open" and wanted <= {x.casefold() for x in issue["labels"]}


def issue_requirement(project, snapshot, clarification=None, policy=None):
    title = f"Gitea #{snapshot['number']}: {snapshot['title']}"[:190]
    text = (
        f"Thực hiện yêu cầu trong issue Gitea #{snapshot['number']} của {project['repository']}.\n"
        f"Nguồn: {snapshot['url']}\n\n# Tiêu đề\n{snapshot['title']}\n\n# Nội dung issue\n{snapshot['body']}\n\n"
        "Đây là yêu cầu nghiệp vụ từ issue. Giữ nguyên các bước duyệt, phạm vi nguồn, kiểm thử độc lập và quyền công cụ của project. "
        "Nếu thiếu thông tin, hỏi người dùng bằng ask_user_question."
    )
    if clarification:
        text += "\n\n# Thông tin người dùng đã chốt cho bản issue này\n"
        text += "\n".join(f"{q['question']}\n{clarification['answers'][q['id']]}" for q in QUESTIONS)
        if clarification.get("approach") == "spec_first":
            text += "\nLập đặc tả rõ ràng trước, dùng đặc tả đó để phân rã công việc và tiêu chí kiểm thử."
    if policy:
        text += f"\n\n# Giới hạn đã giao cho lượt tự động\nTổng ngân sách làm việc: {policy['auto_max_active_minutes']} phút."
        if policy["mode"] == "risk":
            text += "\nPhạm vi được tự duyệt: " + ", ".join(policy["auto_allowed_paths"]) + "."
            text += "\nNếu yêu cầu thực sự cần file ngoài phạm vi hoặc lệnh khác, ghi đúng nhu cầu trong kế hoạch để người dùng duyệt. Không bỏ kiểm thử hoặc đổi mục tiêu chỉ để lọt chính sách."
    if not snapshot["title"].strip() or len(text) > 20000:
        raise ServiceCheckError("ISSUE_REQUIRES_MANUAL_SUMMARY", 422)
    return title, text


class IssueStore:
    def __init__(self, live):
        self.live = live
        self.path = live.path
        with self.db() as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS project_issue_settings(project TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS issue_proposals(id TEXT PRIMARY KEY,owner TEXT NOT NULL,project TEXT NOT NULL,number INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(owner,project,number))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS issue_proposals_owner_project ON issue_proposals(owner,project)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS issue_audit(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,project TEXT NOT NULL,proposal TEXT,event TEXT NOT NULL,at TEXT NOT NULL,details TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS issue_audit_scope ON issue_audit(owner,project,proposal,id)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS issue_auto_attempts(run TEXT PRIMARY KEY,owner TEXT NOT NULL,project TEXT NOT NULL,proposal TEXT NOT NULL,started REAL NOT NULL,policy_revision INTEGER NOT NULL,executed REAL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS issue_auto_attempts_scope ON issue_auto_attempts(owner,project,started)"
            )

    def db(self):
        return closing(sqlite3.connect(self.path, timeout=15))

    def settings(self, owner, project):
        self.live.project(owner, project)
        default = {
            "project_id": project,
            "watch_issues": True,
            "mode": "review",
            "labels": [],
            "workflow_id": None,
            "revision": 1,
            "updated_at": now(),
            "updated_by": None,
            "last_scan_at": None,
            "scan_error": None,
            "scan_truncated": False,
            "poll_seconds": 60,
            **POLICY_DEFAULTS,
        }
        with self.db() as db, db:
            db.execute(
                "INSERT OR IGNORE INTO project_issue_settings VALUES(?,?,?)", (project, owner, json.dumps(default))
            )
            row = db.execute(
                "SELECT payload FROM project_issue_settings WHERE project=? AND owner=?", (project, owner)
            ).fetchone()
        if row is None:
            raise ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404)
        policy = json.loads(row[0])
        if any(key not in policy for key in POLICY_DEFAULTS):
            with self.db() as db, db:
                db.execute("BEGIN IMMEDIATE")
                policy = json.loads(
                    db.execute(
                        "SELECT payload FROM project_issue_settings WHERE project=? AND owner=?", (project, owner)
                    ).fetchone()[0]
                )
                if any(key not in policy for key in POLICY_DEFAULTS):
                    policy = {**POLICY_DEFAULTS, **policy, "revision": policy["revision"] + 1, "updated_at": now()}
                    db.execute(
                        "UPDATE project_issue_settings SET payload=? WHERE project=? AND owner=?",
                        (json.dumps(policy), project, owner),
                    )
                    self._audit(db, owner, project, None, "policy_upgraded", {"revision": policy["revision"]})
        return policy

    def save_settings(
        self,
        owner,
        project,
        *,
        expected_revision,
        watch_issues,
        mode,
        labels,
        workflow_id,
        auto_confirmed=False,
        auto_allowed_paths=None,
        auto_max_runs_per_day=3,
        auto_max_active_minutes=20,
    ):
        self.settings(owner, project)
        if (
            mode not in {"review", *AUTOMATIC_MODES}
            or len(labels) > 20
            or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in labels)
        ):
            raise ServiceCheckError("ISSUE_SETTINGS_INVALID", 422)
        try:
            scopes = normalize_allowed_paths(
                POLICY_DEFAULTS["auto_allowed_paths"] if auto_allowed_paths is None else auto_allowed_paths
            )
        except ValueError as exc:
            raise ServiceCheckError(str(exc), 422) from None
        if (
            type(auto_max_runs_per_day) is not int
            or not 1 <= auto_max_runs_per_day <= 50
            or type(auto_max_active_minutes) is not int
            or not 5 <= auto_max_active_minutes <= 60
        ):
            raise ServiceCheckError("ISSUE_AUTO_LIMITS_INVALID", 422)
        if watch_issues and mode == "risk" and not scopes:
            raise ServiceCheckError("ISSUE_ALLOWED_PATHS_REQUIRED", 422)
        if watch_issues and mode in AUTOMATIC_MODES and not auto_confirmed:
            raise ServiceCheckError("ISSUE_AUTO_CONFIRMATION_REQUIRED", 422)
        labels = sorted(set(x.strip() for x in labels), key=str.casefold)
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?", (owner, project)
            ).fetchone()
            policy = json.loads(row[0])
            if policy["revision"] != expected_revision:
                raise ServiceCheckError("ISSUE_SETTINGS_CHANGED")
            policy.update(
                watch_issues=watch_issues,
                mode=mode,
                labels=labels,
                workflow_id=workflow_id,
                revision=policy["revision"] + 1,
                updated_at=now(),
                updated_by=owner,
                auto_allowed_paths=scopes,
                auto_max_runs_per_day=auto_max_runs_per_day,
                auto_max_active_minutes=auto_max_active_minutes,
            )
            db.execute(
                "UPDATE project_issue_settings SET payload=? WHERE owner=? AND project=?",
                (json.dumps(policy), owner, project),
            )
            self._audit(
                db,
                owner,
                project,
                None,
                "policy_saved",
                {
                    "actor": owner,
                    "revision": policy["revision"],
                    "mode": mode,
                    "watch_issues": watch_issues,
                    "allowed_paths": scopes,
                    "max_runs_per_day": auto_max_runs_per_day,
                    "max_active_minutes": auto_max_active_minutes,
                },
            )
        return policy

    @staticmethod
    def _audit(db, owner, project, proposal, event, details):
        db.execute(
            "INSERT INTO issue_audit(owner,project,proposal,event,at,details) VALUES(?,?,?,?,?,?)",
            (owner, project, proposal, event, now(), json.dumps(details, ensure_ascii=False)),
        )

    def audit(self, owner, project, proposal):
        self.get(owner, project, proposal)
        with self.db() as db:
            rows = db.execute(
                "SELECT id,event,at,details FROM issue_audit WHERE owner=? AND project=? AND (proposal=? OR proposal IS NULL) ORDER BY id DESC LIMIT 50",
                (owner, project, proposal),
            ).fetchall()
        return [{"id": r[0], "event": r[1], "at": r[2], "details": json.loads(r[3])} for r in rows]

    def record_event(self, owner, project, proposal, event, details):
        self.get(owner, project, proposal)
        with self.db() as db, db:
            self._audit(db, owner, project, proposal, event, details)

    def usage(self, owner, project):
        policy = self.settings(owner, project)
        with self.db() as db:
            count, first = db.execute(
                "SELECT COUNT(*),MIN(started) FROM issue_auto_attempts WHERE owner=? AND project=? AND started>?",
                (owner, project, time.time() - 86400),
            ).fetchone()
        return {
            "used": count,
            "limit": policy["auto_max_runs_per_day"],
            "window_hours": 24,
            "next_available_at": first + 86400 if first and count >= policy["auto_max_runs_per_day"] else None,
        }

    def _assess(self, db, row, policy, plan=None):
        value = assess_issue(row["issue"], row.get("clarification"), policy, plan)
        key = fingerprint(value)
        if row.get("assessment_digest") != key:
            self._audit(db, row["owner"], row["project_id"], row["proposal_id"], "assessed", value)
        row.update(value, assessment_digest=key)
        if not row.get("run_id") and row["state"] in {"DETECTED", "NEEDS_CONTEXT", "NEEDS_SPEC", "ERROR"}:
            action = value["triage"]["action"]
            if action != "ready":
                row["state"] = "NEEDS_SPEC" if action == "needs_spec" else "NEEDS_CONTEXT"
            elif row["state"] in {"NEEDS_CONTEXT", "NEEDS_SPEC"}:
                row["state"] = "DETECTED"
        return row

    def assess(self, owner, project, identity, plan=None):
        self.settings(owner, project)
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
            if saved is None:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            policy = json.loads(
                db.execute(
                    "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?", (owner, project)
                ).fetchone()[0]
            )
            row = self._assess(db, json.loads(saved[0]), policy, plan)
            db.execute(
                "UPDATE issue_proposals SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity)
            )
        return row

    def clarify(self, owner, project, identity, expected_digest, answers, approach):
        if (
            set(answers) != {q["id"] for q in QUESTIONS}
            or any(not isinstance(v, str) or not 8 <= len(v.strip()) <= 4000 for v in answers.values())
            or approach not in {"implement", "spec_first"}
        ):
            raise ServiceCheckError("ISSUE_CLARIFICATION_INVALID", 422)
        self.settings(owner, project)
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
            if saved is None:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            row = json.loads(saved[0])
            if row["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            if row.get("run_id") or row["state"] in {"CLOSED", "FILTERED", "IGNORED"}:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_READY")
            clarification = {
                "source_digest": expected_digest,
                "answers": {k: v.strip() for k, v in answers.items()},
                "approach": approach,
                "by": owner,
                "at": now(),
            }
            row.update(clarification=clarification, state="DETECTED", review_reason=None, error_code=None)
            policy = json.loads(
                db.execute(
                    "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?", (owner, project)
                ).fetchone()[0]
            )
            row = self._assess(db, row, policy)
            self._audit(db, owner, project, identity, "clarified", clarification)
            db.execute(
                "UPDATE issue_proposals SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity)
            )
        return row

    def scan_status(self, owner, project, *, error=None, truncated=False):
        self.settings(owner, project)
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = json.loads(
                db.execute(
                    "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?", (owner, project)
                ).fetchone()[0]
            )
            row.update(last_scan_at=now(), scan_error=error, scan_truncated=truncated)
            db.execute(
                "UPDATE project_issue_settings SET payload=? WHERE owner=? AND project=?",
                (json.dumps(row), owner, project),
            )

    def proposals(self, owner, project=None):
        with self.db() as db:
            rows = db.execute(
                "SELECT payload FROM issue_proposals WHERE owner=?"
                + (" AND project=?" if project else "")
                + " ORDER BY number DESC",
                (owner, project) if project else (owner,),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get(self, owner, project, identity):
        with self.db() as db:
            row = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
        if row is None:
            raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
        return json.loads(row[0])

    def ingest(self, owner, project, issue, policy):
        snapshot = issue_snapshot(project, issue)
        if snapshot is None:
            return None
        identity = str(uuid5(UUID(project["project_id"]), "gitea-issue:" + str(snapshot["number"])))
        content = issue_digest(snapshot)
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute("SELECT payload FROM issue_proposals WHERE id=?", (identity,)).fetchone()
            old = json.loads(saved[0]) if saved else None
            if old and old["owner"] != owner:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            changed = (
                old is None
                or old["source_digest"] != content
                or (old["issue"]["state"] == "closed" and snapshot["state"] == "open")
            )
            if changed:
                history = old.get("previous_runs", []) if old else []
                if old and old.get("run_id"):
                    history = [
                        *history,
                        {"run_id": old["run_id"], "source_digest": old["source_digest"], "revision": old["revision"]},
                    ]
                value = {
                    "proposal_id": identity,
                    "owner": owner,
                    "project_id": project["project_id"],
                    "repository": project["repository"],
                    "repository_id": project["repository_id"],
                    "issue": snapshot,
                    "source_digest": content,
                    "revision": (old["revision"] + 1) if old else 1,
                    "state": "DETECTED",
                    "created_at": old["created_at"] if old else now(),
                    "run_id": None,
                    "previous_runs": history[-50:],
                    "error_code": None,
                    "review_reason": None,
                    "lease_until": 0,
                    "lease_owner": None,
                }
            else:
                value = {**old, "issue": snapshot}
            if snapshot["state"] != "open":
                value["state"] = "CLOSED"
            elif not eligible(snapshot, policy) and not value.get("run_id"):
                value["state"] = "FILTERED"
            elif value["state"] in {"FILTERED", "CLOSED"} and not value.get("run_id"):
                value["state"] = "DETECTED"
            value["updated_at"] = now()
            if changed or not value.get("triage"):
                value = self._assess(db, value, policy)
            db.execute(
                "INSERT OR REPLACE INTO issue_proposals VALUES(?,?,?,?,?)",
                (identity, owner, project["project_id"], snapshot["number"], json.dumps(value, ensure_ascii=False)),
            )
        return value

    def mark_missing_closed(self, owner, project, seen):
        for row in self.proposals(owner, project):
            if row["issue"]["number"] not in seen and row["issue"]["state"] == "open":
                self.update(
                    owner, project, row["proposal_id"], issue={**row["issue"], "state": "closed"}, state="CLOSED"
                )

    def update(self, owner, project, identity, *, expected_digest=None, **changes):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
            if saved is None:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            row = json.loads(saved[0])
            if expected_digest is not None and row["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            row.update(**changes, updated_at=now())
            db.execute(
                "UPDATE issue_proposals SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity)
            )
        return row

    def claim(self, owner, project, identity, expected_digest, instance, policy, *, automatic=False):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
            if saved is None:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            row = json.loads(saved[0])
            if row["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            if row.get("run_id"):
                return row, False
            if row["state"] not in {"DETECTED", "ERROR"} or row.get("lease_until", 0) > time.time():
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_READY")
            identity_run = str(uuid5(UUID(identity), str(row["revision"]) + ":" + row["source_digest"]))
            current_policy = json.loads(
                db.execute(
                    "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?", (owner, project)
                ).fetchone()[0]
            )
            row = self._assess(db, row, current_policy)
            if row["triage"]["action"] != "ready":
                raise ServiceCheckError(row["auto_decision"]["code"])
            if automatic:
                if (
                    current_policy["revision"] != policy["revision"]
                    or not current_policy["watch_issues"]
                    or current_policy["mode"] not in AUTOMATIC_MODES
                ):
                    raise ServiceCheckError("ISSUE_AUTO_POLICY_CHANGED")
                if not row["auto_decision"]["allowed"]:
                    raise ServiceCheckError(row["auto_decision"]["code"])
                previous = db.execute("SELECT run FROM issue_auto_attempts WHERE run=?", (identity_run,)).fetchone()
                if previous is None:
                    used = db.execute(
                        "SELECT COUNT(*) FROM issue_auto_attempts WHERE owner=? AND project=? AND started>?",
                        (owner, project, time.time() - 86400),
                    ).fetchone()[0]
                    if used >= policy["auto_max_runs_per_day"]:
                        raise ServiceCheckError("ISSUE_AUTO_BUDGET_EXHAUSTED")
                    db.execute(
                        "INSERT INTO issue_auto_attempts VALUES(?,?,?,?,?,?,NULL)",
                        (identity_run, owner, project, identity, time.time(), policy["revision"]),
                    )
                    self._audit(
                        db,
                        owner,
                        project,
                        identity,
                        "auto_reserved",
                        {
                            "run_id": identity_run,
                            "policy_revision": policy["revision"],
                            "max_active_minutes": policy["auto_max_active_minutes"],
                        },
                    )
            row.update(
                state="STARTING",
                run_id=identity_run,
                policy_revision=policy["revision"],
                automatic=automatic,
                triage_digest=row["triage"]["input_digest"],
                lease_owner=instance,
                lease_until=time.time() + 300,
                error_code=None,
                review_reason=None,
            )
            db.execute(
                "UPDATE issue_proposals SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity)
            )
        return row, True

    def ignore(self, owner, project, identity, expected_digest, restore=False):
        with self.db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            saved = db.execute(
                "SELECT payload FROM issue_proposals WHERE id=? AND owner=? AND project=?", (identity, owner, project)
            ).fetchone()
            if saved is None:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_FOUND", 404)
            row = json.loads(saved[0])
            if row["source_digest"] != expected_digest:
                raise ServiceCheckError("ISSUE_CHANGED")
            if row.get("run_id") or row["state"] not in {"DETECTED", "NEEDS_CONTEXT", "NEEDS_SPEC", "IGNORED", "ERROR"}:
                raise ServiceCheckError("ISSUE_PROPOSAL_NOT_READY")
            row.update(state="DETECTED" if restore else "IGNORED", error_code=None, updated_at=now())
            self._audit(db, owner, project, identity, "restored" if restore else "ignored", {"actor": owner})
            db.execute(
                "UPDATE issue_proposals SET payload=? WHERE id=?", (json.dumps(row, ensure_ascii=False), identity)
            )
        return row

    def guard_auto_execution(self, db, proposal, run):
        """Runs inside the same transaction that approves the exact plan digest."""
        policy = json.loads(
            db.execute(
                "SELECT payload FROM project_issue_settings WHERE owner=? AND project=?",
                (proposal["owner"], proposal["project_id"]),
            ).fetchone()[0]
        )
        current = json.loads(
            db.execute("SELECT payload FROM issue_proposals WHERE id=?", (proposal["proposal_id"],)).fetchone()[0]
        )
        if (
            not policy["watch_issues"]
            or policy["mode"] not in AUTOMATIC_MODES
            or policy["revision"] != proposal["policy_revision"]
        ):
            raise ServiceCheckError("ISSUE_AUTO_POLICY_CHANGED")
        if (
            current["run_id"] != run["run_id"]
            or current["source_digest"] != proposal["source_digest"]
            or not eligible(current["issue"], policy)
        ):
            raise ServiceCheckError("ISSUE_CHANGED")
        assessment = assess_issue(current["issue"], current.get("clarification"), policy, run["plan"])
        if not current.get("automatic") or current.get("triage_digest") != assessment["triage"]["input_digest"]:
            raise ServiceCheckError("ISSUE_TRIAGE_CHANGED")
        if not assessment["auto_decision"]["allowed"]:
            raise ServiceCheckError(assessment["auto_decision"]["code"])
        others = db.execute(
            "SELECT payload FROM runs WHERE owner=? AND project=? AND id<>?",
            (proposal["owner"], proposal["project_id"], run["run_id"]),
        ).fetchall()
        if any(json.loads(other[0])["state"] in {"PLANNING", "RUNNING", "UNCONFIRMED"} for other in others):
            raise ServiceCheckError("LIVE_PROJECT_RUN_ACTIVE")
        reserved = db.execute(
            "SELECT policy_revision FROM issue_auto_attempts WHERE run=? AND owner=? AND project=?",
            (run["run_id"], proposal["owner"], proposal["project_id"]),
        ).fetchone()
        if not reserved or reserved[0] != policy["revision"]:
            raise ServiceCheckError("ISSUE_AUTO_RESERVATION_MISSING")
        if run.get("auto_timing", {}).get("active_seconds", 0) >= policy["auto_max_active_minutes"] * 60:
            raise ServiceCheckError("ISSUE_AUTO_TIME_LIMIT_EXHAUSTED")
        run.update(
            approval_source="project_issue_policy",
            automation={
                "project_id": proposal["project_id"],
                "settings_revision": policy["revision"],
                "issue_digest": current["source_digest"],
                "triage_digest": assessment["triage"]["input_digest"],
                "risk": assessment["risk"],
                "decision": assessment["auto_decision"],
                "approved_at": now(),
                "approved_by": proposal["owner"],
            },
        )
        run["auto_timing"] = {**run.get("auto_timing", {}), "limit_seconds": policy["auto_max_active_minutes"] * 60}
        db.execute("UPDATE issue_auto_attempts SET executed=? WHERE run=?", (time.time(), run["run_id"]))
        self._audit(
            db,
            proposal["owner"],
            proposal["project_id"],
            proposal["proposal_id"],
            "auto_approved",
            {"actor": proposal["owner"], "run_id": run["run_id"], **assessment},
        )


def public_proposal(row):
    return {k: v for k, v in row.items() if k not in {"owner", "lease_owner", "lease_until"}}

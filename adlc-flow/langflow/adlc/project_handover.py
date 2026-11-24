"""Human-requested Gitea PR handover, with exact commit and branch checks."""
from __future__ import annotations

import asyncio
from fnmatch import fnmatchcase
import json
from urllib.parse import quote

from langflow.adlc.gitea_projects import Gitea
from langflow.adlc.vai_services import ServiceCheckError, now


def pull_public(pull):
    return {"number": pull["number"], "url": pull["html_url"], "title": pull["title"], "state": pull["state"],
            "merged": pull.get("merged", False), "merge_commit": pull.get("merge_commit_sha"),
            "head": pull["head"]["sha"], "base": pull["base"]["ref"], "base_commit": pull["base"]["sha"],
            "mergeable": pull.get("mergeable"), "draft": pull.get("draft", False)}


def merge_readiness(row, pull, branch, statuses, reviews):
    """The server enforces its protections again; the admin token never requests an override."""
    reasons, latest = [], {}
    published = row.get("published") or {}
    if pull["head"]["sha"] != published.get("commit") or pull["head"].get("ref") != published.get("branch"):
        reasons.append("LIVE_PR_HEAD_CHANGED")
    if pull["base"].get("ref") != row.get("handover", {}).get("base_branch", pull["base"].get("ref")):
        reasons.append("LIVE_PR_BASE_CHANGED")
    if branch.get("commit", {}).get("id") != row["base_commit"] or pull["base"]["sha"] != row["base_commit"]:
        reasons.append("LIVE_PR_BASE_CHANGED")
    if pull.get("merged"):
        return {"can_merge": False, "reasons": [], "ci": [], "approvals": 0, "required_approvals": 0, "no_ci": False}
    if pull["state"] != "open" or pull.get("draft") or pull.get("mergeable") is not True:
        reasons.append("LIVE_PR_NOT_MERGEABLE")
    if branch.get("user_can_merge") is False:
        reasons.append("LIVE_PR_MERGE_DENIED")
    # Status endpoints can include history. Only the latest status of each context counts.
    for item in statuses:
        context = item.get("context", "")
        key = (item.get("updated_at") or item.get("created_at") or "", item.get("id", 0))
        previous = latest.get(context)
        if previous is None or key > previous[0]:
            latest[context] = (key, item)
    ci = [{"context": context, "state": item.get("status", "pending"), "url": item.get("target_url"), "description": item.get("description", "")} for context, (_, item) in sorted(latest.items())]
    if any(item["state"] != "success" for item in ci):
        reasons.append("LIVE_PR_CHECKS_NOT_PASSED")
    patterns = branch.get("status_check_contexts") or []
    if branch.get("enable_status_check") and (not patterns or any(not any(fnmatchcase(item["context"], pattern) and item["state"] == "success" for item in ci) for pattern in patterns)):
        reasons.append("LIVE_PR_REQUIRED_CHECK_MISSING")
    final_reviews = {}
    for review in reviews:
        if review.get("dismissed") or review.get("stale") or review.get("state") not in {"APPROVED", "REQUEST_CHANGES"}:
            continue
        user = review.get("user", {}).get("id")
        key = (review.get("submitted_at") or "", review.get("id", 0))
        if user not in final_reviews or key > final_reviews[user][0]:
            final_reviews[user] = (key, review)
    approvals = sum(review.get("state") == "APPROVED" and review.get("official", True) and review.get("commit_id") == published.get("commit") and user != pull.get("user", {}).get("id") for user, (_, review) in final_reviews.items())
    required = branch.get("required_approvals", 0)
    if type(required) is not int or approvals < required:
        reasons.append("LIVE_PR_REVIEW_REQUIRED")
    if any(review["state"] == "REQUEST_CHANGES" for _, review in final_reviews.values()) or pull.get("requested_reviewers") or pull.get("requested_reviewers_teams"):
        reasons.append("LIVE_PR_REVIEW_REQUIRED")
    return {"can_merge": not reasons, "reasons": sorted(set(reasons)), "ci": ci, "approvals": approvals,
            "required_approvals": required, "no_ci": not ci, "checked_at": now()}


class ProjectHandover:
    def __init__(self, live, gitea=None):
        self.live, self.gitea = live, gitea or Gitea()
        self.locks = {}

    def lock(self, identity):
        return self.locks.setdefault(identity, asyncio.Lock())

    def project(self, row):
        return self.live.store.project(row["owner"], row["project_id"])

    def path(self, row):
        return "/repos/" + self.project(row)["repository"]

    def save(self, row, value):
        return self.live.store.update(row["run_id"], {"handover": {**value, "updated_at": now()}})["handover"]

    async def all_pages(self, path):
        items = []
        separator = "&" if "?" in path else "?"
        for page in range(1, 21):
            reply = await self.gitea.request("GET", path + separator + f"limit=50&page={page}")
            values = reply.get("statuses", []) if isinstance(reply, dict) else reply
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise ServiceCheckError("LIVE_PR_STATUS_UNCONFIRMED")
            items.extend(values)
            if len(values) < 50:
                return items
        raise ServiceCheckError("LIVE_PR_STATUS_UNCONFIRMED")

    async def bound_pull(self, row):
        handover = row.get("handover") or {}
        number = handover.get("pull", {}).get("number")
        if not number:
            return None
        pull = await self.gitea.request("GET", self.path(row) + "/pulls/" + str(int(number)))
        published = row.get("published") or {}
        if pull["head"].get("sha") != published.get("commit") or pull["head"].get("ref") != published.get("branch") or pull["base"].get("ref") != handover["base_branch"]:
            raise ServiceCheckError("LIVE_PR_HEAD_CHANGED")
        return pull

    def description(self, row):
        checks = [test for group in row.get("checks", []) for test in group.get("tests", [])]
        issue = row.get("issue") or {}
        lines = [row["requirement"][:7000], "", "## Kết quả vAIPlatform", "", "- Run: `" + row["run_id"] + "`", "- Source baseline: `" + row["base_commit"] + "`", "- Kế hoạch: `" + row["approved_plan_digest"] + "`"]
        if issue.get("number"):
            lines.append("- Liên quan #" + str(int(issue["number"])))
        origin = row.get("origin_document") or {}
        if origin:
            lines.append("- Tài liệu đã duyệt: " + str(origin.get("confluence_url") or "") + " · phiên bản " + str(origin.get("page_version")))
            lines.append("- Duyệt cho project: `" + origin["digest"] + "` · " + origin["approved_at"])
            if origin.get("slack_url"):
                lines.append("- Trao đổi Slack: " + origin["slack_url"])
        if row.get("workflow"):
            lines.append("- Workflow: " + row["workflow"]["name"] + " · phiên bản " + str(row["workflow"]["revision"]))
        if row.get("environment"):
            lines.append("- Môi trường: `" + row["environment"]["digest"] + "`")
        lines.extend(["", "### File thay đổi", *["- `" + p + "`" for p in row.get("changed_files", [])], "", "### Kiểm chứng"])
        lines.extend("- " + str(test.get("label", test.get("id", "Kiểm tra")))[:300] + ": " + ("Đạt" if test.get("passed") is True else "Chưa xác nhận") for test in checks)
        lines.extend(["", "Kiểm chứng gắn với source và kế hoạch trên. Cần xem CI/review của PR trước khi merge.", "", "<!-- pokedev-run:" + row["run_id"] + " -->"])
        return "\n".join(lines)

    async def create(self, owner, identity, expected_head, command):
        async with self.lock(identity):
            row = self.live.observe(self.live.store.get(owner, identity))
            published = row.get("published") or {}
            if row["state"] != "SUCCEEDED" or published.get("commit") != expected_head:
                raise ServiceCheckError("LIVE_PR_VERIFIED_BRANCH_REQUIRED")
            if (row.get("handover") or {}).get("pull"):
                return await self.refresh(owner, identity, locked=True)
            project = self.project(row)
            head = await self.gitea.request("GET", self.path(row) + "/branches/" + quote(published["branch"], safe=""))
            if head.get("commit", {}).get("id") != expected_head:
                raise ServiceCheckError("LIVE_PR_HEAD_CHANGED")
            existing = await self.all_pages(self.path(row) + "/pulls?state=all")
            matches = [pull for pull in existing if pull.get("head", {}).get("ref") == published["branch"] and pull.get("base", {}).get("ref") == project["branch"]]
            handover = row.get("handover") or {"base_branch": project["branch"], "created_by": owner}
            if matches:
                pull = next((p for p in matches if p.get("state") == "open"), matches[0])
                if "<!-- pokedev-run:" + identity + " -->" not in (pull.get("body") or "") or pull["head"]["sha"] != expected_head:
                    raise ServiceCheckError("LIVE_PR_HEAD_CHANGED")
            else:
                if handover.get("create_intent"):
                    raise ServiceCheckError("LIVE_PR_CREATE_UNCONFIRMED")
                handover.update(state="CREATING", create_intent={"command_id": command, "head": expected_head, "at": now()})
                self.save(row, handover)
                try:
                    pull = await self.gitea.request("POST", self.path(row) + "/pulls", {"base": project["branch"], "head": published["branch"], "title": row["title"][:200], "body": self.description(row)})
                except ServiceCheckError as exc:
                    if exc.code in {"GITEA_CHANGE_REJECTED", "GITEA_ACCESS_DENIED", "GITEA_REPOSITORY_NOT_FOUND"}:
                        handover.pop("create_intent", None)
                        self.save(row, {**handover, "state": "NOT_CREATED"})
                        raise ServiceCheckError("LIVE_PR_CREATE_REJECTED") from None
                    self.save(row, {**handover, "state": "UNCONFIRMED"})
                    raise ServiceCheckError("LIVE_PR_CREATE_UNCONFIRMED") from None
            self.save(row, {**handover, "state": "MERGED" if pull.get("merged") else "OPEN", "pull": pull_public(pull)})
            return await self.refresh(owner, identity, locked=True)

    async def refresh(self, owner, identity, *, locked=False):
        if not locked:
            async with self.lock(identity):
                return await self.refresh(owner, identity, locked=True)
        row = self.live.store.get(owner, identity)
        handover = row.get("handover") or {}
        pull = await self.bound_pull(row)
        if pull is None and handover.get("create_intent"):
            published = row.get("published") or {}
            matches = [p for p in await self.all_pages(self.path(row) + "/pulls?state=all")
                       if p.get("head", {}).get("ref") == published.get("branch") and p.get("base", {}).get("ref") == handover["base_branch"] and "<!-- pokedev-run:" + identity + " -->" in (p.get("body") or "")]
            if matches:
                if len(matches) != 1 or matches[0]["head"]["sha"] != published["commit"]:
                    raise ServiceCheckError("LIVE_PR_HEAD_CHANGED")
                handover = self.save(row, {**handover, "pull": pull_public(matches[0])})
                row = self.live.store.get(owner, identity)
                pull = await self.bound_pull(row)
        if pull is None:
            return {"state": "NOT_CREATED", **handover}
        if pull.get("merged"):
            if (handover.get("merge_intent") or {}).get("close_issue") and not handover.get("issue_update") and row.get("issue"):
                handover["issue_update"] = {"state": "PENDING", "number": row["issue"]["number"]}
            return self.save(row, {**handover, "state": "MERGED", "pull": pull_public(pull), "readiness": {"can_merge": False, "reasons": [], "ci": [], "no_ci": False}})
        path = self.path(row)
        branch = await self.gitea.request("GET", path + "/branches/" + quote(handover["base_branch"], safe=""))
        statuses = await self.all_pages(path + "/commits/" + pull["head"]["sha"] + "/status")
        reviews = await self.all_pages(path + "/pulls/" + str(pull["number"]) + "/reviews")
        readiness = merge_readiness(row, pull, branch, statuses, reviews)
        return self.save(row, {**handover, "state": "CLOSED" if pull["state"] != "open" else "OPEN", "pull": pull_public(pull), "readiness": readiness})

    async def merge(self, owner, identity, command, expected_head, expected_base, *, accept_no_ci=False, close_issue=False):
        async with self.lock(identity):
            row = self.live.observe(self.live.store.get(owner, identity))
            if row["state"] != "SUCCEEDED":
                raise ServiceCheckError("LIVE_PR_VERIFIED_BRANCH_REQUIRED")
            value = await self.refresh(owner, identity, locked=True)
            if value["state"] == "MERGED":
                if close_issue:
                    return await self.close_issue(row, value)
                return value
            if value.get("merge_intent"):
                raise ServiceCheckError("LIVE_PR_MERGE_UNCONFIRMED")
            readiness = value.get("readiness") or {}
            if value.get("pull", {}).get("head") != expected_head or expected_head != row.get("published", {}).get("commit") or value["pull"]["base_commit"] != expected_base:
                raise ServiceCheckError("LIVE_PR_HEAD_CHANGED")
            if not readiness.get("can_merge"):
                raise ServiceCheckError((readiness.get("reasons") or ["LIVE_PR_STATUS_UNCONFIRMED"])[0])
            if readiness["no_ci"] and not accept_no_ci:
                raise ServiceCheckError("LIVE_PR_NO_CI_CONFIRMATION_REQUIRED")
            value.update(state="MERGING", merge_intent={"command_id": command, "head": expected_head, "base": expected_base, "actor": owner, "at": now(), "close_issue": close_issue})
            self.save(row, value)
            try:
                await self.gitea.request("POST", self.path(row) + "/pulls/" + str(value["pull"]["number"]) + "/merge", {"do": "merge", "head_commit_id": expected_head, "force_merge": False, "merge_when_checks_succeed": False, "delete_branch_after_merge": False})
            except ServiceCheckError as exc:
                if exc.code in {"GITEA_CHANGE_REJECTED", "GITEA_ACCESS_DENIED", "GITEA_REPOSITORY_NOT_FOUND"}:
                    value.pop("merge_intent", None)
                    self.save(row, {**value, "state": "OPEN"})
                    raise ServiceCheckError("LIVE_PR_MERGE_REJECTED") from None
                self.save(row, {**value, "state": "UNCONFIRMED"})
                raise ServiceCheckError("LIVE_PR_MERGE_UNCONFIRMED") from None
            value = await self.refresh(owner, identity, locked=True)
            if value["state"] != "MERGED":
                raise ServiceCheckError("LIVE_PR_MERGE_UNCONFIRMED")
            return await self.close_issue(row, value) if close_issue else value

    async def close_issue(self, row, value):
        issue = row.get("issue") or {}
        if not issue.get("number") or value["state"] != "MERGED":
            return value
        path = self.path(row) + "/issues/" + str(int(issue["number"]))
        try:
            remote = await self.gitea.request("GET", path)
            if remote.get("pull_request"):
                raise ServiceCheckError("LIVE_PR_ISSUE_UPDATE_FAILED")
            if remote.get("state") != "closed":
                await self.gitea.request("PATCH", path, {"state": "closed"})
            value.update(issue_update={"state": "CLOSED", "number": issue["number"], "at": now()})
        except ServiceCheckError:
            value.update(issue_update={"state": "UNCONFIRMED", "number": issue["number"], "at": now()})
        return self.save(row, value)

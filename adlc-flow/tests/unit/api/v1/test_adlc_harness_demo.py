"""Signed demo ingress, explicit human gates and repository boundaries; no external writes."""
# ruff: noqa: S101, PLR2004

import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from langflow.api.v1.adlc_harness_demo import approve, restart, tools, webhook
from tests.unit.adlc.test_harness_demo import REQUIREMENT, service


def request(value, **headers):
    raw = json.dumps(value).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        },
        receive,
    )


async def test_approval_binds_exact_digest_and_owner(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("a", REQUIREMENT)
    await demo.plan(run["id"])
    with pytest.raises(HTTPException) as bad:
        await approve(
            run["id"], "approve-plan", request({"digest": "sha256:" + "0" * 64}), SimpleNamespace(id="a"), demo
        )
    assert bad.value.status_code == 409
    with pytest.raises(HTTPException) as other:
        await approve(
            run["id"],
            "approve-plan",
            request({"digest": demo.ledger.get(run["id"])["plan_digest"]}),
            SimpleNamespace(id="b"),
            demo,
        )
    assert other.value.status_code == 404
    assert not demo.jobs


async def test_demo_tool_rejects_unsigned_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ADLC_DEMO_TOOL_SECRET", "s" * 32)
    demo = service(tmp_path)
    with pytest.raises(HTTPException) as bad:
        await tools(request({}), demo, SimpleNamespace(headers={}))
    assert bad.value.status_code == 401


async def test_webhook_repo_label_signature_and_issue_dedup(tmp_path, monkeypatch):
    demo = service(tmp_path)
    monkeypatch.setenv("ADLC_DEMO_GITHUB_ENABLED", "true")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_WEBHOOK_SECRET", "w" * 32)
    monkeypatch.setenv("ADLC_DEMO_GITHUB_REPOSITORY_ID", "1234")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_OWNER_ID", str(uuid4()))
    monkeypatch.setenv("ADLC_DEMO_WEBHOOK_AUTO_PLAN", "false")
    payload = {
        "repository": {"full_name": "vanguard-lint/vanguard", "id": 1234},
        "action": "opened",
        "issue": {"number": 10, "title": "Demo", "body": REQUIREMENT, "labels": [{"name": "adlc-harness-demo"}]},
    }

    def signed(value, delivery="d1"):
        signature = "sha256=" + hmac.new(b"w" * 32, json.dumps(value).encode(), hashlib.sha256).hexdigest()
        return request(
            value, **{"X-Hub-Signature-256": signature, "X-GitHub-Event": "issues", "X-GitHub-Delivery": delivery}
        )

    first = await webhook(signed(payload), demo)
    again = await webhook(signed({**payload, "action": "labeled"}, "d2"), demo)
    assert first["run_id"] == again["run_id"]
    assert again["duplicate"]
    assert not demo.jobs
    assert not demo.client.commands
    assert demo.ledger.get(first["run_id"])["github"]
    with pytest.raises(HTTPException) as bad:
        await webhook(request(payload), demo)
    assert bad.value.status_code == 401
    wrong = {**payload, "repository": {"id": 1234, "full_name": "other/repo"}}
    with pytest.raises(HTTPException) as denied:
        await webhook(signed(wrong), demo)
    assert denied.value.status_code == 403


async def test_explicit_restart_creates_one_draft_preserves_issue_and_never_inherits_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "aspiringcoder6/vanguard")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_ENABLED", "true")
    demo = service(tmp_path)
    old = await demo.create(
        "a",
        REQUIREMENT,
        github=True,
        issue={
            "source": "GITHUB_WEBHOOK",
            "number": 1,
            "repository": "aspiringcoder6/vanguard",
            "delivery_id": "signed-delivery",
        },
    )
    await demo.update(
        old["id"], status="FAILED", plan_digest="old-approved-plan", candidate={"old": True}, commit="old"
    )
    child = await restart(old["id"], request({}), SimpleNamespace(id="a"), demo)
    again = await restart(old["id"], request({}), SimpleNamespace(id="a"), demo)
    assert child["id"] == again["id"] != old["id"]
    assert child["status"] == "DRAFT"
    assert child["requirement"] == old["requirement"]
    assert child["github"] is True
    assert child["restart_of"] == old["id"]
    assert child["issue"]["delivery_id"] == "signed-delivery"
    assert child["issue"]["source"] == "EXPLICIT_SESSION_RESTART"
    assert not set(child).intersection({"plan_digest", "candidate", "commit", "handoff_digest"})
    assert not demo.client.commands
    assert demo.ledger.get(old["id"])["status"] == "FAILED"
    assert demo.ledger.get(old["id"])["plan_digest"] == "old-approved-plan"
    assert len(demo.ledger.list("a")) == 2


@pytest.mark.parametrize(("scenario", "status"), [("owner", 404), ("repository", 409), ("pending", 409), ("live", 409)])
async def test_restart_rejects_wrong_scope_live_run_and_unknown_intent(tmp_path, monkeypatch, scenario, status):
    monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "aspiringcoder6/vanguard")
    monkeypatch.setenv("ADLC_DEMO_GITHUB_ENABLED", "true")
    demo = service(tmp_path)
    old = await demo.create("a", REQUIREMENT, github=True)
    await demo.update(old["id"], status="FAILED")
    if scenario == "repository":
        monkeypatch.setenv("ADLC_HARNESS_GITHUB_REPOSITORY", "another/repository")
    if scenario == "pending":
        await demo.update(old["id"], restart_pending=True)
    if scenario == "live":
        await demo.update(old["id"], status="RUNNING")
    with pytest.raises(HTTPException) as failure:
        await restart(old["id"], request({}), SimpleNamespace(id="b" if scenario == "owner" else "a"), demo)
    assert failure.value.status_code == status
    assert len(demo.ledger.list("a")) == 1
    assert not demo.client.commands

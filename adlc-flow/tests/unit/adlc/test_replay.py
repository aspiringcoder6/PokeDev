"""H6B actual local HTTP reproduction plus deterministic frozen-suite acceptance."""

# ruff: noqa: S101, S603, S106, INP001, PLR2004 - test-owned data/processes only.
import asyncio
import hashlib
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from uuid import uuid4
from xml.etree import ElementTree as ET

import httpx
import pytest
from pydantic import ValidationError

from langflow.adlc.replay_client import ReplayWorkerClient
from langflow.adlc.replay_models import (
    CREDENTIAL,
    TARGET,
    ReplayCase,
    ReplayPlan,
    ReplayReceipt,
    compare_replay,
    suite_bytes,
)
from langflow.adlc.replay_repository import RUNNER_DIGEST, ReplayRepository
from langflow.adlc.verification_models import VerificationError, canonical, digest
from langflow.adlc.verification_repository import VerificationRepository
from tests.unit.adlc.test_verification import example_plan


def sha(raw):
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def replay_plan(expected=42):
    original = example_plan(expected)
    cases = [ReplayCase(**c.model_dump()) for c in original.cases]
    return ReplayPlan(
        plan_id=original.plan_id,
        workflow_run_id=original.workflow_run_id,
        candidate=original.candidate,
        contract_reference=original.contract_reference,
        cases=cases,
        suite_digest="sha256:" + hashlib.sha256(suite_bytes(cases)).hexdigest(),
    )


def replay_receipt(plan, *, execution_id=None):
    execution_id = execution_id or uuid4()
    passed = plan.cases[0].expected == 42 and not isinstance(plan.cases[0].expected, bool)
    root = ET.Element(
        "testsuite", name="adlc-http-json-replay", tests="1", failures="0" if passed else "1", errors="0", skipped="0"
    )
    child = ET.SubElement(root, "testcase", classname="http-json-fixture", name=plan.cases[0].case_id)
    if not passed:
        ET.SubElement(child, "failure", type="AssertionError").text = "Frozen assertion did not match"
    junit = ET.tostring(root, encoding="unicode")
    return ReplayReceipt(
        schema_version="0.1",
        execution_id=execution_id,
        plan_digest=digest(plan),
        candidate_digest=plan.candidate.content_digest,
        suite_digest=plan.suite_digest,
        config_digest=plan.config_digest,
        runner_ref="runner:adlc-http-json-replay/0.1.0",
        runner_digest=RUNNER_DIGEST,
        provider="local-http-fixture",
        target_profile_ref=TARGET,
        credential_ref=CREDENTIAL,
        target_instance_id=execution_id,
        target_origin="http://127.0.0.1:39001",
        target_released=True,
        heal=False,
        models_used=False,
        tests_run=1,
        completion_mode="process-exit",
        exit_code=0 if passed else 1,
        observations=[
            {
                "case_id": plan.cases[0].case_id,
                "pointer": plan.cases[0].pointer,
                "found": True,
                "observed": 42,
                "http_status": 200,
                "response_digest": plan.candidate.content_digest,
                "outcome": "PASS" if passed else "FAIL",
            }
        ],
        junit_xml=junit,
        junit_digest=sha(junit),
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize("expected", [42, 43, True, 42.0])
def test_binary_verdict_requires_exact_scalar_assertions_and_case_evidence(expected):
    plan = replay_plan(expected)
    report = compare_replay(plan, replay_receipt(plan), RUNNER_DIGEST)
    assert report.verdict == ("PASS" if expected == 42 and not isinstance(expected, bool) else "FAIL")
    assert report.application_verified is False
    assert report.contract_fully_verified is False


@pytest.mark.parametrize(
    "change",
    [
        {"tests_run": 0},
        {"observations": []},
        {"candidate_digest": "sha256:" + "0" * 64},
        {"suite_digest": "sha256:" + "0" * 64},
        {"config_digest": "sha256:" + "0" * 64},
        {"runner_digest": "sha256:" + "0" * 64},
        {"target_instance_id": uuid4()},
        {"heal": True},
        {"models_used": True},
        {"target_released": False},
        {"exit_code": 1},
    ],
)
def test_incomplete_changed_or_unbound_evidence_has_no_binary_verdict(change):
    plan = replay_plan()
    with pytest.raises(VerificationError):
        compare_replay(plan, replay_receipt(plan).model_copy(update=change), RUNNER_DIGEST)


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite name="adlc-http-json-replay" tests="0" failures="0" errors="0" skipped="0" />',
        '<testsuite name="adlc-http-json-replay" tests="1" failures="0" errors="0" skipped="1">'
        '<testcase classname="http-json-fixture" name="answer"><skipped/></testcase></testsuite>',
        '<testsuite name="adlc-http-json-replay" tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="http-json-fixture" name="wrong"/></testsuite>',
        '<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///never-read-this">]><testsuite>&x;</testsuite>',
        '<testsuite name="adlc-http-json-replay" tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="http-json-fixture" name="answer"><error/></testcase></testsuite>',
    ],
)
def test_zero_skipped_wrong_case_errors_and_xml_entities_are_rejected(xml):
    plan = replay_plan()
    receipt = replay_receipt(plan).model_copy(update={"junit_xml": xml, "junit_digest": sha(xml)})
    with pytest.raises(VerificationError):
        compare_replay(plan, receipt, RUNNER_DIGEST)


def test_frozen_suite_rejects_changed_or_duplicate_cases_and_arbitrary_targets():
    plan = replay_plan()
    for change in [
        {"cases": []},
        {"cases": [plan.cases[0].model_dump()] * 2},
        {"heal": True},
        {"target_url": "http://prod"},
    ]:
        with pytest.raises(ValidationError):
            ReplayPlan.model_validate({**plan.model_dump(mode="json"), **change})
    changed = plan.model_dump(mode="json")
    changed["cases"][0]["expected"] = 43
    with pytest.raises(ValidationError):
        ReplayPlan.model_validate(changed)


def test_separate_store_preserves_h6a_records_and_immutable_replay_archive(tmp_path):
    path = tmp_path / "archive.sqlite3"
    original, store = VerificationRepository(path), ReplayRepository(path)
    first = example_plan()
    old = original.create(first, '{"answer":42}', owner="owner", command_key="same", command_digest=digest(0))
    plan = replay_plan(43)
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="same", command_digest=digest(1))
    assert original.get(first.plan_id, owner="owner", run_id=first.workflow_run_id) == old
    with pytest.raises(VerificationError):
        store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    running = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    with pytest.raises(VerificationError):
        store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)
    prepared = store.accept(plan.plan_id, replay_receipt(plan, execution_id=running.execution_id), **args)
    assert prepared.report.verdict == "FAIL"
    assert prepared.state == "READY_FOR_SUBMISSION"
    store.close()
    restored = ReplayRepository(path)
    assert restored.get(plan.plan_id, **args) == prepared
    assert (
        restored.action(plan.plan_id, plan_digest=row.plan_digest, operation="submit", **args)[0].state == "SUBMITTED"
    )
    restored.close()
    original.close()


def test_cancellation_intent_requires_confirmation_and_does_not_make_a_verdict():
    store, plan = ReplayRepository(), replay_plan()
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="one", command_digest=digest(1))
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    running = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    pending = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="cancel", **args)[0]
    assert pending.state == "CANCEL_REQUESTED"
    assert pending.cancelled_at is None
    store.diagnostic(plan.plan_id, code="REPLAY_CANCELLATION_UNCONFIRMED", uncertain=True, **args)
    assert store.get(plan.plan_id, **args).state == "CANCEL_REQUESTED"
    with pytest.raises(VerificationError):
        store.confirm_cancel(plan.plan_id, execution_id=uuid4(), **args)
    cancelled = store.confirm_cancel(plan.plan_id, execution_id=running.execution_id, **args)
    assert cancelled.state == "CANCELLED"
    assert cancelled.report is None
    assert cancelled.cancel_requested_by == "owner"
    assert cancelled.cancelled_at is not None
    with pytest.raises(VerificationError):
        store.action(plan.plan_id, plan_digest=row.plan_digest, operation="submit", **args)
    with pytest.raises(VerificationError):
        store.get(plan.plan_id, owner="another", run_id=plan.workflow_run_id)
    store.close()


@pytest.fixture
def real_replay_worker(tmp_path):
    node = which("node")
    assert node, "Node is required for the real HTTP replay test"
    script = (
        Path(__file__).resolve().parents[4]
        / "agent-harness-server/deepseek-harness/plugins/vai-adlc-replay-runtime/tests/server.mjs"
    )
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "Path", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP"}}
    env.update(
        ADLC_H6B_TEST_DIRECTORY=str(tmp_path / "worker"),
        ADLC_H6B_TEST_PYTHON=sys.executable,
        ADLC_H6B_TEST_TOKEN="test-only-h6b-worker-token-at-least-32-bytes",
    )
    process = subprocess.Popen(
        [node, str(script)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        url = process.stdout.readline().strip()
        assert url.startswith("http://127.0.0.1:")
        yield ReplayWorkerClient(url, env["ADLC_H6B_TEST_TOKEN"])
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("expected", [42, 43, 42.0])
async def test_real_http_json_target_junit_acceptance_and_cleanup(real_replay_worker, expected):
    worker, store, plan = real_replay_worker, ReplayRepository(), replay_plan(expected)
    assert (await worker.health())["ready"]
    assert (await worker.health())["testforge_ready"] is False
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="one", command_digest=digest(1))
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    running = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    await worker.create(running, '{"answer":42}')
    for _ in range(100):
        result = await worker.read(running.execution_id)
        if result["state"] == "READY":
            break
        await asyncio.sleep(0.03)
    receipt = worker.receipt(result)
    prepared = store.accept(plan.plan_id, receipt, **args)
    assert prepared.report.verdict == ("PASS" if expected == 42 else "FAIL")
    assert prepared.receipt.observations[0].http_status == 200
    assert prepared.receipt.target_released is True
    async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            await client.get(receipt.target_origin + "/fixture")
    result["signature"] = "0" * 64
    with pytest.raises(VerificationError, match="UNAUTHENTICATED"):
        worker.receipt(result)
    store.close()


def test_worker_cannot_use_legacy_broker_or_redirect_credentials():
    for url in [
        "http://10.0.10.195:9099/api/v1/replay",
        "http://public.example/api/v1/adlc-harness-replay",
        "https://user:pass@example/api/v1/adlc-harness-replay",
        "https://example/api/v1/adlc-harness-replay?key=x",
        "https://unreviewed.example/api/v1/adlc-harness-replay",
    ]:
        assert not ReplayWorkerClient(url, "x" * 32).configured


def test_cancel_confirmation_is_authenticated_and_bound_to_the_exact_candidate_suite_and_job():
    store, plan = ReplayRepository(), replay_plan()
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="one", command_digest=digest(1))
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    row = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    token = "test-only-token-with-at-least-32-bytes"  # noqa: S105 - never a deployment credential.
    worker = ReplayWorkerClient("http://127.0.0.1:3082/api/v1/adlc-harness-replay", token)
    state = {
        "execution_id": str(row.execution_id),
        "plan_digest": row.plan_digest,
        "candidate_digest": plan.candidate.content_digest,
        "suite_digest": plan.suite_digest,
        "config_digest": plan.config_digest,
        "state": "CANCELLED",
        "target_released": True,
    }
    body = canonical(state).decode()
    result = {
        "state": "CANCELLED",
        "state_json": body,
        "state_signature": hmac.new(
            token.encode(), ("adlc-replay-state/v0.1\n" + body).encode(), hashlib.sha256
        ).hexdigest(),
    }
    worker.confirm_state(row, result)
    with pytest.raises(VerificationError, match="UNAUTHENTICATED"):
        worker.confirm_state(row, {**result, "state_signature": "0" * 64})
    state["suite_digest"] = "sha256:" + "0" * 64
    body = canonical(state).decode()
    result.update(
        state_json=body,
        state_signature=hmac.new(
            token.encode(), ("adlc-replay-state/v0.1\n" + body).encode(), hashlib.sha256
        ).hexdigest(),
    )
    with pytest.raises(VerificationError, match="CANCELLATION_UNCONFIRMED"):
        worker.confirm_state(row, result)
    store.close()


async def test_timed_out_post_is_never_retried():
    calls = []

    def failure(request):
        calls.append(request)
        detail = "test-owned lost response"
        raise httpx.ReadTimeout(detail)

    worker = ReplayWorkerClient(
        "http://127.0.0.1:3082/api/v1/adlc-harness-replay", "x" * 32, transport=httpx.MockTransport(failure)
    )
    with pytest.raises(VerificationError, match="EXECUTION_UNCONFIRMED"):
        await worker.request("POST", "/executions", {})
    assert len(calls) == 1


def test_schemas_match_closed_models():
    from jsonschema import Draft202012Validator

    from scripts.generate_adlc_replay_schemas import OUTPUT, generated

    for name, schema in generated().items():
        assert json.loads((OUTPUT / name).read_text(encoding="utf-8")) == schema
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False

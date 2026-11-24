"""H6A: real protected reproduction, deterministic comparison and durable state.

All files, Git repositories, service credentials and processes are test-owned.
No Docker, external broker, model, user project or production store is used.
"""

# ruff: noqa: S101, S603, S106, INP001, PLR2004, PT018 - test-owned credentials/processes; existing namespace convention.
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from langflow.adlc.contract_models import ContractReference
from langflow.adlc.local_projects import git_at, prepare_project_source
from langflow.adlc.verification_candidate import apply_file_patch, freeze_candidate, strict_json
from langflow.adlc.verification_client import VerificationWorkerClient
from langflow.adlc.verification_models import (
    CandidateReference,
    ExecutionReceipt,
    Observation,
    VerificationCase,
    VerificationError,
    VerificationPlan,
    compare,
    digest,
)
from langflow.adlc.verification_repository import RUNNER_DIGEST, VerificationRepository


def example_plan(expected=42, content='{"answer":42}'):
    return VerificationPlan(
        plan_id=uuid4(),
        workflow_run_id=uuid4(),
        contract_reference=ContractReference(contract_id=uuid4(), revision=1, content_digest="sha256:" + "a" * 64),
        candidate=CandidateReference(
            source_task_id=uuid4(),
            source_attempt_id=uuid4(),
            source_session_id="source-session",
            artifact_id=uuid4(),
            artifact_digest="sha256:" + "b" * 64,
            base_commit="c" * 40,
            project_id=uuid4(),
            source_ref="owned-pinned-source",
            file="fixture.json",
            content_digest="sha256:" + hashlib.sha256(content.encode()).hexdigest(),
        ),
        cases=[
            VerificationCase(
                case_id="answer", pointer="/answer", expected=expected, criterion_node_id=uuid4(), criterion_index=0
            )
        ],
    )


def receipt_for(plan, *, execution_id=None, observed=42, found=True):
    return ExecutionReceipt(
        execution_id=execution_id or uuid4(),
        plan_digest=digest(plan),
        candidate_digest=plan.candidate.content_digest,
        runner_digest=RUNNER_DIGEST,
        provider="local-fixture",
        tests_run=1,
        exit_code=0,
        observations=[Observation(case_id="answer", pointer="/answer", found=found, observed=observed)],
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    ("expected", "observed", "found", "verdict"),
    [
        (42, 42, True, "PASS"),
        (43, 42, True, "FAIL"),
        (True, 1, True, "FAIL"),
        (None, None, False, "FAIL"),
        (None, None, True, "PASS"),
        (1.0, 1, True, "PASS"),
        ("<script>alert(1)</script>", "<script>alert(1)</script>", True, "PASS"),
    ],
)
def test_fixed_predicates(expected, observed, found, verdict):
    plan = example_plan(expected)
    report = compare(plan, receipt_for(plan, observed=observed, found=found), RUNNER_DIGEST)
    assert report.verdict == verdict


@pytest.mark.parametrize(
    "change",
    [
        {"tests_run": 0},
        {"observations": []},
        {"exit_code": 5},
        {"candidate_digest": "sha256:" + "d" * 64},
        {"plan_digest": "sha256:" + "e" * 64},
        {"runner_digest": "sha256:" + "f" * 64},
    ],
)
def test_incomplete_or_mismatched_reproduction_has_no_verdict(change):
    plan = example_plan()
    with pytest.raises(VerificationError):
        compare(plan, receipt_for(plan).model_copy(update=change), RUNNER_DIGEST)


def test_unknown_cases_and_nonempty_unique_plan_are_required():
    plan = example_plan()
    with pytest.raises(ValidationError):
        VerificationPlan.model_validate({**plan.model_dump(mode="json"), "cases": []})
    with pytest.raises(ValidationError):
        VerificationPlan.model_validate({**plan.model_dump(mode="json"), "cases": [plan.cases[0].model_dump()] * 2})
    with pytest.raises(ValidationError):
        VerificationCase.model_validate({**plan.cases[0].model_dump(), "approved_by": "human"})
    with pytest.raises(ValidationError):
        Observation(case_id="answer", pointer="/answer", found="true", observed=42)
    wrong = receipt_for(plan)
    wrong.observations[0].case_id = "different"
    with pytest.raises(VerificationError):
        compare(plan, wrong, RUNNER_DIGEST)


def test_recovered_checkpoint_does_not_claim_an_observed_os_exit():
    plan = example_plan()
    receipt = receipt_for(plan).model_copy(update={"completion_mode": "durable-checkpoint", "exit_code": None})
    assert compare(plan, receipt, RUNNER_DIGEST).verdict == "PASS"
    with pytest.raises(VerificationError):
        compare(plan, receipt.model_copy(update={"exit_code": 0}), RUNNER_DIGEST)


def test_durable_exact_approval_execution_receipt_and_manual_submit(tmp_path):
    path = tmp_path / "verification.sqlite3"
    store = VerificationRepository(path)
    plan = example_plan()
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    draft = store.create(plan, '{"answer":42}', owner="owner", command_key="create", command_digest=digest("command"))
    assert draft.state == "DRAFT"
    with pytest.raises(VerificationError):
        store.action(plan.plan_id, plan_digest=draft.plan_digest, operation="execute", **args)
    with pytest.raises(VerificationError):
        store.action(plan.plan_id, plan_digest="sha256:" + "f" * 64, operation="approve", **args)
    approved, _ = store.action(plan.plan_id, plan_digest=draft.plan_digest, operation="approve", **args)
    assert approved.approved_by == "owner" and approved.state == "APPROVED"
    started, _ = store.action(plan.plan_id, plan_digest=draft.plan_digest, operation="execute", **args)
    with pytest.raises(VerificationError, match="EXECUTION_NOT_ALLOWED"):
        store.action(plan.plan_id, plan_digest=draft.plan_digest, operation="execute", **args)
    assert store.get(plan.plan_id, **args).execution_id == started.execution_id
    receipt = receipt_for(plan, execution_id=started.execution_id)
    prepared = store.accept(plan.plan_id, receipt, **args)
    assert prepared.state == "READY_FOR_SUBMISSION" and prepared.submitted_at is None
    store.close()
    restored = VerificationRepository(path)
    assert restored.get(plan.plan_id, **args) == prepared
    submitted = restored.action(plan.plan_id, plan_digest=draft.plan_digest, operation="submit", **args)[0]
    assert submitted.state == "SUBMITTED" and submitted.report.verdict == "PASS"
    assert restored.action(plan.plan_id, plan_digest=draft.plan_digest, operation="submit", **args)[0] == submitted
    restored.close()


def test_ownership_idempotency_and_quota(tmp_path):
    store = VerificationRepository(tmp_path / "proof.sqlite3", max_records=1)
    plan = example_plan()
    first = store.create(plan, '{"answer":42}', owner="one", command_key="key", command_digest=digest(1))
    assert (
        store.create(
            example_plan().model_copy(update={"workflow_run_id": plan.workflow_run_id}),
            '{"answer":42}',
            owner="one",
            command_key="key",
            command_digest=digest(1),
        )
        == first
    )
    with pytest.raises(VerificationError):
        store.get(plan.plan_id, owner="two", run_id=plan.workflow_run_id)
    with pytest.raises(VerificationError):
        store.create(plan, '{"answer":42}', owner="one", command_key="key", command_digest=digest(2))
    with pytest.raises(VerificationError):
        store.create(example_plan(), '{"answer":42}', owner="one", command_key="different", command_digest=digest(3))
    store.close()


def test_store_tampering_and_conflicting_receipt_fail_closed(tmp_path):
    store = VerificationRepository(tmp_path / "proof.sqlite3")
    plan = example_plan()
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="one", command_digest=digest(1))
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    started = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    receipt = receipt_for(plan, execution_id=started.execution_id)
    store.accept(plan.plan_id, receipt, **args)
    with pytest.raises(VerificationError):
        store.accept(plan.plan_id, receipt.model_copy(update={"tests_run": 0}), **args)
    store.db.execute("UPDATE adlc_verifications SET candidate='{}'")
    store.db.commit()
    with pytest.raises(VerificationError, match="VERIFICATION_STORE_INVALID"):
        store.get(plan.plan_id, **args)
    store.close()


@pytest.mark.parametrize("value", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', "[" * 20 + "0" + "]" * 20])
def test_candidate_parser_rejects_ambiguous_or_unbounded_json(value):
    with pytest.raises((ValueError, VerificationError)):
        strict_json(value)


def test_candidate_reconstructed_from_real_pinned_git_source_and_archived_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_ROOTS", str(tmp_path))
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_SOURCE_ROOT", str(tmp_path / "snapshots"))
    source = tmp_path / "source"
    source.mkdir()
    git_at(source, "init")
    git_at(source, "config", "user.name", "Fixture")
    git_at(source, "config", "user.email", "fixture@example.invalid")
    (source / "fixture.json").write_text('{"answer":0}\n', encoding="utf-8")
    git_at(source, "add", "fixture.json")
    git_at(source, "commit", "-m", "test fixture base")
    ref = prepare_project_source(uuid4(), "Fixture", str(source))
    (source / "fixture.json").write_text('{"answer":42}\n', encoding="utf-8")
    patch = git_at(source, "diff", "--no-ext-diff", "--", "fixture.json")
    attempt = uuid4()
    task = SimpleNamespace(
        id=uuid4(),
        current_attempt_id=attempt,
        request=SimpleNamespace(context={"adlc_local_project": ref}),
        result=SimpleNamespace(metadata={"harness_session_id": "source-session"}),
    )
    snapshot = SimpleNamespace(
        base_commit=ref["base_commit"],
        artifact=SimpleNamespace(attempt_id=attempt, artifact_id=uuid4(), checksum=SimpleNamespace(value="b" * 64)),
        files=[SimpleNamespace(file="fixture.json", patch=patch)],
    )
    candidate, content = freeze_candidate(task, snapshot, "fixture.json")
    assert content == '{"answer":42}'
    assert candidate.base_commit == ref["base_commit"]
    assert candidate.content_digest == digest({"answer": 42})
    assert (source / "fixture.json").read_text() == '{"answer":42}\n'
    with pytest.raises(VerificationError):
        freeze_candidate(task, snapshot, "../secret.json")
    task.current_attempt_id = uuid4()
    with pytest.raises(VerificationError, match="STALE"):
        freeze_candidate(task, snapshot, "fixture.json")


def test_patch_rejects_wrong_base_other_file_and_deleted_file():
    patch = (
        "diff --git a/fixture.json b/fixture.json\n--- a/fixture.json\n+++ b/fixture.json\n"
        '@@ -1 +1 @@\n-{"answer":0}\n+{"answer":42}'
    )
    assert apply_file_patch('{"answer":0}', patch, "fixture.json") == '{"answer":42}'
    for base, changed in [
        ("wrong", patch),
        ('{"answer":0}', patch.replace("+++ b/fixture.json", "+++ b/other.json")),
        ('{"answer":0}', patch.replace("+++ b/fixture.json", "+++ /dev/null")),
    ]:
        with pytest.raises(VerificationError):
            apply_file_patch(base, changed, "fixture.json")


@pytest.fixture
def real_worker(tmp_path):
    node = which("node")
    assert node, "Node.js is required for the real H6A fixture integration test."
    script = (
        Path(__file__).resolve().parents[4]
        / "agent-harness-server/deepseek-harness/plugins/vai-adlc-sandbox-runtime/tests/server.mjs"
    )
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "Path", "SystemRoot", "SYSTEMROOT", "TEMP", "TMP"}}
    env.update(
        ADLC_H6A_TEST_DIRECTORY=str(tmp_path / "worker"),
        ADLC_H6A_TEST_PYTHON=sys.executable,
        ADLC_H6A_TEST_TOKEN="test-only-worker-token-at-least-32-bytes",
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
        yield VerificationWorkerClient(url, env["ADLC_H6A_TEST_TOKEN"])
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("expected", [42, 43])
async def test_real_node_to_python_reproduction_authentication_comparison_and_archive(real_worker, tmp_path, expected):
    assert (await real_worker.health())["ready"]
    plan = example_plan(expected)
    store = VerificationRepository(tmp_path / "accepted.sqlite3")
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    row = store.create(plan, '{"answer":42}', owner="owner", command_key="one", command_digest=digest(1))
    store.action(plan.plan_id, plan_digest=row.plan_digest, operation="approve", **args)
    row = store.action(plan.plan_id, plan_digest=row.plan_digest, operation="execute", **args)[0]
    await real_worker.create(row, '{"answer":42}')
    result = None
    for _ in range(100):
        result = await real_worker.read(row.execution_id)
        if result["state"] == "READY":
            break
        await asyncio.sleep(0.03)
    receipt = real_worker.receipt(result)
    prepared = store.accept(plan.plan_id, receipt, **args)
    assert prepared.report.verdict == ("PASS" if expected == 42 else "FAIL")
    assert prepared.receipt.completion_mode == "process-exit"
    assert prepared.receipt.observations[0].observed == 42
    result["signature"] = "0" * 64
    with pytest.raises(VerificationError, match="UNAUTHENTICATED"):
        real_worker.receipt(result)
    store.close()


def test_worker_configuration_refuses_arbitrary_http_and_url_credentials():
    for url in [
        "http://remote.example/api/v1/adlc-harness-verify",
        "https://user:pass@example/api/v1/adlc-harness-verify",
        "https://example/api/v1/adlc-harness-verify?secret=x",
        "https://example:invalid/api/v1/adlc-harness-verify",
        "https:///api/v1/adlc-harness-verify",
    ]:
        assert not VerificationWorkerClient(url, "x" * 32).configured


def test_published_verification_schemas_match_closed_runtime_models():
    from jsonschema import Draft202012Validator

    from scripts.generate_adlc_verification_schemas import OUTPUT, generated

    for name, schema in generated().items():
        assert json.loads((OUTPUT / name).read_text(encoding="utf-8")) == schema
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False


def test_session_filter_precedes_pagination_and_archive_has_two_pages():
    store = VerificationRepository()
    plan = example_plan()
    store.create(plan, '{"answer":42}', owner="owner", command_key="oldest", command_digest=digest(0))
    for i in range(100):
        other = plan.model_copy(deep=True)
        other.plan_id = uuid4()
        other.candidate.source_session_id = "a-different-session"
        store.create(other, '{"answer":42}', owner="owner", command_key=str(i), command_digest=digest(i + 1))
    assert len(store.list(owner="owner", run_id=plan.workflow_run_id)) == 100
    assert len(store.list(owner="owner", run_id=plan.workflow_run_id, offset=100)) == 1
    selected = store.list(
        owner="owner",
        run_id=plan.workflow_run_id,
        attempt_id=plan.candidate.source_attempt_id,
        session_id="source-session",
    )
    assert len(selected) == 1 and selected[0].plan.plan_id == plan.plan_id
    store.close()

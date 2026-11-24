"""H6D exact revisions, durable sidecars, hostile rasters and bounded proposals."""

# ruff: noqa: S101, PLR2004, INP001, PT018 - bounded test fixture assertions.
import base64
import io
import json
from uuid import uuid4

import pytest
from PIL import Image, PngImagePlugin
from pydantic import TypeAdapter, ValidationError

from langflow.adlc.replay_repository import ReplayRepository
from langflow.adlc.test_extension_models import PerformanceBudget, ProposalCommand, ScreenshotUpload, TestPermissions
from langflow.adlc.test_extension_repository import TestExtensionRepository, bytes_digest, normalize_png
from langflow.adlc.verification_models import VerificationError
from tests.unit.adlc.test_replay import replay_plan, replay_receipt

ADAPTER = TypeAdapter(ProposalCommand)
PERMISSIONS = {
    "target_profile_ref": "target-profile:disposable-http-json/0.1.0",
    "credential_ref": "credential-profile:ephemeral-fixture/0.1.0",
    "environment": "non-production",
    "data_scope": "synthetic-run-owned-only",
    "allowed_methods": ["GET"],
    "allowed_paths": ["/fixture"],
    "network_scope": "allocated-loopback-target-only",
    "cleanup": "release-owned-target",
    "cancellation": "confirmed-worker-cancel",
    "max_duration_seconds": 15,
}
BUDGET = {
    "virtual_users": 2,
    "duration_seconds": 10,
    "requests_per_second": 2,
    "max_requests": 20,
    "p95_latency_ms_max": 500,
    "failed_requests_max": 0,
}


def png(width=20, height=10, *, metadata=False):
    stream = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("external", "<script>not rendered</script>")
    Image.new("RGB", (width, height), "white").save(stream, format="PNG", pnginfo=info)
    return stream.getvalue()


def upload(source, raw=None, **changes):
    body = png(metadata=True) if raw is None else raw
    return ScreenshotUpload(
        plan_digest=source.plan_digest,
        execution_id=source.execution_id,
        case_id=source.plan.cases[0].case_id,
        caption="Owner reference, not runner evidence",
        png_base64=base64.b64encode(body).decode(),
        input_digest=bytes_digest(body),
        idempotency_key="image-one",
        **changes,
    )


@pytest.fixture
def stores(tmp_path):
    replays, proposals = ReplayRepository(tmp_path / "replay.db"), TestExtensionRepository(tmp_path / "extensions.db")
    plan = replay_plan(43)
    source = replays.create(
        plan, '{"answer":42}', owner="owner", command_key="source", command_digest="sha256:" + "a" * 64
    )
    args = {"owner": "owner", "run_id": plan.workflow_run_id}
    yield replays, proposals, source, args
    replays.close()
    proposals.close()


def init(proposals, source, args, *, kind="suite-revision", **changes):
    command = ADAPTER.validate_python(
        {
            "operation": "init",
            "source_plan_id": str(source.plan.plan_id),
            "kind": kind,
            "title": "Reviewed successor",
            "rationale": "Repair creates a new standard, never a changed PASS.",
            "idempotency_key": "init-one",
            **changes,
        }
    )
    return proposals.command(command, source=source, **args)


def command(proposals, row, args, operation, **changes):
    parsed = ADAPTER.validate_python(
        {
            "operation": operation,
            "reference": row.reference.model_dump(mode="json"),
            "idempotency_key": str(uuid4()),
            **changes,
        }
    )
    return proposals.command(parsed, validate=lambda _: None, **args)


def ready(proposals, row, args):
    row = command(proposals, row, args, "set_permissions", permissions=PERMISSIONS)
    return command(proposals, row, args, "validate")


def test_exact_frozen_successor_preserves_original_and_requires_new_permissions(stores):
    replays, proposals, source, args = stores
    row = init(proposals, source, args)
    assert row.document.permissions is None
    with pytest.raises(VerificationError, match="INCOMPLETE"):
        command(proposals, row, args, "validate")
    case = row.document.cases[0].model_dump(mode="json")
    changed = command(proposals, row, args, "upsert_case", case={**case, "expected": 42})
    assert changed.reference.document_digest != row.reference.document_digest
    with pytest.raises(VerificationError, match="REFERENCE_CONFLICT"):
        command(proposals, row, args, "remove_case", case_id="answer")
    reviewed = ready(proposals, changed, args)
    with pytest.raises(VerificationError, match="FROZEN"):
        command(proposals, reviewed, args, "upsert_case", case=case)
    approved = proposals.approve(reviewed.reference, **args)
    assert approved.approved_by == "owner" and approved.state == "APPROVED"
    fork = init(
        proposals, source, args, parent_reference=approved.reference.model_dump(mode="json"), idempotency_key="fork"
    )
    assert fork.reference.revision == 2 and fork.document.parent_reference == approved.reference
    assert fork.document.permissions is None and fork.approved_by is None
    assert fork.document.executable is False and fork.document.verification_evidence is False
    assert replays.get(source.plan.plan_id, **args) == source


def test_mutation_idempotency_cross_owner_and_active_session_draft_ownership(stores):
    _, proposals, source, args = stores
    row = init(proposals, source, args)
    assert init(proposals, source, args).reference == row.reference
    with pytest.raises(VerificationError, match="IDEMPOTENCY_CONFLICT"):
        init(proposals, source, args, title="Changed request")
    with pytest.raises(VerificationError, match="NOT_FOUND"):
        proposals.get(row.reference.proposal_id, owner="other", run_id=args["run_id"])
    parsed = ADAPTER.validate_python(
        {
            "operation": "remove_case",
            "reference": row.reference.model_dump(mode="json"),
            "case_id": "answer",
            "idempotency_key": "agent-edit",
        }
    )
    with pytest.raises(VerificationError, match="NOT_FOUND"):
        proposals.command(parsed, session_id="different-agent", **args)
    updated = proposals.command(parsed, **args)
    assert proposals.command(parsed, **args) == updated
    assert updated.document.cases == []
    with pytest.raises(VerificationError, match="INCOMPLETE"):
        ready(proposals, updated, args)


@pytest.mark.parametrize(
    "change",
    [
        {"approved_by": "human"},
        {"role": "human"},
        {"heal": True},
        {"base_url": "https://production"},
        {"kind": "deploy"},
    ],
)
def test_caller_cannot_supply_permission_or_execution_authority(change):
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(
            {
                "operation": "init",
                "source_plan_id": str(uuid4()),
                "kind": "exploration",
                "title": "Draft",
                "rationale": "Proposal only",
                "idempotency_key": "one",
                **change,
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "production"},
        {"allowed_methods": ["DELETE"]},
        {"data_scope": "all-data"},
        {"allowed_paths": ["/admin"]},
        {"cleanup_url": "http://prod"},
        {"max_duration_seconds": True},
        {"max_duration_seconds": 61},
    ],
)
def test_permissions_reject_arbitrary_production_targets_and_cleanup(change):
    with pytest.raises(ValidationError):
        TestPermissions.model_validate({**PERMISSIONS, **change})


@pytest.mark.parametrize(
    "change",
    [
        {"virtual_users": 6},
        {"max_requests": 101},
        {"duration_seconds": 31},
        {"requests_per_second": 6},
        {"max_requests": 19},
        {"virtual_users": True},
        {"p95_latency_ms_max": 0},
    ],
)
def test_performance_planning_limits_are_strict(change):
    with pytest.raises(ValidationError):
        PerformanceBudget.model_validate({**BUDGET, **change})


def completed(replays, source, args):
    replays.action(source.plan.plan_id, plan_digest=source.plan_digest, operation="approve", **args)
    running = replays.action(source.plan.plan_id, plan_digest=source.plan_digest, operation="execute", **args)[0]
    return replays.accept(source.plan.plan_id, replay_receipt(source.plan, execution_id=running.execution_id), **args)


def test_supplementary_png_is_sanitized_bound_immutable_and_never_changes_fail(stores, tmp_path):
    replays, proposals, source, args = stores
    source = completed(replays, source, args)
    image = proposals.attach(upload(source), source, owner="owner")
    same = proposals.attach(upload(source), source, owner="owner")
    assert same == image
    assert image.affects_verdict is False and image.capture_provenance_verified is False
    assert image.authority == "SUPPLEMENTARY_UNTRUSTED" and image.case_evidence_digest == source.evidence_digest
    read, body = proposals.screenshot(image.attachment_id, source, owner="owner")
    assert read == image and bytes_digest(body) == image.content_digest and b"external" not in body
    assert replays.get(source.plan.plan_id, **args).report.verdict == "FAIL"
    assert replays.get(source.plan.plan_id, **args) == source
    with pytest.raises(VerificationError, match="NOT_FOUND"):
        proposals.screenshot(image.attachment_id, source, owner="other")
    changed = upload(source).model_copy(update={"execution_id": uuid4()})
    with pytest.raises(VerificationError, match="BINDING_INVALID"):
        proposals.attach(changed, source, owner="owner")
    reopened = TestExtensionRepository(tmp_path / "extensions.db")
    assert reopened.screenshot(image.attachment_id, source, owner="owner")[1] == body
    reopened.close()


@pytest.mark.parametrize(
    "raw",
    [
        b"<svg><script>bad()</script></svg>",
        b"<html>not an image</html>",
        b"\x89PNG\r\n\x1a\ntruncated",
        b"",
        png(4097, 1),
        png(2001, 2000),
    ],
    ids=["svg", "html", "truncated", "empty", "dimension-cap", "pixel-cap"],
)
def test_invalid_or_oversized_raster_is_rejected(raw, stores):
    replays, _, source, args = stores
    source = completed(replays, source, args)
    if not raw:
        with pytest.raises(ValidationError):
            upload(source, raw)
    else:
        with pytest.raises(VerificationError, match="SCREENSHOT_INVALID"):
            normalize_png(upload(source, raw))


def test_quota_and_corruption_fail_closed(stores):
    _, proposals, source, args = stores
    row = init(proposals, source, args)
    proposals.max_commands = 1
    with pytest.raises(VerificationError, match="ARCHIVE_FULL"):
        command(proposals, row, args, "set_permissions", permissions=PERMISSIONS)
    assert proposals.get(row.reference.proposal_id, **args) == row  # rolled back
    proposals.db.execute("UPDATE adlc_test_proposals SET body=?", (json.dumps({"state": "APPROVED"}),))
    proposals.db.commit()
    with pytest.raises(VerificationError, match="ARCHIVE_INVALID"):
        proposals.get(row.reference.proposal_id, **args)

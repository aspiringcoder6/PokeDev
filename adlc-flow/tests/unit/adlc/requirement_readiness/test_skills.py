import hashlib

import pytest

from langflow.adlc.requirement_readiness.skills import SkillCatalog


def test_skill_hash_and_dependency_containment(tmp_path):
    entry = tmp_path / "SKILL.md"
    entry.write_text("trusted instructions")
    manifest = {"skills": {"router": {"entry": "SKILL.md", "sha256": hashlib.sha256(entry.read_bytes()).hexdigest()}}}
    catalog = SkillCatalog(tmp_path, manifest)
    assert catalog.read("router") == "trusted instructions"
    assert not catalog.check_route("openspec").ready
    entry.write_text("changed")
    with pytest.raises(ValueError, match="READINESS_RUNTIME_CHANGED"):
        catalog.read("router")
    with pytest.raises(ValueError):
        catalog.read("../secret")


def test_native_receipt_binds_actual_workspace_operation_route_and_version(tmp_path):
    import subprocess
    import sys

    from langflow.adlc.requirement_readiness.models import NormalizedInput, PipelineConfig
    from langflow.adlc.requirement_readiness.skills import NativeCommandRunner
    from langflow.adlc.requirement_readiness.store import ReadinessStore

    store = ReadinessStore(tmp_path / "runs.db")
    run = store.create("svc", NormalizedInput(request_id="r", project_id="p", requirement="Assess"), PipelineConfig())
    store.begin_operation(run.id, "review-op", "reviewer-a", "review-session")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "spec.md").write_text("Actual native spec")
    version = subprocess.check_output([sys.executable, "--version"]).decode().strip()
    command = {
        "argv": [
            sys.executable,
            "-c",
            "from pathlib import Path; assert Path(__import__('sys').argv[1]).read_text()",
            "{spec}",
        ],
        "mode": "read-only",
        "version": version,
        "version_argv": [sys.executable, "--version"],
    }
    manifest = {
        "artifact_workspace": str(artifacts),
        "commands": {"check": command, "other": command},
        "routes": {"openspec": {"required_steps": ["check"]}, "spec-kit": {"required_steps": ["other"]}},
    }
    catalog = SkillCatalog(tmp_path, manifest, store)
    receipt = NativeCommandRunner(catalog, store, artifacts).execute(
        "check", "snapshot", {"spec": "spec.md"}, operation_id="review-op"
    )
    assert catalog.validate_receipts([receipt.id], "snapshot", ["spec.md"], "openspec", run.id)
    assert not catalog.validate_receipts([receipt.id], "snapshot", ["spec.md"], "spec-kit", run.id)
    assert not catalog.validate_receipts([receipt.id], "snapshot", ["spec.md"], "openspec", "other-run")
    (artifacts / "spec.md").write_text("Changed after check")
    assert not catalog.validate_receipts([receipt.id], "snapshot", ["spec.md"], "openspec", run.id)

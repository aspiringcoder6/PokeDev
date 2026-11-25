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

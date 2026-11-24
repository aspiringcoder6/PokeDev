"""Enterprise repositories must retain the original content of planned edits."""

import pytest

from langflow.adlc import gitea_projects as projects
from langflow.adlc.vai_services import ServiceCheckError


def source(monkeypatch, files):
    reads = []

    def git(_folder, *args, **_options):
        if args[0] == "ls-tree":
            return "\0".join(files) + "\0"
        path = args[-1].split(":", 1)[1]
        if args[0] == "cat-file":
            return str(len(files[path].encode()))
        assert args[0] == "show"
        reads.append(path)
        return files[path]

    monkeypatch.setattr(projects, "git", git)
    return reads


def test_late_planned_sources_and_i18n_survive_optional_context_budget(monkeypatch):
    files = {f"src/domain/Early{n:02}.java": "a" * 100000 for n in range(12)}
    service = "src/service/YouthUnionService.java"
    resource = "src/i18n/messages.properties"
    files.update({service: "original application source", resource: "original.error=Message"})
    source(monkeypatch, files)
    assert service not in projects.source_files("repo", "commit")[0]
    selected, tree = projects.source_files("repo", "commit", required_paths=[service, resource, "new/Stats.java"])
    assert selected[service] == files[service]
    assert selected[resource] == files[resource]
    assert tree == list(files)
    assert "new/Stats.java" not in selected
    assert sum(len(value.encode()) for value in selected.values()) <= 1200000


def test_required_binary_is_rejected_and_secrets_are_never_read(monkeypatch):
    reads = source(monkeypatch, {".env.remote": "secret", "lib/binary.jar": "binary", "app.java": "source"})
    with pytest.raises(ServiceCheckError) as error:
        projects.source_files("repo", "commit", required_paths=["lib/binary.jar", ".env.remote"])
    assert error.value.code == "PROJECT_REQUIRED_SOURCE_UNAVAILABLE"
    assert ".env.remote" not in reads
    assert "lib/binary.jar" not in reads


def test_java_dependencies_are_prioritized_without_granting_them_write_access(monkeypatch):
    files = {f"src/domain/Early{n:02}.java": "a" * 100000 for n in range(12)}
    files.update({"src/service/FeatureService.java": "class FeatureService { PermissionService permissions; }",
        "src/service/PermissionService.java": "class PermissionService {}"})
    source(monkeypatch, files)
    selected, _ = projects.source_files("repo", "commit", required_paths=["src/service/FeatureService.java"])
    assert selected["src/service/PermissionService.java"] == files["src/service/PermissionService.java"]


def test_large_editable_source_is_loaded_whole_or_fails_explicitly(monkeypatch):
    source(monkeypatch, {"Large.java": "x" * 120000})
    assert len(projects.source_files("repo", "commit", required_paths=["Large.java"])[0]["Large.java"]) == 120000
    source(monkeypatch, {"Large.java": "x" * 160001})
    with pytest.raises(ServiceCheckError) as error:
        projects.source_files("repo", "commit", required_paths=["Large.java"])
    assert error.value.code == "PROJECT_REQUIRED_SOURCE_TOO_LARGE"

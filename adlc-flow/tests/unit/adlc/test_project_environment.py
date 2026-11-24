import copy
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4
import zipfile

import pytest

from langflow.adlc.gitea_projects import git, prepare_candidate
from langflow.adlc.live_workflows import LiveService, LiveStore
from langflow.adlc.project_environment import (
    DEFAULT_PROFILE,
    ProjectEnvironment,
    apply_environment,
    archive_sources,
    environment_commands,
    environment_preview,
    public_environment,
    validate_profile,
    workspace_path,
)
from langflow.adlc.vai_services import ServiceCheckError
from test_live_workflows import plan, project


def profile():
    return {
        **copy.deepcopy(DEFAULT_PROFILE),
        "tests": [{"label": "Unit tests", "argv": ["python", "-m", "unittest"], "timeout": 60}],
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ({"working_directory": "../private"}, "INVALID"),
        ({"tests": []}, "TESTS_REQUIRED"),
        ({"tests": [{"label": "test", "argv": ["python"], "timeout": True}]}, "COMMAND_INVALID"),
        ({"base": {"repository_id": 1, "commit": 123}}, "BASE_INVALID"),
        ({"base": {"repository_id": True}}, "BASE_INVALID"),
        ({"overlays": [{"source": "src", "target": "app"}]}, "MAPPING_INVALID"),
        ({"preview": {"path": "/etc"}}, "PREVIEW_INVALID"),
    ],
)
def test_environment_rejects_escaping_and_unbounded_execution(change, code):
    with pytest.raises(ServiceCheckError, match=code):
        validate_profile({**profile(), **change})


@pytest.mark.asyncio
async def test_profiles_are_owned_revision_checked_and_freeze_commands_for_each_run(tmp_path):
    store = LiveStore(tmp_path / "live.db")
    p = project(store)
    service = LiveService(store)
    environments = ProjectEnvironment(service)
    first = await environments.save("alice", p["project_id"], 0, profile())
    frozen = environments.freeze("alice", p["project_id"])
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        await environments.save("alice", p["project_id"], 0, profile())
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        environments.read("bob", p["project_id"])
    updated = profile()
    updated["tests"][0]["argv"].append("-v")
    second = await environments.save("alice", p["project_id"], 1, updated)
    assert first["digest"] != second["digest"] and frozen["revision"] == 1
    row, _ = store.create("alice", p, "delivery", str(uuid4()), "Build app", "App", "a" * 40, environment=frozen)
    assert row["environment"]["digest"] == first["digest"]
    original = plan()
    approved = apply_environment(original, frozen)
    assert approved["environment_digest"] == first["digest"] and approved["commands"] == frozen["profile"]["tests"]
    assert original == plan() and apply_environment(approved, frozen)["digest"] == approved["digest"]
    assert approved["digest"] != apply_environment(original, environments.freeze("alice", p["project_id"]))["digest"]


def test_frozen_environment_replaces_proposed_commands_before_validating_the_final_plan():
    generated = plan()
    generated.update(commands=[{"argv": ["python", "x" * 1000], "timeout": 1200}], preview="unusable")
    original = copy.deepcopy(generated)
    frozen = {"profile": profile(), "digest": "d" * 64}
    final = apply_environment(generated, frozen)
    assert final["commands"] == profile()["tests"]
    assert final["preview"] is None and final["browser_checks"] == []
    assert generated == original
    generated["tasks"][0]["write_paths"] = ["../escape"]
    with pytest.raises(ValueError, match="WRITE_PATH"):
        apply_environment(generated, frozen)


def test_without_a_frozen_environment_proposed_commands_still_require_validation():
    generated = plan()
    generated["commands"] = [{"argv": ["python", "x" * 1000]}]
    with pytest.raises(ValueError, match="COMMAND_INVALID"):
        apply_environment(generated, None)


def test_directory_shim_uses_argv_and_preview_paths_follow_workdir():
    value = {"profile": {**profile(), "working_directory": "apps/web", "preview": {"path": "dist"}}}
    command = environment_commands(value)[0]
    assert command["argv"][-4:] == ["apps/web", "python", "-m", "unittest"]
    assert command["argv"][:2] == ["python", "-c"]
    assert environment_preview(value) == {"path": "apps/web/dist"}
    value["profile"]["preview"] = {"argv": ["node", "server.js"]}
    assert environment_preview(value)["argv"][-3:] == ["apps/web", "node", "server.js"]


def repository(path, files):
    path.mkdir()
    git(path, "init", "--initial-branch=main")
    for name, body in files.items():
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body if isinstance(body, bytes) else body.encode())
    git(path, "add", ".")
    git(path, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "baseline")
    return git(path, "rev-parse", "HEAD")


def test_real_git_shell_assembly_maps_primary_files_deletions_and_binary_assets_deterministically(tmp_path):
    shell = tmp_path / "shell"
    pin = repository(
        shell,
        {
            "package.json": "{}",
            "src/module/old.ts": "stale",
            "src/module/keep.ts": "old",
            "public/icon.png": b"\x89PNG\x00binary",
            ".env.secret": "secret",
        },
    )
    source = tmp_path / "sut"
    commit = repository(
        source, {"FE/module/keep.ts": "before", "FE/module/deleted.ts": "gone", "docs/readme.md": "doc"}
    )
    candidate = tmp_path / "candidate"
    prepare_candidate(source, commit, candidate)
    (candidate / "FE/module/keep.ts").write_text("after")
    (candidate / "FE/module/deleted.ts").unlink()
    environment = {
        "profile": {
            **profile(),
            "base": {"source_path": str(shell), "commit": pin},
            "overlays": [{"source": "FE/module", "target": "src/module"}],
        }
    }
    paths = ["FE/module/keep.ts", "FE/module/deleted.ts", "docs/readme.md"]
    first = archive_sources(candidate, paths, environment, tmp_path / "first.zip")
    second = archive_sources(candidate, paths, environment, tmp_path / "second.zip")
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.read("src/module/keep.ts") == b"after"
        assert archive.read("public/icon.png") == b"\x89PNG\x00binary"
        assert "src/module/old.ts" not in archive.namelist() and "src/module/deleted.ts" not in archive.namelist()
        assert not any(p.startswith(".env") for p in archive.namelist())
    assert workspace_path("FE/module/new.spec.ts", environment) == "src/module/new.spec.ts"
    assert "source_path" not in public_environment(environment)["profile"]["base"]
    (candidate / "src/module").mkdir(parents=True)
    (candidate / "src/module/keep.ts").write_text("collision")
    with pytest.raises(ServiceCheckError, match="COLLISION"):
        archive_sources(candidate, paths + ["src/module/keep.ts"], environment, tmp_path / "collision.zip")


def test_mapping_overlap_is_rejected_before_fetching_sources():
    value = profile()
    value.update(
        base={"repository_id": 2},
        overlays=[
            {"source": "FE/module", "target": "src/module"},
            {"source": "FE/module/child", "target": "src/other"},
        ],
    )
    with pytest.raises(ServiceCheckError, match="MAPPING_INVALID"):
        validate_profile(value)


def test_dependency_cache_uses_git_objects_without_materializing_another_worktree(tmp_path, monkeypatch):
    from langflow.adlc import gitea_projects as sources

    upstream = tmp_path / "upstream" / "admin"
    upstream.mkdir(parents=True)
    commit = repository(upstream / "base.git", {"lib/core.jar": "pinned dependency"})
    branch = git(upstream / "base.git", "branch", "--show-current")
    monkeypatch.setattr(sources, "DATA", tmp_path / "cache")
    monkeypatch.setattr(sources, "configuration", lambda: (str(tmp_path / "upstream"), "unused", "unused"))
    repo = {"id": 1, "full_name": "admin/base", "default_branch": branch}
    cache, revision = sources.checkout("alice", "environment", repo, materialize=False)
    assert revision == commit and not (Path(cache) / "lib/core.jar").exists()
    assert git(cache, "show", commit + ":lib/core.jar") == "pinned dependency"
    primary, _ = sources.checkout("alice", "primary", repo)
    assert (Path(primary) / "lib/core.jar").read_text() == "pinned dependency"


def test_root_module_overlay_preserves_pinned_dependencies_and_maps_protected_paths(tmp_path):
    shell = tmp_path / "shell"
    pin = repository(shell, {"lib/common.jar": "dependency", "modules/api/obsolete.txt": "old"})
    source = tmp_path / "module"
    commit = repository(source, {"pom.xml": "build", "src/Test.java": "protected test"})
    candidate = tmp_path / "candidate"
    prepare_candidate(source, commit, candidate)
    value = profile()
    value.update(
        base={"repository_id": 2}, working_directory="modules/api", overlays=[{"source": ".", "target": "modules/api"}]
    )
    validate_profile(value)
    value["base"] = {"source_path": str(shell), "commit": pin}
    environment = {"profile": value}
    raw = archive_sources(candidate, ["pom.xml", "src/Test.java"], environment, tmp_path / "root.zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.read("lib/common.jar") == b"dependency"
        assert archive.read("modules/api/src/Test.java") == b"protected test"
        assert "modules/api/obsolete.txt" not in archive.namelist()
    assert workspace_path("src/Test.java", environment) == "modules/api/src/Test.java"
    value["base"] = {"repository_id": 2}
    value["overlays"].append({"source": "src", "target": "other"})
    with pytest.raises(ServiceCheckError, match="MAPPING_INVALID"):
        validate_profile(value)


@pytest.mark.asyncio
async def test_check_replay_retains_one_job_and_foreign_owner_cannot_read_it(tmp_path):
    store = LiveStore(tmp_path / "live.db")
    p = project(store)
    service = LiveService(store)
    environments = ProjectEnvironment(service)
    await environments.save("alice", p["project_id"], 0, profile())
    environment = environments.freeze("alice", p["project_id"])
    environments.prepare_check = AsyncMock()
    identity = str(uuid4())
    first = await environments.begin_check("alice", p["project_id"], identity, environment["digest"])
    second = await environments.begin_check("alice", p["project_id"], identity, environment["digest"])
    await environments.tasks[identity]
    assert first == second and environments.prepare_check.await_count == 1
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        environments.check_read("bob", p["project_id"], identity)

# ruff: noqa: INP001, S101
"""Local source isolation, revision pinning, and hostile browser references."""

from uuid import uuid4

import pytest

from langflow.adlc.local_projects import (
    LocalProjectError,
    checked_folder,
    git_at,
    inspect_local_project,
    list_local_folders,
    prepare_project_source,
    snapshot_path,
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_ROOTS", str(tmp_path))
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_SOURCE_ROOT", str(tmp_path / "snapshots"))
    source = tmp_path / "source"
    source.mkdir()
    git_at(source, "init", "-q")
    (source / "README.md").write_text("committed\n", encoding="utf-8")
    git_at(source, "add", ".")
    git_at(source, "-c", "user.name=Check", "-c", "user.email=check@example.invalid", "commit", "-qm", "base")
    return source


def test_committed_snapshot_preserves_dirty_working_folder_and_old_revision(project):
    commit = git_at(project, "rev-parse", "HEAD")
    (project / "README.md").write_text("developer changes\n", encoding="utf-8")
    (project / "untracked.txt").write_text("local only", encoding="utf-8")
    project_id = uuid4()
    assert inspect_local_project(project_id, "Project", str(project)).uncommitted_changes
    reference = prepare_project_source(project_id, "Project", str(project))
    snapshot = snapshot_path(reference)
    assert (snapshot / "README.md").read_text() == "committed\n"
    assert not (snapshot / "untracked.txt").exists()
    assert git_at(snapshot, "remote") == ""
    assert (project / "README.md").read_text() == "developer changes\n"
    git_at(project, "add", "README.md")
    git_at(project, "-c", "user.name=Check", "-c", "user.email=check@example.invalid", "commit", "-qm", "next")
    newer = prepare_project_source(project_id, "Project", str(project))
    assert newer["base_commit"] != commit
    assert reference["base_commit"] == commit
    assert git_at(snapshot, "rev-parse", "HEAD") == commit
    assert (snapshot_path(newer) / "README.md").read_text() == "developer changes\n"


def test_folder_listing_and_non_git_readiness(project):
    (project / "subfolder").mkdir()
    (project / ".hidden").mkdir()
    listing = list_local_folders(str(project))
    assert [item.name for item in listing.folders] == ["subfolder"]
    read = inspect_local_project(uuid4(), "Nested", str(project / "subfolder"))
    assert not read.ready
    assert "root folder" in read.message
    empty = project.parent / "empty"
    empty.mkdir()
    git_at(empty, "init", "-q")
    assert not inspect_local_project(uuid4(), "Empty", str(empty)).ready
    with pytest.raises(LocalProjectError, match="initial Git commit"):
        prepare_project_source(uuid4(), "Empty", str(empty))


@pytest.mark.parametrize("value", ["relative/path", "\0", "", "../source"])
@pytest.mark.usefixtures("project")
def test_rejects_nonabsolute_and_malformed_folder_paths(value):
    with pytest.raises(LocalProjectError):
        checked_folder(value)


def test_rejects_paths_outside_configured_locations(project):
    with pytest.raises(LocalProjectError) as error:
        checked_folder(str(project.parent.parent))
    assert error.value.code == "LOCAL_FOLDER_NOT_ALLOWED"


@pytest.mark.parametrize(
    "change", [{"project_id": "../escape"}, {"base_commit": "HEAD"}, {"source_ref": "../../escape"}]
)
def test_rejects_untrusted_snapshot_references(project, change):
    reference = prepare_project_source(uuid4(), "Project", str(project))
    with pytest.raises(LocalProjectError) as error:
        snapshot_path({**reference, **change})
    assert error.value.code == "LOCAL_PROJECT_REFERENCE_INVALID"


def test_rejects_corrupt_cached_revision(project):
    reference = prepare_project_source(uuid4(), "Project", str(project))
    cached = snapshot_path(reference)
    (cached / "README.md").write_text("changed cache\n", encoding="utf-8")
    git_at(cached, "add", ".")
    git_at(cached, "-c", "user.name=Check", "-c", "user.email=check@example.invalid", "commit", "-qm", "tampered")
    with pytest.raises(LocalProjectError) as error:
        prepare_project_source(reference["project_id"], "Project", str(project))
    assert error.value.code == "LOCAL_PROJECT_SNAPSHOT_INVALID"

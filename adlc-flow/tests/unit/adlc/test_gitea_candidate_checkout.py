import os
import subprocess

import pytest

from langflow.adlc.gitea_projects import prepare_candidate
from langflow.adlc.vai_services import ServiceCheckError


def run_git(folder, *args):
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.autocrlf=false", "-C", str(folder), *args],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def commit(folder, text):
    (folder / "source.txt").write_text(text, encoding="utf8")
    run_git(folder, "add", "source.txt")
    run_git(folder, "-c", "user.name=Fixture", "-c", "user.email=fixture@localhost.invalid", "commit", "-m", text)
    return run_git(folder, "rev-parse", "HEAD")


def test_candidate_fetches_reviewed_commit_missing_from_cached_branch(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    run_git(upstream, "init", "--initial-branch=main")
    original = commit(upstream, "original")
    cache = tmp_path / "cache"
    run_git(tmp_path, "clone", "--no-local", "--no-checkout", str(upstream), str(cache))
    reviewed = commit(upstream, "reviewed")
    commit(upstream, "newer unapproved change")
    # A cache fetch acquires new objects without advancing its frozen main ref.
    run_git(cache, "fetch", str(upstream), "main")
    assert run_git(cache, "rev-parse", "HEAD") == original

    candidate = tmp_path / "candidate"
    prepare_candidate(str(cache), reviewed, candidate)

    assert run_git(candidate, "rev-parse", "HEAD") == reviewed
    assert (candidate / "source.txt").read_text() == "reviewed"
    assert run_git(cache, "rev-parse", "HEAD") == original
    assert run_git(candidate, "status", "--porcelain") == ""


def test_candidate_requires_an_immutable_commit_id(tmp_path):
    with pytest.raises(ServiceCheckError) as error:
        prepare_candidate(str(tmp_path / "source"), "main", tmp_path / "candidate")
    assert error.value.code == "PROJECT_SOURCE_REVISION_INVALID"
    assert not (tmp_path / "candidate").exists()

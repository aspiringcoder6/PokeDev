from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import subprocess

from fastapi import HTTPException, Response
import pytest

from langflow.adlc import project_source
from langflow.adlc.vai_services import ServiceCheckError
from langflow.api.v1 import adlc_project_lifecycle as api


def test_index_reads_only_regular_files_at_bound_commit_without_secret_names(tmp_path):
    def git(*args, input=None):
        return subprocess.run(["git", "-C", str(tmp_path), *args], input=input, capture_output=True, check=True).stdout.decode().strip()
    git("init")
    git("config", "user.name", "Canvas test")
    git("config", "user.email", "canvas@example.invalid")
    for name in ["src/app.ts", "tests/test_existing.py", ".env.local", "keys/private-key.pem", "node_modules/a.js", "readme.md"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source", encoding="utf8")
    git("add", "-f", ".")
    blob = git("hash-object", "-w", "--stdin", input=b"../outside-secret")
    git("update-index", "--add", "--cacheinfo", f"120000,{blob},outside-link")
    git("commit", "-m", "Bound source")
    commit = git("rev-parse", "HEAD")
    # Working tree edits must not change what is offered for the saved project revision.
    (tmp_path / "src/app.ts").unlink()
    (tmp_path / "untracked.ts").write_text("not in source")
    project = {"project_id": str(uuid4()), "source_path": str(tmp_path), "base_commit": commit}
    result = project_source.project_file_index(project)
    assert result == {"project_id": project["project_id"], "commit": commit, "paths": ["readme.md", "src/app.ts", "tests/test_existing.py"], "truncated": False}
    assert "source_path" not in result


def test_index_bounds_large_trees_and_rejects_revision_options(monkeypatch):
    read = Mock(return_value="\0".join(f"100644 blob {'b'*40}\tsrc/file{i}.ts" for i in range(20002)))
    monkeypatch.setattr(project_source, "git", read)
    result = project_source.project_file_index({"project_id": "p", "source_path": "private-cache", "base_commit": "a"*40})
    assert len(result["paths"]) == 20000 and result["truncated"]
    with pytest.raises(ServiceCheckError):
        project_source.project_file_index({"project_id": "p", "source_path": "private-cache", "base_commit": "--all"})
    assert read.call_count == 1


@pytest.mark.asyncio
async def test_file_picker_checks_project_read_permission_before_accessing_git(monkeypatch):
    read = Mock()
    authorize = AsyncMock(side_effect=ServiceCheckError("LIVE_PROJECT_NOT_FOUND", 404))
    monkeypatch.setattr(api, "live_service", lambda: object())
    monkeypatch.setattr(api, "authorize_project", authorize)
    monkeypatch.setattr(project_source, "project_file_index", read)
    session, actor, identity = AsyncMock(), SimpleNamespace(id=uuid4()), uuid4()
    with pytest.raises(HTTPException) as denied:
        await api.project_files(identity, session, actor, Response())
    assert denied.value.status_code == 404
    read.assert_not_called()
    project = {"project_id": str(identity)}
    authorize.side_effect = None
    authorize.return_value = project
    read.return_value = {"paths": []}
    response = Response()
    assert await api.project_files(identity, session, actor, response) == {"paths": []}
    session.commit.assert_awaited_once()
    read.assert_called_once_with(project)
    assert response.headers["Cache-Control"] == "no-store"

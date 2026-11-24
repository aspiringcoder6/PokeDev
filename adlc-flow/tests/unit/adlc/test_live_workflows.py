import copy
import json
from uuid import uuid4

import pytest

from langflow.adlc.live_workflows import LiveService, LiveStore, safe_path, validate_plan
from langflow.adlc.vai_services import ServiceCheckError


def plan():
    return {"tasks": [
        {"id": "UI", "title": "Thêm giao diện tạo ghi chú", "kind": "implement", "depends_on": [], "write_paths": ["index.html"], "steps": ["Xây form nhập và danh sách ghi chú"], "acceptance": ["Người dùng thêm được ghi chú"]},
        {"id": "TEST", "title": "Viết test độc lập theo spec ghi chú", "kind": "test", "depends_on": [], "write_paths": ["tests/test_notes.py"], "steps": ["Kiểm tra từng tiêu chí của spec"], "acceptance": ["Không bỏ qua assertion nghiệp vụ"]},
        {"id": "REVIEW", "title": "Đối chiếu toàn bộ source với spec", "kind": "review", "depends_on": ["UI", "TEST"], "write_paths": [], "steps": ["Đọc source và kiểm tra phạm vi"], "acceptance": ["Không thay đổi test đã đóng băng"]}],
        "commands": [{"label": "Unit tests", "argv": ["python", "-m", "unittest", "discover", "-s", "tests"]}],
        "preview": {"path": "."}, "browser_checks": [{"label": "Mở trang ghi chú", "steps": [{"action": "goto", "path": "/"}, {"action": "text", "text": "Ghi chú"}]}]}


def test_generic_plan_accepts_parallel_branches_and_requires_real_dependencies():
    original = plan()
    approved = validate_plan(original)
    assert approved["max_parallel"] == 2 and len(approved["tasks"]) == 3
    assert validate_plan(copy.deepcopy(approved))["digest"] == approved["digest"]
    cycle = plan(); cycle["tasks"][0]["depends_on"] = ["REVIEW"]
    with pytest.raises(ValueError, match="DAG_INVALID"):
        validate_plan(cycle)
    conflict = plan(); conflict["tasks"][1]["write_paths"] = ["index.html"]
    with pytest.raises(ValueError, match="WRITE_CONFLICT"):
        validate_plan(conflict)


@pytest.mark.parametrize("bad", ["../file", "/etc/passwd", "C:/data", ".env", "src/.env.local", "src/../../x", ".git/config", "x\\y"])
def test_plan_never_grants_an_escaping_or_secret_path(bad):
    assert not safe_path(bad)
    value = plan(); value["tasks"][0]["write_paths"] = [bad]
    with pytest.raises(ValueError, match="WRITE_PATH"):
        validate_plan(value)


def test_plan_digest_covers_tests_preview_and_acceptance():
    approved = validate_plan(plan())["digest"]
    for mutate in [lambda v: v["commands"][0]["argv"].append("-v"), lambda v: v["tasks"][0]["acceptance"].append("Lưu dữ liệu sau tải lại"), lambda v: v["preview"].update(path="public")]:
        changed = plan(); mutate(changed)
        assert validate_plan(changed)["digest"] != approved
    invalid = plan(); invalid["browser_checks"][0]["steps"][0]["path"] = "//external.example/"
    with pytest.raises(ValueError, match="BROWSER_CHECK"):
        validate_plan(invalid)


def project(store, owner="alice", repo_id=1):
    return store.save_project(owner, str(uuid4()), {"id": repo_id, "name": "notes", "full_name": "admin/notes", "html_url": "http://gitea/admin/notes"}, "/private/source", "a" * 40)


def test_runs_are_idempotent_owner_and_project_scoped_and_keep_history(tmp_path):
    store = LiveStore(tmp_path / "runs.db")
    first_project = project(store)
    identity = str(uuid4())
    first, fresh = store.create("alice", first_project, "delivery", identity, "Yêu cầu bất kỳ", "Ghi chú", "a" * 40)
    assert fresh
    assert store.create("alice", first_project, "delivery", identity, "Yêu cầu bất kỳ", "Ghi chú", "a" * 40) == (first, False)
    with pytest.raises(ServiceCheckError, match="CONFLICT"):
        store.create("bob", first_project, "delivery", identity, "Yêu cầu bất kỳ", "Ghi chú", "a" * 40)
    with pytest.raises(ServiceCheckError, match="ACTIVE"):
        store.create("alice", first_project, "other", str(uuid4()), "Khác", "Khác", "a" * 40)
    assert store.runs("bob") == []
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        store.get("bob", identity)
    other_project = project(store, repo_id=2)
    other, _ = store.create("alice", other_project, "other", str(uuid4()), "Tạo danh bạ", "Danh bạ", "b" * 40)
    store.update(identity, {"state": "FAILED", "checks": [{"id": "actual-failure"}]})
    second, _ = store.create("alice", first_project, "next", str(uuid4()), "Cải thiện tìm kiếm", "Tìm kiếm", "a" * 40)
    restarted = LiveStore(store.path)
    assert len(restarted.runs("alice")) == 3
    assert len(restarted.runs("alice", first_project["project_id"])) == 2
    assert restarted.get("alice", identity)["checks"] == [{"id": "actual-failure"}]
    assert second["scope_id"] == first["scope_id"] != other["scope_id"]


def test_success_needs_bound_runner_proof_not_an_agent_claim(tmp_path, monkeypatch):
    import langflow.adlc.live_workflows as module
    monkeypatch.setattr(module, "DATA", tmp_path)
    store = LiveStore(tmp_path / "runs.db"); p = project(store)
    row, _ = store.create("alice", p, "delivery", str(uuid4()), "Xây sản phẩm", "Sản phẩm", "a" * 40)
    row = store.update(row["run_id"], {"phase": "execution", "approved_plan_digest": "b" * 64})
    directory = tmp_path / "runs" / row["run_id"] / "execution"; directory.mkdir(parents=True)
    result = {k: row[k] for k in ("run_id", "scope_id", "phase")}
    result.update(state="SUCCEEDED", nodes=[{"id": "UI", "state": "DONE"}], changed_files=["index.html"], file_hashes={"index.html": "c" * 64}, source_sha256="d" * 64, verification={"passed": True, "source_sha256": "d" * 64})
    file = directory / "result.json"; file.write_text(json.dumps(result))
    service = LiveService(store)
    assert service.observe(row)["state"] == "UNCONFIRMED"
    result["verification"].update(protected_intact=True, binding_verified=True, plan_digest="b" * 64)
    file.write_text(json.dumps(result))
    assert service.observe(row)["state"] == "SUCCEEDED"
    result["scope_id"] = "foreign"; file.write_text(json.dumps(result))
    assert service.observe(row)["state"] == "UNCONFIRMED"


@pytest.mark.asyncio
@pytest.mark.parametrize("alternate", [None, {"provider": "alternate", "model": "verified-model"}])
async def test_retry_is_a_new_scoped_run_and_replay_never_dispatches_twice(tmp_path, monkeypatch, alternate):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from langflow.api.v1 import adlc_live as api
    from uuid import UUID
    owner = str(uuid4()); store = LiveStore(tmp_path / "live.db"); p = project(store, owner)
    row, _ = store.create(owner, p, str(uuid4()), str(uuid4()), "Yêu cầu theo repo", "Lượt nguồn", "a" * 40)
    approved = validate_plan(plan())
    store.update(row["run_id"], {"state": "FAILED", "phase": "execution", "plan": approved, "approved_plan_digest": approved["digest"], "documents": [{"id": "SPEC", "body": "spec"}]})
    service = LiveService(store); service.spawn = Mock()
    monkeypatch.setattr(api, "live_service", lambda: service)
    monkeypatch.setattr(api, "source", AsyncMock(return_value=(object(), object())))
    monkeypatch.setattr(api, "permission", AsyncMock(return_value=True))
    monkeypatch.setattr(api, "validated_execution_model", AsyncMock(return_value=alternate))
    command = api.RetryCommand(run_id=uuid4(), model_route=alternate); actor = SimpleNamespace(id=UUID(owner))
    first = await api.retry_run(UUID(row["run_id"]), command, AsyncMock(), actor)
    second = await api.retry_run(UUID(row["run_id"]), command, AsyncMock(), actor)
    assert first["run_id"] == second["run_id"] != row["run_id"]
    assert first["parent_run_id"] == row["run_id"] and first["approved_plan_digest"] == approved["digest"]
    assert first.get("model_route") == alternate
    assert store.get(owner, row["run_id"])["state"] == "FAILED"
    assert service.spawn.call_count == 1
    with pytest.raises(api.HTTPException) as denied:
        await api.retry_run(UUID(row["run_id"]), api.RetryCommand(run_id=uuid4()), AsyncMock(), SimpleNamespace(id=uuid4()))
    assert denied.value.status_code == 404


def test_git_timeout_terminates_helpers_that_inherit_its_pipes(tmp_path):
    import os
    import subprocess
    import sys
    import time
    import psutil
    from langflow.adlc.gitea_projects import bounded_process

    marker = tmp_path / "helper.pid"
    script = (
        "import subprocess,sys,time,pathlib; "
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_process([sys.executable, "-c", script, str(marker)], dict(os.environ), 1)
    assert time.monotonic() - started < 6
    assert marker.exists()
    helper_pid = int(marker.read_text())
    assert not psutil.pid_exists(helper_pid) or psutil.Process(helper_pid).status() == psutil.STATUS_ZOMBIE


@pytest.mark.asyncio
async def test_reconciliation_only_reads_native_contracts_bound_to_this_run():
    from unittest.mock import AsyncMock
    from langflow.api.v1.adlc_live import scoped_contracts

    client = AsyncMock()
    client.http_get.return_value = {"nodes": [{"id": "T01", "workspace": "/scoped/run/T01"}, {"id": "T02", "workspace": "/scoped/run/T02"}]}
    client.get_task.return_value = {"status": "DONE"}
    row = {"run_id": str(uuid4()), "phase": "execution", "scope_id": "a" * 64, "nodes": [{"id": "T01", "session_id": "owned"}, {"id": "T02", "state": "PENDING"}]}
    assert await scoped_contracts(client, row) == [{"status": "DONE"}]
    client.get_task.assert_awaited_once_with("/scoped/run/T01", "1")
    client.list_sessions.assert_not_called()

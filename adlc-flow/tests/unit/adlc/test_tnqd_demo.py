import json
import pytest
from langflow.adlc.tnqd_memory import ProjectDocumentMemory
from langflow.adlc.tnqd_demo import TnqdStore,TnqdService
from langflow.adlc.tnqd_plan import OPERATIONS,validate_plan
from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.tnqd_relay import valid_path

def plan():
    tasks=[]
    for index,op in enumerate(OPERATIONS):
        deps=[] if index==0 else ["T00"] if index<7 else [f"T{i:02}" for i in range(1,7)] if index==7 else [f"T{index-1:02}"]
        if op=="patch.race":deps=["T01"]
        tasks.append({"id":f"T{index:02}","operation":op,"title":"Cải tiến tra cứu danh sách nhân sự "+op,"role":"BA","depends_on":deps,"steps":["Đọc snapshot tài liệu nghiệp vụ đã khóa","Thực hiện công việc trong phạm vi file","Xuất artifact và đối chiếu điều kiện"],"inputs":["Spec có nguồn"],"outputs":["Artifact ràng buộc task"],"acceptance":["Đầu vào được đối chiếu digest","Kết quả có nguồn kiểm tra độc lập"],"requirements":[f"AC{i:02}" for i in range(1,13)]})
    return {"title":"Kế hoạch chi tiết pilot TNQD","summary":"Các nhánh độc lập và phụ thuộc artifact được kiểm tra trước khi cho phép thực hiện.","tasks":tasks}

def test_plan_requires_real_dag_join_and_independent_branches():
    value=plan();assert len(validate_plan(value)["tasks"])==17
    value["tasks"][7]["depends_on"]=["T01"]
    with pytest.raises(ValueError,match="REQUIRED_DEPENDENCY"):validate_plan(value)
    value=plan();value["tasks"][4]["depends_on"]=["T01"]
    with pytest.raises(ValueError,match="INDEPENDENT"):validate_plan(value)
    value=plan();value["tasks"][0]["depends_on"]=["T16"]
    with pytest.raises(ValueError,match="CYCLE"):validate_plan(value)

def test_memory_is_versioned_scoped_and_readable_in_a_new_context_after_restart(tmp_path):
    path=tmp_path/"memory.sqlite3";memory=ProjectDocumentMemory(path)
    first=memory.publish("project-a","PTYC","v1","Nghiệp vụ có nguồn","source@commit")
    second=ProjectDocumentMemory(path).read("project-a","PTYC","v1","new-agent-context")
    assert first["sha256"]==second["sha256"] and first["retrieval_id"]!=second["retrieval_id"]
    assert second["body"]=="Nghiệp vụ có nguồn" and not second["durable_graph_verified"]
    with pytest.raises(ValueError,match="NOT_FOUND"):memory.read("project-b","PTYC","v1","intruder")
    with pytest.raises(ValueError,match="CONFLICT"):memory.publish("project-a","PTYC","v1","Thay đổi nội dung","source")
    assert memory.publish("project-a","PTYC","v2","Nội dung bổ sung được kiểm chứng","verified-source")["revision"]=="v2"
    assert memory.read("project-a","PTYC","v1","audit")["body"]=="Nghiệp vụ có nguồn"
    assert ProjectDocumentMemory(path).latest("project-a","PTYC","next-loop")["revision"]=="v2"
    assert memory.latest("project-b","PTYC","intruder") is None
    assert memory.latest("project-a","PTYC","new-ba",verified_only=True) is None

def test_intent_replay_is_exact_and_cannot_cross_owner_or_duplicate_active_run(tmp_path):
    store=TnqdStore(tmp_path/"runs.sqlite3")
    row,fresh=store.create("owner","delivery","cycle","run","goal");assert fresh
    assert store.create("owner","delivery","cycle","run","goal")== (row,False)
    with pytest.raises(ServiceCheckError,match="CONFLICT"):store.create("intruder","delivery","cycle","run","goal")
    with pytest.raises(ServiceCheckError,match="ACTIVE"):store.create("owner","delivery","cycle","new","goal")
    assert store.list("intruder","delivery","cycle")==[]

def test_reset_preserves_old_receipts_and_memory_but_new_run_starts_empty(tmp_path):
    import sqlite3
    store = TnqdStore(tmp_path / "runs.sqlite3")
    original, _ = store.create("owner", "delivery", "cycle", "old-run", "goal")
    store.update("old-run", {"state": "SUCCEEDED", "nodes": [{"id": "T01", "state": "DONE"}], "checks": [{"passed": 13}]})
    memory = ProjectDocumentMemory(tmp_path / "memory.sqlite3")
    memory.publish(original["scope_id"], "PTYC", "v1", "Ngữ cảnh nghiệp vụ được giữ lại", "business-source")
    artifact = tmp_path / "old-source.patch"
    artifact.write_text("verified patch", encoding="utf8")

    assert store.reset("owner", "delivery", "cycle", "old-run")["archived_run_ids"] == ["old-run"]
    assert store.list("owner", "delivery", "cycle") == []
    with sqlite3.connect(store.path) as db:
        saved = json.loads(db.execute("SELECT payload FROM tnqd_runs WHERE id='old-run'").fetchone()[0])
    assert saved["state"] == "SUCCEEDED" and saved["checks"] == [{"passed": 13}] and saved["archived_at"]
    assert artifact.read_text(encoding="utf8") == "verified patch"
    assert memory.read(original["scope_id"], "PTYC", "v1", "next-run")["body"] == "Ngữ cảnh nghiệp vụ được giữ lại"
    assert store.reset("owner", "delivery", "cycle", "old-run")["archived_run_ids"] == []
    with pytest.raises(ServiceCheckError, match="ARCHIVED"):
        store.create("owner", "delivery", "cycle", "old-run", "goal")
    with pytest.raises(ServiceCheckError, match="ARCHIVED"):
        store.get("owner", "delivery", "cycle", "old-run")
    new, fresh = store.create("owner", "delivery", "cycle", "new-run", "goal")
    assert fresh and new["state"] == "PLANNING" and new["scope_id"] == original["scope_id"]
    assert new["nodes"] == new["events"] == new["documents"] == [] and "checks" not in new
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        store.reset("owner", "delivery", "cycle", "old-run")

@pytest.mark.parametrize("state", ["PLANNING", "RUNNING", "UNCONFIRMED"])
def test_reset_cannot_hide_active_or_unconfirmed_runs_even_in_another_cycle(tmp_path, state):
    store = TnqdStore(tmp_path / "runs.sqlite3")
    store.create("owner", "delivery", "cycle", "finished", "goal")
    store.update("finished", {"state": "SUCCEEDED"})
    store.create("owner", "delivery", "other-cycle", "active", "goal")
    store.update("active", {"state": state})
    with pytest.raises(ServiceCheckError, match="ACTIVE"):
        store.reset("owner", "delivery", "cycle", "finished")
    assert len(store.list("owner", "delivery", "cycle")) == 1

def test_reset_is_scoped_to_owner_delivery_and_cycle(tmp_path):
    store = TnqdStore(tmp_path / "runs.sqlite3")
    store.create("owner", "delivery", "cycle", "run", "goal")
    store.update("run", {"state": "SUCCEEDED"})
    for owner, delivery, cycle in [("intruder", "delivery", "cycle"), ("owner", "other", "cycle"), ("owner", "delivery", "other")]:
        with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
            store.reset(owner, delivery, cycle, "run")
    assert store.get("owner", "delivery", "cycle", "run")["state"] == "SUCCEEDED"

def test_engine_success_without_independent_checks_is_rejected(tmp_path):
    store=TnqdStore(tmp_path/"runs.sqlite3");row,_=store.create("o","d","c","r","goal")
    row=store.update("r",{"phase":"execution","plan":validate_plan(plan())})
    directory=tmp_path/"results/r/execution";directory.mkdir(parents=True)
    result={k:row[k] for k in ("run_id","scope_id","phase")};result.update(state="SUCCEEDED",nodes=[{"id":t["id"],"state":"DONE"} for t in row["plan"]["tasks"]])
    (directory/"result.json").write_text(json.dumps(result))
    assert TnqdService(store,tmp_path/"results").observe(row)["state"]=="UNCONFIRMED"

def test_preview_relay_blocks_cross_host_and_encoded_path_escape():
    assert valid_path("/main-123.js") and valid_path("/api/military-youth/youths/filter?page=0&keyword=DEMO-AN")
    for path in ("//evil.local/","http://evil.local/","/%2e%2e/.env","/assets/../../secret","/\\secret"):
        assert not valid_path(path)

@pytest.mark.asyncio
async def test_resume_checks_resource_owner_before_observing_agents_or_starting_worker(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException,Response
    from uuid import uuid4
    from langflow.api.v1 import adlc_tnqd_demo as api
    monkeypatch.setattr(api,"source",AsyncMock(side_effect=HTTPException(404)))
    monkeypatch.setattr(api,"tnqd_service",lambda:pytest.fail("Unauthorized worker access"))
    with pytest.raises(HTTPException):
        await api.resume(uuid4(),api.PlanCommand(cycle_id=uuid4(),run_id=uuid4()),AsyncMock(),object(),Response())

def test_demo_reset_is_not_exposed_as_a_public_operation():
    from langflow.api.v1.adlc_tnqd_demo import router
    assert all(not route.path.endswith("/reset") for route in router.routes)

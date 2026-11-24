import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from langflow.adlc.live_workflows import LiveService, LiveStore, validate_plan
from langflow.adlc.project_workflows import compile_workflow, planning_plan, workflow_snapshot, workflow_status
from langflow.adlc.vai_services import ServiceCheckError


def graph():
    tasks = [
        {"id": "DEV", "kind": "implement", "title": "Repair the offline counter function", "steps": ["Return the next integer from the existing function"], "acceptance": ["Protected counter tests pass without modifications"], "write_paths": ["counter.mjs"]},
        {"id": "TEST", "kind": "test", "title": "Write independent page wiring tests", "steps": ["Test the HTML module wiring using Python unittest"], "acceptance": ["The counter button and module import are present"], "write_paths": ["tests/test_page.py"]},
        {"id": "REVIEW", "kind": "review", "title": "Review the result against the requirement", "steps": ["Compare the source, baseline and verification receipt"], "acceptance": ["Only the approved paths have changed"], "write_paths": []},
    ]
    return {"version": 1, "title": "Counter workflow", "summary": "Repair, test and review the counter.",
            "nodes": [{"id": t["id"], "task": t, "position": {"x": i * 200, "y": 10}} for i, t in enumerate(tasks)],
            "edges": [{"source": "DEV", "target": "REVIEW"}, {"source": "TEST", "target": "REVIEW"}],
            "commands": [{"label": "Node tests", "argv": ["node", "--test", "tests/test_counter.mjs"], "timeout": 90}],
            "preview": {"path": "."}, "browser_checks": [{"label": "Increment", "steps": [{"action": "goto", "path": "/"}, {"action": "click", "selector": "#increment"}]}]}


def setup_store(tmp_path):
    store = LiveStore(tmp_path / "live.db")
    owner, project_id = str(uuid4()), str(uuid4())
    project = store.save_project(owner, project_id, {"id": 1, "name": "counter", "full_name": "admin/counter", "html_url": "http://localhost:3001/admin/counter"}, "/private/source", "a" * 40)
    workflow = store.save_workflow(owner, str(uuid4()), project_id, "Counter", graph())
    return store, owner, project, workflow


def test_canvas_edges_are_authoritative_and_checks_survive_compilation():
    value = graph()
    value["nodes"][0]["task"]["depends_on"] = ["FORGED"]
    original = copy.deepcopy(value)
    plan = compile_workflow(value)
    assert plan["tasks"][0]["depends_on"] == []
    assert plan["tasks"][2]["depends_on"] == ["DEV", "TEST"]
    assert plan["commands"] == value["commands"] and plan["browser_checks"] == value["browser_checks"]
    assert plan["preview"] == value["preview"] and value == original
    moved = copy.deepcopy(value); moved["nodes"][0]["position"]["x"] += 100
    assert compile_workflow(moved)["digest"] == plan["digest"]
    moved["nodes"][0]["task"]["acceptance"].append("Handle negative input integers correctly")
    assert compile_workflow(moved)["digest"] != plan["digest"]


@pytest.mark.parametrize("edge", [{"source": "REVIEW", "target": "DEV"}, {"source": "MISSING", "target": "TEST"}, {"source": "DEV", "target": "DEV"}, {"source": "DEV", "target": "REVIEW"}])
def test_invalid_dependencies_cannot_become_runnable(edge):
    value = graph(); value["edges"].append(edge)
    assert workflow_status(value)[1] == "LIVE_PLAN_DAG_INVALID"


def test_drafts_are_persisted_but_cannot_run_and_saves_have_conflict_detection(tmp_path):
    store, owner, project, workflow = setup_store(tmp_path)
    draft = graph(); draft["nodes"][0]["task"]["write_paths"] = []
    saved = store.save_workflow(owner, workflow["workflow_id"], project["project_id"], "Draft", draft, workflow["digest"])
    assert saved["revision"] == 2
    assert workflow_status(store.workflow(owner, workflow["workflow_id"])["graph"])[1] == "LIVE_PLAN_WRITE_PATH"
    with pytest.raises(ValueError, match="WRITE_PATH"):
        workflow_snapshot(saved)
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        store.save_workflow(owner, workflow["workflow_id"], project["project_id"], "Stale tab", graph(), workflow["digest"])
    assert store.workflow(owner, workflow["workflow_id"])["name"] == "Draft"
    assert store.workflows("other") == []
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        store.workflow("other", workflow["workflow_id"])
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        store.save_workflow("other", workflow["workflow_id"], project["project_id"], "Foreign", graph())


@pytest.mark.asyncio
async def test_selected_workflow_bypasses_planner_and_is_immutable_per_run(tmp_path):
    store, owner, project, workflow = setup_store(tmp_path)
    snapshot = workflow_snapshot(workflow)
    generate = AsyncMock()
    assert (await planning_plan(snapshot, generate))["digest"] == compile_workflow(graph())["digest"]
    generate.assert_not_called()
    row, _ = store.create(owner, project, "delivery", str(uuid4()), "Repair counter", "Counter", "a" * 40, snapshot)
    changed = graph(); changed["nodes"][0]["task"]["write_paths"] = ["other.js"]
    store.save_workflow(owner, workflow["workflow_id"], project["project_id"], "Changed template", changed, workflow["digest"])
    assert store.get(owner, row["run_id"])["workflow"] == snapshot
    tampered = copy.deepcopy(snapshot); tampered["plan"]["tasks"][0]["write_paths"] = ["secret.js"]
    with pytest.raises(ValueError, match="CHANGED"):
        await planning_plan(tampered, generate)
    automatic = AsyncMock(return_value=compile_workflow(graph()))
    assert (await planning_plan(None, automatic))["digest"] == snapshot["plan"]["digest"]
    automatic.assert_awaited_once()


def test_edit_before_approval_rejects_old_approval_and_late_planner_observations(tmp_path, monkeypatch):
    from langflow.adlc import live_workflows as module
    monkeypatch.setattr(module, "DATA", tmp_path)
    store, owner, project, workflow = setup_store(tmp_path)
    original = compile_workflow(graph())
    row, _ = store.create(owner, project, "delivery", str(uuid4()), "Repair counter", "Counter", "a" * 40)
    row = store.update(row["run_id"], {"state": "PLAN_READY", "plan": original, "documents": [{"id": "SPEC"}]})
    stale = copy.deepcopy(row)
    new_graph = graph(); new_graph["edges"].append({"source": "DEV", "target": "TEST"})
    saved = store.save_workflow(owner, workflow["workflow_id"], project["project_id"], "Sequential", new_graph, workflow["digest"])
    snapshot = workflow_snapshot(saved)
    revised = store.revise_plan(owner, row["run_id"], original["digest"], snapshot)
    assert revised["plan"]["digest"] != original["digest"]
    directory = tmp_path / "runs" / row["run_id"] / "planning"; directory.mkdir(parents=True)
    (directory / "result.json").write_text(json.dumps({**{k: row[k] for k in ("run_id", "scope_id", "phase")}, "state": "PLAN_READY", "plan": original, "documents": [{"id": "SPEC"}]}))
    service = LiveService(store)
    assert service.observe(stale)["plan"] == snapshot["plan"]
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        store.begin_execution(owner, row["run_id"], original["digest"])
    accepted, fresh = store.begin_execution(owner, row["run_id"], revised["plan"]["digest"])
    assert fresh and accepted["approved_plan_digest"] == revised["plan"]["digest"]
    assert service.observe(stale)["state"] == "RUNNING"
    assert store.begin_execution(owner, row["run_id"], revised["plan"]["digest"])[1] is False
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        store.revise_plan(owner, row["run_id"], revised["plan"]["digest"], snapshot)


@pytest.mark.asyncio
async def test_api_freezes_only_matching_project_and_version_before_dispatch(tmp_path, monkeypatch):
    from langflow.api.v1 import adlc_live as api
    store, owner, project, workflow = setup_store(tmp_path)
    service = LiveService(store); service.spawn = Mock()
    monkeypatch.setattr(api, "live_service", lambda: service)
    monkeypatch.setattr(api, "source", AsyncMock(return_value=(SimpleNamespace(requirement="Repair the existing counter", title="Counter"), SimpleNamespace(folder_id=UUID(project["project_id"])))))
    monkeypatch.setattr(api, "permission", AsyncMock(return_value=True))
    monkeypatch.setattr(api, "Gitea", lambda: SimpleNamespace(repository=AsyncMock(return_value={"id": 1})))
    monkeypatch.setattr(api, "checkout", lambda *args: ("/private/source", "a" * 40))
    actor = SimpleNamespace(id=UUID(owner))
    body = dict(run_id=uuid4(), delivery_id=uuid4(), project_id=project["project_id"], workflow_id=workflow["workflow_id"], workflow_digest=workflow["digest"])
    response = await api.plan(api.PlanCommand(**body), AsyncMock(), actor)
    assert service.spawn.call_args.args[0]["workflow"]["plan"] == compile_workflow(graph())
    assert response["workflow"]["revision"] == 1
    await api.plan(api.PlanCommand(**body), AsyncMock(), actor)
    assert service.spawn.call_count == 1
    with pytest.raises(ServiceCheckError, match="PROJECT_MISMATCH"):
        api.selected_workflow(service, owner, uuid4(), workflow["workflow_id"], workflow["digest"])
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        api.selected_workflow(service, owner, project["project_id"], workflow["workflow_id"], "b" * 64)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        api.selected_workflow(service, "other", project["project_id"], workflow["workflow_id"], workflow["digest"])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_graph", [{"version": 1, "nodes": "not an array"}, {**graph(), "edges": [{"source": ["DEV"], "target": "TEST"}]}])
async def test_api_rejects_malformed_drafts_before_persistence(bad_graph, monkeypatch):
    from langflow.api.v1 import adlc_live as api
    service = SimpleNamespace(store=Mock())
    monkeypatch.setattr(api, "live_service", lambda: service)
    command = api.WorkflowCommand(workflow_id=uuid4(), project_id=uuid4(), name="Draft", graph=bad_graph)
    with pytest.raises(api.HTTPException) as error:
        await api.save_workflow(command.workflow_id, command, SimpleNamespace(id=uuid4()))
    assert error.value.status_code == 422
    service.store.save_workflow.assert_not_called()

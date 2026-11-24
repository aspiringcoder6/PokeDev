import ast
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from langflow.adlc.human_inputs import HumanInputStore
from langflow.adlc.live_workflows import digest, validate_plan
from langflow.adlc.project_workflows import compile_workflow
from langflow.adlc.vai_services import ServiceCheckError
from langflow.adlc.workflow_controls import active_inputs, condition_result, verify_control_result


def controlled_graph(reviewer="human"):
    def task(identity, kind, paths, **extra):
        return {"id": identity, "kind": kind, "title": "Perform the approved task " + identity, "steps": ["Follow the approved requirements"], "acceptance": ["Meet the approved acceptance criteria"], "write_paths": paths, **extra}
    tasks = [task("DEV", "implement", ["app.py"]), task("TEST", "test", ["tests/test_app.py"]),
             task("VERIFY", "review", [], control={"type": "verify"}),
             task("CONDITION", "review", [], control={"type": "condition", "predicate": "verification_passed"}),
             task("GATE", "review", [], control={"type": "gate", "reviewer": reviewer, "max_rounds": 2})]
    return {"version": 2, "title": "Controlled workflow", "summary": "An explicit bounded review loop", "nodes": [{"id": t["id"], "task": t, "position": {"x": i*100, "y": 0}} for i,t in enumerate(tasks)],
        "edges": [{"source": "DEV", "target": "VERIFY"}, {"source": "TEST", "target": "VERIFY"}, {"source": "VERIFY", "target": "CONDITION"}, {"source": "CONDITION", "target": "GATE", "port": "match"}, {"source": "CONDITION", "target": "GATE", "port": "no_match"}, {"source": "GATE", "target": "DEV", "port": "changes_requested", "feedback": True}],
        "commands": [{"label": "Tests", "argv": ["python", "-m", "unittest", "discover"]}], "preview": None, "browser_checks": []}


def test_explicit_feedback_freezes_a_dag_and_the_review_limits():
    graph = controlled_graph(); original = copy.deepcopy(graph)
    plan = compile_workflow(graph)
    assert graph == original and plan["control_flow"]["max_repairs"] == 0
    assert plan["control_flow"]["loops"] == [{"gate": "GATE", "target": "DEV", "nodes": ["DEV", "VERIFY", "CONDITION"], "max_rounds": 2}]
    assert plan["tasks"][0]["depends_on"] == []
    assert validate_plan(copy.deepcopy(plan))["digest"] == plan["digest"]
    tampered = copy.deepcopy(plan); tampered["control_flow"]["loops"][0]["max_rounds"] = 9
    with pytest.raises(ValueError, match="CONTROL_CHANGED"):
        validate_plan(tampered)


@pytest.mark.parametrize("case,code", [("cycle", "DAG_INVALID"), ("missing_branch", "BRANCHES_REQUIRED"), ("wrong_source", "SOURCE_INVALID"), ("unbounded", "LIMIT_INVALID"), ("wrong_target", "LOOP_INVALID"), ("no_tests", "TESTS_REQUIRED"), ("feedback_type", "PORT_INVALID"), ("tester_after_gate", "TESTER_BRANCH_UNSUPPORTED"), ("loop_exit", "LOOP_EXIT")])
def test_invalid_control_plans_fail_before_execution(case, code):
    graph = controlled_graph()
    if case == "cycle": graph["edges"].append({"source": "VERIFY", "target": "DEV"})
    if case == "missing_branch": graph["edges"].pop(4)
    if case == "wrong_source": graph["edges"][2]["source"] = "DEV"
    if case == "unbounded": graph["nodes"][-1]["task"]["control"]["max_rounds"] = 999
    if case == "wrong_target": graph["edges"][-1]["target"] = "TEST"
    if case == "no_tests": graph["edges"].pop(1)
    if case == "feedback_type": graph["edges"][-1]["feedback"] = "true"
    if case == "tester_after_gate":
        graph["edges"].pop(1)
        graph["edges"].append({"source": "GATE", "target": "TEST", "port": "approved"})
    if case == "loop_exit":
        graph["nodes"].append({"id": "OUTSIDE", "task": {**graph["nodes"][-1]["task"], "id": "OUTSIDE", "control": None}, "position": {"x": 0, "y": 0}})
        graph["edges"].append({"source": "DEV", "target": "OUTSIDE"})
    with pytest.raises(ValueError, match=code): compile_workflow(graph)


def test_unknown_verification_is_false_and_branch_join_has_skip_semantics():
    assert condition_result("verification_passed", {})["port"] == "no_match"
    assert condition_result("status_done", {})["port"] == "no_match"
    edges = [{"source": "C", "target": "T", "port": "match"}, {"source": "B", "target": "T"}]
    assert not active_inputs({"id": "T"}, edges, {"C": {"port": "no_match"}, "B": {}})
    assert not active_inputs({"id": "T"}, edges, {"C": {"port": "match"}, "B": {"skipped": True}})
    assert active_inputs({"id": "VISIT", "original_id": "T"}, edges, {"C": {"port": "match"}, "B": {}})
    ordinary = [{"source": "A", "target": "T"}, {"source": "B", "target": "T"}]
    assert active_inputs({"id": "T", "join": "any"}, ordinary, {"A": {"skipped": True}, "B": {}})


def gate_binding(tmp_path, can_approve=True):
    store = HumanInputStore(tmp_path / "questions.db")
    task = {"id": "GATE__R0_test", "original_id": "GATE", "title": "Review the verified candidate", "acceptance": ["Source and tests match"]}
    run = {"owner": "alice", "project_id": "project", "run_id": str(uuid4()), "phase": "execution", "state": "RUNNING", "approved_plan_digest": "p"*64, "title": "Example", "nodes": [{**task, "state": "WAITING_INPUT", "candidate_digest": "s"*64}]}
    question = store.open_gate(run, task, "s"*64, 0, can_approve=can_approve)
    return store, run, task, question


def reply(label="Duyệt kết quả", custom=""):
    return {"answers": [{"id": "gate", "selected": [label], "custom": custom}]}


def test_gate_is_durable_and_answer_is_bound_to_source_plan_owner_and_run(tmp_path):
    store, run, task, q = gate_binding(tmp_path)
    assert HumanInputStore(store.path).open_gate(run, task, "s"*64, 0, can_approve=True)["request_id"] == q["request_id"]
    for change in ({"state": "UNCONFIRMED"}, {"approved_plan_digest": "changed"}, {"nodes": [{**run["nodes"][0], "candidate_digest": "changed"}]}):
        with pytest.raises(ServiceCheckError, match="INPUT_CHANGED"): store.answer_gate("alice", {**run, **change}, q["request_id"], "command", reply())
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"): store.answer_gate("bob", run, q["request_id"], "command", reply())
    answer = store.answer_gate("alice", run, q["request_id"], "command", reply())
    assert answer["gate_decision"] == "approved"
    assert store.answer_gate("alice", run, q["request_id"], "command", reply()) == answer
    retry = {**run, "run_id": str(uuid4())}
    assert store.open_gate(retry, task, "s"*64, 0, can_approve=True)["status"] == "PENDING"


def test_failed_verification_never_offers_approve_and_changes_require_feedback(tmp_path):
    store, run, task, q = gate_binding(tmp_path, can_approve=False)
    with pytest.raises(ServiceCheckError, match="RESPONSE_INVALID"): store.answer_gate("alice", run, q["request_id"], "a", reply())
    with pytest.raises(ServiceCheckError, match="FEEDBACK_REQUIRED"): store.answer_gate("alice", run, q["request_id"], "a", reply("Yêu cầu sửa"))
    assert store.answer_gate("alice", run, q["request_id"], "a", reply("Yêu cầu sửa", "Handle negative inputs"))["gate_decision"] == "changes_requested"


@pytest.mark.asyncio
async def test_local_review_gate_is_answerable_without_a_native_websocket(tmp_path):
    from langflow.adlc.human_inputs import HumanInputMonitor
    store, run, task, q = gate_binding(tmp_path)
    live = SimpleNamespace(store=SimpleNamespace(path=store.path, get=lambda *_: run), observe=lambda r: r)
    monitor = HumanInputMonitor(live)
    monitor.ready = AsyncMock(side_effect=AssertionError("Local gate must not depend on native questions channel"))
    assert monitor.pending("alice")[0]["can_respond"]
    result = await monitor.answer("alice", run, q["request_id"], "reply", reply())
    assert result["status"] == "ANSWERED"
    monitor.ready.assert_not_awaited()


def worker_class(tmp_path):
    """Exercise production Driver methods without starting a real remote session."""
    root = Path(__file__).resolve().parents[4]
    tree = ast.parse((root / "integration-sources/workloop/project_worker.py").read_text(encoding="utf8"))
    selected = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in {"Driver", "update", "sha"}]
    snap = {"nodes": [], "events": [], "verification": {"passed": True}}
    space = {"asyncio": asyncio, "json": json, "time": __import__("time"), "hashlib": hashlib, "snapshot": snap, "persist": lambda: None, "directory": tmp_path, "manifest": {"phase": "execution", "approved_plan_digest": "p"*64}, "SimpleNamespace": SimpleNamespace, "Data": lambda **kw: kw, "active_inputs": active_inputs, "condition_result": condition_result}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "real-project-worker", "exec"), space)
    obj = space["Driver"].__new__(space["Driver"])
    plan = compile_workflow(controlled_graph("agent"))
    obj.control_flow = plan["control_flow"]
    obj.definitions = {t["id"]: t for t in plan["tasks"]}
    obj.outputs = {"DEV": {}, "TEST": {}, "VERIFY": {"passed": True}, "CONDITION": {"port": "match"}}
    obj.contracts = {}; obj.verified_candidate_digest = "source"
    obj.candidate_digest = lambda: "source"
    obj.implementation = AsyncMock(return_value={"summary": "Fixed", "status": "DONE"})
    obj.verification = AsyncMock(return_value={"passed": True, "status": "DONE"})
    return obj, snap, space


@pytest.mark.asyncio
async def test_real_driver_replays_only_explicit_region_and_keeps_tester_frozen(tmp_path):
    driver, snap, space = worker_class(tmp_path)
    async def native(task, instruction):
        space["update"](task["id"], "RUNNING", session_id="session-"+task["id"])
        return {"approved": task["iteration"] > 0, "summary": "Review result"}
    driver.native = native
    result = await driver.review_gate(driver.definitions["GATE"])
    assert result["approved"] is True
    driver.implementation.assert_awaited_once()
    assert driver.implementation.await_args.args[0]["original_id"] == "DEV"
    driver.verification.assert_awaited_once()
    assert snap["control_receipts"][-1]["reviewer"] == "agent"
    assert driver.outputs["CONDITION"]["port"] == "match"


@pytest.mark.asyncio
async def test_real_driver_exhaustion_escalates_to_human_and_cannot_loop_forever(tmp_path):
    driver, snap, space = worker_class(tmp_path)
    async def native(task, instruction):
        space["update"](task["id"], "RUNNING", session_id=task["id"])
        return {"approved": False, "summary": "Needs a fix"}
    driver.native = native
    driver.human_gate = AsyncMock(return_value={"approved": False, "port": "stopped"})
    await driver.review_gate(driver.definitions["GATE"])
    assert driver.implementation.await_count == 2
    assert driver.human_gate.await_args.kwargs == {"exhausted": True}
    assert driver.human_gate.await_args.args[1] == 3


@pytest.mark.asyncio
async def test_real_driver_malformed_verdict_fails_and_inactive_branch_never_calls_agent(tmp_path):
    driver, snap, space = worker_class(tmp_path)
    driver.native = AsyncMock(return_value={"approved": "true", "summary": "Bad"})
    with pytest.raises(RuntimeError, match="VERDICT_INVALID"): await driver.review_gate(driver.definitions["GATE"])
    driver.control_flow["edges"].append({"source": "CONDITION", "target": "SKIP", "port": "no_match"})
    await driver.execute_task({"id": "SKIP", "kind": "review", "title": "An inactive review branch", "depends_on": ["CONDITION"]})
    assert driver.outputs["SKIP"]["skipped"] is True
    driver.implementation.assert_not_called()


def test_success_proof_cannot_bypass_gate_or_forge_branch(tmp_path):
    plan = compile_workflow(controlled_graph("agent"))
    run = {"plan": plan, "approved_plan_digest": plan["digest"]}
    nodes = [{"id": t["id"], "state": "DONE", "outcome": "DONE"} for t in plan["tasks"]]
    nodes[3]["port"] = "match"
    with pytest.raises(ValueError, match="RECEIPT_REQUIRED"): verify_control_result(run, {"nodes": nodes}, None)
    nodes[3]["port"] = "no_match"
    with pytest.raises(ValueError, match="RESULT_INVALID"): verify_control_result(run, {"nodes": nodes}, None)


def test_success_proof_accepts_only_the_bound_human_receipt(tmp_path):
    store, run, task, q = gate_binding(tmp_path)
    store.answer_gate("alice", run, q["request_id"], "command", reply())
    plan = compile_workflow(controlled_graph())
    # The question and immutable execution plan use the same digest in production.
    run["plan"] = plan
    nodes = [{"id": t["id"], "state": "DONE", "outcome": "DONE"} for t in plan["tasks"]]
    nodes[3]["port"] = "match"
    nodes[4].update(outcome="APPROVED", source_digest="s"*64, port="approved")
    nodes.append({**task, "state": "DONE", "outcome": "APPROVED"})
    result = {"nodes": nodes, "control_receipts": [{"gate": "GATE", "reviewer": "human", "request_id": q["request_id"], "approved": True, "source_digest": "s"*64, "plan_digest": run["approved_plan_digest"]}]}
    verify_control_result(run, result, store)
    result["control_receipts"][0]["source_digest"] = "different"
    with pytest.raises(ValueError, match="RECEIPT_REQUIRED"): verify_control_result(run, result, store)


@pytest.mark.asyncio
@pytest.mark.parametrize("source_changes", [False, True])
async def test_real_worker_publishes_diff_waits_for_reply_and_resumes_only_same_source(tmp_path, source_changes):
    import difflib
    from langflow.adlc.live_workflows import safe_path
    driver, snapshot, space = worker_class(tmp_path)
    driver.baseline = {"app.py": "value = 0\n"}
    driver.files = {"app.py": "value = 1\n"}
    driver.tree = ["app.py"]
    driver.candidate = tmp_path / "candidate"; driver.candidate.mkdir()
    (driver.candidate / "app.py").write_text(driver.files["app.py"], encoding="utf8")
    space.update(Path=Path, digest=digest, safe_path=safe_path, difflib=difflib)
    driver.candidate_digest = type(driver).candidate_digest.__get__(driver)
    driver.verified_candidate_digest = driver.candidate_digest()
    store = HumanInputStore(tmp_path / "worker-questions.db")
    space["human_inputs"] = store
    space["manifest"].update(owner="alice", project_id="project", run_id=str(uuid4()), title="A pending review")
    async def user_reply(_):
        question = store.rows()[0]
        assert "+value = 1" in snapshot["diff"]
        assert snapshot["changed_files"] == ["app.py"]
        run = {**space["manifest"], "state": "RUNNING", "nodes": snapshot["nodes"]}
        store.answer_gate("alice", run, question["request_id"], "reply", reply())
        if source_changes:
            (driver.candidate / "app.py").write_text("value = 2\n", encoding="utf8")
    space["asyncio"] = SimpleNamespace(sleep=user_reply)
    visit = driver.visit_task(driver.definitions["GATE"], 0)
    if source_changes:
        with pytest.raises(RuntimeError, match="SOURCE_CHANGED"): await driver.human_gate(visit, 0)
        assert not snapshot.get("control_receipts")
    else:
        result = await driver.human_gate(visit, 0)
        assert result["approved"] and result["port"] == "approved"
        assert snapshot["control_receipts"][0]["source_digest"] == driver.candidate_digest()
        assert store.rows()[0]["status"] == "ANSWERED"

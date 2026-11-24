"""Typed branch routing and bounded review regions for project workflows."""
from copy import deepcopy

CONTROL_TYPES = {"condition", "verify", "gate"}
PREDICATES = {"status_done", "verification_passed", "review_approved"}


def topological(tasks):
    known, result = {task["id"]: task for task in tasks}, []
    while len(result) < len(known):
        ready = [key for key, task in known.items() if key not in result and set(task["depends_on"]) <= set(result)]
        if not ready:
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        result.extend(ready)
    return result


def compile_controls(tasks, edges):
    if any(not isinstance(t.get("id"), str) or not isinstance(t.get("kind"), str) for t in tasks):
        raise ValueError("LIVE_CONTROL_INVALID")
    known = {task["id"]: task for task in tasks}
    seen, forward, feedback = set(), [], []
    for task in tasks:
        control = task.get("control")
        if control is not None:
            if not isinstance(control, dict) or task["kind"] != "review" or control.get("type") not in CONTROL_TYPES:
                raise ValueError("LIVE_CONTROL_INVALID")
            if control["type"] == "condition" and control.get("predicate") not in PREDICATES:
                raise ValueError("LIVE_CONDITION_INVALID")
            if control["type"] == "gate" and (control.get("reviewer") not in {"human", "agent"} or type(control.get("max_rounds")) is not int or not 0 <= control["max_rounds"] <= 3):
                raise ValueError("LIVE_REVIEW_LIMIT_INVALID")
        if task.get("join", "all") not in {"all", "any"}:
            raise ValueError("LIVE_CONTROL_INVALID")
        task["depends_on"] = []
    for raw in edges:
        if not isinstance(raw, dict) or ("feedback" in raw and type(raw["feedback"]) is not bool):
            raise ValueError("LIVE_CONTROL_PORT_INVALID")
        source, target, port = raw.get("source"), raw.get("target"), raw.get("port", "done")
        if source not in known or target not in known or source == target or (source, target, port) in seen:
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        seen.add((source, target, port))
        source_type = (known[source].get("control") or {}).get("type")
        allowed = {"match", "no_match"} if source_type == "condition" else {"approved", "changes_requested"} if source_type == "gate" else {"done"}
        if port not in allowed or bool(raw.get("feedback")) != (port == "changes_requested"):
            raise ValueError("LIVE_CONTROL_PORT_INVALID")
        edge = {"source": source, "target": target, "port": port, "feedback": port == "changes_requested"}
        if edge["feedback"]:
            feedback.append(edge)
        else:
            forward.append(edge)
            if source not in known[target]["depends_on"]:
                known[target]["depends_on"].append(source)
    order = topological(tasks)
    def ancestors(identity):
        found, pending = set(), list(known[identity]["depends_on"])
        while pending:
            node = pending.pop()
            if node not in found:
                found.add(node); pending.extend(known[node]["depends_on"])
        return found
    loops, occupied = [], set()
    for task in tasks:
        kind = (task.get("control") or {}).get("type")
        incoming = [edge for edge in forward if edge["target"] == task["id"]]
        outgoing = [edge for edge in forward if edge["source"] == task["id"]]
        if task["kind"] == "test" and any((known[p].get("control") or {}).get("type") in {"condition", "gate"} for p in ancestors(task["id"])):
            raise ValueError("LIVE_TESTER_BRANCH_UNSUPPORTED")
        if kind == "verify" and any(t["id"] not in ancestors(task["id"]) for t in tasks if t["kind"] == "test"):
            raise ValueError("LIVE_CONTROL_TESTS_REQUIRED")
        if kind == "condition":
            if len(incoming) != 1 or {e["port"] for e in outgoing} != {"match", "no_match"}:
                raise ValueError("LIVE_CONDITION_BRANCHES_REQUIRED")
            predicate = task["control"]["predicate"]
            upstream = known[incoming[0]["source"]]
            if predicate == "verification_passed" and (upstream.get("control") or {}).get("type") != "verify":
                raise ValueError("LIVE_CONDITION_SOURCE_INVALID")
        if kind != "gate":
            continue
        parents = ancestors(task["id"])
        if not any((known[p].get("control") or {}).get("type") == "verify" for p in parents):
            raise ValueError("LIVE_REVIEW_VERIFICATION_REQUIRED")
        # No unrelated writer may change the candidate while a review is open.
        if any(t["kind"] in {"implement", "test"} and t["id"] not in parents and task["id"] not in ancestors(t["id"]) for t in tasks):
            raise ValueError("LIVE_REVIEW_BARRIER_REQUIRED")
        returns = [edge for edge in feedback if edge["source"] == task["id"]]
        if len(returns) > 1:
            raise ValueError("LIVE_REVIEW_LOOP_INVALID")
        if not returns:
            if task["control"]["max_rounds"]:
                raise ValueError("LIVE_REVIEW_LOOP_INVALID")
            continue
        target = returns[0]["target"]
        if target not in parents or known[target]["kind"] != "implement" or task["control"]["max_rounds"] < 1:
            raise ValueError("LIVE_REVIEW_LOOP_INVALID")
        region = {p for p in parents if p == target or target in ancestors(p)} | {task["id"]}
        if any((known[p].get("control") or {}).get("type") == "gate" for p in region - {task["id"]}) or region & occupied:
            raise ValueError("LIVE_REVIEW_LOOP_OVERLAP")
        if any(known[p]["kind"] == "implement" and p != target for p in region):
            raise ValueError("LIVE_REVIEW_LOOP_SCOPE")
        if any(e["source"] in region - {task["id"]} and e["target"] not in region for e in forward):
            raise ValueError("LIVE_REVIEW_LOOP_EXIT")
        if not any((known[p].get("control") or {}).get("type") == "verify" for p in region):
            raise ValueError("LIVE_REVIEW_VERIFICATION_REQUIRED")
        occupied.update(region)
        loops.append({"gate": task["id"], "target": target, "nodes": [p for p in order if p in region and p != task["id"]], "max_rounds": task["control"]["max_rounds"]})
    if len(tasks) + 2 + sum((len(loop["nodes"])+1) * loop["max_rounds"] for loop in loops) + sum((t.get("control") or {}).get("type") == "gate" for t in tasks) > 100:
        raise ValueError("LIVE_CONTROL_VISIT_LIMIT")
    return {"version": 1, "edges": [*forward, *feedback], "loops": loops, "max_repairs": 0}


def validate_controls(plan):
    data = plan.get("control_flow")
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("edges"), list):
        raise ValueError("LIVE_CONTROL_INVALID")
    tasks = deepcopy(plan["tasks"])
    expected = compile_controls(tasks, data["edges"])
    if expected != data or any(a["depends_on"] != b["depends_on"] for a, b in zip(tasks, plan["tasks"], strict=True)):
        raise ValueError("LIVE_CONTROL_CHANGED")


def active_inputs(task, edges, outputs):
    incoming = [edge for edge in edges if edge["target"] == task.get("original_id", task["id"]) and not edge.get("feedback")]
    if not incoming:
        return True
    flags, routed = [], []
    for edge in incoming:
        value = outputs.get(edge["source"], {})
        chosen = not value.get("skipped")
        if edge.get("port", "done") != "done":
            routed.append(chosen and value.get("port") == edge["port"])
        else:
            flags.append(chosen)
    normal = (any(flags) if task.get("join") == "any" else all(flags)) if flags else True
    return normal and (any(routed) if routed else True)


def condition_result(predicate, value):
    if predicate == "verification_passed":
        matched = value.get("passed") is True
    elif predicate == "review_approved":
        matched = value.get("approved") is True
    else:
        matched = predicate == "status_done" and value.get("status") in {"DONE", "APPROVED", "DONE_WITH_CONCERNS"} and not value.get("skipped")
    return {"port": "match" if matched else "no_match", "matched": matched, "status": "DONE", "summary": "Điều kiện đúng" if matched else "Điều kiện không khớp"}


def control_definitions(plan):
    return [*deepcopy(plan["tasks"]),
        {"id": "SYS_VERIFY", "title": "Kiểm chứng cuối trên source thực tế", "role": "runner", "depends_on": [t["id"] for t in plan["tasks"]]},
        {"id": "SYS_HANDOVER", "title": "Bàn giao kết quả đã kiểm chứng", "role": "runner", "depends_on": ["SYS_VERIFY"]}]


def verify_control_result(run, result, human_store):
    tasks = {task["id"]: task for task in run["plan"]["tasks"]}
    nodes = {node["id"]: node for node in result["nodes"]}
    outputs = {}
    for identity in topological(list(tasks.values())):
        task = tasks[identity]
        node = nodes.get(identity, {})
        active = active_inputs(task, run["plan"]["control_flow"]["edges"], outputs)
        if node.get("state") != ("DONE" if active else "SKIPPED"):
            raise ValueError("LIVE_CONTROL_RESULT_INVALID")
        outputs[identity] = {"skipped": not active, "port": node.get("port"), "status": node.get("outcome", "DONE")}
        outputs[identity]["passed"] = (task.get("control") or {}).get("type") == "verify" and node.get("outcome") == "DONE"
        outputs[identity]["approved"] = node.get("approved") is True or node.get("outcome") == "APPROVED"
        if active and (task.get("control") or {}).get("type") == "condition":
            source = next(edge["source"] for edge in run["plan"]["control_flow"]["edges"] if edge["target"] == identity and not edge["feedback"])
            if node.get("port") != condition_result(task["control"]["predicate"], outputs[source])["port"]:
                raise ValueError("LIVE_CONTROL_RESULT_INVALID")
        if not active or (task.get("control") or {}).get("type") != "gate":
            continue
        receipts = [r for r in result.get("control_receipts", []) if r.get("gate") == identity and r.get("approved") is True and r.get("plan_digest") == run["approved_plan_digest"]]
        if not receipts or node.get("outcome") != "APPROVED":
            raise ValueError("LIVE_REVIEW_RECEIPT_REQUIRED")
        receipt = receipts[-1]
        if node.get("source_digest") != receipt.get("source_digest"):
            raise ValueError("LIVE_REVIEW_RECEIPT_REQUIRED")
        if receipt.get("reviewer") == "human":
            try:
                question = human_store.get(run["owner"], run["run_id"], receipt["request_id"])
            except Exception as exc:
                raise ValueError("LIVE_REVIEW_RECEIPT_REQUIRED") from exc
            question_node = nodes.get(question.get("node_id"), {})
            if question_node.get("original_id") != identity or question.get("origin") != "workflow_gate" or question.get("status") != "ANSWERED" or question.get("gate_decision") != "approved" or question.get("source_digest") != receipt.get("source_digest") or question.get("plan_digest") != run["approved_plan_digest"]:
                raise ValueError("LIVE_REVIEW_RECEIPT_REQUIRED")
        elif task["control"]["reviewer"] != "agent" or receipt.get("reviewer") != "agent" or not receipt.get("session_id") or not any(n.get("session_id") == receipt["session_id"] and n.get("original_id") == identity and n.get("state") == "DONE" and n.get("outcome") == "APPROVED" for n in result["nodes"]):
            raise ValueError("LIVE_REVIEW_RECEIPT_REQUIRED")

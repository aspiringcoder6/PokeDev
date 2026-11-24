"""Compile the editable project canvas into the exact plan used by Workloop."""
from copy import deepcopy
import math

from langflow.adlc.live_workflows import validate_plan


def validate_draft(graph):
    """Incomplete content is allowed; malformed or unbounded canvas data is not."""
    if not isinstance(graph, dict) or graph.get("version") not in {1, 2}:
        raise ValueError("LIVE_WORKFLOW_INVALID")
    for key, limit in (("nodes", 20), ("edges", 190), ("commands", 8), ("browser_checks", 15)):
        if not isinstance(graph.get(key), list) or len(graph[key]) > limit:
            raise ValueError("LIVE_WORKFLOW_INVALID")
    for node in graph["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("task"), dict) or not isinstance(node.get("position"), dict):
            raise ValueError("LIVE_WORKFLOW_INVALID")
        for axis in ("x", "y"):
            value = node["position"].get(axis)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1000000:
                raise ValueError("LIVE_WORKFLOW_INVALID")
        task = node["task"]
        if not isinstance(task.get("title"), str) or not isinstance(task.get("kind"), str):
            raise ValueError("LIVE_WORKFLOW_INVALID")
        for key in ("steps", "acceptance", "write_paths"):
            if not isinstance(task.get(key), list) or len(task[key]) > 40 or any(not isinstance(value, str) or len(value) > 3000 for value in task[key]):
                raise ValueError("LIVE_WORKFLOW_INVALID")
    if any(not isinstance(edge, dict) or not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str) for edge in graph["edges"]):
        raise ValueError("LIVE_WORKFLOW_INVALID")
    if any(not isinstance(command, dict) or not isinstance(command.get("label"), str) or not isinstance(command.get("argv"), list) or any(not isinstance(arg, str) for arg in command["argv"]) for command in graph["commands"]):
        raise ValueError("LIVE_WORKFLOW_INVALID")
    return graph


def compile_workflow(graph):
    if not isinstance(graph, dict) or graph.get("version") not in {1, 2}:
        raise ValueError("LIVE_WORKFLOW_INVALID")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 20 or not isinstance(edges, list) or len(edges) > 190:
        raise ValueError("LIVE_PLAN_TASK_LIMIT")
    tasks, known = [], set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("task"), dict):
            raise ValueError("LIVE_WORKFLOW_INVALID")
        task = deepcopy(node["task"])
        if node.get("id") != task.get("id") or node["id"] in known:
            raise ValueError("LIVE_PLAN_TASK_ID")
        known.add(node["id"])
        task["depends_on"] = []
        tasks.append(task)
    control_flow = None
    if graph["version"] == 2:
        from langflow.adlc.workflow_controls import compile_controls
        control_flow = compile_controls(tasks, edges)
        edges = []
    elif any(task.get("control") for task in tasks):
        raise ValueError("LIVE_CONTROL_VERSION_REQUIRED")
    by_id, seen = {task["id"]: task for task in tasks}, set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known or source == target or (source, target) in seen:
            raise ValueError("LIVE_PLAN_DAG_INVALID")
        seen.add((source, target))
        by_id[target]["depends_on"].append(source)
    return validate_plan({
        "title": str(graph.get("title", ""))[:300],
        "summary": str(graph.get("summary", ""))[:3000],
        "tasks": tasks,
        "commands": deepcopy(graph.get("commands", [])),
        "preview": deepcopy(graph.get("preview")),
        "browser_checks": deepcopy(graph.get("browser_checks", [])),
        **({"control_flow": control_flow} if control_flow else {}),
    })


def workflow_status(graph):
    try:
        return compile_workflow(graph), None
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        code = str(exc)
        return None, code if code.startswith("LIVE_") else "LIVE_WORKFLOW_INVALID"


def workflow_snapshot(workflow):
    plan, error = workflow_status(workflow["graph"])
    if error:
        raise ValueError(error)
    return {key: deepcopy(workflow[key]) for key in ("workflow_id", "name", "project_id", "revision", "digest")} | {"plan": plan}


async def planning_plan(workflow, generate):
    if not workflow:
        return validate_plan(await generate())
    plan = validate_plan(deepcopy(workflow["plan"]))
    if plan["digest"] != workflow["plan"]["digest"]:
        raise ValueError("LIVE_WORKFLOW_CHANGED")
    return plan

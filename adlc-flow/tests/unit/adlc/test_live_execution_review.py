from copy import deepcopy

from langflow.adlc.live_workflows import completed_native_nodes, execution_definitions


def task(identity, kind, parents=()):
    return {"id": identity, "kind": kind, "depends_on": list(parents)}


def assert_topological(definitions):
    seen = set()
    for definition in definitions:
        assert set(definition["depends_on"]) <= seen
        seen.add(definition["id"])


def test_final_review_receives_verification_and_handover_waits_for_review():
    plan = {"tasks": [task("CODE", "implement"), task("TEST", "test"), task("REVIEW", "review", ["CODE", "TEST"])]}
    original = deepcopy(plan)
    definitions = execution_definitions(plan)
    nodes = {node["id"]: node for node in definitions}
    assert_topological(definitions)
    assert nodes["SYS_VERIFY"]["depends_on"] == ["CODE", "TEST"]
    assert nodes["REVIEW"]["depends_on"] == ["CODE", "TEST", "SYS_VERIFY"]
    assert nodes["REVIEW"]["verification_required"] is True
    assert set(nodes["SYS_HANDOVER"]["depends_on"]) == {"CODE", "TEST", "REVIEW", "SYS_VERIFY"}
    assert plan == original


def test_early_review_gate_stays_before_dependent_writer_without_a_cycle():
    plan = {"tasks": [task("A", "implement"), task("EARLY", "review", ["A"]), task("B", "implement", ["EARLY"]),
                      task("TEST", "test", ["B"]), task("FINAL", "review", ["TEST"])]}
    definitions = execution_definitions(plan)
    nodes = {node["id"]: node for node in definitions}
    assert_topological(definitions)
    assert nodes["EARLY"]["depends_on"] == ["A"]
    assert "verification_required" not in nodes["EARLY"]
    assert set(nodes["SYS_VERIFY"]["depends_on"]) == {"A", "EARLY", "B", "TEST"}
    assert nodes["FINAL"]["depends_on"] == ["TEST", "SYS_VERIFY"]


def test_no_review_keeps_verification_after_all_writer_tasks():
    definitions = execution_definitions({"tasks": [task("CODE", "implement"), task("TEST", "test", ["CODE"])]})
    assert_topological(definitions)
    assert [node["id"] for node in definitions] == ["CODE", "TEST", "SYS_VERIFY", "SYS_HANDOVER"]


def test_failed_application_review_is_not_reused_even_when_native_contract_done():
    code = {"id": "CODE", "state": "DONE", "session_id": "session-code", "native_status": "DONE"}
    review = {"id": "REVIEW", "state": "FAILED", "session_id": "session-review", "native_status": "DONE"}
    system = {"id": "SYS_VERIFY", "state": "DONE"}
    assert completed_native_nodes([code, review, system]) == {"CODE": code}

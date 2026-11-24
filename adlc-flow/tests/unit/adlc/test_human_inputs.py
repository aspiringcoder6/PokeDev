import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from langflow.adlc.human_inputs import (
    ActiveClock,
    HumanInputMonitor,
    HumanInputStore,
    normalize_request,
    validate_answer,
    wait_native_contract,
)
from langflow.adlc.live_workflows import LiveService, LiveStore
from langflow.adlc.vai_services import ServiceCheckError


def question_event(session="owned", identity="event-one"):
    return {
        "type": "waterfall",
        "event": "user-questions/request",
        "eventId": identity,
        "agentId": session,
        "request": {
            "questions": [
                {
                    "id": "color",
                    "question": "Which label should be used?",
                    "options": [{"label": "Blue", "description": "The blue label"}, {"label": "Green"}],
                }
            ]
        },
    }


def bound_run(tmp_path):
    store = LiveStore(tmp_path / "live.sqlite3")
    p = store.save_project(
        "alice",
        str(uuid4()),
        {"id": 1, "name": "test", "full_name": "admin/test", "html_url": "http://gitea/test"},
        "/source",
        "a" * 40,
    )
    row, _ = store.create("alice", p, str(uuid4()), str(uuid4()), "Requirement", "Test run", "a" * 40)
    row = store.update(row["run_id"], {"nodes": [{"id": "T01", "title": "Implement the test", "session_id": "owned"}]})
    service = LiveService(store)
    service.observe = lambda value: value
    monitor = HumanInputMonitor(service)
    monitor.endpoint = "http://harness"
    return store, row, monitor


def test_multiple_questions_keep_choice_labels_and_custom_text():
    event = question_event()
    event["request"]["questions"] += [
        {
            "id": "features",
            "question": "Which features?",
            "multiSelect": True,
            "options": [{"label": "Search"}, {"label": "Export"}],
        },
        {"id": "note", "question": "Any other details?"},
    ]
    request = normalize_request(event)
    answer = {
        "answers": [
            {"id": "color", "selected": ["Blue"], "custom": "Use a dark blue"},
            {"id": "features", "selected": ["Search", "Export"]},
            {"id": "note", "selected": [], "custom": "Keep it offline"},
        ]
    }
    assert validate_answer(request, answer) == answer


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"id": "foreign", "selected": ["Blue"]}],
        [{"id": "color", "selected": ["Unknown"]}],
        [{"id": "color", "selected": ["Blue", "Green"]}],
        [{"id": "color", "selected": [], "custom": "   "}],
        [{"id": "color", "selected": "Blue"}],
        [{"id": "color", "selected": ["Blue"], "approve": True}],
    ],
)
def test_invalid_or_incomplete_answers_are_never_forwarded(answers):
    with pytest.raises(ServiceCheckError, match="RESPONSE_INVALID"):
        validate_answer(normalize_request(question_event()), {"answers": answers})


def test_permissions_are_explicit_once_or_reject_never_persistent():
    request = normalize_request(
        {"event": "approval/request", "request": {"toolName": "shell", "displayReason": {"en": "Run the tests?"}}}
    )
    assert request["prompt"] == "Run the tests?"
    assert validate_answer(request, {"decision": "allowed-once"}) == "allowed-once"
    assert validate_answer(request, {"decision": "rejected"}) == "rejected"
    for value in ["approved", "always", "allowed", True, []]:
        with pytest.raises(ServiceCheckError):
            validate_answer(request, {"decision": value})


def test_only_local_run_sessions_are_visible_and_reconnects_deduplicate(tmp_path):
    _, run, monitor = bound_run(tmp_path)
    monitor.receive(question_event(session="somebody-elses-agent"))
    assert monitor.store.rows() == []
    event = question_event()
    monitor.receive(event)
    monitor.receive(event)
    assert len(monitor.store.rows()) == 1
    monitor.connected.set()
    row = monitor.pending("alice")[0]
    assert row["node_id"] == "T01" and row["can_respond"]
    assert not {"owner", "event_id", "endpoint"} & set(row)
    assert monitor.pending("bob") == []
    monitor.receive({"type": "cancel", "eventId": event["eventId"]})
    assert monitor.pending("alice") == []
    assert monitor.store.rows()[0]["status"] == "RESOLVED_ELSEWHERE"


@pytest.mark.asyncio
async def test_response_replay_is_idempotent_and_other_run_is_denied(tmp_path):
    _, run, monitor = bound_run(tmp_path)
    monitor.receive(question_event())
    request = monitor.pending("alice")[0]
    monitor.connected.set()
    monitor.ready = AsyncMock()
    monitor.stream = SimpleNamespace(answer=AsyncMock())
    answer = {"answers": [{"id": "color", "selected": ["Blue"]}]}
    first = await monitor.answer("alice", run, request["request_id"], "command", answer)
    second = await monitor.answer("alice", run, request["request_id"], "command", answer)
    assert first["status"] == second["status"] == "ANSWERED"
    monitor.stream.answer.assert_awaited_once_with("event-one", answer)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        await monitor.answer("bob", run, request["request_id"], "other", answer)
    with pytest.raises(ServiceCheckError, match="NOT_FOUND"):
        await monitor.answer("alice", {**run, "run_id": "another-run"}, request["request_id"], "other", answer)
    with pytest.raises(ServiceCheckError, match="CHANGED"):
        await monitor.answer(
            "alice", run, request["request_id"], "other", {"answers": [{"id": "color", "selected": ["Green"]}]}
        )


@pytest.mark.asyncio
async def test_lost_ack_is_not_replayed_and_fresh_native_replay_allows_retry(tmp_path):
    _, run, monitor = bound_run(tmp_path)
    event = question_event()
    monitor.receive(event)
    identity = monitor.pending("alice")[0]["request_id"]
    monitor.connected.set()
    monitor.ready = AsyncMock()
    socket = SimpleNamespace(close=AsyncMock())
    monitor.stream = SimpleNamespace(answer=AsyncMock(side_effect=TimeoutError), socket=socket)
    response = {"answers": [{"id": "color", "selected": ["Blue"]}]}
    with pytest.raises(ServiceCheckError, match="UNCONFIRMED"):
        await monitor.answer("alice", run, identity, "command", response)
    assert monitor.store.get("alice", run["run_id"], identity)["status"] == "UNCERTAIN"
    socket.close.assert_awaited_once()
    with pytest.raises(ServiceCheckError):
        await monitor.answer("alice", run, identity, "command", response)
    assert monitor.stream.answer.await_count == 1
    monitor.receive(event)
    assert monitor.store.get("alice", run["run_id"], identity)["status"] == "PENDING"


def test_foreign_or_stale_node_binding_cannot_receive_response(tmp_path):
    store, run, monitor = bound_run(tmp_path)
    monitor.receive(question_event())
    row = monitor.store.rows()[0]
    with pytest.raises(ServiceCheckError, match="BINDING_CHANGED"):
        monitor.store.receive(question_event(), {**run, "run_id": "foreign"}, run["nodes"][0], monitor.endpoint)
    assert HumanInputStore(store.path).get("alice", run["run_id"], row["request_id"])["status"] == "PENDING"


def test_restart_does_not_lose_a_reply_that_was_in_flight(tmp_path):
    _, run, monitor = bound_run(tmp_path)
    event = question_event()
    monitor.receive(event)
    identity = monitor.store.rows()[0]["request_id"]
    monitor.store.claim(
        "alice", run["run_id"], identity, "command", {"answers": [{"id": "color", "selected": ["Blue"]}]}
    )
    monitor.store.update(identity, sender_pid=-1)
    recovered = HumanInputMonitor(monitor.live)
    recovered.endpoint = monitor.endpoint
    assert recovered.store.get("alice", run["run_id"], identity)["status"] == "UNCERTAIN"
    recovered.receive(event)
    assert recovered.store.get("alice", run["run_id"], identity)["status"] == "PENDING"


def test_waiting_for_a_person_does_not_consume_execution_budget():
    value = [0.0]
    clock = ActiveClock(lambda: value[0])
    value[0] = 30
    assert clock.tick() == 30
    value[0] = 24 * 3600
    assert clock.tick(paused=True) == 30
    value[0] += 5
    assert clock.tick() == 35


@pytest.mark.asyncio
async def test_native_contract_survives_long_human_wait_and_resumes(monkeypatch):
    import langflow.adlc.human_inputs as module

    value, count = [0], [0]
    monkeypatch.setattr(module, "ActiveClock", lambda: ActiveClock(lambda: value[0]))

    async def sleep(_):
        value[0] += 1000
        count[0] += 1

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    from dsh_web_sdk import taskloop

    monkeypatch.setattr(
        taskloop,
        "get_task",
        AsyncMock(side_effect=[{"status": "IN_PROGRESS"}, {"status": "IN_PROGRESS"}, {"status": "DONE"}]),
    )
    result = await wait_native_contract(
        object(), "/owned", "1", waiting=lambda: count[0] < 2, timeout_s=10, stall_s=5, poll_s=1
    )
    assert result["status"] == "DONE"


@pytest.mark.asyncio
async def test_answer_endpoint_checks_execution_permission_before_native_response(tmp_path, monkeypatch):
    from langflow.api.v1 import adlc_live as api

    store, row, monitor = bound_run(tmp_path)
    owner = str(uuid4())
    with store.db() as db:
        db.execute(
            "UPDATE runs SET owner=?,payload=? WHERE id=?", (owner, json.dumps({**row, "owner": owner}), row["run_id"])
        )
    service = monitor.live
    service._human_input = monitor
    monitor.answer = AsyncMock()
    monkeypatch.setattr(api, "live_service", lambda: service)
    monkeypatch.setattr(api, "source", AsyncMock(return_value=(None, object())))
    monkeypatch.setattr(api, "permission", AsyncMock(return_value=False))
    with pytest.raises(api.HTTPException) as denied:
        await api.answer_human_input(
            UUID(row["run_id"]),
            "request",
            api.HumanResponseCommand(command_id=uuid4(), response={}),
            AsyncMock(),
            SimpleNamespace(id=UUID(owner)),
        )
    assert denied.value.status_code == 403
    monitor.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_advanced_human_gates_join_the_inbox_without_remote_session_enumeration(tmp_path, monkeypatch):
    from langflow.api.v1 import adlc as runtime

    _, _, monitor = bound_run(tmp_path)
    histories = [
        SimpleNamespace(id=uuid4(), name="Approval", status=SimpleNamespace(value="WAITING_APPROVAL")),
        SimpleNamespace(id=uuid4(), name="Agent question", status=SimpleNamespace(value="RUNNING")),
        SimpleNamespace(id=uuid4(), name="Finished", status=SimpleNamespace(value="SUCCEEDED")),
    ]
    service = SimpleNamespace(list_runs=AsyncMock(return_value=SimpleNamespace(runs=histories, total=len(histories))))
    pending = SimpleNamespace(attempt_id=uuid4(), status=SimpleNamespace(value="WAITING_INTERACTION"))
    attempts = SimpleNamespace(list_for_workflow_run=AsyncMock(side_effect=[[], [pending]]))
    monkeypatch.setattr(runtime, "get_adlc_run_service", AsyncMock(return_value=service))
    monkeypatch.setattr(runtime, "get_harness_callback_receiver", lambda: SimpleNamespace(attempts=attempts))
    first = await monitor.legacy_reviews("alice")
    assert [r["run_title"] for r in first] == ["Approval", "Agent question"]
    assert first[1]["href"] == "/runs/" + str(histories[1].id)
    assert await monitor.legacy_reviews("alice") == first
    service.list_runs.assert_awaited_once_with(owner_id="alice", limit=100)


@pytest.mark.asyncio
async def test_advanced_inbox_keeps_an_old_gate_beyond_the_first_history_page(tmp_path, monkeypatch):
    from langflow.api.v1 import adlc as runtime

    _, _, monitor = bound_run(tmp_path)
    finished = [SimpleNamespace(id=uuid4(), status=SimpleNamespace(value="SUCCEEDED")) for _ in range(100)]
    gate = SimpleNamespace(id=uuid4(), name="Old approval", status=SimpleNamespace(value="WAITING_APPROVAL"))
    service = SimpleNamespace(list_runs=AsyncMock(side_effect=[SimpleNamespace(runs=finished, total=101), SimpleNamespace(runs=[gate], total=101)]))
    attempts = SimpleNamespace(list_for_workflow_run=AsyncMock(return_value=[]))
    monkeypatch.setattr(runtime, "get_adlc_run_service", AsyncMock(return_value=service))
    monkeypatch.setattr(runtime, "get_harness_callback_receiver", lambda: SimpleNamespace(attempts=attempts))
    result = await monitor.legacy_reviews("alice")
    assert len(result) == 1 and result[0]["run_id"] == str(gate.id)
    assert service.list_runs.await_args_list[1].kwargs == {"owner_id": "alice", "limit": 100, "offset": 100}
    attempts.list_for_workflow_run.assert_awaited_once_with(gate.id)

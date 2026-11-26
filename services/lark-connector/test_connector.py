import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from connector import (
    Backend,
    Journal,
    LarkSender,
    Worker,
    exclusive_worker,
    normalize,
    normalize_v2,
)
from pokedev_lark_contracts import Delivery, DeliveryResult, IngestReceipt, v2


def raw(text="Export monthly revenue"):
    return {
        "header": {
            "app_id": "app_test",
            "tenant_key": "tenant_test",
            "event_id": "event_test",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_type": "user", "sender_id": {"open_id": "ou_test"}},
            "message": {
                "message_id": "om_test",
                "chat_id": "oc_test",
                "chat_type": "p2p",
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }


def delivery():
    identity = uuid4()
    return Delivery(
        id=identity,
        lease_id=uuid4(),
        uuid=identity,
        chat_id="oc_test",
        reply_to="om_test",
        text="Requirement received",
    )


def test_normalizer_preserves_source_and_hashes_pair_codes_before_persistence(tmp_path):
    code = "a" * 32
    command = normalize(raw("/link " + code))
    assert (
        command.kind == "pair"
        and command.text is None
        and len(command.pair_digest) == 64
    )
    journal = Journal(tmp_path / "journal.sqlite3")
    journal.record(command)
    journal.record(command)
    assert len(journal.pending()) == 1
    with journal.connect() as db:
        assert code not in db.execute("SELECT payload FROM inbox").fetchone()[0]
    other = raw()
    other["event"]["message"]["chat_type"] = "group"
    assert normalize(other) is None
    other["event"]["message"]["chat_type"] = "p2p"
    other["event"]["sender"]["sender_type"] = "app"
    assert normalize(other) is None


def test_backend_outage_and_restart_replay_the_same_durable_ingress(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    command = normalize(raw())
    journal.record(command)
    backend = SimpleNamespace(
        ingest=lambda message: (_ for _ in ()).throw(RuntimeError("offline")),
        claim=lambda: [],
    )
    worker = Worker(journal, backend, None)
    with pytest.raises(RuntimeError):
        worker.once()
    reopened = Journal(path)
    assert len(reopened.pending()) == 1
    seen = []
    backend.ingest = lambda message: (
        seen.append(message),
        IngestReceipt(event_id=message.event_id, status="CREATED", request_id=uuid4()),
    )[1]
    Worker(reopened, backend, None).once()
    assert seen == [command] and not reopened.pending()


def test_crash_after_intent_is_unconfirmed_without_resending(tmp_path):
    path = tmp_path / "journal.sqlite3"
    journal = Journal(path)
    item = delivery()
    assert journal.begin_send(item)
    reports = []
    backend = SimpleNamespace(result=lambda d, r: reports.append(r), claim=lambda: [])
    sender = SimpleNamespace(
        send=lambda _: pytest.fail("Uncertain sends must never be repeated")
    )
    Worker(Journal(path), backend, sender).once()
    assert len(reports) == 1 and reports[0].state == "UNCONFIRMED"


def test_lost_backend_receipt_retries_reporting_without_sending_twice(tmp_path):
    journal = Journal(tmp_path / "journal.sqlite3")
    item = delivery()
    calls, reports = [], []

    def report(d, result):
        reports.append(result)
        if len(reports) == 1:
            raise RuntimeError("response lost")

    backend = SimpleNamespace(claim=lambda: [item], result=report)
    sender = SimpleNamespace(
        send=lambda d: (
            calls.append(d),
            DeliveryResult(
                lease_id=d.lease_id, state="DELIVERED", provider_message_id="om_reply"
            ),
        )[1]
    )
    worker = Worker(journal, backend, sender)
    with pytest.raises(RuntimeError):
        worker.once()
    backend.claim = lambda: []
    worker.once()
    assert len(calls) == 1 and len(reports) == 2 and reports[0] == reports[1]


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("success", "DELIVERED"),
        ("timeout", "UNCONFIRMED"),
        ("server", "UNCONFIRMED"),
        ("rate", "RETRY"),
        ("rejected", "FAILED"),
        ("wrong_chat", "UNCONFIRMED"),
    ],
)
def test_provider_outcomes_never_hide_uncertainty(scenario, expected):
    requests = []

    def handle(request):
        requests.append(request)
        if "/auth/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "synthetic-token",
                    "expire": 7200,
                },
            )
        body = json.loads(request.content)
        assert body["uuid"] and body["msg_type"] == "text"
        if scenario == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if scenario == "rate":
            return httpx.Response(
                429, headers={"retry-after": "2"}, json={"code": 99991400}
            )
        if scenario == "server":
            return httpx.Response(503, json={"code": 1})
        if scenario == "rejected":
            return httpx.Response(403, json={"code": 1})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "message_id": "om_reply",
                    "chat_id": "oc_wrong" if scenario == "wrong_chat" else "oc_test",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = LarkSender("app_test", "synthetic-secret", client=client).send(
            delivery()
        )
    assert result.state == expected
    assert len([request for request in requests if "/reply" in request.url.path]) == 1


def test_backend_consumer_uses_the_shared_contract_and_separate_credential():
    def handle(request):
        assert request.headers["authorization"] == "Bearer " + "s" * 48
        payload = json.loads(request.content)
        command = normalize(raw())
        assert payload == command.model_dump(mode="json")
        return httpx.Response(
            200,
            json=IngestReceipt(
                event_id=command.event_id, status="LINK_REQUIRED"
            ).model_dump(mode="json"),
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            Backend("http://127.0.0.1:7862", "s" * 48, client=client)
            .ingest(normalize(raw()))
            .status
            == "LINK_REQUIRED"
        )
    with pytest.raises(ValueError, match="HTTPS_REQUIRED"):
        Backend("http://public.example", "s" * 48)


def test_same_journal_refuses_a_second_live_worker(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with exclusive_worker(path), pytest.raises(OSError):
        with exclusive_worker(path):
            pytest.fail("A second worker acquired the same journal")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"code": False},
        {"code": 0, "tenant_access_token": "token", "expire": -1},
    ],
)
def test_malformed_auth_responses_never_send_messages(payload):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = LarkSender("app_test", "synthetic-secret", client=client).send(
            delivery()
        )
    assert result.state == "RETRY" and len(paths) == 1


def group_raw(text="@_user_1 Export monthly revenue", **fields):
    payload = raw(text)
    payload["event"]["message"].update(
        {
            "chat_type": "group",
            "mentions": [{"key": "@_user_1", "id": {"open_id": "ou_bot"}}],
            **fields,
        }
    )
    return payload


def test_v2_normalizer_keeps_native_ids_and_only_strips_actual_bot_placeholder():
    payload = group_raw(
        "@_user_1 Report for @_user_10",
        root_id="om_root",
        parent_id="om_parent",
        thread_id="omt_thread",
    )
    command = normalize_v2(payload, bot_open_id="ou_bot", group_ids={"oc_test"})
    assert command.version == "2" and command.chat_type == "group"
    assert command.text == "Report for @_user_10"
    assert (command.root_id, command.parent_id, command.thread_id) == (
        "om_root",
        "om_parent",
        "omt_thread",
    )
    assert command.mentioned_open_ids == ["ou_bot"]
    payload["event"]["sender"]["sender_type"] = "app"
    assert normalize_v2(payload, bot_open_id="ou_bot", group_ids={"oc_test"}) is None


def test_v2_unknown_groups_only_persist_explicit_probe_metadata_without_text():
    assert normalize_v2(group_raw(), bot_open_id="ou_bot") is None
    command = normalize_v2(group_raw("@_user_1 /probe"), bot_open_id="ou_bot")
    assert command.discovery and command.kind == "unsupported" and command.text is None
    assert command.chat_id == "oc_test"
    assert normalize_v2(group_raw("@_user_1 /probe"), bot_open_id="ou_other") is None


def test_v2_group_pairing_code_is_hashed_and_empty_sdk_identifiers_are_normalized(
    tmp_path,
):
    code = "a" * 32
    command = normalize_v2(
        group_raw("@_user_1 /link " + code, root_id="", parent_id="", thread_id=""),
        bot_open_id="ou_bot",
        group_ids={"oc_test"},
    )
    assert (
        command.kind == "pair"
        and command.text is None
        and command.root_id is command.parent_id is command.thread_id is None
    )
    journal = Journal(tmp_path / "journal.sqlite3")
    journal.record(command)
    with journal.connect() as db:
        assert code not in db.execute("SELECT payload FROM inbox").fetchone()[0]


def test_v2_nonmention_roots_are_ignored_but_thread_events_can_be_verified():
    payload = group_raw("An ordinary message", mentions=[])
    assert normalize_v2(payload, bot_open_id="ou_bot", group_ids={"oc_test"}) is None
    payload["event"]["message"].update(parent_id="om_tracked", root_id="om_root")
    command = normalize_v2(payload, bot_open_id="ou_bot", group_ids={"oc_test"})
    assert command.mentioned_open_ids == [] and command.parent_id == "om_tracked"


def test_mixed_v1_v2_journal_preserves_receipt_protocol_during_recovery(tmp_path):
    path = tmp_path / "mixed.sqlite3"
    journal = Journal(path)
    old = normalize(raw())
    new = normalize_v2(group_raw(), bot_open_id="ou_bot", group_ids={"oc_test"})
    new = new.model_copy(update={"event_id": "event_v2"})
    journal.record(old)
    journal.record(new)
    old_delivery = delivery()
    new_delivery = v2.Delivery(
        **delivery().model_dump(mode="json"), reply_in_thread=True
    )
    journal.begin_send(old_delivery)
    journal.finish_send(
        old_delivery,
        DeliveryResult(
            lease_id=old_delivery.lease_id,
            state="DELIVERED",
            provider_message_id="om_old_reply",
        ),
    )
    journal.begin_send(new_delivery)
    reopened = Journal(path)
    assert [item.version for _, item in reopened.pending()] == ["1", "2"]
    results = list(reopened.unreported())
    assert type(results[0][1]) is DeliveryResult
    assert (
        type(results[1][1]) is v2.DeliveryResult
        and results[1][1].state == "UNCONFIRMED"
    )


def test_v2_backend_uses_versioned_paths_but_reconciles_legacy_receipts_on_v1():
    paths = []
    command = normalize_v2(raw(), bot_open_id="ou_bot")

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/events"):
            assert v2.InboundMessage.model_validate_json(request.content) == command
            return httpx.Response(
                200,
                json=v2.IngestReceipt(
                    event_id=command.event_id, status="APPENDED"
                ).model_dump(mode="json"),
            )
        if request.url.path.endswith("/claim"):
            return httpx.Response(
                200, json=v2.DeliveryBatch(items=[]).model_dump(mode="json")
            )
        assert "version" not in json.loads(request.content)
        return httpx.Response(200, json={"state": "DELIVERED"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        backend = Backend("http://127.0.0.1:7862", "s" * 48, version=2, client=client)
        assert backend.ingest(command).status == "APPENDED"
        assert backend.claim() == []
        old = delivery()
        backend.result(
            old,
            DeliveryResult(
                lease_id=old.lease_id, state="DELIVERED", provider_message_id="om_old"
            ),
        )
    assert paths[0].endswith("/v2/events") and paths[1].endswith("/v2/deliveries/claim")
    assert "/v2/" not in paths[2]


def test_group_outbound_uses_thread_flag_and_stable_uuid_and_bot_identity_is_exact():
    calls = []
    group_delivery = v2.Delivery(
        **delivery().model_dump(mode="json"), reply_in_thread=True
    )

    def handle(request):
        calls.append(request)
        if "/auth/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "synthetic-token",
                    "expire": 7200,
                },
            )
        if request.url.path.endswith("/bot/v3/info"):
            return httpx.Response(
                200, json={"code": 0, "bot": {"open_id": "ou_actual_bot"}}
            )
        body = json.loads(request.content)
        assert body["reply_in_thread"] is True and body["uuid"] == str(
            group_delivery.uuid
        )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"chat_id": "oc_test", "message_id": "om_group_reply"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        sender = LarkSender("app_test", "synthetic-secret", client=client)
        assert sender.bot_identity() == "ou_actual_bot"
        result = sender.send(group_delivery)
        assert type(result) is v2.DeliveryResult and result.state == "DELIVERED"
    assert (
        len([request for request in calls if request.url.path.endswith("/reply")]) == 1
    )


@pytest.mark.parametrize(
    "payload", [None, [], {"code": False}, {"code": 0, "bot": {"open_id": "bad/id"}}]
)
def test_malformed_bot_identity_never_falls_back_to_display_name(payload):
    def handle(request):
        if "/auth/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "synthetic-token",
                    "expire": 7200,
                },
            )
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="BOT_IDENTITY"):
            LarkSender("app_test", "synthetic-secret", client=client).bot_identity()


def test_bot_info_cli_is_read_only_and_works_while_the_journal_worker_is_locked(
    tmp_path, monkeypatch, capsys
):
    import connector

    path = tmp_path / "transport.sqlite3"
    requests = []

    def handle(request):
        requests.append(request)
        if "/auth/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": "synthetic-token",
                    "expire": 7200,
                },
            )
        return httpx.Response(
            200, json={"code": 0, "bot": {"open_id": "ou_actual_bot"}}
        )

    original_sender = connector.LarkSender
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        monkeypatch.setattr(
            connector, "credentials", lambda: ("app_test", "synthetic-secret")
        )
        monkeypatch.setattr(
            connector,
            "LarkSender",
            lambda app, secret: original_sender(app, secret, client=client),
        )
        monkeypatch.setattr(
            connector.sys,
            "argv",
            ["connector.py", "--bot-info", "--journal", str(path)],
        )
        with exclusive_worker(path):
            connector.main()
    output = capsys.readouterr().out
    assert json.loads(output) == {"bot_open_id": "ou_actual_bot"}
    assert "synthetic-secret" not in output and "synthetic-token" not in output
    assert not path.exists() and len(requests) == 2

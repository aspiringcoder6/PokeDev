import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from connector import Backend, Journal, LarkSender, Worker, exclusive_worker, normalize
from pokedev_lark_contracts import Delivery, DeliveryResult, IngestReceipt


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

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx
from fastapi import HTTPException, Response

from langflow.adlc import slack_notifications as module
from langflow.adlc.document_intake import DocumentIntake
from langflow.adlc.slack_notifications import SlackNotifications
from langflow.adlc.slack_notifications import SlackAPI
from langflow.api.v1 import adlc_integrations as integration_api
from langflow.adlc.vai_services import ServiceCheckError
from test_document_intake import Client, Pages


TOKEN = "xoxb-example-token-for-unit-tests-only"


@pytest.fixture
async def notifications(tmp_path):
    intake = DocumentIntake(tmp_path / "intake.sqlite3", Client(), Pages())
    await intake.sync("owner")
    gateway = SimpleNamespace(
        call=AsyncMock(
            return_value={
                "delivery": "SENT",
                "bot_id": "B01234567",
                "user_id": "U01234567",
                "user": "test-bot",
                "team": "ADLC",
                "team_id": "T01234567",
                "url": "https://adlcfactory.slack.com/",
                "ts": "1793249999.123456",
            }
        )
    )
    store = {}

    def seal(value):
        store["ciphertext"] = value
        return "ciphertext"

    live = SimpleNamespace()
    notifier = SlackNotifications(intake, live, gateway, AsyncMock(), seal, lambda _: store["ciphertext"])
    await notifier.connect("owner", TOKEN)
    gateway.call.reset_mock()
    notifier.configure("owner", 1, True)
    return notifier, intake, gateway, store


@pytest.mark.asyncio
async def test_token_is_encrypted_and_status_never_returns_it(notifications):
    notifier, intake, _, _ = notifications
    assert notifier.settings("owner")["configured"] and not notifier.settings("other")["configured"]
    assert TOKEN not in json.dumps(notifier.settings("owner"))
    with intake.db() as db:
        assert db.execute("SELECT cipher FROM intake_slack_credentials").fetchone()[0] != TOKEN


@pytest.mark.asyncio
async def test_notice_uses_source_thread_and_does_not_repeat_on_poll_or_restart(notifications):
    notifier, intake, gateway, store = notifications
    await notifier.observe("owner", 1)
    await notifier.deliver()
    await notifier.observe("owner", 1)
    await notifier.deliver()
    assert gateway.call.await_count == 1
    method, token, payload = gateway.call.await_args.args
    assert method == "chat.postMessage" and token == TOKEN
    assert payload["thread_ts"] == "1793074062.301049" and payload["channel"] == "C01234567"
    assert payload["reply_broadcast"] is False and payload["mrkdwn"] is False
    assert "Chưa bắt đầu" in payload["text"] and "run" not in payload["metadata"]["event_payload"]
    receipt_url = (
        "https://adlcfactory.slack.com/archives/C01234567/p1793249999123456?thread_ts=1793074062.301049&cid=C01234567"
    )
    assert notifier.history("owner", 1)[0]["message_url"] == receipt_url
    assert intake.get("owner", 1)["notifications"]["last_message_url"] == receipt_url
    assert not notifier.history("other", 1)
    restarted = SlackNotifications(intake, notifier.live, gateway, AsyncMock(), notifier.seal, notifier.unseal)
    await restarted.observe("owner", 1)
    await restarted.deliver()
    assert gateway.call.await_count == 1


@pytest.mark.asyncio
async def test_missing_configuration_disabled_or_revoked_permission_sends_nothing(notifications):
    notifier, _, gateway, _ = notifications
    notifier.configure("owner", 1, False)
    await notifier.observe("owner", 1)
    await notifier.deliver()
    notifier.configure("owner", 1, True)
    notifier.permission.side_effect = ServiceCheckError("DENIED", 403)
    with pytest.raises(ServiceCheckError):
        await notifier.observe("owner", 1)
    notifier.permission.side_effect = None
    notifier.disconnect("owner")
    await notifier.observe("owner", 1)
    await notifier.deliver()
    assert gateway.call.await_count == 0


@pytest.mark.asyncio
async def test_lost_delivery_reply_and_crashed_inflight_send_are_never_replayed(notifications):
    notifier, intake, gateway, _ = notifications
    gateway.call.return_value = {"delivery": "UNCONFIRMED", "error": "SLACK_DELIVERY_UNCONFIRMED"}
    await notifier.observe("owner", 1)
    await notifier.deliver()
    await notifier.deliver()
    assert gateway.call.await_count == 1 and notifier.history("owner", 1)[0]["state"] == "UNCONFIRMED"
    assert notifier.history("owner", 1)[0]["message_url"] is None
    with intake.db() as db, db:
        db.execute("UPDATE intake_slack_outbox SET state='SENDING'")
    restarted = SlackNotifications(intake, notifier.live, gateway, AsyncMock(), notifier.seal, notifier.unseal)
    await restarted.deliver()
    assert gateway.call.await_count == 1


@pytest.mark.asyncio
async def test_rate_limit_waits_before_retry_and_reuses_event_identity(notifications):
    notifier, intake, gateway, _ = notifications
    gateway.call.return_value = {"delivery": "RETRY", "error": "SLACK_RATE_LIMITED", "delay": 60}
    await notifier.observe("owner", 1)
    await notifier.deliver()
    await notifier.deliver()
    assert gateway.call.await_count == 1
    first_id = gateway.call.await_args.args[2]["client_msg_id"]
    with intake.db() as db, db:
        db.execute("UPDATE intake_slack_outbox SET available=0")
    gateway.call.return_value = {"delivery": "SENT"}
    await notifier.deliver()
    assert gateway.call.await_args.args[2]["client_msg_id"] == first_id


@pytest.mark.asyncio
async def test_new_human_question_replaces_stale_unsent_notice_even_when_count_is_unchanged(notifications):
    notifier, intake, gateway, _ = notifications
    run = {
        "run_id": "run",
        "project_id": "project",
        "phase": "execution",
        "state": "RUNNING",
        "origin_document": {"document_id": "1", "lifecycle_id": "lc-thread"},
        "nodes": [],
    }
    notifier.live = SimpleNamespace(
        store=SimpleNamespace(get=Mock(return_value=run)),
        observe=lambda r: r,
        human_input=SimpleNamespace(pending=Mock(return_value=[{"id": "question-1"}])),
    )
    intake.change("owner", 1, lambda row: row.update(project_id="project", run_id="run"))
    await notifier.observe("owner", 1)
    notifier.live.human_input.pending.return_value = [{"id": "question-2"}]
    await notifier.observe("owner", 1)
    assert {r["state"] for r in notifier.history("owner", 1)} == {"SUPERSEDED", "PENDING"}
    await notifier.deliver()
    assert gateway.call.await_count == 1 and "Chờ người dùng" in gateway.call.await_args.args[2]["text"]


@pytest.mark.asyncio
async def test_wrong_workspace_never_replaces_a_working_connection(notifications):
    notifier, _, gateway, _ = notifications
    gateway.call.return_value = {"delivery": "SENT", "bot_id": "B99999999", "url": "https://other.slack.com/"}
    with pytest.raises(ServiceCheckError, match="WORKSPACE_MISMATCH"):
        await notifier.connect("owner", TOKEN)
    assert notifier.settings("owner")["identity"]["bot_id"] == "B01234567"


@pytest.mark.asyncio
async def test_changed_source_thread_cancels_the_queued_send_before_contacting_slack(notifications):
    notifier, intake, gateway, _ = notifications
    await notifier.observe("owner", 1)
    intake.client.docs[0]["slack_thread"] = "999.123456"
    await notifier.deliver()
    assert not gateway.call.await_count
    assert notifier.history("owner", 1)[0]["state"] == "CANCELLED"
    assert not intake.get("owner", 1)["notifications"]["enabled"]


@pytest.mark.asyncio
async def test_reconnecting_clears_paused_status_without_replaying_a_delivered_notice(notifications):
    notifier, intake, gateway, _ = notifications
    await notifier.observe("owner", 1)
    await notifier.deliver()
    notifier.disconnect("owner")
    await notifier.observe("owner", 1)
    assert intake.get("owner", 1)["notifications"]["state"] == "NEEDS_CONFIGURATION"
    await notifier.connect("owner", TOKEN)
    await notifier.observe("owner", 1)
    await notifier.deliver()
    assert intake.get("owner", 1)["notifications"]["state"] == "READY"
    assert [call.args[0] for call in gateway.call.await_args_list].count("chat.postMessage") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {"ok": True, "channel": "C99999999", "ts": "123.123456"},
        {"ok": True, "channel": "C01234567"},
    ],
)
async def test_success_requires_a_message_acknowledgement_for_the_exact_channel(monkeypatch, result):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)), **kwargs),
    )
    reply = await SlackAPI().call("chat.postMessage", TOKEN, {"channel": "C01234567", "text": "test"})
    assert reply["delivery"] == "UNCONFIRMED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,delivery",
    [
        (httpx.ConnectTimeout, "RETRY"),
        (httpx.PoolTimeout, "RETRY"),
        (httpx.ReadTimeout, "UNCONFIRMED"),
        (httpx.WriteTimeout, "UNCONFIRMED"),
    ],
)
async def test_only_failures_before_sending_the_body_can_retry_automatically(monkeypatch, failure, delivery):
    original = httpx.AsyncClient

    def unavailable(_request):
        raise failure("private connection detail")

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(unavailable), **kwargs),
    )
    reply = await SlackAPI().call("chat.postMessage", TOKEN, {"channel": "C01234567", "text": "test"})
    assert reply["delivery"] == delivery
    assert "private connection detail" not in json.dumps(reply)


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_thread,expected", [("999.123456", "UNCONFIRMED"), ("1793074062.301049", "SENT")])
async def test_acknowledgement_must_also_match_the_parent_thread(monkeypatch, returned_thread, expected):
    original = httpx.AsyncClient
    result = {"ok": True, "channel": "C01234567", "ts": "1793249999.123456", "message": {"thread_ts": returned_thread}}
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)), **kwargs),
    )
    reply = await SlackAPI().call(
        "chat.postMessage", TOKEN, {"channel": "C01234567", "thread_ts": "1793074062.301049", "text": "test"}
    )
    assert reply["delivery"] == expected


@pytest.mark.asyncio
async def test_admin_permission_is_checked_before_reading_or_writing_any_credential(monkeypatch):
    monkeypatch.setattr(integration_api, "document_intake", Mock(side_effect=AssertionError("must not access storage")))
    actor = SimpleNamespace(id="other", is_superuser=False)
    with pytest.raises(HTTPException) as exc:
        await integration_api.slack_notifications(actor, Response())
    assert exc.value.status_code == 403
    command = integration_api.SlackCredential(token=TOKEN)
    assert TOKEN not in command.model_dump_json()
    with pytest.raises(HTTPException) as exc:
        await integration_api.save_slack_notifications(command, actor)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_connection_update_retries_only_a_known_rejected_current_notice(notifications):
    notifier, _, gateway, _ = notifications
    gateway.call.return_value = {"delivery": "ERROR", "error": "SLACK_INVALID_AUTH"}
    await notifier.observe("owner", 1)
    await notifier.deliver()
    event_id = notifier.history("owner", 1)[0]["id"]
    gateway.call.return_value = {"delivery": "SENT", "bot_id": "B01234567", "url": "https://adlcfactory.slack.com/"}
    await notifier.connect("owner", TOKEN)
    assert notifier.history("owner", 1)[0]["state"] == "PENDING"
    await notifier.deliver()
    assert notifier.history("owner", 1)[0]["id"] == event_id
    assert notifier.history("owner", 1)[0]["state"] == "SENT"

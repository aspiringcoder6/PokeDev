import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "lark_probe", Path(__file__).with_name("probe.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def event(identity="event-test"):
    return {
        "header": {
            "event_id": identity,
            "event_type": "im.message.receive_v1",
            "tenant_key": "test-tenant",
            "app_id": "test-app",
        },
        "event": {
            "token": "test-only-secret",
            "message": {"message_id": "test-message", "content": "Synthetic request"},
        },
    }


def test_event_duplicate_is_scoped_by_app_and_tenant(tmp_path):
    journal = probe.IngressJournal(tmp_path / "events.sqlite3")
    assert journal.record(event())["stored"]
    assert not journal.record(event())["stored"]
    other = event()
    other["header"]["tenant_key"] = "other-tenant"
    assert journal.record(other)["stored"]
    assert journal.count() == 2


def test_journal_survives_crash_before_callback_returns(tmp_path):
    path = tmp_path / "crash.sqlite3"
    script = "import sys,os,json;sys.path.insert(0,sys.argv[1]);from probe import IngressJournal;IngressJournal(sys.argv[2]).record(json.loads(sys.argv[3]));os._exit(42)"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(Path(__file__).parent),
            str(path),
            json.dumps(event()),
        ]
    )
    assert result.returncode == 42
    journal = probe.IngressJournal(path)
    assert journal.count() == 1
    assert not journal.record(event())["stored"]


def test_event_tokens_are_redacted_in_the_journal(tmp_path):
    journal = probe.IngressJournal(tmp_path / "redacted.sqlite3")
    journal.record(event())
    with journal.connect() as db:
        stored = db.execute("SELECT payload FROM events").fetchone()[0]
    assert "test-only-secret" not in stored
    assert "[redacted]" in stored


def test_unverified_live_checks_are_never_reported_as_passed(monkeypatch):
    monkeypatch.setattr(probe, "credentials", lambda: ("", ""))
    report = probe.sdk_report()
    assert report["domain"] == "https://open.larksuite.com"
    assert report["credentials_present"] is False
    assert set(report["live_checks"].values()) == {"NOT_RUN"}


def test_real_sdk_dispatch_commits_before_return_and_recovers_after_failure(
    tmp_path, monkeypatch
):
    pytest.importorskip("lark_oapi")
    journal = probe.IngressJournal(tmp_path / "dispatch.sqlite3")
    handler = probe.build_handler(journal)
    original = journal.record

    def fail_after_commit(payload):
        original(payload)
        raise RuntimeError("simulated failure before ACK")

    monkeypatch.setattr(journal, "record", fail_after_commit)
    payload = json.dumps({"schema": "2.0", **event()}).encode()
    with pytest.raises(RuntimeError, match="before ACK"):
        handler._do_without_validation(payload)
    assert journal.count() == 1
    monkeypatch.setattr(journal, "record", original)
    handler._do_without_validation(payload)
    assert journal.count() == 1


def test_real_sdk_card_event_dispatch_is_distinct_from_ws_transport(tmp_path):
    pytest.importorskip("lark_oapi")
    journal = probe.IngressJournal(tmp_path / "card.sqlite3")
    payload = event("card-event-test")
    payload["schema"] = "2.0"
    payload["header"]["event_type"] = "card.action.trigger"
    payload["event"] = {
        "operator": {"open_id": "test-user"},
        "token": "test-only-callback",
        "context": {"open_message_id": "test-message"},
        "action": {"tag": "button", "value": {"probe": True}},
    }
    response = probe.build_handler(journal)._do_without_validation(
        json.dumps(payload).encode()
    )
    assert response is not None
    assert journal.count() == 1

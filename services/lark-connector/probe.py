"""LI-00 receive-only Lark probe. No messages, agent calls or domain writes."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = "https://open.larksuite.com"
DEFAULT_JOURNAL = ROOT / "adlc-flow/data/local/lark-probe/events.sqlite3"
SECRET = re.compile(r"token|secret|authorization|password|encrypt.?key", re.I)


def sanitized(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if SECRET.search(key) else sanitized(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


class IngressJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (event_key TEXT PRIMARY KEY, kind TEXT NOT NULL, received_at TEXT NOT NULL, payload_digest TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def record(self, payload: dict) -> dict:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(encoded.encode()) > 2_000_000:
            raise ValueError("LARK_PROBE_EVENT_TOO_LARGE")
        header = payload.get("header") or {}
        event_id = header.get("event_id")
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        # This is a transport probe, not production callback dedup. Capture the
        # fallback explicitly until real tenant fixtures establish stable IDs.
        key_kind = "event_id" if event_id else "payload_hash"
        key = json.dumps(
            [header.get("app_id"), header.get("tenant_key"), event_id or fingerprint]
        )
        kind = str(header.get("event_type") or "unknown")
        with self.connect() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)",
                (
                    key,
                    kind,
                    datetime.now(timezone.utc).isoformat(),
                    fingerprint,
                    json.dumps(sanitized(payload), ensure_ascii=False),
                ),
            )
            stored = result.rowcount == 1
        # Exiting the transaction commits before the SDK callback can return.
        return {"kind": kind, "stored": stored, "key_kind": key_kind}

    def count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def credentials():
    values = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    keys = ["POKEDEV_LARK_APP_ID", "POKEDEV_LARK_APP_SECRET"]
    return tuple(os.environ.get(key) or values.get(key, "") for key in keys)


def sdk_report():
    versions = {}
    for package in ("lark-channel-sdk", "lark-oapi", "websockets"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    card_branch = "not_inspected"
    source_hash = None
    if versions["lark-oapi"]:
        source = Path(
            importlib.metadata.distribution("lark-oapi").locate_file(
                "lark_oapi/ws/client.py"
            )
        ).read_text(encoding="utf-8")
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        if re.search(r"elif message_type == MessageType\.CARD:\s*return", source):
            card_branch = "returns_without_dispatch"
        else:
            card_branch = "requires_live_verification"
    app, secret = credentials()
    return {
        "domain": DOMAIN,
        "versions": versions,
        "credentials_present": bool(app and secret),
        "ws_client_source_sha256": source_hash,
        "card_frame_branch": card_branch,
        "live_checks": {
            name: "NOT_RUN"
            for name in [
                "dm",
                "mention",
                "unmentioned_reply",
                "card",
                "form",
                "doc_allowed",
                "doc_denied",
                "redelivery",
            ]
        },
    }


def build_handler(journal: IngressJournal):
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )

    def received(data):
        start = time.monotonic()
        result = journal.record(json.loads(lark.JSON.marshal(data)))
        print(
            json.dumps(
                {**result, "journal_ms": round((time.monotonic() - start) * 1000, 1)}
            ),
            flush=True,
        )

    def card(data):
        received(data)
        return P2CardActionTriggerResponse({})

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(received)
        .register_p2_card_action_trigger(card)
        .build()
    )


def listen(journal: IngressJournal):
    app, secret = credentials()
    if not app or not secret:
        raise RuntimeError(
            "Set POKEDEV_LARK_APP_ID and POKEDEV_LARK_APP_SECRET in this project's .env"
        )
    import lark_oapi as lark

    handler = build_handler(journal)
    print(
        "Receive-only probe starting; payloads stay in the local journal. No automatic replies.",
        flush=True,
    )
    client = lark.ws.Client(
        app,
        secret,
        domain=DOMAIN,
        event_handler=handler,
        log_level=lark.LogLevel.WARNING,
    )
    client.start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Connect to Lark and journal incoming events; never send messages",
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    args = parser.parse_args()
    if args.listen:
        listen(IngressJournal(args.journal))
    else:
        print(json.dumps(sdk_report(), indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except KeyboardInterrupt:
        print("Probe stopped.")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

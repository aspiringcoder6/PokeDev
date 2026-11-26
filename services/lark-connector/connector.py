"""LI-02 optional DM connector. Durable ingress and explicit send outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from pokedev_lark_contracts import (
    Delivery,
    DeliveryBatch,
    DeliveryResult,
    InboundMessage,
    IngestReceipt,
    v2,
)
from probe import DOMAIN, ROOT, credentials

PAIR = re.compile(r"^/link ([A-Za-z0-9_-]{32})$")
DEFAULT_JOURNAL = ROOT / "adlc-flow/data/local/lark-connector/transport.sqlite3"


@contextmanager
def exclusive_worker(path):
    stream = Path(str(path) + ".lock").open("a+b")
    try:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        stream.close()


def normalize(payload):
    header, event = payload.get("header") or {}, payload.get("event") or {}
    message, sender = event.get("message") or {}, event.get("sender") or {}
    if (
        header.get("event_type") != "im.message.receive_v1"
        or message.get("chat_type") != "p2p"
        or sender.get("sender_type") != "user"
    ):
        return None
    body = {
        "app_id": header.get("app_id"),
        "tenant_key": header.get("tenant_key"),
        "event_id": header.get("event_id"),
        "message_id": message.get("message_id"),
        "chat_id": message.get("chat_id"),
        "open_id": (sender.get("sender_id") or {}).get("open_id"),
        "parent_id": message.get("parent_id") or None,
        "root_id": message.get("root_id") or None,
        "kind": "unsupported",
    }
    if message.get("message_type") == "text":
        try:
            content = json.loads(message.get("content") or "{}").get("text")
        except (ValueError, AttributeError):
            content = None
        if isinstance(content, str) and content.strip() and len(content) <= 20000:
            match = PAIR.fullmatch(content.strip())
            if match:
                body.update(
                    kind="pair",
                    pair_digest=hashlib.sha256(match[1].encode()).hexdigest(),
                )
            elif not content.strip().startswith("/link"):
                body.update(kind="text", text=content)
    return InboundMessage.model_validate(body)


def normalize_v2(payload, *, bot_open_id, group_ids=()):
    header, event = payload.get("header") or {}, payload.get("event") or {}
    message, sender = event.get("message") or {}, event.get("sender") or {}
    if (
        header.get("event_type") != "im.message.receive_v1"
        or sender.get("sender_type") != "user"
    ):
        return None
    chat_type = message.get("chat_type")
    if chat_type not in {"p2p", "group"}:
        return None
    mentions = message.get("mentions") or []
    ids = list(
        dict.fromkeys(
            item["id"]["open_id"]
            for item in mentions
            if isinstance(item, dict)
            and isinstance(item.get("id"), dict)
            and item["id"].get("open_id")
        )
    )
    mentioned = bool(bot_open_id and bot_open_id in ids)
    try:
        content = json.loads(message.get("content") or "{}")
        text = content.get("text")
    except (ValueError, AttributeError):
        text = None
    if isinstance(text, str) and mentioned:
        for item in mentions:
            if (item.get("id") or {}).get("open_id") == bot_open_id:
                key = item.get("key", "")
                if re.fullmatch(r"@_user_\d+", key):
                    text = re.sub(re.escape(key) + r"(?![A-Za-z0-9_])", "", text)
        text = text.strip()
    discovery = (
        chat_type == "group"
        and mentioned
        and message.get("message_type") == "text"
        and text == "/probe"
    )
    if chat_type == "group":
        if not discovery and message.get("chat_id") not in group_ids:
            return None
        if not mentioned and not (
            message.get("parent_id")
            or message.get("root_id")
            or message.get("thread_id")
        ):
            return None
    normalized = normalize(
        {
            **payload,
            "event": {
                **event,
                "message": {
                    **message,
                    "chat_type": "p2p",
                    "content": json.dumps({"text": text})
                    if isinstance(text, str)
                    else message.get("content"),
                },
            },
        }
    )
    if normalized is None:
        return None
    body = normalized.model_dump(mode="json", exclude={"version"})
    if discovery:
        body.update(kind="unsupported", text=None, pair_digest=None)
    return v2.InboundMessage(
        **body,
        chat_type=chat_type,
        thread_id=message.get("thread_id") or None,
        mentioned_open_ids=ids,
        discovery=discovery,
    )


def load_message(payload):
    body = json.loads(payload)
    return (
        v2.InboundMessage if body.get("version") == "2" else InboundMessage
    ).model_validate(body)


def load_delivery(payload):
    body = json.loads(payload)
    return (v2.Delivery if body.get("version") == "2" else Delivery).model_validate(
        body
    )


def result_type(delivery):
    return v2.DeliveryResult if isinstance(delivery, v2.Delivery) else DeliveryResult


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS inbox (
                  key TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING');
                CREATE TABLE IF NOT EXISTS sends (
                  id TEXT NOT NULL, lease TEXT NOT NULL, delivery TEXT NOT NULL,
                  result TEXT, acked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(id,lease));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def record(self, message: InboundMessage):
        key = json.dumps([message.app_id, message.tenant_key, message.event_id])
        payload = message.model_dump_json()
        with self.connect() as db:
            prior = db.execute(
                "SELECT payload FROM inbox WHERE key=?", (key,)
            ).fetchone()
            if prior and prior[0] != payload:
                raise ValueError("LARK_EVENT_CONFLICT")
            db.execute(
                "INSERT OR IGNORE INTO inbox(key,payload) VALUES (?,?)", (key, payload)
            )

    def pending(self):
        with self.connect() as db:
            return [
                (key, load_message(payload))
                for key, payload in db.execute(
                    "SELECT key,payload FROM inbox WHERE state='PENDING' ORDER BY rowid LIMIT 20"
                )
            ]

    def accepted(self, key):
        with self.connect() as db:
            db.execute("UPDATE inbox SET state='ACCEPTED' WHERE key=?", (key,))

    def begin_send(self, delivery: Delivery):
        with self.connect() as db:
            prior = db.execute(
                "SELECT delivery FROM sends WHERE id=? AND lease=?",
                (str(delivery.id), str(delivery.lease_id)),
            ).fetchone()
            if prior:
                if prior[0] != delivery.model_dump_json():
                    raise ValueError("LARK_DELIVERY_CONFLICT")
                return False
            db.execute(
                "INSERT INTO sends(id,lease,delivery) VALUES (?,?,?)",
                (str(delivery.id), str(delivery.lease_id), delivery.model_dump_json()),
            )
            return True

    def finish_send(self, delivery, result):
        with self.connect() as db:
            db.execute(
                "UPDATE sends SET result=? WHERE id=? AND lease=?",
                (result.model_dump_json(), str(delivery.id), str(delivery.lease_id)),
            )

    def unreported(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT delivery,result FROM sends WHERE acked=0"
            ).fetchall()
        for raw, result in rows:
            delivery = load_delivery(raw)
            if result is None:
                result = result_type(delivery)(
                    lease_id=delivery.lease_id,
                    state="UNCONFIRMED",
                    error_code="PROCESS_INTERRUPTED",
                )
                self.finish_send(delivery, result)
            else:
                result = result_type(delivery).model_validate_json(result)
            yield delivery, result

    def reported(self, delivery):
        with self.connect() as db:
            db.execute(
                "UPDATE sends SET acked=1 WHERE id=? AND lease=?",
                (str(delivery.id), str(delivery.lease_id)),
            )


class Backend:
    def __init__(self, url, secret, *, client=None, version=1):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LARK_BACKEND_URL_INVALID")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("LARK_BACKEND_HTTPS_REQUIRED")
        if len(secret) < 32:
            raise ValueError("LARK_CONNECTOR_SECRET_REQUIRED")
        self.base = url.rstrip("/") + "/api/v1/adlc/intake/lark"
        self.secret = secret
        self.version = version
        self.client = client or httpx.Client(
            timeout=10, follow_redirects=False, trust_env=False
        )

    def post(self, path, body=None):
        response = self.client.post(
            self.base + path,
            headers={"Authorization": "Bearer " + self.secret},
            json=body,
        )
        if not response.is_success:
            raise RuntimeError("LARK_BACKEND_UNAVAILABLE")
        return response.json()

    def ingest(self, message):
        current = isinstance(message, v2.InboundMessage)
        return (v2.IngestReceipt if current else IngestReceipt).model_validate(
            self.post(
                ("/v2" if current else "") + "/events", message.model_dump(mode="json")
            )
        )

    def claim(self):
        prefix = "/v2" if self.version == 2 else ""
        batch = v2.DeliveryBatch if self.version == 2 else DeliveryBatch
        return batch.model_validate(self.post(prefix + "/deliveries/claim")).items

    def result(self, delivery, result):
        prefix = "/v2" if isinstance(delivery, v2.Delivery) else ""
        self.post(
            prefix + f"/deliveries/{delivery.id}/result", result.model_dump(mode="json")
        )


class LarkSender:
    def __init__(self, app_id, secret, *, client=None):
        self.app_id, self.secret = app_id, secret
        self.client = client or httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        )
        self.token, self.expires_at = "", 0

    def access_token(self):
        if self.token and self.expires_at > time.monotonic() + 60:
            return self.token
        response = self.client.post(
            DOMAIN + "/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.secret},
        )
        payload = response.json()
        if (
            response.status_code != 200
            or not isinstance(payload, dict)
            or type(payload.get("code")) is not int
            or payload.get("code") != 0
            or not isinstance(payload.get("tenant_access_token"), str)
            or not re.fullmatch(r"[!-~]{1,4096}", payload["tenant_access_token"])
            or type(payload.get("expire")) is not int
            or not 1 <= payload["expire"] <= 86400
        ):
            raise ValueError("LARK_APP_AUTH_FAILED")
        self.token = payload["tenant_access_token"]
        self.expires_at = time.monotonic() + int(payload["expire"])
        return self.token

    def bot_identity(self):
        try:
            response = self.client.get(
                DOMAIN + "/open-apis/bot/v3/info",
                headers={"Authorization": "Bearer " + self.access_token()},
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise ValueError("LARK_BOT_IDENTITY_UNAVAILABLE") from None
        bot = payload.get("bot") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or not response.is_success
            or type(payload.get("code")) is not int
            or payload.get("code") != 0
            or not isinstance(bot, dict)
            or not isinstance(bot.get("open_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", bot["open_id"])
        ):
            raise ValueError("LARK_BOT_IDENTITY_UNAVAILABLE")
        return bot["open_id"]

    def send(self, delivery):
        def outcome(state, code=None, **kwargs):
            return result_type(delivery)(
                lease_id=delivery.lease_id, state=state, error_code=code, **kwargs
            )

        try:
            token = self.access_token()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return outcome("RETRY", "APP_AUTH_FAILED")
        try:
            response = self.client.post(
                DOMAIN
                + "/open-apis/im/v1/messages/"
                + quote(delivery.reply_to, safe="")
                + "/reply",
                headers={"Authorization": "Bearer " + token},
                json={
                    "msg_type": "text",
                    "content": json.dumps({"text": delivery.text}, ensure_ascii=False),
                    "reply_in_thread": getattr(delivery, "reply_in_thread", False),
                    "uuid": str(delivery.uuid),
                },
            )
        except httpx.HTTPError:
            return outcome("UNCONFIRMED", "SEND_TRANSPORT_UNCONFIRMED")
        try:
            payload = response.json()
        except ValueError:
            return outcome("UNCONFIRMED", "SEND_RESPONSE_UNCONFIRMED")
        if not isinstance(payload, dict):
            return outcome("UNCONFIRMED", "SEND_RESPONSE_UNCONFIRMED")
        if type(payload.get("code")) is not int:
            return outcome("UNCONFIRMED", "SEND_RESPONSE_UNCONFIRMED")
        if response.status_code == 429 or payload.get("code") == 99991400:
            try:
                delay = min(
                    3600, max(1, int(response.headers.get("retry-after", "60")))
                )
            except ValueError:
                delay = 60
            return outcome("RETRY", "RATE_LIMITED", retry_after=delay)
        if payload.get("code") == 99991663:
            self.token = ""
            return outcome("RETRY", "TOKEN_EXPIRED")
        if response.status_code >= 500:
            return outcome("UNCONFIRMED", "PROVIDER_SERVER_UNCONFIRMED")
        if not response.is_success or payload.get("code") != 0:
            return outcome("FAILED", "PROVIDER_REJECTED")
        data = payload.get("data") or {}
        if (
            not isinstance(data, dict)
            or data.get("chat_id") != delivery.chat_id
            or not data.get("message_id")
        ):
            return outcome("UNCONFIRMED", "PROVIDER_RECEIPT_UNCONFIRMED")
        return outcome("DELIVERED", provider_message_id=data["message_id"])


class Worker:
    def __init__(self, journal, backend, sender):
        self.journal, self.backend, self.sender = journal, backend, sender

    def report(self):
        for delivery, result in self.journal.unreported():
            self.backend.result(delivery, result)
            self.journal.reported(delivery)

    def once(self):
        self.report()
        for key, message in self.journal.pending():
            receipt = self.backend.ingest(message)
            if receipt.event_id != message.event_id:
                raise ValueError("LARK_INGRESS_RECEIPT_INVALID")
            self.journal.accepted(key)
        for delivery in self.backend.claim():
            if not self.journal.begin_send(delivery):
                continue
            result = self.sender.send(delivery)
            self.journal.finish_send(delivery, result)
        self.report()


def local_config():
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    return {**values, **os.environ}


def run(args):
    config = local_config()
    app, secret = credentials()
    tenant = config.get("POKEDEV_LARK_TENANT_KEY", "")
    if not app or not secret or not tenant:
        raise ValueError("LARK_APP_AND_TENANT_REQUIRED")
    journal = Journal(args.journal)
    backend = Backend(
        config.get("POKEDEV_LARK_BACKEND_URL", "http://127.0.0.1:7862"),
        config.get("POKEDEV_LARK_CONNECTOR_SECRET", ""),
        version=2
        if config.get("POKEDEV_LARK_CONVERSATIONS_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
        else 1,
    )
    sender = LarkSender(app, secret)
    group_ids, bot_id = set(), ""
    if backend.version == 2 and not args.once:
        bot_id = sender.bot_identity()
        if (
            config.get("POKEDEV_LARK_BOT_OPEN_ID")
            and config["POKEDEV_LARK_BOT_OPEN_ID"] != bot_id
        ):
            raise ValueError("LARK_BOT_IDENTITY_MISMATCH")
        if config.get("POKEDEV_LARK_GROUPS_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            group_config = json.loads(config.get("POKEDEV_LARK_GROUPS_JSON", "{}"))
            if not isinstance(group_config, dict):
                raise ValueError("LARK_GROUP_CONFIGURATION_INVALID")
            for identity, policy in group_config.items():
                v2.GroupPolicy.model_validate(policy)
                if not isinstance(identity, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,256}", identity
                ):
                    raise ValueError("LARK_GROUP_CONFIGURATION_INVALID")
                group_ids.add(identity)
    worker = Worker(journal, backend, sender)
    if args.once:
        worker.once()
        print("Connector drain completed.")
        return
    import lark_oapi as lark

    stop = threading.Event()

    def receive(data):
        payload = json.loads(lark.JSON.marshal(data))
        message = (
            normalize_v2(payload, bot_open_id=bot_id, group_ids=group_ids)
            if backend.version == 2
            else normalize(payload)
        )
        if message is None or message.app_id != app or message.tenant_key != tenant:
            return
        journal.record(message)
        metadata = {"received": True, "kind": message.kind}
        if getattr(message, "discovery", False):
            metadata.update(group_probe=True, chat_id=message.chat_id)
        print(json.dumps(metadata), flush=True)

    def work():
        while not stop.is_set():
            try:
                worker.once()
            except (httpx.HTTPError, RuntimeError, ValueError, sqlite3.Error):
                print(
                    "Connector waiting for backend or delivery reconciliation; local work retained.",
                    flush=True,
                )
                stop.wait(5)
            stop.wait(1)

    thread = threading.Thread(target=work, daemon=True, name="lark-intake-delivery")
    thread.start()
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(receive)
        .build()
    )
    try:
        print(
            f"PokeDev Lark connector starting; wire v{backend.version}, DM intake and receipts enabled.",
            flush=True,
        )
        lark.ws.Client(
            app,
            secret,
            domain=DOMAIN,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        ).start()
    finally:
        stop.set()
        thread.join(timeout=5)
        backend.client.close()
        sender.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bot-info",
        action="store_true",
        help="Read the dedicated bot open_id without starting a consumer or printing credentials",
    )
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument(
        "--once",
        action="store_true",
        help="Drain local work without starting a WebSocket",
    )
    args = parser.parse_args()
    if args.bot_info:
        app, secret = credentials()
        sender = LarkSender(app, secret)
        try:
            print(json.dumps({"bot_open_id": sender.bot_identity()}))
        finally:
            sender.client.close()
        return
    args.journal.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_worker(args.journal):
        run(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Connector stopped; durable work retained.")
    except (RuntimeError, ValueError, OSError):
        print(
            "Connector could not start; check the dedicated PokeDev configuration.",
            file=sys.stderr,
        )
        sys.exit(1)

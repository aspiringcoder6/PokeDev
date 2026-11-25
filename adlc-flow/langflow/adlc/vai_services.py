"""Bounded vAI service checks, with durable intent and no create replay.

These observations are advisory. They never approve a plan or issue a Verify receipt.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from dotenv import dotenv_values

SERVICES = ("sandbox", "memory", "testforge")
TARGET = os.getenv("POKEDEV_TESTFORGE_TARGET_URL", "http://127.0.0.1:7862/work")
ROOT = "/api/v1/pokedev-services"
ACTIVE = {"RESERVED", "RUNNING", "UNCONFIRMED"}


class ServiceCheckError(Exception):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code, self.status = code, status


def now():
    return datetime.now(timezone.utc).isoformat()


def redact(value, depth=0):
    if depth > 16:
        return "[nested data omitted]"
    if isinstance(value, str):
        value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", value[:24000])
        return re.sub(r"(?i)([?&](?:token|password|api_key)=)[^&\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {key: "[redacted]" if re.search(r"(?i)password|secret|authorization|credential|(?:^|_)token$|api.?key", key)
                else redact(item, depth + 1) for key, item in list(value.items())[:100]}
    return value


def settings():
    base, token = os.getenv("VAI_PLATFORM_URL", ""), os.getenv("VAI_PLATFORM_TOKEN", "")
    if not (base and token):
        project = Path(__file__).resolve().parents[2]
        path = Path(os.getenv("ADLC_VAI_PLATFORM_ENV_FILE", str(project.parent / ".env.vai-platform.local")))
        try:
            values = dotenv_values(path) if path.is_file() else {}
        except OSError:
            raise ServiceCheckError("VAI_SERVICES_NOT_CONFIGURED", 503) from None
        base, token = base or values.get("VAI_PLATFORM_URL", ""), token or values.get("VAI_PLATFORM_TOKEN", "")
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"} or not token):
        raise ServiceCheckError("VAI_SERVICES_NOT_CONFIGURED", 503)
    return base.rstrip("/"), token


class PlatformClient:
    def __init__(self):
        self._capabilities = None
        self._capabilities_at = 0
        self._client = None
        self._key = None
        self._auth_lock = asyncio.Lock()

    async def request(self, method, path, body=None):
        # Observations may retry a transient gateway failure; a create is sent once.
        for attempt in range(2 if method == "GET" else 1):
            try:
                return await self._request_once(method, path, body)
            except ServiceCheckError as exc:
                if method != "GET" or attempt or exc.code != "VAI_PLATFORM_UNAVAILABLE":
                    raise
                await asyncio.sleep(0.6)

    async def _request_once(self, method, path, body=None):
        try:
            from dsh_web_sdk import DshClient, RetryConfig
        except ImportError:
            raise ServiceCheckError("VAI_SDK_NOT_INSTALLED", 503) from None

        base, token = settings()
        try:
            async with self._auth_lock:
                if self._client is None or self._key != (base, token):
                    candidate = DshClient(base, token, timeout=15, retry=RetryConfig(max_attempts=1))
                    await candidate.__aenter__()
                    self._client, self._key = candidate, (base, token)
                    self._capabilities = None
                client = self._client
            if method == "POST":
                return await client.http_post(path, body, timeout=15)
            return await client.http_get(path, timeout=15)
        except Exception as exc:  # transport text can contain credentials; expose stable codes only
            if type(exc).__name__ == "DshAuthError":
                self._client = None  # refresh auth on the next observation; never replay a POST
                if getattr(exc.__cause__, "code", None) == 401:
                    raise ServiceCheckError("VAI_PLATFORM_AUTH_FAILED", 503) from None
            code = getattr(exc, "code", "")
            if code == "http/404":
                raise ServiceCheckError("VAI_RECEIPT_NOT_FOUND", 503) from None
            if code == "http/409":
                native_code = re.search(r'"error_code"\s*:\s*"(LOOP_[A-Z_]+)"', str(exc))
                if native_code:
                    raise ServiceCheckError(native_code.group(1), 409) from None
                raise ServiceCheckError("VAI_CHECK_CONFLICT", 409) from None
            raise ServiceCheckError("VAI_PLATFORM_UNAVAILABLE", 503) from None

    async def capabilities(self):
        if self._capabilities is not None and time.monotonic() - self._capabilities_at < 10:
            return self._capabilities
        try:
            value = await self.request("GET", ROOT + "/capabilities")
        except ServiceCheckError as exc:
            if exc.code == "VAI_RECEIPT_NOT_FOUND":
                raise ServiceCheckError("VAI_BRIDGE_UNAVAILABLE", 503) from None
            raise
        if value.get("version") != "0.1.0" or value.get("no_agent_created") is not True:
            raise ServiceCheckError("VAI_BRIDGE_RELEASE_MISMATCH", 503)
        self._capabilities = {key: value.get(key) for key in ("version", "services", "allowed_targets")}
        self._capabilities_at = time.monotonic()
        return self._capabilities


class CheckStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS service_checks (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, delivery TEXT NOT NULL,
                cycle TEXT NOT NULL, service TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS service_checks_scope ON service_checks(owner,delivery,cycle)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def list(self, owner, delivery, cycle):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM service_checks WHERE owner=? AND delivery=? AND cycle=? ORDER BY rowid DESC LIMIT 60",
                              (owner, delivery, cycle)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def reserve(self, owner, delivery, cycle, service, identity):
        scope = hashlib.sha256(json.dumps([owner, delivery, cycle], separators=(",", ":")).encode()).hexdigest()
        command = {"check_id": identity, "service": service, "scope_id": scope}
        if service == "testforge":
            command["target_url"] = TARGET
        digest = hashlib.sha256(json.dumps([service, scope, command.get("target_url")], separators=(",", ":")).encode()).hexdigest()
        value = {**command, "request_digest": digest, "cycle_id": cycle, "state": "RESERVED",
                 "created_at": now(), "updated_at": now(), "verification_evidence": False}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT owner,delivery,cycle,payload FROM service_checks WHERE id=?", (identity,)).fetchone()
            if old:
                if old[:3] != (owner, delivery, cycle) or json.loads(old[3])["request_digest"] != digest:
                    raise ServiceCheckError("VAI_CHECK_ID_CONFLICT")
                return json.loads(old[3]), False
            rows = db.execute("SELECT payload FROM service_checks WHERE owner=?", (owner,)).fetchall()
            active = [json.loads(row[0]) for row in rows if json.loads(row[0])["state"] in ACTIVE]
            if any(row["scope_id"] == scope and row["service"] == service for row in active):
                raise ServiceCheckError("VAI_CHECK_ALREADY_ACTIVE")
            if len(active) >= 3:
                raise ServiceCheckError("VAI_CHECK_CAPACITY")
            db.execute("INSERT INTO service_checks VALUES (?,?,?,?,?,?)", (identity, owner, delivery, cycle, service, json.dumps(value)))
        return value, True

    def update(self, identity, update):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM service_checks WHERE id=?", (identity,)).fetchone()
            value = json.loads(row[0])
            value.update(redact(update))
            value["updated_at"] = now()
            value["verification_evidence"] = False
            db.execute("UPDATE service_checks SET payload=? WHERE id=?", (json.dumps(value), identity))
        return value


class CheckService:
    def __init__(self, store, client=None):
        self.store, self.client = store, client or PlatformClient()
        self.tasks = {}

    def spawn(self, row, *, create=False):
        identity = row["check_id"]
        if identity not in self.tasks:
            task = asyncio.create_task(self.follow(row, create=create))
            self.tasks[identity] = task
            task.add_done_callback(lambda _task: self.tasks.pop(identity, None))

    async def follow(self, row, *, create=False):
        identity = row["check_id"]
        try:
            if create:
                self.store.update(identity, {"state": "UNCONFIRMED"})
                command = {key: row[key] for key in ("check_id", "service", "scope_id", "target_url") if key in row}
                result = await self.client.request("POST", ROOT + "/checks", command)
                self.accept(row, result)
            for _ in range(220):
                recovery = {key: row[key] for key in ("service", "scope_id", "job_id") if row.get(key)}
                result = await self.client.request("GET", ROOT + "/checks/" + identity + "?" + urlencode(recovery))
                self.accept(row, result)
                if result["state"] not in ACTIVE:
                    return
                await asyncio.sleep(2)
            self.store.update(identity, {"state": "UNCONFIRMED", "error_code": "VAI_CHECK_STILL_PENDING"})
        except ServiceCheckError as exc:
            # A lost create response or remote restart is never permission to resend create.
            self.store.update(identity, {"state": "UNCONFIRMED", "error_code": exc.code})
        except Exception:  # never expose backend exceptions or allow an unobserved task
            self.store.update(identity, {"state": "UNCONFIRMED", "error_code": "VAI_RESULT_INVALID"})

    def accept(self, row, result):
        if (not isinstance(result, dict) or any(result.get(k) != row.get(k) for k in
                ("check_id", "service", "scope_id", "request_digest"))
                or result.get("state") not in {"RUNNING", "SUCCEEDED", "FAILED", "UNCONFIRMED"}
                or result.get("verification_evidence") is not False):
            raise ServiceCheckError("VAI_RESULT_SCOPE_MISMATCH", 503)
        allowed = {key: result[key] for key in ("state", "steps", "summary", "error", "job_id", "session_id", "dataset") if key in result}
        allowed["error_code"] = None
        self.store.update(row["check_id"], allowed)


@lru_cache(maxsize=1)
def service_checks():
    default = Path(__file__).resolve().parents[2] / "data" / "vai-services" / "checks.sqlite3"
    return CheckService(CheckStore(os.getenv("ADLC_VAI_CHECKS_DB", str(default))))

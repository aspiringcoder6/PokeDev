"""Authenticated bounded client for the new H6A execution-plane endpoint."""

# ruff: noqa: EM101 - transport exceptions expose fixed codes only.

import hashlib
import hmac
import json
import os
from functools import lru_cache
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from langflow.adlc.verification_models import MAX_EVIDENCE_BYTES, ExecutionReceipt, VerificationError
from langflow.adlc.verification_repository import RUNNER_DIGEST

MIN_TOKEN_LENGTH = 32
MAX_PORT = 65535


class VerificationWorkerClient:
    api_root = "/api/v1/adlc-harness-verify"
    response_limit = MAX_EVIDENCE_BYTES

    def __init__(self, base_url=None, token=None, *, transport=None):
        self.base_url = (base_url if base_url is not None else os.getenv("ADLC_VERIFICATION_WORKER_URL", "")).rstrip(
            "/"
        )
        self.token = token if token is not None else os.getenv("ADLC_VERIFICATION_WORKER_TOKEN", "")
        self.transport = transport

    @property
    def configured(self):
        try:
            url = urlsplit(self.base_url)
            port = url.port
        except ValueError:
            return False
        return (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and (port is None or 0 < port <= MAX_PORT)
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and (url.scheme == "https" or url.hostname in {"localhost", "127.0.0.1", "::1"})
            and url.path.endswith(self.api_root)
            and len(self.token) >= MIN_TOKEN_LENGTH
        )

    async def request(self, method, path, body=None):
        if not self.configured:
            raise VerificationError("VERIFICATION_WORKER_NOT_CONFIGURED", 503)
        try:
            async with (
                httpx.AsyncClient(transport=self.transport, timeout=10, follow_redirects=False) as client,
                client.stream(
                    method, self.base_url + path, json=body, headers={"Authorization": "Bearer " + self.token}
                ) as response,
            ):
                if response.status_code not in {200, 202}:
                    raise VerificationError("VERIFICATION_WORKER_UNAVAILABLE", 503)
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.response_limit:
                        raise VerificationError("VERIFICATION_EVIDENCE_TOO_LARGE", 413)
                    chunks.append(chunk)
                result = json.loads(b"".join(chunks))
                if not isinstance(result, dict):
                    raise VerificationError("VERIFICATION_WORKER_RESPONSE_INVALID", 422)
                return result
        except VerificationError:
            raise
        except (httpx.HTTPError, ValueError, UnicodeError, RecursionError):
            # In particular, a POST timeout is never retried automatically.
            raise VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED", 503) from None

    async def health(self):
        if not self.configured:
            return {"ready": False, "provider": None}
        result = await self.request("GET", "/health")
        if (
            type(result.get("ready")) is not bool
            or result.get("profile_ref") != "verification-profile:json-fixture/0.1.0"
            or result.get("runner_ref") != "runner:adlc-json-fixture/0.1.0"
            or result.get("provider") not in ("disabled", "local-fixture", "sandbox-kit")
            or (result["ready"] and result["provider"] == "disabled")
        ):
            raise VerificationError("VERIFICATION_WORKER_RESPONSE_INVALID", 422)
        if result.get("runner_digest") != RUNNER_DIGEST:
            raise VerificationError("VERIFICATION_RUNNER_MISMATCH", 503)
        return result

    async def create(self, record, content):
        result = await self.request(
            "POST",
            "/executions",
            {
                "execution_id": str(record.execution_id),
                "plan_digest": record.plan_digest,
                "candidate_digest": record.plan.candidate.content_digest,
                "candidate": content,
                "cases": [{"case_id": c.case_id, "pointer": c.pointer} for c in record.plan.cases],
                "timeout_seconds": record.plan.timeout_seconds,
            },
        )
        if result.get("execution_id") != str(record.execution_id) or result.get("state") not in (
            "RUNNING",
            "READY",
            "DISPATCH_UNCERTAIN",
            "NOT_VERIFIED",
        ):
            raise VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED", 503)
        return result

    async def read(self, execution_id):
        result = await self.request("GET", "/executions/" + str(execution_id))
        if result.get("execution_id") != str(execution_id):
            raise VerificationError("VERIFICATION_EXECUTION_MISMATCH")
        if result.get("state") not in ("RUNNING", "DISPATCH_UNCERTAIN", "READY", "NOT_VERIFIED"):
            raise VerificationError("VERIFICATION_WORKER_RESPONSE_INVALID", 422)
        return result

    def receipt(self, result):
        body, signature = result.get("receipt_json"), result.get("signature")
        if not isinstance(body, str) or not isinstance(signature, str):
            raise VerificationError("VERIFICATION_RECEIPT_MISSING")
        expected = hmac.new(
            self.token.encode(), ("adlc-verification-receipt/v0.1\n" + body).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise VerificationError("VERIFICATION_RECEIPT_UNAUTHENTICATED")
        try:
            return ExecutionReceipt.model_validate_json(body)
        except (ValidationError, ValueError):
            raise VerificationError("VERIFICATION_RECEIPT_INVALID", 422) from None


@lru_cache(maxsize=1)
def get_verification_worker():
    return VerificationWorkerClient()

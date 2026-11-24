"""H6B protected worker port; deliberately no raw upstream TestForge POSTs."""

# ruff: noqa: EM101 - never expose remote response text or credentials.
import hashlib
import hmac
import json
import os
from functools import lru_cache
from urllib.parse import urlsplit

from langflow.adlc.replay_models import (
    CONFIG_DIGEST,
    MAX_REPLAY_EVIDENCE_BYTES,
    PROFILE,
    RUNNER,
    ReplayReceipt,
    suite_bytes,
)
from langflow.adlc.replay_repository import RUNNER_DIGEST
from langflow.adlc.verification_client import VerificationWorkerClient
from langflow.adlc.verification_models import VerificationError

STATES = frozenset({"RUNNING", "READY", "DISPATCH_UNCERTAIN", "NOT_VERIFIED", "CANCEL_REQUESTED", "CANCELLED"})


class ReplayWorkerClient(VerificationWorkerClient):
    api_root = "/api/v1/adlc-harness-replay"
    response_limit = MAX_REPLAY_EVIDENCE_BYTES

    @property
    def configured(self):
        # v0.1 is the local pilot only. A remote TestForge/gateway deployment
        # needs a reviewed new provider, not a URL substitution in this profile.
        return super().configured and urlsplit(self.base_url).hostname in {"127.0.0.1", "localhost", "::1"}

    def __init__(self, base_url=None, token=None, *, transport=None):
        super().__init__(
            base_url if base_url is not None else os.getenv("ADLC_REPLAY_WORKER_URL", ""),
            token if token is not None else os.getenv("ADLC_REPLAY_WORKER_TOKEN", ""),
            transport=transport,
        )

    async def health(self):
        if not self.configured:
            return {"ready": False, "provider": None}
        result = await self.request("GET", "/health")
        if (
            type(result.get("ready")) is not bool
            or result.get("profile_ref") != PROFILE
            or result.get("runner_ref") != RUNNER
            or result.get("runner_digest") != RUNNER_DIGEST
            or result.get("config_digest") != CONFIG_DIGEST
            or result.get("provider") not in {"disabled", "local-http-fixture"}
            or (result["ready"] and result["provider"] == "disabled")
            or result.get("testforge_ready") is not False
        ):
            raise VerificationError("REPLAY_WORKER_CONTRACT_MISMATCH", 503)
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
                # Preserve canonical bytes across JSON number/Unicode implementations.
                "suite_json": suite_bytes(record.plan.cases).decode("utf-8"),
                "suite_digest": record.plan.suite_digest,
                "config_digest": record.plan.config_digest,
                "timeout_seconds": record.plan.timeout_seconds,
            },
        )
        if result.get("execution_id") != str(record.execution_id) or result.get("state") not in STATES:
            raise VerificationError("VERIFICATION_EXECUTION_UNCONFIRMED", 503)
        return result

    async def read(self, execution_id):
        result = await self.request("GET", "/executions/" + str(execution_id))
        if result.get("execution_id") != str(execution_id) or result.get("state") not in STATES:
            raise VerificationError("REPLAY_WORKER_RESPONSE_INVALID", 422)
        return result

    async def cancel(self, record):
        result = await self.request(
            "POST", "/executions/" + str(record.execution_id) + "/cancel", {"plan_digest": record.plan_digest}
        )
        if result.get("execution_id") != str(record.execution_id) or result.get("state") not in STATES:
            raise VerificationError("REPLAY_CANCELLATION_UNCONFIRMED", 503)
        return result

    def authenticated(self, body, signature, domain):
        if not isinstance(body, str) or not isinstance(signature, str):
            raise VerificationError("REPLAY_EVIDENCE_MISSING")
        expected = hmac.new(self.token.encode(), (domain + body).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise VerificationError("REPLAY_EVIDENCE_UNAUTHENTICATED")
        return body

    def receipt(self, result):
        body = self.authenticated(result.get("receipt_json"), result.get("signature"), "adlc-replay-receipt/v0.1\n")
        try:
            return ReplayReceipt.model_validate_json(body)
        except ValueError:
            raise VerificationError("REPLAY_RECEIPT_INVALID", 422) from None

    def confirm_state(self, record, result):
        body = self.authenticated(result.get("state_json"), result.get("state_signature"), "adlc-replay-state/v0.1\n")
        try:
            state = json.loads(body)
            expected = {
                "execution_id": str(record.execution_id),
                "plan_digest": record.plan_digest,
                "candidate_digest": record.plan.candidate.content_digest,
                "suite_digest": record.plan.suite_digest,
                "config_digest": record.plan.config_digest,
                "state": result["state"],
                "target_released": True,
            }
            if state != expected or result["state"] != "CANCELLED":
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise VerificationError("REPLAY_CANCELLATION_UNCONFIRMED") from None


@lru_cache(maxsize=1)
def get_replay_worker():
    return ReplayWorkerClient()

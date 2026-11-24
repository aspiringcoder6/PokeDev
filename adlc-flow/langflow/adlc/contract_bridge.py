"""Purpose-separated HMAC authentication for the six-tool Harness bridge."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field

from langflow.adlc.contract_repository import ContractError

BRIDGE_DOMAIN = b"adlc-contract-tools-v1\n"
AUTHORING_READ_DOMAIN = b"adlc-contract-authoring-v1\n"
EXECUTION_DOMAIN = b"adlc-contract-execution-v1\n"
BRIDGE_MAX_BODY_BYTES = 32 * 1024
BRIDGE_MIN_SECRET_BYTES = 32
BRIDGE_MAX_TIMESTAMP_DIGITS = 12


def sign_contract_command(secret: str, timestamp: str, body: bytes, *, domain: bytes = BRIDGE_DOMAIN) -> str:
    payload = domain + timestamp.encode("ascii") + b"\n" + body
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ContractBridgeSettings:
    secret: str | None = field(default=None, repr=False)
    tolerance_seconds: int = 300

    @classmethod
    def from_environment(cls) -> ContractBridgeSettings:
        return cls(secret=os.getenv("ADLC_CONTRACT_TOOL_SECRET") or None)

    def authenticate(
        self, timestamp: str, signature: str, body: bytes, *, now: float | None = None, domain: bytes = BRIDGE_DOMAIN
    ) -> None:
        if len(body) > BRIDGE_MAX_BODY_BYTES:
            msg = "CONTRACT_REQUEST_TOO_LARGE"
            raise ContractError(msg, 413)
        if not self.secret or len(self.secret.encode()) < BRIDGE_MIN_SECRET_BYTES:
            msg = "CONTRACT_BRIDGE_NOT_CONFIGURED"
            raise ContractError(msg, 503)
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > BRIDGE_MAX_TIMESTAMP_DIGITS:
            msg = "CONTRACT_BRIDGE_UNAUTHENTICATED"
            raise ContractError(msg, 401)
        if abs((time.time() if now is None else now) - int(timestamp)) > self.tolerance_seconds:
            msg = "CONTRACT_BRIDGE_EXPIRED"
            raise ContractError(msg, 401)
        expected = sign_contract_command(self.secret, timestamp, body, domain=domain)
        if not signature.isascii() or not hmac.compare_digest(signature, expected):
            msg = "CONTRACT_BRIDGE_UNAUTHENTICATED"
            raise ContractError(msg, 401)

"""Authenticated, idempotent webhook ingress for Harness terminal results."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from langflow.adlc.harness_artifacts import is_captured_harness_patch
from langflow.adlc.harness_attempts import (
    HarnessAttemptError,
    TaskAttemptRepository,
    create_task_attempt_repository_from_environment,
    validate_harness_result_for_attempt,
)
from langflow.adlc.harness_client import HarnessClientError
from langflow.adlc.harness_models import (
    HarnessCallbackReceipt,
    HarnessResultDelivery,
    HarnessSessionResult,
    TaskAttemptRecord,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from langflow.adlc.harness_artifacts import HarnessArtifactImporter
    from langflow.adlc.models import TaskRequest

HARNESS_CALLBACK_SECRET_ENV = "ADLC_HARNESS_CALLBACK_SECRET"  # noqa: S105 - environment variable name.
HARNESS_SIGNATURE_PREFIX = "sha256="
HARNESS_CALLBACK_MAX_BODY_BYTES = 1024 * 1024
CALLBACK_EXPIRED = "HARNESS_CALLBACK_EXPIRED"
CALLBACK_INVALID = "HARNESS_CALLBACK_INVALID"
CALLBACK_NOT_CONFIGURED = "HARNESS_CALLBACK_NOT_CONFIGURED"
CALLBACK_SIGNATURE_INVALID = "HARNESS_CALLBACK_SIGNATURE_INVALID"
CALLBACK_TIMESTAMP_INVALID = "HARNESS_CALLBACK_TIMESTAMP_INVALID"
CALLBACK_UNAUTHENTICATED = "HARNESS_CALLBACK_UNAUTHENTICATED"
DELIVERY_CONFLICT = "HARNESS_DELIVERY_CONFLICT"
DELIVERY_ID_MISMATCH = "HARNESS_DELIVERY_ID_MISMATCH"
RESULT_MISSING = "HARNESS_RESULT_MISSING"
RESULT_TIMEOUT = "HARNESS_RESULT_TIMEOUT"


class HarnessCallbackError(RuntimeError):
    """Safe callback error with a stable machine code and HTTP status."""

    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class HarnessCallbackSettings:
    """Callback verification settings; secret values are excluded from repr."""

    secret: str | None = field(default=None, repr=False)
    tolerance_seconds: int = 300

    def __post_init__(self) -> None:
        if self.tolerance_seconds <= 0:
            msg = "Harness callback tolerance must be positive."
            raise ValueError(msg)

    @classmethod
    def from_environment(cls) -> HarnessCallbackSettings:
        return cls(secret=os.getenv(HARNESS_CALLBACK_SECRET_ENV) or None)

    @property
    def ready(self) -> bool:
        return bool(self.secret)


def sign_harness_delivery(secret: str, timestamp: str, body: bytes) -> str:
    """Sign one exact callback body using the shared timestamped HMAC format."""
    payload = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{HARNESS_SIGNATURE_PREFIX}{digest}"


class HarnessCallbackReceiver:
    """Validate deliveries, deduplicate them, and wake the owning executor."""

    def __init__(
        self,
        settings: HarnessCallbackSettings | None = None,
        *,
        attempts: TaskAttemptRepository | None = None,
        clock: Callable[[], float] = time.time,
        artifact_importer: HarnessArtifactImporter | None = None,
    ) -> None:
        self.settings = settings or HarnessCallbackSettings.from_environment()
        self.attempts = attempts or create_task_attempt_repository_from_environment()
        self._clock = clock
        self.artifact_importer = artifact_importer
        self._waiters: dict[UUID, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return self.settings.ready

    @property
    def durable(self) -> bool:
        return self.attempts.is_durable

    async def register_attempt(self, request: TaskRequest) -> TaskAttemptRecord:
        return await self.attempts.create(request)

    async def bind_session(self, attempt_id: UUID, session_id: str) -> TaskAttemptRecord:
        return await self.attempts.bind_session(attempt_id, session_id)

    async def receive(
        self,
        body: bytes,
        *,
        delivery_id: str | None,
        timestamp: str | None,
        signature: str | None,
    ) -> HarnessCallbackReceipt:
        """Accept one signed terminal delivery and return an idempotent receipt."""
        if len(body) > HARNESS_CALLBACK_MAX_BODY_BYTES:
            raise HarnessCallbackError(
                CALLBACK_INVALID,
                "The Harness callback payload exceeds the accepted size limit.",
                http_status=413,
            )
        self._verify_signature(body, timestamp=timestamp, signature=signature)
        try:
            delivery = HarnessResultDelivery.model_validate_json(body)
        except ValidationError as exc:
            raise HarnessCallbackError(
                CALLBACK_INVALID,
                "The Harness callback payload does not satisfy the v0.1 contract.",
                http_status=422,
            ) from exc

        if delivery_id is None or delivery_id != str(delivery.delivery_id):
            raise HarnessCallbackError(
                DELIVERY_ID_MISMATCH,
                "The Harness delivery header does not match the signed payload.",
                http_status=400,
            )

        try:
            await self._prepare_artifacts(delivery.result)
            accepted, duplicate = await self.attempts.accept_delivery(delivery.delivery_id, delivery.result)
        except HarnessAttemptError as exc:
            status = 404 if exc.code == "HARNESS_ATTEMPT_NOT_FOUND" else 409
            raise HarnessCallbackError(exc.code, exc.message, http_status=status) from exc

        async with self._lock:
            waiter = self._waiters.get(accepted.attempt_id)
            if waiter is not None:
                waiter.set()
            return HarnessCallbackReceipt(
                delivery_id=delivery.delivery_id,
                attempt_id=accepted.attempt_id,
                duplicate=duplicate,
            )

    async def accept_reconciled_result(self, result: HarnessSessionResult) -> TaskAttemptRecord:
        """Accept a terminal result discovered by reconciliation and wake local waiters."""
        await self._prepare_artifacts(result)
        accepted = await self.attempts.accept_result(result)
        async with self._lock:
            waiter = self._waiters.get(accepted.attempt_id)
            if waiter is not None:
                waiter.set()
        return accepted

    async def _prepare_artifacts(self, result: HarnessSessionResult) -> None:
        record = await self.attempts.get(result.correlation.attempt_id)
        validate_harness_result_for_attempt(record, result)
        # Immutable accepted replay never depends on a live server or expired bytes.
        if record.result is not None or not any(is_captured_harness_patch(item) for item in result.artifacts):
            return
        if self.artifact_importer is None:
            code = "HARNESS_ARTIFACT_IMPORT_UNAVAILABLE"
            message = "Source-patch retention is not configured."
            raise HarnessCallbackError(code, message, http_status=503)
        try:
            await self.artifact_importer.import_result(result)
        except HarnessClientError as exc:
            raise HarnessCallbackError(
                exc.code,
                "The source patch could not be retained. The Harness result was not accepted.",
                http_status=503 if exc.retryable else 409,
            ) from None

    async def wait_for_result(self, attempt_id: UUID, *, timeout_seconds: float) -> HarnessSessionResult:
        """Wait for a callback while preserving an already-accepted result replay."""
        try:
            record = await self.attempts.get(attempt_id)
        except HarnessAttemptError as exc:
            raise HarnessCallbackError(exc.code, exc.message, http_status=404) from exc
        if record.result is not None:
            return record.result.model_copy(deep=True)

        async with self._lock:
            waiter = self._waiters.setdefault(attempt_id, asyncio.Event())
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout_seconds)
        except TimeoutError as exc:
            raise HarnessCallbackError(
                RESULT_TIMEOUT,
                "Timed out while waiting for the Harness result callback.",
                http_status=504,
            ) from exc
        finally:
            async with self._lock:
                self._waiters.pop(attempt_id, None)

        record = await self.attempts.get(attempt_id)
        if record.result is None:
            raise HarnessCallbackError(
                RESULT_MISSING,
                "The callback completed without a terminal Harness result.",
                http_status=500,
            )
        return record.result.model_copy(deep=True)

    def _verify_signature(self, body: bytes, *, timestamp: str | None, signature: str | None) -> None:
        secret = self.settings.secret
        if secret is None:
            raise HarnessCallbackError(
                CALLBACK_NOT_CONFIGURED,
                "Harness callback verification is not configured.",
                http_status=503,
            )
        if timestamp is None or signature is None:
            raise HarnessCallbackError(
                CALLBACK_UNAUTHENTICATED,
                "Harness callback authentication headers are required.",
                http_status=401,
            )
        try:
            timestamp_value = int(timestamp)
        except ValueError as exc:
            raise HarnessCallbackError(
                CALLBACK_TIMESTAMP_INVALID,
                "The Harness callback timestamp is invalid.",
                http_status=401,
            ) from exc
        if abs(self._clock() - timestamp_value) > self.settings.tolerance_seconds:
            raise HarnessCallbackError(
                CALLBACK_EXPIRED,
                "The Harness callback timestamp is outside the accepted replay window.",
                http_status=401,
            )
        expected = sign_harness_delivery(secret, timestamp, body)
        if not hmac.compare_digest(expected, signature):
            raise HarnessCallbackError(
                CALLBACK_SIGNATURE_INVALID,
                "The Harness callback signature is invalid.",
                http_status=401,
            )


__all__ = [
    "HARNESS_CALLBACK_MAX_BODY_BYTES",
    "HARNESS_CALLBACK_SECRET_ENV",
    "HarnessCallbackError",
    "HarnessCallbackReceiver",
    "HarnessCallbackSettings",
    "sign_harness_delivery",
]

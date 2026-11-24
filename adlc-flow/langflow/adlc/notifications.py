"""Owner-facing notification seam for orchestrator events that need attention."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from lfx.log.logger import logger

NOTIFICATION_CONTRACT_VERSION = "0.1"
_WEBHOOK_SUCCESS_MIN_STATUS = 300


class AdlcNotificationKind(str, Enum):
    """Stable notification categories emitted by the run coordinator."""

    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    SLA_BREACHED = "SLA_BREACHED"


class AdlcNotification(BaseModel):
    """One secret-safe notification payload projected to owner channels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = NOTIFICATION_CONTRACT_VERSION
    notification_id: UUID = Field(default_factory=uuid4)
    kind: AdlcNotificationKind
    workflow_run_id: UUID
    task_run_id: UUID | None = None
    approval_request_id: UUID | None = None
    message: str = Field(min_length=1, max_length=512)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdlcNotificationSink(Protocol):
    """Replaceable output port for orchestrator notifications."""

    def notify(self, notification: AdlcNotification) -> None:
        """Deliver one notification."""
        ...


class NoOpAdlcNotificationSink:
    """Default for services composed without a notification channel."""

    def notify(self, notification: AdlcNotification) -> None:  # noqa: ARG002
        return


class InMemoryAdlcNotificationSink:
    """Thread-safe recorder used by unit tests and local verification."""

    def __init__(self) -> None:
        self._notifications: list[AdlcNotification] = []
        self._lock = Lock()

    def notify(self, notification: AdlcNotification) -> None:
        with self._lock:
            self._notifications.append(notification.model_copy(deep=True))

    @property
    def notifications(self) -> tuple[AdlcNotification, ...]:
        with self._lock:
            return tuple(item.model_copy(deep=True) for item in self._notifications)

    def clear(self) -> None:
        with self._lock:
            self._notifications.clear()


class StructuredLogAdlcNotificationSink:
    """Export notifications through Langflow's structured logger."""

    def notify(self, notification: AdlcNotification) -> None:
        payload = notification.model_dump(mode="json", exclude_none=True)
        payload.pop("kind", None)
        logger.info(notification.kind.value, **payload)


class CompositeAdlcNotificationSink:
    """Fan one notification out to several sinks without letting one break the rest."""

    def __init__(self, sinks: tuple[AdlcNotificationSink, ...]) -> None:
        self._sinks = sinks

    def notify(self, notification: AdlcNotification) -> None:
        for sink in self._sinks:
            sink.notify(notification)


class WebhookAdlcNotificationSink:
    """POST notifications to an operator-configured HTTP endpoint.

    Delivery is strictly best-effort: network failures, non-2xx responses,
    and timeouts are logged and swallowed so the coordinated path is never
    affected. The optional token is sent as a bearer credential.
    """

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout_seconds = timeout_seconds

    def notify(self, notification: AdlcNotification) -> None:
        headers = {"content-type": "application/json"}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        try:
            response = httpx.post(
                self._url,
                json=notification.model_dump(mode="json", exclude_none=True),
                headers=headers,
                timeout=self._timeout_seconds,
            )
            if response.status_code >= _WEBHOOK_SUCCESS_MIN_STATUS:
                logger.warning(
                    "adlc.notification.webhook_rejected",
                    status_code=response.status_code,
                    kind=notification.kind.value,
                )
        except Exception:  # noqa: BLE001 - webhook delivery must never break the coordinator
            logger.warning("adlc.notification.webhook_failed", kind=notification.kind.value, exc_info=True)


NOOP_ADLC_NOTIFICATION_SINK = NoOpAdlcNotificationSink()

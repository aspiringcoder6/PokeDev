"""DeepSeek Harness web-gateway adapter for the ADLC ``HarnessClient`` port.

The live Harness server exposes the DSH typert RPC gateway (``POST /api/<method>``
with ``dsh-auth-*`` cookie authentication) instead of the v0.1 REST control API.
This adapter implements the same ``HarnessClient`` protocol as
:class:`langflow.adlc.harness_client.HarnessHttpClient` on top of the official
``dsh_web_sdk`` package, so :class:`langflow.adlc.harness_executor.DeepSeekHarnessTaskExecutor`
and the HITL/run-detail API routes keep working unchanged.

Mapping summary:

- ``create_session`` -> ``session/create`` + ``session/prompt`` with the ADLC
  objective rendered as the user prompt;
- ``get_session`` -> ``session/list`` (running flag) plus ``session/page``
  (latest assistant text), finalized into a terminal ``HarnessSessionResult``
  after an idle grace period, reconciled by the executor's polling loop;
- ``cancel_session`` -> ``session/cancel``;
- ``submit_session`` / interactions are no-ops or explicit rejections because
  the web gateway has no submission or HITL interaction concept yet.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from langflow.adlc.artifact_payload_store import (
    ArtifactPayloadStoreError,
    BoundedArtifactPayloadStore,
)
from langflow.adlc.harness_client import (
    REQUEST_REJECTED,
    RESPONSE_INVALID,
    SERVER_AUTHENTICATION_FAILED,
    SERVER_ERROR,
    SERVER_UNAVAILABLE,
    HarnessClientError,
    HarnessServerSettings,
)
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessDeliveryStatus,
    HarnessInteractionReceipt,
    HarnessInteractionResponse,
    HarnessPluginLockEntry,
    HarnessSessionAccepted,
    HarnessSessionRead,
    HarnessSessionRequest,
    HarnessSessionResult,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    HarnessSubmissionReceipt,
    TaskResultStatus,
)
from langflow.adlc.models import Artifact, Checksum, ServiceError, TaskMetrics

if TYPE_CHECKING:
    from dsh_web_sdk import DshClient
    from dsh_web_sdk.errors import DshError
else:
    try:
        from dsh_web_sdk.errors import DshError
    except ImportError:  # pragma: no cover - SDK is an optional dependency.
        DshError = None  # type: ignore[assignment,misc]

HARNESS_DSH_IDLE_GRACE_ENV = "ADLC_HARNESS_DSH_IDLE_GRACE_SECONDS"
HARNESS_DSH_GOAL_ENABLED_ENV = "ADLC_DSH_GOAL_ENABLED"
HARNESS_DSH_GOAL_IDLE_GRACE_ENV = "ADLC_HARNESS_DSH_GOAL_IDLE_GRACE_SECONDS"
DSH_SERVICE_NAME = "agent-provider:deepseek-harness"
# Reduced from 8s/90s — DSH signals completion via the running flag, so
# a short grace is enough to debounce transient idle blips without
# adding 90s of latency to every goal-driven task.
DEFAULT_IDLE_GRACE_SECONDS = 2.0
DEFAULT_GOAL_IDLE_GRACE_SECONDS = 5.0
_GOAL_OBJECTIVE_MAX_LENGTH = 400
_GOAL_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})

_ADLC_FILE_BLOCK_PATTERN = re.compile(
    r'<adlc:file\s+path="(?P<path>[^"]+)"\s*>\s*\n(?P<content>.*?)\n?\s*</adlc:file\s*>',
    re.DOTALL,
)
_UNSAFE_FILE_PATH_PATTERN = re.compile(r"(^|[/\\])\.\.($|[/\\])")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class DshSessionRecord:
    """Process-local projection binding one DSH session to its ADLC attempt."""

    session_id: str
    correlation: HarnessCorrelation
    idempotency_key: str
    objective: str
    submission_mode: HarnessSubmissionMode
    plugin_lock: list[HarnessPluginLockEntry]
    started_at: datetime
    updated_at: datetime
    cancelled: bool = False
    finalized: bool = False
    last_seen_seq: int = -1
    idle_since: float | None = None
    result: HarnessSessionResult | None = None
    goal_state: str = "off"


GOAL_STATE_PENDING = "pending"
GOAL_STATE_ARMED = "armed"
GOAL_STATE_DISABLED = "disabled"


class DshHarnessClient:
    """Implement the ``HarnessClient`` protocol against one DSH web server."""

    def __init__(
        self,
        settings: HarnessServerSettings,
        *,
        idle_grace_seconds: float = DEFAULT_IDLE_GRACE_SECONDS,
        goal_idle_grace_seconds: float = DEFAULT_GOAL_IDLE_GRACE_SECONDS,
        goal_enabled: bool | None = None,
        dsh_client: DshClient | None = None,
        artifact_payloads: BoundedArtifactPayloadStore | None = None,
    ) -> None:
        settings.validate()
        if not settings.api_token:
            msg = "DSH Harness transport requires an API token."
            raise ValueError(msg)
        if idle_grace_seconds < 0:
            msg = "DSH idle grace must not be negative."
            raise ValueError(msg)
        if goal_idle_grace_seconds < 0:
            msg = "DSH goal idle grace must not be negative."
            raise ValueError(msg)
        self.settings = settings
        self.idle_grace_seconds = idle_grace_seconds
        self.goal_idle_grace_seconds = goal_idle_grace_seconds
        self.goal_enabled = dsh_goal_enabled_from_environment() if goal_enabled is None else goal_enabled
        self._artifact_payloads = artifact_payloads
        self._sdk_errors: tuple[type[Exception], ...] = ()
        try:
            from dsh_web_sdk import DshClient
            from dsh_web_sdk.errors import DshError
        except ModuleNotFoundError as exc:
            if dsh_client is None:
                msg = "DSH_SDK_UNAVAILABLE: install the optional dsh_web_sdk to enable the DSH transport."
                raise ValueError(msg) from exc
        else:
            self._sdk_errors = (DshError,)
        self._dsh = (
            dsh_client
            if dsh_client is not None
            else DshClient(settings.base_url, settings.api_token, timeout=settings.request_timeout_seconds)
        )
        self._auth_lock = asyncio.Lock()
        self._authed = False
        self._records: dict[str, DshSessionRecord] = {}
        self._by_idempotency_key: dict[str, str] = {}
        self._registry_lock = asyncio.Lock()
        self._goal_sessions: set[str] = set()

    # ---- transport plumbing -------------------------------------------

    async def _ensure_auth(self) -> None:
        if self._authed:
            return
        async with self._auth_lock:
            if self._authed:
                return
            try:
                await self._dsh.__aenter__()
            except self._sdk_errors as exc:
                raise self._translate(exc) from exc
            self._authed = True

    @staticmethod
    def _translate(exc: DshError) -> HarnessClientError:
        from dsh_web_sdk.errors import (
            DshAuthError,
            DshConfigError,
            DshProtocolError,
            DshTimeoutError,
            DshTransportError,
        )

        if isinstance(exc, DshAuthError):
            return HarnessClientError(
                SERVER_AUTHENTICATION_FAILED,
                category="AUTHENTICATION",
                retryable=False,
            )
        if isinstance(exc, (DshTransportError, DshTimeoutError)):
            return HarnessClientError(SERVER_UNAVAILABLE)
        if isinstance(exc, DshProtocolError):
            return HarnessClientError(RESPONSE_INVALID, retryable=False)
        if isinstance(exc, DshConfigError):
            return HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)
        return HarnessClientError(SERVER_ERROR)

    # ---- HarnessClient protocol ---------------------------------------

    async def health(self) -> dict[str, object]:
        """Read a secret-free readiness projection from the DSH gateway.

        Beyond the basic ``list_sessions`` ping, this also queries the DSH
        plugin hub (``GET /dsh-plugin-hub/installed``) to project a
        ``plugin_integrity`` block compatible with
        :class:`langflow.adlc.harness_models.HarnessPluginInventory`. The
        ``plugin_lock_ready`` flag is ``True`` only when every dsh-capable
        plugin reported by the hub is also present in the running loader.
        """
        await self._ensure_auth()
        try:
            await self._dsh.list_sessions()
        except self._sdk_errors as exc:
            raise self._translate(exc) from exc

        plugin_integrity, plugin_lock_ready = await self._collect_plugin_integrity()
        return {
            "ready": True,
            "version": "dsh-web-gateway",
            "plugin_integrity": plugin_integrity,
            "plugin_lock_ready": plugin_lock_ready,
        }

    async def _collect_plugin_integrity(self) -> tuple[dict[str, object], bool]:
        """Project the DSH plugin hub into the ADLC ``HarnessPluginInventory`` shape.

        Returns a tuple of ``(plugin_integrity_dict, plugin_lock_ready)``. When
        the hub endpoint is unreachable or returns an unexpected payload, the
        integrity dict is still returned (with ``ready=False`` and an
        ``error_code``) so callers can surface a precise failure mode instead
        of a generic ``HARNESS_PLUGIN_INTEGRITY_UNAVAILABLE``.
        """
        from langflow.adlc.harness_models import (
            HarnessPluginIntegrityEntry,
            HarnessPluginIntegrityStatus,
            HarnessPluginInventory,
        )

        checked_at = _utc_now()
        try:
            installed_payload = await self._dsh.http_get("/dsh-plugin-hub/installed")
        except self._sdk_errors as exc:
            inventory = HarnessPluginInventory(
                ready=False,
                checked_at=checked_at,
                error_code="HARNESS_PLUGIN_HUB_UNREACHABLE",
                plugins=[],
            )
            return inventory.model_dump(mode="json"), False

        if not isinstance(installed_payload, dict):
            inventory = HarnessPluginInventory(
                ready=False,
                checked_at=checked_at,
                error_code="HARNESS_PLUGIN_HUB_INVALID_PAYLOAD",
                plugins=[],
            )
            return inventory.model_dump(mode="json"), False

        installed_map = installed_payload.get("installed")
        loaded_list = installed_payload.get("loaded")
        dsh_capable_list = installed_payload.get("dshCapable")
        if not isinstance(installed_map, dict) or not isinstance(loaded_list, list) or not isinstance(
            dsh_capable_list, list
        ):
            inventory = HarnessPluginInventory(
                ready=False,
                checked_at=checked_at,
                error_code="HARNESS_PLUGIN_HUB_INVALID_PAYLOAD",
                plugins=[],
            )
            return inventory.model_dump(mode="json"), False

        loaded = {str(name) for name in loaded_list}
        dsh_capable = {str(name) for name in dsh_capable_list}
        entries: list[HarnessPluginIntegrityEntry] = []
        all_loaded = True
        for plugin_id in sorted(dsh_capable):
            spec = installed_map.get(plugin_id)
            is_loaded = plugin_id in loaded
            if not is_loaded:
                all_loaded = False
            entries.append(
                HarnessPluginIntegrityEntry(
                    plugin_id=plugin_id,
                    required=True,
                    expected_version="*",
                    expected_digest="*",
                    installed_version=str(spec) if isinstance(spec, str) else None,
                    installed_digest=None,
                    status=(
                        HarnessPluginIntegrityStatus.EXACT
                        if is_loaded
                        else HarnessPluginIntegrityStatus.MISSING
                    ),
                )
            )

        inventory = HarnessPluginInventory(
            ready=all_loaded,
            checked_at=checked_at,
            error_code=None if all_loaded else "HARNESS_PLUGIN_LOCK_NOT_READY",
            plugins=entries,
        )
        return inventory.model_dump(mode="json"), all_loaded

    async def create_session(self, request: HarnessSessionRequest) -> HarnessSessionAccepted:
        async with self._registry_lock:
            existing_id = self._by_idempotency_key.get(request.idempotency_key)
        if existing_id is not None:
            record = self._records[existing_id]
            return self._accepted(record, replayed=True)

        await self._ensure_auth()
        cwd = request.context.get("cwd") if isinstance(request.context, dict) else None
        try:
            session = await self._dsh.create_session(
                cwd=cwd if isinstance(cwd, str) and cwd else None,
            )
            await session.prompt(self._compose_prompt(request))
        except self._sdk_errors as exc:
            raise self._translate(exc) from exc

        now = _utc_now()
        record = DshSessionRecord(
            session_id=session.session_id,
            correlation=request.correlation,
            idempotency_key=request.idempotency_key,
            objective=request.objective,
            submission_mode=request.submission_mode,
            plugin_lock=[entry.model_copy(deep=True) for entry in request.execution.plugin_lock],
            started_at=now,
            updated_at=now,
            goal_state=GOAL_STATE_PENDING if self.goal_enabled else "off",
        )
        async with self._registry_lock:
            self._records[record.session_id] = record
            self._by_idempotency_key[record.idempotency_key] = record.session_id
        return self._accepted(record, replayed=False)

    async def get_session(self, session_id: str) -> HarnessSessionRead:
        record = self._records.get(session_id)
        if record is None:
            raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)
        if not record.finalized:
            await self._refresh(record)
        return self._read(record)

    async def session_events(self, session_id: str, *, max_events: int = 200) -> list[dict[str, object]]:
        """Return recent DSH event payloads for read-only activity projection.

        Sessions created by other processes (for example before a backend
        restart) are not tracked in ``_records``; this lookup works directly
        against the remote server instead of the local registry.
        """
        await self._ensure_auth()
        try:
            events = await self._dsh.session(session_id).history(max_messages=max_events)
        except self._sdk_errors as exc:
            raise self._translate(exc) from exc
        return [event for event in events if isinstance(event, dict)]

    async def submit_session(self, session_id: str) -> HarnessSubmissionReceipt:
        record = self._records.get(session_id)
        if record is None:
            raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)
        return HarnessSubmissionReceipt(
            session_id=record.session_id,
            status=self._status_of(record),
            delivery_id=uuid5(NAMESPACE_URL, f"dsh:{record.session_id}"),
            delivery_status=HarnessDeliveryStatus.DELIVERED,
            replayed=True,
        )

    async def respond_to_interaction(
        self,
        session_id: str,  # noqa: ARG002 - preserve the HarnessClient keyword interface.
        interaction_id: str,  # noqa: ARG002 - this transport has no HITL interaction endpoint.
        response: HarnessInteractionResponse,  # noqa: ARG002 - unsupported responses are rejected.
    ) -> HarnessInteractionReceipt:
        raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)

    async def cancel_session(self, session_id: str) -> HarnessSessionRead:
        record = self._records.get(session_id)
        if record is None:
            raise HarnessClientError(REQUEST_REJECTED, category="VALIDATION", retryable=False)
        if not record.finalized:
            await self._ensure_auth()
            try:
                await self._dsh.session(session_id).cancel()
            except self._sdk_errors as exc:
                raise self._translate(exc) from exc
            record.cancelled = True
            record.result = self._cancelled_result(record)
            record.finalized = True
        self._goal_sessions.discard(session_id)
        return self._read(record)

    async def _arm_goal(self, record: DshSessionRecord) -> None:
        """Arm the DSH goal round driver for one task session.

        The arm happens once the first turn ends (an idle session): a goal
        armed while a turn is still running never drives rounds. The host
        driver then re-prompts the agent across goal rounds (auto-healing
        provider 429s) until the objective is met instead of letting one
        fragile turn decide the task outcome. Best-effort: a failure to arm
        never fails the dispatch or the result projection.
        """
        text = " ".join((record.objective or "").split())
        if not text:
            record.goal_state = GOAL_STATE_DISABLED
            return
        if len(text) > _GOAL_OBJECTIVE_MAX_LENGTH:
            text = text[:_GOAL_OBJECTIVE_MAX_LENGTH].rstrip()
        try:
            await self._dsh.rpc(
                "commands/execute",
                {
                    "agentId": record.session_id,
                    "line": f"/goal {text}",
                    "submittedAttachments": [],
                },
                timeout=self.settings.request_timeout_seconds,
            )
        except self._sdk_errors:
            record.goal_state = GOAL_STATE_DISABLED
            return
        record.goal_state = GOAL_STATE_ARMED
        self._goal_sessions.add(record.session_id)

    async def close(self) -> None:
        """No persistent transport to release; kept for client symmetry."""

    # ---- projection helpers -------------------------------------------

    async def _refresh(self, record: DshSessionRecord) -> None:
        await self._ensure_auth()
        dsh_session = self._dsh.session(record.session_id)
        try:
            # Single SDK call: ``summary()`` returns the running flag
            # from session/list. We skip the separate ``cursor()`` call
            # when the session is actively running — we only need the
            # cursor to detect new events after the session goes idle.
            summary = await dsh_session.summary()
            running = bool(summary.get("running"))
            if not running:
                cursor = await dsh_session.cursor()
            else:
                cursor = record.last_seen_seq
        except self._sdk_errors as exc:
            raise self._translate(exc) from exc

        now_mono = time.monotonic()
        record.updated_at = _utc_now()
        if cursor > record.last_seen_seq:
            record.last_seen_seq = cursor
            record.idle_since = None if running else now_mono
        elif running:
            record.idle_since = None
        elif record.idle_since is None:
            record.idle_since = now_mono

        if record.goal_state == GOAL_STATE_PENDING and not running:
            # Arm the goal at the first idle observation: the host goal driver
            # only engages for goals armed while the session is idle, and it
            # re-prompts the agent until the objective is met.
            await self._arm_goal(record)

        if running or record.idle_since is None:
            return
        # Goal-driven sessions pause between rounds (429 backoff can exceed a
        # minute), so only finalize once the quiet period outlasts the goal grace.
        grace = self.goal_idle_grace_seconds if record.session_id in self._goal_sessions else self.idle_grace_seconds
        if now_mono - record.idle_since < grace:
            return

        try:
            final_text = await dsh_session.final_text()
        except self._sdk_errors as exc:
            raise self._translate(exc) from exc
        record.result = self._terminal_result(record, final_text)
        record.finalized = True
        self._goal_sessions.discard(record.session_id)

    def _terminal_result(self, record: DshSessionRecord, final_text: str | None) -> HarnessSessionResult:
        completed_at = _utc_now()
        duration_ms = max(0, int((completed_at - record.started_at).total_seconds() * 1000))
        if record.cancelled:
            return HarnessSessionResult(
                session_id=record.session_id,
                correlation=record.correlation,
                status=TaskResultStatus.CANCELLED,
                output=None,
                artifacts=[],
                error=ServiceError(
                    error_id=uuid4(),
                    code="HARNESS_SESSION_CANCELLED",
                    category="CANCELLED",
                    message="The DSH session was cancelled before completion.",
                    retryable=False,
                    service=DSH_SERVICE_NAME,
                    details={"session_id": record.session_id},
                    correlation_id=f"run-{record.correlation.workflow_run_id}/task-{record.correlation.task_run_id}",
                    occurred_at=completed_at,
                ),
                plugin_lock=[entry.model_copy(deep=True) for entry in record.plugin_lock],
                metrics=TaskMetrics(duration_ms=duration_ms),
                trace_ref=f"dsh://{record.session_id}/events",
                started_at=record.started_at,
                completed_at=completed_at,
                metadata={"transport": "dsh-web-gateway"},
            )
        if final_text:
            artifacts = self._capture_file_artifacts(record, final_text, completed_at)
            return HarnessSessionResult(
                session_id=record.session_id,
                correlation=record.correlation,
                status=TaskResultStatus.SUCCEEDED,
                output={"final_text": final_text, "session_id": record.session_id},
                artifacts=artifacts,
                error=None,
                plugin_lock=[entry.model_copy(deep=True) for entry in record.plugin_lock],
                metrics=TaskMetrics(duration_ms=duration_ms),
                trace_ref=f"dsh://{record.session_id}/events",
                started_at=record.started_at,
                completed_at=completed_at,
                metadata={"transport": "dsh-web-gateway"},
            )
        return HarnessSessionResult(
            session_id=record.session_id,
            correlation=record.correlation,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code="HARNESS_RESULT_MISSING",
                category="DEPENDENCY",
                message="The DSH session ended without an assistant response.",
                retryable=True,
                service=DSH_SERVICE_NAME,
                details={"session_id": record.session_id},
                correlation_id=f"run-{record.correlation.workflow_run_id}/task-{record.correlation.task_run_id}",
                occurred_at=completed_at,
            ),
            plugin_lock=[entry.model_copy(deep=True) for entry in record.plugin_lock],
            metrics=TaskMetrics(duration_ms=duration_ms),
            trace_ref=f"dsh://{record.session_id}/events",
            started_at=record.started_at,
            completed_at=completed_at,
            metadata={"transport": "dsh-web-gateway"},
        )

    def _capture_file_artifacts(
        self,
        record: DshSessionRecord,
        final_text: str,
        completed_at: datetime,
    ) -> list[Artifact]:
        """Turn adlc:file blocks in the final message into retained SOURCE_PATCH artifacts."""
        if self._artifact_payloads is None:
            return []
        extracted = self._extract_file_blocks(final_text)
        if not extracted:
            return []
        files: list[dict[str, Any]] = []
        reported: list[str] = []
        for path, content in extracted:
            lines = content.splitlines()
            patch = "\n".join(
                [
                    "--- /dev/null",
                    f"+++ b/{path}",
                    f"@@ -0,0 +1,{len(lines)} @@",
                    *(f"+{line}" for line in lines),
                ]
            )
            files.append(
                {
                    "file": path,
                    "patch": patch,
                    "additions": len(lines),
                    "deletions": 0,
                    "status": "added",
                }
            )
            reported.append(path)
        snapshot = {
            "format": "opencode-vcs-diff-v1",
            "files": files,
            "reported_files": reported,
        }
        content = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        artifact_id = uuid5(record.correlation.attempt_id, "dsh-final-message-files")
        artifact = Artifact(
            artifact_id=artifact_id,
            workflow_run_id=record.correlation.workflow_run_id,
            task_run_id=record.correlation.task_run_id,
            attempt_id=record.correlation.attempt_id,
            kind="SOURCE_PATCH",
            name="source-patch.json",
            media_type="application/vnd.dsh.final-message+json",
            uri=f"adlc://runs/{record.correlation.workflow_run_id}/artifacts/{artifact_id}",
            size_bytes=len(content),
            checksum=Checksum(value=hashlib.sha256(content).hexdigest()),
            producer=DSH_SERVICE_NAME,
            created_at=completed_at,
            expires_at=self._artifact_payloads.expires_at(completed_at),
            metadata={
                "capture": "dsh-final-message",
                "payload_retained": True,
                "dsh_session_id": record.session_id,
                "file_count": len(reported),
            },
        )
        try:
            self._artifact_payloads.retain(artifact, content)
        except ArtifactPayloadStoreError:
            return []
        return [artifact]

    @staticmethod
    def _extract_file_blocks(final_text: str) -> list[tuple[str, str]]:
        extracted: list[tuple[str, str]] = []
        seen_paths: set[str] = set()
        for match in _ADLC_FILE_BLOCK_PATTERN.finditer(final_text):
            raw_path = match.group("path").strip().replace("\\", "/")
            content = match.group("content")
            if not raw_path or not content.strip():
                continue
            if raw_path.startswith("/") or _UNSAFE_FILE_PATH_PATTERN.search(raw_path):
                continue
            if raw_path in seen_paths:
                continue
            seen_paths.add(raw_path)
            extracted.append((raw_path, content))
        return extracted

    def _cancelled_result(self, record: DshSessionRecord) -> HarnessSessionResult:
        return self._terminal_result(record, None)

    def _status_of(self, record: DshSessionRecord) -> HarnessSessionStatus:
        if record.result is not None:
            return {
                TaskResultStatus.SUCCEEDED: HarnessSessionStatus.SUCCEEDED,
                TaskResultStatus.FAILED: HarnessSessionStatus.FAILED,
                TaskResultStatus.CANCELLED: HarnessSessionStatus.CANCELLED,
            }[record.result.status]
        if record.cancelled:
            return HarnessSessionStatus.CANCELLED
        return HarnessSessionStatus.RUNNING

    def _read(self, record: DshSessionRecord) -> HarnessSessionRead:
        return HarnessSessionRead(
            session_id=record.session_id,
            correlation=record.correlation,
            idempotency_key=record.idempotency_key,
            status=self._status_of(record),
            submission_mode=record.submission_mode,
            result=record.result.model_copy(deep=True) if record.result is not None else None,
            created_at=record.started_at,
            updated_at=record.updated_at,
        )

    def _accepted(self, record: DshSessionRecord, *, replayed: bool) -> HarnessSessionAccepted:
        return HarnessSessionAccepted(session=self._read(record), replayed=replayed)

    def _compose_prompt(self, request: HarnessSessionRequest) -> str:
        lines = [request.objective.strip()]
        input_payload = request.input if isinstance(request.input, dict) else {}
        named = input_payload.get("namedInputs")
        if isinstance(named, dict):
            requirement = named.get("requirement")
            if isinstance(requirement, str) and requirement.strip():
                lines.append(f"\n# Task requirement\n{requirement.strip()}")
        filtered_input = json.loads(json.dumps(input_payload)) if input_payload else {}
        artifact = filtered_input.get("artifact") if isinstance(filtered_input, dict) else None
        if isinstance(artifact, dict):
            content = artifact.get("content")
            if isinstance(content, str) and content.startswith("Mock artifact produced for plan task"):
                artifact.pop("content", None)
        sections: list[tuple[str, Any]] = [
            ("Input", filtered_input or None),
            ("Constraints", request.constraints or None),
            ("Context", request.context or None),
            ("Metadata", request.metadata or None),
        ]
        for title, payload in sections:
            if payload in (None, {}, []):
                continue
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            lines.append(f"\n## {title}\n{rendered}")
        lines.append(
            "\nCarry out the task requirement inside the session workspace before replying. "
            "Then reply with a single final message summarizing the outcome; it is returned "
            "verbatim as the ADLC task result."
        )
        lines.append(
            "\nIf you created or modified any files, the final message must also include "
            "the complete content of every such file, each wrapped exactly as:\n"
            '<adlc:file path="relative/path/to/file.ext">\n'
            "...complete file content...\n"
            "</adlc:file>\n"
            "Place all adlc:file blocks after the summary text. Never truncate file content."
        )
        return "\n".join(lines)


def dsh_idle_grace_seconds_from_environment() -> float:
    raw = os.getenv(HARNESS_DSH_IDLE_GRACE_ENV, "")
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_IDLE_GRACE_SECONDS
    return value if value >= 0 else DEFAULT_IDLE_GRACE_SECONDS


def dsh_goal_enabled_from_environment() -> bool:
    """Goal arming is on by default; set ADLC_DSH_GOAL_ENABLED=false to opt out."""
    raw = os.getenv(HARNESS_DSH_GOAL_ENABLED_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in _GOAL_DISABLED_VALUES


def dsh_goal_idle_grace_seconds_from_environment() -> float:
    raw = os.getenv(HARNESS_DSH_GOAL_IDLE_GRACE_ENV, "")
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_GOAL_IDLE_GRACE_SECONDS
    return value if value > 0 else DEFAULT_GOAL_IDLE_GRACE_SECONDS


__all__ = [
    "DSH_SERVICE_NAME",
    "DshHarnessClient",
    "DshSessionRecord",
    "dsh_goal_enabled_from_environment",
    "dsh_goal_idle_grace_seconds_from_environment",
    "dsh_idle_grace_seconds_from_environment",
]

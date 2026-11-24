"""Read-only live task activity projection for the run-detail UI.

The coordinator stores only terminal task results. This module rebuilds the
in-flight (and historical) agent view by querying the backing coding agent
directly: the OpenCode headless server for ``agent-provider:opencode`` tasks
and the DSH gateway for ``agent-provider:deepseek-harness`` tasks. Every agent
failure degrades into a ``note`` so the endpoint always answers with the
static task projection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

from langflow.adlc.models import TaskRun

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langflow.adlc.harness_client import HarnessClient, HarnessClientError
    from langflow.adlc.harness_models import TaskAttemptRecord
    from langflow.adlc.opencode_client import OpenCodeClient, OpenCodeClientError

OPENCODE_SERVICE = "agent-provider:opencode"
HARNESS_SERVICE = "agent-provider:deepseek-harness"

_MAX_ENTRIES = 400
_TEXT_PREVIEW_CHARS = 2000
_REASONING_PREVIEW_CHARS = 500
_TOOL_OUTPUT_PREVIEW_CHARS = 1200
_TOOL_INPUT_PREVIEW_CHARS = 240
_EVENT_PREVIEW_CHARS = 400


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} chars]"


class TaskActivityEntry(BaseModel):
    """One normalized line of agent activity, ordered by ``seq``."""

    seq: int
    kind: str
    title: str
    detail: str | None = None
    status: str | None = None
    occurred_at: str | None = None


class TaskAgentActivity(BaseModel):
    """Live projection of the coding-agent session behind one task attempt."""

    source: str
    session_id: str | None = None
    directory: str | None = None
    running: bool = False
    entries: list[TaskActivityEntry] = Field(default_factory=list)
    entries_total: int = 0
    note: str | None = None
    updated_at: str = Field(default_factory=_utc_now_iso)


class TaskActivityResponse(BaseModel):
    """Everything the run-detail task panel needs for one task run."""

    task_run_id: UUID
    attempt_id: UUID | None = None
    status: str
    executor_service: str
    name: str
    task_type: str
    requirement: str | None = None
    objective: str | None = None
    output_summary: str | None = None
    output_outputs: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    agent: TaskAgentActivity | None = None


class TaskActivityService:
    """Query backing agents and normalize their transcripts for one task."""

    def __init__(
        self,
        *,
        opencode_client: OpenCodeClient | None,
        worktree_root: Path | None,
        harness_events: Callable[[str, int], Awaitable[list[dict[str, object]]]] | None,
        harness_attempts: Callable[[UUID], Awaitable[TaskAttemptRecord | None]] | None,
        harness_attempt_finder: Callable[[UUID], Awaitable[TaskAttemptRecord | None]] | None = None,
    ) -> None:
        self._opencode = opencode_client
        self._worktree_root = worktree_root
        self._harness_events = harness_events
        self._harness_attempts = harness_attempts
        self._harness_attempt_finder = harness_attempt_finder

    async def collect(self, task: TaskRun) -> TaskActivityResponse:
        response = TaskActivityResponse(
            task_run_id=task.id,
            attempt_id=task.current_attempt_id,
            status=str(task.status.value) if hasattr(task.status, "value") else str(task.status),
            executor_service=task.executor.service,
            name=task.name,
            task_type=task.task_type,
            **self._static_fields(task),
        )
        service = task.executor.service
        if service == OPENCODE_SERVICE:
            response.agent = await self._collect_opencode(task)
        elif service == HARNESS_SERVICE:
            response.agent = await self._collect_harness(task)
        return response

    # ---- static projection --------------------------------------------

    @staticmethod
    def _static_fields(task: TaskRun) -> dict[str, Any]:
        request = task.request
        input_payload = request.input if request is not None and isinstance(request.input, dict) else {}
        named = input_payload.get("namedInputs")
        named = named if isinstance(named, dict) else {}
        requirement = named.get("requirement")
        output = task.result.output if task.result is not None and task.result.output else None
        output_dict = output if isinstance(output, dict) else {}
        error = task.result.error if task.result is not None else None
        metrics = (
            task.result.metrics.model_dump(mode="json")
            if task.result is not None and task.result.metrics is not None
            else {}
        )
        metadata = task.result.metadata if task.result is not None and task.result.metadata else {}
        started = task.result.started_at if task.result is not None else task.started_at
        completed = task.result.completed_at if task.result is not None else task.completed_at
        return {
            "requirement": _preview(requirement if isinstance(requirement, str) else None, 20000),
            "objective": _preview(
                input_payload.get("objective") if isinstance(input_payload.get("objective"), str) else None,
                4000,
            ),
            "output_summary": _preview(
                output_dict.get("summary") if isinstance(output_dict.get("summary"), str) else None,
                _TEXT_PREVIEW_CHARS * 2,
            ),
            "output_outputs": output_dict.get("outputs") if isinstance(output_dict.get("outputs"), dict) else {},
            "error_code": error.code if error is not None else None,
            "error_message": error.message if error is not None else None,
            "metrics": metrics,
            "result_metadata": {key: value for key, value in metadata.items() if isinstance(value, (str, int, float, bool))},
            "started_at": started.isoformat() if isinstance(started, datetime) else None,
            "completed_at": completed.isoformat() if isinstance(completed, datetime) else None,
        }

    # ---- OpenCode -------------------------------------------------------

    async def _collect_opencode(self, task: TaskRun) -> TaskAgentActivity | None:
        if self._opencode is None or self._worktree_root is None or task.current_attempt_id is None:
            return None
        directory = str(self._worktree_root / f"worktree-{task.current_attempt_id}")
        activity = TaskAgentActivity(source=OPENCODE_SERVICE, directory=directory)
        metadata = task.result.metadata if task.result is not None and task.result.metadata else {}
        session_id = metadata.get("opencode_session_id")
        session_id = session_id if isinstance(session_id, str) and session_id else None

        if session_id is None:
            try:
                sessions = await self._opencode.list_sessions(directory=directory)
            except Exception as exc:  # noqa: BLE001 - degrade into a note
                activity.note = _error_note(exc)
                return activity
            session_id = _newest_opencode_session(sessions)
            if session_id is None:
                running = task.status == "RUNNING"
                activity.running = running
                activity.note = "OPENCODE_SESSION_NOT_FOUND" if not running else None
                return activity

        activity.session_id = session_id
        try:
            messages = await self._opencode.get_messages(session_id, directory=directory, timeout_ms=15000)
        except Exception as exc:  # noqa: BLE001 - degrade into a note
            activity.note = _error_note(exc)
            return activity

        entries, total = self._normalize_opencode_messages(messages)
        activity.entries = entries
        activity.entries_total = total
        activity.running = task.status == "RUNNING" or _opencode_last_unfinished(messages)
        return activity

    @staticmethod
    def _normalize_opencode_messages(messages: list[dict[str, Any]]) -> tuple[list[TaskActivityEntry], int]:
        raw: list[tuple[str, str | None, str, str | None, str | None]] = []
        for message in messages:
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            role = info.get("role") if isinstance(info.get("role"), str) else "assistant"
            created = _opencode_time(info)
            parts = message.get("parts") if isinstance(message.get("parts"), list) else []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "reasoning":
                    text = part.get("text") if isinstance(part.get("text"), str) else None
                    if text and text.strip():
                        raw.append(("reasoning", "Thinking", _preview(text, _REASONING_PREVIEW_CHARS), None, created))
                elif kind == "tool":
                    raw.append(_opencode_tool_entry(part, created))
                elif kind == "text":
                    text = part.get("text") if isinstance(part.get("text"), str) else ""
                    if not text.strip():
                        continue
                    entry_kind = "prompt" if role == "user" else "text"
                    title = "Prompt" if role == "user" else "Assistant"
                    raw.append((entry_kind, title, _preview(text, _TEXT_PREVIEW_CHARS), None, created))
                elif kind == "patch":
                    files = part.get("files") if isinstance(part.get("files"), list) else []
                    names = [name for name in files if isinstance(name, str)]
                    if names:
                        raw.append(("patch", f"Files changed ({len(names)})", "\n".join(names), None, created))

        total = len(raw)
        kept = raw[-_MAX_ENTRIES:]
        entries = [
            TaskActivityEntry(seq=index, kind=kind, title=title, detail=detail, status=status, occurred_at=occurred)
            for index, (kind, title, detail, status, occurred) in enumerate(kept)
        ]
        return entries, total

    # ---- DeepSeek Harness -----------------------------------------------

    async def _collect_harness(self, task: TaskRun) -> TaskAgentActivity | None:
        activity = TaskAgentActivity(source=HARNESS_SERVICE)
        if self._harness_attempts is None or self._harness_events is None:
            return None

        # Try the current attempt first, then fall back to the latest
        # attempt for this task run. The fallback handles the race
        # where the activity panel is polled before the attempt is
        # registered, or after a retry where current_attempt_id is
        # briefly stale.
        attempt = None
        if task.current_attempt_id is not None:
            try:
                attempt = await self._harness_attempts(task.current_attempt_id)
            except Exception:  # noqa: BLE001 - attempt lookup is best effort
                attempt = None

        if attempt is None and self._harness_attempt_finder is not None:
            # Fallback: find the latest attempt by task_run_id.
            try:
                attempt = await self._harness_attempt_finder(task.id)
            except Exception:  # noqa: BLE001
                attempt = None

        if attempt is None:
            # No attempt registered yet — the task may not have started.
            if task.status in {"CREATED", "QUEUED", "READY"}:
                activity.note = "HARNESS_SESSION_PENDING"
                return activity
            if task.status == "RUNNING":
                # The attempt has not been registered yet while the task is
                # executing — a wait state, not an error. Plan-orchestrated
                # tasks expose their transcripts per subtask instead (see
                # the subtask activity endpoint).
                activity.note = "HARNESS_SESSION_PENDING"
                activity.running = True
                return activity
            activity.note = "HARNESS_SESSION_NOT_BOUND"
            return activity

        if attempt.external_session_id is None:
            # Attempt exists but session hasn't been bound yet.
            # This is normal during the brief window between
            # register_attempt and bind_session.
            activity.note = "HARNESS_SESSION_BINDING"
            activity.running = task.status == "RUNNING"
            return activity

        activity.session_id = attempt.external_session_id
        try:
            events = await self._harness_events(attempt.external_session_id, 200)
        except Exception as exc:  # noqa: BLE001 - degrade into a note
            activity.note = _error_note(exc)
            if task.status == "RUNNING":
                activity.running = True
            return activity

        entries, total = _normalize_harness_events(events)
        activity.entries = entries
        activity.entries_total = total
        activity.running = task.status == "RUNNING"
        return activity


def _normalize_harness_events(events: list[dict[str, object]]) -> tuple[list[TaskActivityEntry], int]:
    raw: list[tuple[int, str, str, str | None, str | None]] = []
    fallback_seq = 0
    for event in events:
        event_type = event.get("type") if isinstance(event.get("type"), str) else "event"
        seq = event.get("seq")
        seq = seq if isinstance(seq, int) and seq >= 0 else fallback_seq
        fallback_seq = max(fallback_seq, seq) + 1
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event_type in {"assistant/message", "user/message"}:
            role = "Assistant" if event_type == "assistant/message" else "Prompt"
            text = _harness_message_text(data)
            if not text:
                continue
            raw.append((seq, "text" if role == "Assistant" else "prompt", role, _preview(text, _TEXT_PREVIEW_CHARS), None))
        elif event_type == "session/created":
            raw.append((seq, "system", "Session created", _preview(_compact(data), _EVENT_PREVIEW_CHARS), None))
        else:
            title = event_type.replace("/", " · ").replace("_", " ")
            raw.append((seq, "event", title, _preview(_compact(data), _EVENT_PREVIEW_CHARS), None))

    total = len(raw)
    kept = raw[-_MAX_ENTRIES:]
    entries = [
        TaskActivityEntry(seq=index, kind=kind, title=title, detail=detail, occurred_at=occurred)
        for index, (seq, kind, title, detail, occurred) in enumerate(kept)
    ]
    return entries, total


# ---- helpers -----------------------------------------------------------


def _compact(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _error_note(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else type(exc).__name__


def _newest_opencode_session(sessions: tuple[dict[str, Any], ...]) -> str | None:
    best_id: str | None = None
    best_updated = -1
    for session in sessions:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id:
            continue
        time_info = session.get("time") if isinstance(session.get("time"), dict) else {}
        updated = time_info.get("updated", time_info.get("created", 0))
        updated = updated if isinstance(updated, (int, float)) and not isinstance(updated, bool) else 0
        if updated >= best_updated:
            best_updated = updated
            best_id = session_id
    return best_id


def _opencode_time(info: dict[str, Any]) -> str | None:
    time_info = info.get("time") if isinstance(info.get("time"), dict) else {}
    created = time_info.get("created")
    if isinstance(created, (int, float)) and not isinstance(created, bool) and created > 0:
        return datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
    return None


def _opencode_last_unfinished(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        info = message.get("info") if isinstance(message.get("info"), dict) else {}
        if info.get("role") != "assistant":
            continue
        finish = info.get("finish")
        return not (isinstance(finish, str) and finish and finish not in {"tool-calls", "unknown"})
    return False


def _opencode_tool_entry(part: dict[str, Any], created: str | None) -> tuple[str, str, str | None, str | None, str | None]:
    tool = part.get("tool") if isinstance(part.get("tool"), str) else "tool"
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    status = state.get("status") if isinstance(state.get("status"), str) else None
    title = state.get("title") if isinstance(state.get("title"), str) else ""
    input_data = state.get("input") if isinstance(state.get("input"), dict) else {}
    output = state.get("output") if isinstance(state.get("output"), str) else None
    if output and output.strip():
        detail = _preview(output, _TOOL_OUTPUT_PREVIEW_CHARS)
    elif input_data:
        detail = _preview(_compact(input_data), _TOOL_INPUT_PREVIEW_CHARS)
    else:
        detail = None
    heading = f"{tool}: {title}" if title else tool
    return ("tool", heading, detail, status, created)


def _harness_message_text(data: dict[str, object]) -> str:
    message = data.get("message") if isinstance(data.get("message"), dict) else data
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    parts = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(part for part in parts if part)

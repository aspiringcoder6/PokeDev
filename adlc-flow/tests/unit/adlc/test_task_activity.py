"""Unit tests for the read-only task activity projection service."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.models import ExecutorTarget, TaskRun, TaskRunStatus
from langflow.adlc.opencode_client import OpenCodeClientError
from langflow.adlc.task_activity import (
    OPENCODE_SERVICE,
    TaskActivityService,
)

def _message(message_id: str, *, role: str, finish: str | None, parts: list[dict]) -> dict:
    info: dict[str, Any] = {"id": message_id, "role": role, "time": {"created": 1700000000000}}
    if finish is not None:
        info["finish"] = finish
    return {"info": info, "parts": parts}


def _task(*, service: str = OPENCODE_SERVICE, attempt_id: Any = None) -> TaskRun:
    attempt = attempt_id or uuid4()
    return TaskRun(
        id=uuid4(),
        workflow_run_id=uuid4(),
        task_definition_id=uuid4(),
        key="task-1",
        name="Implement API",
        task_type="IMPLEMENTATION",
        status=TaskRunStatus.RUNNING,
        dependency_task_run_ids=[],
        executor=ExecutorTarget(service=service, operation="coding-task"),
        current_attempt_id=attempt,
    )


class StubOpenCodeClient:
    def __init__(self, *, sessions: tuple[dict, ...] = (), messages: list[dict] | None = None, error: OpenCodeClientError | None = None) -> None:
        self.sessions = sessions
        self.messages = messages or []
        self.error = error
        self.listed: list[str] = []
        self.fetched: list[str] = []

    async def list_sessions(self, *, directory: str, timeout_ms: int = 5000) -> tuple[dict, ...]:
        self.listed.append(directory)
        if self.error is not None:
            raise self.error
        return self.sessions

    async def get_messages(self, session_id: str, *, directory: str, timeout_ms: int) -> list[dict]:
        self.fetched.append(session_id)
        if self.error is not None:
            raise self.error
        return self.messages


@dataclass
class StubAttempt:
    external_session_id: str | None = "session-1"
    calls: list = field(default_factory=list)


def test_collect_opencode_normalizes_transcript() -> None:
    attempt_id = uuid4()
    messages = [
        _message("msg-user", role="user", finish=None, parts=[{"type": "text", "text": "Execute this ADLC task"}]),
        _message(
            "msg-a1",
            role="assistant",
            finish="tool-calls",
            parts=[
                {"type": "step-start"},
                {"type": "reasoning", "text": "Analyzing the task requirements"},
                {"type": "tool", "tool": "bash", "state": {"status": "completed", "title": "ls -la", "input": {"command": "ls -la"}, "output": "total 40"}},
                {"type": "text", "text": "Created the module"},
            ],
        ),
    ]
    client = StubOpenCodeClient(sessions=({"id": "ses_test", "time": {"updated": 1}},), messages=messages)
    service = TaskActivityService(opencode_client=client, worktree_root=Path("/tmp/adlc-worktrees"), harness_events=None, harness_attempts=None)
    task = _task(attempt_id=attempt_id)

    response = asyncio.run(service.collect(task))

    assert response.name == "Implement API"
    assert response.executor_service == OPENCODE_SERVICE
    assert response.agent is not None
    assert response.agent.session_id == "ses_test"
    assert response.agent.directory == str(Path("/tmp/adlc-worktrees") / f"worktree-{attempt_id}")
    assert response.agent.running is True
    kinds = [entry.kind for entry in response.agent.entries]
    assert kinds == ["prompt", "reasoning", "tool", "text"]
    tool_entry = response.agent.entries[2]
    assert tool_entry.title == "bash: ls -la"
    assert tool_entry.status == "completed"
    assert tool_entry.detail == "total 40"


def test_collect_opencode_falls_back_to_session_listing() -> None:
    sessions = ({"id": "ses_old", "time": {"updated": 1}}, {"id": "ses_new", "time": {"updated": 999}})
    client = StubOpenCodeClient(sessions=sessions, messages=[])
    service = TaskActivityService(opencode_client=client, worktree_root=Path("/tmp/adlc-worktrees"), harness_events=None, harness_attempts=None)

    response = asyncio.run(service.collect(_task()))

    assert response.agent is not None
    assert response.agent.session_id == "ses_new"


def test_collect_opencode_degrades_agent_failure_into_note() -> None:
    client = StubOpenCodeClient(error=OpenCodeClientError(code="OPENCODE_SERVER_UNAVAILABLE", category="DEPENDENCY", retryable=True))
    service = TaskActivityService(opencode_client=client, worktree_root=Path("/tmp/adlc-worktrees"), harness_events=None, harness_attempts=None)

    response = asyncio.run(service.collect(_task()))

    assert response.agent is not None
    assert response.agent.entries == []
    assert response.agent.note == "OPENCODE_SERVER_UNAVAILABLE"
    assert response.status == "RUNNING"


def test_collect_harness_uses_attempt_repository() -> None:
    @dataclass
    class HarnessStub:
        events: list[dict]

        async def session_events(self, session_id: str, max_events: int) -> list[dict]:
            return self.events

    events = [
        {"seq": 1, "type": "user/message", "data": {"message": {"content": [{"type": "text", "text": "prompt"}]}}},
        {"seq": 2, "type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "final answer"}]}}},
    ]
    attempts: dict[str, Any] = {}

    async def attempt_getter(attempt_id):
        return StubAttempt(external_session_id="session-abc")

    harness = HarnessStub(events=events)
    service = TaskActivityService(opencode_client=None, worktree_root=None, harness_events=harness.session_events, harness_attempts=attempt_getter)

    response = asyncio.run(service.collect(_task(service="agent-provider:deepseek-harness")))

    assert response.agent is not None
    assert response.agent.source == "agent-provider:deepseek-harness"
    assert response.agent.session_id == "session-abc"
    kinds = [entry.kind for entry in response.agent.entries]
    assert kinds == ["prompt", "text"]
    assert response.agent.entries[1].detail == "final answer"

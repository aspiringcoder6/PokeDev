"""Tests for the subtask activity endpoint.

The endpoint returns the live DSH transcript for a single subtask by
resolving the subtask's session id from the in-process registry and
querying the DSH gateway for the latest events.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from langflow.adlc.subtask_registry import get_subtask_registry
from langflow.adlc.task_subtasks import SubtaskRun, TaskSubtasksResponse


def _make_subtask(
    subtask_id: str,
    *,
    status: str = "running",
    session_id: str | None = None,
) -> SubtaskRun:
    return SubtaskRun(
        id=subtask_id,
        task_run_id="00000000-0000-0000-0000-000000000001",
        name=f"Subtask {subtask_id}",
        description="",
        objective="",
        status=status,
        dependencies=[],
        trigger="on_success",
        timeout_seconds=600,
        expected_outputs=[],
        result={"session_id": session_id} if session_id else None,
    )


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset the subtask registry between tests."""
    registry = get_subtask_registry()
    # Snapshot existing entries to restore later if needed.
    yield
    # Best-effort cleanup: forget any entries created during the test.
    for key in list(registry._entries.keys()):  # noqa: SLF001
        registry._entries.pop(key, None)  # noqa: SLF001


async def test_subtask_activity_returns_pending_when_no_session() -> None:
    """When the subtask has no session id yet, return PENDING note."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()
    subtask_id = "task-1.sub-1"

    # Register a subtask without a session id.
    registry = get_subtask_registry()
    registry._entries[(str(run_id), str(task_run_id))] = {  # noqa: SLF001
        subtask_id: _make_subtask(subtask_id, status="pending", session_id=None),
    }

    # Mock the run service to return a run with the task.
    service = MagicMock()
    run = MagicMock()
    task = MagicMock()
    task.id = task_run_id
    run.tasks = [task]
    service.get_run = AsyncMock(return_value=run)

    # Mock the activity service (no harness_events needed for this case).
    activity_service = MagicMock()
    activity_service._harness_events = None  # noqa: SLF001

    current_user = MagicMock()
    current_user.id = "owner-1"

    result = await get_adlc_subtask_activity(
        run_id=run_id,
        task_run_id=task_run_id,
        subtask_id=subtask_id,
        current_user=current_user,
        service=service,
        activity_service=activity_service,
    )

    assert result.source == "agent-provider:deepseek-harness"
    assert result.note == "HARNESS_SESSION_PENDING"
    assert result.session_id is None
    assert result.entries == []


async def test_subtask_activity_returns_events_when_session_bound() -> None:
    """When the subtask has a session id, fetch events from DSH."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()
    subtask_id = "task-1.sub-1"
    session_id = "dsh-session-abc123"

    # Register a subtask with a session id.
    registry = get_subtask_registry()
    registry._entries[(str(run_id), str(task_run_id))] = {  # noqa: SLF001
        subtask_id: _make_subtask(subtask_id, status="running", session_id=session_id),
    }

    # Mock the run service.
    service = MagicMock()
    run = MagicMock()
    task = MagicMock()
    task.id = task_run_id
    run.tasks = [task]
    service.get_run = AsyncMock(return_value=run)

    # Mock the activity service with a harness_events callable.
    events = [
        {"type": "session/created", "seq": 0, "data": {"session_id": session_id}},
        {
            "type": "assistant/message",
            "seq": 1,
            "data": {
                "message": {
                    "content": [{"type": "text", "text": "Hello from DSH"}],
                },
            },
        },
    ]
    activity_service = MagicMock()
    activity_service._harness_events = AsyncMock(return_value=events)  # noqa: SLF001

    current_user = MagicMock()
    current_user.id = "owner-1"

    result = await get_adlc_subtask_activity(
        run_id=run_id,
        task_run_id=task_run_id,
        subtask_id=subtask_id,
        current_user=current_user,
        service=service,
        activity_service=activity_service,
    )

    assert result.source == "agent-provider:deepseek-harness"
    assert result.session_id == session_id
    assert result.note is None
    assert len(result.entries) == 2
    assert result.entries[0].title == "Session created"
    assert result.entries[1].title == "Assistant"
    assert "Hello from DSH" in (result.entries[1].detail or "")


async def test_subtask_activity_returns_not_registered_when_no_snapshot() -> None:
    """When the registry has no entry for the task, return NOT_REGISTERED."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()
    subtask_id = "task-1.sub-1"

    # No registry entry for this task.
    service = MagicMock()
    run = MagicMock()
    task = MagicMock()
    task.id = task_run_id
    run.tasks = [task]
    service.get_run = AsyncMock(return_value=run)

    activity_service = MagicMock()
    current_user = MagicMock()
    current_user.id = "owner-1"

    result = await get_adlc_subtask_activity(
        run_id=run_id,
        task_run_id=task_run_id,
        subtask_id=subtask_id,
        current_user=current_user,
        service=service,
        activity_service=activity_service,
    )

    assert result.note == "SUBTASK_NOT_REGISTERED"


async def test_subtask_activity_raises_404_for_unknown_subtask() -> None:
    """When the subtask id is not in the registry, raise 404."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()

    # Register a different subtask.
    registry = get_subtask_registry()
    registry._entries[(str(run_id), str(task_run_id))] = {  # noqa: SLF001
        "task-1.sub-1": _make_subtask("task-1.sub-1", status="running"),
    }

    service = MagicMock()
    run = MagicMock()
    task = MagicMock()
    task.id = task_run_id
    run.tasks = [task]
    service.get_run = AsyncMock(return_value=run)

    activity_service = MagicMock()
    current_user = MagicMock()
    current_user.id = "owner-1"

    with pytest.raises(HTTPException) as exc_info:
        await get_adlc_subtask_activity(
            run_id=run_id,
            task_run_id=task_run_id,
            subtask_id="task-1.sub-999",
            current_user=current_user,
            service=service,
            activity_service=activity_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "SUBTASK_NOT_FOUND"


async def test_subtask_activity_raises_404_for_unknown_task() -> None:
    """When the task is not in the run, raise 404."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()
    subtask_id = "task-1.sub-1"

    service = MagicMock()
    run = MagicMock()
    run.tasks = []  # No tasks in the run.
    service.get_run = AsyncMock(return_value=run)

    activity_service = MagicMock()
    current_user = MagicMock()
    current_user.id = "owner-1"

    with pytest.raises(HTTPException) as exc_info:
        await get_adlc_subtask_activity(
            run_id=run_id,
            task_run_id=task_run_id,
            subtask_id=subtask_id,
            current_user=current_user,
            service=service,
            activity_service=activity_service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "TASK_RUN_NOT_FOUND"


async def test_subtask_activity_degrades_on_harness_error() -> None:
    """When harness_events raises, return a note instead of crashing."""
    from langflow.api.v1.adlc import get_adlc_subtask_activity

    run_id = uuid4()
    task_run_id = uuid4()
    subtask_id = "task-1.sub-1"
    session_id = "dsh-session-abc123"

    registry = get_subtask_registry()
    registry._entries[(str(run_id), str(task_run_id))] = {  # noqa: SLF001
        subtask_id: _make_subtask(subtask_id, status="running", session_id=session_id),
    }

    service = MagicMock()
    run = MagicMock()
    task = MagicMock()
    task.id = task_run_id
    run.tasks = [task]
    service.get_run = AsyncMock(return_value=run)

    # Mock harness_events to raise an error.
    activity_service = MagicMock()
    activity_service._harness_events = AsyncMock(  # noqa: SLF001
        side_effect=Exception("DSH gateway timeout"),
    )

    current_user = MagicMock()
    current_user.id = "owner-1"

    result = await get_adlc_subtask_activity(
        run_id=run_id,
        task_run_id=task_run_id,
        subtask_id=subtask_id,
        current_user=current_user,
        service=service,
        activity_service=activity_service,
    )

    assert result.session_id == session_id
    assert result.note == "Exception"  # type name of the exception
    assert result.running is True  # subtask is still running

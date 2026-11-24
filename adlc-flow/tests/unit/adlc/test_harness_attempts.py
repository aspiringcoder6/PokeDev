# ruff: noqa: INP001, S101

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from langflow.adlc.harness_attempts import (
    DELIVERY_CONFLICT,
    HarnessAttemptError,
    SqliteTaskAttemptRepository,
)
from langflow.adlc.harness_models import HarnessCorrelation, HarnessSessionResult, TaskAttemptStatus
from langflow.adlc.models import ExecutorTarget, TaskRequest, TaskResultStatus

if TYPE_CHECKING:
    from pathlib import Path


def _request() -> TaskRequest:
    workflow_run_id = uuid4()
    task_run_id = uuid4()
    attempt_id = uuid4()
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=workflow_run_id,
        task_run_id=task_run_id,
        attempt_id=attempt_id,
        task_definition_id=uuid4(),
        task_type="coding",
        name="Durable Harness task",
        executor=ExecutorTarget(service="agent-provider:deepseek-harness", operation="coding-task"),
        input={"objective": "Implement it."},
        context={},
        dependency_task_run_ids=[],
        constraints={"timeout_ms": 1000},
        idempotency_key=f"{workflow_run_id}:{task_run_id}:{attempt_id}",
        requested_at=datetime.now(timezone.utc),
    )


def _result(request: TaskRequest, *, summary: str = "done") -> HarnessSessionResult:
    now = datetime.now(timezone.utc)
    return HarnessSessionResult(
        session_id="session-durable",
        correlation=HarnessCorrelation(
            request_id=request.request_id,
            workflow_run_id=request.workflow_run_id,
            task_run_id=request.task_run_id,
            attempt_id=request.attempt_id,
        ),
        status=TaskResultStatus.SUCCEEDED,
        output={"summary": summary},
        artifacts=[],
        error=None,
        started_at=now,
        completed_at=now,
    )


async def test_sqlite_attempt_and_delivery_dedup_survive_repository_restart(tmp_path: Path) -> None:
    database = tmp_path / "harness-attempts.sqlite3"
    request = _request()
    delivery_id = uuid4()
    result = _result(request)
    first_repository = SqliteTaskAttemptRepository(database)

    created = await first_repository.create(request)
    assert created.status is TaskAttemptStatus.CREATED
    await first_repository.bind_session(request.attempt_id, "session-durable")
    await first_repository.update_status(request.attempt_id, TaskAttemptStatus.RUNNING)
    accepted, duplicate = await first_repository.accept_delivery(delivery_id, result)

    assert duplicate is False
    assert accepted.status is TaskAttemptStatus.SUCCEEDED

    restarted = SqliteTaskAttemptRepository(database)
    restored = await restarted.find_by_session("session-durable")
    replayed, duplicate = await restarted.accept_delivery(delivery_id, result)

    assert restored.result is not None
    assert restored.status is TaskAttemptStatus.SUCCEEDED
    assert replayed == restored
    assert duplicate is True
    assert await restarted.list_unfinished() == []
    assert [item.attempt_id for item in await restarted.list_for_workflow_run(request.workflow_run_id)] == [
        request.attempt_id
    ]

    with pytest.raises(HarnessAttemptError) as conflict:
        await restarted.accept_delivery(delivery_id, _result(request, summary="different"))
    assert conflict.value.code == DELIVERY_CONFLICT

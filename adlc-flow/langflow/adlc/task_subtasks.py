"""Task subtasks response model and service.

After the user accepts a high-level plan, the system SDKs to DSH for
each task and asks "how would you divide this task into parallel
subtasks?". The response is cached so subsequent calls return the
same subtasks.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from langflow.adlc.models import TaskRun

logger = logging.getLogger(__name__)


class SubtaskRun(BaseModel):
    """A single subtask within a task."""

    id: str
    task_run_id: str = ""
    name: str
    description: str = ""
    objective: str = ""
    status: str = "pending"
    dependencies: list[str] = Field(default_factory=list)
    trigger: str = "on_success"
    timeout_seconds: int = 600
    expected_outputs: list[str] = Field(default_factory=list)
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    attempt_id: str | None = None


class SubtaskSummary(BaseModel):
    """Aggregated stats for a task's subtasks."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    running: int = 0
    pending: int = 0
    skipped: int = 0


class TaskSubtasksResponse(BaseModel):
    """Response for the task subtasks endpoint."""

    task_run_id: UUID
    subtasks: list[SubtaskRun] = Field(default_factory=list)
    summary: SubtaskSummary = Field(default_factory=SubtaskSummary)
    is_mock: bool = False
    note: str | None = None


__all__ = [
    "SubtaskRun",
    "SubtaskSummary",
    "TaskSubtasksResponse",
]

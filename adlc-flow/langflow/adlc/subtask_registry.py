"""Live subtask progress registry for the run-detail subtask panel.

The plan orchestrator executes each subtask as an independent DSH session;
this registry mirrors that live progress so the
``GET /runs/{id}/tasks/{task_id}/subtasks`` endpoint can report real
statuses (running / succeeded / failed) plus per-subtask execution detail
while the task is still executing.

It reuses the response models from :mod:`langflow.adlc.task_subtasks` so
the API contract stays in one place. The registry is process-local and
best-effort: a restart loses live progress and callers fall back to the
static template projection.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langflow.adlc.plan_state import SubtaskStatus
from langflow.adlc.task_subtasks import SubtaskRun, SubtaskSummary, TaskSubtasksResponse

if TYPE_CHECKING:
    from langflow.adlc.plan_models import PlanSpec

_SUMMARY_KEYS = ("succeeded", "failed", "running", "pending", "skipped")


def summarize(subtasks: list[SubtaskRun]) -> SubtaskSummary:
    """Aggregate the summary counters for a subtask list."""
    counts: dict[str, int] = {}
    for subtask in subtasks:
        counts[subtask.status] = counts.get(subtask.status, 0) + 1
    return SubtaskSummary(
        total=len(subtasks),
        succeeded=counts.get("succeeded", 0),
        failed=counts.get("failed", 0),
        running=counts.get("running", 0),
        pending=counts.get("pending", 0) + counts.get("ready", 0),
        skipped=counts.get("skipped", 0),
    )


class SubtaskRegistry:
    """Thread-safe in-process store of live subtask progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], dict[str, SubtaskRun]] = {}

    def register_plan(self, workflow_run_id: UUID, task_run_id: UUID, plan: PlanSpec) -> None:
        """Seed the registry with every subtask of the (single-task) plan."""
        task_spec = plan.tasks[0]
        rows: dict[str, SubtaskRun] = {}
        for subtask in task_spec.subtasks:
            rows[subtask.id] = SubtaskRun(
                id=subtask.id,
                task_run_id=str(task_run_id),
                name=subtask.name,
                description=subtask.description,
                objective=subtask.objective,
                status="pending",
                dependencies=list(subtask.dependencies),
                trigger=subtask.trigger.value,
                timeout_seconds=int(subtask.timeout_seconds) if subtask.timeout_seconds else 600,
                expected_outputs=list(subtask.expected_outputs),
            )
        with self._lock:
            self._entries[(str(workflow_run_id), str(task_run_id))] = rows

    def observe(
        self,
        workflow_run_id: UUID,
        task_run_id: UUID,
        subtask_id: str,
        *,
        status: str,
        attempt_id: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        duration_ms: int | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, str] | None = None,
    ) -> None:
        """Update one subtask row; unknown plans are ignored."""
        with self._lock:
            rows = self._entries.get((str(workflow_run_id), str(task_run_id)))
            if rows is None or subtask_id not in rows:
                return
            row = rows[subtask_id]
            rows[subtask_id] = row.model_copy(
                update={
                    "status": status.value if isinstance(status, SubtaskStatus) else status,
                    "attempt_id": attempt_id or row.attempt_id,
                    "started_at": started_at or row.started_at,
                    "completed_at": completed_at or row.completed_at,
                    "duration_ms": duration_ms if duration_ms is not None else row.duration_ms,
                    "result": result if result is not None else row.result,
                    "error": error if error is not None else row.error,
                }
            )

    def snapshot(self, workflow_run_id: UUID | str, task_run_id: UUID | str) -> TaskSubtasksResponse | None:
        """Project the live subtask state, or ``None`` when nothing is registered."""
        task_uuid = task_run_id if isinstance(task_run_id, UUID) else UUID(str(task_run_id))
        with self._lock:
            rows = self._entries.get((str(workflow_run_id), str(task_run_id)))
            if rows is None:
                return None
            subtasks = [rows[key] for key in sorted(rows)]
        return TaskSubtasksResponse(
            task_run_id=task_uuid,
            subtasks=subtasks,
            summary=summarize(subtasks),
            is_mock=False,
        )

    def forget(self, workflow_run_id: UUID | str, task_run_id: UUID | str) -> None:
        """Drop one entry (used when a run is removed or a task restarts)."""
        with self._lock:
            self._entries.pop((str(workflow_run_id), str(task_run_id)), None)


_registry = SubtaskRegistry()


def get_subtask_registry() -> SubtaskRegistry:
    """Return the process-wide subtask registry."""
    return _registry


__all__ = [
    "SubtaskRegistry",
    "get_subtask_registry",
    "summarize",
]

"""Plan-level subtask cache.

After a user approves an execution plan, the system pre-generates subtasks
for every task in the plan by SDKing to DSH. The generated subtasks are
stored in this cache (keyed by plan_id) so that:

1. The Run button on the PlanDetailPage is only enabled after all subtasks
   are generated (no more "TASK_EXECUTION_CRASHED" because subtasks
   weren't ready when the run started).
2. When the run is created, the pre-generated subtasks are copied into
   the subtask registry so the executor has them ready.
3. The user sees a "Preparing subtasks..." spinner during generation.

The cache is process-local and best-effort: a restart loses the cache and
the system falls back to on-demand generation when viewing subtasks.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from uuid import UUID

from langflow.adlc.task_subtasks import SubtaskRun, SubtaskSummary, TaskSubtasksResponse

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PlanSubtaskCache:
    """Thread-safe in-process store of pre-generated subtasks per plan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # plan_id -> {task_id -> TaskSubtasksResponse}
        self._entries: dict[str, dict[str, TaskSubtasksResponse]] = {}
        # plan_id -> {"pending" | "ready" | "failed", "error": str | None}
        self._status: dict[str, dict[str, str]] = {}

    def set_status(
        self,
        plan_id: UUID | str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update the preparation status for a plan."""
        with self._lock:
            self._status[str(plan_id)] = {"status": status, "error": error or ""}

    def get_status(self, plan_id: UUID | str) -> dict[str, str]:
        """Return the preparation status for a plan."""
        with self._lock:
            return dict(self._status.get(str(plan_id), {"status": "pending", "error": ""}))

    def store_subtasks(
        self,
        plan_id: UUID | str,
        task_id: UUID | str,
        response: TaskSubtasksResponse,
    ) -> None:
        """Store pre-generated subtasks for one task in a plan."""
        with self._lock:
            plan_entries = self._entries.setdefault(str(plan_id), {})
            plan_entries[str(task_id)] = response

    def get_subtasks(
        self,
        plan_id: UUID | str,
        task_id: UUID | str,
    ) -> TaskSubtasksResponse | None:
        """Return pre-generated subtasks for one task, or None."""
        with self._lock:
            plan_entries = self._entries.get(str(plan_id))
            if plan_entries is None:
                return None
            return plan_entries.get(str(task_id))

    def get_all_subtasks(
        self,
        plan_id: UUID | str,
    ) -> dict[str, TaskSubtasksResponse]:
        """Return all pre-generated subtasks for a plan."""
        with self._lock:
            plan_entries = self._entries.get(str(plan_id))
            if plan_entries is None:
                return {}
            return dict(plan_entries)

    def is_ready(self, plan_id: UUID | str) -> bool:
        """Return True when all subtasks for the plan have been generated."""
        with self._lock:
            return self._status.get(str(plan_id), {}).get("status") == "ready"

    def forget(self, plan_id: UUID | str) -> None:
        """Drop all entries for a plan (used when a plan is superseded)."""
        with self._lock:
            self._entries.pop(str(plan_id), None)
            self._status.pop(str(plan_id), None)


_cache = PlanSubtaskCache()


def get_plan_subtask_cache() -> PlanSubtaskCache:
    """Return the process-wide plan subtask cache."""
    return _cache


def summarize_subtasks(subtasks: list[SubtaskRun]) -> SubtaskSummary:
    """Aggregate summary counters for a subtask list."""
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


__all__ = [
    "PlanSubtaskCache",
    "get_plan_subtask_cache",
    "summarize_subtasks",
]

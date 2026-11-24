# ruff: noqa: INP001, PLR2004, S101, S106

"""Unit tests for the plan-level subtask cache."""

from __future__ import annotations

from uuid import uuid4

from langflow.adlc.plan_subtask_cache import (
    PlanSubtaskCache,
    get_plan_subtask_cache,
    summarize_subtasks,
)
from langflow.adlc.task_subtasks import SubtaskRun, SubtaskSummary, TaskSubtasksResponse


def _make_subtask(status: str = "pending") -> SubtaskRun:
    return SubtaskRun(
        id="sub-1",
        name="Subtask 1",
        description="Do thing 1",
        objective="Do thing 1 as part of the larger task",
        status=status,
        dependencies=[],
        trigger="on_success",
        timeout_seconds=600,
        expected_outputs=["summary"],
    )


def _make_response(task_id, subtasks: list[SubtaskRun]) -> TaskSubtasksResponse:
    return TaskSubtasksResponse(
        task_run_id=task_id,
        subtasks=subtasks,
        summary=SubtaskSummary(
            total=len(subtasks),
            succeeded=sum(1 for s in subtasks if s.status == "succeeded"),
            failed=sum(1 for s in subtasks if s.status == "failed"),
            running=sum(1 for s in subtasks if s.status == "running"),
            pending=sum(1 for s in subtasks if s.status in ("pending", "ready")),
            skipped=sum(1 for s in subtasks if s.status == "skipped"),
        ),
        is_mock=False,
    )


class TestPlanSubtaskCache:
    def test_initial_status_is_pending(self):
        cache = PlanSubtaskCache()
        plan_id = uuid4()
        assert cache.get_status(plan_id) == {"status": "pending", "error": ""}
        assert cache.is_ready(plan_id) is False

    def test_set_status_updates_state(self):
        cache = PlanSubtaskCache()
        plan_id = uuid4()
        cache.set_status(plan_id, status="ready")
        assert cache.is_ready(plan_id) is True
        cache.set_status(plan_id, status="failed", error="boom")
        assert cache.get_status(plan_id) == {"status": "failed", "error": "boom"}
        assert cache.is_ready(plan_id) is False

    def test_store_and_get_subtasks(self):
        cache = PlanSubtaskCache()
        plan_id = uuid4()
        task_id = uuid4()
        response = _make_response(task_id, [_make_subtask()])
        cache.store_subtasks(plan_id, task_id, response)
        assert cache.get_subtasks(plan_id, task_id) == response

    def test_get_subtasks_returns_none_when_missing(self):
        cache = PlanSubtaskCache()
        assert cache.get_subtasks(uuid4(), uuid4()) is None

    def test_get_all_subtasks(self):
        cache = PlanSubtaskCache()
        plan_id = uuid4()
        task_a = uuid4()
        task_b = uuid4()
        cache.store_subtasks(plan_id, task_a, _make_response(task_a, [_make_subtask()]))
        cache.store_subtasks(plan_id, task_b, _make_response(task_b, [_make_subtask()]))
        all_subtasks = cache.get_all_subtasks(plan_id)
        assert len(all_subtasks) == 2
        assert str(task_a) in all_subtasks
        assert str(task_b) in all_subtasks

    def test_forget_drops_entries(self):
        cache = PlanSubtaskCache()
        plan_id = uuid4()
        task_id = uuid4()
        cache.set_status(plan_id, status="ready")
        cache.store_subtasks(plan_id, task_id, _make_response(task_id, [_make_subtask()]))
        cache.forget(plan_id)
        assert cache.get_status(plan_id) == {"status": "pending", "error": ""}
        assert cache.get_subtasks(plan_id, task_id) is None

    def test_get_plan_subtask_cache_returns_singleton(self):
        a = get_plan_subtask_cache()
        b = get_plan_subtask_cache()
        assert a is b


class TestSummarizeSubtasks:
    def test_counts_each_status(self):
        subtasks = [
            _make_subtask("succeeded"),
            _make_subtask("succeeded"),
            _make_subtask("failed"),
            _make_subtask("running"),
            _make_subtask("pending"),
            _make_subtask("ready"),
            _make_subtask("skipped"),
        ]
        summary = summarize_subtasks(subtasks)
        assert summary.total == 7
        assert summary.succeeded == 2
        assert summary.failed == 1
        assert summary.running == 1
        assert summary.pending == 2  # pending + ready
        assert summary.skipped == 1

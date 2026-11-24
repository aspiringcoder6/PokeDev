"""Post-run reflection dispatch (plan package G6).

When a workflow run reaches SUCCEEDED or FAILED, the run coordinator
calls ``dispatch_run_reflection`` to ask the orchestrator's reflection
plugin for a ``ReflectionReport`` (successes / failures / suggestions)
and stores it on the run metadata. The dispatcher:

* is configuration-gated via ``ADLC_RUN_REFLECTION``
  (see ``quality_gate_policy.py``);
* uses the production ``OrchestratorHost`` and picks the first enabled
  plugin declaring the ``REFLECTION`` capability (Monarch today);
* never raises — observability must not break orchestration; callers
  receive ``None`` when reflection is disabled or unavailable.

Run services may inject their own async dispatcher for tests, keeping
the coordinator independent from the plugin registry.
"""

from __future__ import annotations

import logging
from typing import Any

from langflow.adlc.models import TaskRunStatus, WorkflowRun
from langflow.adlc.orchestrator_plugin.host import get_production_host
from langflow.adlc.orchestrator_plugin.interface import ExecutionResult, ReflectionReport, StepResult
from langflow.adlc.quality_gate_policy import reflection_enabled
from langflow.adlc.resource_manager import AgentCapability

logger = logging.getLogger(__name__)

_REFLECTION_CAPABILITY = frozenset({AgentCapability.REFLECTION})

_STEP_STATUS = {
    TaskRunStatus.SUCCEEDED: "succeeded",
    TaskRunStatus.FAILED: "failed",
    TaskRunStatus.SKIPPED: "skipped",
}


def _build_execution_result(run: WorkflowRun, outcome: str) -> ExecutionResult:
    """Project a finished workflow run onto the plugin ExecutionResult shape."""
    plan_id = next(
        (
            task.plan_traceability.execution_plan_id
            for task in run.tasks
            if task.plan_traceability is not None
        ),
        run.id,
    )
    step_results = tuple(
        StepResult(
            step_id=task.id,
            status=_STEP_STATUS.get(task.status, "failed"),
            output=task.result.output if task.result is not None else None,
            error=task.result.error.code if task.result is not None and task.result.error else None,
            started_at=task.started_at or run.created_at,
            completed_at=task.completed_at or run.created_at,
            artifacts=(),
        )
        for task in run.tasks
    )
    started_at = min((task.started_at for task in run.tasks if task.started_at is not None), default=run.created_at)
    completed_at = max(
        (task.completed_at for task in run.tasks if task.completed_at is not None),
        default=run.created_at,
    )
    return ExecutionResult(
        plan_id=plan_id,
        intent_id=run.id,
        status=outcome,
        step_results=step_results,
        started_at=started_at,
        completed_at=completed_at,
        plugin_id=_reflection_plugin_id(),
    )


def _reflection_plugin_id() -> str:
    """Pick the production plugin that owns reflection (Monarch today)."""
    host = get_production_host()
    for plugin in host.find_capable(_REFLECTION_CAPABILITY):
        return plugin.metadata.plugin_id
    for metadata in host.list_metadata():
        if metadata.enabled:
            return metadata.plugin_id
    return "monarch"


async def dispatch_run_reflection(run: WorkflowRun, outcome: str) -> ReflectionReport | None:
    """Dispatch reflect() on the production host; return None when unavailable."""
    if not reflection_enabled():
        return None
    host = get_production_host()
    execution_result = _build_execution_result(run, outcome)
    try:
        return await host.dispatch_reflect(execution_result)
    except Exception as exc:  # noqa: BLE001 - reflection must never break a run
        logger.warning("ADLC reflection dispatch failed for run %s: %s", run.id, exc)
        return None


def reflection_metadata(report: ReflectionReport) -> dict[str, Any]:
    """Project a ReflectionReport onto the run metadata payload."""
    return {
        "report_id": str(report.report_id),
        "plan_id": str(report.plan_id),
        "intent_id": str(report.intent_id),
        "summary": report.summary,
        "successes": list(report.successes),
        "failures": list(report.failures),
        "suggestions": list(report.suggestions),
        "plugin_id": report.plugin_id,
        "created_at": report.created_at.isoformat(),
    }


__all__ = ["dispatch_run_reflection", "reflection_metadata"]

"""Opt-in DeepSeek Harness runtime composition and readiness reporting."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_callbacks import HarnessCallbackError, HarnessCallbackReceiver
from langflow.adlc.harness_client import HarnessClient, HarnessClientError, HarnessHttpClient, HarnessServerSettings
from langflow.adlc.harness_dsh_client import (
    DshHarnessClient,
    dsh_goal_idle_grace_seconds_from_environment,
    dsh_idle_grace_seconds_from_environment,
)
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.harness_models import (
    HarnessPluginInventory,
    HarnessReconciliationReport,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    TaskAttemptStatus,
)
from langflow.adlc.plan_orchestrator import PlanOrchestratingExecutor

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.adapter_interfaces import TaskExecutor

HARNESS_ENABLED_ENV = "ADLC_HARNESS_ENABLED"
HARNESS_TRANSPORT_ENV = "ADLC_HARNESS_TRANSPORT"
HARNESS_TRANSPORT_REST = "rest"
HARNESS_TRANSPORT_DSH = "dsh"
HARNESS_PLAN_ORCHESTRATION_ENV = "ADLC_HARNESS_PLAN_ORCHESTRATION"
HARNESS_MAX_PARALLEL_SUBTASKS_ENV = "ADLC_HARNESS_MAX_PARALLEL_SUBTASKS"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class HarnessRuntimeSettings:
    enabled: bool
    server: HarnessServerSettings
    transport: str = HARNESS_TRANSPORT_REST

    @classmethod
    def from_environment(cls) -> HarnessRuntimeSettings:
        transport = os.getenv(HARNESS_TRANSPORT_ENV, HARNESS_TRANSPORT_REST).strip().lower()
        if transport not in {HARNESS_TRANSPORT_REST, HARNESS_TRANSPORT_DSH}:
            transport = HARNESS_TRANSPORT_REST
        return cls(
            enabled=harness_execution_enabled(),
            server=HarnessServerSettings.from_environment(),
            transport=transport,
        )


class HarnessRuntimeReadiness(BaseModel):
    enabled: bool
    ready: bool
    service: str = DeepSeekHarnessTaskExecutor.service_name
    package: str = "coding-agent-deepseek-harness@0.3.2"
    server_ready: bool
    callback_ready: bool
    attempt_store_ready: bool
    plugin_lock_ready: bool = False
    plugin_inventory: HarnessPluginInventory | None = None
    server_version: str | None = None
    error_code: str | None = None


def harness_execution_enabled() -> bool:
    return os.getenv(HARNESS_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def harness_plan_orchestration_enabled() -> bool:
    """Whether to wrap the harness executor with plan orchestration.

    When enabled (default), each task first runs a planner session that
    produces a structured :class:`PlanSpec`, then dispatches the
    subtasks in parallel. When disabled, tasks run as a single DSH
    session (legacy behaviour).
    """
    raw = os.getenv(HARNESS_PLAN_ORCHESTRATION_ENV, "true").strip().lower()
    if raw == "":
        return True
    return raw in _TRUE_VALUES


def harness_max_parallel_subtasks_from_environment() -> int:
    """Read the max-parallel-subtasks setting from the environment."""
    raw = os.getenv(HARNESS_MAX_PARALLEL_SUBTASKS_ENV, "5").strip()
    try:
        value = int(raw)
    except ValueError:
        return 5
    return max(1, value)


HARNESS_PLAN_SOURCE_ENV = "ADLC_PLAN_SOURCE"


def plan_orchestration_mode() -> str:
    """Which plan source the orchestrating executor uses.

    ``template`` (default) expands tasks into fixed subtask DAGs by task
    type without spending a planner session; ``llm`` asks a DSH planner
    session to produce the plan.
    """
    raw = os.getenv(HARNESS_PLAN_SOURCE_ENV, "template").strip().lower()
    return raw if raw in {"template", "llm"} else "template"


def create_harness_client(
    settings: HarnessRuntimeSettings,
    *,
    artifact_payloads: BoundedArtifactPayloadStore | None = None,
) -> HarnessClient:
    """Build the configured Harness transport; raises ValueError when invalid."""
    if settings.transport == HARNESS_TRANSPORT_DSH:
        return DshHarnessClient(
            settings.server,
            idle_grace_seconds=dsh_idle_grace_seconds_from_environment(),
            goal_idle_grace_seconds=dsh_goal_idle_grace_seconds_from_environment(),
            artifact_payloads=artifact_payloads,
        )
    return HarnessHttpClient(settings.server)


def create_harness_task_executor(
    callbacks: HarnessCallbackReceiver,
    settings: HarnessRuntimeSettings | None = None,
    *,
    client: HarnessClient | None = None,
    artifact_payloads: BoundedArtifactPayloadStore | None = None,
) -> TaskExecutor | None:
    """Create the remote executor only when deployment activation is complete.

    When :func:`harness_plan_orchestration_enabled` returns ``True``
    (the default), the returned executor is a
    :class:`PlanOrchestratingExecutor` that wraps a
    :class:`DeepSeekHarnessTaskExecutor` and adds plan-based parallel
    execution. Set ``ADLC_HARNESS_PLAN_ORCHESTRATION=false`` to fall
    back to the legacy single-session behaviour.
    """
    runtime = settings or HarnessRuntimeSettings.from_environment()
    if not runtime.enabled or not callbacks.ready or not callbacks.durable or not runtime.server.api_token:
        return None
    try:
        configured_client = client or create_harness_client(runtime, artifact_payloads=artifact_payloads)
    except ValueError:
        return None
    base_executor = DeepSeekHarnessTaskExecutor(configured_client, callbacks)
    if not harness_plan_orchestration_enabled():
        return base_executor
    return PlanOrchestratingExecutor(
        base_executor,
        max_parallel_subtasks=harness_max_parallel_subtasks_from_environment(),
        planning_mode=plan_orchestration_mode(),
    )


async def check_harness_readiness(
    settings: HarnessRuntimeSettings | None = None,
    *,
    callbacks: HarnessCallbackReceiver | None = None,
    client: HarnessClient | None = None,
) -> HarnessRuntimeReadiness:
    runtime = settings or HarnessRuntimeSettings.from_environment()
    receiver = callbacks or HarnessCallbackReceiver()
    if not runtime.enabled:
        return HarnessRuntimeReadiness(
            enabled=False,
            ready=False,
            server_ready=False,
            callback_ready=receiver.ready,
            attempt_store_ready=receiver.durable,
            error_code="HARNESS_EXECUTION_DISABLED",
        )

    if not receiver.ready:
        return HarnessRuntimeReadiness(
            enabled=True,
            ready=False,
            server_ready=False,
            callback_ready=False,
            attempt_store_ready=receiver.durable,
            error_code="HARNESS_CALLBACK_NOT_CONFIGURED",
        )

    if not receiver.durable:
        return HarnessRuntimeReadiness(
            enabled=True,
            ready=False,
            server_ready=False,
            callback_ready=True,
            attempt_store_ready=False,
            error_code="HARNESS_ATTEMPT_STORE_NOT_CONFIGURED",
        )

    if not runtime.server.api_token:
        return HarnessRuntimeReadiness(
            enabled=True,
            ready=False,
            server_ready=False,
            callback_ready=True,
            attempt_store_ready=True,
            error_code="HARNESS_API_TOKEN_NOT_CONFIGURED",
        )

    owned_client: HarnessClient | None = None
    try:
        if client is None:
            owned_client = create_harness_client(runtime)
        configured_client = client or owned_client
        health = await configured_client.health()
    except ValueError:
        return HarnessRuntimeReadiness(
            enabled=True,
            ready=False,
            server_ready=False,
            callback_ready=True,
            attempt_store_ready=True,
            error_code="HARNESS_SERVER_CONFIGURATION_INVALID",
        )
    except HarnessClientError as exc:
        return HarnessRuntimeReadiness(
            enabled=True,
            ready=False,
            server_ready=False,
            callback_ready=True,
            attempt_store_ready=True,
            error_code=exc.code,
        )
    finally:
        if owned_client is not None:
            await owned_client.close()

    raw_inventory = health.get("plugin_integrity")
    try:
        plugin_inventory = HarnessPluginInventory.model_validate(raw_inventory)
    except ValidationError:
        plugin_inventory = None
    plugin_lock_ready = (
        health.get("plugin_lock_ready") is True and plugin_inventory is not None and plugin_inventory.ready
    )
    server_ready = health.get("ready") is True
    version = health.get("version") if isinstance(health.get("version"), str) else None
    return HarnessRuntimeReadiness(
        enabled=True,
        ready=server_ready and plugin_lock_ready,
        server_ready=server_ready,
        callback_ready=True,
        attempt_store_ready=True,
        plugin_lock_ready=plugin_lock_ready,
        plugin_inventory=plugin_inventory,
        server_version=version,
        error_code=(
            None
            if server_ready and plugin_lock_ready
            else plugin_inventory.error_code
            if plugin_inventory is not None and not plugin_inventory.ready
            else "HARNESS_PLUGIN_INTEGRITY_UNAVAILABLE"
            if server_ready
            else "HARNESS_SERVER_NOT_READY"
        ),
    )


async def reconcile_harness_attempts(
    callbacks: HarnessCallbackReceiver,
    client: HarnessClient,
    *,
    limit: int = 100,
    workflow_run_id: UUID | None = None,
) -> HarnessReconciliationReport:
    """Recover unfinished attempts from authoritative Harness session projections."""
    if workflow_run_id is None:
        attempts = await callbacks.attempts.list_unfinished(limit=limit)
    else:
        attempts = [
            attempt
            for attempt in await callbacks.attempts.list_for_workflow_run(workflow_run_id)
            if attempt.status
            not in {TaskAttemptStatus.SUCCEEDED, TaskAttemptStatus.FAILED, TaskAttemptStatus.CANCELLED}
        ][:limit]
    recovered_results = 0
    submitted_sessions = 0
    unavailable_sessions = 0
    status_map = {
        HarnessSessionStatus.ACCEPTED: TaskAttemptStatus.DISPATCHED,
        HarnessSessionStatus.PROVISIONING: TaskAttemptStatus.RUNNING,
        HarnessSessionStatus.RUNNING: TaskAttemptStatus.RUNNING,
        HarnessSessionStatus.WAITING_INTERACTION: TaskAttemptStatus.WAITING_INTERACTION,
        HarnessSessionStatus.VERIFYING: TaskAttemptStatus.VERIFYING,
        HarnessSessionStatus.READY_FOR_SUBMISSION: TaskAttemptStatus.READY_TO_SUBMIT,
    }
    for attempt in attempts:
        if attempt.external_session_id is None:
            unavailable_sessions += 1
            continue
        try:
            session = await client.get_session(attempt.external_session_id)
        except HarnessClientError:
            unavailable_sessions += 1
            continue
        if session.result is not None and session.status in {
            HarnessSessionStatus.SUCCEEDED,
            HarnessSessionStatus.FAILED,
            HarnessSessionStatus.CANCELLED,
        }:
            try:
                await callbacks.accept_reconciled_result(session.result)
                recovered_results += 1
            except (HarnessAttemptError, HarnessCallbackError):
                unavailable_sessions += 1
            continue
        desired = status_map.get(session.status)
        if desired is not None and desired is not attempt.status:
            try:
                current = attempt
                if current.status is TaskAttemptStatus.CREATED:
                    current = await callbacks.attempts.update_status(
                        current.attempt_id,
                        TaskAttemptStatus.DISPATCHED,
                    )
                if current.status is TaskAttemptStatus.DISPATCHED and desired not in {
                    TaskAttemptStatus.DISPATCHED,
                    TaskAttemptStatus.RESULT_RECEIVED,
                }:
                    current = await callbacks.attempts.update_status(
                        current.attempt_id,
                        TaskAttemptStatus.RUNNING,
                    )
                if current.status is TaskAttemptStatus.WAITING_INTERACTION and desired in {
                    TaskAttemptStatus.VERIFYING,
                    TaskAttemptStatus.READY_TO_SUBMIT,
                }:
                    current = await callbacks.attempts.update_status(
                        current.attempt_id,
                        TaskAttemptStatus.RUNNING,
                    )
                if current.status is not desired:
                    await callbacks.attempts.update_status(current.attempt_id, desired)
            except HarnessAttemptError:
                unavailable_sessions += 1
        if (
            session.status is HarnessSessionStatus.READY_FOR_SUBMISSION
            and session.submission_mode is HarnessSubmissionMode.AUTO
        ):
            try:
                await client.submit_session(session.session_id)
                submitted_sessions += 1
            except HarnessClientError:
                unavailable_sessions += 1
    return HarnessReconciliationReport(
        inspected=len(attempts),
        recovered_results=recovered_results,
        submitted_sessions=submitted_sessions,
        unavailable_sessions=unavailable_sessions,
    )


__all__ = [
    "HARNESS_ENABLED_ENV",
    "HARNESS_MAX_PARALLEL_SUBTASKS_ENV",
    "HARNESS_PLAN_ORCHESTRATION_ENV",
    "HARNESS_PLAN_SOURCE_ENV",
    "HARNESS_TRANSPORT_DSH",
    "HARNESS_TRANSPORT_ENV",
    "HARNESS_TRANSPORT_REST",
    "HarnessRuntimeReadiness",
    "HarnessRuntimeSettings",
    "check_harness_readiness",
    "create_harness_client",
    "create_harness_task_executor",
    "harness_execution_enabled",
    "harness_max_parallel_subtasks_from_environment",
    "harness_plan_orchestration_enabled",
    "plan_orchestration_mode",
    "reconcile_harness_attempts",
]

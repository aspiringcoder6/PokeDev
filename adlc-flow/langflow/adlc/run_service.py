"""In-memory coordinator for ADLC runs created from legacy graphs or accepted plans."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import ValidationError

from langflow.adlc.artifact_payload_store import (
    ArtifactPayloadUnavailableError,
    BoundedArtifactPayloadStore,
    SourcePatchRead,
    SourcePatchSnapshot,
)
from langflow.adlc.coding_agent import CONTRACT_LOOP_SERVICE
from langflow.adlc.executor_router import TaskExecutorRecoveryError
from langflow.adlc.evidence_plane import (
    Evidence,
    EvidencePlaneService,
    EvidenceQuery,
    EvidenceType,
    get_default_evidence_plane,
)
from langflow.adlc.expressions import TemplateResolutionError, resolve_templates
from langflow.adlc.harness_attempts import HarnessAttemptError
from langflow.adlc.harness_executor import harness_result_to_task_result
from langflow.adlc.harness_models import HarnessCorrelation
from langflow.adlc.harness_workflow import SERVICE as HARNESS_WORKFLOW_SERVICE
from langflow.adlc.harness_workflow import DemoError
from langflow.adlc.harness_workflow import digest as harness_digest
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.mock_workflow import TASK_TRANSITIONS, WORKFLOW_TRANSITIONS
from langflow.adlc.quality_gate import (
    QualityGateDecision,
    TaskCriterion,
    TaskQualityVerdict,
    evaluate_task_quality,
)
from langflow.adlc.quality_gate_policy import QualityGateRunPolicy, load_quality_gate_policy
from langflow.adlc.run_reflection import dispatch_run_reflection, reflection_metadata
from langflow.adlc.models import (
    Actor,
    AdlcDeadLetter,
    AdlcRunSummary,
    AdlcTaskDefinition,
    ApprovalAction,
    ApprovalContext,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalStatus,
    Artifact,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    GateType,
    RunEvent,
    RunRecoveryReport,
    ServiceError,
    TaskMetrics,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    TaskRun,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunListResponse,
    WorkflowRunStatus,
    WorkflowRunSummary,
)
from langflow.adlc.notifications import (
    NOOP_ADLC_NOTIFICATION_SINK,
    AdlcNotification,
    AdlcNotificationKind,
    AdlcNotificationSink,
)
from langflow.adlc.observability import (
    NOOP_ADLC_OBSERVABILITY_SINK,
    AdlcObservabilitySink,
    AdlcObservationOutcome,
    AdlcObservationType,
    elapsed_milliseconds,
    observation_error_code,
    observation_outcome_for_exception,
    record_observation_safely,
)
from langflow.adlc.run_repository import RunRepository, RunRepositoryError, StoredAdlcRun
from langflow.adlc.task_loop import TASK_LOOP_MOCK_SERVICE
from langflow.adlc.task_loop_harness import HARNESS_CONTRACT_LOOP_SERVICE, HARNESS_LOOP_SERVICE
from langflow.adlc.task_loop_inspection import (
    LoopIterationView,
    RunOperatorControls,
    TaskLoopInspection,
    empty_inspection,
    failure_patterns,
    inspect_live_loop,
    result_reason,
)
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE
from langflow.adlc.task_loop_store import TaskLoopStore
from langflow.adlc.task_loop_workspace import LiveLoopError
from lfx.log.logger import logger

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import TaskExecutor
    from langflow.adlc.harness_callbacks import HarnessCallbackReceiver


class _RunRepositoryPersistence:
    """Adapt the RunRepository snapshot port to the coordinator persistence protocol."""

    def __init__(self, repository: RunRepository) -> None:
        self._repository = repository
        self._records: dict[UUID, StoredAdlcRun] = {}

    @property
    def is_durable(self) -> bool:
        return self._repository.is_durable

    async def save(self, *, owner_id: str, run: WorkflowRun, definitions: dict[str, AdlcTaskDefinition]) -> None:
        snapshot = self._records.get(run.id)
        if snapshot is None:
            snapshot = StoredAdlcRun(owner_id=owner_id, run=run, definitions=definitions, delay_ms=0)
        else:
            snapshot.run = run
            snapshot.definitions = definitions
        self._repository.save(snapshot)
        self._records[run.id] = snapshot

    async def load(self, *, owner_id: str | None = None) -> list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]]:
        records = self._repository.load_all()
        self._records.update({record.run.id: record for record in records})
        return [
            (record.owner_id, record.run, list(record.definitions.values()))
            for record in records
            if owner_id is None or record.owner_id == owner_id
        ]

    async def load_inspection(self, *, owner_id: str) -> list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]]:
        """Do not refresh a live coordinator's revision cache while serving detached reads."""
        return [
            (record.owner_id, record.run, list(record.definitions.values()))
            for record in self._repository.load_all()
            if record.owner_id == owner_id
        ]

    async def clear(self) -> None:
        msg = "RunRepository snapshots are append-only durable state."
        raise NotImplementedError(msg)


EXECUTION_MODE_MISMATCH = "EXECUTION_MODE_MISMATCH"
_MOCK_EXECUTOR_SERVICES = frozenset({MockExecutor.service_name, "agent-provider:mock"})
_ASYNC_EXECUTOR_SERVICES = frozenset({"agent-provider:deepseek-harness"})
_DURABLE_LOOP_SERVICES = {
    TASK_LOOP_LIVE_SERVICE,
    CONTRACT_LOOP_SERVICE,
    HARNESS_LOOP_SERVICE,
    HARNESS_CONTRACT_LOOP_SERVICE,
}
_CONTRACT_LOOP_SERVICES = {CONTRACT_LOOP_SERVICE, HARNESS_CONTRACT_LOOP_SERVICE}
_LOOP_SERVICES = _DURABLE_LOOP_SERVICES | {TASK_LOOP_MOCK_SERVICE}
_BACKGROUND_EXECUTOR_SERVICES = _ASYNC_EXECUTOR_SERVICES | _DURABLE_LOOP_SERVICES | {HARNESS_WORKFLOW_SERVICE}
MAX_RUN_HISTORY_LIMIT = 100
_CONTRACT_PLUGIN_DIGEST_LENGTH = len("sha256:") + 64
EVENT_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
RUNTIME_EVENT_EMITTED = "workflow_run.event_emitted"

_TERMINAL_WORKFLOW_STATUSES = frozenset(
    {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
)
_TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskRunStatus.SUCCEEDED,
        TaskRunStatus.FAILED,
        TaskRunStatus.CANCELLED,
        TaskRunStatus.SKIPPED,
    }
)
_CANCELLABLE_TASK_STATUSES = frozenset(
    {
        TaskRunStatus.PENDING,
        TaskRunStatus.READY,
        TaskRunStatus.RUNNING,
        TaskRunStatus.WAITING_APPROVAL,
    }
)
_PAUSE_REASON_USER = "user_pause"
_PAUSE_REASON_RETRY = "retry_available"
_PAUSE_REASON_EVENTS = "waiting_for_events"
_PAUSE_REASON_APPROVAL_EXPIRED = "approval_expired"
_DEFAULT_MAX_ATTEMPTS = 2
_MAX_RETRY_BACKOFF_MS = 30_000
_IN_PROCESS_WORKER_ID = f"adlc-inprocess-{os.getpid()}"
_APPROVAL_EXPIRED_ERROR_CODE = "APPROVAL_EXPIRED"

WORKFLOW_EVENT_TYPES = {
    WorkflowRunStatus.CREATED: "workflow_run.created",
    WorkflowRunStatus.QUEUED: "workflow_run.queued",
    WorkflowRunStatus.RUNNING: "workflow_run.started",
    WorkflowRunStatus.PAUSED: "workflow_run.paused",
    WorkflowRunStatus.WAITING_APPROVAL: "workflow_run.waiting_approval",
    WorkflowRunStatus.SUCCEEDED: "workflow_run.succeeded",
    WorkflowRunStatus.FAILED: "workflow_run.failed",
    WorkflowRunStatus.CANCELLED: "workflow_run.cancelled",
}

TASK_EVENT_TYPES = {
    TaskRunStatus.PENDING: "task_run.created",
    TaskRunStatus.READY: "task_run.ready",
    TaskRunStatus.RUNNING: "task_run.started",
    TaskRunStatus.WAITING_APPROVAL: "task_run.waiting_approval",
    TaskRunStatus.SUCCEEDED: "task_run.succeeded",
    TaskRunStatus.FAILED: "task_run.failed",
    TaskRunStatus.CANCELLED: "task_run.cancelled",
    TaskRunStatus.SKIPPED: "task_run.skipped",
}

SYSTEM_ACTOR = Actor(type="SYSTEM", id="adlc-run-coordinator", display_name="ADLC Run Coordinator")


class AdlcRunNotFoundError(LookupError):
    """The run-scoped resource is absent or belongs to another user."""


class AdlcRunStateError(RuntimeError):
    """The requested command is invalid for the aggregate's current state."""


class AdlcArtifactUnavailableError(LookupError):
    """A run still references a source patch whose temporary bytes are unavailable."""


@runtime_checkable
class AdlcRunPersistence(Protocol):
    """Optional durable snapshot sink for the in-memory run coordinator."""

    async def save(self, *, owner_id: str, run: WorkflowRun, definitions: dict[str, AdlcTaskDefinition]) -> None:
        """Persist one run snapshot together with its runtime definitions."""

    async def load(self, *, owner_id: str | None = None) -> list[tuple[str, WorkflowRun, list[AdlcTaskDefinition]]]:
        """Return persisted snapshots oldest first, scoped to one owner."""

    async def clear(self) -> None:
        """Remove all persisted snapshots."""


@dataclass
class _StoredRun:
    owner_id: str
    run: WorkflowRun
    definitions: dict[str, AdlcTaskDefinition]
    delay_ms: int
    max_concurrency: int | None = None
    emitted_events: set[str] = field(default_factory=set)
    in_flight: dict[asyncio.Task[None], TaskRun] = field(default_factory=dict)
    cancel_requested: bool = False
    pause_requested: bool = False
    pause_reason: str | None = None
    retry_ready_at: dict[UUID, datetime] = field(default_factory=dict)
    scheduler_task: asyncio.Task[None] | None = None
    subtask_cache: dict[tuple[UUID, UUID], "TaskSubtasksResponse"] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _submit_evidence_safely(plane: EvidencePlaneService | None, evidence: Evidence) -> None:
    """Submit evidence inside a failure-isolated boundary.

    The Evidence Plane is an observability mirror: a submission failure must
    never alter the run being observed.
    """
    if plane is None:
        return
    try:
        plane.submit_evidence(evidence)
    except Exception:  # noqa: BLE001 - evidence mirroring must not break runs
        logger.warning(
            "Failed to mirror ADLC evidence %s into the evidence plane.",
            evidence.evidence_id,
            exc_info=True,
        )


def _loop_checkpoint_store() -> TaskLoopStore:
    root = Path(os.getenv("ADLC_TASK_LOOP_STATE_ROOT", str(Path(__file__).resolve().parents[2] / "data/task-loop")))
    return TaskLoopStore(root / "task-loop.sqlite3", initialize=False)


def _actor_payload(actor: Actor | None) -> dict:
    if actor is None or not actor.id:
        return {}
    return {"actor_id": actor.id, "actor_type": actor.type}


def _run_summary(run: WorkflowRun) -> AdlcRunSummary:
    """Project a run snapshot into its history-listing summary."""
    return AdlcRunSummary(
        id=run.id,
        workflow_key=run.workflow_key,
        name=run.name,
        status=run.status,
        execution_mode=run.execution_mode,
        flow_id=run.flow_id,
        execution_plan_id=run.execution_plan_id,
        run_number=run.run_number,
        created_at=run.created_at,
        completed_at=run.completed_at,
        task_total=len(run.tasks),
        task_succeeded=sum(1 for task in run.tasks if task.status is TaskRunStatus.SUCCEEDED),
        task_failed=sum(1 for task in run.tasks if task.status is TaskRunStatus.FAILED),
        pending_approval=any(approval.status is ApprovalStatus.PENDING for approval in run.approval_requests),
    )


class AdlcRunService:
    """Execute mock tasks and keep run projections in process memory."""

    def __init__(
        self,
        executor: TaskExecutor | None = None,
        *,
        artifact_payloads: BoundedArtifactPayloadStore | None = None,
        observability_sink: AdlcObservabilitySink | None = None,
        persistence: AdlcRunPersistence | None = None,
        notification_sink: AdlcNotificationSink | None = None,
        repository: RunRepository | None = None,
        harness_callbacks: HarnessCallbackReceiver | None = None,
        evidence_plane: EvidencePlaneService | None = None,
        project_scope_loader=None,
        quality_gate_policy: QualityGateRunPolicy | None = None,
        reflection_dispatcher=None,
    ) -> None:
        self._executor = executor or MockExecutor()
        self._runs: dict[UUID, _StoredRun] = {}
        self._artifact_payloads = artifact_payloads if artifact_payloads is not None else BoundedArtifactPayloadStore()
        self._mutation_lock = asyncio.Lock()
        self._observability = observability_sink if observability_sink is not None else NOOP_ADLC_OBSERVABILITY_SINK
        self._notifications = notification_sink if notification_sink is not None else NOOP_ADLC_NOTIFICATION_SINK
        self._evidence_plane = evidence_plane if evidence_plane is not None else get_default_evidence_plane()
        self._quality_gate_policy = quality_gate_policy if quality_gate_policy is not None else load_quality_gate_policy()
        self._reflection_dispatcher = (
            reflection_dispatcher if reflection_dispatcher is not None else dispatch_run_reflection
        )
        self._background_runs: set[asyncio.Task[None]] = set()
        self._persistence = _RunRepositoryPersistence(repository) if repository is not None else persistence
        self._harness_callbacks = harness_callbacks
        self._project_scope_loader = project_scope_loader
        self._project_bound_run_ids: set[UUID] = set()
        self._hydration_lock = asyncio.Lock()
        self._hydrated_owners: set[str] = set()
        self._recovery_done = False
        self._recovery_report = RunRecoveryReport()
        self._closing = False
        self._sweeper_task: asyncio.Task[None] | None = None
        bind = getattr(self._executor, "bind_workflow_authority", None)
        if callable(bind):
            bind(self.authorize_harness_workflow)
        bind_plugins = getattr(self._executor, "bind_plugin_workflow_authority", None)
        if callable(bind_plugins):
            bind_plugins(self.authorize_plugin_workflow)

    def authorize_plugin_workflow(self, request: TaskRequest) -> dict:
        """Derive plugin scope only from the current compiler-bound owned attempt."""
        from langflow.adlc.workflow_plugin_client import PluginError

        record = self._runs.get(request.workflow_run_id)
        task = next((item for item in record.run.tasks if item.id == request.task_run_id), None) if record else None
        if (
            not record or not task or record.run.execution_mode is not WorkflowExecutionMode.EXECUTION_PLAN
            or record.run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.QUEUED}
            or record.cancel_requested or task.request is None or task.plan_traceability is None
            or task.current_attempt_id != request.attempt_id
            or harness_digest(task.request.model_dump(mode="json")) != harness_digest(request.model_dump(mode="json"))
        ):
            raise PluginError("WORKFLOW_PLUGIN_REQUEST_NOT_OWNED", 403)
        return {"owner_id": record.owner_id, "flow_id": str(record.run.flow_id)}

    def authorize_harness_workflow(self, request: TaskRequest) -> dict:
        record = self._runs.get(request.workflow_run_id)
        task = next((t for t in record.run.tasks if t.id == request.task_run_id), None) if record else None
        if (
            not record
            or not task
            or record.run.execution_mode is not WorkflowExecutionMode.EXECUTION_PLAN
            or record.run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.QUEUED}
            or record.cancel_requested
            or task.request is None
            or task.plan_traceability is None
            or harness_digest(task.request.model_dump(mode="json")) != harness_digest(request.model_dump(mode="json"))
        ):
            code = "HARNESS_WORKFLOW_REQUEST_NOT_OWNED"
            raise DemoError(code)
        result = {"owner_id": record.owner_id}
        if request.executor.operation == "PLAN":
            return result
        reviews = []
        for dependency_id in task.dependency_task_run_ids:
            dependency = self._task_by_id(record.run, dependency_id)
            if dependency.executor.service != "control:approval" or dependency.status is not TaskRunStatus.SUCCEEDED:
                continue
            for approval in record.run.approval_requests:
                if (
                    approval.task_run_id == dependency_id
                    and approval.status is ApprovalStatus.APPROVED
                    and approval.decision
                    and approval.decision.effect == "APPROVE"
                    and approval.decision.decided_by.type == "USER"
                    and approval.decision.decided_by.id == record.owner_id
                ):
                    review = approval.context.payload.get("harness_workflow_review")
                    source_id = approval.context.payload.get("harness_source_task_id")
                    source = next((t for t in record.run.tasks if str(t.id) == source_id), None)
                    if (
                        review
                        and source
                        and source.id in dependency.dependency_task_run_ids
                        and source.executor.service == HARNESS_WORKFLOW_SERVICE
                        and source.result
                        and source.result.status is TaskResultStatus.SUCCEEDED
                        and source.result.output["outputs"].get("review") == review
                        and harness_digest(review) == approval.context.payload.get("harness_workflow_digest")
                    ):
                        reviews.append({"review": review, "approval_request_id": str(approval.approval_request_id)})
        if len(reviews) != 1:
            code = "HARNESS_WORKFLOW_EXACT_REVIEW_REQUIRED"
            raise DemoError(code)
        return {**result, **reviews[0]}

    async def start_run(
        self,
        *,
        flow_id: UUID,
        flow_name: str,
        definitions: list[AdlcTaskDefinition],
        request: CreateWorkflowRunRequest,
        owner_id: str,
        execution_plan_id: UUID | None = None,
        workflow_key: str | None = None,
    ) -> WorkflowRun:
        async with self._mutation_lock:
            await self._ensure_hydrated(owner_id)
            record = self._create_run(
                flow_id=flow_id,
                flow_name=flow_name,
                definitions=definitions,
                request=request,
                owner_id=owner_id,
                execution_plan_id=execution_plan_id,
                workflow_key=workflow_key,
            )
            self._runs[record.run.id] = record
            self._transition_workflow(record.run, WorkflowRunStatus.QUEUED)
            self._transition_workflow(record.run, WorkflowRunStatus.RUNNING)
            if any(task.executor.service in _BACKGROUND_EXECUTOR_SERVICES for task in record.run.tasks):
                await self._persist_safely(record, required=True)
                self._start_background(record)
                return record.run.model_copy(deep=True)
            await self._schedule(record)
            await self._persist_safely(record)
            return record.run.model_copy(deep=True)

    async def get_run(self, run_id: UUID, *, owner_id: str) -> WorkflowRun:
        await self._ensure_hydrated(owner_id)
        record = self._owned_run(run_id, owner_id)
        return record.run.model_copy(deep=True)

    async def get_run_for_approval(self, approval_id: UUID, *, owner_id: str) -> WorkflowRun:
        await self._ensure_hydrated(owner_id)
        record, _ = self._owned_approval(approval_id, owner_id)
        return record.run.model_copy(deep=True)

    async def get_tasks(self, run_id: UUID, *, owner_id: str) -> list[TaskRun]:
        await self._ensure_hydrated(owner_id)
        record = self._owned_run(run_id, owner_id)
        return [task.model_copy(deep=True) for task in record.run.tasks]

    async def get_task_subtasks(
        self,
        run_id: UUID,
        task: TaskRun,
        *,
        owner_id: str,
    ) -> "TaskSubtasksResponse":
        """Return subtasks for a task, generated on-demand by DSH.

        The system SDKs to DSH and asks "how would you divide this task
        into parallel subtasks?". The response is cached so subsequent
        calls return the same subtasks.
        """
        from langflow.adlc.task_subtasks import (
            SubtaskRun,
            SubtaskSummary,
            TaskSubtasksResponse,
        )

        await self._ensure_hydrated(owner_id)
        record = self._owned_run(run_id, owner_id)

        # Live plan-orchestration progress (real subtask DSH sessions) wins
        # over the static template projection.
        from langflow.adlc.subtask_registry import get_subtask_registry

        live = get_subtask_registry().snapshot(run_id, task.id)
        if live is not None:
            return live

        # Check the run-level cache first.
        cache_key = (run_id, task.id)
        if cache_key in record.subtask_cache:
            return record.subtask_cache[cache_key]

        # Check the plan-level cache (pre-generated during plan approval).
        # This is the fast path that avoids re-generating subtasks when
        # the user opens a task that was already prepared.
        from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

        plan_cache = get_plan_subtask_cache()
        plan_response = plan_cache.get_subtasks(run_id, task.id)
        if plan_response is not None:
            record.subtask_cache[cache_key] = plan_response
            return plan_response

        # Generate subtasks via DSH SDK (default) or mock templates (fallback).
        subtasks, is_mock = await self._generate_subtasks_for_task(task, record.run)

        # Compute summary.
        summary = SubtaskSummary(
            total=len(subtasks),
            succeeded=sum(1 for s in subtasks if s.status == "succeeded"),
            failed=sum(1 for s in subtasks if s.status == "failed"),
            running=sum(1 for s in subtasks if s.status == "running"),
            pending=sum(
                1 for s in subtasks if s.status in ("pending", "ready")
            ),
            skipped=sum(1 for s in subtasks if s.status == "skipped"),
        )

        response = TaskSubtasksResponse(
            task_run_id=task.id,
            subtasks=subtasks,
            summary=summary,
            is_mock=is_mock,
            note=(
                "Mock subtasks generated from node-type template (DSH SDK unavailable)."
                if is_mock
                else None
            ),
        )

        # Cache the response.
        record.subtask_cache[cache_key] = response
        return response

    async def prepare_plan_subtasks(
        self,
        plan_id: UUID,
        tasks: list[TaskRun],
        *,
        owner_id: str,
    ) -> dict[str, Any]:
        """Pre-generate subtasks for every task in an approved plan.

        Called immediately after plan approval so the Run button can be
        enabled only when all subtasks are ready. The generated subtasks
        are stored in the plan-level cache and copied into the subtask
        registry when the run is created.

        This method returns IMMEDIATELY with status ``pending``. The
        actual generation runs in a background asyncio task so the
        HTTP request never blocks on DSH. Callers poll
        :meth:`get_plan_subtask_status` to track progress.

        Returns a status dict with ``status`` (``pending``/``ready``/
        ``failed``), ``total_tasks``, ``prepared_tasks``, and ``error``.
        """
        from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

        cache = get_plan_subtask_cache()
        # If a background task is already running for this plan AND
        # entries have been pre-registered, return the current status
        # instead of starting a duplicate. We check for entries (not
        # just status) because the default status after ``forget()`` is
        # also ``pending``.
        existing = cache.get_all_subtasks(plan_id)
        if existing and cache.get_status(plan_id)["status"] == "pending":
            return self.get_plan_subtask_status(plan_id)

        cache.set_status(plan_id, status="pending")
        # Pre-register empty entries for every task so the progress
        # bar shows the right denominator from the first poll.
        from langflow.adlc.task_subtasks import (
            SubtaskRun,
            SubtaskSummary,
            TaskSubtasksResponse,
        )

        for task in tasks:
            empty_response = TaskSubtasksResponse(
                task_run_id=task.id,
                subtasks=[],
                summary=SubtaskSummary(),
                is_mock=False,
            )
            cache.store_subtasks(plan_id, task.id, empty_response)

        # Spawn the actual generation in the background so the HTTP
        # request returns immediately. The background task updates the
        # cache as each subtask is generated.
        background_tasks: set[asyncio.Task[None]] = getattr(
            self, "_subtask_prep_tasks", set()
        )
        self._subtask_prep_tasks = background_tasks
        task = asyncio.create_task(
            self._prepare_plan_subtasks_background(plan_id, tasks, owner_id=owner_id)
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

        return self.get_plan_subtask_status(plan_id)

    async def _prepare_plan_subtasks_background(
        self,
        plan_id: UUID,
        tasks: list[TaskRun],
        *,
        owner_id: str,
    ) -> None:
        """Background worker that generates subtasks for every task.

        Updates the plan-level cache as each task completes so the
        frontend can show real-time progress.

        Tasks are processed in PARALLEL (bounded by a semaphore) so the
        total wall-clock time is roughly the slowest single task rather
        than the sum of all tasks. Each task still uses its own DSH
        session — the semaphore just prevents us from spawning dozens
        of concurrent DSH sessions at once.
        """
        from langflow.adlc.plan_subtask_cache import (
            get_plan_subtask_cache,
            summarize_subtasks,
        )
        from langflow.adlc.task_subtasks import TaskSubtasksResponse

        cache = get_plan_subtask_cache()
        total = len(tasks)

        # Bound concurrency so we don't overwhelm DSH. Default 5 matches
        # the max-parallel-subtasks setting used by the executor.
        max_concurrency = int(
            os.getenv("ADLC_SUBTASK_PREP_CONCURRENCY", "5")
        )
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _generate_one(task: TaskRun) -> tuple[TaskRun, str | None]:
            """Generate subtasks for one task under the semaphore."""
            async with semaphore:
                try:
                    subtasks, is_mock = await self._generate_subtasks_for_task(
                        task, None  # type: ignore[arg-type]
                    )
                    summary = summarize_subtasks(subtasks)
                    response = TaskSubtasksResponse(
                        task_run_id=task.id,
                        subtasks=subtasks,
                        summary=summary,
                        is_mock=is_mock,
                        note=(
                            "Mock subtasks generated from node-type template (DSH SDK unavailable)."
                            if is_mock
                            else None
                        ),
                    )
                    cache.store_subtasks(plan_id, task.id, response)
                    logger.info(
                        "Pre-generated subtasks for task %s in plan %s",
                        task.id,
                        plan_id,
                    )
                    return task, None
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Failed to pre-generate subtasks for task %s in plan %s: %s",
                        task.id,
                        plan_id,
                        exc,
                    )
                    return task, f"{task.name or task.id}: {exc}"

        # Fire all tasks in parallel; gather collects results.
        results = await asyncio.gather(
            *[_generate_one(task) for task in tasks],
            return_exceptions=False,
        )

        prepared = sum(1 for _, err in results if err is None)
        errors = [err for _, err in results if err is not None]

        if errors and prepared == 0:
            cache.set_status(
                plan_id,
                status="failed",
                error="; ".join(errors),
            )
        else:
            cache.set_status(plan_id, status="ready")
        logger.info(
            "Subtask preparation for plan %s finished: %d/%d ready, %d errors",
            plan_id,
            prepared,
            total,
            len(errors),
        )

    async def prepare_plan_subtasks_sync(
        self,
        plan_id: UUID,
        tasks: list[TaskRun],
        *,
        owner_id: str,
    ) -> dict[str, Any]:
        """Synchronous variant of :meth:`prepare_plan_subtasks`.

        Used by :func:`create_run_from_execution_plan` as a fallback
        when the user skipped the preparation step. Blocks until all
        subtasks are generated.
        """
        from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

        cache = get_plan_subtask_cache()
        if cache.is_ready(plan_id):
            return self.get_plan_subtask_status(plan_id)

        cache.set_status(plan_id, status="pending")
        await self._prepare_plan_subtasks_background(
            plan_id, tasks, owner_id=owner_id
        )
        return self.get_plan_subtask_status(plan_id)

    def get_plan_subtask_status(self, plan_id: UUID) -> dict[str, Any]:
        """Return the current preparation status for a plan."""
        from langflow.adlc.plan_subtask_cache import get_plan_subtask_cache

        cache = get_plan_subtask_cache()
        status = cache.get_status(plan_id)
        all_subtasks = cache.get_all_subtasks(plan_id)
        prepared = sum(1 for r in all_subtasks.values() if r.subtasks)
        # ``total_tasks`` is the total number of tasks in the plan. We
        # use the larger of the two counts so the progress bar shows
        # the right denominator even before all tasks are registered.
        total = max(prepared, len(all_subtasks))
        return {
            "status": status["status"],
            "error": status.get("error") or None,
            "total_tasks": total,
            "prepared_tasks": prepared,
        }

    async def _generate_subtasks_for_task(
        self,
        task: TaskRun,
        run: "WorkflowRun",
    ) -> tuple[list["SubtaskRun"], bool]:
        """Generate subtasks for a single task by SDKing to DSH.

        Default mode is ``dsh``: the system asks the DSH LLM how to
        divide the task into parallel subtasks. Falls back to mock
        templates (based on the task's node type) when the DSH SDK is
        unavailable or the planner session fails.

        Set ``ADLC_SUBTASK_GENERATION_MODE=mock`` to force the mock
        template path (useful for offline development).
        """
        from langflow.adlc.task_subtasks import SubtaskRun

        # Check if mock mode is forced via env var.
        use_mock = os.getenv("ADLC_SUBTASK_GENERATION_MODE", "dsh").lower() == "mock"

        if use_mock:
            logger.debug(
                "Using mock subtask template for task %s (forced via env).",
                task.id,
            )
            return _mock_subtasks_for_task(task), True

        # Default: SDK to DSH for subtask generation.
        from langflow.adlc.subtask_generator import SubtaskGenerator

        harness_executor = self._get_harness_executor()
        if harness_executor is None:
            logger.warning(
                "DSH-based subtask generation requested but no harness executor "
                "available. Falling back to mock for task %s.",
                task.id,
            )
            return _mock_subtasks_for_task(task), True

        # Build the generator.
        try:
            generator = SubtaskGenerator(harness_executor)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to create SubtaskGenerator: %s. "
                "Returning mock subtasks for task %s.",
                exc,
                task.id,
            )
            return _mock_subtasks_for_task(task), True

        # Extract task details.
        task_name = task.name or task.key or str(task.id)
        task_type = task.task_type or "unknown"
        task_description = task.request.constraints.get("description", "") if task.request and task.request.constraints else ""
        task_objective = task.name or ""

        # Build workflow context. When called from the plan-level
        # preparation step, ``run`` may be None — fall back to a
        # minimal context in that case.
        if run is not None:
            workflow_context = (
                f"Workflow run: {run.id}\n"
                f"Workflow status: {run.status}\n"
                f"Other tasks: {', '.join(t.name for t in run.tasks if t.id != task.id)}"
            )
        else:
            workflow_context = (
                f"Plan-level subtask preparation for task {task.id}.\n"
                f"Task name: {task_name}\n"
                f"Task type: {task_type}"
            )

        # Generate subtasks via DSH SDK.
        try:
            spec_subtasks = await generator.generate_subtasks(
                task_id=str(task.id),
                task_name=task_name,
                task_type=task_type,
                task_description=task_description,
                task_objective=task_objective,
                workflow_context=workflow_context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Subtask generation failed for task %s: %s. "
                "Returning mock subtasks.",
                task.id,
                exc,
            )
            return _mock_subtasks_for_task(task), True

        # Convert SubtaskSpec to SubtaskRun.
        subtasks = [
            SubtaskRun(
                id=spec.id,
                name=spec.name,
                description=spec.description,
                objective=spec.objective,
                status="pending",
                dependencies=list(spec.dependencies),
                trigger=spec.trigger.value if hasattr(spec.trigger, "value") else str(spec.trigger),
                timeout_seconds=spec.timeout_seconds,
                expected_outputs=list(spec.expected_outputs),
            )
            for spec in spec_subtasks
        ]
        return subtasks, False

    def _get_harness_executor(self):
        """Get the underlying DeepSeekHarnessTaskExecutor from the router.

        The service stores a TaskExecutorRouter which dispatches to
        different executors based on the request's service name. We
        need the harness executor specifically for subtask generation.
        """
        executor = self._executor
        if executor is None:
            return None

        # If it's a router, look up the harness executor.
        if hasattr(executor, "_routes"):
            routes = executor._routes
            for service, route_executor in routes.items():
                if "deepseek-harness" in service:
                    # Unwrap PlanOrchestratingExecutor if present.
                    if hasattr(route_executor, "_task_executor"):
                        return route_executor._task_executor
                    return route_executor

        # If it's a PlanOrchestratingExecutor, unwrap it.
        if hasattr(executor, "_task_executor"):
            return executor._task_executor

        return None

    async def get_operator_controls(self, run_id: UUID, *, owner_id: str) -> RunOperatorControls:
        record = await self._owned_inspection_record(run_id, owner_id=owner_id)
        can_resume = (
            record.run.status is WorkflowRunStatus.PAUSED
            and record.pause_reason != _PAUSE_REASON_RETRY
            and not record.in_flight
        )
        if can_resume:
            for task in record.run.tasks:
                if task.executor.service in _LOOP_SERVICES and task.status is TaskRunStatus.READY:
                    view = await self.get_task_loop(run_id, task.id, owner_id=owner_id)
                    if view.stopped:
                        can_resume = False
                    if not self._loop_service_available(task):
                        can_resume = False
        return RunOperatorControls(
            workflow_run_id=run_id,
            can_pause=record.run.status in {WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING}
            and not record.pause_requested,
            can_resume=can_resume,
            can_cancel=record.run.status not in _TERMINAL_WORKFLOW_STATUSES,
            pause_requested=record.pause_requested,
            pause_reason=record.pause_reason,
        )

    async def get_task_loop(self, run_id: UUID, task_id: UUID, *, owner_id: str) -> TaskLoopInspection:
        """Authorize the run/task first; never dispatch or recover work on this read."""
        record = await self._owned_inspection_record(run_id, owner_id=owner_id)
        task = next((item.model_copy(deep=True) for item in record.run.tasks if item.id == task_id), None)
        if task is None or task.executor.service not in _LOOP_SERVICES:
            message = "The workflow run does not contain this task loop."
            raise AdlcRunNotFoundError(message)
        mode = "MOCK" if task.executor.service == TASK_LOOP_MOCK_SERVICE else "COMMAND"
        view = TaskLoopInspection(
            workflow_run_id=run_id,
            task_run_id=task_id,
            mode=mode,
            history_source="NOT_STARTED" if task.request is None else "UNAVAILABLE",
            history_complete=task.request is None,
        )
        read = getattr(self._executor, "inspect_loop", None)
        try:
            request = await self._loop_inspection_request(task)
            if request is None and task.retry_count:
                view = view.model_copy(
                    update={
                        "history_source": "UNAVAILABLE",
                        "history_complete": False,
                        "unavailable_reason": "TASK_LOOP_INSPECTION_REQUEST_UNAVAILABLE",
                    }
                )
            if request:
                view = empty_inspection(request)
                inspected = await read(request) if callable(read) else None
                if inspected is None and task.executor.service in _DURABLE_LOOP_SERVICES:
                    # Historical checkpoint reads remain available when provider dispatch is disabled.
                    inspected = inspect_live_loop(_loop_checkpoint_store(), request)
                if inspected is not None:
                    view = TaskLoopInspection.model_validate(inspected.model_dump())
                    if view.workflow_run_id != run_id or view.task_run_id != task_id:
                        code = "TASK_LOOP_CORRELATION_MISMATCH"
                        raise LiveLoopError(code)
        except (ValidationError, LiveLoopError, OSError, sqlite3.Error):
            view = TaskLoopInspection(
                workflow_run_id=run_id,
                task_run_id=task_id,
                mode=mode,
                unavailable_reason="TASK_LOOP_HISTORY_UNAVAILABLE",
            )
        if not view.history_complete:
            result = task.pending_result or task.result
            info = result.metadata.get("task_loop", {}) if result else {}
            try:
                history = tuple(LoopIterationView.model_validate(item) for item in info.get("operator_history", []))
                snapshot = view.model_dump()
                snapshot.update(
                    history_source="RUN_SNAPSHOT" if info else "UNAVAILABLE",
                    unavailable_reason=view.unavailable_reason or "TASK_LOOP_CHECKPOINT_UNAVAILABLE",
                    iterations=history,
                    failure_patterns=failure_patterns(history),
                    current_candidate_id=info.get("candidate_id"),
                    current_candidate_digest=info.get("candidate_digest"),
                    total_tokens=info.get("total_tokens"),
                    total_cost=info.get("total_cost"),
                    stop_reason=info.get("stop_reason"),
                    stopped=result is not None,
                )
                view = TaskLoopInspection.model_validate(snapshot)
            except (ValidationError, AttributeError, TypeError):
                # Never expose unchecked arbitrary TaskResult metadata as loop evidence.
                pass
        latest = view.iterations[-1] if view.iterations else None
        if view.history_complete and latest is None and task.result is not None:
            view = view.model_copy(update={"stopped": True, "stop_reason": result_reason(task.result)})
        recoverable = bool(
            view.history_complete
            and latest
            and latest.attempt_id == task.current_attempt_id
            and latest.status == "PASSED"
            and task.status is TaskRunStatus.FAILED
            and self._loop_service_available(task)
        )
        can_retry = bool(
            record.run.status is WorkflowRunStatus.PAUSED
            and record.pause_reason == _PAUSE_REASON_RETRY
            and task.status is TaskRunStatus.FAILED
            and self._loop_service_available(task)
            and (record.scheduler_task is None or record.scheduler_task.done())
            and (
                recoverable
                or (
                    view.history_complete
                    and not view.stopped
                    and view.max_iterations
                    and task.retry_count + 1 < view.max_iterations
                )
            )
        )
        updates = {"can_retry": can_retry, "recovery_available": recoverable and can_retry}
        if record.run.status is WorkflowRunStatus.CANCELLED or task.status is TaskRunStatus.CANCELLED:
            updates.update(stopped=True, stop_reason="TASK_LOOP_CANCELLED", can_retry=False, recovery_available=False)
            if view.iterations and view.iterations[0].started_at and view.iterations[-1].completed_at:
                updates["elapsed_ms"] = max(
                    0, int((view.iterations[-1].completed_at - view.iterations[0].started_at).total_seconds() * 1000)
                )
        return view.model_copy(update=updates)

    async def get_task_loop_runtime(self, run_id: UUID, task_id: UUID, *, owner_id: str):
        """Read the sealed runtime identity; do not infer it from the currently configured adapter."""
        from langflow.adlc.task_loop_runtime_inspection import inspect_runtime
        from langflow.adlc.task_loop_runtime_models import LoopRuntimeView
        from langflow.adlc.task_loop_runtime_v2 import VIEW

        record = await self._owned_inspection_record(run_id, owner_id=owner_id)
        task = next((item.model_copy(deep=True) for item in record.run.tasks if item.id == task_id), None)
        if task is None or task.executor.service not in _LOOP_SERVICES:
            message = "The workflow run does not contain this task loop."
            raise AdlcRunNotFoundError(message)
        scope = {"workflow_run_id": run_id, "task_run_id": task_id}
        try:
            request = await self._loop_inspection_request(task)
            if request is None:
                return LoopRuntimeView(**scope, binding_source="UNAVAILABLE" if task.retry_count else "NOT_STARTED")
            if task.executor.service == TASK_LOOP_MOCK_SERVICE:
                return LoopRuntimeView(**scope, binding_source="LEGACY")
            read = getattr(self._executor, "inspect_loop_runtime", None)
            view = await read(request) if callable(read) else None
            if view is None:
                view = inspect_runtime(_loop_checkpoint_store(), request)
            view = VIEW.validate_python(view.model_dump())
            if view.workflow_run_id != run_id or view.task_run_id != task_id:
                code = "TASK_LOOP_CORRELATION_MISMATCH"
                raise LiveLoopError(code)
        except (ValidationError, LiveLoopError, OSError, sqlite3.Error):
            return LoopRuntimeView(**scope, binding_source="UNAVAILABLE")
        else:
            return view

    async def _loop_inspection_request(self, task: TaskRun) -> TaskRequest | None:
        """Only called after ownership authorization; a sealed reference grants no dispatch authority."""
        if task.request is not None:
            return task.request.model_copy(deep=True)
        if task.retry_count == 0:
            return None
        read = getattr(self._executor, "get_loop_request", None)
        if callable(read):
            request = await read(task.executor.service, task.workflow_run_id, task.id, task.task_definition_id)
        else:
            request = None
        if request is None and task.executor.service in _DURABLE_LOOP_SERVICES:
            request = _loop_checkpoint_store().latest_request(task.workflow_run_id, task.id, task.task_definition_id)
        if request and (
            request.workflow_run_id != task.workflow_run_id
            or request.task_run_id != task.id
            or request.task_definition_id != task.task_definition_id
            or request.executor != task.executor
        ):
            code = "TASK_LOOP_CORRELATION_MISMATCH"
            raise LiveLoopError(code)
        return request

    def _loop_service_available(self, task: TaskRun) -> bool:
        services = getattr(self._executor, "available_services", (self._executor.service_name,))
        return task.executor.service in services

    async def _owned_inspection_record(self, run_id: UUID, *, owner_id: str) -> _StoredRun:
        """Read a detached persisted record without initiating coordinator recovery."""
        if self._project_scope_loader is not None:
            self._project_bound_run_ids = set(await self._project_scope_loader())
        if run_id in self._project_bound_run_ids:
            raise AdlcRunNotFoundError("Shared runs require project-scoped access.")
        if run_id in self._runs:
            return self._owned_run(run_id, owner_id)
        if self._persistence is not None:
            read = getattr(self._persistence, "load_inspection", self._persistence.load)
            snapshots = await read(owner_id=owner_id)
            for saved_owner, run, definitions in snapshots:
                if run.id == run_id and saved_owner == owner_id and run.project_id is None:
                    record = _StoredRun(
                        owner_id=owner_id,
                        run=run,
                        definitions={item.key: item for item in definitions},
                        delay_ms=0,
                    )
                    self._restore_pause_reason(record)
                    return record
        message = "The workflow run was not found."
        raise AdlcRunNotFoundError(message)

    async def get_events(self, run_id: UUID, *, owner_id: str) -> list[RunEvent]:
        await self._ensure_hydrated(owner_id)
        record = self._owned_run(run_id, owner_id)
        return [event.model_copy(deep=True) for event in record.run.events]

    async def list_runs(
        self,
        *,
        owner_id: str,
        limit: int = 25,
        offset: int = 0,
        status: WorkflowRunStatus | None = None,
        flow_id: UUID | None = None,
        execution_plan_id: UUID | None = None,
    ) -> WorkflowRunListResponse:
        """Return owner-scoped, paginated run summaries for run history (read-only)."""
        await self._ensure_hydrated(owner_id)
        if not 1 <= limit <= MAX_RUN_HISTORY_LIMIT or offset < 0:
            message = "Invalid run-history pagination."
            raise AdlcRunStateError(message)
        records = [
            record
            for record in self._runs.values()
            if record.owner_id == owner_id
            and record.run.id not in self._project_bound_run_ids and record.run.project_id is None
            and (status is None or record.run.status is status)
            and (flow_id is None or record.run.flow_id == flow_id)
            and (execution_plan_id is None or record.run.execution_plan_id == execution_plan_id)
        ]
        records.sort(key=lambda record: (record.run.created_at, str(record.run.id)), reverse=True)
        summaries = [
            WorkflowRunSummary(
                id=record.run.id,
                name=record.run.name,
                execution_mode=record.run.execution_mode,
                flow_id=record.run.flow_id,
                execution_plan_id=record.run.execution_plan_id,
                status=record.run.status,
                task_count=len(record.run.tasks),
                completed_task_count=sum(task.status is TaskRunStatus.SUCCEEDED for task in record.run.tasks),
                created_at=record.run.created_at,
                completed_at=record.run.completed_at,
                updated_at=record.run.events[-1].occurred_at if record.run.events else record.run.created_at,
            )
            for record in records[offset : offset + limit]
        ]
        return WorkflowRunListResponse(runs=summaries, total=len(records), limit=limit, offset=offset)

    async def list_run_summaries(
        self,
        *,
        owner_id: str,
        flow_id: UUID | None = None,
        execution_plan_id: UUID | None = None,
    ) -> list[AdlcRunSummary]:
        """Return owner-scoped flat run summaries with task counters (read-only)."""
        await self._ensure_hydrated(owner_id)
        summaries = [
            _run_summary(record.run)
            for record in self._runs.values()
            if record.owner_id == owner_id
            and record.run.id not in self._project_bound_run_ids and record.run.project_id is None
            and (flow_id is None or record.run.flow_id == flow_id)
            and (execution_plan_id is None or record.run.execution_plan_id == execution_plan_id)
        ]
        summaries.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return summaries

    def contract_authoring_owner(self, *, run_id: UUID, task_id: UUID, attempt_id: UUID, request_id: UUID) -> str:
        """Trusted bridge-only lookup; never accept an owner/profile supplied by the tool caller.

        H5A/H5B do not grant existing coding recipes access. The dedicated authoring
        recipe freezes the profile and required plugin into the registered request.
        """
        record = self._runs.get(run_id)
        if record is None:
            msg = "The contract authoring attempt was not found."
            raise AdlcRunNotFoundError(msg)
        task = next((item for item in record.run.tasks if item.id == task_id), None)
        request = task.request if task is not None else None
        if (
            task is None
            or request is None
            or task.current_attempt_id != attempt_id
            or request.attempt_id != attempt_id
            or request.request_id != request_id
            or request.workflow_run_id != run_id
            or request.task_run_id != task_id
            or task.status not in {TaskRunStatus.RUNNING, TaskRunStatus.WAITING_APPROVAL}
            or record.run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.WAITING_APPROVAL}
            or request.executor.service != "agent-provider:deepseek-harness"
            or request.executor.operation != "skilltree-authoring"
        ):
            msg = "The contract authoring attempt is not active."
            raise AdlcRunStateError(msg)
        configuration = request.metadata.get("resolved_configuration")
        if not isinstance(configuration, dict):
            msg = "The contract authoring profile is not authorized."
            raise AdlcRunStateError(msg)
        lock = configuration.get("plugin_lock")
        if configuration.get("harness_profile_ref") != "harness-profile:adlc-skilltree/0.1.0" or not (
            isinstance(lock, list)
            and any(
                isinstance(entry, dict)
                and entry.get("plugin_id") == "vai-adlc-skilltree"
                and entry.get("version") == "0.1.0"
                and entry.get("required") is True
                and isinstance(entry.get("content_digest"), str)
                and entry["content_digest"].startswith("sha256:")
                and len(entry["content_digest"]) == _CONTRACT_PLUGIN_DIGEST_LENGTH
                and all(char in "0123456789abcdef" for char in entry["content_digest"][7:])
                for entry in lock
            )
        ):
            msg = "The contract authoring profile is not authorized."
            raise AdlcRunStateError(msg)
        return record.owner_id

    def memory_session_context(self, *, run_id: UUID, task_id: UUID, attempt_id: UUID, request_id: UUID):
        """Kernel-only ownership lookup for optional read-only project context.

        No model-supplied owner/project or terminal/stale attempt is accepted.
        This does not grant contract, execution, ingestion or deletion authority.
        """
        from langflow.adlc.project_memory_models import ProjectMemoryError

        record = self._runs.get(run_id)
        task = next((item for item in record.run.tasks if item.id == task_id), None) if record else None
        request = task.request if task else None
        if (
            record is None
            or task is None
            or request is None
            or task.current_attempt_id != attempt_id
            or request.attempt_id != attempt_id
            or request.request_id != request_id
            or request.workflow_run_id != run_id
            or request.task_run_id != task_id
            or task.status not in {TaskRunStatus.RUNNING, TaskRunStatus.WAITING_APPROVAL}
            or record.run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.WAITING_APPROVAL}
            or request.executor.service != "agent-provider:deepseek-harness"
        ):
            code = "MEMORY_ATTEMPT_INACTIVE"
            raise ProjectMemoryError(code, 403)
        return record.owner_id, record.run.model_copy(deep=True)

    def contract_execution_context(self, *, run_id: UUID, task_id: UUID, attempt_id: UUID, request_id: UUID):
        """Kernel-only lookup of the current frozen H5C request and accepted plan links."""
        from langflow.adlc.coding_agent import is_contract_coding_release

        record = self._runs.get(run_id)
        task = next((item for item in record.run.tasks if item.id == task_id), None) if record else None
        request = task.request if task else None
        trace = task.plan_traceability if task else None
        if (
            record is None
            or task is None
            or request is None
            or trace is None
            or task.current_attempt_id != attempt_id
            or request.attempt_id != attempt_id
            or request.request_id != request_id
            or request.workflow_run_id != run_id
            or request.task_run_id != task_id
            or task.status not in {TaskRunStatus.RUNNING, TaskRunStatus.WAITING_APPROVAL}
            or record.run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.WAITING_APPROVAL}
            or request.executor.service != "agent-provider:deepseek-harness"
            or request.executor.operation != "contract-coding"
            or trace.execution_plan_id != record.run.execution_plan_id
        ):
            message = "The contract execution attempt is not authorized."
            raise AdlcRunStateError(message)
        configuration = request.metadata.get("resolved_configuration")
        lock = configuration.get("plugin_lock") if isinstance(configuration, dict) else None
        if (
            not isinstance(configuration, dict)
            or not is_contract_coding_release(trace.package_id, trace.package_version, configuration)
            or configuration.get("harness_profile_ref") != "harness-profile:adlc-contract-coding/0.1.0"
            or not (
                isinstance(lock, list)
                and any(
                    isinstance(entry, dict)
                    and entry.get("plugin_id") == "vai-adlc-contract-execution"
                    and entry.get("version") == "0.1.0"
                    and entry.get("required") is True
                    and isinstance(entry.get("content_digest"), str)
                    and entry["content_digest"].startswith("sha256:")
                    and len(entry["content_digest"]) == _CONTRACT_PLUGIN_DIGEST_LENGTH
                    and all(char in "0123456789abcdef" for char in entry["content_digest"][7:])
                    for entry in lock
                )
            )
        ):
            message = "The contract execution profile is not authorized."
            raise AdlcRunStateError(message)
        return record.owner_id, configuration, trace

    async def get_source_patch(self, run_id: UUID, artifact_id: UUID, *, owner_id: str) -> SourcePatchRead:
        """Authorize through run ownership before reading any retained patch bytes."""
        record = await self._owned_inspection_record(run_id, owner_id=owner_id)
        artifact = next(
            (
                item
                for task in record.run.tasks
                for item in task.artifacts
                if item.artifact_id == artifact_id and item.kind == "SOURCE_PATCH"
            ),
            None,
        )
        if artifact is None and self._harness_callbacks is not None:
            # Older immutable attempts remain reviewable after an explicit retry.
            attempts = await self._harness_callbacks.attempts.list_for_workflow_run(run_id)
            artifact = next(
                (
                    item
                    for attempt in attempts
                    for item in (attempt.result.artifacts if attempt.result is not None else [])
                    if item.artifact_id == artifact_id and item.kind == "SOURCE_PATCH"
                ),
                None,
            )
        if artifact is None:
            read = getattr(self._executor, "get_loop_artifact", None)
            try:
                for task in record.run.tasks:
                    if task.executor.service in _DURABLE_LOOP_SERVICES:
                        request = await self._loop_inspection_request(task)
                        if request is None:
                            continue
                        artifact = await read(request, artifact_id) if callable(read) else None
                        if artifact is None:
                            artifact = _loop_checkpoint_store().artifact(request, artifact_id)
                        if artifact is not None:
                            break
            except (ValidationError, LiveLoopError, OSError, sqlite3.Error):
                message = "The saved iteration patch is unavailable."
                raise AdlcArtifactUnavailableError(message) from None
        if artifact is None:
            message = f"Source patch artifact {artifact_id} was not found in workflow run {run_id}."
            raise AdlcRunNotFoundError(message)
        try:
            payload = self._artifact_payloads.read(artifact)
        except ArtifactPayloadUnavailableError as exc:
            message = "The source patch is no longer available for review."
            raise AdlcArtifactUnavailableError(message) from exc
        snapshot = SourcePatchSnapshot.model_validate_json(payload)
        return SourcePatchRead(artifact=artifact.model_copy(deep=True), **snapshot.model_dump())

    async def retry_task(self, task_id: UUID, *, owner_id: str) -> WorkflowRun:
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record, task = self._owned_task(task_id, owner_id)
            run = record.run
            if run.status is not WorkflowRunStatus.PAUSED or record.pause_reason != _PAUSE_REASON_RETRY:
                msg = "Only a PAUSED workflow run awaiting manual retry can retry a task."
                raise AdlcRunStateError(msg)
            if task.status is not TaskRunStatus.FAILED:
                msg = "Only a FAILED task run can be retried."
                raise AdlcRunStateError(msg)

            if record.scheduler_task is not None and not record.scheduler_task.done():
                msg = "Recovery or execution is still active for this run."
                raise AdlcRunStateError(msg)
            if await self._prepare_accepted_recovery_result(record, task):
                self._start_background(record, recovery=True)
                return run.model_copy(deep=True)

            if task.executor.service in _LOOP_SERVICES:
                if not self._loop_service_available(task):
                    message = "The task-loop runtime is unavailable. Restore it before retrying."
                    raise AdlcRunStateError(message)
                view = await self.get_task_loop(run.id, task.id, owner_id=owner_id)
                if not view.history_complete or view.stopped:
                    message = "This task loop cannot continue. Preserve its candidate and start a new run."
                    raise AdlcRunStateError(message)

            max_attempts = 2
            if task.request and task.request.constraints:
                configured_max = task.request.constraints.get("max_attempts")
                if isinstance(configured_max, int) and not isinstance(configured_max, bool):
                    max_attempts = configured_max
            attempts_used = task.retry_count + 1
            if attempts_used >= max_attempts:
                message = f"Task '{task.name}' has exhausted its {max_attempts} configured attempt(s)."
                raise AdlcRunStateError(message)

            task.retry_count += 1
            task.simulate_failure = False
            task.current_attempt_id = None
            task.request = None
            task.result = None
            task.pending_result = None
            task.completed_at = None
            task.deadline_at = None
            record.retry_ready_at.pop(task.id, None)
            self._transition_task(
                run,
                task,
                TaskRunStatus.READY,
                event_type="task_run.retry_requested",
                payload={"retry_count": task.retry_count},
            )
            self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload={"reason": "task_retry"})
            self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload={"reason": "task_retry"})
            record.pause_reason = None
            if any(item.executor.service in _BACKGROUND_EXECUTOR_SERVICES for item in run.tasks):
                await self._persist_safely(record, required=True)
                self._start_background(record)
                return run.model_copy(deep=True)
            await self._execute_task(record, task)
            await self._schedule(record)
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def approve(self, approval_id: UUID, *, owner_id: str, actor: Actor, comment: str | None) -> WorkflowRun:
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record, approval = self._owned_approval(approval_id, owner_id)
            run = record.run
            task = self._task_by_id(run, approval.task_run_id)
            self._validate_pending_approval(run, task, approval)
            self._verify_approval_artifact_digests(record, run, task, approval)

            approval.status = ApprovalStatus.APPROVED
            approval.decision = ApprovalDecision(
                action_id="approve",
                effect="APPROVE",
                decided_by=actor,
                comment=comment,
                decided_at=utc_now(),
            )
            self._emit_approval_event(
                run,
                approval,
                previous_status=ApprovalStatus.PENDING,
                event_type="approval_request.approved",
                actor=actor,
            )
            pending_result = task.pending_result
            if pending_result is None:  # Guarded by _validate_pending_approval.
                message = "The approval task has no pending result."
                raise AdlcRunStateError(message)
            if approval.gate_type is GateType.ACTION:
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.RUNNING,
                    event_type="task_run.resumed",
                    payload={"approval_request_id": str(approval.approval_request_id)},
                )
            task.result = (
                pending_result.model_copy(
                    update={
                        "output": {"outputs": {"approval_decision": approval.decision.model_dump(mode="json")}},
                        "completed_at": approval.decision.decided_at,
                    },
                    deep=True,
                )
                if task.executor.service == "control:approval"
                else pending_result
            )
            task.pending_result = None
            self._transition_task(
                run,
                task,
                TaskRunStatus.SUCCEEDED,
                payload={"approval_request_id": str(approval.approval_request_id)},
            )
            self._mirror_task_evidence(run, task, task.result)
            self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload={"reason": "approval_resolved"})
            self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload={"reason": "approval_resolved"})
            await self._continue_run(record)
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def reject(self, approval_id: UUID, *, owner_id: str, actor: Actor, comment: str | None) -> WorkflowRun:
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record, approval = self._owned_approval(approval_id, owner_id)
            run = record.run
            task = self._task_by_id(run, approval.task_run_id)
            self._validate_pending_approval(run, task, approval)

            now = utc_now()
            approval.status = ApprovalStatus.REJECTED
            approval.decision = ApprovalDecision(
                action_id="reject",
                effect="REJECT",
                decided_by=actor,
                comment=comment,
                decided_at=now,
            )
            self._emit_approval_event(
                run,
                approval,
                previous_status=ApprovalStatus.PENDING,
                event_type="approval_request.rejected",
                actor=actor,
            )
            pending_result = task.pending_result
            if pending_result is None:  # Guarded by _validate_pending_approval.
                msg = "The approval task has no pending result."
                raise AdlcRunStateError(msg)
            error = ServiceError(
                error_id=uuid4(),
                code="APPROVAL_REJECTED",
                category="AUTHORIZATION",
                message="The reviewer rejected the task result.",
                retryable=False,
                service="adlc-run-coordinator",
                details={"approval_request_id": str(approval_id)},
                correlation_id=f"run-{run.id}/task-{task.id}",
                occurred_at=now,
            )
            task.result = TaskResult(
                request_id=pending_result.request_id,
                workflow_run_id=pending_result.workflow_run_id,
                task_run_id=pending_result.task_run_id,
                attempt_id=pending_result.attempt_id,
                status=TaskResultStatus.FAILED,
                output=None,
                artifacts=pending_result.artifacts,
                error=error,
                metrics=pending_result.metrics,
                started_at=pending_result.started_at,
                completed_at=now,
                metadata={**pending_result.metadata, "approval_rejected": True},
            )
            task.pending_result = None
            self._transition_task(
                run,
                task,
                TaskRunStatus.FAILED,
                payload={"approval_request_id": str(approval_id), "error_code": error.code},
            )
            self._mirror_task_evidence(run, task, task.result)
            self._transition_workflow(
                run,
                WorkflowRunStatus.FAILED,
                payload={"approval_request_id": str(approval_id)},
            )
            await self._reflect_on_run(run)
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def emit_event(
        self,
        run_id: UUID,
        event_name: str,
        *,
        owner_id: str,
        payload: dict | None = None,
    ) -> WorkflowRun:
        """Record an external runtime event and wake any task waiting on it."""
        await self._ensure_hydrated(owner_id)
        if not EVENT_NAME_PATTERN.match(event_name):
            message = f"Event name '{event_name}' is not a valid lowercase identifier."
            raise AdlcRunStateError(message)
        async with self._mutation_lock:
            record = self._owned_run(run_id, owner_id)
            run = record.run
            if run.status not in {WorkflowRunStatus.RUNNING, WorkflowRunStatus.PAUSED}:
                message = "Runtime events can only be emitted onto RUNNING or PAUSED workflow runs."
                raise AdlcRunStateError(message)
            if run.status is WorkflowRunStatus.PAUSED and record.pause_reason == _PAUSE_REASON_USER:
                # A user pause suppresses automatic progress; the event is recorded
                # for replay and takes effect when the run is explicitly resumed.
                self._emit_runtime_event(record, run, event_name, payload)
                await self._persist_safely(record)
                return run.model_copy(deep=True)
            if run.status is WorkflowRunStatus.PAUSED:
                self._transition_workflow(
                    run,
                    WorkflowRunStatus.QUEUED,
                    payload={"reason": "event_received", "event_name": event_name},
                )
                self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload={"reason": "event_received"})
            self._emit_runtime_event(record, run, event_name, payload)
            await self._continue_run(record)
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def resume_run(self, run_id: UUID, *, owner_id: str) -> WorkflowRun:
        """Re-dispatch work for a PAUSED or restored run after executor loss."""
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record = self._owned_run(run_id, owner_id)
            run = record.run
            if run.status in _TERMINAL_WORKFLOW_STATUSES:
                msg = "A terminal workflow run cannot be resumed."
                raise AdlcRunStateError(msg)
            if run.status is WorkflowRunStatus.PAUSED and record.pause_reason == _PAUSE_REASON_RETRY:
                msg = "This run requires a task retry or a successor run."
                raise AdlcRunStateError(msg)
            if run.status is WorkflowRunStatus.PAUSED:
                for task in run.tasks:
                    if task.executor.service in _LOOP_SERVICES and task.status is TaskRunStatus.READY:
                        if not self._loop_service_available(task):
                            msg = "The task-loop runtime is unavailable. Restore it before resuming."
                            raise AdlcRunStateError(msg)
                        view = await self.get_task_loop(run.id, task.id, owner_id=owner_id)
                        if view.stopped:
                            msg = "This task loop reached its stopping condition. Start a successor run."
                            raise AdlcRunStateError(msg)
            if record.in_flight:
                msg = "The workflow run still has tasks executing in this process."
                raise AdlcRunStateError(msg)

            record.cancel_requested = False
            record.pause_requested = False
            record.pause_reason = None
            orphaned = [task for task in run.tasks if task.status is TaskRunStatus.RUNNING]
            for task in orphaned:
                task.deadline_at = None
                task.worker_id = None
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.READY,
                    event_type="task_run.resumed",
                    payload={"reason": "executor_state_restored"},
                )
            if run.status is not WorkflowRunStatus.RUNNING:
                self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload={"reason": "resume_requested"})
                self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload={"reason": "resume_requested"})
            if any(task.executor.service in _BACKGROUND_EXECUTOR_SERVICES for task in run.tasks):
                await self._persist_safely(record, required=True)
                self._start_background(record, recovery=bool(orphaned))
                return run.model_copy(deep=True)
            await self._schedule(record)
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def cancel_run(self, run_id: UUID, *, owner_id: str, actor: Actor | None = None) -> WorkflowRun:
        """Cancel a non-terminal workflow run and every piece of work it still owns.

        In-flight executor attempts are cancelled cooperatively; once the run is
        persisted as CANCELLED the transition is terminal. Pending approval
        requests are cancelled with the run per the v0.1 approval invariants.
        """
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record = self._owned_run(run_id, owner_id)
            run = record.run
            if run.status in _TERMINAL_WORKFLOW_STATUSES:
                msg = "A terminal workflow run cannot be cancelled."
                raise AdlcRunStateError(msg)

            record.cancel_requested = True
            record.pause_requested = False
            in_flight = list(record.in_flight)
            for pending in in_flight:
                pending.cancel()
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
                for pending in in_flight:
                    record.in_flight.pop(pending, None)

            payload = _actor_payload(actor)
            for task in run.tasks:
                if task.status not in _CANCELLABLE_TASK_STATUSES:
                    continue
                if task.status is TaskRunStatus.WAITING_APPROVAL:
                    task.pending_result = None
                task.deadline_at = None
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.CANCELLED,
                    payload={"reason": "workflow_cancelled", **payload},
                )
            for approval in run.approval_requests:
                if approval.status is not ApprovalStatus.PENDING:
                    continue
                approval.status = ApprovalStatus.CANCELLED
                self._emit_approval_event(
                    run,
                    approval,
                    previous_status=ApprovalStatus.PENDING,
                    event_type="approval_request.cancelled",
                    actor=actor or SYSTEM_ACTOR,
                )
            self._transition_workflow(
                run,
                WorkflowRunStatus.CANCELLED,
                payload={"reason": "cancelled_by_user", **payload},
            )
            await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def pause_run(self, run_id: UUID, *, owner_id: str, actor: Actor | None = None) -> WorkflowRun:
        """Request a run-level pause.

        The scheduler stops dispatching new work; in-flight attempts run to
        their safe boundary before the run transitions to PAUSED. Runs blocked
        by an open approval cannot be paused per the frozen state machine.
        """
        await self._ensure_hydrated(owner_id)
        async with self._mutation_lock:
            record = self._owned_run(run_id, owner_id)
            run = record.run
            if run.status in _TERMINAL_WORKFLOW_STATUSES:
                msg = "A terminal workflow run cannot be paused."
                raise AdlcRunStateError(msg)
            if run.status is WorkflowRunStatus.WAITING_APPROVAL:
                msg = "A run blocked by an open approval cannot be paused; resolve or cancel the approval instead."
                raise AdlcRunStateError(msg)
            if run.status is WorkflowRunStatus.PAUSED:
                msg = "The workflow run is already paused."
                raise AdlcRunStateError(msg)

            record.pause_requested = True
            record.pause_reason = _PAUSE_REASON_USER
            scheduler = record.scheduler_task
            if scheduler is None or scheduler.done():
                # No live scheduler loop will observe the flag; pause immediately.
                record.pause_requested = False
                self._transition_workflow(
                    run,
                    WorkflowRunStatus.PAUSED,
                    payload={"reason": _PAUSE_REASON_USER, **_actor_payload(actor)},
                )
                await self._persist_safely(record)
            return run.model_copy(deep=True)

    async def expire_due_approvals(self, *, now: datetime | None = None) -> list[UUID]:
        """Expire every overdue pending approval and fail its waiting task.

        Returns the expired approval request ids. Expiry uses only frozen
        machine transitions: PENDING -> EXPIRED on the approval, WAITING_APPROVAL -> FAILED on
        the task, and WAITING_APPROVAL -> FAILED on the run (the human gate lapsed, so the run
        terminalizes like any other failure; a fresh run is the correct revival path).
        """
        current = now or utc_now()
        expired_ids: list[UUID] = []
        dirty_records: set[UUID] = set()
        async with self._mutation_lock:
            for record in self._runs.values():
                run = record.run
                for approval in list(run.approval_requests):
                    if approval.status is not ApprovalStatus.PENDING or approval.expires_at is None:
                        continue
                    if approval.expires_at > current:
                        continue
                    self._expire_approval(record, approval, current)
                    expired_ids.append(approval.approval_request_id)
                    dirty_records.add(run.id)
            for record_id in dirty_records:
                record = self._runs.get(record_id)
                if record is not None:
                    if record.run.status is WorkflowRunStatus.FAILED:
                        await self._reflect_on_run(record.run)
                    await self._persist_safely(record)
        return expired_ids

    async def check_run_slas(self, *, now: datetime | None = None) -> list[UUID]:
        """Mark and notify the first SLA breach per non-terminal run."""
        current = now or utc_now()
        breached_ids: list[UUID] = []
        dirty_records: set[UUID] = set()
        async with self._mutation_lock:
            for record in self._runs.values():
                run = record.run
                if (
                    run.sla_deadline_at is None
                    or run.sla_breached_at is not None
                    or run.status in _TERMINAL_WORKFLOW_STATUSES
                ):
                    continue
                if run.sla_deadline_at > current:
                    continue
                run.sla_breached_at = current
                run.events.append(
                    RunEvent(
                        event_id=uuid4(),
                        event_type="workflow_run.sla_breached",
                        workflow_run_id=run.id,
                        aggregate_type="WORKFLOW_RUN",
                        aggregate_id=run.id,
                        sequence=len(run.events) + 1,
                        previous_status=run.status.value,
                        status=run.status.value,
                        actor=SYSTEM_ACTOR,
                        correlation_id=f"run-{run.id}",
                        occurred_at=current,
                        producer="adlc-run-coordinator",
                        payload={"sla_deadline_at": run.sla_deadline_at.isoformat()},
                    )
                )
                self._notify(
                    AdlcNotificationKind.SLA_BREACHED,
                    run,
                    message=f"Run '{run.name}' exceeded its service-level deadline.",
                    metadata={"sla_deadline_at": run.sla_deadline_at.isoformat()},
                )
                breached_ids.append(run.id)
                dirty_records.add(run.id)
            for record_id in dirty_records:
                record = self._runs.get(record_id)
                if record is not None:
                    await self._persist_safely(record)
        return breached_ids

    def start_approval_sweeper(self, *, interval_seconds: float = 30.0) -> None:
        """Start the background approval-expiry and SLA sweep loop (idempotent)."""
        if self._sweeper_task is not None and not self._sweeper_task.done():
            return
        self._sweeper_task = asyncio.create_task(
            self._run_approval_sweeper(interval_seconds),
            name="adlc-approval-sweeper",
        )

    async def stop_approval_sweeper(self) -> None:
        """Cancel the background sweep loop and wait for it to finish."""
        task = self._sweeper_task
        self._sweeper_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def recover(self) -> RunRecoveryReport:
        """Restore snapshots and observe original attempts once, without redispatch."""
        await self._ensure_hydrated(None)
        report = self._recovery_report
        self._recovery_report = RunRecoveryReport()
        return report

    async def shutdown(self) -> None:
        """Stop background loops and cancel in-flight scheduling tasks."""
        self._closing = True
        await self.stop_approval_sweeper()
        for background in list(self._background_runs):
            background.cancel()
        if self._background_runs:
            await asyncio.gather(*self._background_runs, return_exceptions=True)

    async def _prepare_accepted_recovery_result(self, record: _StoredRun, task: TaskRun) -> bool:
        """Adopt a late accepted result before allowing an explicit replacement attempt."""
        error = task.result.error if task.result is not None else None
        request = task.request
        if task.status is not TaskRunStatus.FAILED or request is None or error is None:
            return False
        if task.executor.service in _DURABLE_LOOP_SERVICES:
            read = getattr(self._executor, "get_saved_result", None)
            if not callable(read):
                return False
            try:
                saved = await read(request)
            except (LiveLoopError, OSError):
                message = "The saved task-loop attempt is unavailable; restore its storage before retrying."
                raise AdlcRunStateError(message) from None
            if (
                saved is None
                or saved.status is not TaskResultStatus.SUCCEEDED
                or (saved.request_id, saved.workflow_run_id, saved.task_run_id, saved.attempt_id)
                != (request.request_id, request.workflow_run_id, request.task_run_id, request.attempt_id)
            ):
                return False
        elif (
            self._harness_callbacks is not None
            and task.executor.service in _ASYNC_EXECUTOR_SERVICES
            and error.code.startswith(("ADLC_RECOVERY_", "HARNESS_RECOVERY_"))
        ):
            try:
                attempt = await self._harness_callbacks.attempts.get(request.attempt_id)
            except HarnessAttemptError:
                return False
            if attempt.result is None or attempt.result.correlation != HarnessCorrelation(
                request_id=request.request_id,
                workflow_run_id=request.workflow_run_id,
                task_run_id=request.task_run_id,
                attempt_id=request.attempt_id,
            ):
                return False
        else:
            return False
        task.result = None
        task.completed_at = None
        self._transition_task(
            record.run,
            task,
            TaskRunStatus.READY,
            event_type="task_run.resumed",
            payload={"reason": "accepted_result_after_recovery_failure"},
        )
        if record.run.status is WorkflowRunStatus.PAUSED:
            self._transition_workflow(record.run, WorkflowRunStatus.QUEUED)
            self._transition_workflow(record.run, WorkflowRunStatus.RUNNING)
            record.pause_reason = None
        await self._persist_safely(record, required=True)
        return True

    async def _observe_attempt(self, record: _StoredRun, task: TaskRun, on_state_change) -> None:
        """Consume durable results or resume observation of the exact original request."""
        request = task.request
        if task.status is TaskRunStatus.READY and request is not None:
            await on_state_change(TaskRunStatus.RUNNING, None)
        if request is not None and task.executor.service == HARNESS_WORKFLOW_SERVICE:
            await self._executor.resume(request, on_state_change)
            return
        if request is not None and task.executor.service in _DURABLE_LOOP_SERVICES:
            try:
                await self._executor.resume(request, on_state_change)
            except TaskExecutorRecoveryError:
                await self._recovery_failure(record, task, "ADLC_RECOVERY_TASK_LOOP_MISSING", on_state_change)
            return
        if request is not None and task.executor.service in _ASYNC_EXECUTOR_SERVICES:
            if self._harness_callbacks is not None:
                try:
                    attempt = await self._harness_callbacks.attempts.get(request.attempt_id)
                except HarnessAttemptError:
                    await self._recovery_failure(record, task, "ADLC_RECOVERY_ATTEMPT_MISSING", on_state_change)
                    return
                if attempt.result is not None:
                    if attempt.result.correlation != HarnessCorrelation(
                        request_id=request.request_id,
                        workflow_run_id=request.workflow_run_id,
                        task_run_id=request.task_run_id,
                        attempt_id=request.attempt_id,
                    ):
                        await self._recovery_failure(
                            record, task, "ADLC_RECOVERY_CORRELATION_MISMATCH", on_state_change
                        )
                        return
                    result = harness_result_to_task_result(attempt.result)
                    await on_state_change(TaskRunStatus(result.status.value), result)
                    return
            resume = getattr(self._executor, "resume", None)
            if callable(resume):
                try:
                    await resume(request, on_state_change)
                except TaskExecutorRecoveryError:
                    pass
                else:
                    return
        await self._recovery_failure(record, task, "ADLC_RECOVERY_REQUIRES_RETRY", on_state_change)

    async def _recovery_failure(self, record: _StoredRun, task: TaskRun, code: str, on_state_change) -> None:
        now = utc_now()
        request = task.request
        attempt_id = request.attempt_id if request is not None else task.current_attempt_id or uuid4()
        task.current_attempt_id = attempt_id
        result = TaskResult(
            request_id=request.request_id if request is not None else uuid4(),
            workflow_run_id=record.run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=ServiceError(
                error_id=uuid4(),
                code=code,
                category="DEPENDENCY",
                retryable=True,
                message=(
                    "The interrupted attempt could not be safely reattached. No replacement execution was started; "
                    "review it before requesting Retry."
                ),
                service="adlc-run-coordinator",
                occurred_at=now,
            ),
            started_at=task.started_at or now,
            completed_at=now,
            metadata={"restart_recovery": True},
        )
        await on_state_change(TaskRunStatus.FAILED, result)

    async def list_dead_letters(self, *, owner_id: str) -> list[AdlcDeadLetter]:
        """Return owner-scoped tasks that auto-recovery cannot revive.

        A task is dead-lettered when its attempt budget is exhausted or its
        recorded error is non-retryable; both require a human decision.
        """
        await self._ensure_hydrated(owner_id)
        letters: list[AdlcDeadLetter] = []
        for record in self._runs.values():
            if (
                record.owner_id != owner_id
                or record.run.project_id is not None
                or record.run.id in self._project_bound_run_ids
            ):
                continue
            run = record.run
            for task in run.tasks:
                if task.status is not TaskRunStatus.FAILED:
                    continue
                error = task.result.error if task.result is not None else None
                attempts_exhausted = task.retry_count + 1 >= self._max_attempts(task)
                non_retryable = error is not None and not error.retryable
                if not (attempts_exhausted or non_retryable):
                    continue
                letters.append(
                    AdlcDeadLetter(
                        workflow_run_id=run.id,
                        run_name=run.name,
                        run_status=run.status,
                        task_run_id=task.id,
                        task_key=str(task.key),
                        task_name=task.name,
                        error_code=error.code if error is not None else None,
                        error_message=error.message if error is not None else None,
                        retry_count=task.retry_count,
                        max_attempts=self._max_attempts(task),
                        failed_at=task.completed_at,
                    )
                )
        letters.sort(
            key=lambda letter: (
                letter.failed_at or datetime.min.replace(tzinfo=timezone.utc),
                letter.task_run_id,
            ),
            reverse=True,
        )
        return letters

    async def clear(self) -> None:
        async with self._mutation_lock:
            for background in self._background_runs:
                background.cancel()
            if self._background_runs:
                await asyncio.gather(*self._background_runs, return_exceptions=True)
            self._background_runs.clear()
            self._runs.clear()
            self._hydrated_owners.clear()
            self._recovery_done = False
            self._recovery_report = RunRecoveryReport()
            self._closing = False
            if self._persistence is not None:
                try:
                    await self._persistence.clear()
                except Exception:  # noqa: BLE001 - teardown must tolerate unavailable snapshot stores.
                    logger.warning("Failed to clear persisted ADLC run snapshots.", exc_info=True)

    def _start_background(self, record: _StoredRun, *, recovery: bool = False) -> None:
        if record.run.project_id is not None or record.run.id in self._project_bound_run_ids:
            raise AdlcRunStateError("TEAM_SHARED_EXECUTION_NOT_ENABLED")
        if self._closing or (record.scheduler_task is not None and not record.scheduler_task.done()):
            return
        background = asyncio.create_task(self._schedule_background(record, recovery=recovery))
        record.scheduler_task = background
        self._background_runs.add(background)
        background.add_done_callback(self._background_runs.discard)

    async def _continue_run(self, record: _StoredRun) -> None:
        """Advance commands without starting a second scheduler for live agent work."""
        await self._persist_safely(record, required=True)
        if record.scheduler_task is not None and not record.scheduler_task.done():
            return
        if any(task.executor.service in _BACKGROUND_EXECUTOR_SERVICES for task in record.run.tasks):
            self._start_background(record)
        else:
            await self._schedule(record)

    async def _schedule_background(self, record: _StoredRun, *, recovery: bool = False) -> None:
        try:
            if recovery:
                for task in record.run.tasks:
                    if (
                        task.status in {TaskRunStatus.RUNNING, TaskRunStatus.READY, TaskRunStatus.WAITING_APPROVAL}
                        and task.pending_result is None
                        and (task.request is not None or task.status is not TaskRunStatus.READY)
                    ):
                        record.in_flight[asyncio.create_task(self._execute_task(record, task, recovery=True))] = task
            await self._schedule(record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the background boundary must record unexpected executor failures.
            run = record.run
            if run.status not in {
                WorkflowRunStatus.SUCCEEDED,
                WorkflowRunStatus.FAILED,
                WorkflowRunStatus.CANCELLED,
            }:
                self._transition_workflow(
                    run,
                    WorkflowRunStatus.FAILED,
                    payload={"reason": "background_execution_failed", "exception_type": type(exc).__name__},
                )
            await self._persist_safely(record)

    def _create_run(
        self,
        *,
        flow_id: UUID,
        flow_name: str,
        definitions: list[AdlcTaskDefinition],
        request: CreateWorkflowRunRequest,
        owner_id: str,
        execution_plan_id: UUID | None,
        workflow_key: str | None,
    ) -> _StoredRun:
        if request.execution_mode is WorkflowExecutionMode.MOCK_WORKFLOW:
            msg = "MOCK_WORKFLOW mode belongs to MockWorkflowService."
            raise AdlcRunStateError(msg)
        if request.execution_mode is WorkflowExecutionMode.EXECUTION_PLAN and execution_plan_id is None:
            msg = "EXECUTION_PLAN mode requires an execution plan id."
            raise AdlcRunStateError(msg)
        if request.execution_mode is not WorkflowExecutionMode.EXECUTION_PLAN and execution_plan_id is not None:
            msg = "Only EXECUTION_PLAN mode may carry an execution plan id."
            raise AdlcRunStateError(msg)
        run_id = uuid4()
        definitions = [definition.model_copy(deep=True) for definition in definitions]
        definition_map = {definition.key: definition for definition in definitions}
        task_ids = {key: uuid4() for key in definition_map}
        failure_key = request.failure_task_id
        if request.simulate_failure and failure_key is None:
            failure_key = next(definition.key for definition in definitions if not definition.dependencies)
        if request.simulate_failure and failure_key not in definition_map:
            msg = f"Failure task '{failure_key}' is not present in the ADLC DAG."
            raise AdlcRunStateError(msg)

        tasks = [
            TaskRun(
                id=task_ids[definition.key],
                workflow_run_id=run_id,
                task_definition_id=definition.id,
                key=definition.key,
                name=definition.name,
                task_type=definition.task_type,
                status=TaskRunStatus.PENDING,
                dependency_task_run_ids=[task_ids[key] for key in definition.dependencies],
                executor=definition.executor_target
                or ExecutorTarget(
                    service=self._executor.service_name,
                    operation=definition.key,
                    capabilities=list(self._executor.capabilities),
                ),
                simulate_failure=(request.simulate_failure and failure_key == definition.key)
                or definition.simulate_failure,
                plan_traceability=definition.plan_traceability,
            )
            for definition in definitions
        ]
        run_number = 1 + sum(1 for record in self._runs.values() if record.run.flow_id == flow_id)
        created_at = utc_now()
        run = WorkflowRun(
            id=run_id,
            workflow_key=workflow_key or str(flow_id),
            execution_mode=request.execution_mode,
            flow_id=flow_id,
            execution_plan_id=execution_plan_id,
            run_number=run_number,
            name=flow_name,
            status=WorkflowRunStatus.CREATED,
            tasks=tasks,
            created_at=created_at,
            sla_deadline_at=(
                created_at + timedelta(seconds=request.sla_seconds) if request.sla_seconds is not None else None
            ),
        )
        self._emit_workflow_event(
            run,
            previous_status=None,
            payload={
                "flow_id": str(flow_id),
                "mock": True,
                "execution_mode": request.execution_mode.value,
                "max_concurrency": request.max_concurrency,
                "delay_ms": request.delay_ms,
            },
        )
        for task in tasks:
            self._emit_task_event(run, task, previous_status=None, payload={"task_key": str(task.key)})
        return _StoredRun(
            owner_id=owner_id,
            run=run,
            definitions=definition_map,
            delay_ms=request.delay_ms,
            max_concurrency=request.max_concurrency,
        )

    async def _schedule(self, record: _StoredRun) -> None:
        if record.run.project_id is not None or record.run.id in self._project_bound_run_ids:
            raise AdlcRunStateError("TEAM_SHARED_EXECUTION_NOT_ENABLED")
        in_flight = record.in_flight
        run = record.run
        try:
            while not record.cancel_requested:
                self._skip_unsatisfiable_tasks(record, run)
                batch = [] if record.pause_requested else self._select_dispatch_batch(record, run, in_flight)
                if not batch:
                    if in_flight:
                        done, _ = await asyncio.wait(set(in_flight), return_when=asyncio.FIRST_COMPLETED)
                        for finished in done:
                            task = in_flight.pop(finished, None)
                            await self._reap_finished(record, run, finished, task)
                        # Persist after every reaped completion so a crash loses at
                        # most the work still in flight, never completed outcomes.
                        await self._persist_safely(record)
                        continue
                    if record.pause_requested:
                        break
                    next_ready = self._earliest_retry_time(record, run)
                    if next_ready is None:
                        break
                    delay_seconds = (next_ready - utc_now()).total_seconds()
                    if delay_seconds > 0:
                        await asyncio.sleep(delay_seconds)
                    continue
                for task in batch:
                    if task.status is TaskRunStatus.PENDING:
                        self._transition_task(run, task, TaskRunStatus.READY)
                for task in batch:
                    in_flight[asyncio.create_task(self._execute_task(record, task))] = task
        finally:
            if in_flight:
                for pending in in_flight:
                    pending.cancel()
                await asyncio.gather(*in_flight, return_exceptions=True)
                in_flight.clear()
        await self._persist_safely(record)
        if record.cancel_requested:
            # cancel_run owns every CANCELLED transition for this run.
            return
        if record.pause_requested:
            record.pause_requested = False
            record.pause_reason = _PAUSE_REASON_USER
            self._transition_workflow(
                run,
                WorkflowRunStatus.PAUSED,
                payload={"reason": _PAUSE_REASON_USER},
            )
            await self._persist_safely(record)
            return
        self._finalize(record, run)
        if run.status in {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED}:
            await self._reflect_on_run(run)
        # The finalize transition (SUCCEEDED/WAITING_APPROVAL/PAUSED) must be
        # durable before the scheduler loop exits, or a restart restores the
        # pre-terminal projection and replays already-completed work.
        await self._persist_safely(record)

    async def _reap_finished(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        finished: asyncio.Task[None],
        task: TaskRun | None,
    ) -> None:
        """Surface one completed dispatch outcome without killing the scheduler loop."""
        try:
            finished.result()
        except asyncio.CancelledError:
            if record.cancel_requested or task is None:
                return
            logger.warning(
                "ADLC task '%s' in run %s lost its executor task unexpectedly.",
                task.key,
                run.id,
            )
            self._handle_task_failure_from_exception(record, run, task)
        except RunRepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001 - one crashed attempt must not kill sibling work.
            logger.warning(
                "ADLC task dispatch crashed for run %s task '%s'.",
                run.id,
                task.key if task is not None else "<unknown>",
                exc_info=exc,
            )
            if task is not None:
                self._handle_task_failure_from_exception(record, run, task, exception=exc)

    def _earliest_retry_time(self, record: _StoredRun, run: WorkflowRun) -> datetime | None:
        """Return the earliest backoff deadline among tasks still awaiting dispatch."""
        dispatchable_ids = {
            task.id for task in run.tasks if task.status in {TaskRunStatus.PENDING, TaskRunStatus.READY}
        }
        ready_times = [ready_at for task_id, ready_at in record.retry_ready_at.items() if task_id in dispatchable_ids]
        return min(ready_times) if ready_times else None

    def _select_dispatch_batch(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        in_flight: dict[asyncio.Task[None], TaskRun],
    ) -> list[TaskRun]:
        """Pick highest-priority ready tasks honoring the concurrency budget and resource locks."""
        limit = record.max_concurrency
        remaining = limit - len(in_flight) if limit is not None else None
        locked: set[str] = set()
        dispatched_ids = {task.id for task in in_flight.values()}
        for task in in_flight.values():
            locked |= self._task_resources(record, task)
        selected: list[TaskRun] = []
        for task in sorted(
            (task for task in run.tasks if task.id not in dispatched_ids and self._is_ready(record, run, task)),
            key=lambda item: -self._task_priority(record, item),
        ):
            if remaining is not None and len(selected) >= remaining:
                break
            resources = self._task_resources(record, task)
            if resources & locked:
                continue
            selected.append(task)
            locked |= resources
        return selected

    def _finalize(self, record: _StoredRun, run: WorkflowRun) -> None:
        if run.status in _TERMINAL_WORKFLOW_STATUSES:
            return
        failed = [task for task in run.tasks if task.status is TaskRunStatus.FAILED]
        unhandled = [task for task in failed if not self._failure_handled(record, run, task)]
        if unhandled:
            record.pause_reason = _PAUSE_REASON_RETRY
            self._transition_workflow(
                run,
                WorkflowRunStatus.PAUSED,
                payload={"reason": _PAUSE_REASON_RETRY, "failed_tasks": [str(task.key) for task in unhandled]},
            )
        elif any(task.status is TaskRunStatus.WAITING_APPROVAL for task in run.tasks):
            if run.status is not WorkflowRunStatus.WAITING_APPROVAL:
                self._transition_workflow(run, WorkflowRunStatus.WAITING_APPROVAL)
        elif all(task.status is TaskRunStatus.SUCCEEDED for task in run.tasks):
            self._transition_workflow(run, WorkflowRunStatus.SUCCEEDED)
        elif all(
            task.status in {TaskRunStatus.SUCCEEDED, TaskRunStatus.FAILED, TaskRunStatus.SKIPPED} for task in run.tasks
        ):
            self._transition_workflow(
                run,
                WorkflowRunStatus.SUCCEEDED,
                payload={
                    "reason": "conditional_branches_resolved",
                    "failed_tasks": [str(task.key) for task in failed],
                    "skipped_tasks": [str(task.key) for task in run.tasks if task.status is TaskRunStatus.SKIPPED],
                },
            )
        elif any(
            task.status is TaskRunStatus.PENDING
            and self._dependencies_satisfied(record, run, task)
            and not self._waits_satisfied(record, task)
            for task in run.tasks
        ):
            waiting = [
                task
                for task in run.tasks
                if task.status is TaskRunStatus.PENDING
                and self._dependencies_satisfied(record, run, task)
                and not self._waits_satisfied(record, task)
            ]
            record.pause_reason = _PAUSE_REASON_EVENTS
            self._transition_workflow(
                run,
                WorkflowRunStatus.PAUSED,
                payload={
                    "reason": _PAUSE_REASON_EVENTS,
                    "waiting_tasks": [str(task.key) for task in waiting],
                },
            )
        else:
            msg = "The ADLC scheduler reached an invalid deadlock."
            raise AdlcRunStateError(msg)

    def _task_priority(self, record: _StoredRun, task: TaskRun) -> int:
        definition = record.definitions.get(str(task.key))
        return definition.priority if definition is not None else 50

    async def _reflect_on_run(self, run: WorkflowRun) -> None:
        """Store the orchestrator's ReflectionReport once a run is terminal (G6).

        Fires for SUCCEEDED and FAILED runs alike (the presentation's
        feedback loop needs both). Best-effort: a missing plugin or a
        failing dispatcher logs and leaves the run untouched.
        """
        if self._reflection_dispatcher is None or run.metadata.get("reflection") is not None:
            return
        try:
            report = await self._reflection_dispatcher(run, run.status.value.lower())
        except Exception as exc:  # noqa: BLE001 - reflection must never break a run
            logger.warning("ADLC reflection dispatcher failed for run %s: %s", run.id, exc)
            return
        if report is None:
            return
        run.metadata["reflection"] = reflection_metadata(report)

    @staticmethod
    def _task_resources(record: _StoredRun, task: TaskRun) -> set[str]:
        definition = record.definitions.get(str(task.key))
        return set(definition.required_resources) if definition is not None else set()

    def _dependency_condition(self, record: _StoredRun, task: TaskRun, index: int) -> str:
        definition = record.definitions.get(str(task.key))
        conditions = definition.dependency_conditions if definition is not None else []
        return conditions[index] if index < len(conditions) else "ON_SUCCESS"

    def _is_ready(self, record: _StoredRun, run: WorkflowRun, task: TaskRun) -> bool:
        # READY tasks are dispatchable so resumed/recovered orphans re-enter the
        # scheduler instead of deadlocking between states.
        if task.status not in {TaskRunStatus.PENDING, TaskRunStatus.READY}:
            return False
        if not (self._dependencies_satisfied(record, run, task) and self._waits_satisfied(record, task)):
            return False
        ready_at = record.retry_ready_at.get(task.id)
        return ready_at is None or utc_now() >= ready_at

    def _dependencies_satisfied(self, record: _StoredRun, run: WorkflowRun, task: TaskRun) -> bool:
        return all(
            self._condition_satisfied(record, run, task, index, dependency)
            for index, dependency in enumerate(
                self._task_by_id(run, dependency_id) for dependency_id in task.dependency_task_run_ids
            )
        )

    @staticmethod
    def _waits_satisfied(record: _StoredRun, task: TaskRun) -> bool:
        definition = record.definitions.get(str(task.key))
        if definition is None:
            return True
        return all(event_name in record.emitted_events for event_name in definition.waits_for)

    def _condition_satisfied(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        index: int,
        dependency: TaskRun,
    ) -> bool:
        condition = self._dependency_condition(record, task, index)
        if condition == "ON_FAILURE":
            return dependency.status is TaskRunStatus.FAILED
        if condition == "ALWAYS":
            return dependency.status in {TaskRunStatus.SUCCEEDED, TaskRunStatus.FAILED}
        if condition == "ON_DONE":
            if dependency.status in {TaskRunStatus.SUCCEEDED, TaskRunStatus.SKIPPED}:
                return True
            return dependency.status is TaskRunStatus.FAILED and self._failure_handled(record, run, dependency)
        return dependency.status is TaskRunStatus.SUCCEEDED

    def _skip_unsatisfiable_tasks(self, record: _StoredRun, run: WorkflowRun) -> None:
        """Mark not-yet-dispatched tasks whose dependency conditions can never be satisfied."""
        while True:
            blocked = [
                task
                for task in run.tasks
                if task.status in {TaskRunStatus.PENDING, TaskRunStatus.READY}
                and any(
                    self._condition_unsatisfiable(record, run, task, index, dependency)
                    for index, dependency in enumerate(
                        self._task_by_id(run, dependency_id) for dependency_id in task.dependency_task_run_ids
                    )
                )
            ]
            if not blocked:
                return
            for task in blocked:
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.SKIPPED,
                    payload={"reason": "dependency_condition_unsatisfied"},
                )

    def _condition_unsatisfiable(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        index: int,
        dependency: TaskRun,
    ) -> bool:
        status = dependency.status
        terminal_unreachable = {TaskRunStatus.SKIPPED, TaskRunStatus.CANCELLED}
        condition = self._dependency_condition(record, task, index)
        if condition == "ON_FAILURE":
            return status is TaskRunStatus.SUCCEEDED or status in terminal_unreachable
        if condition == "ALWAYS":
            return status in terminal_unreachable
        if condition == "ON_DONE":
            # Every reachable outcome satisfies ON_DONE; only CANCELLED can strand it forever.
            return status is TaskRunStatus.CANCELLED
        if status is TaskRunStatus.FAILED:
            # A failed dependency stays retryable until its failure branch resolves.
            return self._failure_handled(record, run, dependency)
        return status in terminal_unreachable

    def _failure_handled(self, record: _StoredRun, run: WorkflowRun, failed_task: TaskRun) -> bool:
        """A failure is handled when an ON_FAILURE branch succeeded on its behalf."""
        return any(
            task.status is TaskRunStatus.SUCCEEDED
            and any(
                dependency_id == failed_task.id and self._dependency_condition(record, task, index) == "ON_FAILURE"
                for index, dependency_id in enumerate(task.dependency_task_run_ids)
            )
            for task in run.tasks
        )

    async def _execute_task(self, record: _StoredRun, task: TaskRun, *, recovery: bool = False) -> None:
        started_at_ns = perf_counter_ns()
        run = record.run
        if record.cancel_requested:
            # A cancellation may land between scheduler selection and coroutine
            # start; cancel_run owns the CANCELLED transitions for those tasks.
            if task.status in _CANCELLABLE_TASK_STATUSES:
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.CANCELLED,
                    payload={"reason": "workflow_cancelled"},
                )
            return
        try:
            if recovery:
                definition = record.definitions[str(task.key)]
                configured_timeout = task.request.constraints.get("timeout_ms") if task.request is not None else None
                timeout_ms = (
                    configured_timeout if isinstance(configured_timeout, int) and configured_timeout > 0 else 1000
                )
            else:
                definition, timeout_ms = self._prepare_attempt(record, task)
        except Exception as exc:
            self._emit_dispatch_observation(run, task, started_at_ns=started_at_ns, failure=exc)
            raise
        record.retry_ready_at.pop(task.id, None)
        if task.executor.service == "control:approval":
            self._execute_approval_gate(record, run, task, definition)
            self._emit_dispatch_observation(run, task, started_at_ns=started_at_ns)
            return
        task.worker_id = _IN_PROCESS_WORKER_ID
        task.deadline_at = utc_now() + timedelta(milliseconds=timeout_ms)

        async def on_state_change(status: TaskRunStatus, result: TaskResult | None) -> None:
            self._on_executor_state(record, run, task, definition, status, result)
            await self._persist_safely(record, required=True)

        if self._persistence is not None:
            # The frozen request, attempt identity and idempotency key must be
            # durable BEFORE any external dispatch so a restart replays the same
            # attempt instead of creating a replacement execution.
            await self._persist_safely(record, required=True)

        dispatch = asyncio.create_task(
            self._observe_attempt(record, task, on_state_change)
            if recovery
            else self._executor.execute(task.request, on_state_change)
        )
        timed_out = False
        try:
            while True:
                remaining_ms = int((task.deadline_at - utc_now()).total_seconds() * 1000)
                try:
                    await asyncio.wait_for(asyncio.shield(dispatch), timeout=max(remaining_ms, 1) / 1000)
                    break
                except asyncio.TimeoutError:
                    if task.status is TaskRunStatus.WAITING_APPROVAL:
                        # Human gates are unbounded by design; renew the lease
                        # while the attempt waits for a decision.
                        task.deadline_at = utc_now() + timedelta(milliseconds=timeout_ms)
                        continue
                    timed_out = True
                    break
        except asyncio.CancelledError:
            # Deliberate cancellation (cancel_run / teardown); its owner transitions the task.
            raise
        except Exception as exc:
            self._emit_dispatch_observation(run, task, started_at_ns=started_at_ns, failure=exc)
            raise
        finally:
            task.deadline_at = None
            if not dispatch.done():
                dispatch.cancel()
            await asyncio.gather(dispatch, return_exceptions=True)
        if timed_out:
            self._complete_deadline_timeout(record, run, task, definition, started_at_ns=started_at_ns)
            return
        self._emit_dispatch_observation(run, task, started_at_ns=started_at_ns)

    def _complete_deadline_timeout(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        definition: AdlcTaskDefinition,
        *,
        started_at_ns: int,
    ) -> None:
        """Convert a coordinator-level deadline breach into a typed failed result."""
        completed_at = utc_now()
        error = ServiceError(
            error_id=uuid4(),
            code="TASK_DEADLINE_EXCEEDED",
            category="TIMEOUT",
            message=(
                "The task attempt exceeded the coordinator deadline before the executor reported a terminal result."
            ),
            retryable=True,
            service="adlc-run-coordinator",
            details={"executor_service": task.executor.service},
            correlation_id=f"run-{run.id}/task-{task.id}",
            occurred_at=completed_at,
        )
        result = TaskResult(
            request_id=task.request.request_id if task.request else uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id or uuid4(),
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=error,
            metrics=TaskMetrics(
                duration_ms=int(elapsed_milliseconds(started_at_ns)),
                custom={"coordinator_timeout": True},
            ),
            started_at=completed_at,
            completed_at=completed_at,
            metadata={"coordinator_deadline": True},
        )
        self._emit_dispatch_observation(run, task, started_at_ns=started_at_ns, failure=error)
        self._handle_task_failure(record, run, task, definition=definition, result=result)

    def _prepare_attempt(self, record: _StoredRun, task: TaskRun) -> tuple[AdlcTaskDefinition, int]:
        """Build the TaskRequest for one attempt and return its definition and deadline."""
        run = record.run
        definition = record.definitions[str(task.key)]
        attempt_id = uuid4()
        task.current_attempt_id = attempt_id
        delay_ms = definition.delay_ms if definition.delay_ms is not None else record.delay_ms
        named_inputs = dict(definition.direct_inputs)
        try:
            named_inputs = resolve_templates(named_inputs, roots=self._template_roots(run))
        except TemplateResolutionError as exc:
            msg = f"INPUT_RESOLUTION_FAILED: {exc}"
            raise AdlcRunStateError(msg) from exc
        resolved_bindings = self._resolve_input_bindings(run, definition)
        for binding in resolved_bindings:
            target_input = binding["target_input"]
            if binding.get("target_multiple") is True:
                current_value = named_inputs.get(target_input)
                values = list(current_value) if isinstance(current_value, list) else []
                if current_value is not None and not isinstance(current_value, list):
                    values.append(current_value)
                values.append(binding["value"])
                named_inputs[target_input] = values
            else:
                named_inputs[target_input] = binding["value"]
        dependency_tasks = [self._task_by_id(run, dependency_id) for dependency_id in task.dependency_task_run_ids]
        artifact_refs = [
            self._artifact_ref(artifact) for dependency in dependency_tasks for artifact in dependency.artifacts
        ]
        configured_context = definition.request_context
        configured_artifact_refs = configured_context.get("artifact_refs", [])
        configured_memory_refs = configured_context.get("memory_refs", [])
        configured_variables = configured_context.get("variables", {})
        mock_execution = task.executor.service in _MOCK_EXECUTOR_SERVICES
        request_context = {
            **configured_context,
            "artifact_refs": [
                *(configured_artifact_refs if isinstance(configured_artifact_refs, list) else []),
                *artifact_refs,
            ],
            "memory_refs": configured_memory_refs if isinstance(configured_memory_refs, list) else [],
            "variables": {
                "mock": mock_execution,
                **(configured_variables if isinstance(configured_variables, dict) else {}),
            },
            "upstream_results": [
                {
                    "task_run_id": str(dependency.id),
                    "plan_task_id": (
                        str(dependency.plan_traceability.plan_task_id)
                        if dependency.plan_traceability is not None
                        else None
                    ),
                    "output": dependency.result.output if dependency.result is not None else None,
                }
                for dependency in dependency_tasks
            ],
            "resolved_input_bindings": resolved_bindings,
            "workflow_name": run.name,
            "workflow_run_number": run.run_number,
        }
        constraints = {
            "timeout_ms": max(1000, delay_ms + 500),
            "priority": definition.priority,
            "max_attempts": 2,
            **definition.constraints,
        }
        if task.executor.service in {TASK_LOOP_MOCK_SERVICE, *_DURABLE_LOOP_SERVICES}:
            request_context["task_loop_iteration"] = task.retry_count + 1
        metadata = {"mock": mock_execution, "flow_id": str(run.flow_id), **definition.request_metadata}
        if task.executor.service in _CONTRACT_LOOP_SERVICES:
            # Coordinator ownership always replaces client/workflow metadata before persistence/dispatch.
            metadata["coding_agent_owner_id"] = record.owner_id
        trace_context: dict[str, str] = {}
        if definition.plan_traceability is not None:
            metadata["plan_traceability"] = definition.plan_traceability.model_dump(mode="json")
            trace_context = {
                "execution_plan_id": str(definition.plan_traceability.execution_plan_id),
                "plan_task_id": str(definition.plan_traceability.plan_task_id),
                "source_workflow_stage_id": str(definition.plan_traceability.source_workflow_stage_id),
                "resolved_node_digest": definition.plan_traceability.resolved_node_digest,
            }
        task.request = TaskRequest(
            request_id=uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
            task_definition_id=task.task_definition_id,
            task_type=task.task_type,
            name=task.name,
            executor=task.executor,
            input={
                "taskKey": str(task.key),
                "objective": definition.objective,
                "namedInputs": named_inputs,
                "inputBindings": definition.input_bindings,
                "simulateFailure": task.simulate_failure,
                "delayMs": delay_ms,
                "predeterminedResult": definition.predetermined_output,
                "artifact": {
                    "kind": definition.artifact.kind,
                    "name": definition.artifact.name,
                    "mediaType": definition.artifact.media_type,
                    "content": definition.artifact.content,
                },
            },
            context=request_context,
            dependency_task_run_ids=task.dependency_task_run_ids,
            constraints=constraints,
            idempotency_key=f"{run.id}:{task.id}:{attempt_id}",
            requested_at=utc_now(),
            trace_context=trace_context,
            metadata=metadata,
        )

        timeout_ms = constraints.get("timeout_ms")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
            timeout_ms = max(1000, delay_ms + 500)
        return definition, timeout_ms

    def _execute_approval_gate(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        definition: AdlcTaskDefinition,
    ) -> None:
        """Run a control-plane approval gate without dispatching to an executor."""
        if definition.approval_gate is not GateType.ACTION:
            message = "A control approval task requires an ACTION approval gate."
            raise AdlcRunStateError(message)
        # Approval is a control-plane gate, not an agent/service dispatch.
        self._transition_task(run, task, TaskRunStatus.RUNNING)
        now = utc_now()
        attempt_id = task.current_attempt_id or uuid4()
        pending_result = TaskResult(
            request_id=task.request.request_id if task.request else uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=attempt_id,
            status=TaskResultStatus.SUCCEEDED,
            output={"outputs": {}},
            artifacts=[],
            error=None,
            metrics=TaskMetrics(duration_ms=0),
            started_at=now,
            completed_at=now,
            metadata={"control_plane": True, "mock": False},
        )
        self._on_executor_state(record, run, task, definition, TaskRunStatus.SUCCEEDED, pending_result)

    def _emit_dispatch_observation(
        self,
        run: WorkflowRun,
        task: TaskRun,
        *,
        started_at_ns: int,
        failure: Exception | None = None,
    ) -> None:
        result = task.pending_result or task.result
        error_code: str | None = None
        if failure is not None:
            outcome = observation_outcome_for_exception(failure)
            error_code = observation_error_code(failure, "TASK_DISPATCH_FAILED")
        elif result is None:
            outcome = AdlcObservationOutcome.FAILED
            error_code = "TASK_RESULT_MISSING"
        elif result.status is TaskResultStatus.SUCCEEDED:
            outcome = AdlcObservationOutcome.SUCCEEDED
        elif result.status is TaskResultStatus.CANCELLED:
            outcome = AdlcObservationOutcome.CANCELLED
        elif result.error is not None:
            outcome = observation_outcome_for_exception(result.error)
            error_code = observation_error_code(result.error, "TASK_EXECUTION_FAILED")
        else:
            outcome = AdlcObservationOutcome.FAILED
            error_code = "TASK_EXECUTION_FAILED"

        trace = task.plan_traceability
        record_observation_safely(
            self._observability,
            event_type=AdlcObservationType.TASK_DISPATCH_COMPLETED,
            outcome=outcome,
            duration_ms=elapsed_milliseconds(started_at_ns),
            error_code=error_code,
            workflow_definition_id=run.flow_id,
            execution_plan_id=trace.execution_plan_id if trace is not None else run.execution_plan_id,
            workflow_run_id=run.id,
            plan_task_id=trace.plan_task_id if trace is not None else None,
            source_workflow_stage_id=trace.source_workflow_stage_id if trace is not None else None,
            resolved_node_spec_id=trace.resolved_node_spec_id if trace is not None else None,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id,
            package_id=trace.package_id if trace is not None else None,
            package_version=trace.package_version if trace is not None else None,
            package_content_digest=trace.package_content_digest if trace is not None else None,
            resolved_node_digest=trace.resolved_node_digest if trace is not None else None,
            executor_service=task.executor.service,
            artifact_count=len(result.artifacts) if result is not None else 0,
            attempt_number=task.retry_count + 1,
        )

    def _source_patch_evidence_payload(self, artifact: Artifact) -> dict[str, Any] | None:
        """Project a SOURCE_PATCH artifact into a patch-evidence payload.

        Returns ``None`` when the payload cache no longer holds the diff; the
        artifact payload store remains the payload cache of record.
        """
        try:
            payload = self._artifact_payloads.read(artifact)
            snapshot = SourcePatchSnapshot.model_validate_json(payload)
        except (ArtifactPayloadUnavailableError, ValidationError):
            return None
        return {
            "files": [
                {
                    "file": item.file,
                    "patch": item.patch,
                    "additions": item.additions,
                    "deletions": item.deletions,
                }
                for item in snapshot.files
            ],
            "artifact_id": str(artifact.artifact_id),
        }

    def _mirror_task_evidence(self, run: WorkflowRun, task: TaskRun, result: TaskResult) -> None:
        """Mirror one terminal task result into the Evidence Plane (best-effort).

        Emits a metric evidence item summarizing the outcome plus one patch
        evidence item per SOURCE_PATCH artifact whose diff payload is still
        cached. Never raises: observability must not break orchestration.
        """
        if self._evidence_plane is None:
            return
        submitted_at = utc_now()
        _submit_evidence_safely(
            self._evidence_plane,
            Evidence(
                evidence_type=EvidenceType.METRIC,
                producer=task.executor.service,
                submitted_at=submitted_at,
                payload={
                    "event": "task_completed",
                    "status": result.status.value,
                    "artifact_count": len(result.artifacts),
                    **({"error_code": result.error.code} if result.error is not None else {}),
                },
                workflow_run_id=run.id,
                task_run_id=task.id,
                attempt_id=task.current_attempt_id,
            ),
        )
        for artifact in result.artifacts:
            if artifact.kind != "SOURCE_PATCH":
                continue
            patch_payload = self._source_patch_evidence_payload(artifact)
            if patch_payload is None:
                continue
            _submit_evidence_safely(
                self._evidence_plane,
                Evidence(
                    evidence_type=EvidenceType.PATCH,
                    producer=artifact.producer or task.executor.service,
                    submitted_at=submitted_at,
                    payload=patch_payload,
                    workflow_run_id=run.id,
                    task_run_id=task.id,
                    attempt_id=task.current_attempt_id,
                ),
            )

    def _on_executor_state(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        definition: AdlcTaskDefinition,
        status: TaskRunStatus,
        result: TaskResult | None,
    ) -> None:
        if status is TaskRunStatus.RUNNING:
            if task.status is not TaskRunStatus.RUNNING:
                self._transition_task(run, task, status)
            if run.status is WorkflowRunStatus.WAITING_APPROVAL:
                payload = {"reason": "harness_interaction_resolved"}
                self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload=payload)
                self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload=payload)
            return
        if status is TaskRunStatus.WAITING_APPROVAL:
            if task.status is not TaskRunStatus.WAITING_APPROVAL:
                self._transition_task(
                    run,
                    task,
                    status,
                    payload={"reason": "harness_interaction_or_manual_submission"},
                )
            if run.status is WorkflowRunStatus.RUNNING:
                self._transition_workflow(
                    run,
                    WorkflowRunStatus.WAITING_APPROVAL,
                    payload={"reason": "harness_interaction_or_manual_submission"},
                )
            return
        if result is None:
            msg = f"The executor emitted {status.value} without a TaskResult."
            raise AdlcRunStateError(msg)

        if status is TaskRunStatus.SUCCEEDED and (
            task.executor.operation == "contract-coding" or task.executor.service in _CONTRACT_LOOP_SERVICES
        ):
            from langflow.adlc.contract_execution import validate_task_outcome
            from langflow.adlc.contract_repository import ContractError

            try:
                if task.executor.service in _CONTRACT_LOOP_SERVICES:
                    validate = getattr(self._executor, "validate_result", None)
                    if not callable(validate):
                        code = "CODING_AGENT_CONTRACT_EVIDENCE_UNAVAILABLE"
                        raise ContractError(code, 422)
                    validate(task.request, result, owner_id=self._runs[run.id].owner_id)
                else:
                    validate_task_outcome(
                        task.request, result, owner_id=self._runs[run.id].owner_id, trace=task.plan_traceability
                    )
            except ContractError as exc:
                status = TaskRunStatus.FAILED
                result = result.model_copy(
                    update={
                        "status": TaskResultStatus.FAILED,
                        "output": None,
                        "artifacts": [],
                        "error": ServiceError(
                            error_id=uuid4(),
                            code=exc.code,
                            category="VALIDATION",
                            retryable=False,
                            message="Contract execution evidence did not match the frozen approved attempt.",
                            service="adlc-run-coordinator",
                            occurred_at=utc_now(),
                        ),
                    }
                )

        result = self._with_plan_traceability(result, definition)
        task.artifacts = [artifact.model_copy(deep=True) for artifact in result.artifacts]
        if status is TaskRunStatus.SUCCEEDED:
            gated = self._apply_quality_gate(record, run, task, definition, result)
            if gated is None:
                # The independent quality gate rejected the attempt and its
                # retry policy scheduled another attempt; this flow is done.
                return
            result = gated
            if result.status is TaskResultStatus.FAILED:
                # The gate rejected the succeeded attempt without retry
                # budget: continue through the standard failure path.
                status = TaskRunStatus.FAILED
        if status is TaskRunStatus.SUCCEEDED and definition.approval_gate in {GateType.ACTION, GateType.AFTER_TASK}:
            task.pending_result = result
            approval = self._create_approval(run, task, definition)
            if task.status is not TaskRunStatus.WAITING_APPROVAL:
                self._transition_task(
                    run,
                    task,
                    TaskRunStatus.WAITING_APPROVAL,
                    payload={"approval_request_id": str(approval.approval_request_id)},
                )
            return

        if status is TaskRunStatus.FAILED and self._should_auto_retry(task, result):
            self._begin_auto_retry(record, run, task, result)
            return

        task.result = result
        self._transition_task(
            run,
            task,
            status,
            payload={
                "request_id": str(result.request_id),
                "artifact_ids": [str(artifact.artifact_id) for artifact in result.artifacts],
                **({"error_code": result.error.code} if result.error else {}),
            },
        )
        self._mirror_task_evidence(run, task, result)
        if run.status is WorkflowRunStatus.WAITING_APPROVAL:
            # A terminal attempt resolves this task's blocking interaction; the
            # workflow projection must not stay WAITING_APPROVAL when progress
            # was made. _finalize re-enters WAITING_APPROVAL if approvals still
            # block the sole path forward.
            payload = {"reason": "harness_interaction_resolved"}
            self._transition_workflow(run, WorkflowRunStatus.QUEUED, payload=payload)
            self._transition_workflow(run, WorkflowRunStatus.RUNNING, payload=payload)
        for event_name in definition.emits_events:
            self._emit_runtime_event(record, run, event_name, {"source_task_run_id": str(task.id)})

    def _apply_quality_gate(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        definition: AdlcTaskDefinition,
        result: TaskResult,
    ) -> TaskResult | None:
        """Judge a succeeded attempt with the independent quality gate (G6).

        The verdict is scored from EVIDENCE (artifacts, Evidence Plane
        items, testing-adapter outcome) against the acceptance criteria
        declared on the task definition — never from the executor's
        self-reported summary. Returns the result to continue with
        (verdict attached to its metadata), or ``None`` when the gate
        consumed the attempt by scheduling a policy retry. When the
        retry budget is exhausted the returned result is converted to a
        terminal FAILED result carrying ``QUALITY_GATE_FAILED``; the
        standard failure path then escalates (existing PAUSED behavior).
        """
        criteria = self._declared_acceptance_criteria(task, definition)
        if not criteria:
            return result
        mock_execution = task.request.metadata.get("mock") is True if task.request is not None else False
        if not self._quality_gate_policy.applies_to_task(
            task_type=task.task_type,
            executor_service=task.executor.service,
            mock_execution=mock_execution,
        ):
            return result
        human_gate_required = definition.approval_gate in {GateType.ACTION, GateType.AFTER_TASK}
        verdict = evaluate_task_quality(
            run,
            task,
            criteria=criteria,
            result=result,
            evidence=self._task_evidence(run, task),
            human_gate_required=human_gate_required,
        )
        gated_metadata = {**result.metadata, "quality_gate": verdict.model_dump(mode="json")}
        if verdict.decision is QualityGateDecision.PASS:
            return result.model_copy(update={"metadata": gated_metadata})
        retry_available = task.retry_count + 1 < self._max_attempts(task) and task.executor.service != "control:approval"
        error = ServiceError(
            error_id=uuid4(),
            code="QUALITY_GATE_FAILED",
            category="VALIDATION",
            message="The independent quality gate rejected the task result against its acceptance criteria.",
            retryable=retry_available,
            service="adlc-quality-gate",
            details={"decision": verdict.decision.value, "reasons": list(verdict.reasons)},
            correlation_id=f"run-{run.id}/task-{task.id}",
            occurred_at=utc_now(),
        )
        failed_result = result.model_copy(
            update={
                "status": TaskResultStatus.FAILED,
                "output": None,
                "error": error,
                "metadata": gated_metadata,
            }
        )
        if retry_available:
            self._begin_auto_retry(record, run, task, failed_result)
            return None
        logger.warning(
            "ADLC quality gate rejected task '%s' in run %s after exhausting retries: %s",
            task.key,
            run.id,
            "; ".join(verdict.reasons) or verdict.decision.value,
        )
        return failed_result

    @staticmethod
    def _declared_acceptance_criteria(
        task: TaskRun,
        definition: AdlcTaskDefinition | None,
    ) -> list[TaskCriterion] | None:
        """Parse declared acceptance criteria; None (or empty) disables the gate."""
        sources: list[Any] = []
        if task.request is not None and isinstance(task.request.constraints, dict):
            sources.append(task.request.constraints.get("acceptance_criteria"))
        if definition is not None and isinstance(definition.constraints, dict):
            sources.append(definition.constraints.get("acceptance_criteria"))
        raw = next((item for item in sources if isinstance(item, list) and item), None)
        if raw is None:
            return None
        criteria: list[TaskCriterion] = []
        for entry in raw:
            if isinstance(entry, str) and entry.strip():
                criteria.append(TaskCriterion(description=entry.strip()))
            elif isinstance(entry, dict) and str(entry.get("description", "")).strip():
                criteria.append(
                    TaskCriterion.model_validate(
                        {
                            "description": str(entry["description"]).strip(),
                            "verification": entry.get("verification", "HUMAN"),
                        }
                    )
                )
        return criteria or None

    def _task_evidence(self, run: WorkflowRun, task: TaskRun) -> list[Evidence]:
        """Query the Evidence Plane for this task's items (best-effort)."""
        if self._evidence_plane is None:
            return []
        try:
            return list(self._evidence_plane.query(EvidenceQuery(workflow_run_id=run.id, task_run_id=task.id)))
        except Exception:  # noqa: BLE001 - evidence is advisory for the gate
            return []

    def _should_auto_retry(self, task: TaskRun, result: TaskResult) -> bool:
        """Automatic retry applies only to retryable failures with remaining attempt budget."""
        if result.status is not TaskResultStatus.FAILED:
            return False
        if task.status is not TaskRunStatus.RUNNING:
            return False
        if task.executor.service == "control:approval":
            return False
        error = result.error
        if error is None or not error.retryable:
            return False
        if error.code.startswith(("ADLC_RECOVERY_", "HARNESS_RECOVERY_")):
            return False
        return task.retry_count + 1 < self._max_attempts(task)

    def _begin_auto_retry(self, record: _StoredRun, run: WorkflowRun, task: TaskRun, result: TaskResult) -> None:
        """Reopen the same TaskRun for another attempt after its backoff elapses."""
        backoff_ms = self._retry_backoff_ms(task)
        task.retry_count += 1
        task.simulate_failure = False
        task.current_attempt_id = None
        task.request = None
        task.result = None
        task.pending_result = None
        task.completed_at = None
        task.deadline_at = None
        task.worker_id = None
        record.retry_ready_at[task.id] = utc_now() + timedelta(milliseconds=backoff_ms)
        self._transition_task(
            run,
            task,
            TaskRunStatus.READY,
            event_type="task_run.retry_scheduled",
            payload={
                "retry_count": task.retry_count,
                "backoff_ms": backoff_ms,
                "retry_ready_at": record.retry_ready_at[task.id].isoformat(),
                "error_code": result.error.code if result.error else None,
            },
        )

    def _retry_backoff_ms(self, task: TaskRun) -> int:
        """Exponential backoff with the configured base delay, capped for safety.

        Computed before the retry counter is incremented: the first retry uses
        the base delay, the second doubles it, and so on.
        """
        base_ms = 500
        if task.request and task.request.constraints:
            configured = task.request.constraints.get("retry_backoff_ms")
            if isinstance(configured, int) and not isinstance(configured, bool) and configured >= 0:
                base_ms = configured
        return min(base_ms * (2 ** max(0, task.retry_count)), _MAX_RETRY_BACKOFF_MS)

    def _max_attempts(self, task: TaskRun) -> int:
        if task.request and task.request.constraints:
            configured = task.request.constraints.get("max_attempts")
            if isinstance(configured, int) and not isinstance(configured, bool) and configured >= 1:
                return configured
        return _DEFAULT_MAX_ATTEMPTS

    def _handle_task_failure(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        *,
        definition: AdlcTaskDefinition | None,
        result: TaskResult,
    ) -> None:
        """Funnel timeout and crashed-attempt outcomes through the standard failure path."""
        if task.status in _TERMINAL_TASK_STATUSES:
            return
        resolved_definition = definition if definition is not None else record.definitions.get(str(task.key))
        if resolved_definition is None:
            self._transition_task(
                run,
                task,
                TaskRunStatus.FAILED,
                payload={
                    "error_code": result.error.code if result.error else "TASK_EXECUTION_FAILED",
                    "reason": "definition_unavailable",
                },
            )
            return
        self._on_executor_state(record, run, task, resolved_definition, TaskRunStatus.FAILED, result)

    def _handle_task_failure_from_exception(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        *,
        exception: Exception | None = None,
    ) -> None:
        """Synthesize a typed failed result for attempts that ended without one."""
        completed_at = utc_now()
        error = ServiceError(
            error_id=uuid4(),
            code="TASK_EXECUTION_CRASHED",
            category="INTERNAL",
            message="The task attempt ended without a terminal TaskResult.",
            retryable=True,
            service="adlc-run-coordinator",
            details={"exception_type": type(exception).__name__} if exception is not None else {},
            correlation_id=f"run-{run.id}/task-{task.id}",
            occurred_at=completed_at,
        )
        result = TaskResult(
            request_id=task.request.request_id if task.request else uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id or uuid4(),
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=error,
            metrics=None,
            started_at=completed_at,
            completed_at=completed_at,
            metadata={"crash_synthesized": True},
        )
        self._handle_task_failure(
            record,
            run,
            task,
            definition=record.definitions.get(str(task.key)),
            result=result,
        )

    def _create_approval(
        self,
        run: WorkflowRun,
        task: TaskRun,
        definition: AdlcTaskDefinition,
    ) -> ApprovalRequest:
        if task.current_attempt_id is None:
            msg = "Cannot create approval without a task attempt."
            raise AdlcRunStateError(msg)
        if any(item.status is ApprovalStatus.PENDING for item in run.approval_requests):
            msg = "Only one pending blocking approval is supported per run."
            raise AdlcRunStateError(msg)
        reviewed_artifacts = (
            [
                artifact
                for dependency_id in task.dependency_task_run_ids
                for artifact in self._task_by_id(run, dependency_id).artifacts
            ]
            if task.executor.service == "control:approval"
            else task.artifacts
        )
        now = utc_now()
        ttl_seconds = definition.constraints.get("approval_ttl_seconds")
        native_sources = [
            self._task_by_id(run, dependency_id)
            for dependency_id in task.dependency_task_run_ids
            if self._task_by_id(run, dependency_id).executor.service == HARNESS_WORKFLOW_SERVICE
        ]
        native_review = {}
        if task.executor.service == "control:approval" and native_sources:
            if len(native_sources) != 1 or not native_sources[0].result:
                code = "HARNESS_WORKFLOW_REVIEW_AMBIGUOUS"
                raise AdlcRunStateError(code)
            review = native_sources[0].result.output["outputs"].get("review")
            if not isinstance(review, dict) or review.get("kind") not in {"PLAN", "COMMIT"}:
                code = "HARNESS_WORKFLOW_REVIEW_MISSING"
                raise AdlcRunStateError(code)
            native_review = {
                "harness_workflow_review": review,
                "harness_workflow_digest": harness_digest(review),
                "harness_source_task_id": str(native_sources[0].id),
            }
        expires_at = (
            now + timedelta(seconds=ttl_seconds)
            if isinstance(ttl_seconds, (int, float)) and not isinstance(ttl_seconds, bool) and ttl_seconds > 0
            else None
        )
        approval = ApprovalRequest(
            approval_request_id=uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id,
            gate_type=definition.approval_gate or GateType.AFTER_TASK,
            status=ApprovalStatus.PENDING,
            title=f"Approve {task.name}",
            requested_by=SYSTEM_ACTOR,
            required_role=definition.approval_required_role or "maintainer",
            reviewer_ids=[],
            actions=[
                ApprovalAction(action_id="approve", label="Approve", effect="APPROVE", comment_required=False),
                ApprovalAction(action_id="reject", label="Reject", effect="REJECT", comment_required=False),
            ],
            context=ApprovalContext(
                summary=definition.approval_message or f"Task '{task.name}' is waiting for approval.",
                risk=(
                    "This vertical slice executes deterministic mock data only."
                    if task.request and task.request.metadata.get("mock") is True
                    else None
                ),
                requested_action="Approve or reject the task result.",
                artifact_refs=[self._artifact_ref(artifact) for artifact in reviewed_artifacts],
                payload={
                    "task_key": str(task.key),
                    **(
                        {
                            "artifact_digests": [
                                {
                                    "artifact_id": str(artifact.artifact_id),
                                    "digest": self._artifact_digest(artifact),
                                }
                                for artifact in reviewed_artifacts
                            ]
                        }
                        if reviewed_artifacts
                        else {}
                    ),
                    **native_review,
                    **(
                        {
                            "reviewed_candidates": [
                                {
                                    "task_run_id": str(artifact.task_run_id),
                                    "artifact_id": str(artifact.artifact_id),
                                    "candidate_id": artifact.metadata.get("candidate_id"),
                                    "candidate_digest": artifact.metadata["candidate_digest"],
                                    "iteration": artifact.metadata.get("iteration"),
                                }
                                for artifact in reviewed_artifacts
                                if artifact.kind == "SOURCE_PATCH" and artifact.producer in _DURABLE_LOOP_SERVICES
                            ]
                        }
                        if any(artifact.producer in _DURABLE_LOOP_SERVICES for artifact in reviewed_artifacts)
                        else {}
                    ),
                },
            ),
            decision=None,
            created_at=now,
            expires_at=expires_at,
            metadata={
                "mock": task.request.metadata.get("mock") is True if task.request else False,
                **(
                    {"plan_traceability": definition.plan_traceability.model_dump(mode="json")}
                    if definition.plan_traceability is not None
                    else {}
                ),
            },
        )
        run.approval_requests.append(approval)
        self._emit_approval_event(run, approval, previous_status=None, event_type="approval_request.created")
        self._notify(
            AdlcNotificationKind.APPROVAL_REQUIRED,
            run,
            task_run_id=task.id,
            approval_request_id=approval.approval_request_id,
            message=f"Approval required for task '{task.name}' in run '{run.name}'.",
            metadata={"gate_type": approval.gate_type.value, "required_role": approval.required_role},
        )
        return approval

    def _expire_approval(self, record: _StoredRun, approval: ApprovalRequest, now: datetime) -> None:
        """Apply the frozen-machine expiry transitions for one overdue approval."""
        run = record.run
        approval.status = ApprovalStatus.EXPIRED
        self._emit_approval_event(
            run,
            approval,
            previous_status=ApprovalStatus.PENDING,
            event_type="approval_request.expired",
        )
        task = self._task_by_id(run, approval.task_run_id)
        completed_at = now
        error = ServiceError(
            error_id=uuid4(),
            code=_APPROVAL_EXPIRED_ERROR_CODE,
            category="TIMEOUT",
            message=f"Approval '{approval.title}' expired before a decision was recorded.",
            retryable=False,
            service="control:approval",
            occurred_at=completed_at,
            details={"approval_request_id": str(approval.approval_request_id)},
        )
        task.result = TaskResult(
            request_id=task.request.request_id if task.request else uuid4(),
            workflow_run_id=run.id,
            task_run_id=task.id,
            attempt_id=task.current_attempt_id or uuid4(),
            status=TaskResultStatus.FAILED,
            output=None,
            artifacts=[],
            error=error,
            metrics=None,
            started_at=completed_at,
            completed_at=completed_at,
            metadata={"approval_expired": True},
        )
        task.pending_result = None
        task.completed_at = completed_at
        if task.status is TaskRunStatus.WAITING_APPROVAL:
            self._transition_task(run, task, TaskRunStatus.FAILED, payload={"reason": "approval_expired"})
        self._mirror_task_evidence(run, task, task.result)
        if run.status is WorkflowRunStatus.WAITING_APPROVAL:
            self._transition_workflow(
                run,
                WorkflowRunStatus.FAILED,
                payload={"reason": _PAUSE_REASON_APPROVAL_EXPIRED},
            )
        self._notify(
            AdlcNotificationKind.APPROVAL_EXPIRED,
            run,
            task_run_id=task.id,
            approval_request_id=approval.approval_request_id,
            message=f"Approval '{approval.title}' expired without a decision.",
            metadata={"error_code": _APPROVAL_EXPIRED_ERROR_CODE},
        )

    async def _run_approval_sweeper(self, interval_seconds: float) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.expire_due_approvals()
                await self.check_run_slas()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the approval sweep must survive transient infrastructure failures.
                with contextlib.suppress(Exception):
                    logger.warning("adlc.approval_sweeper.tick_failed", exc_info=True)

    def _notify(
        self,
        kind: AdlcNotificationKind,
        run: WorkflowRun,
        *,
        message: str,
        task_run_id: UUID | None = None,
        approval_request_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Deliver one notification without ever breaking the coordinated path."""
        try:
            self._notifications.notify(
                AdlcNotification(
                    kind=kind,
                    workflow_run_id=run.id,
                    task_run_id=task_run_id,
                    approval_request_id=approval_request_id,
                    message=message,
                    metadata=dict(metadata or {}),
                )
            )
        except Exception:  # noqa: BLE001 - notification delivery must not break coordination.
            with contextlib.suppress(Exception):
                logger.warning("adlc.notification.emit_failed", kind=kind.value, workflow_run_id=str(run.id))

    @staticmethod
    def _with_plan_traceability(result: TaskResult, definition: AdlcTaskDefinition) -> TaskResult:
        trace = definition.plan_traceability
        if trace is None:
            return result
        trace_payload = trace.model_dump(mode="json")
        artifacts = [
            artifact.model_copy(
                update={"metadata": {**artifact.metadata, "plan_traceability": trace_payload}},
                deep=True,
            )
            for artifact in result.artifacts
        ]
        return result.model_copy(
            update={
                "artifacts": artifacts,
                "metadata": {**result.metadata, "plan_traceability": trace_payload},
            },
            deep=True,
        )

    def _template_roots(self, run: WorkflowRun) -> dict[str, Any]:
        """Build the strict template resolution roots for one dispatch pass."""
        return {
            "run": {
                "id": str(run.id),
                "name": run.name,
                "run_number": run.run_number,
                "workflow_key": run.workflow_key,
                "status": run.status.value,
            },
            "task": {
                str(task.key): {
                    "status": task.status.value,
                    "output": task.result.output if task.result is not None else None,
                }
                for task in run.tasks
            },
        }

    @staticmethod
    def _resolve_input_bindings(run: WorkflowRun, definition: AdlcTaskDefinition) -> list[dict]:
        resolved: list[dict] = []
        for binding in definition.input_bindings:
            source_plan_task_id = str(binding.get("source_plan_task_id", ""))
            source_task = next(
                (
                    task
                    for task in run.tasks
                    if task.plan_traceability is not None
                    and str(task.plan_traceability.plan_task_id) == source_plan_task_id
                ),
                None,
            )
            if source_task is None or source_task.result is None:
                message = f"Input binding source plan task {source_plan_task_id} has no completed runtime result."
                raise AdlcRunStateError(message)
            source_output = str(binding.get("source_output", ""))
            output = source_task.result.output
            value = output
            if isinstance(output, dict):
                outputs = output.get("outputs")
                if isinstance(outputs, dict) and source_output in outputs:
                    value = outputs[source_output]
                elif source_output in output:
                    value = output[source_output]
            resolved.append(
                {
                    **binding,
                    "source_task_run_id": str(source_task.id),
                    "value": value,
                }
            )
        return resolved

    @staticmethod
    def _artifact_ref(artifact: Artifact) -> dict[str, str]:
        return {
            "artifact_id": str(artifact.artifact_id),
            "name": artifact.name,
            "media_type": artifact.media_type,
            "uri": artifact.uri,
        }

    @staticmethod
    def _artifact_digest(artifact: Artifact) -> str:
        """Content digest pinning an artifact revision for the human gate."""
        return f"{artifact.checksum.algorithm.lower()}:{artifact.checksum.value}"

    def _verify_approval_artifact_digests(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        task: TaskRun,
        approval: ApprovalRequest,
    ) -> None:
        """Human gate version pinning (G6).

        The pending approval froze the digest of every artifact the
        reviewer was shown. If any of those artifacts has since changed,
        the approval is refused: the human must re-review the new
        revision, never rubber-stamp a stale decision.
        """
        pinned = approval.context.payload.get("artifact_digests")
        if not isinstance(pinned, list) or not pinned:
            return
        reviewed = (
            [
                artifact
                for dependency_id in task.dependency_task_run_ids
                for artifact in self._task_by_id(run, dependency_id).artifacts
            ]
            if task.executor.service == "control:approval"
            else task.artifacts
        )
        current = {str(artifact.artifact_id): self._artifact_digest(artifact) for artifact in reviewed}
        for entry in pinned:
            if not isinstance(entry, dict):
                continue
            artifact_id = str(entry.get("artifact_id", ""))
            pinned_digest = entry.get("digest")
            if current.get(artifact_id) != pinned_digest:
                self._emit_runtime_event(
                    record,
                    run,
                    "approval_request.artifact_digest_mismatch",
                    {
                        "approval_request_id": str(approval.approval_request_id),
                        "artifact_id": artifact_id,
                        "pinned_digest": pinned_digest,
                        "current_digest": current.get(artifact_id),
                    },
                )
                msg = (
                    "APPROVAL_ARTIFACT_DIGEST_MISMATCH: "
                    f"artifact {artifact_id} changed since the review snapshot "
                    f"(pinned {pinned_digest}, current {current.get(artifact_id)})."
                )
                raise AdlcRunStateError(msg)

    @staticmethod
    def _validate_pending_approval(
        run: WorkflowRun,
        task: TaskRun,
        approval: ApprovalRequest,
    ) -> None:
        if run.status is not WorkflowRunStatus.WAITING_APPROVAL:
            msg = "The workflow run is not waiting for approval."
            raise AdlcRunStateError(msg)
        if approval.status is not ApprovalStatus.PENDING:
            msg = "The approval request has already been resolved."
            raise AdlcRunStateError(msg)
        if task.status is not TaskRunStatus.WAITING_APPROVAL or task.pending_result is None:
            msg = "The approval task has no pending result."
            raise AdlcRunStateError(msg)

    def _transition_workflow(
        self,
        run: WorkflowRun,
        status: WorkflowRunStatus,
        *,
        payload: dict | None = None,
    ) -> None:
        previous_status = run.status
        if status not in WORKFLOW_TRANSITIONS[previous_status]:
            msg = f"Invalid WorkflowRun transition: {previous_status.value} -> {status.value}"
            raise AdlcRunStateError(msg)
        run.status = status
        if status in {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}:
            run.completed_at = utc_now()
        self._emit_workflow_event(run, previous_status=previous_status, payload=payload or {})

    def _transition_task(
        self,
        run: WorkflowRun,
        task: TaskRun,
        status: TaskRunStatus,
        *,
        payload: dict | None = None,
        event_type: str | None = None,
    ) -> None:
        previous_status = task.status
        if status not in TASK_TRANSITIONS[previous_status]:
            msg = f"Invalid TaskRun transition: {previous_status.value} -> {status.value}"
            raise AdlcRunStateError(msg)
        task.status = status
        if status is TaskRunStatus.RUNNING and task.started_at is None:
            task.started_at = utc_now()
        if status in {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
            TaskRunStatus.SKIPPED,
        }:
            task.completed_at = utc_now()
        self._emit_task_event(
            run,
            task,
            previous_status=previous_status,
            payload=payload or {},
            event_type=event_type,
        )

    async def _persist_safely(self, record: _StoredRun, *, required: bool = False) -> None:
        """Save snapshots, failing closed at dispatch and revision-fenced repository boundaries."""
        if self._persistence is None:
            return
        try:
            await self._persistence.save(
                owner_id=record.owner_id,
                run=record.run,
                definitions=record.definitions,
            )
        except Exception:
            if required or isinstance(self._persistence, _RunRepositoryPersistence):
                raise
            logger.warning(
                "Failed to persist ADLC workflow run %s snapshot.",
                record.run.id,
                exc_info=True,
            )

    async def _ensure_hydrated(self, owner_id: str | None) -> None:  # noqa: ARG002 - recovery restores all owners once.
        """Restore persisted runs once per process and recover interrupted work.

        The owner-scoped argument is retained for call-site stability; hydration
        deliberately restores every owner once per process so startup recovery
        can requeue all interrupted work.

        Lock ordering: this hydration lock is only ever taken from inside the
        mutation lock, so recovery itself must not reacquire the mutation lock.
        """
        # Scope is immutable; refresh discovery across workers/imports before
        # every legacy read or mutation, even when runtime hydration is complete.
        if self._project_scope_loader is not None:
            self._project_bound_run_ids = set(await self._project_scope_loader())
        if self._persistence is None:
            return
        async with self._hydration_lock:
            if self._recovery_done:
                return
            snapshots = await self._persistence.load(owner_id=None)
            for restored_owner_id, run, definitions in snapshots:
                if run.id in self._runs:
                    continue
                definition_map = {definition.key: definition for definition in definitions}
                record = _StoredRun(
                    owner_id=restored_owner_id,
                    run=run,
                    definitions=definition_map,
                    delay_ms=0,
                )
                for event in run.events:
                    if event.event_type == "workflow_run.created":
                        max_concurrency = event.payload.get("max_concurrency")
                        if (
                            isinstance(max_concurrency, int)
                            and not isinstance(max_concurrency, bool)
                            and max_concurrency > 0
                        ):
                            record.max_concurrency = max_concurrency
                        delay_ms = event.payload.get("delay_ms")
                        if isinstance(delay_ms, int) and not isinstance(delay_ms, bool) and delay_ms >= 0:
                            record.delay_ms = delay_ms
                    if event.event_type == "task_run.retry_scheduled" and event.task_run_id is not None:
                        ready_at = event.payload.get("retry_ready_at")
                        if isinstance(ready_at, str):
                            record.retry_ready_at[event.task_run_id] = datetime.fromisoformat(ready_at)
                    if event.event_type == RUNTIME_EVENT_EMITTED and isinstance(event.payload.get("event_name"), str):
                        record.emitted_events.add(event.payload["event_name"])
                self._restore_pause_reason(record)
                self._runs[run.id] = record
                self._hydrated_owners.add(restored_owner_id)
            self._recovery_done = True
            for record in self._runs.values():
                self._recovery_report.inspected += 1
                if await self._recover_record(record):
                    self._recovery_report.reattached += 1
                if record.run.status not in _TERMINAL_WORKFLOW_STATUSES:
                    self._recovery_report.restored_approvals += sum(
                        approval.status is ApprovalStatus.PENDING for approval in record.run.approval_requests
                    )

    def _restore_pause_reason(self, record: _StoredRun) -> None:
        """Derive the durable pause reason from the latest persisted pause event."""
        for event in reversed(record.run.events):
            if event.event_type != "workflow_run.paused":
                continue
            reason = event.payload.get("reason")
            if reason in {
                _PAUSE_REASON_USER,
                _PAUSE_REASON_RETRY,
                _PAUSE_REASON_EVENTS,
                _PAUSE_REASON_APPROVAL_EXPIRED,
            }:
                record.pause_reason = str(reason)
            return

    async def _recover_record(self, record: _StoredRun) -> bool:
        """Restore approvals and reattach interrupted attempts through the shared scheduler."""
        run = record.run
        if run.project_id is not None or run.id in self._project_bound_run_ids:
            return False  # H7C must supply delegation before shared dispatch/recovery.
        if run.status in _TERMINAL_WORKFLOW_STATUSES:
            return False
        for task in run.tasks:
            await self._prepare_accepted_recovery_result(record, task)
            if task.pending_result is None and task.status in {TaskRunStatus.RUNNING, TaskRunStatus.READY}:
                task.deadline_at = None
                task.worker_id = None
        interrupted = any(
            task.status in {TaskRunStatus.RUNNING, TaskRunStatus.READY, TaskRunStatus.WAITING_APPROVAL}
            and task.pending_result is None
            and (task.request is not None or task.status is not TaskRunStatus.READY)
            for task in run.tasks
        )
        pending_approvals = any(approval.status is ApprovalStatus.PENDING for approval in run.approval_requests)
        if pending_approvals and not interrupted:
            if run.status is WorkflowRunStatus.RUNNING:
                self._transition_workflow(run, WorkflowRunStatus.WAITING_APPROVAL)
                await self._persist_safely(record, required=True)
            return False
        if run.status is WorkflowRunStatus.PAUSED or (
            run.status is WorkflowRunStatus.WAITING_APPROVAL and not interrupted
        ):
            return False
        if run.status is WorkflowRunStatus.CREATED:
            self._transition_workflow(run, WorkflowRunStatus.QUEUED)
        if run.status is WorkflowRunStatus.QUEUED:
            self._transition_workflow(run, WorkflowRunStatus.RUNNING)
        self._start_background(record, recovery=True)
        return True

    def _emit_runtime_event(
        self,
        record: _StoredRun,
        run: WorkflowRun,
        event_name: str,
        payload: dict | None = None,
    ) -> RunEvent:
        event_payload = dict(payload or {})
        event_payload["event_name"] = event_name
        record.emitted_events.add(event_name)
        event = RunEvent(
            event_id=uuid4(),
            event_type=RUNTIME_EVENT_EMITTED,
            workflow_run_id=run.id,
            aggregate_type="WORKFLOW_RUN",
            aggregate_id=run.id,
            sequence=len(run.events) + 1,
            previous_status=run.status.value,
            status=run.status.value,
            actor=SYSTEM_ACTOR,
            correlation_id=f"run-{run.id}",
            occurred_at=utc_now(),
            producer="adlc-run-coordinator",
            payload=event_payload,
        )
        run.events.append(event)
        return event

    def _emit_workflow_event(
        self,
        run: WorkflowRun,
        *,
        previous_status: WorkflowRunStatus | None,
        payload: dict,
    ) -> None:
        event_payload = dict(payload)
        if run.execution_plan_id is not None:
            event_payload["execution_plan_id"] = str(run.execution_plan_id)
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=WORKFLOW_EVENT_TYPES[run.status],
                workflow_run_id=run.id,
                aggregate_type="WORKFLOW_RUN",
                aggregate_id=run.id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=run.status.value,
                actor=SYSTEM_ACTOR,
                correlation_id=f"run-{run.id}",
                occurred_at=utc_now(),
                producer="adlc-run-coordinator",
                payload=event_payload,
            )
        )

    def _emit_task_event(
        self,
        run: WorkflowRun,
        task: TaskRun,
        *,
        previous_status: TaskRunStatus | None,
        payload: dict,
        event_type: str | None = None,
    ) -> None:
        event_payload = dict(payload)
        if task.plan_traceability is not None:
            event_payload["plan_traceability"] = task.plan_traceability.model_dump(mode="json")
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=event_type or TASK_EVENT_TYPES[task.status],
                workflow_run_id=run.id,
                task_run_id=task.id,
                attempt_id=task.current_attempt_id,
                aggregate_type="TASK_RUN",
                aggregate_id=task.id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=task.status.value,
                actor=SYSTEM_ACTOR,
                correlation_id=f"run-{run.id}/task-{task.id}",
                occurred_at=utc_now(),
                producer="adlc-run-coordinator",
                payload=event_payload,
            )
        )

    def _emit_approval_event(
        self,
        run: WorkflowRun,
        approval: ApprovalRequest,
        *,
        previous_status: ApprovalStatus | None,
        event_type: str,
        actor: Actor = SYSTEM_ACTOR,
    ) -> None:
        task = self._task_by_id(run, approval.task_run_id)
        event_payload = {"gate_type": approval.gate_type.value}
        if task.plan_traceability is not None:
            event_payload["plan_traceability"] = task.plan_traceability.model_dump(mode="json")
        run.events.append(
            RunEvent(
                event_id=uuid4(),
                event_type=event_type,
                workflow_run_id=run.id,
                task_run_id=approval.task_run_id,
                attempt_id=approval.attempt_id,
                approval_request_id=approval.approval_request_id,
                aggregate_type="APPROVAL_REQUEST",
                aggregate_id=approval.approval_request_id,
                sequence=len(run.events) + 1,
                previous_status=previous_status.value if previous_status else None,
                status=approval.status.value,
                actor=actor,
                correlation_id=f"run-{run.id}/approval-{approval.approval_request_id}",
                occurred_at=utc_now(),
                producer="adlc-run-coordinator",
                payload=event_payload,
            )
        )

    def _owned_run(self, run_id: UUID, owner_id: str) -> _StoredRun:
        record = self._runs.get(run_id)
        if record is None or record.owner_id != owner_id or record.run.project_id is not None or run_id in self._project_bound_run_ids:
            msg = f"Workflow run {run_id} was not found."
            raise AdlcRunNotFoundError(msg)
        return record

    def _owned_task(self, task_id: UUID, owner_id: str) -> tuple[_StoredRun, TaskRun]:
        for record in self._runs.values():
            if record.owner_id != owner_id or record.run.project_id is not None or record.run.id in self._project_bound_run_ids:
                continue
            task = next((item for item in record.run.tasks if item.id == task_id), None)
            if task is not None:
                return record, task
        msg = f"Task run {task_id} was not found."
        raise AdlcRunNotFoundError(msg)

    def _owned_approval(self, approval_id: UUID, owner_id: str) -> tuple[_StoredRun, ApprovalRequest]:
        for record in self._runs.values():
            if record.owner_id != owner_id or record.run.project_id is not None or record.run.id in self._project_bound_run_ids:
                continue
            approval = next(
                (item for item in record.run.approval_requests if item.approval_request_id == approval_id),
                None,
            )
            if approval is not None:
                return record, approval
        msg = f"Approval request {approval_id} was not found."
        raise AdlcRunNotFoundError(msg)

    @staticmethod
    def _task_by_id(run: WorkflowRun, task_id: UUID) -> TaskRun:
        task = next((item for item in run.tasks if item.id == task_id), None)
        if task is None:
            msg = f"Task run {task_id} does not belong to workflow run {run.id}."
            raise AdlcRunStateError(msg)
        return task


def _mock_subtasks_for_task(task: TaskRun) -> list["SubtaskRun"]:
    """Generate mock subtasks for a task based on its node type.

    Each node type has a pre-defined template with 3-6 subtasks.
    Templates prioritize parallel execution where subtasks don't
    depend on each other. The DSH-based generator in
    :mod:`subtask_generator` is kept for future use but is not
    invoked by default — this mock provides deterministic, fast
    responses for the demo.

    Node types and their templates:
    - requirements: Gather, analyze, document requirements
    - design: Architecture, data model, API design, UI mockups
    - backend: Models, API endpoints, validation, tests
    - frontend: Components, state management, styling, tests
    - testing: Unit, integration, e2e, performance
    - deployment: CI/CD, infrastructure, monitoring
    - research: Search, read, analyze, summarize
    - default: Generic analyze → plan → execute → verify → review
    """
    from langflow.adlc.task_subtasks import SubtaskRun

    task_name = (task.name or task.key or str(task.id)).lower()
    task_id = str(task.id)

    # Determine node type from task name.
    node_type = _classify_node_type(task_name)

    # Get template for this node type.
    template, deps = _SUBTASK_TEMPLATES[node_type]

    subtasks = []
    for i, (name, desc) in enumerate(template):
        subtask_id = f"{task_id}.sub-{i + 1}"
        subtasks.append(
            SubtaskRun(
                id=subtask_id,
                name=name,
                description=desc,
                objective=f"{name} for {task.name or task_id}",
                status="pending",
                dependencies=[f"{task_id}.sub-{d + 1}" for d in deps[i]],
                trigger="on_success",
                timeout_seconds=600,
                expected_outputs=["summary"],
            )
        )
    return subtasks


def _classify_node_type(task_name: str) -> str:
    """Classify a task into a node type based on its name."""
    name = task_name.lower()
    if any(kw in name for kw in ("requirement", "yêu cầu", "spec", "gather")):
        return "requirements"
    if any(kw in name for kw in ("design", "thiết kế", "architect", "plan")):
        return "design"
    if any(kw in name for kw in ("backend", "api", "server", "database", "model")):
        return "backend"
    if any(kw in name for kw in ("frontend", "ui", "client", "component", "page")):
        return "frontend"
    if any(kw in name for kw in ("test", "verify", "validate", "check", "qa")):
        return "testing"
    if any(kw in name for kw in ("deploy", "ci", "cd", "infra", "monitor", "release")):
        return "deployment"
    if any(kw in name for kw in ("research", "analyze", "investigate", "study")):
        return "research"
    return "default"


# Subtask templates per node type.
# Each template is (subtasks, dependencies) where dependencies are
# 0-based indices of subtasks that must complete first.
# Parallel execution is prioritized: subtasks with no dependencies
# can run concurrently.
_SUBTASK_TEMPLATES: dict[str, tuple[list[tuple[str, str]], list[list[int]]]] = {
    "requirements": (
        [
            ("Gather stakeholder requirements", "Interview users and collect needs"),
            ("Analyze existing system", "Review current implementation and gaps"),
            ("Document functional requirements", "Write detailed requirement specs"),
            ("Prioritize requirements", "Rank by business value and feasibility"),
        ],
        # sub-3 depends on sub-1, sub-2 (parallel); sub-4 depends on sub-3
        [[], [], [0, 1], [2]],
    ),
    "design": (
        [
            ("Design system architecture", "Define components and their interactions"),
            ("Design data model", "Define entities, relationships, schemas"),
            ("Design API contracts", "Define endpoints, request/response shapes"),
            ("Create UI mockups", "Design user interface wireframes"),
            ("Write design document", "Compile all design decisions"),
        ],
        # sub-1, sub-2, sub-3, sub-4 can run in parallel; sub-5 depends on all
        [[], [], [], [], [0, 1, 2, 3]],
    ),
    "backend": (
        [
            ("Set up project structure", "Initialize repo, dependencies, config"),
            ("Implement data models", "Define database schemas and ORM models"),
            ("Implement API endpoints", "Build REST/GraphQL handlers"),
            ("Add input validation", "Validate requests, handle errors"),
            ("Write integration tests", "Test API endpoints end-to-end"),
            ("Final code review", "Review and clean up code"),
        ],
        # sub-1 first; sub-2, sub-3 can run in parallel after sub-1;
        # sub-4 after sub-3; sub-5 after sub-3, sub-4; sub-6 after sub-5
        [[], [0], [0], [2], [2, 3], [4]],
    ),
    "frontend": (
        [
            ("Set up component library", "Initialize UI framework and design system"),
            ("Build core components", "Implement reusable UI primitives"),
            ("Implement page layouts", "Build page-level components"),
            ("Add state management", "Wire up stores, contexts, data fetching"),
            ("Style and polish", "Apply design tokens, responsive layout"),
            ("Write component tests", "Test components in isolation"),
        ],
        # sub-1 first; sub-2, sub-3 can run in parallel after sub-1;
        # sub-4 after sub-3; sub-5 after sub-2, sub-3; sub-6 after sub-2
        [[], [0], [0], [2], [1, 2], [1]],
    ),
    "testing": (
        [
            ("Write unit tests", "Cover individual functions and classes"),
            ("Write integration tests", "Test component interactions"),
            ("Write end-to-end tests", "Test full user flows"),
            ("Performance testing", "Measure latency, throughput, resource usage"),
            ("Security audit", "Check for common vulnerabilities"),
            ("Final test report", "Compile results and recommendations"),
        ],
        # sub-1, sub-2, sub-3, sub-4, sub-5 can run in parallel; sub-6 after all
        [[], [], [], [], [], [0, 1, 2, 3, 4]],
    ),
    "deployment": (
        [
            ("Set up CI/CD pipeline", "Configure build, test, deploy automation"),
            ("Configure infrastructure", "Provision servers, databases, networking"),
            ("Set up monitoring", "Add logging, metrics, alerting"),
            ("Write runbooks", "Document operational procedures"),
            ("Deploy to staging", "Roll out to staging environment"),
            ("Deploy to production", "Roll out to production environment"),
        ],
        # sub-1, sub-2, sub-3, sub-4 can run in parallel;
        # sub-5 after sub-1, sub-2; sub-6 after sub-5
        [[], [], [], [], [0, 1], [4]],
    ),
    "research": (
        [
            ("Search documentation", "Find relevant docs and references"),
            ("Read source code", "Analyze existing implementation"),
            ("Identify patterns", "Extract common patterns and conventions"),
            ("Summarize findings", "Write up research summary"),
        ],
        # Linear: each depends on previous
        [[], [0], [1], [2]],
    ),
    "default": (
        [
            ("Analyze requirements", "Understand what needs to be done"),
            ("Plan approach", "Design the solution"),
            ("Execute work", "Implement the solution"),
            ("Verify results", "Check correctness"),
            ("Final review", "Review and finalize"),
        ],
        # Linear with one parallel branch
        [[], [0], [1], [1], [2, 3]],
    ),
}

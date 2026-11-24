"""Authenticated HTTP surface for the ADLC mock execution slice."""

from __future__ import annotations

import asyncio
import copy
import os
from datetime import timedelta, timezone
from functools import lru_cache
from typing import Annotated, Any, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore, SourcePatchRead
from langflow.adlc.blueprint_generator import (
    BlueprintGenerationError,
    BlueprintGenerationSettings,
    applied_edges_summary,
    applied_stages_summary,
    apply_blueprint_to_flow_data,
    current_stages_projection,
    generate_blueprint_document,
)
from langflow.adlc.blueprints.errors import (
    BLUEPRINT_REQUIRES_EXECUTION_PLAN,
    PACKAGE_NOT_FOUND,
    PACKAGE_NOT_VISIBLE,
    PackageAccessError,
    PackageRegistryError,
)
from langflow.adlc.blueprints.models import (
    ExecutionPlan,
    PackageReference,
    PlanStatus,
    PlanValidationIssue,
    RegistryKey,
    SemanticVersion,
    WorkflowDefinition,
)
from langflow.adlc.contract_execution_models import (
    ContractRecoveryCommand,  # noqa: TC001 - FastAPI resolves body models at runtime.
)
from langflow.adlc.cron import CronParseError, describe_cron_next
from langflow.adlc.harness_artifacts import HarnessArtifactImporter, is_captured_harness_patch
from langflow.adlc.harness_attempts import HarnessAttemptError, validate_harness_result_for_attempt
from langflow.adlc.harness_callbacks import HarnessCallbackError, HarnessCallbackReceiver
from langflow.adlc.harness_client import HarnessClient, HarnessClientError
from langflow.adlc.harness_models import (
    HarnessCallbackReceipt,
    HarnessCorrelation,
    HarnessInteractionReceipt,
    HarnessInteractionResponse,
    HarnessReconciliationReport,
    HarnessRunResultProjection,
    HarnessRunSessionProjection,
    HarnessSessionRead,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    HarnessSubmissionReceipt,
)
from langflow.adlc.harness_runtime import (
    HarnessRuntimeReadiness,
    HarnessRuntimeSettings,
    check_harness_readiness,
    create_harness_client,
    reconcile_harness_attempts,
)
from langflow.adlc.legacy_flow_normalizer import FlowDagValidationError, normalize_legacy_flow_graph
from langflow.adlc.metrics import (
    AdlcMetricsCollector,
    AdlcMetricsSnapshot,
    CompositeAdlcObservabilitySink,
    render_prometheus,
    thresholds_from_environment,
)
from langflow.adlc.mock_workflow import (
    MockRunNotFoundError,
    MockRunStateError,
    MockWorkflowService,
    utc_now,
)
from langflow.adlc.models import (
    Actor,
    AdlcDeadLetter,
    ApprovalComment,
    ApprovalDecisionCommand,
    CreateWorkflowRunRequest,
    EmitRunEventCommand,
    MaterializeExecutionPlanRequest,
    MockWorkflowDefinition,
    PlanApprovalCommand,
    RegenerateExecutionPlanRequest,
    RunEventsResponse,
    ServiceError,
    StartMockWorkflowRequest,
    TaskRun,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunListResponse,
    WorkflowRunStatus,
)
from langflow.adlc.notifications import (
    AdlcNotificationSink,
    CompositeAdlcNotificationSink,
    StructuredLogAdlcNotificationSink,
    WebhookAdlcNotificationSink,
)
from langflow.adlc.observability import StructuredLogAdlcObservabilitySink
from langflow.adlc.opencode_client import OpenCodeClient, OpenCodeHttpClient, OpenCodeServerSettings
from langflow.adlc.opencode_runtime import (
    OpenCodeRuntimeReadiness,
    OpenCodeRuntimeSettings,
    check_opencode_readiness,
    create_default_task_executor,
)
from langflow.adlc.packages import (
    InMemoryPackageAccessPolicy,
    NodePackageRead,
    PackageAccessPolicy,
    RepositoryNodePackageRegistry,
    create_default_package_access_policy,
    create_default_package_registry,
    create_default_package_resolver,
)
from langflow.adlc.orchestrator_intake import (
    ORCHESTRATOR_ROUTING_DISABLED,
    IntentPlanProposalRequest,
    IntentRoutingDisabledError,
    create_intent_plan_proposal,
)
from langflow.adlc.orchestrator_routing import orchestrator_routing_enabled
from langflow.adlc.planning import (
    PLAN_NOT_FOUND,
    BlueprintCompiler,
    BlueprintParseContext,
    BlueprintParseError,
    ExecutionPlanMaterializer,
    ExecutionPlanNotFoundError,
    ExecutionPlanService,
    ExecutionPlanStateError,
    has_adlc_blueprint_marker,
    parse_blueprint_flow,
    plan_routing_proposal,
    workflow_structure_warnings,
)
from langflow.adlc.planning.proposals import (
    GeneratePlanProposalConfig,
    GeneratePlanProposalRequest,
    LLMPlannerAgent,
    MockPlannerAgent,
    PlannerGenerationError,
    PlannerMode,
    PlanProposalLimits,
    ProposalApprovalCommand,
    ProposalApprovalResponse,
    ProposalError,
    ProposalNotFoundError,
    ProposalService,
    ProposedPlan,
)
from langflow.adlc.run_persistence import SqlAdlcRunPersistence, database_session_factory
from langflow.adlc.run_repository import SqliteRunRepository, create_run_repository_from_environment
from langflow.adlc.run_service import (
    EXECUTION_MODE_MISMATCH,
    AdlcArtifactUnavailableError,
    AdlcRunNotFoundError,
    AdlcRunService,
    AdlcRunStateError,
)
from langflow.adlc.task_activity import TaskActivityResponse, TaskActivityService, TaskAgentActivity
from langflow.adlc.task_loop_inspection import RunOperatorControls, TaskLoopInspection
from langflow.adlc.task_loop_runtime_models import LoopRuntimeView
from langflow.adlc.task_loop_runtime_v2 import LoopRuntimeViewV2
from langflow.adlc.task_subtasks import TaskSubtasksResponse
from langflow.adlc.trigger_persistence import SqlAdlcTriggerPersistence
from langflow.adlc.triggers import (
    AdlcRunTriggerView,
    AdlcTriggerService,
    CreateRunTriggerCommand,
    NextTriggerRunsView,
    TriggerScheduleKind,
    UpdateRunTriggerCommand,
    WebhookFireResponse,
    WebhookTokenView,
)
from langflow.api.utils import CurrentActiveUser, DbSession, release_db_transaction
from langflow.api.v1.adlc_local_projects import project_context
from langflow.api.v1.adlc_local_projects import router as local_projects_router
from langflow.api.v1.authz_route_dependencies import (
    get_authorized_flow_for_read,
    get_authorized_flow_for_write,
)
from langflow.services.authorization import FlowAction, ensure_flow_permission
from langflow.services.database.models.adlc_execution_plan import (
    AdlcExecutionPlanSummaryRead,
    get_execution_plan_archive,
    list_execution_plan_archives,
    save_execution_plan,
)
from langflow.services.database.models.adlc_workflow_definition_version import (
    AdlcWorkflowDefinitionVersionRead,
    AdlcWorkflowDefinitionVersionReadWithData,
    get_definition_version_row,
    get_definition_version_rows,
    get_next_definition_version_number,
    publish_definition_version,
)
from lfx.log.logger import logger
from lfx.services.deps import injectable_session_scope

router = APIRouter(prefix="/adlc", tags=["ADLC"])

router.include_router(local_projects_router)

OptionalDbSession = Annotated[AsyncSession | None, Depends(injectable_session_scope)]

_adlc_observability_sink = StructuredLogAdlcObservabilitySink()
_mock_workflow_service = MockWorkflowService()
_execution_plan_materializer = ExecutionPlanMaterializer(_adlc_observability_sink)


def get_mock_workflow_service() -> MockWorkflowService:
    return _mock_workflow_service


MockWorkflowServiceDep = Annotated[MockWorkflowService, Depends(get_mock_workflow_service)]


@lru_cache(maxsize=1)
def get_harness_callback_receiver() -> HarnessCallbackReceiver:
    """Share attempt state between executor dispatch and callback ingress."""
    return HarnessCallbackReceiver(
        artifact_importer=HarnessArtifactImporter(get_adlc_artifact_payload_store(), get_harness_client()),
    )


@lru_cache(maxsize=1)
def get_adlc_artifact_payload_store() -> BoundedArtifactPayloadStore:
    """Share durable bytes between callback import, previews, and accepted-run review."""
    repository = create_run_repository_from_environment()
    return BoundedArtifactPayloadStore(
        database_path=repository.path if isinstance(repository, SqliteRunRepository) else None,
    )


HarnessCallbackReceiverDep = Annotated[
    HarnessCallbackReceiver,
    Depends(get_harness_callback_receiver),
]


@lru_cache(maxsize=1)
def get_harness_client() -> HarnessClient | None:
    """Share one authenticated Harness control client with execution and HITL routes."""
    settings = HarnessRuntimeSettings.from_environment()
    if not settings.enabled or not settings.server.api_token:
        return None
    try:
        return create_harness_client(settings, artifact_payloads=get_adlc_artifact_payload_store())
    except ValueError:
        return None


HarnessClientDep = Annotated[HarnessClient | None, Depends(get_harness_client)]


@lru_cache(maxsize=1)
def get_task_activity_service() -> TaskActivityService:
    """Share one read-only agent-activity projection service."""
    opencode_settings = OpenCodeRuntimeSettings.from_environment()
    opencode_client: OpenCodeClient | None = None
    if opencode_settings.enabled:
        opencode_client = OpenCodeHttpClient(OpenCodeServerSettings.from_environment())
    harness_client = get_harness_client()
    harness_events = None
    if harness_client is not None and hasattr(harness_client, "session_events"):

        async def harness_events(session_id: str, max_events: int) -> list[dict[str, object]]:
            return await harness_client.session_events(session_id, max_events=max_events)  # type: ignore[attr-defined]

    callbacks = get_harness_callback_receiver()

    async def attempt_getter(attempt_id: UUID):
        try:
            return await callbacks.attempts.get(attempt_id)
        except HarnessAttemptError:
            return None

    async def attempt_finder(task_run_id: UUID):
        """Find the latest attempt for a task run.

        Used as a fallback when ``current_attempt_id`` is stale or not yet set.
        """
        find_latest = getattr(callbacks.attempts, "find_latest_by_task_run_id", None)
        if find_latest is None:
            return None
        try:
            return await find_latest(task_run_id)
        except HarnessAttemptError:
            return None

    return TaskActivityService(
        opencode_client=opencode_client,
        worktree_root=opencode_settings.worktree_root,
        harness_events=harness_events,
        harness_attempts=attempt_getter,
        harness_attempt_finder=attempt_finder,
    )


TaskActivityServiceDep = Annotated[TaskActivityService, Depends(get_task_activity_service)]


@lru_cache(maxsize=1)
def get_adlc_metrics_collector() -> AdlcMetricsCollector:
    """Return the process-local rolling-window metrics aggregator."""
    return AdlcMetricsCollector(thresholds=thresholds_from_environment())


@lru_cache(maxsize=1)
def get_adlc_notification_sink() -> AdlcNotificationSink:
    """Compose operator notification channels from the environment."""
    webhook_url = os.environ.get("ADLC_NOTIFY_WEBHOOK_URL")
    sinks: list[AdlcNotificationSink] = [StructuredLogAdlcNotificationSink()]
    if webhook_url:
        sinks.append(
            WebhookAdlcNotificationSink(
                webhook_url,
                token=os.environ.get("ADLC_NOTIFY_WEBHOOK_TOKEN") or None,
            )
        )
    return CompositeAdlcNotificationSink(tuple(sinks))


AdlcMetricsCollectorDep = Annotated[AdlcMetricsCollector, Depends(get_adlc_metrics_collector)]


def _build_adlc_run_service() -> AdlcRunService:
    """Compose the process-local scheduler with durable snapshots and opt-in routing."""
    from langflow.adlc.collaboration import bound_run_ids

    repository = create_run_repository_from_environment()
    # Preserve configured and existing Harness history; fresh installs use the
    # orchestrator's Langflow SQL snapshot tables.
    retain_repository = os.getenv("ADLC_RUN_DB_PATH") is not None or bool(repository.load_all())
    artifact_payloads = get_adlc_artifact_payload_store()
    harness_callbacks = get_harness_callback_receiver()
    harness_client = get_harness_client()
    return AdlcRunService(
        executor=create_default_task_executor(
            artifact_payloads=artifact_payloads,
            harness_callbacks=harness_callbacks,
            harness_client=harness_client,
        ),
        artifact_payloads=artifact_payloads,
        observability_sink=CompositeAdlcObservabilitySink((_adlc_observability_sink, get_adlc_metrics_collector())),
        persistence=SqlAdlcRunPersistence(database_session_factory()),
        repository=repository if retain_repository else None,
        harness_callbacks=harness_callbacks,
        notification_sink=get_adlc_notification_sink(),
        project_scope_loader=bound_run_ids,
    )


class _AdlcSingletons:
    """Process singletons resolved inside the running event loop.

    The run and trigger services own background tasks (approval sweeper, trigger
    loop), so they must be created inside the event loop instead of the sync
    dependency threadpool.
    """

    run_service: AdlcRunService | None = None
    run_service_lock: asyncio.Lock | None = None
    trigger_service: AdlcTriggerService | None = None
    trigger_service_lock: asyncio.Lock | None = None


_adlc_singletons = _AdlcSingletons()


async def get_adlc_run_service() -> AdlcRunService:
    """Resolve the run service inside the event loop so background tasks can start."""
    if _adlc_singletons.run_service is None:
        if _adlc_singletons.run_service_lock is None:
            _adlc_singletons.run_service_lock = asyncio.Lock()
        async with _adlc_singletons.run_service_lock:
            if _adlc_singletons.run_service is None:
                service = _build_adlc_run_service()
                service.start_approval_sweeper()
                _adlc_singletons.run_service = service
    return _adlc_singletons.run_service


AdlcRunServiceDep = Annotated[AdlcRunService, Depends(get_adlc_run_service)]


def _build_adlc_trigger_service() -> AdlcTriggerService:
    """Compose the run-trigger scheduler with durable trigger rows."""
    run_service = _adlc_singletons.run_service or _build_adlc_run_service()
    return AdlcTriggerService(
        run_service,
        persistence=SqlAdlcTriggerPersistence(database_session_factory()),
    )


async def get_adlc_trigger_service() -> AdlcTriggerService:
    """Resolve the trigger service inside the event loop so its loop task can start."""
    await get_adlc_run_service()
    if _adlc_singletons.trigger_service is None:
        if _adlc_singletons.trigger_service_lock is None:
            _adlc_singletons.trigger_service_lock = asyncio.Lock()
        async with _adlc_singletons.trigger_service_lock:
            if _adlc_singletons.trigger_service is None:
                service = _build_adlc_trigger_service()
                service.start()
                _adlc_singletons.trigger_service = service
    return _adlc_singletons.trigger_service


AdlcTriggerServiceDep = Annotated[AdlcTriggerService, Depends(get_adlc_trigger_service)]


@lru_cache(maxsize=1)
def get_node_package_registry() -> RepositoryNodePackageRegistry:
    """Return the process-local immutable package catalogue."""
    return create_default_package_registry()


NodePackageRegistryDep = Annotated[RepositoryNodePackageRegistry, Depends(get_node_package_registry)]


@lru_cache(maxsize=1)
def get_package_access_policy() -> InMemoryPackageAccessPolicy:
    """Return the process-local mock authorization and lifecycle policy."""
    return create_default_package_access_policy()


PackageAccessPolicyDep = Annotated[PackageAccessPolicy, Depends(get_package_access_policy)]


@lru_cache(maxsize=1)
def get_blueprint_compiler() -> BlueprintCompiler:
    """Compose the package resolver and compiler for pure planning passes."""
    registry = get_node_package_registry()
    resolver = create_default_package_resolver(
        registry,
        get_package_access_policy(),
        observability_sink=_adlc_observability_sink,
    )
    return BlueprintCompiler(resolver, observability_sink=_adlc_observability_sink)


@lru_cache(maxsize=1)
def get_execution_plan_service() -> ExecutionPlanService:
    """Compose the process-local blueprint planning and plan-lifecycle boundary."""
    return ExecutionPlanService(get_blueprint_compiler())


ExecutionPlanServiceDep = Annotated[ExecutionPlanService, Depends(get_execution_plan_service)]


def get_execution_plan_materializer() -> ExecutionPlanMaterializer:
    return _execution_plan_materializer


ExecutionPlanMaterializerDep = Annotated[ExecutionPlanMaterializer, Depends(get_execution_plan_materializer)]


@lru_cache(maxsize=1)
def get_proposal_service() -> ProposalService:
    planner = (
        LLMPlannerAgent.from_env() if os.getenv("ADLC_PLANNER_MODE", "MOCK").upper() == "LLM" else MockPlannerAgent()
    )
    return ProposalService(
        planner,
        get_node_package_registry(),
        get_execution_plan_service(),
        access_policy=get_package_access_policy(),
    )


ProposalServiceDep = Annotated[ProposalService, Depends(get_proposal_service)]


async def get_opencode_runtime_readiness() -> OpenCodeRuntimeReadiness:
    return await check_opencode_readiness()


OpenCodeRuntimeReadinessDep = Annotated[
    OpenCodeRuntimeReadiness,
    Depends(get_opencode_runtime_readiness),
]


async def get_harness_runtime_readiness(
    callbacks: HarnessCallbackReceiverDep,
) -> HarnessRuntimeReadiness:
    return await check_harness_readiness(callbacks=callbacks)


HarnessRuntimeReadinessDep = Annotated[
    HarnessRuntimeReadiness,
    Depends(get_harness_runtime_readiness),
]


def _service_error(
    *,
    code: str,
    category: str,
    message: str,
    http_status: int,
    details: dict | None = None,
    service: str = "adlc-run-coordinator",
) -> dict:
    error = ServiceError(
        error_id=uuid4(),
        code=code,
        category=category,
        message=message,
        retryable=False,
        service=service,
        http_status=http_status,
        details=details or {},
        occurred_at=utc_now(),
    )
    return error.model_dump(mode="json", exclude_none=True)


def _raise_for_mock_error(exc: Exception) -> NoReturn:
    if isinstance(exc, MockRunNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="MOCK_RUN_NOT_FOUND",
                category="NOT_FOUND",
                message=str(exc),
                http_status=status.HTTP_404_NOT_FOUND,
            ),
        ) from exc
    if isinstance(exc, MockRunStateError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code="STATE_CONFLICT",
                category="CONFLICT",
                message=str(exc),
                http_status=status.HTTP_409_CONFLICT,
            ),
        ) from exc
    raise exc


def _raise_for_adlc_error(exc: Exception) -> NoReturn:
    if isinstance(exc, AdlcArtifactUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=_service_error(
                code="ARTIFACT_PAYLOAD_UNAVAILABLE",
                category="NOT_FOUND",
                message=str(exc),
                http_status=status.HTTP_410_GONE,
                service="adlc-artifact-payload-store",
            ),
        ) from exc
    if isinstance(exc, AdlcRunNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="ADLC_RESOURCE_NOT_FOUND",
                category="NOT_FOUND",
                message=str(exc),
                http_status=status.HTTP_404_NOT_FOUND,
            ),
        ) from exc
    if isinstance(exc, AdlcRunStateError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code="STATE_CONFLICT",
                category="CONFLICT",
                message=str(exc),
                http_status=status.HTTP_409_CONFLICT,
            ),
        ) from exc
    raise exc


def _raise_for_harness_error(exc: Exception) -> NoReturn:
    if isinstance(exc, HarnessAttemptError):
        http_status = status.HTTP_404_NOT_FOUND if exc.code == "HARNESS_ATTEMPT_NOT_FOUND" else status.HTTP_409_CONFLICT
        raise HTTPException(
            status_code=http_status,
            detail=_service_error(
                code=exc.code,
                category="NOT_FOUND" if http_status == status.HTTP_404_NOT_FOUND else "CONFLICT",
                message=exc.message,
                http_status=http_status,
                service="adlc-harness-attempt-store",
            ),
        ) from exc
    if isinstance(exc, HarnessClientError):
        http_status = {
            "CONFLICT": status.HTTP_409_CONFLICT,
            "VALIDATION": status.HTTP_422_UNPROCESSABLE_CONTENT,
        }.get(exc.category, status.HTTP_503_SERVICE_UNAVAILABLE)
        if exc.code in {"HARNESS_ARTIFACT_EXPIRED", "ARTIFACT_PAYLOAD_ALREADY_EXPIRED"}:
            http_status = status.HTTP_410_GONE
        raise HTTPException(
            status_code=http_status,
            detail=_service_error(
                code=exc.code,
                category=exc.category,
                message="The Harness control service could not complete the request.",
                http_status=http_status,
                service="agent-provider:deepseek-harness",
            ),
        ) from exc
    raise exc


def _require_harness_client(client: HarnessClient | None) -> HarnessClient:
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_service_error(
                code="HARNESS_CONTROL_CLIENT_NOT_CONFIGURED",
                category="CONFIGURATION",
                message="DeepSeek Harness control is not configured for this deployment.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                service="agent-provider:deepseek-harness",
            ),
        )
    return client


async def _authorize_harness_session(
    run_id: UUID,
    session_id: str,
    *,
    owner_id: str,
    service: AdlcRunService,
    callbacks: HarnessCallbackReceiver,
) -> None:
    try:
        await service.get_run(run_id, owner_id=owner_id)
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
    except HarnessAttemptError as exc:
        _raise_for_harness_error(exc)
    if attempt.workflow_run_id != run_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="HARNESS_ATTEMPT_NOT_FOUND",
                category="NOT_FOUND",
                message="The Harness session is not part of this workflow run.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-harness-attempt-store",
            ),
        )


def _raise_for_planning_error(exc: Exception) -> NoReturn:
    if isinstance(exc, BlueprintParseError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code=exc.code,
                category="VALIDATION",
                message=exc.message,
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details=exc.details,
                service="adlc-blueprint-planner",
            ),
        ) from exc
    if isinstance(exc, ExecutionPlanNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code=PLAN_NOT_FOUND,
                category="NOT_FOUND",
                message=str(exc),
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-blueprint-planner",
            ),
        ) from exc
    if isinstance(exc, ExecutionPlanStateError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code=exc.code,
                category="CONFLICT",
                message=exc.message,
                http_status=status.HTTP_409_CONFLICT,
                details=exc.details,
                service="adlc-plan-materializer",
            ),
        ) from exc
    if isinstance(exc, PackageAccessError):
        hidden = exc.code == PACKAGE_NOT_VISIBLE
        http_status = status.HTTP_404_NOT_FOUND if hidden else status.HTTP_403_FORBIDDEN
        raise HTTPException(
            status_code=http_status,
            detail=_service_error(
                code=exc.code,
                category="NOT_FOUND" if hidden else "AUTHORIZATION",
                message=exc.message,
                http_status=http_status,
                details=exc.details,
                service="adlc-package-access",
            ),
        ) from exc
    if isinstance(exc, PackageRegistryError):
        http_status = (
            status.HTTP_404_NOT_FOUND if exc.code == PACKAGE_NOT_FOUND else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(
            status_code=http_status,
            detail=_service_error(
                code=exc.code,
                category="NOT_FOUND" if http_status == status.HTTP_404_NOT_FOUND else "VALIDATION",
                message=exc.message,
                http_status=http_status,
                details=exc.details,
                service="adlc-blueprint-planner",
            ),
        ) from exc
    raise exc


async def archive_execution_plan(
    session: DbSession,
    *,
    owner_id: str,
    plan: ExecutionPlan,
    workflow: WorkflowDefinition,
    strict: bool = False,
) -> None:
    """Write one immutable plan snapshot through to the durable archive."""
    try:
        await save_execution_plan(
            session,
            owner_id=owner_id,
            workflow_definition_id=plan.workflow_definition_id,
            workflow_definition_version=plan.workflow_definition_version,
            plan_version=plan.plan_version,
            status=plan.status.value,
            validation_status=plan.validation_status.value,
            supersedes_plan_id=plan.supersedes_plan_id,
            approval_required=plan.approval_required,
            generated_at=plan.generated_at,
            plan_payload=plan.model_dump(mode="json"),
            workflow_payload=workflow.model_dump(mode="json"),
            execution_plan_id=plan.execution_plan_id,
        )
    except Exception:
        if strict:
            raise
        logger.warning(
            "Failed to archive execution plan %s for owner %s.",
            plan.execution_plan_id,
            owner_id,
            exc_info=True,
        )


async def _hydrate_plan_from_archive(
    session: OptionalDbSession,
    service: ExecutionPlanService,
    *,
    plan_id: UUID,
    owner_id: str,
) -> ExecutionPlan | None:
    """Restore one archived plan into the process-local service after a restart."""
    if session is None:
        return None
    try:
        row = await get_execution_plan_archive(session, plan_id=plan_id, owner_id=owner_id)
    except Exception:  # noqa: BLE001 - a failed archive read leaves normal plan lookup available.
        logger.warning("Failed to rehydrate execution plan %s from the archive.", plan_id, exc_info=True)
        return None
    if row is None:
        return None
    try:
        plan = ExecutionPlan.model_validate(row.plan_payload)
        workflow = WorkflowDefinition.model_validate(row.workflow_payload)
    except ValidationError:
        return None
    service.restore_plan(workflow=workflow, plan=plan, owner_id=owner_id)
    return plan


def _definition_parse_context(flow, current_user) -> BlueprintParseContext:
    flow_updated_at = getattr(flow, "updated_at", None) or utc_now()
    if flow_updated_at.utcoffset() is None:
        flow_updated_at = flow_updated_at.replace(tzinfo=timezone.utc)
    else:
        flow_updated_at = flow_updated_at.astimezone(timezone.utc)
    return BlueprintParseContext(
        flow_id=flow.id,
        project_id=flow.workspace_id or flow.folder_id or flow.id,
        name=flow.name,
        description=getattr(flow, "description", None) or "",
        created_by=str(current_user.id),
        created_at=flow_updated_at,
        updated_at=flow_updated_at,
    )


async def _local_definition_context(flow, current_user, session) -> BlueprintParseContext:
    from dataclasses import replace

    return replace(
        _definition_parse_context(flow, current_user), local_project=await project_context(flow, current_user, session)
    )


@router.get("/node-packages", response_model=list[NodePackageRead])
async def list_node_packages(
    current_user: CurrentActiveUser,
    registry: NodePackageRegistryDep,
    access_policy: PackageAccessPolicyDep,
    *,
    include_legacy: bool = False,
) -> list[NodePackageRead]:
    """List exact registered package versions visible to the caller."""
    try:
        from langflow.adlc.coding_agent import CODING_AGENT_PACKAGE, CODING_AGENT_VERSION, coding_package_in_catalogue

        subject_id = str(current_user.id)
        unified_visible = any(
            access_policy.can_view_package(
                subject_id, PackageReference(package_id=CODING_AGENT_PACKAGE, version=version)
            )
            for version in (CODING_AGENT_VERSION, "0.2.1", "0.2.0")
        )
        visible: list[NodePackageRead] = []
        for package in registry.list_packages():
            package_ref = PackageReference(
                package_id=package.definition.package_id,
                version=package.definition.version,
            )
            if not access_policy.can_view_package(subject_id, package_ref):
                continue
            if not include_legacy and not coding_package_in_catalogue(
                package_ref.package_id, package_ref.version, unified_visible=unified_visible
            ):
                continue
            visible.append(
                NodePackageRead.from_registered(
                    package,
                    effective_status=access_policy.package_status(package_ref, package.definition.status),
                )
            )
    except PackageRegistryError as exc:
        _raise_for_planning_error(exc)
    else:
        return visible


@router.get("/executors/opencode/readiness", response_model=OpenCodeRuntimeReadiness)
async def read_opencode_runtime_readiness(
    current_user: CurrentActiveUser,  # noqa: ARG001 - authentication is required for operational status.
    readiness: OpenCodeRuntimeReadinessDep,
) -> OpenCodeRuntimeReadiness:
    """Return a secret-free OpenCode server, model, and sandbox readiness projection."""
    return readiness


@router.get("/executors/deepseek-harness/readiness", response_model=HarnessRuntimeReadiness)
async def read_harness_runtime_readiness(
    current_user: CurrentActiveUser,  # noqa: ARG001 - authentication is required for operational status.
    readiness: HarnessRuntimeReadinessDep,
) -> HarnessRuntimeReadiness:
    """Return a secret-free Harness server and callback readiness projection."""
    return readiness


@router.post(
    "/harness/callbacks/session-results",
    response_model=HarnessCallbackReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_harness_session_result(
    request: Request,
    callbacks: HarnessCallbackReceiverDep,
) -> HarnessCallbackReceipt:
    """Accept a timestamped HMAC delivery without using end-user authentication."""
    try:
        return await callbacks.receive(
            await request.body(),
            delivery_id=request.headers.get("x-adlc-delivery-id"),
            timestamp=request.headers.get("x-adlc-timestamp"),
            signature=request.headers.get("x-adlc-signature"),
        )
    except HarnessCallbackError as exc:
        error_category = {
            status.HTTP_400_BAD_REQUEST: "VALIDATION",
            status.HTTP_401_UNAUTHORIZED: "AUTHENTICATION",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_413_CONTENT_TOO_LARGE: "VALIDATION",
            status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION",
            status.HTTP_503_SERVICE_UNAVAILABLE: "DEPENDENCY",
            status.HTTP_504_GATEWAY_TIMEOUT: "TIMEOUT",
        }.get(exc.http_status, "INTERNAL")
        raise HTTPException(
            status_code=exc.http_status,
            detail=_service_error(
                code=exc.code,
                category=error_category,
                message=exc.message,
                http_status=exc.http_status,
                service="adlc-harness-callback",
            ),
        ) from exc


@router.get(
    "/node-packages/{package_id}/versions/{version}",
    response_model=NodePackageRead,
)
async def get_node_package_version(
    package_id: RegistryKey,
    version: SemanticVersion,
    current_user: CurrentActiveUser,
    registry: NodePackageRegistryDep,
    access_policy: PackageAccessPolicyDep,
) -> NodePackageRead:
    """Read one immutable exact package version and registry digest."""
    try:
        package_ref = PackageReference(package_id=package_id, version=version)
        registered = registry.get(package_ref)
        access_policy.ensure_package_visible(str(current_user.id), package_ref)
        return NodePackageRead.from_registered(
            registered,
            effective_status=access_policy.package_status(package_ref, registered.definition.status),
        )
    except (PackageAccessError, PackageRegistryError) as exc:
        _raise_for_planning_error(exc)


@router.post(
    "/workflow-definitions/{workflow_id}/plans",
    response_model=ExecutionPlan,
    status_code=status.HTTP_201_CREATED,
)
async def create_execution_plan(
    workflow_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    service: ExecutionPlanServiceDep,
) -> ExecutionPlan:
    """Compile a marked saved flow without creating any runtime records or events."""
    flow = await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    from langflow.adlc.delivery_cycles import reject_external_planning

    await reject_external_planning(session, workflow_id, current_user)
    graph = flow.data or {}
    context = await _local_definition_context(flow, current_user, session)
    try:
        plan = service.create_plan_from_graph(
            graph,
            context=context,
            owner_id=str(current_user.id),
            generated_by=str(current_user.id),
        )
    except (BlueprintParseError, PackageRegistryError) as exc:
        _raise_for_planning_error(exc)
    workflow = service.get_materialization_snapshot(plan.execution_plan_id, owner_id=str(current_user.id))[1]
    await _auto_publish_definition_version(session, flow=flow, workflow=workflow, current_user=current_user)
    await archive_execution_plan(session, owner_id=str(current_user.id), plan=plan, workflow=workflow)
    return plan


async def _auto_publish_definition_version(
    session: DbSession,
    *,
    flow,
    workflow: WorkflowDefinition,
    current_user,
) -> None:
    """Record one definition-version row when the marker version is not yet archived."""
    owner_id = str(current_user.id)
    try:
        latest = await get_next_definition_version_number(session, flow.id) - 1
        if latest >= workflow.version:
            return
        await publish_definition_version(
            session,
            flow_id=flow.id,
            version_number=workflow.version,
            created_by=owner_id,
            data=flow.data,
            description=f"Auto-published with plan generation (v{workflow.version}).",
        )
    except Exception:  # noqa: BLE001 - automatic version publication is a best-effort archive operation.
        logger.warning(
            "Failed to auto-publish workflow definition %s at version %s.",
            flow.id,
            workflow.version,
            exc_info=True,
        )


class ValidateWorkflowDefinitionRequest(BaseModel):
    """Request one off-plan validation pass over a saved blueprint graph."""

    model_config = ConfigDict(populate_by_name=True)

    flow_id: UUID = Field(alias="flowId")
    deep: bool = False


class BlueprintValidationResponse(BaseModel):
    valid: bool
    issues: list[PlanValidationIssue]
    warnings: list[PlanValidationIssue]
    plan_status: str | None = None


class BlueprintGenerateRequest(BaseModel):
    requirement: str = Field(min_length=1, max_length=20000)
    instructions: str | None = Field(default=None, max_length=5000)


class BlueprintGeneratedStageRead(BaseModel):
    node_id: str
    stage_id: str
    name: str
    stage_type: str
    package: str


class BlueprintGeneratedEdgeRead(BaseModel):
    edge_id: str
    source: str
    target: str


class BlueprintGenerateResponse(BaseModel):
    flow_id: str
    applied: bool
    stages: list[BlueprintGeneratedStageRead]
    edges: list[BlueprintGeneratedEdgeRead]
    warnings: list[str]
    dsh_session_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _raise_for_blueprint_generation_error(exc: BlueprintGenerationError) -> NoReturn:
    category = {
        422: "VALIDATION",
        502: "DEPENDENCY",
        503: "DEPENDENCY",
        504: "TIMEOUT",
    }.get(exc.http_status, "INTERNAL")
    raise HTTPException(
        status_code=exc.http_status,
        detail=_service_error(
            code=exc.code,
            category=category,
            message=exc.message,
            http_status=exc.http_status,
            details=exc.details,
            service="adlc-blueprint-generator",
        ),
    ) from exc


@router.post(
    "/workflow-definitions/{workflow_id}/generate-blueprint",
    response_model=BlueprintGenerateResponse,
)
async def generate_workflow_blueprint(
    workflow_id: UUID,
    request: BlueprintGenerateRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> BlueprintGenerateResponse:
    """Generate or replace one flow's blueprint from a free-text requirement.

    The requirement is dispatched to a DeepSeek Harness (DSH) agent session;
    the returned ``blueprint.json`` file is validated against the visible node
    packages, applied to the saved flow graph, and persisted. The caller keeps
    full manual control afterwards: stages, bindings and constraints remain
    editable on the canvas like any hand-authored blueprint.
    """
    flow = await get_authorized_flow_for_write(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    if getattr(flow, "locked", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code="BLUEPRINT_FLOW_LOCKED",
                category="CONFLICT",
                message="The flow is locked and cannot be regenerated.",
                http_status=status.HTTP_409_CONFLICT,
                service="adlc-blueprint-generator",
            ),
        )

    graph = flow.data or {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    component_nodes = [
        node
        for node in (graph.get("nodes") or [])
        if isinstance(node, dict)
        and not isinstance((node.get("data") or {}).get("adlc"), dict)
        and str(node.get("type") or "").lower() != "notenode"
    ]
    if component_nodes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code="BLUEPRINT_COMPONENT_NODES_PRESENT",
                category="CONFLICT",
                message="Remove the Langflow component nodes before generating a blueprint for this flow.",
                http_status=status.HTTP_409_CONFLICT,
                details={"node_count": len(component_nodes)},
                service="adlc-blueprint-generator",
            ),
        )

    registry = get_node_package_registry()
    access_policy = get_package_access_policy()
    subject = str(current_user.id)
    packages = []
    for registered in registry.list_packages():
        package_ref = PackageReference(
            package_id=registered.definition.package_id,
            version=registered.definition.version,
        )
        if not access_policy.can_view_package(subject, package_ref):
            continue
        packages.append(registered.definition)

    settings = BlueprintGenerationSettings.from_environment()
    try:
        blueprint, dsh_session_id = await generate_blueprint_document(
            request.requirement,
            packages,
            settings=settings,
            instructions=request.instructions,
            current_stages=current_stages_projection(graph),
        )
        updated_data, stage_nodes, adlc_edges, warnings = apply_blueprint_to_flow_data(
            graph,
            blueprint,
            packages,
            flow_id=str(workflow_id),
        )
    except BlueprintGenerationError as exc:
        _raise_for_blueprint_generation_error(exc)

    flow.data = updated_data
    session.add(flow)
    await session.commit()
    return BlueprintGenerateResponse(
        flow_id=str(workflow_id),
        applied=True,
        stages=applied_stages_summary(stage_nodes),
        edges=applied_edges_summary(adlc_edges),
        warnings=warnings,
        dsh_session_id=dsh_session_id or None,
        data=updated_data,
    )


class PublishWorkflowDefinitionRequest(BaseModel):
    description: str | None = Field(default=None, max_length=500)


@router.post("/workflow-definitions/validate", response_model=BlueprintValidationResponse)
async def validate_workflow_definition(
    request: ValidateWorkflowDefinitionRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
    service: ExecutionPlanServiceDep,  # noqa: ARG001 - preserve the planning dependency on validation routes.
) -> BlueprintValidationResponse:
    """Validate a saved blueprint graph without compiling or storing a plan."""
    flow = await get_authorized_flow_for_read(
        flow_id=request.flow_id,
        current_user=current_user,
        session=session,
    )
    graph = flow.data or {}
    if not has_adlc_blueprint_marker(graph):
        return BlueprintValidationResponse(
            valid=False,
            issues=[
                PlanValidationIssue(
                    code="BLUEPRINT_MARKER_MISSING",
                    message="The flow does not declare an ADLC blueprint marker.",
                    path="/adlc",
                    details={},
                )
            ],
            warnings=[],
            plan_status=None,
        )
    context = await _local_definition_context(flow, current_user, session)
    try:
        workflow = parse_blueprint_flow(graph, context)
    except BlueprintParseError as exc:
        return BlueprintValidationResponse(valid=False, issues=list(exc.issues), warnings=[], plan_status=None)
    warnings = list(workflow_structure_warnings(workflow))
    if not request.deep:
        return BlueprintValidationResponse(valid=True, issues=[], warnings=warnings, plan_status=None)
    compiler = get_blueprint_compiler()
    try:
        plan = compiler.compile(
            workflow,
            plan_version=1,
            generated_by=str(current_user.id),
            authorization_subject=str(current_user.id),
        )
    except PackageRegistryError as exc:
        _raise_for_planning_error(exc)
    return BlueprintValidationResponse(
        valid=plan.status is PlanStatus.VALIDATED,
        issues=list(plan.validation_errors),
        warnings=[*warnings, *plan.warnings],
        plan_status=plan.status.value,
    )


@router.get("/workflow-definitions/{workflow_id}/plans", response_model=list[AdlcExecutionPlanSummaryRead])
async def list_workflow_execution_plans(
    workflow_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[AdlcExecutionPlanSummaryRead]:
    """List archived execution-plan versions for one workflow definition."""
    await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    rows = await list_execution_plan_archives(
        session,
        owner_id=str(current_user.id),
        workflow_definition_id=workflow_id,
    )
    return [
        AdlcExecutionPlanSummaryRead(
            execution_plan_id=row.id,
            workflow_definition_id=row.workflow_definition_id,
            workflow_definition_version=row.workflow_definition_version,
            plan_version=row.plan_version,
            status=row.status,
            validation_status=row.validation_status,
            supersedes_plan_id=row.supersedes_plan_id,
            approval_required=row.approval_required,
            generated_at=row.generated_at,
        )
        for row in rows
    ]


@router.get("/workflow-definitions/{workflow_id}/versions", response_model=list[AdlcWorkflowDefinitionVersionRead])
async def list_workflow_definition_versions(
    workflow_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> list[AdlcWorkflowDefinitionVersionRead]:
    """List the durable workflow-definition version history."""
    await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    rows = await get_definition_version_rows(
        session,
        flow_id=workflow_id,
        created_by=str(current_user.id),
    )
    return [_definition_version_read(row, with_data=False) for row in rows]


@router.post(
    "/workflow-definitions/{workflow_id}/versions",
    response_model=AdlcWorkflowDefinitionVersionReadWithData,
    status_code=status.HTTP_201_CREATED,
)
async def publish_workflow_definition_version(
    workflow_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    command: PublishWorkflowDefinitionRequest | None = None,
) -> AdlcWorkflowDefinitionVersionReadWithData:
    """Snapshot the current graph as a new durable workflow-definition version."""
    flow = await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    await ensure_flow_permission(
        current_user,
        FlowAction.WRITE,
        flow_id=flow.id,
        flow_user_id=flow.user_id,
        workspace_id=flow.workspace_id,
        folder_id=flow.folder_id,
    )
    owner_id = str(current_user.id)
    data = flow.data
    marker = data.get("adlc") if isinstance(data, dict) else None
    marker_version = marker.get("version") if isinstance(marker, dict) else None
    marker_version = marker_version if isinstance(marker_version, int) and marker_version >= 1 else 1
    next_version = max(await get_next_definition_version_number(session, flow.id), marker_version)
    if isinstance(data, dict) and isinstance(marker, dict) and marker_version != next_version:
        data = {**data, "adlc": {**marker, "version": next_version}}
        flow.data = data
    row = await publish_definition_version(
        session,
        flow_id=flow.id,
        version_number=next_version,
        created_by=owner_id,
        data=data,
        description=command.description if command else None,
    )
    return _definition_version_read(row, with_data=True)


@router.get(
    "/workflow-definitions/{workflow_id}/versions/{version_number}",
    response_model=AdlcWorkflowDefinitionVersionReadWithData,
)
async def get_workflow_definition_version(
    workflow_id: UUID,
    version_number: int,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> AdlcWorkflowDefinitionVersionReadWithData:
    """Read one workflow-definition version snapshot including its graph data."""
    await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    row = await get_definition_version_row(
        session,
        flow_id=workflow_id,
        version_number=version_number,
        created_by=str(current_user.id),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="WORKFLOW_DEFINITION_VERSION_NOT_FOUND",
                category="NOT_FOUND",
                message=f"Workflow definition version {version_number} was not found.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-blueprint-planner",
            ),
        )
    return _definition_version_read(row, with_data=True)


@router.post(
    "/workflow-definitions/{workflow_id}/versions/{version_number}/rollback",
    response_model=AdlcWorkflowDefinitionVersionReadWithData,
    status_code=status.HTTP_201_CREATED,
)
async def rollback_workflow_definition_version(
    workflow_id: UUID,
    version_number: int,
    current_user: CurrentActiveUser,
    session: DbSession,
) -> AdlcWorkflowDefinitionVersionReadWithData:
    """Restore a historical graph snapshot as a new monotonic definition version."""
    flow = await get_authorized_flow_for_read(
        flow_id=workflow_id,
        current_user=current_user,
        session=session,
    )
    await ensure_flow_permission(
        current_user,
        FlowAction.WRITE,
        flow_id=flow.id,
        flow_user_id=flow.user_id,
        workspace_id=flow.workspace_id,
        folder_id=flow.folder_id,
    )
    owner_id = str(current_user.id)
    historical = await get_definition_version_row(
        session,
        flow_id=workflow_id,
        version_number=version_number,
        created_by=owner_id,
    )
    if historical is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="WORKFLOW_DEFINITION_VERSION_NOT_FOUND",
                category="NOT_FOUND",
                message=f"Workflow definition version {version_number} was not found.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-blueprint-planner",
            ),
        )
    restored = copy.deepcopy(historical.data)
    if not isinstance(restored, dict):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code="WORKFLOW_DEFINITION_VERSION_INVALID",
                category="CONFLICT",
                message="The historical version snapshot has no restorable graph data.",
                http_status=status.HTTP_409_CONFLICT,
                service="adlc-blueprint-planner",
            ),
        )
    marker = restored.get("adlc")
    marker_version = marker.get("version") if isinstance(marker, dict) else None
    marker_version = marker_version if isinstance(marker_version, int) and marker_version >= 1 else 1
    next_version = max(
        await get_next_definition_version_number(session, flow.id),
        marker_version,
    )
    if isinstance(marker, dict):
        restored["adlc"] = {**marker, "version": next_version}
    flow.data = restored
    row = await publish_definition_version(
        session,
        flow_id=flow.id,
        version_number=next_version,
        created_by=owner_id,
        data=restored,
        description=f"Rollback of v{version_number}.",
    )
    return _definition_version_read(row, with_data=True)


def _definition_version_read(row, *, with_data: bool):
    payload = AdlcWorkflowDefinitionVersionRead(
        id=row.id,
        flow_id=row.flow_id,
        version_number=row.version_number,
        status=row.status,
        description=row.description,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    if not with_data:
        return payload
    return AdlcWorkflowDefinitionVersionReadWithData(**payload.model_dump(), data=row.data)


def _proposal_config(command: GeneratePlanProposalRequest | None) -> GeneratePlanProposalConfig:
    if command is None:
        return GeneratePlanProposalConfig()
    try:
        mode = PlannerMode(command.mode.strip().upper()) if command.mode else None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_service_error(
                code="PLANNER_MODE_INVALID",
                category="VALIDATION",
                message="Planner mode must be MOCK or LLM.",
                http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            ),
        ) from exc
    limits = {
        name: getattr(command, name)
        for name in ("max_tasks", "max_tasks_per_stage", "max_depth")
        if getattr(command, name) is not None
    }
    return GeneratePlanProposalConfig(mode=mode, limits=PlanProposalLimits(**limits) if limits else None)


def _raise_for_proposal_error(exc: ProposalError) -> NoReturn:
    http_status = (
        status.HTTP_404_NOT_FOUND
        if isinstance(exc, ProposalNotFoundError)
        else status.HTTP_503_SERVICE_UNAVAILABLE
        if isinstance(exc, PlannerGenerationError)
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(
        status_code=http_status,
        detail=_service_error(
            code=exc.details.get("code", exc.code) if isinstance(exc, PlannerGenerationError) else exc.code,
            category="NOT_FOUND" if http_status == status.HTTP_404_NOT_FOUND else "EXECUTION",
            message=exc.message,
            http_status=http_status,
            details=exc.details,
            service="adlc-blueprint-planner",
        ),
    ) from exc


@router.post(
    "/workflow-definitions/{workflow_id}/plan-proposals",
    response_model=ProposedPlan,
    status_code=status.HTTP_201_CREATED,
)
async def generate_plan_proposal(
    workflow_id: UUID,
    current_user: CurrentActiveUser,
    session: DbSession,
    service: ProposalServiceDep,
    command: GeneratePlanProposalRequest | None = None,
) -> ProposedPlan:
    """Propose tasks from an authorized saved blueprint before compiling an execution plan."""
    flow = await get_authorized_flow_for_read(flow_id=workflow_id, current_user=current_user, session=session)
    from langflow.adlc.delivery_cycles import reject_external_planning

    await reject_external_planning(session, workflow_id, current_user)
    owner_id = str(current_user.id)
    try:
        workflow = parse_blueprint_flow(flow.data or {}, await _local_definition_context(flow, current_user, session))
        return await service.generate_proposal(
            workflow, owner_id=owner_id, generated_by=owner_id, config=_proposal_config(command)
        )
    except (BlueprintParseError, PackageRegistryError) as exc:
        _raise_for_planning_error(exc)
    except ProposalError as exc:
        _raise_for_proposal_error(exc)


@router.get("/plan-proposals/{proposal_id}", response_model=ProposedPlan)
async def get_plan_proposal(
    proposal_id: UUID, current_user: CurrentActiveUser, service: ProposalServiceDep
) -> ProposedPlan:
    try:
        return service.get_proposal(proposal_id, owner_id=str(current_user.id))
    except ProposalError as exc:
        _raise_for_proposal_error(exc)


@router.post("/plan-proposals/{proposal_id}/validate", response_model=ProposedPlan)
async def validate_plan_proposal(
    proposal_id: UUID, current_user: CurrentActiveUser, service: ProposalServiceDep
) -> ProposedPlan:
    try:
        return service.validate_proposal(proposal_id, owner_id=str(current_user.id))
    except ProposalError as exc:
        _raise_for_proposal_error(exc)


@router.post("/plan-proposals/{proposal_id}/approve", response_model=ProposalApprovalResponse)
async def approve_plan_proposal(
    proposal_id: UUID,
    current_user: CurrentActiveUser,
    service: ProposalServiceDep,
    plan_service: ExecutionPlanServiceDep,
    command: ProposalApprovalCommand | None = None,
    session: OptionalDbSession = None,
) -> ProposalApprovalResponse:
    owner_id = str(current_user.id)
    try:
        from langflow.adlc.delivery_cycles import reject_external_planning

        pending = service.get_proposal(proposal_id, owner_id=owner_id)
        await reject_external_planning(session, pending.workflow_definition_id, current_user)
        proposal, plan = await service.approve_proposal(
            proposal_id, owner_id=owner_id, approved_by=owner_id, comment=command.comment if command else None
        )
        workflow = plan_service.get_materialization_snapshot(plan.execution_plan_id, owner_id=owner_id)[1]
    except ProposalError as exc:
        _raise_for_proposal_error(exc)
    except (PackageRegistryError, ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)
    await archive_execution_plan(session, owner_id=owner_id, plan=plan, workflow=workflow)
    return ProposalApprovalResponse(proposal=proposal, execution_plan=plan)


@router.post(
    "/plan-proposals/{proposal_id}/regenerate", response_model=ProposedPlan, status_code=status.HTTP_201_CREATED
)
async def regenerate_plan_proposal(
    proposal_id: UUID,
    current_user: CurrentActiveUser,
    service: ProposalServiceDep,
    command: GeneratePlanProposalRequest | None = None,
    session: OptionalDbSession = None,
) -> ProposedPlan:
    owner_id = str(current_user.id)
    try:
        from langflow.adlc.delivery_cycles import reject_external_planning

        pending = service.get_proposal(proposal_id, owner_id=owner_id)
        await reject_external_planning(session, pending.workflow_definition_id, current_user)
        return await service.regenerate_proposal(
            proposal_id, owner_id=owner_id, generated_by=owner_id, config=_proposal_config(command)
        )
    except ProposalError as exc:
        _raise_for_proposal_error(exc)


@router.post("/plan-proposals/{proposal_id}/reject", response_model=ProposedPlan)
async def reject_plan_proposal(
    proposal_id: UUID, current_user: CurrentActiveUser, service: ProposalServiceDep
) -> ProposedPlan:
    try:
        return service.reject_proposal(proposal_id, owner_id=str(current_user.id))
    except ProposalError as exc:
        _raise_for_proposal_error(exc)


@router.get("/execution-plans/{plan_id}", response_model=ExecutionPlan)
async def get_execution_plan(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    service: ExecutionPlanServiceDep,
    session: OptionalDbSession = None,
) -> ExecutionPlan:
    """Read an owner-scoped immutable plan snapshot, rehydrating from the archive if needed."""
    owner_id = str(current_user.id)
    # SQL is authoritative for workspace lifecycle transitions across workers.
    if session is not None:
        archived = await get_execution_plan_archive(session, plan_id=plan_id, owner_id=owner_id)
        if archived:
            from langflow.services.database.models.adlc_delivery import AdlcDelivery

            workspace = (
                await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == archived.workflow_definition_id))
            ).first()
            if workspace:
                plan = ExecutionPlan.model_validate(archived.plan_payload)
                workflow = WorkflowDefinition.model_validate(archived.workflow_payload)
                service.restore_plan(workflow=workflow, plan=plan, owner_id=owner_id, replace_existing=True)
                return plan
    try:
        return service.get_plan(plan_id, owner_id=owner_id)
    except ExecutionPlanNotFoundError:
        plan = await _hydrate_plan_from_archive(session, service, plan_id=plan_id, owner_id=owner_id)
        if plan is not None:
            return plan
        _raise_for_planning_error(ExecutionPlanNotFoundError(f"Execution plan {plan_id} was not found"))


@router.get("/execution-plans/{plan_id}/routing-proposal", response_model=dict)
async def get_execution_plan_routing_proposal(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    service: ExecutionPlanServiceDep,
) -> dict:
    """Preview which executor each plan task will run on, per capability.

    Read-only projection over the immutable plan snapshot for approvers:
    with ``ADLC_ORCHESTRATOR_ROUTING`` on, tasks whose adapter reference is
    ``orchestrator:auto`` report the orchestrator-selected plugin; every
    other task reports its literal adapter reference (user-routed). The
    plan snapshot is never mutated and no run is created.
    """
    owner_id = str(current_user.id)
    try:
        plan, _workflow = service.get_materialization_snapshot(plan_id, owner_id=owner_id)
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)
    return {
        "plan_id": str(plan.execution_plan_id),
        "routing_enabled": orchestrator_routing_enabled(),
        "tasks": plan_routing_proposal(plan),
    }


@router.post("/intents/plan-proposals", response_model=dict, status_code=status.HTTP_200_OK)
async def create_adlc_intent_plan_proposal(
    request: IntentPlanProposalRequest,
    current_user: CurrentActiveUser,
) -> dict:
    """Turn a raw request into a structured Intent and return a plan proposal.

    Advisory only: the orchestrator plugin (plan-only mode, no LLM in this
    endpoint) proposes one execution plan; nothing is run or materialized.
    The caller follows the existing plan approval and materialization path.
    The intent classification heuristic is echoed in the response for audit.
    """
    try:
        return await create_intent_plan_proposal(request, owner_id=str(current_user.id))
    except IntentRoutingDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": ORCHESTRATOR_ROUTING_DISABLED, "message": str(exc)},
        ) from exc


@router.post(
    "/execution-plans/{plan_id}/regenerate",
    response_model=ExecutionPlan,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_execution_plan(
    plan_id: UUID,
    request: RegenerateExecutionPlanRequest,
    current_user: CurrentActiveUser,
    service: ExecutionPlanServiceDep,
    session: OptionalDbSession = None,
) -> ExecutionPlan:
    """Compile the latest saved graph as an idempotent successor to the selected plan."""
    owner_id = str(current_user.id)
    try:
        predecessor = service.get_plan(plan_id, owner_id=owner_id)
    except ExecutionPlanNotFoundError:
        await _hydrate_plan_from_archive(session, service, plan_id=plan_id, owner_id=owner_id)
        try:
            predecessor = service.get_plan(plan_id, owner_id=owner_id)
        except ExecutionPlanNotFoundError as exc:
            _raise_for_planning_error(exc)
    flow = await get_authorized_flow_for_read(
        flow_id=predecessor.workflow_definition_id,
        current_user=current_user,
        session=session,
    )
    from langflow.adlc.delivery_cycles import reject_external_planning

    await reject_external_planning(session, predecessor.workflow_definition_id, current_user)
    graph = flow.data or {}
    context = await _local_definition_context(flow, current_user, session)
    try:
        plan = service.regenerate_plan_from_graph(
            graph,
            context=context,
            owner_id=owner_id,
            generated_by=owner_id,
            supersedes_plan_id=plan_id,
            idempotency_key=request.idempotency_key,
        )
    except (BlueprintParseError, PackageRegistryError, ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)
    workflow = service.get_materialization_snapshot(plan.execution_plan_id, owner_id=owner_id)[1]
    await archive_execution_plan(session, owner_id=owner_id, plan=plan, workflow=workflow)
    return plan


@router.post("/execution-plans/{plan_id}/validate", response_model=ExecutionPlan)
async def validate_execution_plan(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    service: ExecutionPlanServiceDep,
) -> ExecutionPlan:
    """Re-run package resolution and validation without mutating or executing the plan."""
    try:
        return service.validate_plan(plan_id, owner_id=str(current_user.id))
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)


@router.post("/execution-plans/{plan_id}/approve", response_model=ExecutionPlan)
async def approve_execution_plan(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    service: ExecutionPlanServiceDep,
    command: PlanApprovalCommand | None = None,
    session: OptionalDbSession = None,
) -> ExecutionPlan:
    """Accept one valid plan snapshot before runtime materialization."""
    owner_id = str(current_user.id)
    from langflow.adlc.delivery_cycles import reject_external_planning

    candidate = await get_execution_plan(plan_id, current_user, service, session)
    await reject_external_planning(session, candidate.workflow_definition_id, current_user)
    try:
        plan = service.approve_plan(
            plan_id,
            owner_id=owner_id,
            approved_by=owner_id,
            comment=command.comment if command else None,
        )
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)
    workflow = service.get_materialization_snapshot(plan_id, owner_id=owner_id)[1]
    await archive_execution_plan(session, owner_id=owner_id, plan=plan, workflow=workflow)
    return plan


@router.post(
    "/execution-plans/{plan_id}/prepare-subtasks",
    response_model=dict,
)
async def prepare_execution_plan_subtasks(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    plan_service: ExecutionPlanServiceDep,
    run_service: AdlcRunServiceDep,
    session: OptionalDbSession = None,
) -> dict:
    """Pre-generate subtasks for every task in an approved plan.

    Called immediately after plan approval so the Run button can be
    enabled only when all subtasks are ready. The generated subtasks
    are stored in the plan-level cache and copied into the subtask
    registry when the run is created.

    Returns a status dict with ``status`` (``pending``/``ready``/
    ``failed``), ``total_tasks``, ``prepared_tasks``, and ``error``.
    """
    owner_id = str(current_user.id)
    try:
        plan, _workflow = plan_service.get_materialization_snapshot(plan_id, owner_id=owner_id)
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)

    from langflow.adlc.delivery_cycles import reject_external_planning

    await reject_external_planning(session, plan.workflow_definition_id, current_user)

    # Build lightweight TaskRun projections for the subtask generator.
    from langflow.adlc.models import ExecutorTarget, TaskRun, TaskRunStatus

    tasks: list[TaskRun] = []
    for plan_task in plan.tasks:
        tasks.append(  # noqa: PERF401 - explicit projection mirrors the persisted TaskRun contract.
            TaskRun(
                id=plan_task.plan_task_id,
                # Lightweight projection values: the executor consumes the
                # PlanSpec directly, so these only feed the subtask generator.
                workflow_run_id=plan_id,
                task_definition_id=plan_task.resolved_node_spec_id,
                key=str(plan_task.plan_task_id),
                name=plan_task.name,
                task_type=plan_task.task_type,
                status=TaskRunStatus.PENDING,
                dependency_task_run_ids=list(plan_task.dependency_task_ids),
                executor=ExecutorTarget(
                    service="subtask-preparation",
                    operation=plan_task.task_type,
                ),
                request=None,  # type: ignore[arg-type]
                result=None,
                current_attempt_id=None,
                started_at=None,
                completed_at=None,
            )
        )

    return await run_service.prepare_plan_subtasks(plan_id, tasks, owner_id=owner_id)


@router.get(
    "/execution-plans/{plan_id}/subtask-status",
    response_model=dict,
)
async def get_execution_plan_subtask_status(
    plan_id: UUID,
    current_user: CurrentActiveUser,
    run_service: AdlcRunServiceDep,
    plan_service: ExecutionPlanServiceDep,
    session: OptionalDbSession = None,
) -> dict:
    """Return the current subtask preparation status for a plan."""
    await get_execution_plan(plan_id, current_user, plan_service, session)
    return run_service.get_plan_subtask_status(plan_id)


@router.post(
    "/execution-plans/{plan_id}/runs",
    response_model=WorkflowRun,
    status_code=status.HTTP_201_CREATED,
)
async def create_run_from_execution_plan(
    plan_id: UUID,
    request: MaterializeExecutionPlanRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
    plan_service: ExecutionPlanServiceDep,
    run_service: AdlcRunServiceDep,
    materializer: ExecutionPlanMaterializerDep,
    access_policy: PackageAccessPolicyDep,
    http_request: Request = None,
) -> WorkflowRun:
    """Authorize the source flow, then run the accepted immutable plan snapshot."""
    owner_id = str(current_user.id)
    try:
        plan, _workflow = plan_service.get_materialization_snapshot(plan_id, owner_id=owner_id)
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError) as exc:
        _raise_for_planning_error(exc)
    if any(spec.implementation.adapter_ref == "agent-provider:harness-workflow" for spec in plan.resolved_node_specs):
        from langflow.api.v1.adlc_contracts import get_contract_approver

        explicit = await get_contract_approver(http_request, session)
        if str(explicit.id) != owner_id:
            raise HTTPException(403, {"code": "HARNESS_WORKFLOW_OWNER_DENIED"})
    flow = await get_authorized_flow_for_read(
        flow_id=plan.workflow_definition_id,
        current_user=current_user,
        session=session,
    )
    await ensure_flow_permission(
        current_user,
        FlowAction.EXECUTE,
        flow_id=flow.id,
        flow_user_id=flow.user_id,
        workspace_id=flow.workspace_id,
        folder_id=flow.folder_id,
    )
    from langflow.adlc.delivery import ensure_run_authority

    await ensure_run_authority(
        session, flow, current_user, plan, materializing=True, dispatch_key=request.idempotency_key
    )
    from langflow.services.database.models.adlc_delivery import AdlcDelivery

    workspace_bound = (
        session is not None
        and (await session.exec(select(AdlcDelivery).where(AdlcDelivery.flow_id == flow.id))).first() is not None
    )
    await release_db_transaction(session)

    # Kick off subtask generation in the background AFTER the run
    # starts. The run returns immediately; subtasks are generated
    # concurrently (bounded by ADLC_SUBTASK_PREP_CONCURRENCY) and
    # cached so the UI can show them as soon as each task is opened.
    # The executor uses the subtasks from PlanSpec directly, so this
    # is purely for UI display speed.
    from langflow.adlc.models import ExecutorTarget, TaskRun, TaskRunStatus

    tasks: list[TaskRun] = []
    for plan_task in plan.tasks:
        tasks.append(  # noqa: PERF401 - explicit projection mirrors the persisted TaskRun contract.
            TaskRun(
                id=plan_task.plan_task_id,
                # Lightweight projection values: the executor consumes the
                # PlanSpec directly, so these only feed the subtask generator.
                workflow_run_id=plan_id,
                task_definition_id=plan_task.resolved_node_spec_id,
                key=str(plan_task.plan_task_id),
                name=plan_task.name,
                task_type=plan_task.task_type,
                status=TaskRunStatus.PENDING,
                dependency_task_run_ids=list(plan_task.dependency_task_ids),
                executor=ExecutorTarget(
                    service="subtask-preparation",
                    operation=plan_task.task_type,
                ),
                request=None,  # type: ignore[arg-type]
                result=None,
                current_attempt_id=None,
                started_at=None,
                completed_at=None,
            )
        )
    # Fire-and-forget: don't block the run start on DSH.
    # A workspace runs its frozen accepted graph. A second paid decomposition
    # would require H8C's separately persisted and reviewed cycle contract.
    if not workspace_bound:
        await run_service.prepare_plan_subtasks(plan_id, tasks, owner_id=owner_id)

    try:
        run = await materializer.materialize(
            plan_id,
            idempotency_key=request.idempotency_key,
            owner_id=owner_id,
            plan_service=plan_service,
            run_service=run_service,
            access_policy=access_policy,
        )
    except (ExecutionPlanNotFoundError, ExecutionPlanStateError, PackageAccessError) as exc:
        _raise_for_planning_error(exc)
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    plan, workflow = plan_service.get_materialization_snapshot(plan_id, owner_id=owner_id)
    await archive_execution_plan(session, owner_id=owner_id, plan=plan, workflow=workflow)
    return run


@router.post(
    "/runs",
    response_model=WorkflowRun,
    status_code=status.HTTP_201_CREATED,
)
async def create_adlc_run(
    request: CreateWorkflowRunRequest,
    current_user: CurrentActiveUser,
    session: DbSession,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    """Run an unmarked saved flow through the explicit legacy normalization path."""
    if request.execution_mode is not WorkflowExecutionMode.LEGACY_FLOW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code=EXECUTION_MODE_MISMATCH,
                category="CONFLICT",
                message="This endpoint accepts only LEGACY_FLOW execution mode.",
                http_status=status.HTTP_409_CONFLICT,
                details={
                    "expected": WorkflowExecutionMode.LEGACY_FLOW.value,
                    "received": request.execution_mode.value,
                },
            ),
        )
    flow = await get_authorized_flow_for_read(
        flow_id=request.flow_id,
        current_user=current_user,
        session=session,
    )
    await ensure_flow_permission(
        current_user,
        FlowAction.EXECUTE,
        flow_id=flow.id,
        flow_user_id=flow.user_id,
        workspace_id=flow.workspace_id,
        folder_id=flow.folder_id,
    )
    flow_id = flow.id
    flow_name = flow.name
    flow_data = flow.data or {}
    from langflow.adlc.delivery import ensure_run_authority

    await ensure_run_authority(session, flow, current_user, None)
    await release_db_transaction(session)
    if has_adlc_blueprint_marker(flow_data):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code=BLUEPRINT_REQUIRES_EXECUTION_PLAN,
                category="CONFLICT",
                message="Marked ADLC blueprints must be compiled and validated before execution.",
                http_status=status.HTTP_409_CONFLICT,
                details={"workflow_id": str(flow_id)},
            ),
        )
    try:
        definitions = normalize_legacy_flow_graph(flow_id, flow_data)
    except FlowDagValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code="INVALID_ADLC_DAG",
                category="VALIDATION",
                message="The saved flow is not a valid ADLC task DAG.",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"issues": exc.issues},
            ),
        ) from exc

    try:
        return await service.start_run(
            flow_id=flow_id,
            flow_name=flow_name,
            definitions=definitions,
            request=request,
            owner_id=str(current_user.id),
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get("/runs", response_model=WorkflowRunListResponse)
async def list_adlc_runs(
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    run_status: Annotated[WorkflowRunStatus | None, Query(alias="status")] = None,
    flow_id: UUID | None = None,
) -> WorkflowRunListResponse:
    """List owner-scoped run summaries, newest first, with bounded pagination."""
    return await service.list_runs(
        owner_id=str(current_user.id),
        limit=limit,
        offset=offset,
        status=run_status,
        flow_id=flow_id,
    )


@router.get("/runs/{run_id}", response_model=WorkflowRun)
async def get_adlc_run(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    try:
        return await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get("/runs/{run_id}/tasks", response_model=list[TaskRun])
async def get_adlc_run_tasks(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> list[TaskRun]:
    try:
        return await service.get_tasks(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get("/runs/{run_id}/controls", response_model=RunOperatorControls)
async def get_adlc_run_controls(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> RunOperatorControls:
    try:
        return await service.get_operator_controls(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get("/runs/{run_id}/tasks/{task_run_id}/task-loop", response_model=TaskLoopInspection)
async def get_adlc_task_loop(
    run_id: UUID,
    task_run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> TaskLoopInspection:
    try:
        return await service.get_task_loop(run_id, task_run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get("/runs/{run_id}/tasks/{task_run_id}/task-loop-runtime", response_model=LoopRuntimeView | LoopRuntimeViewV2)
async def get_adlc_task_loop_runtime(
    run_id: UUID,
    task_run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> LoopRuntimeView | LoopRuntimeViewV2:
    try:
        return await service.get_task_loop_runtime(run_id, task_run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get(
    "/runs/{run_id}/tasks/{task_run_id}/activity",
    response_model=TaskActivityResponse,
)
async def get_adlc_task_activity(
    run_id: UUID,
    task_run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    activity_service: TaskActivityServiceDep,
) -> TaskActivityResponse:
    """Return the live coding-agent transcript and terminal projection for one task."""
    try:
        run = await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    task = next((item for item in run.tasks if item.id == task_run_id), None)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="TASK_RUN_NOT_FOUND",
                category="NOT_FOUND",
                message="The workflow run does not contain this task.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-run-service",
            ),
        )
    return await activity_service.collect(task)


@router.get(
    "/runs/{run_id}/tasks/{task_run_id}/subtasks",
    response_model=TaskSubtasksResponse,
)
async def get_adlc_task_subtasks(
    run_id: UUID,
    task_run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    session: OptionalDbSession = None,
) -> TaskSubtasksResponse:
    """Return the subtasks for a task, generated on-demand by DSH.

    The system SDKs to DSH and asks "how would you divide this task
    into parallel subtasks?". The response is cached so subsequent
    calls return the same subtasks.
    """
    try:
        run = await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    task = next((item for item in run.tasks if item.id == task_run_id), None)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="TASK_RUN_NOT_FOUND",
                category="NOT_FOUND",
                message="The workflow run does not contain this task.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-run-service",
            ),
        )
    from langflow.adlc.delivery_cycles import reject_external_planning

    if run.flow_id is not None:
        await reject_external_planning(session, run.flow_id, current_user)
    return await service.get_task_subtasks(run_id, task, owner_id=str(current_user.id))


@router.get(
    "/runs/{run_id}/tasks/{task_run_id}/subtasks/{subtask_id}/activity",
    response_model=TaskAgentActivity,
)
async def get_adlc_subtask_activity(
    run_id: UUID,
    task_run_id: UUID,
    subtask_id: str,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    activity_service: TaskActivityServiceDep,
) -> TaskAgentActivity:
    """Return the live DSH transcript for a single subtask.

    Each subtask runs as its own DSH session (see
    :mod:`langflow.adlc.plan_executor`). The session id is captured in
    the subtask registry when the orchestrator observes the subtask
    state, so this endpoint resolves the session id from the registry
    and queries the DSH gateway for the latest events.
    """
    from langflow.adlc.subtask_registry import get_subtask_registry

    try:
        run = await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    task = next((item for item in run.tasks if item.id == task_run_id), None)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="TASK_RUN_NOT_FOUND",
                category="NOT_FOUND",
                message="The workflow run does not contain this task.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-run-service",
            ),
        )

    snapshot = get_subtask_registry().snapshot(run_id, task_run_id)
    if snapshot is None:
        return TaskAgentActivity(
            source="agent-provider:deepseek-harness",
            note="SUBTASK_NOT_REGISTERED",
        )
    subtask = next((s for s in snapshot.subtasks if s.id == subtask_id), None)
    if subtask is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="SUBTASK_NOT_FOUND",
                category="NOT_FOUND",
                message="The task does not contain this subtask.",
                http_status=status.HTTP_404_NOT_FOUND,
                service="adlc-run-service",
            ),
        )

    result = subtask.result if isinstance(subtask.result, dict) else {}
    session_id = result.get("session_id") if isinstance(result.get("session_id"), str) else None
    activity = TaskAgentActivity(source="agent-provider:deepseek-harness")
    if session_id is None:
        if subtask.status in {"pending", "ready"}:
            activity.note = "HARNESS_SESSION_PENDING"
        elif subtask.status in {"running"}:
            activity.note = "HARNESS_SESSION_BINDING"
        else:
            activity.note = "HARNESS_SESSION_NOT_BOUND"
        activity.running = subtask.status == "running"
        return activity

    activity.session_id = session_id
    harness_events = getattr(activity_service, "_harness_events", None)
    if harness_events is None:
        activity.note = "HARNESS_CLIENT_UNAVAILABLE"
        return activity
    try:
        events = await harness_events(session_id, 200)
    except Exception as exc:  # noqa: BLE001 - degrade into a note
        activity.note = getattr(exc, "code", None) or type(exc).__name__
        activity.running = subtask.status == "running"
        return activity

    from langflow.adlc.task_activity import _normalize_harness_events

    entries, total = _normalize_harness_events(events)
    activity.entries = entries
    activity.entries_total = total
    activity.running = subtask.status == "running"
    return activity


@router.get(
    "/runs/{run_id}/harness-results",
    response_model=list[HarnessRunResultProjection],
)
async def get_adlc_run_harness_results(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
) -> list[HarnessRunResultProjection]:
    """Read owner-scoped accepted results without contacting the Harness service."""
    try:
        await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    attempts = await callbacks.attempts.list_for_workflow_run(run_id)
    return [
        HarnessRunResultProjection(
            attempt_id=attempt.attempt_id,
            task_run_id=attempt.task_run_id,
            attempt_status=attempt.status,
            result=attempt.result,
            stored_at=attempt.updated_at,
        )
        for attempt in attempts
        if attempt.result is not None
    ]


@router.get(
    "/runs/{run_id}/harness-sessions",
    response_model=list[HarnessRunSessionProjection],
)
async def get_adlc_run_harness_sessions(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
) -> list[HarnessRunSessionProjection]:
    """Return owner-scoped live Harness sessions for interaction rendering."""
    try:
        await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    attempts = await callbacks.attempts.list_for_workflow_run(run_id)
    # Accepted results are read from ADLC's archive, never from disposable agent sessions.
    bound = [attempt for attempt in attempts if attempt.external_session_id is not None and attempt.result is None]
    if not bound:
        return []
    configured_client = _require_harness_client(client)
    projections: list[HarnessRunSessionProjection] = []
    try:
        for attempt in bound:
            session = await configured_client.get_session(attempt.external_session_id or "")
            projections.append(
                HarnessRunSessionProjection(
                    attempt_id=attempt.attempt_id,
                    task_run_id=attempt.task_run_id,
                    attempt_status=attempt.status,
                    session=session,
                )
            )
    except HarnessClientError as exc:
        _raise_for_harness_error(exc)
    return projections


@router.get(
    "/runs/{run_id}/harness-sessions/{session_id}/artifacts/{artifact_id}",
    response_model=SourcePatchRead,
)
async def get_adlc_harness_source_patch_preview(
    run_id: UUID,
    session_id: str,
    artifact_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
    response: Response,
) -> SourcePatchRead:
    """Retain/read a prepared patch without accepting, submitting, or applying it."""
    response.headers["Cache-Control"] = "no-store"
    await _authorize_harness_session(
        run_id,
        session_id,
        owner_id=str(current_user.id),
        service=service,
        callbacks=callbacks,
    )
    try:
        session = await _require_harness_client(client).get_session(session_id)
        attempt = await callbacks.attempts.find_by_session(session_id)
        if session.session_id != session_id or session.result is None:
            code = "HARNESS_ARTIFACT_PREVIEW_UNAVAILABLE"
            raise HarnessClientError(code, category="CONFLICT", retryable=False)
        validate_harness_result_for_attempt(attempt, session.result)
        if session.correlation != session.result.correlation:
            code = "HARNESS_ARTIFACT_CORRELATION_MISMATCH"
            raise HarnessClientError(code, category="CONFLICT", retryable=False)
        artifact = next((item for item in session.result.artifacts if item.artifact_id == artifact_id), None)
        if artifact is None:
            message = "The source patch was not found in this session."
            raise AdlcRunNotFoundError(message)
        if callbacks.artifact_importer is None:
            code = "HARNESS_ARTIFACT_IMPORT_UNAVAILABLE"
            raise HarnessClientError(code)
        return await callbacks.artifact_importer.read(session_id, session.correlation, artifact)
    except (HarnessClientError, HarnessAttemptError) as exc:
        _raise_for_harness_error(exc)
    except AdlcRunNotFoundError as exc:
        _raise_for_adlc_error(exc)


@router.post(
    "/runs/{run_id}/harness-sessions/{session_id}/interactions/{interaction_id}/responses",
    response_model=HarnessInteractionReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def respond_to_adlc_harness_interaction(
    run_id: UUID,
    session_id: str,
    interaction_id: str,
    command: HarnessInteractionResponse,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
) -> HarnessInteractionReceipt:
    """Resolve one agent-internal interaction without touching workflow approval gates."""
    await _authorize_harness_session(
        run_id,
        session_id,
        owner_id=str(current_user.id),
        service=service,
        callbacks=callbacks,
    )
    try:
        return await _require_harness_client(client).respond_to_interaction(
            session_id,
            interaction_id,
            command,
        )
    except HarnessClientError as exc:
        _raise_for_harness_error(exc)


@router.post(
    "/runs/{run_id}/harness-sessions/{session_id}/submit",
    response_model=HarnessSubmissionReceipt,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_adlc_harness_session(
    run_id: UUID,
    session_id: str,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
) -> HarnessSubmissionReceipt:
    """Submit one prepared MANUAL Harness result to the signed callback outbox."""
    await _authorize_harness_session(
        run_id,
        session_id,
        owner_id=str(current_user.id),
        service=service,
        callbacks=callbacks,
    )
    configured_client = _require_harness_client(client)
    try:
        session = await configured_client.get_session(session_id)
        if session.session_id != session_id:
            code = "HARNESS_RESULT_SESSION_MISMATCH"
            raise HarnessClientError(code, category="CONFLICT", retryable=False)
        if (
            session.submission_mode is not HarnessSubmissionMode.MANUAL
            or session.status is not HarnessSessionStatus.READY_FOR_SUBMISSION
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_service_error(
                    code="HARNESS_SESSION_NOT_MANUALLY_SUBMITTABLE",
                    category="CONFLICT",
                    message="The Harness session is not waiting for manual submission.",
                    http_status=status.HTTP_409_CONFLICT,
                    service="agent-provider:deepseek-harness",
                ),
            )
        if session.result is not None:
            attempt = await callbacks.attempts.find_by_session(session_id)
            validate_harness_result_for_attempt(attempt, session.result)
            if any(is_captured_harness_patch(item) for item in session.result.artifacts):
                if callbacks.artifact_importer is None:
                    code = "HARNESS_ARTIFACT_IMPORT_UNAVAILABLE"
                    raise HarnessClientError(code)
                await callbacks.artifact_importer.import_result(session.result)
        return await configured_client.submit_session(session_id)
    except (HarnessClientError, HarnessAttemptError) as exc:
        _raise_for_harness_error(exc)


@router.post(
    "/runs/{run_id}/harness-sessions/{session_id}/reconcile-verification",
    response_model=HarnessSessionRead,
)
async def reconcile_adlc_contract_verification(
    run_id: UUID,
    session_id: str,
    _command: ContractRecoveryCommand,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
) -> HarnessSessionRead:
    """Owner-only retry of a frozen H5D checkpoint; not Submit or a new execution."""
    from langflow.adlc.contract_execution import recovery_enabled

    await _authorize_harness_session(
        run_id, session_id, owner_id=str(current_user.id), service=service, callbacks=callbacks
    )
    if not recovery_enabled():
        raise HTTPException(status_code=403, detail={"code": "CONTRACT_RECOVERY_DISABLED"})
    try:
        attempt = await callbacks.attempts.find_by_session(session_id)
        owner, _configuration, trace = service.contract_execution_context(
            run_id=run_id, task_id=attempt.task_run_id, attempt_id=attempt.attempt_id, request_id=attempt.request_id
        )
        if owner != str(current_user.id) or trace.package_version != "0.2.0":
            raise HTTPException(status_code=409, detail={"code": "CONTRACT_RECOVERY_RELEASE_REQUIRED"})
        configured = _require_harness_client(client)
        before = await configured.get_session(session_id)
        if before.status is not HarnessSessionStatus.VERIFYING or before.correlation != HarnessCorrelation(
            request_id=attempt.request_id,
            workflow_run_id=run_id,
            task_run_id=attempt.task_run_id,
            attempt_id=attempt.attempt_id,
        ):
            raise HTTPException(status_code=409, detail={"code": "CONTRACT_RECOVERY_STATE_CONFLICT"})
        recovered = await configured.reconcile_contract_session(session_id)
        if recovered.correlation != before.correlation:
            code = "HARNESS_RESULT_CORRELATION_MISMATCH"
            raise HarnessClientError(code, category="CONFLICT", retryable=False)
    except (HarnessClientError, HarnessAttemptError) as exc:
        _raise_for_harness_error(exc)
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    else:
        return recovered


@router.post(
    "/runs/{run_id}/harness/reconcile",
    response_model=HarnessReconciliationReport,
)
async def reconcile_adlc_run_harness_sessions(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    callbacks: HarnessCallbackReceiverDep,
    client: HarnessClientDep,
) -> HarnessReconciliationReport:
    """Reconcile only the authenticated owner's selected workflow run."""
    try:
        await service.get_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    try:
        return await reconcile_harness_attempts(
            callbacks,
            _require_harness_client(client),
            workflow_run_id=run_id,
        )
    except HarnessClientError as exc:
        _raise_for_harness_error(exc)


@router.get("/runs/{run_id}/events", response_model=RunEventsResponse)
async def get_adlc_run_events(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> RunEventsResponse:
    try:
        events = await service.get_events(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)
    return RunEventsResponse(workflow_run_id=run_id, events=events)


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=SourcePatchRead)
async def get_adlc_source_patch(
    run_id: UUID,
    artifact_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    response: Response,
) -> SourcePatchRead:
    """Return a bounded source patch only to the owner of its workflow run."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.get_source_patch(run_id, artifact_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcArtifactUnavailableError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/tasks/{task_id}/retry", response_model=WorkflowRun)
async def retry_adlc_task(
    task_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    try:
        return await service.retry_task(task_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/runs/{run_id}/resume", response_model=WorkflowRun)
async def resume_adlc_run(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    """Resume a PAUSED run, re-dispatching work left behind by a lost executor."""
    try:
        return await service.resume_run(run_id, owner_id=str(current_user.id))
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/runs/{run_id}/cancel", response_model=WorkflowRun)
async def cancel_adlc_run(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    """Cancel a non-terminal run, its in-flight attempts, and its open approvals."""
    try:
        return await service.cancel_run(
            run_id,
            owner_id=str(current_user.id),
            actor=_user_actor(current_user),
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/runs/{run_id}/pause", response_model=WorkflowRun)
async def pause_adlc_run(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    """Pause a QUEUED or RUNNING run; in-flight attempts finish at a safe boundary."""
    try:
        return await service.pause_run(
            run_id,
            owner_id=str(current_user.id),
            actor=_user_actor(current_user),
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/runs/{run_id}/events", response_model=WorkflowRun)
async def emit_adlc_run_event(
    run_id: UUID,
    command: EmitRunEventCommand,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> WorkflowRun:
    """Emit one runtime event onto a run and wake any task waiting for it."""
    try:
        return await service.emit_event(
            run_id,
            command.event_name,
            owner_id=str(current_user.id),
            payload=command.payload,
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


def _user_actor(current_user) -> Actor:
    return Actor(type="USER", id=str(current_user.id), display_name=getattr(current_user, "username", None))


@router.post("/approvals/{approval_id}/approve", response_model=WorkflowRun)
async def approve_adlc_run(
    approval_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    http_request: Request = None,
    session: DbSession = None,
    command: ApprovalComment | None = None,
) -> WorkflowRun:
    try:
        run = await service.get_run_for_approval(approval_id, owner_id=str(current_user.id))
        if any(
            a.approval_request_id == approval_id and a.context.payload.get("harness_workflow_review")
            for a in run.approval_requests
        ):
            from langflow.api.v1.adlc_contracts import get_contract_approver

            explicit = await get_contract_approver(http_request, session)
            if str(explicit.id) != str(current_user.id):
                raise HTTPException(403, {"code": "HARNESS_WORKFLOW_OWNER_DENIED"})
            await release_db_transaction(session)
        return await service.approve(
            approval_id,
            owner_id=str(current_user.id),
            actor=_user_actor(current_user),
            comment=command.comment if command else None,
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.post("/approvals/{approval_id}/reject", response_model=WorkflowRun)
async def reject_adlc_run(
    approval_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
    command: ApprovalComment | None = None,
) -> WorkflowRun:
    try:
        return await service.reject(
            approval_id,
            owner_id=str(current_user.id),
            actor=_user_actor(current_user),
            comment=command.comment if command else None,
        )
    except (AdlcRunNotFoundError, AdlcRunStateError) as exc:
        _raise_for_adlc_error(exc)


@router.get(
    "/mock/workflow",
    response_model=MockWorkflowDefinition,
)
async def get_mock_workflow(
    current_user: CurrentActiveUser,  # noqa: ARG001 - authentication is the purpose of this dependency
    service: MockWorkflowServiceDep,
) -> MockWorkflowDefinition:
    """Return the fixed Plan -> parallel implementation -> Verify -> Approval graph."""
    return service.get_definition()


@router.post(
    "/mock/runs",
    response_model=WorkflowRun,
    status_code=status.HTTP_201_CREATED,
)
async def start_mock_workflow_run(
    request: StartMockWorkflowRequest,
    current_user: CurrentActiveUser,
    service: MockWorkflowServiceDep,
) -> WorkflowRun:
    """Execute mock tasks until the workflow fails or reaches human approval."""
    return await service.start_run(request, owner_id=str(current_user.id))


@router.get(
    "/mock/runs/{run_id}",
    response_model=WorkflowRun,
)
async def get_mock_workflow_run(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: MockWorkflowServiceDep,
) -> WorkflowRun:
    """Read an owner-scoped in-memory run snapshot."""
    try:
        return await service.get_run(run_id, owner_id=str(current_user.id))
    except (MockRunNotFoundError, MockRunStateError) as exc:
        _raise_for_mock_error(exc)


@router.get(
    "/mock/runs/{run_id}/events",
    response_model=RunEventsResponse,
)
async def get_mock_workflow_run_events(
    run_id: UUID,
    current_user: CurrentActiveUser,
    service: MockWorkflowServiceDep,
) -> RunEventsResponse:
    """Return the ordered v0.1 state-change events for a mock run."""
    try:
        events = await service.get_events(run_id, owner_id=str(current_user.id))
    except (MockRunNotFoundError, MockRunStateError) as exc:
        _raise_for_mock_error(exc)
    return RunEventsResponse(workflow_run_id=run_id, events=events)


@router.post(
    "/mock/runs/{run_id}/approval",
    response_model=WorkflowRun,
)
async def resolve_mock_workflow_approval(
    run_id: UUID,
    command: ApprovalDecisionCommand,
    current_user: CurrentActiveUser,
    service: MockWorkflowServiceDep,
) -> WorkflowRun:
    """Approve or reject the one AFTER_TASK gate in the mock workflow."""
    actor = Actor(type="USER", id=str(current_user.id), display_name=getattr(current_user, "username", None))
    try:
        return await service.resolve_approval(
            run_id,
            command,
            owner_id=str(current_user.id),
            actor=actor,
        )
    except (MockRunNotFoundError, MockRunStateError) as exc:
        _raise_for_mock_error(exc)


@router.post("/triggers", response_model=AdlcRunTriggerView, status_code=status.HTTP_201_CREATED)
async def create_adlc_run_trigger(
    command: CreateRunTriggerCommand,
    current_user: CurrentActiveUser,
    session: DbSession,
    service: AdlcTriggerServiceDep,
) -> AdlcRunTriggerView:
    """Create one scheduled or webhook run trigger with a frozen flow snapshot."""
    if command.execution_mode is not WorkflowExecutionMode.LEGACY_FLOW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code="UNSUPPORTED_TRIGGER_EXECUTION_MODE",
                category="VALIDATION",
                message="Run triggers currently support only LEGACY_FLOW execution mode.",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"received": command.execution_mode.value},
            ),
        )
    flow = await get_authorized_flow_for_read(
        flow_id=command.flow_id,
        current_user=current_user,
        session=session,
    )
    await ensure_flow_permission(
        current_user,
        FlowAction.EXECUTE,
        flow_id=flow.id,
        flow_user_id=flow.user_id,
        workspace_id=flow.workspace_id,
        folder_id=flow.folder_id,
    )
    flow_data = flow.data or {}
    await release_db_transaction(session)
    if has_adlc_blueprint_marker(flow_data):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_service_error(
                code=BLUEPRINT_REQUIRES_EXECUTION_PLAN,
                category="CONFLICT",
                message="Marked ADLC blueprints must be compiled and validated before execution.",
                http_status=status.HTTP_409_CONFLICT,
                details={"workflow_id": str(flow.id)},
            ),
        )
    try:
        definitions = normalize_legacy_flow_graph(flow.id, flow_data)
    except FlowDagValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code="INVALID_ADLC_DAG",
                category="VALIDATION",
                message="The saved flow is not a valid ADLC task DAG.",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"issues": exc.issues},
            ),
        ) from exc
    try:
        trigger = await service.create_trigger(
            owner_id=str(current_user.id),
            command=command,
            definitions=definitions,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code="INVALID_RUN_TRIGGER",
                category="VALIDATION",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
        ) from exc
    return trigger.public_view


@router.get("/triggers", response_model=list[AdlcRunTriggerView])
async def list_adlc_run_triggers(
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
) -> list[AdlcRunTriggerView]:
    """List the caller's run triggers, oldest first."""
    return await service.list_triggers(owner_id=str(current_user.id))


@router.get("/triggers/{trigger_id}", response_model=AdlcRunTriggerView)
async def get_adlc_run_trigger(
    trigger_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
) -> AdlcRunTriggerView:
    """Return one owner-scoped run trigger projection."""
    try:
        return await service.get_trigger(trigger_id, owner_id=str(current_user.id))
    except LookupError as exc:
        _raise_trigger_not_found(exc)


@router.patch("/triggers/{trigger_id}", response_model=AdlcRunTriggerView)
async def update_adlc_run_trigger(
    trigger_id: UUID,
    command: UpdateRunTriggerCommand,
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
) -> AdlcRunTriggerView:
    """Apply a partial update to one owner-scoped run trigger."""
    try:
        return await service.update_trigger(trigger_id, owner_id=str(current_user.id), command=command)
    except LookupError as exc:
        _raise_trigger_not_found(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_service_error(
                code="INVALID_RUN_TRIGGER",
                category="VALIDATION",
                message=str(exc),
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
        ) from exc


@router.delete("/triggers/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_adlc_run_trigger(
    trigger_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
) -> None:
    """Delete one owner-scoped run trigger."""
    deleted = await service.delete_trigger(trigger_id, owner_id=str(current_user.id))
    if not deleted:
        _raise_trigger_not_found(f"Run trigger {trigger_id} was not found")


@router.post("/triggers/{trigger_id}/rotate-webhook-token", response_model=WebhookTokenView)
async def rotate_adlc_trigger_webhook_token(
    trigger_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
) -> WebhookTokenView:
    """Replace the webhook secret and reveal the new token once."""
    try:
        token = await service.rotate_webhook_token(trigger_id, owner_id=str(current_user.id))
    except LookupError as exc:
        _raise_trigger_not_found(exc)
    return WebhookTokenView(webhook_token=token)


@router.get("/triggers/{trigger_id}/next-runs", response_model=NextTriggerRunsView)
async def preview_adlc_trigger_runs(
    trigger_id: UUID,
    current_user: CurrentActiveUser,
    service: AdlcTriggerServiceDep,
    count: int = 3,
) -> NextTriggerRunsView:
    """Preview the next fire times for one trigger's schedule."""
    count = max(1, min(count, 20))
    try:
        trigger = await service.get_trigger(trigger_id, owner_id=str(current_user.id))
    except LookupError as exc:
        _raise_trigger_not_found(exc)
    now = utc_now()
    cron = trigger.schedule.cron if trigger.schedule.kind is TriggerScheduleKind.CRON else None
    if cron is not None:
        try:
            upcoming = describe_cron_next(cron, after=now, limit=count)
        except CronParseError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_service_error(
                    code="INVALID_RUN_TRIGGER",
                    category="VALIDATION",
                    message=str(exc),
                    http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                ),
            ) from exc
    else:
        interval = trigger.schedule.interval_seconds
        if interval is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_service_error(
                    code="INVALID_RUN_TRIGGER",
                    category="VALIDATION",
                    message="The trigger schedule is missing its interval.",
                    http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                ),
            )
        upcoming = [now + timedelta(seconds=interval * (index + 1)) for index in range(count)]
    return NextTriggerRunsView(trigger_id=trigger.trigger_id, next_run_times=upcoming)


@router.post("/triggers/webhook/{token}", response_model=WebhookFireResponse)
async def fire_adlc_trigger_webhook(token: str, service: AdlcTriggerServiceDep) -> WebhookFireResponse:
    """Start one run for the trigger matching this webhook token (no user session)."""
    try:
        return await service.fire_webhook(token=token)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_service_error(
                code="TRIGGER_WEBHOOK_NOT_FOUND",
                category="NOT_FOUND",
                message=str(exc),
                http_status=status.HTTP_404_NOT_FOUND,
            ),
        ) from exc


def _raise_trigger_not_found(exc: LookupError | str) -> NoReturn:
    message = exc if isinstance(exc, str) else str(exc)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_service_error(
            code="ADLC_TRIGGER_NOT_FOUND",
            category="NOT_FOUND",
            message=message,
            http_status=status.HTTP_404_NOT_FOUND,
        ),
    )


@router.get("/metrics", response_model=AdlcMetricsSnapshot)
async def read_adlc_metrics(collector: AdlcMetricsCollectorDep) -> AdlcMetricsSnapshot:
    """Return the rolling-window aggregation of the ADLC observation stream."""
    return collector.snapshot()


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def read_adlc_metrics_prometheus(collector: AdlcMetricsCollectorDep) -> str:
    """Render the current metrics snapshot in Prometheus text exposition format."""
    return render_prometheus(collector.snapshot())


@router.get("/dead-letters", response_model=list[AdlcDeadLetter])
async def list_adlc_dead_letters(
    current_user: CurrentActiveUser,
    service: AdlcRunServiceDep,
) -> list[AdlcDeadLetter]:
    """List owner-scoped tasks whose attempt budget is exhausted."""
    return await service.list_dead_letters(owner_id=str(current_user.id))

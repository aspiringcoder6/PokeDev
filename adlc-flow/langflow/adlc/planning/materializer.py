"""Materialize accepted execution-plan snapshots into the existing mock runtime."""

from __future__ import annotations

import asyncio
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Iterable, NoReturn
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from langflow.adlc.blueprints.canonicalization import sha256_digest
from langflow.adlc.blueprints.models import (
    AUTHORING_CONTRACT_VERSION,
    ExecutionPlan,
    NodePackageKind,
    PlanStatus,
    PlanTask,
    PlanValidationStatus,
    ResolvedNodeSpec,
)
from langflow.adlc.models import (
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    ExecutorTarget,
    GateType,
    MockArtifactSpec,
    PlanTaskTraceability,
    WorkflowExecutionMode,
    WorkflowRun,
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
from langflow.adlc.orchestrator_plugin.host import OrchestratorHost, get_production_host
from langflow.adlc.orchestrator_plugin.interface import PluginMetadata
from langflow.adlc.orchestrator_routing import (
    ORCHESTRATOR_AUTO_ADAPTER_REF,
    orchestrator_routing_enabled,
)
from langflow.adlc.planning.errors import (
    PLAN_GATE_UNSUPPORTED,
    PLAN_INTEGRITY_MISMATCH,
    PLAN_NO_CAPABLE_PLUGIN,
    PLAN_NOT_ACCEPTED,
    ExecutionPlanStateError,
)
from langflow.adlc.resource_manager import AgentCapability

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.blueprints.models import ExecutionProfile
    from langflow.adlc.packages.access import PackageAccessPolicy
    from langflow.adlc.planning.service import ExecutionPlanService
    from langflow.adlc.run_service import AdlcRunService


class ExecutionPlanMaterializer:
    """Idempotent in-memory bridge from planning state to runtime state."""

    def __init__(self, observability_sink: AdlcObservabilitySink | None = None) -> None:
        self._run_ids: dict[tuple[str, UUID, str], UUID] = {}
        self._lock = asyncio.Lock()
        self._observability = observability_sink if observability_sink is not None else NOOP_ADLC_OBSERVABILITY_SINK

    async def materialize(
        self,
        plan_id: UUID,
        *,
        idempotency_key: str,
        owner_id: str,
        plan_service: ExecutionPlanService,
        run_service: AdlcRunService,
        access_policy: PackageAccessPolicy,
    ) -> WorkflowRun:
        """Create one runtime aggregate from an authorized accepted plan snapshot."""
        started_at_ns = perf_counter_ns()
        try:
            run, idempotent_replay = await self._materialize(
                plan_id,
                idempotency_key=idempotency_key,
                owner_id=owner_id,
                plan_service=plan_service,
                run_service=run_service,
                access_policy=access_policy,
            )
        except Exception as exc:
            record_observation_safely(
                self._observability,
                event_type=AdlcObservationType.PLAN_MATERIALIZATION_COMPLETED,
                outcome=observation_outcome_for_exception(exc),
                duration_ms=elapsed_milliseconds(started_at_ns),
                error_code=observation_error_code(exc, "PLAN_MATERIALIZATION_FAILED"),
                execution_plan_id=plan_id,
                idempotent_replay=False,
            )
            raise

        record_observation_safely(
            self._observability,
            event_type=AdlcObservationType.PLAN_MATERIALIZATION_COMPLETED,
            outcome=AdlcObservationOutcome.SUCCEEDED,
            duration_ms=elapsed_milliseconds(started_at_ns),
            workflow_definition_id=run.flow_id,
            execution_plan_id=plan_id,
            workflow_run_id=run.id,
            task_count=len(run.tasks),
            idempotent_replay=idempotent_replay,
        )
        return run

    async def _materialize(
        self,
        plan_id: UUID,
        *,
        idempotency_key: str,
        owner_id: str,
        plan_service: ExecutionPlanService,
        run_service: AdlcRunService,
        access_policy: PackageAccessPolicy,
    ) -> tuple[WorkflowRun, bool]:
        key = (owner_id, plan_id, idempotency_key)
        async with self._lock:
            existing_run_id = self._run_ids.get(key)
            if existing_run_id is not None:
                return await run_service.get_run(existing_run_id, owner_id=owner_id), True

            plan, workflow = plan_service.get_materialization_snapshot(plan_id, owner_id=owner_id)
            access_policy.ensure_plan_authorized(owner_id, plan)
            definitions = materialize_task_definitions(plan)
            from langflow.adlc.contract_execution import validate_plan_contracts

            validate_plan_contracts(plan, owner_id)
            max_concurrency = plan.metadata.get("max_concurrency")
            run = await run_service.start_run(
                flow_id=workflow.workflow_definition_id,
                flow_name=workflow.name,
                workflow_key=f"execution-plan:{plan.execution_plan_id}",
                execution_plan_id=plan.execution_plan_id,
                definitions=definitions,
                request=CreateWorkflowRunRequest(
                    flowId=workflow.workflow_definition_id,
                    executionMode=WorkflowExecutionMode.EXECUTION_PLAN,
                    delayMs=0,
                    maxConcurrency=max_concurrency if isinstance(max_concurrency, int) else None,
                ),
                owner_id=owner_id,
            )
            plan_service.mark_executing(plan_id, owner_id=owner_id)
            self._run_ids[key] = run.id
            return run, False

    async def clear(self) -> None:
        async with self._lock:
            self._run_ids.clear()


def materialize_task_definitions(plan: ExecutionPlan) -> list[AdlcTaskDefinition]:
    """Build runtime definitions only from the accepted immutable plan snapshot."""
    _assert_plan_is_accepted(plan)
    _assert_plan_contract(plan)
    _assert_plan_integrity(plan)
    specs = {spec.resolved_node_spec_id: spec for spec in plan.resolved_node_specs}
    definitions: list[AdlcTaskDefinition] = []
    for task in plan.tasks:
        spec = specs.get(task.resolved_node_spec_id)
        if spec is None:
            _integrity_error(plan, task, "The plan task references a missing resolved node snapshot.")
        _assert_snapshot_integrity(plan, task, spec)
        definitions.append(_materialize_task(plan, task, spec))
    return definitions


def parse_required_capabilities(capabilities: Iterable[str]) -> tuple[AgentCapability, ...]:
    """Reduce opaque executor-target capability refs to known capabilities.

    ``ExecutorTarget.capabilities`` mixes semantic capability values with
    opaque package references (provider, model, prompt, tool...). Only
    entries matching an :class:`AgentCapability` value can be matched
    against plugin metadata; everything else is ignored here.
    """
    parsed: list[AgentCapability] = []
    for value in capabilities:
        try:
            capability = AgentCapability(value)
        except ValueError:
            continue
        if capability not in parsed:
            parsed.append(capability)
    return tuple(parsed)


def resolve_orchestrator_route(
    capabilities: Iterable[str],
    *,
    host: OrchestratorHost | None = None,
) -> PluginMetadata:
    """Select the orchestrator plugin for one ``orchestrator:auto`` task.

    Picks the first enabled plugin (registration order) that supports ALL
    recognized required capabilities. Raises :class:`ExecutionPlanStateError`
    with the ``NO_CAPABLE_PLUGIN`` code when nothing qualifies — routing
    never falls back silently.
    """
    required = parse_required_capabilities(capabilities)
    target = host if host is not None else get_production_host()
    capable = target.find_capable(frozenset(required)) if required else ()
    if not capable:
        raw = list(dict.fromkeys(capabilities))
        raise ExecutionPlanStateError(
            PLAN_NO_CAPABLE_PLUGIN,
            "No enabled orchestrator plugin supports the required capabilities.",
            details={
                "adapter_ref": ORCHESTRATOR_AUTO_ADAPTER_REF,
                "required_capabilities": raw,
                "recognized_capabilities": sorted(capability.value for capability in required),
            },
        )
    return capable[0].metadata


def plan_routing_proposal(plan: ExecutionPlan) -> list[dict[str, Any]]:
    """Project the per-task executor routing decision for approvers.

    Pure read over the immutable plan snapshot: no package-registry
    resolution, no runtime mutation, no acceptance check. With the
    orchestrator routing flag off, every task reports its literal
    ``adapter_ref`` as a user-routed service (legacy behavior).
    """
    specs = {spec.resolved_node_spec_id: spec for spec in plan.resolved_node_specs}
    routing_enabled = orchestrator_routing_enabled()
    proposal: list[dict[str, Any]] = []
    for task in plan.tasks:
        spec = specs.get(task.resolved_node_spec_id)
        entry: dict[str, Any] = {
            "plan_task_id": str(task.plan_task_id),
            "task_name": task.name,
        }
        if spec is None:
            entry.update(
                {
                    "status": "integrity_error",
                    "adapter_ref": None,
                    "resolved_service": None,
                    "routing_source": None,
                    "required_capabilities": [],
                    "recognized_capabilities": [],
                    "error": {
                        "code": PLAN_INTEGRITY_MISMATCH,
                        "message": "The plan task references a missing resolved node snapshot.",
                    },
                }
            )
            proposal.append(entry)
            continue
        adapter_ref = spec.implementation.adapter_ref
        capability_strings = _task_capability_strings(task, spec.execution_profile)
        entry.update(
            {
                "adapter_ref": adapter_ref,
                "entrypoint": spec.implementation.entrypoint,
                "required_capabilities": capability_strings,
                "recognized_capabilities": [
                    capability.value for capability in parse_required_capabilities(capability_strings)
                ],
            }
        )
        if routing_enabled and adapter_ref == ORCHESTRATOR_AUTO_ADAPTER_REF:
            try:
                selected = resolve_orchestrator_route(capability_strings)
            except ExecutionPlanStateError as exc:
                entry.update(
                    {
                        "status": "no_capable_plugin",
                        "resolved_service": None,
                        "routing_source": "orchestrator",
                        "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                    }
                )
            else:
                entry.update(
                    {
                        "status": "resolved",
                        "resolved_service": selected.plugin_id,
                        "plugin_id": selected.plugin_id,
                        "routing_source": "orchestrator",
                    }
                )
        else:
            entry.update(
                {
                    "status": "user",
                    "resolved_service": adapter_ref,
                    "routing_source": "user",
                }
            )
        proposal.append(entry)
    return proposal


def _assert_plan_is_accepted(plan: ExecutionPlan) -> None:
    valid = plan.validation_status is PlanValidationStatus.VALID and not plan.validation_errors and bool(plan.tasks)
    accepted = plan.status in {PlanStatus.APPROVED, PlanStatus.EXECUTING} or (
        plan.status is PlanStatus.VALIDATED and not plan.approval_required
    )
    if valid and accepted:
        return
    raise ExecutionPlanStateError(
        PLAN_NOT_ACCEPTED,
        "The execution plan must be valid and, when required, approved before it can run.",
        details={
            "plan_id": str(plan.execution_plan_id),
            "status": plan.status.value,
            "validation_status": plan.validation_status.value,
            "approval_required": plan.approval_required,
        },
    )


def _assert_snapshot_integrity(plan: ExecutionPlan, task: PlanTask, spec: ResolvedNodeSpec) -> None:
    expected_digest = sha256_digest(
        {
            "schema_version": AUTHORING_CONTRACT_VERSION,
            "workflow_definition_id": spec.workflow_definition_id,
            "workflow_definition_version": spec.workflow_definition_version,
            "source_stage_id": spec.source_stage_id,
            "package_ref": spec.package_ref,
            "kind": spec.kind,
            "implementation": spec.implementation,
            "interface": spec.interface,
            "configuration": spec.configuration,
            "execution_profile": spec.execution_profile,
            "policies": spec.policies,
            "secret_refs": spec.secret_refs,
        }
    )
    if (
        spec.resolved_digest != expected_digest
        or task.resolved_node_digest != spec.resolved_digest
        or task.source_workflow_stage_id != spec.source_stage_id
    ):
        _integrity_error(
            plan,
            task,
            "The stored resolved-node snapshot no longer matches its accepted digest.",
            expected_digest=expected_digest,
            stored_digest=spec.resolved_digest,
        )


def _assert_plan_contract(plan: ExecutionPlan) -> None:
    try:
        type(plan).model_validate(plan.model_dump(mode="python"))
    except ValidationError as exc:
        raise ExecutionPlanStateError(
            PLAN_INTEGRITY_MISMATCH,
            "The stored execution plan no longer satisfies the v0.1 plan contract.",
            details={
                "plan_id": str(plan.execution_plan_id),
                "reason": str(exc),
            },
        ) from exc


def _assert_plan_integrity(plan: ExecutionPlan) -> None:
    workflow_digest = plan.metadata.get("workflow_digest")
    stored_resolution_digest = plan.metadata.get("resolution_digest")
    if not isinstance(workflow_digest, str) or not isinstance(stored_resolution_digest, str):
        raise ExecutionPlanStateError(
            PLAN_INTEGRITY_MISMATCH,
            "The execution plan is missing its compiler digest evidence.",
            details={"plan_id": str(plan.execution_plan_id)},
        )
    expected_resolution_digest = sha256_digest(
        {
            "workflow_digest": workflow_digest,
            "resolved_specs": [
                {
                    "stage_id": spec.source_stage_id,
                    "resolved_digest": spec.resolved_digest,
                }
                for spec in sorted(plan.resolved_node_specs, key=lambda item: str(item.source_stage_id))
            ],
            "validation_errors": plan.validation_errors,
        }
    )
    expected_plan_id = uuid5(
        NAMESPACE_URL,
        (
            f"adlc:execution-plan:{plan.workflow_definition_id}:{plan.workflow_definition_version}:"
            f"{plan.plan_version}:{expected_resolution_digest}"
        ),
    )
    if stored_resolution_digest != expected_resolution_digest or plan.execution_plan_id != expected_plan_id:
        raise ExecutionPlanStateError(
            PLAN_INTEGRITY_MISMATCH,
            "The execution plan identity no longer matches its compiler digest evidence.",
            details={
                "plan_id": str(plan.execution_plan_id),
                "expected_plan_id": str(expected_plan_id),
                "stored_resolution_digest": stored_resolution_digest,
                "expected_resolution_digest": expected_resolution_digest,
            },
        )


def _materialize_task(plan: ExecutionPlan, task: PlanTask, spec: ResolvedNodeSpec) -> AdlcTaskDefinition:
    gate_value = spec.policies.approval.gate_type
    if spec.kind is NodePackageKind.APPROVAL and gate_value is None:
        raise ExecutionPlanStateError(
            PLAN_GATE_UNSUPPORTED,
            "An APPROVAL package requires an explicit v0.1 approval gate.",
            details={"plan_id": str(plan.execution_plan_id), "plan_task_id": str(task.plan_task_id)},
        )
    if gate_value == GateType.BEFORE_TASK.value:
        raise ExecutionPlanStateError(
            PLAN_GATE_UNSUPPORTED,
            "BEFORE_TASK gates are not supported by the v0.1 mock runtime.",
            details={"plan_id": str(plan.execution_plan_id), "plan_task_id": str(task.plan_task_id)},
        )
    gate = GateType(gate_value) if gate_value else None
    profile = spec.execution_profile
    capabilities = _task_capability_strings(task, profile)
    package_digest = spec.package_ref.content_digest
    if package_digest is None:  # Also guarded by ResolvedNodeSpec validation.
        _integrity_error(plan, task, "The resolved package snapshot has no content digest.")
    trace = PlanTaskTraceability(
        execution_plan_id=plan.execution_plan_id,
        plan_task_id=task.plan_task_id,
        source_workflow_stage_id=task.source_workflow_stage_id,
        resolved_node_spec_id=spec.resolved_node_spec_id,
        package_id=spec.package_ref.package_id,
        package_version=spec.package_ref.version,
        package_content_digest=package_digest,
        resolved_node_digest=spec.resolved_digest,
    )
    artifact_name = str(
        spec.configuration.get("artifact_name")
        or (f"{task.expected_artifacts[0]}.txt" if task.expected_artifacts else "mock-result.txt")
    )
    delay_ms = _integer(spec.configuration.get("delay_ms"), default=0)
    simulate_failure = spec.configuration.get("simulate_failure") is True
    required_resources = _string_list(spec.configuration.get("required_resources"))
    waits_for = _string_list(spec.configuration.get("waits_for"))
    emits_events = _string_list(spec.configuration.get("emits_events"))
    outputs = {
        output_name: f"mock://plan-tasks/{task.plan_task_id}/outputs/{output_name}"
        for output_name in task.expected_artifacts
    }
    request_context = {
        "artifact_refs": [],
        "memory_refs": [profile.memory_policy_ref] if profile is not None else [],
        "variables": {
            "execution_plan_id": str(plan.execution_plan_id),
            "plan_task_id": str(task.plan_task_id),
        },
    }
    if "adlc_local_project" in plan.metadata:
        request_context["adlc_local_project"] = dict(plan.metadata["adlc_local_project"])
    request_metadata: dict[str, Any] = {
        "source": "execution_plan",
        "package_implementation": spec.implementation.model_dump(mode="json"),
        "execution_profile": profile.model_dump(mode="json") if profile is not None else None,
        "resolved_configuration": dict(spec.configuration),
        "secret_refs": dict(spec.secret_refs),
        "resolver_version": spec.resolver_version,
        "resolved_at": spec.resolved_at.isoformat(),
    }
    executor_service = spec.implementation.adapter_ref
    if orchestrator_routing_enabled():
        # Flag on: interpret the reserved marker, and label explicit
        # executor references as user-routed. Flag off leaves
        # request_metadata byte-identical to the legacy path.
        if executor_service == ORCHESTRATOR_AUTO_ADAPTER_REF:
            selected = resolve_orchestrator_route(capabilities)
            executor_service = selected.plugin_id
            request_metadata["routing_source"] = "orchestrator"
            request_metadata["routing"] = {
                "adapter_ref": ORCHESTRATOR_AUTO_ADAPTER_REF,
                "plugin_id": selected.plugin_id,
                "capabilities": [capability.value for capability in parse_required_capabilities(capabilities)],
            }
        else:
            request_metadata["routing_source"] = "user"
    constraints = {
        "timeout_ms": task.effective_policies.timeout_ms,
        "max_attempts": task.effective_policies.retry.max_attempts,
        "priority": task.priority,
        "permissions": task.effective_policies.permissions.model_dump(mode="json"),
        "resources": dict(task.effective_policies.resources),
    }
    input_slots = {slot.name: slot for slot in spec.interface.inputs}
    return AdlcTaskDefinition(
        id=task.plan_task_id,
        key=str(task.plan_task_id),
        name=task.name,
        task_type=task.task_type,
        dependencies=[str(dependency) for dependency in task.dependency_task_ids],
        dependency_conditions=list(task.dependency_conditions),
        priority=task.priority,
        required_resources=required_resources,
        waits_for=waits_for,
        emits_events=emits_events,
        executor="mock",
        predetermined_output={
            "planTaskId": str(task.plan_task_id),
            "summary": f"Mock execution completed for {task.name}.",
            "outputs": outputs,
        },
        artifact=MockArtifactSpec(
            kind=task.expected_artifacts[0] if task.expected_artifacts else "MOCK_RESULT",
            name=artifact_name,
            media_type="text/plain",
            content=f"Mock artifact produced for plan task {task.plan_task_id} ({task.name}).",
        ),
        approval_gate=gate,
        objective=task.objective,
        direct_inputs=dict(task.inputs),
        input_bindings=[
            {
                **binding.model_dump(mode="json"),
                "target_multiple": input_slots[binding.target_input].multiple,
            }
            for binding in task.input_bindings
        ],
        executor_target=ExecutorTarget(
            service=executor_service,
            operation=spec.implementation.entrypoint,
            environment_id=task.required_environment,
            capabilities=capabilities,
        ),
        request_context=request_context,
        constraints=constraints,
        request_metadata=request_metadata,
        simulate_failure=simulate_failure,
        delay_ms=delay_ms,
        approval_message=_optional_string(spec.configuration.get("message")),
        approval_required_role=_optional_string(spec.configuration.get("required_role")),
        plan_traceability=trace,
    )


def _task_capability_strings(task: PlanTask, profile: ExecutionProfile | None) -> list[str]:
    """Executor-target capability refs for one plan task (shared by routing)."""
    capability_refs = [task.assigned_capability] if task.assigned_capability is not None else []
    return list(dict.fromkeys([*capability_refs, *_profile_capabilities(profile)]))


def _profile_capabilities(profile: ExecutionProfile | None) -> list[str]:
    if profile is None:
        return []
    references = [
        profile.provider_ref,
        profile.model_ref,
        profile.system_prompt_ref,
        *profile.rule_set_refs,
        *profile.hook_refs,
        *profile.capabilities.tool_refs,
        *profile.capabilities.skill_refs,
        *profile.capabilities.plugin_refs,
        *profile.capabilities.mcp_server_refs,
        profile.memory_policy_ref,
        profile.sandbox_policy_ref,
    ]
    return list(dict.fromkeys(references))


def _integrity_error(
    plan: ExecutionPlan,
    task: PlanTask,
    message: str,
    **details: Any,
) -> NoReturn:
    raise ExecutionPlanStateError(
        PLAN_INTEGRITY_MISMATCH,
        message,
        details={
            "plan_id": str(plan.execution_plan_id),
            "plan_task_id": str(task.plan_task_id),
            **details,
        },
    )


def _integer(value: Any, *, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None

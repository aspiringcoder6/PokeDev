"""Owner-scoped in-memory execution-plan snapshot and lifecycle store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import TYPE_CHECKING

from langflow.adlc.blueprints.models import PlanStatus, PlanValidationStatus
from langflow.adlc.planning.errors import (
    PLAN_NOT_ACCEPTED,
    PLAN_STATE_CONFLICT,
    ExecutionPlanNotFoundError,
    ExecutionPlanStateError,
)
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow

if TYPE_CHECKING:
    from uuid import UUID

    from langflow.adlc.blueprints.models import ExecutionPlan, WorkflowDefinition
    from langflow.adlc.planning.compiler import BlueprintCompiler


@dataclass(frozen=True, slots=True)
class _StoredPlan:
    owner_id: str
    workflow: WorkflowDefinition
    plan: ExecutionPlan


class ExecutionPlanService:
    """Compile immutable plan contents and manage their owner-scoped lifecycle."""

    def __init__(self, compiler: BlueprintCompiler) -> None:
        self._compiler = compiler
        self._records: dict[UUID, _StoredPlan] = {}
        self._versions: dict[tuple[str, UUID], int] = {}
        self._latest_plan_ids: dict[tuple[str, UUID], UUID] = {}
        self._regenerations: dict[tuple[str, UUID, str], UUID] = {}
        self._lock = RLock()

    def create_plan_from_graph(
        self,
        graph: object,
        *,
        context: BlueprintParseContext,
        owner_id: str,
        generated_by: str,
    ) -> ExecutionPlan:
        """Parse, compile, and store one new plan version."""
        workflow = parse_blueprint_flow(graph, context)
        return self.create_plan(workflow, owner_id=owner_id, generated_by=generated_by)

    def compile_snapshot(self, workflow, *, owner_id, generated_by, plan_version, supersedes_plan_id=None):
        """Compile only: SQL-owning callers allocate versions and commit before caching.

        Unlike create_plan, this does not supersede a process-local head. A new
        product cycle must not mark a previous cycle's executing plan superseded.
        """
        return self._compiler.compile(
            workflow.model_copy(deep=True),
            plan_version=plan_version,
            generated_by=generated_by,
            supersedes_plan_id=supersedes_plan_id,
            authorization_subject=owner_id,
        )

    def approve_snapshot(self, workflow, plan, *, owner_id, approved_by, comment=None):
        """Validate an approval without publishing an uncommitted cache mutation."""
        isolated = ExecutionPlanService(self._compiler)
        isolated.restore_plan(workflow=workflow, plan=plan, owner_id=owner_id)
        return isolated.approve_plan(
            plan.execution_plan_id, owner_id=owner_id, approved_by=approved_by, comment=comment
        )

    def create_plan(
        self,
        workflow: WorkflowDefinition,
        *,
        owner_id: str,
        generated_by: str,
    ) -> ExecutionPlan:
        """Compile a new latest plan and supersede the previous latest version, if any."""
        key = (owner_id, workflow.workflow_definition_id)
        with self._lock:
            predecessor_id = self._latest_plan_ids.get(key)
            return self._create_plan_locked(
                workflow,
                owner_id=owner_id,
                generated_by=generated_by,
                predecessor_id=predecessor_id,
            )

    def regenerate_plan_from_graph(
        self,
        graph: object,
        *,
        context: BlueprintParseContext,
        owner_id: str,
        generated_by: str,
        supersedes_plan_id: UUID,
        idempotency_key: str,
    ) -> ExecutionPlan:
        """Parse the latest saved graph and replace one current plan idempotently."""
        with self._lock:
            existing = self._regeneration_result(owner_id, supersedes_plan_id, idempotency_key)
            if existing is not None:
                return existing
        workflow = parse_blueprint_flow(graph, context)
        return self.regenerate_plan(
            workflow,
            owner_id=owner_id,
            generated_by=generated_by,
            supersedes_plan_id=supersedes_plan_id,
            idempotency_key=idempotency_key,
        )

    def regenerate_plan(
        self,
        workflow: WorkflowDefinition,
        *,
        owner_id: str,
        generated_by: str,
        supersedes_plan_id: UUID,
        idempotency_key: str,
    ) -> ExecutionPlan:
        """Create one successor while retaining the predecessor as a read-only snapshot."""
        if not idempotency_key.strip():
            message = "idempotency_key must not be blank"
            raise ValueError(message)
        with self._lock:
            existing = self._regeneration_result(owner_id, supersedes_plan_id, idempotency_key)
            if existing is not None:
                return existing
            predecessor = self._owned_record(supersedes_plan_id, owner_id)
            if predecessor.plan.workflow_definition_id != workflow.workflow_definition_id:
                raise ExecutionPlanStateError(
                    PLAN_STATE_CONFLICT,
                    "A plan can only be regenerated from its source workflow.",
                    details={
                        "plan_id": str(supersedes_plan_id),
                        "workflow_definition_id": str(workflow.workflow_definition_id),
                    },
                )
            key = (owner_id, workflow.workflow_definition_id)
            latest_plan_id = self._latest_plan_ids.get(key)
            if predecessor.plan.status is PlanStatus.SUPERSEDED or latest_plan_id != supersedes_plan_id:
                raise ExecutionPlanStateError(
                    PLAN_STATE_CONFLICT,
                    "Only the latest non-superseded execution plan can be regenerated.",
                    details={
                        "plan_id": str(supersedes_plan_id),
                        "status": predecessor.plan.status.value,
                        "latest_plan_id": str(latest_plan_id) if latest_plan_id else None,
                    },
                )
            plan = self._create_plan_locked(
                workflow,
                owner_id=owner_id,
                generated_by=generated_by,
                predecessor_id=supersedes_plan_id,
            )
            self._regenerations[(owner_id, supersedes_plan_id, idempotency_key)] = plan.execution_plan_id
            return plan

    def get_plan(self, plan_id: UUID, *, owner_id: str) -> ExecutionPlan:
        """Return an owner-scoped immutable plan copy."""
        with self._lock:
            record = self._records.get(plan_id)
            if record is None or record.owner_id != owner_id:
                message = f"Execution plan {plan_id} was not found"
                raise ExecutionPlanNotFoundError(message)
            return record.plan.model_copy(deep=True)

    def validate_plan(self, plan_id: UUID, *, owner_id: str) -> ExecutionPlan:
        """Re-run resolution and validation without replacing the stored plan or starting a run."""
        with self._lock:
            record = self._records.get(plan_id)
            if record is None or record.owner_id != owner_id:
                message = f"Execution plan {plan_id} was not found"
                raise ExecutionPlanNotFoundError(message)
            workflow = record.workflow.model_copy(deep=True)
            original = record.plan.model_copy(deep=True)
            if original.status is PlanStatus.SUPERSEDED:
                raise ExecutionPlanStateError(
                    PLAN_STATE_CONFLICT,
                    "A superseded execution plan is read-only and cannot be revalidated.",
                    details={"plan_id": str(plan_id), "status": original.status.value},
                )
        return self._compiler.compile(
            workflow,
            plan_version=original.plan_version,
            generated_by=original.generated_by,
            generated_at=original.generated_at,
            supersedes_plan_id=original.supersedes_plan_id,
            authorization_subject=owner_id,
        )

    def require_human_review(self, plan_id: UUID, *, owner_id: str) -> ExecutionPlan:
        """Strengthen a not-yet-accepted plan's gate for the product journey."""
        with self._lock:
            record = self._owned_record(plan_id, owner_id)
            if record.plan.status not in {PlanStatus.VALIDATED, PlanStatus.INVALID}:
                raise ExecutionPlanStateError(PLAN_STATE_CONFLICT, "Only a new plan can acquire a review gate.")
            plan = record.plan.model_copy(update={"approval_required": True})
            self._records[plan_id] = _StoredPlan(owner_id=record.owner_id, workflow=record.workflow, plan=plan)
            return plan.model_copy(deep=True)

    def approve_plan(
        self,
        plan_id: UUID,
        *,
        owner_id: str,
        approved_by: str,
        comment: str | None = None,
        approved_at: datetime | None = None,
    ) -> ExecutionPlan:
        """Accept an approval-required, valid snapshot without recompiling it."""
        timestamp = approved_at or datetime.now(timezone.utc)
        if timestamp.utcoffset() is None:
            message = "approved_at must include a timezone"
            raise ValueError(message)
        with self._lock:
            record = self._owned_record(plan_id, owner_id)
            plan = record.plan
            if plan.status is PlanStatus.SUPERSEDED:
                raise ExecutionPlanStateError(
                    PLAN_STATE_CONFLICT,
                    "A superseded execution plan is read-only and cannot be approved.",
                    details={"plan_id": str(plan_id), "status": plan.status.value},
                )
            if plan.status in {PlanStatus.APPROVED, PlanStatus.EXECUTING} and plan.approved_at is not None:
                return plan.model_copy(deep=True)
            if not plan.approval_required:
                raise ExecutionPlanStateError(
                    PLAN_STATE_CONFLICT,
                    "This execution plan does not require plan approval.",
                    details={"plan_id": str(plan_id), "status": plan.status.value},
                )
            if plan.status is not PlanStatus.VALIDATED or plan.validation_status is not PlanValidationStatus.VALID:
                raise ExecutionPlanStateError(
                    PLAN_NOT_ACCEPTED,
                    "Only a valid, validated execution plan can be approved.",
                    details={"plan_id": str(plan_id), "status": plan.status.value},
                )
            from langflow.adlc.contract_execution import validate_plan_contracts

            validate_plan_contracts(plan, owner_id)
            metadata = dict(plan.metadata)
            metadata["plan_approval"] = {"comment": comment} if comment else {}
            approved_payload = plan.model_dump(mode="python")
            approved_payload.update(
                {
                    "status": PlanStatus.APPROVED,
                    "approved_by": approved_by,
                    "approved_at": timestamp,
                    "metadata": metadata,
                }
            )
            approved = type(plan).model_validate(approved_payload)
            self._records[plan_id] = _StoredPlan(
                owner_id=record.owner_id,
                workflow=record.workflow,
                plan=approved,
            )
            return approved.model_copy(deep=True)

    def get_materialization_snapshot(
        self,
        plan_id: UUID,
        *,
        owner_id: str,
    ) -> tuple[ExecutionPlan, WorkflowDefinition]:
        """Return exact stored plan and workflow copies for the runtime boundary."""
        with self._lock:
            record = self._owned_record(plan_id, owner_id)
            return record.plan.model_copy(deep=True), record.workflow.model_copy(deep=True)

    def restore_plan(
        self,
        *,
        workflow: WorkflowDefinition,
        plan: ExecutionPlan,
        owner_id: str,
        replace_existing: bool = False,
    ) -> None:
        """Rehydrate one archived plan snapshot after a process restart.

        The in-memory version counters only move forward: an archived plan
        never becomes the latest version unless it is newer than everything
        currently tracked, and superseded snapshots never claim the slot.
        """
        with self._lock:
            key = (owner_id, workflow.workflow_definition_id)
            if plan.execution_plan_id in self._records and not replace_existing:
                return
            self._records[plan.execution_plan_id] = _StoredPlan(
                owner_id=owner_id,
                workflow=workflow.model_copy(deep=True),
                plan=plan.model_copy(deep=True),
            )
            if plan.plan_version > self._versions.get(key, 0):
                self._versions[key] = plan.plan_version
            latest = self._latest_plan_ids.get(key)
            if (
                latest is None or plan.plan_version > self._records[latest].plan.plan_version
            ) and plan.status is not PlanStatus.SUPERSEDED:
                self._latest_plan_ids[key] = plan.execution_plan_id

    def mark_executing(self, plan_id: UUID, *, owner_id: str) -> ExecutionPlan:
        """Advance an accepted plan after its runtime aggregate has been created."""
        with self._lock:
            record = self._owned_record(plan_id, owner_id)
            plan = record.plan
            if plan.status is PlanStatus.EXECUTING:
                return plan.model_copy(deep=True)
            accepted = plan.status is PlanStatus.APPROVED or (
                plan.status is PlanStatus.VALIDATED and not plan.approval_required
            )
            if not accepted:
                raise ExecutionPlanStateError(
                    PLAN_NOT_ACCEPTED,
                    "The execution plan must be validated and, when required, approved before it can run.",
                    details={
                        "plan_id": str(plan_id),
                        "status": plan.status.value,
                        "approval_required": plan.approval_required,
                    },
                )
            executing_payload = plan.model_dump(mode="python")
            executing_payload["status"] = PlanStatus.EXECUTING
            executing = type(plan).model_validate(executing_payload)
            self._records[plan_id] = _StoredPlan(
                owner_id=record.owner_id,
                workflow=record.workflow,
                plan=executing,
            )
            return executing.model_copy(deep=True)

    def _owned_record(self, plan_id: UUID, owner_id: str) -> _StoredPlan:
        record = self._records.get(plan_id)
        if record is None or record.owner_id != owner_id:
            message = f"Execution plan {plan_id} was not found"
            raise ExecutionPlanNotFoundError(message)
        return record

    def _create_plan_locked(
        self,
        workflow: WorkflowDefinition,
        *,
        owner_id: str,
        generated_by: str,
        predecessor_id: UUID | None,
    ) -> ExecutionPlan:
        key = (owner_id, workflow.workflow_definition_id)
        plan_version = self._versions.get(key, 0) + 1
        plan = self._compiler.compile(
            workflow.model_copy(deep=True),
            plan_version=plan_version,
            generated_by=generated_by,
            supersedes_plan_id=predecessor_id,
            authorization_subject=owner_id,
        )
        if predecessor_id is not None:
            predecessor = self._owned_record(predecessor_id, owner_id)
            superseded_payload = predecessor.plan.model_dump(mode="python")
            superseded_payload["status"] = PlanStatus.SUPERSEDED
            superseded = type(predecessor.plan).model_validate(superseded_payload)
            self._records[predecessor_id] = _StoredPlan(
                owner_id=predecessor.owner_id,
                workflow=predecessor.workflow,
                plan=superseded,
            )
        self._records[plan.execution_plan_id] = _StoredPlan(
            owner_id=owner_id,
            workflow=workflow.model_copy(deep=True),
            plan=plan.model_copy(deep=True),
        )
        self._versions[key] = plan_version
        self._latest_plan_ids[key] = plan.execution_plan_id
        return plan.model_copy(deep=True)

    def _regeneration_result(
        self,
        owner_id: str,
        predecessor_id: UUID,
        idempotency_key: str,
    ) -> ExecutionPlan | None:
        plan_id = self._regenerations.get((owner_id, predecessor_id, idempotency_key))
        if plan_id is None:
            return None
        return self._records[plan_id].plan.model_copy(deep=True)

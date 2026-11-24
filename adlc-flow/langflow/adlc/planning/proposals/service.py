"""Owner-scoped lifecycle for planner proposals.

States::

    GENERATED ──validate──► VALIDATED ──approve──► APPROVED (→ existing pipeline)
        │ │
        │ └──validate(fail)──► REVISION_REQUIRED ──(regenerate)──► new proposal
        └──reject────────────► REJECTED

The service composes the planner (proposal generation), the validator
(orchestrator authority), and the **existing** ``ExecutionPlanService`` for
materialization. It never touches runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from langflow.adlc.blueprints.models import PackageReference, WorkflowDefinition
from langflow.adlc.planning.proposals.errors import (
    ProposalNotFoundError,
    ProposalStateError,
)
from langflow.adlc.planning.proposals.expansion import build_expanded_workflow
from langflow.adlc.planning.proposals.models import (
    PLANNER_CONTRACT_VERSION,
    GeneratePlanProposalConfig,
    PlannerMode,
    PlanProposalLimits,
    ProposalStatus,
    ProposedPlan,
    ProposedTask,
)
from langflow.adlc.planning.proposals.validator import ProposalValidator

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import ExecutionPlan
    from langflow.adlc.packages.access import PackageAccessPolicy
    from langflow.adlc.planning.proposals.planner import PlannerAgent, PlannerOutput
    from langflow.adlc.planning.service import ExecutionPlanService


@dataclass(frozen=True, slots=True)
class _StoredProposal:
    owner_id: str
    proposal: ProposedPlan
    workflow: WorkflowDefinition


@dataclass(frozen=True, slots=True)
class ProposalApprovalResult:
    proposal: ProposedPlan
    execution_plan: ExecutionPlan


class ProposalService:
    """Lifecycle boundary between the Planner Agent and the orchestrator."""

    def __init__(
        self,
        planner: PlannerAgent,
        registry,
        execution_plan_service: ExecutionPlanService,
        *,
        limits: PlanProposalLimits | None = None,
        access_policy: PackageAccessPolicy | None = None,
    ) -> None:
        self._planner = planner
        self._registry = registry
        self._execution_plan_service = execution_plan_service
        self._limits = limits or PlanProposalLimits()
        self._access_policy = access_policy
        self._validator = ProposalValidator(registry, self._limits)
        self._records: dict[UUID, _StoredProposal] = {}
        self._versions: dict[tuple[str, UUID], int] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    async def generate_proposal(
        self,
        workflow: WorkflowDefinition,
        *,
        owner_id: str,
        generated_by: str,
        config: GeneratePlanProposalConfig | None = None,
    ) -> ProposedPlan:
        """Run the planner once and store the resulting GENERATED proposal."""
        config = config or GeneratePlanProposalConfig()
        limits = config.limits or self._limits
        mode = config.mode or self._planner.mode
        if mode is not self._planner.mode:
            message = (
                f"The configured planner only supports mode '{self._planner.mode.value}' "
                f"but '{mode.value}' was requested."
            )
            raise ProposalStateError(message, details={"requested": mode.value})
        packages = self._visible_packages(owner_id)
        output = await self._planner.generate(workflow, packages, limits)
        with self._lock:
            key = (owner_id, workflow.workflow_definition_id)
            version = self._versions.get(key, 0) + 1
            proposal_id = self._proposal_id(workflow, version, mode, owner_id=owner_id)
            proposal = self._assemble(
                proposal_id=proposal_id,
                proposal_version=version,
                workflow=workflow,
                generated_by=generated_by,
                mode=mode,
                output=output,
                supersedes=None,
            )
            self._records[proposal_id] = _StoredProposal(
                owner_id=owner_id,
                proposal=proposal,
                workflow=workflow.model_copy(deep=True),
            )
            self._versions[key] = version
            return proposal.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_proposal(self, proposal_id: UUID, *, owner_id: str) -> ProposedPlan:
        with self._lock:
            record = self._records.get(proposal_id)
            if record is None or record.owner_id != owner_id:
                msg = f"Plan proposal {proposal_id} was not found"
                raise ProposalNotFoundError(msg)
            return record.proposal.model_copy(deep=True)

    def list_proposals(self, *, owner_id: str, workflow_definition_id: UUID) -> list[ProposedPlan]:
        with self._lock:
            owned = [
                record.proposal
                for record in self._records.values()
                if record.owner_id == owner_id and record.proposal.workflow_definition_id == workflow_definition_id
            ]
        return sorted(owned, key=lambda proposal: proposal.proposal_version)

    # ------------------------------------------------------------------
    # Orchestrator validation
    # ------------------------------------------------------------------

    def validate_proposal(self, proposal_id: UUID, *, owner_id: str) -> ProposedPlan:
        """Run orchestrator validation and persist the resulting state."""
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            proposal = record.proposal
            workflow = record.workflow
            if proposal.status is ProposalStatus.VALIDATED:
                return proposal.model_copy(deep=True)
            if proposal.status is not ProposalStatus.GENERATED:
                msg = "Only a GENERATED proposal can be validated."
                raise ProposalStateError(
                    msg,
                    details={
                        "proposal_id": str(proposal_id),
                        "status": proposal.status.value,
                    },
                )
        errors, warnings = self._validator.validate(workflow, proposal)
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            payload = record.proposal.model_dump(mode="python")
            payload["validated_at"] = datetime.now(timezone.utc)
            if errors:
                payload["status"] = ProposalStatus.REVISION_REQUIRED
                payload["validation_errors"] = errors
            else:
                payload["status"] = ProposalStatus.VALIDATED
                payload["validation_errors"] = []
                payload["warnings"] = [*record.proposal.warnings, *warnings]
            validated = ProposedPlan.model_validate(payload)
            self._records[proposal_id] = _StoredProposal(
                owner_id=record.owner_id,
                proposal=validated,
                workflow=record.workflow,
            )
            return validated.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Revision / rejection
    # ------------------------------------------------------------------

    async def regenerate_proposal(
        self,
        proposal_id: UUID,
        *,
        owner_id: str,
        generated_by: str,
        config: GeneratePlanProposalConfig | None = None,
    ) -> ProposedPlan:
        """Create a successor proposal after validation feedback."""
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            predecessor = record.proposal
            workflow = record.workflow
            if predecessor.status in {ProposalStatus.APPROVED, ProposalStatus.REJECTED}:
                msg = "A terminal proposal cannot be regenerated."
                raise ProposalStateError(
                    msg,
                    details={
                        "proposal_id": str(proposal_id),
                        "status": predecessor.status.value,
                    },
                )
        config = config or GeneratePlanProposalConfig()
        mode = config.mode or self._planner.mode
        if mode is not self._planner.mode:
            message = (
                f"The configured planner only supports mode '{self._planner.mode.value}' "
                f"but '{mode.value}' was requested."
            )
            raise ProposalStateError(message, details={"requested": mode.value})
        packages = self._visible_packages(owner_id)
        output = await self._planner.generate(workflow, packages, config.limits or self._limits)
        with self._lock:
            key = (owner_id, workflow.workflow_definition_id)
            version = self._versions.get(key, 0) + 1
            successor_id = self._proposal_id(workflow, version, mode, owner_id=owner_id)
            successor = self._assemble(
                proposal_id=successor_id,
                proposal_version=version,
                workflow=workflow,
                generated_by=generated_by,
                mode=mode,
                output=output,
                supersedes=proposal_id,
            )
            self._records[successor_id] = _StoredProposal(
                owner_id=owner_id,
                proposal=successor,
                workflow=workflow.model_copy(deep=True),
            )
            self._versions[key] = version
            return successor.model_copy(deep=True)

    def reject_proposal(self, proposal_id: UUID, *, owner_id: str) -> ProposedPlan:
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            proposal = record.proposal
            if proposal.status in {ProposalStatus.APPROVED, ProposalStatus.REJECTED}:
                msg = "A terminal proposal cannot be rejected again."
                raise ProposalStateError(
                    msg,
                    details={
                        "proposal_id": str(proposal_id),
                        "status": proposal.status.value,
                    },
                )
            payload = proposal.model_dump(mode="python")
            payload["status"] = ProposalStatus.REJECTED
            payload["validated_at"] = payload.get("validated_at") or datetime.now(timezone.utc)
            rejected = ProposedPlan.model_validate(payload)
            self._records[proposal_id] = _StoredProposal(
                owner_id=record.owner_id,
                proposal=rejected,
                workflow=record.workflow,
            )
            return rejected.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Approval → existing pipeline
    # ------------------------------------------------------------------

    async def approve_proposal(
        self,
        proposal_id: UUID,
        *,
        owner_id: str,
        approved_by: str,
        comment: str | None = None,
    ) -> tuple[ProposedPlan, ExecutionPlan]:
        """Approve a validated proposal and materialize it via the existing pipeline."""
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            proposal = record.proposal
            workflow = record.workflow
            if proposal.status is not ProposalStatus.VALIDATED:
                msg = "Only a VALIDATED proposal can be approved."
                raise ProposalStateError(
                    msg,
                    details={
                        "proposal_id": str(proposal_id),
                        "status": proposal.status.value,
                        "validation_errors": [issue.code for issue in proposal.validation_errors],
                    },
                )
        expanded = build_expanded_workflow(workflow, proposal)
        plan = self._execution_plan_service.create_plan(
            expanded,
            owner_id=owner_id,
            generated_by=f"planner:{proposal.planner_mode.value.lower()}",
        )
        if plan.status.value == "INVALID":
            msg = "The approved proposal failed compilation against the package registry."
            raise ProposalStateError(
                msg,
                details={
                    "proposal_id": str(proposal_id),
                    "execution_plan_id": str(plan.execution_plan_id),
                    "validation_errors": [issue.code for issue in plan.validation_errors],
                },
            )
        if plan.approval_required:
            plan = self._execution_plan_service.approve_plan(
                plan.execution_plan_id,
                owner_id=owner_id,
                approved_by=approved_by,
                comment=comment or f"Approved via planner proposal {proposal_id}",
            )
        with self._lock:
            record = self._owned_record(proposal_id, owner_id)
            payload = record.proposal.model_dump(mode="python")
            payload["status"] = ProposalStatus.APPROVED
            payload["approved_by"] = approved_by
            payload["approved_at"] = datetime.now(timezone.utc)
            payload["materialized_plan_id"] = plan.execution_plan_id
            approved = ProposedPlan.model_validate(payload)
            self._records[proposal_id] = _StoredProposal(
                owner_id=record.owner_id,
                proposal=approved,
                workflow=record.workflow,
            )
            return approved.model_copy(deep=True), plan

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _owned_record(self, proposal_id: UUID, owner_id: str) -> _StoredProposal:
        record = self._records.get(proposal_id)
        if record is None or record.owner_id != owner_id:
            msg = f"Plan proposal {proposal_id} was not found"
            raise ProposalNotFoundError(msg)
        return record

    def _visible_packages(self, owner_id: str) -> list:
        return [
            registered.definition
            for registered in self._registry.list_packages()
            if self._access_policy is None
            or self._access_policy.can_view_package(
                owner_id,
                PackageReference(
                    package_id=registered.definition.package_id,
                    version=registered.definition.version,
                    content_digest=registered.content_digest,
                ),
            )
        ]

    def _proposal_id(
        self,
        workflow: WorkflowDefinition,
        version: int,
        mode: PlannerMode,
        *,
        owner_id: str,
    ) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            (
                f"adlc:plan-proposal:{owner_id}:{workflow.workflow_definition_id}:{workflow.version}:{version}:{mode.value}"
            ),
        )

    def _assemble(
        self,
        *,
        proposal_id: UUID,
        proposal_version: int,
        workflow: WorkflowDefinition,
        generated_by: str,
        mode: PlannerMode,
        output: PlannerOutput,
        supersedes: UUID | None,
    ) -> ProposedPlan:
        tasks = [
            ProposedTask(
                task_id=draft.task_id,
                source_stage_id=UUID(draft.source_stage_id),
                name=draft.name,
                description=draft.description,
                objective=draft.objective,
                parent_task_id=draft.parent_task_id,
                dependency_task_ids=list(draft.dependency_task_ids),
                assigned_package=PackageReference(
                    package_id=draft.package_id,
                    version=draft.package_version,
                ),
                expected_outputs=list(draft.expected_outputs),
                inputs=dict(draft.inputs),
                planning_rationale=draft.planning_rationale,
                priority=draft.priority,
                metadata={"stage_type": draft.stage_type},
            )
            for draft in output.tasks
        ]
        return ProposedPlan(
            proposal_id=proposal_id,
            workflow_definition_id=workflow.workflow_definition_id,
            workflow_definition_version=workflow.version,
            proposal_version=proposal_version,
            status=ProposalStatus.GENERATED,
            planner_mode=mode,
            planner_version=self._planner.version,
            tasks=tasks,
            validation_errors=[],
            warnings=list(output.warnings),
            assumptions=list(output.assumptions),
            clarifications=list(output.clarifications),
            generated_by=generated_by,
            generated_at=datetime.now(timezone.utc),
            supersedes_proposal_id=supersedes,
            metadata={
                "planner_contract_version": PLANNER_CONTRACT_VERSION,
                "planner_version": self._planner.version,
            },
        )

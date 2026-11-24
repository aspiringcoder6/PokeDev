"""Orchestrator-side validation of planner proposals.

The orchestrator is the authority: every planner proposal is treated as an
untrusted suggestion and re-checked here before it can be approved and fed
into the existing ``BlueprintCompiler`` pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from langflow.adlc.blueprints.errors import PackageRegistryError
from langflow.adlc.blueprints.models import PlanValidationIssue
from langflow.adlc.coding_agent import is_unified_coding_agent
from langflow.adlc.planning.proposals.models import (
    PlanProposalLimits,
    ProposedPlan,
    ProposedTask,
)

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import WorkflowDefinition, WorkflowStage
    from langflow.adlc.packages.registry import NodePackageRegistry


def _issue_key(issue: PlanValidationIssue) -> tuple[str, str, str]:
    return (issue.path or "", issue.code, issue.message)


class ProposalValidator:
    """Validate one proposal against its source workflow and the package registry."""

    def __init__(
        self,
        registry: NodePackageRegistry,
        limits: PlanProposalLimits | None = None,
    ) -> None:
        self._registry = registry
        self._limits = limits or PlanProposalLimits()

    def validate(
        self,
        workflow: WorkflowDefinition,
        proposal: ProposedPlan,
    ) -> tuple[list[PlanValidationIssue], list[PlanValidationIssue]]:
        """Return ``(errors, warnings)`` for the proposal."""
        errors: list[PlanValidationIssue] = []
        warnings: list[PlanValidationIssue] = []

        if not proposal.tasks:
            errors.append(
                PlanValidationIssue(
                    code="EMPTY_PROPOSAL",
                    message="The planner proposed no tasks.",
                    path="/tasks",
                    details={},
                )
            )
            return errors, warnings

        if len(proposal.tasks) > self._limits.max_tasks:
            errors.append(
                PlanValidationIssue(
                    code="TASK_LIMIT_EXCEEDED",
                    message=(
                        f"The proposal contains {len(proposal.tasks)} tasks which exceeds "
                        f"the configured maximum of {self._limits.max_tasks}."
                    ),
                    path="/tasks",
                    details={"proposed": len(proposal.tasks), "max": self._limits.max_tasks},
                )
            )

        source_stages = {stage.stage_id: stage for stage in workflow.stages}
        stage_ids = set(source_stages)
        stages_without_tasks = set(stage_ids)
        task_ids: set[str] = set()

        for task in proposal.tasks:
            path = f"/tasks/{task.task_id}"
            if task.task_id in task_ids:
                errors.append(
                    PlanValidationIssue(
                        code="DUPLICATE_TASK_ID",
                        message=f"Task ID '{task.task_id}' is proposed more than once.",
                        path=path,
                        details={"task_id": task.task_id},
                    )
                )
            task_ids.add(task.task_id)

            if task.source_stage_id not in stage_ids:
                errors.append(
                    PlanValidationIssue(
                        code="UNKNOWN_SOURCE_STAGE",
                        message=(
                            f"Task '{task.task_id}' references stage "
                            f"{task.source_stage_id} which is not part of the workflow."
                        ),
                        path=f"{path}/source_stage_id",
                        details={"task_id": task.task_id},
                    )
                )
            else:
                stages_without_tasks.discard(task.source_stage_id)

            if not task.name.strip() or not task.objective.strip():
                errors.append(
                    PlanValidationIssue(
                        code="INVALID_TASK_FIELD",
                        message=f"Task '{task.task_id}' needs a non-blank name and objective.",
                        path=path,
                        details={"task_id": task.task_id},
                    )
                )

            if not task.expected_outputs:
                errors.append(
                    PlanValidationIssue(
                        code="MISSING_EXPECTED_OUTPUTS",
                        message=f"Task '{task.task_id}' does not declare any expected output.",
                        path=f"{path}/expected_outputs",
                        details={"task_id": task.task_id},
                    )
                )

            if task.parent_task_id is not None and task.parent_task_id not in task_ids:
                # A parent declared later in the list is still valid; the second pass
                # re-checks once every task id is known.
                if task.parent_task_id not in {candidate.task_id for candidate in proposal.tasks}:
                    errors.append(
                        PlanValidationIssue(
                            code="INVALID_PARENT_TASK",
                            message=(
                                f"Task '{task.task_id}' references parent "
                                f"'{task.parent_task_id}' which is not a proposed task."
                            ),
                            path=f"{path}/parent_task_id",
                            details={"task_id": task.task_id, "parent": task.parent_task_id},
                        )
                    )

            package_errors = self._package_issues(task, path, source=source_stages.get(task.source_stage_id))
            errors.extend(package_errors)

        errors.extend(self._dependency_issues(proposal, task_ids))
        errors.extend(self._cycle_issues(proposal, task_ids))
        errors.extend(self._parent_cycle_issues(proposal))
        errors.extend(self._depth_issues(proposal))
        errors.extend(self._coding_agent_issues(workflow, proposal))

        for stage_id in sorted(stages_without_tasks, key=str):
            stage = next(candidate for candidate in workflow.stages if candidate.stage_id == stage_id)
            warnings.append(
                PlanValidationIssue(
                    code="STAGE_WITHOUT_TASKS",
                    message=f"Stage '{stage.name}' received no proposed tasks.",
                    path=f"/stages/{stage_id}",
                    details={"stage_id": str(stage_id)},
                )
            )

        return sorted(errors, key=_issue_key), sorted(warnings, key=_issue_key)

    @staticmethod
    def _coding_agent_issues(workflow: WorkflowDefinition, proposal: ProposedPlan) -> list[PlanValidationIssue]:
        issues = []
        for stage in workflow.stages:
            if not is_unified_coding_agent(stage.package_ref.package_id, stage.package_ref.version):
                continue
            tasks = [task for task in proposal.tasks if task.source_stage_id == stage.stage_id]
            loop = stage.configuration_overrides.get("task_loop_enabled") is True or "task_loop_spec" in stage.inputs
            if loop and len(tasks) != 1:
                issues.append(
                    PlanValidationIssue(
                        code="CODING_AGENT_LOOP_REQUIRES_ONE_TASK",
                        message="Keep the complete task loop specification in exactly one task.",
                        path=f"/stages/{stage.stage_id}",
                        details={},
                    )
                )
            issues.extend(
                PlanValidationIssue(
                    code="CODING_AGENT_OPTIONS_MUST_BE_PRESERVED",
                    message="Preserve the Coding Agent package and the original task loop specification.",
                    path=f"/tasks/{task.task_id}",
                    details={},
                )
                for task in tasks
                if (task.assigned_package.package_id, task.assigned_package.version)
                != (stage.package_ref.package_id, stage.package_ref.version)
                or (loop and task.inputs.get("task_loop_spec") != stage.inputs.get("task_loop_spec"))
            )
        return issues

    def _package_issues(
        self, task: ProposedTask, path: str, *, source: WorkflowStage | None = None
    ) -> list[PlanValidationIssue]:
        issues: list[PlanValidationIssue] = []
        reference = task.assigned_package
        try:
            registered = self._registry.get(reference)
        except PackageRegistryError as exc:
            issues.append(
                PlanValidationIssue(
                    code="UNKNOWN_PACKAGE",
                    message=(
                        f"Task '{task.task_id}' assigns package "
                        f"'{reference.package_id}@{reference.version}' which is not available."
                    ),
                    path=f"{path}/assigned_package",
                    details={"task_id": task.task_id, "registry_error": exc.code},
                )
            )
            return issues

        interface = registered.definition.interface
        loop = (
            source is not None
            and is_unified_coding_agent(reference.package_id, reference.version)
            and (source.configuration_overrides.get("task_loop_enabled") is True or "task_loop_spec" in source.inputs)
        )
        output_names = {slot.name for slot in interface.outputs}
        input_slots = {slot.name: slot for slot in interface.inputs}
        for output in task.expected_outputs:
            if output not in output_names:
                issues.append(
                    PlanValidationIssue(
                        code="UNKNOWN_EXPECTED_OUTPUT",
                        message=(
                            f"Task '{task.task_id}' expects output '{output}' which the "
                            f"package '{reference.package_id}' does not declare."
                        ),
                        path=f"{path}/expected_outputs",
                        details={"task_id": task.task_id, "output": output},
                    )
                )
        for input_name in sorted(task.inputs):
            if input_name not in input_slots:
                issues.append(
                    PlanValidationIssue(
                        code="UNKNOWN_TASK_INPUT",
                        message=(
                            f"Task '{task.task_id}' supplies input '{input_name}' which the "
                            f"package '{reference.package_id}' does not declare."
                        ),
                        path=f"{path}/inputs/{input_name}",
                        details={"task_id": task.task_id, "input": input_name},
                    )
                )
        for slot in interface.inputs:
            required = slot.name == "task_loop_spec" if loop else slot.required
            if required and slot.name not in task.inputs:
                issues.append(
                    PlanValidationIssue(
                        code="MISSING_REQUIRED_INPUT",
                        message=(
                            f"Task '{task.task_id}' does not fill the required input "
                            f"'{slot.name}' of package '{reference.package_id}'."
                        ),
                        path=f"{path}/inputs/{slot.name}",
                        details={"task_id": task.task_id, "input": slot.name},
                    )
                )
        return issues

    def _dependency_issues(
        self,
        proposal: ProposedPlan,
        task_ids: set[str],
    ) -> list[PlanValidationIssue]:
        issues: list[PlanValidationIssue] = []
        for task in proposal.tasks:
            for dependency in task.dependency_task_ids:
                if dependency != task.task_id and dependency not in task_ids:
                    issues.append(
                        PlanValidationIssue(
                            code="INVALID_DEPENDENCY",
                            message=(f"Task '{task.task_id}' depends on '{dependency}' which is not a proposed task."),
                            path=f"/tasks/{task.task_id}/dependency_task_ids",
                            details={"task_id": task.task_id, "dependency": dependency},
                        )
                    )
        return issues

    def _cycle_issues(
        self,
        proposal: ProposedPlan,
        task_ids: set[str],
    ) -> list[PlanValidationIssue]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for task in proposal.tasks:
            for dependency in task.dependency_task_ids:
                adjacency[task.task_id].append(dependency)

        state: dict[str, int] = {}
        stack: list[str] = []
        cycle_nodes: set[str] = set()

        def visit(node: str) -> None:
            state[node] = 1
            stack.append(node)
            for neighbor in adjacency.get(node, []):
                if neighbor not in task_ids:
                    continue
                marker = state.get(neighbor, 0)
                if marker == 1:
                    cycle_nodes.update(stack[stack.index(neighbor) :])
                elif marker == 0:
                    visit(neighbor)
            stack.pop()
            state[node] = 2

        for task_id in sorted(task_ids):
            if state.get(task_id, 0) == 0:
                visit(task_id)

        return [
            PlanValidationIssue(
                code="CIRCULAR_DEPENDENCY",
                message=f"Task '{task_id}' participates in a dependency cycle.",
                path=f"/tasks/{task_id}/dependency_task_ids",
                details={"task_id": task_id},
            )
            for task_id in sorted(cycle_nodes)
        ]

    def _parent_cycle_issues(self, proposal: ProposedPlan) -> list[PlanValidationIssue]:
        issues: list[PlanValidationIssue] = []
        tasks_by_id = {task.task_id: task for task in proposal.tasks}
        for task in proposal.tasks:
            seen: set[str] = set()
            current = task.parent_task_id
            while current is not None and current in tasks_by_id:
                if current == task.task_id or current in seen:
                    issues.append(
                        PlanValidationIssue(
                            code="PARENT_CYCLE",
                            message=f"Task '{task.task_id}' is part of a parent chain cycle.",
                            path=f"/tasks/{task.task_id}/parent_task_id",
                            details={"task_id": task.task_id},
                        )
                    )
                    break
                seen.add(current)
                current = tasks_by_id[current].parent_task_id
        return issues

    def _depth_issues(self, proposal: ProposedPlan) -> list[PlanValidationIssue]:
        issues: list[PlanValidationIssue] = []
        tasks_by_id = {task.task_id: task for task in proposal.tasks}
        depth_cache: dict[str, int] = {}

        def depth_of(task_id: str, visiting: frozenset[str] = frozenset()) -> int:
            # Untrusted parent cycles are already reported above; do not recurse forever.
            if task_id in visiting:
                return self._limits.max_depth + 1
            cached = depth_cache.get(task_id)
            if cached is not None:
                return cached
            parent_id = tasks_by_id[task_id].parent_task_id
            if parent_id is None or parent_id not in tasks_by_id:
                depth_cache[task_id] = 1
                return 1
            value = depth_of(parent_id, visiting | {task_id}) + 1
            depth_cache[task_id] = value
            return value

        for task in proposal.tasks:
            level = depth_of(task.task_id)
            if level > self._limits.max_depth:
                issues.append(
                    PlanValidationIssue(
                        code="DEPTH_LIMIT_EXCEEDED",
                        message=(
                            f"Task '{task.task_id}' sits at depth {level} which exceeds the "
                            f"configured maximum of {self._limits.max_depth}."
                        ),
                        path=f"/tasks/{task.task_id}/parent_task_id",
                        details={"task_id": task.task_id, "depth": level},
                    )
                )
        return issues

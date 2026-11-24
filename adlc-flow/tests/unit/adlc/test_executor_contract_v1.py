# ruff: noqa: INP001, PLR2004, S101, SLF001

"""Executor contract v1: capability mock executors plus a 3-task mini run.

Proves the control-plane/execution contract from
``docs/reference/hop-dong-executor.md``:

* future executors only implement the stable ``AgentAdapter`` protocol to
  plug in behind the ``TaskExecutorRouter``;
* routing happens by ``ExecutorTarget.service`` with declared
  capabilities, so two different executors serve one DAG;
* the optional ``executor_contract`` travels from task-definition
  constraints through dispatch to the executor;
* ``TaskResult`` returns summary + artifacts only — never conversation
  or data outside the contract.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_capability_executors import (
    CONTRACT_OUTPUT_KEYS,
    DSH_LIKE_SERVICE,
    OPENCODE_LIKE_SERVICE,
    create_dsh_like_executor,
    create_opencode_like_executor,
)
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.models import (
    AdlcTaskDefinition,
    CreateWorkflowRunRequest,
    ExecutorContract,
    ExecutorTarget,
    MockArtifactSpec,
    TaskRequest,
    TaskResult,
    TaskResultStatus,
    WorkflowRunStatus,
)
from langflow.adlc.run_repository import InMemoryRunRepository
from langflow.adlc.run_service import AdlcRunService

_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "messages",
        "conversation",
        "conversation_history",
        "transcript",
        "subagent",
        "subagents",
        "subagent_log",
        "tool_calls",
        "llm_output",
    }
)


def _definition(
    key: str,
    *,
    service: str,
    task_type: str,
    dependencies: list[str] | None = None,
    contract: dict[str, Any] | None = None,
) -> AdlcTaskDefinition:
    constraints: dict[str, Any] = {}
    if contract is not None:
        constraints["executor_contract"] = contract
    return AdlcTaskDefinition(
        id=uuid4(),
        key=key,
        name=key.replace("_", " ").title(),
        task_type=task_type,
        dependencies=dependencies or [],
        predetermined_output={"summary": f"Result for {key}."},
        artifact=MockArtifactSpec(kind="DOCUMENT", name=f"{key}.txt", media_type="text/plain", content=key),
        delay_ms=0,
        executor_target=ExecutorTarget(service=service, operation=task_type.lower()),
        constraints=constraints,
    )


def _request(**overrides: Any) -> TaskRequest:
    payload: dict[str, Any] = {
        "request_id": uuid4(),
        "workflow_run_id": uuid4(),
        "task_run_id": uuid4(),
        "attempt_id": uuid4(),
        "task_definition_id": uuid4(),
        "task_type": "CODE_GENERATION",
        "name": "Contract task",
        "executor": ExecutorTarget(service=OPENCODE_LIKE_SERVICE, operation="coding-task"),
        "input": {},
        "dependency_task_run_ids": [],
        "requested_at": datetime.now(timezone.utc),
        "idempotency_key": str(uuid4()),
    }
    payload.update(overrides)
    return TaskRequest(**payload)


def _result_envelope(output: dict[str, Any]) -> dict[str, Any]:
    """Contract-shaped TaskResult payload used for schema-level assertions."""
    now = datetime.now(timezone.utc)
    return {
        "request_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "task_run_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "status": "SUCCEEDED",
        "output": output,
        "artifacts": [],
        "error": None,
        "metrics": {"duration_ms": 1},
        "started_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "metadata": {},
    }


class TestCapabilityMockExecutors:
    def test_declare_unique_service_and_capabilities(self) -> None:
        opencode_like = create_opencode_like_executor()
        dsh_like = create_dsh_like_executor()

        assert opencode_like.service_name == OPENCODE_LIKE_SERVICE
        assert opencode_like.capabilities == ("code_generation",)
        assert dsh_like.service_name == DSH_LIKE_SERVICE
        assert dsh_like.capabilities == ("security_scan",)
        services = {opencode_like.service_name, dsh_like.service_name, MockExecutor().service_name}
        assert len(services) == 3, "each executor must own a unique service name"

    def test_output_schema_admits_summary_only(self) -> None:
        result = TaskResult.model_validate(_result_envelope({"summary": "done"}))

        assert set(result.output) <= CONTRACT_OUTPUT_KEYS


class TestExecutorContractField:
    def test_contract_field_optional_and_backward_compatible(self) -> None:
        request = _request()

        assert request.executor_contract is None

    def test_typed_contract_field_accepted(self) -> None:
        contract = ExecutorContract(
            allowed_paths=["src/", "tests/"],
            denied_permissions=["shell", "network"],
            cost_tier="medium",
        )
        request = _request(executor_contract=contract)

        assert request.executor_contract == contract

    def test_contract_lifted_from_constraints_for_run_service_requests(self) -> None:
        request = _request(
            constraints={"executor_contract": {"allowed_paths": ["src/"], "cost_tier": "cheap"}}
        )

        assert request.executor_contract is not None
        assert request.executor_contract.allowed_paths == ["src/"]
        assert request.executor_contract.denied_permissions == []
        assert request.executor_contract.cost_tier == "cheap"

    def test_typed_field_wins_over_constraints(self) -> None:
        typed = ExecutorContract(allowed_paths=["docs/"])
        request = _request(
            executor_contract=typed,
            constraints={"executor_contract": {"allowed_paths": ["src/"]}},
        )

        assert request.executor_contract == typed

    def test_rejects_absolute_or_escaping_paths(self) -> None:
        with pytest.raises(ValueError, match="repository-relative"):
            ExecutorContract(allowed_paths=["/etc/passwd"])
        with pytest.raises(ValueError, match="repository-relative"):
            ExecutorContract(allowed_paths=["src/../.."])

    def test_rejects_invalid_permission_words(self) -> None:
        with pytest.raises(ValueError, match="simple words"):
            ExecutorContract(denied_permissions=["run shell"])


class TestThreeTaskContractRun:
    """One run, three tasks, two capability executors, one shared DAG."""

    @pytest.fixture
    def opencode_like(self) -> Any:
        return create_opencode_like_executor()

    @pytest.fixture
    def dsh_like(self) -> Any:
        return create_dsh_like_executor()

    @pytest.fixture
    def executed_run(self, opencode_like: Any, dsh_like: Any) -> tuple[Any, Any, Any]:
        router = TaskExecutorRouter(
            MockExecutor(),
            routes={OPENCODE_LIKE_SERVICE: opencode_like, DSH_LIKE_SERVICE: dsh_like},
        )
        service = AdlcRunService(router, repository=InMemoryRunRepository())
        flow_id = uuid4()
        definitions = [
            _definition(
                "generate_patch",
                service=OPENCODE_LIKE_SERVICE,
                task_type="CODE_GENERATION",
                contract={
                    "allowed_paths": ["src/"],
                    "denied_permissions": ["shell"],
                    "cost_tier": "medium",
                },
            ),
            _definition(
                "security_scan",
                service=DSH_LIKE_SERVICE,
                task_type="SECURITY_SCAN",
                contract={"denied_permissions": ["write", "network"]},
            ),
            _definition(
                "integrate_results",
                service=OPENCODE_LIKE_SERVICE,
                task_type="CODE_GENERATION",
                dependencies=["generate_patch", "security_scan"],
            ),
        ]
        run = asyncio.run(
            service.start_run(
                flow_id=flow_id,
                flow_name="Executor contract v1",
                definitions=definitions,
                request=CreateWorkflowRunRequest(flowId=flow_id, executionMode="LEGACY_FLOW", delayMs=0),
                owner_id="contract-v1-test",
            )
        )
        return run, opencode_like, dsh_like

    def test_run_succeeds(self, executed_run: tuple[Any, Any, Any]) -> None:
        run, _, _ = executed_run

        assert run.status is WorkflowRunStatus.SUCCEEDED
        assert all(task.status.value == "SUCCEEDED" for task in run.tasks)

    def test_dag_runs_in_dependency_order(self, executed_run: tuple[Any, Any, Any]) -> None:
        run, _, _ = executed_run
        tasks_by_key = {task.key: task for task in run.tasks}

        generate = tasks_by_key["generate_patch"]
        scan = tasks_by_key["security_scan"]
        integrate = tasks_by_key["integrate_results"]

        assert set(integrate.dependency_task_run_ids) == {generate.id, scan.id}
        assert integrate.completed_at >= generate.completed_at
        assert integrate.completed_at >= scan.completed_at

    def test_results_routed_to_declared_service(self, executed_run: tuple[Any, Any, Any]) -> None:
        run, opencode_like, dsh_like = executed_run
        tasks_by_key = {task.key: task for task in run.tasks}

        assert tasks_by_key["generate_patch"].executor.service == OPENCODE_LIKE_SERVICE
        assert tasks_by_key["security_scan"].executor.service == DSH_LIKE_SERVICE
        assert tasks_by_key["integrate_results"].executor.service == OPENCODE_LIKE_SERVICE

        seen_by_service: dict[str, set[str]] = {
            OPENCODE_LIKE_SERVICE: set(),
            DSH_LIKE_SERVICE: set(),
        }
        for adapter in (opencode_like, dsh_like):
            for request in adapter.agent_adapter.executed_requests:
                seen_by_service[adapter.service_name].add(request.name)

        assert seen_by_service[OPENCODE_LIKE_SERVICE] == {"Generate Patch", "Integrate Results"}
        assert seen_by_service[DSH_LIKE_SERVICE] == {"Security Scan"}

    def test_contract_travels_from_definition_to_executor(self, executed_run: tuple[Any, Any, Any]) -> None:
        run, opencode_like, dsh_like = executed_run
        tasks_by_key = {task.key: task for task in run.tasks}

        generate_request = tasks_by_key["generate_patch"].request
        assert generate_request is not None
        assert generate_request.executor_contract is not None
        assert generate_request.executor_contract.allowed_paths == ["src/"]
        assert generate_request.executor_contract.denied_permissions == ["shell"]
        assert generate_request.executor_contract.cost_tier == "medium"

        generate_result = tasks_by_key["generate_patch"].result
        assert generate_result.metadata["contract_allowed_paths"] == ["src/"]
        assert generate_result.metadata["contract_denied_permissions"] == ["shell"]
        assert generate_result.metadata["contract_cost_tier"] == "medium"

        scan_result = tasks_by_key["security_scan"].result
        assert scan_result.metadata["contract_denied_permissions"] == ["write", "network"]
        assert scan_result.metadata["contract_allowed_paths"] == []
        assert scan_result.metadata["contract_cost_tier"] is None

        integrate_result = tasks_by_key["integrate_results"].result
        assert integrate_result.metadata["contract_allowed_paths"] == []
        assert tasks_by_key["integrate_results"].request.executor_contract is None

        assert len(opencode_like.agent_adapter.seen_contracts) == 2
        assert len(dsh_like.agent_adapter.seen_contracts) == 1

    def test_task_results_carry_only_summary_and_artifacts(self, executed_run: tuple[Any, Any, Any]) -> None:
        run, _, _ = executed_run

        for task in run.tasks:
            result = task.result
            assert result is not None
            assert result.status is TaskResultStatus.SUCCEEDED
            assert set(result.output) == {"summary"}, f"{task.key} output must be summary-only"
            assert not _FORBIDDEN_RESULT_KEYS & set(result.metadata)
            for artifact in result.artifacts:
                assert artifact.producer == task.executor.service

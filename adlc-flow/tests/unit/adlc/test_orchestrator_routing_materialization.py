# ruff: noqa: PLR2004, S101
"""Routing-seam tests for the orchestrator routing flag (plan package G2).

Covers:
a. ``orchestrator:auto`` + matching capability → the capable plugin wins.
b. two capable plugins → the first registered one wins (unit-level order tie-break,
   see test_orchestrator_routing.py).
c. no capable plugin → NO_CAPABLE_PLUGIN, the plan does not materialize.
d. flag off → legacy behavior intact (literal adapter_ref, no routing metadata),
   and user-routed tasks keep their explicit service.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from langflow.adlc.blueprints.models import PlanStatus
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.orchestrator_routing import ORCHESTRATOR_ROUTING_ENV
from langflow.adlc.packages.access import InMemoryPackageAccessPolicy
from langflow.adlc.packages.defaults import (
    DEFAULT_PACKAGE_IDENTITIES,
    KNOWN_REFERENCE_IDS,
    MOCK_REFERENCE_IDS,
    create_default_package_resolver,
)
from langflow.adlc.packages.registry import RepositoryNodePackageRegistry
from langflow.adlc.packages.resolver import NodePackageResolver, StaticReferenceRegistry
from langflow.adlc.planning.compiler import BlueprintCompiler
from langflow.adlc.planning.errors import PLAN_NO_CAPABLE_PLUGIN, ExecutionPlanStateError
from langflow.adlc.planning.materializer import ExecutionPlanMaterializer
from langflow.adlc.planning.parser import BlueprintParseContext, parse_blueprint_flow
from langflow.adlc.planning.service import ExecutionPlanService
from langflow.adlc.run_service import AdlcRunService

FIXED_TIME = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)

AUTO_PACKAGE_ID = "orchestrator-auto"
AUTO_ADAPTER_REF = "orchestrator:auto"
#: Reference doubling as a semantic AgentCapability value so the fixture
#: package's ExecutorTarget.capabilities carries ``code_generation``.
CAPABILITY_REF = "code_generation"

FIXTURE_REFERENCES = MOCK_REFERENCE_IDS | {AUTO_ADAPTER_REF, CAPABILITY_REF}
FIXTURE_PACKAGES = DEFAULT_PACKAGE_IDENTITIES | {(AUTO_PACKAGE_ID, "0.1.0")}


def _orchestrator_auto_package_json(*, provider_ref: str) -> str:
    """Minimal published AGENT package whose adapter_ref is orchestrator:auto."""
    return json.dumps(
        {
            "schema_version": "0.1",
            "package_id": AUTO_PACKAGE_ID,
            "version": "0.1.0",
            "status": "PUBLISHED",
            "name": "Orchestrator Auto (test fixture)",
            "description": "Routes its executor through orchestrator:auto.",
            "kind": "AGENT",
            "interface": {
                "inputs": [
                    {
                        "name": "requirement",
                        "schema_ref": "adlc://schemas/requirement/0.1",
                        "required": True,
                        "multiple": False,
                        "description": "The scoped requirement.",
                    }
                ],
                "outputs": [
                    {
                        "name": "source_patch",
                        "schema_ref": "adlc://schemas/source-patch/0.1",
                        "required": True,
                        "multiple": False,
                        "description": "The mock artifact.",
                    }
                ],
            },
            "configuration_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "delay_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                    "simulate_failure": {"type": "boolean"},
                    "artifact_name": {"type": "string", "minLength": 1, "maxLength": 255},
                },
                "required": ["delay_ms", "simulate_failure", "artifact_name"],
            },
            "defaults": {
                "delay_ms": 0,
                "simulate_failure": False,
                "artifact_name": "mock-auto-result.txt",
            },
            "override_allowlist": ["/configuration/delay_ms"],
            "implementation": {
                "adapter_type": "AGENT_PROVIDER",
                "adapter_ref": AUTO_ADAPTER_REF,
                "entrypoint": "mock-task",
            },
            "execution_profile": {
                "provider_ref": provider_ref,
                "model_ref": "model:mock/deterministic",
                "system_prompt_ref": "prompt:coding-agent/0.1.0",
                "rule_set_refs": ["rules:adlc-safe-execution/0.1.0"],
                "hook_refs": ["hook:task-lifecycle/0.1.0"],
                "capabilities": {
                    "tool_refs": ["tool:mock-artifact"],
                    "skill_refs": [],
                    "plugin_refs": [],
                    "mcp_server_refs": [],
                },
                "memory_policy_ref": "memory:mock-task-context/0.1.0",
                "sandbox_policy_ref": "sandbox:mock-workspace/0.1.0",
                "secret_refs": {},
            },
            "default_policies": {
                "retry": {"max_attempts": 1},
                "timeout_ms": 120000,
                "approval": {"gate_type": None},
                "permissions": {"mode": "PACKAGE_ALLOWLIST"},
                "resources": {},
                "runtime_overridable": ["/configuration/simulate_failure"],
            },
            "compatibility": {
                "engine": {"minimum_version": "0.1.0"},
                "execution_contract_versions": ["0.1"],
            },
            "metadata": {"maintainer": "adlc-tests", "provider_mode": "mock"},
        }
    )


def _stage(index: int, *, name: str, package_id: str) -> dict:
    return {
        "id": f"stage-{index}",
        "type": "adlcStageNode",
        "position": {"x": index * 220, "y": 0},
        "data": {
            "adlc": {
                "document_type": "WORKFLOW_STAGE",
                "schema_version": "0.1",
                "stage_id": str(uuid4()),
                "stage_type": "IMPLEMENTATION",
                "name": name,
                "objective": f"Complete {name.lower()}.",
                "inputs": {"requirement": f"Mock requirement for {name}."},
                "expected_outputs": ["source_patch"],
                "package_ref": {"package_id": package_id, "version": "0.1.0"},
                "configuration_overrides": {"delay_ms": 0},
            }
        },
    }


def _graph(flow_id, *, auto_provider_ref: str) -> dict:
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(flow_id),
            "version": 1,
        },
        "nodes": [
            _stage(1, name="Auto Routed Step", package_id=AUTO_PACKAGE_ID),
            _stage(2, name="Mock Step", package_id="coding-agent"),
        ],
        # Independent stages: both dispatch immediately so their frozen
        # request metadata is observable regardless of the other's outcome.
        "edges": [],
    }


def _plan_service(tmp_path, flow_id, *, auto_provider_ref: str) -> tuple[ExecutionPlanService, object]:
    """Compile a plan whose first stage uses the orchestrator:auto package."""
    from langflow.adlc.packages.defaults import default_node_package_root

    package_root = tmp_path / "packages"
    package_dir = package_root / AUTO_PACKAGE_ID / "0.1.0"
    package_dir.mkdir(parents=True)
    (package_dir / "package.json").write_text(
        _orchestrator_auto_package_json(provider_ref=auto_provider_ref)
    )
    # Include the default mock packages so mixed graphs still compile.
    shutil.copytree(
        default_node_package_root() / "coding-agent" / "0.1.0",
        package_root / "coding-agent" / "0.1.0",
    )
    registry = RepositoryNodePackageRegistry(package_root)
    policy = InMemoryPackageAccessPolicy(
        default_visible_packages=FIXTURE_PACKAGES,
        default_authorized_references=FIXTURE_REFERENCES,
    )
    resolver = NodePackageResolver(
        registry,
        StaticReferenceRegistry(KNOWN_REFERENCE_IDS | FIXTURE_REFERENCES),
        access_policy=policy,
    )
    context = BlueprintParseContext(
        flow_id=flow_id,
        project_id=uuid4(),
        name="Orchestrator routing fixture",
        description="Routing seam test.",
        created_by="owner-1",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    workflow = parse_blueprint_flow(
        _graph(flow_id, auto_provider_ref=auto_provider_ref),
        context,
    )
    service = ExecutionPlanService(BlueprintCompiler(resolver))
    plan = service.create_plan(workflow, owner_id="owner-1", generated_by="owner-1")
    return service, plan


def _materialize(service: ExecutionPlanService, plan) -> object:
    """Approve (when required) and materialize one run through the routing seam."""
    if plan.approval_required:
        service.approve_plan(
            plan.execution_plan_id,
            owner_id="owner-1",
            approved_by="owner-1",
            comment="Routing seam test.",
        )
    mock_executor = MockExecutor()
    run_service = AdlcRunService(
        TaskExecutorRouter(mock_executor, routes={"agent-provider:mock": mock_executor})
    )
    materializer = ExecutionPlanMaterializer()
    return asyncio.run(
        materializer.materialize(
            plan.execution_plan_id,
            idempotency_key="routing-seam-run-1",
            owner_id="owner-1",
            plan_service=service,
            run_service=run_service,
            access_policy=InMemoryPackageAccessPolicy(
                default_visible_packages=FIXTURE_PACKAGES,
                default_authorized_references=FIXTURE_REFERENCES,
            ),
        )
    )


class TestOrchestratorAutoMaterialization:
    def test_auto_ref_with_matching_capability_selects_monarch(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(a) orchestrator:auto + code_generation → plugin monarch wins."""
        monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, "1")
        service, plan = _plan_service(tmp_path, uuid4(), auto_provider_ref=CAPABILITY_REF)
        run = _materialize(service, plan)

        auto_task = next(task for task in run.tasks if task.name == "Auto Routed Step")
        assert auto_task.request is not None
        assert auto_task.request.executor.service == "monarch"
        assert auto_task.request.metadata["routing_source"] == "orchestrator"
        routing = auto_task.request.metadata["routing"]
        assert routing["adapter_ref"] == "orchestrator:auto"
        assert routing["plugin_id"] == "monarch"
        assert routing["capabilities"] == ["code_generation"]

    def test_user_routed_task_keeps_explicit_service(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit executor references stay user-routed while the flag is on."""
        monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, "1")
        service, plan = _plan_service(tmp_path, uuid4(), auto_provider_ref=CAPABILITY_REF)
        run = _materialize(service, plan)

        mock_task = next(task for task in run.tasks if task.name == "Mock Step")
        assert mock_task.request is not None
        assert mock_task.request.executor.service == "agent-provider:mock"
        assert mock_task.request.metadata["routing_source"] == "user"
        assert "routing" not in mock_task.request.metadata

    def test_no_capable_plugin_blocks_materialization(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(c) no recognizable capability → NO_CAPABLE_PLUGIN, plan not materialized."""
        monkeypatch.setenv(ORCHESTRATOR_ROUTING_ENV, "1")
        service, plan = _plan_service(
            tmp_path, uuid4(), auto_provider_ref="agent-provider:mock"
        )
        with pytest.raises(ExecutionPlanStateError) as excinfo:
            _materialize(service, plan)
        assert excinfo.value.code == PLAN_NO_CAPABLE_PLUGIN
        # The plan snapshot stays untouched and never reached EXECUTING.
        stored = service.get_plan(plan.execution_plan_id, owner_id="owner-1")
        assert stored.status is PlanStatus.VALIDATED

    def test_flag_off_keeps_legacy_routing_intact(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) flag off → literal adapter_ref, no routing metadata at all."""
        monkeypatch.delenv(ORCHESTRATOR_ROUTING_ENV, raising=False)
        service, plan = _plan_service(tmp_path, uuid4(), auto_provider_ref=CAPABILITY_REF)
        run = _materialize(service, plan)

        auto_task = next(task for task in run.tasks if task.name == "Auto Routed Step")
        assert auto_task.request is not None
        assert auto_task.request.executor.service == "orchestrator:auto"
        assert "routing_source" not in auto_task.request.metadata
        assert "routing" not in auto_task.request.metadata

        mock_task = next(task for task in run.tasks if task.name == "Mock Step")
        assert mock_task.request is not None
        assert mock_task.request.executor.service == "agent-provider:mock"
        assert "routing_source" not in mock_task.request.metadata

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from langflow.adlc.blueprints import (
    ExecutionPlan,
    PackageReference,
    PackageResolutionError,
    StagePosition,
    WorkflowDefinition,
    WorkflowStage,
)
from langflow.adlc.observability import (
    AdlcObservationOutcome,
    AdlcObservationType,
    InMemoryAdlcObservabilitySink,
)
from langflow.adlc.packages import (
    NodePackageResolver,
    RepositoryNodePackageRegistry,
    StaticReferenceRegistry,
)

WORKFLOW_ID = UUID("11111111-1111-4111-8111-111111111111")
STAGE_ID = UUID("22222222-2222-4222-8222-222222222222")
RESOLVED_AT = datetime(2026, 9, 8, tzinfo=timezone.utc)
MOCK_REFERENCES = frozenset(
    {
        "agent-provider:mock",
        "control:approval",
        "hook:task-lifecycle/0.1.0",
        "memory:mock-task-context/0.1.0",
        "model:mock/deterministic",
        "prompt:coding-agent/0.1.0",
        "rules:adlc-safe-execution/0.1.0",
        "sandbox:mock-workspace/0.1.0",
        "tool:mock-artifact",
    }
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolver(
    *,
    references=MOCK_REFERENCES,
    engine_version="0.1.0",
    observability_sink=None,
) -> NodePackageResolver:
    registry = RepositoryNodePackageRegistry(_repository_root() / "adlc_components" / "packages")
    return NodePackageResolver(
        registry,
        StaticReferenceRegistry(frozenset(references)),
        engine_version=engine_version,
        observability_sink=observability_sink,
    )


def _stage(**updates) -> WorkflowStage:
    values = {
        "stage_id": STAGE_ID,
        "stage_type": "IMPLEMENTATION",
        "name": "Implement",
        "objective": "Implement the approved requirement.",
        "inputs": {"requirement": "Implement the approved requirement."},
        "expected_outputs": ["source_patch"],
        "package_ref": PackageReference(package_id="coding-agent", version="0.1.0"),
        "configuration_overrides": {"delay_ms": 10},
        "execution_profile_overrides": {},
        "policy_overrides": {},
        "secret_refs": {},
        "position": StagePosition(x=80, y=120),
        "metadata": {},
    }
    values.update(updates)
    return WorkflowStage.model_validate(values)


def _resolve(stage: WorkflowStage, resolver: NodePackageResolver | None = None, **kwargs):
    return (resolver or _resolver()).resolve(
        stage,
        workflow_definition_id=WORKFLOW_ID,
        workflow_definition_version=1,
        resolved_at=RESOLVED_AT,
        **kwargs,
    )


def test_resolver_applies_defaults_and_allowed_overrides() -> None:
    spec = _resolve(
        _stage(policy_overrides={"timeout_ms": 90000}),
        workflow_policy_overrides={"timeout_ms": 100000},
    )

    assert spec.configuration == {
        "artifact_name": "mock-source-patch.diff",
        "delay_ms": 10,
        "simulate_failure": False,
    }
    assert spec.policies.timeout_ms == 90000
    assert spec.package_ref.content_digest == (
        "sha256:525f8a3b9f90502064e7315e504385c7c3684427cc4bdab99956b187f96d2305"
    )
    assert spec.resolved_digest == "sha256:5ae55a87a476ea355b7bab780551ef7680a40dbd6e602878e3f915530c5dd9c2"


def test_runtime_overrides_use_the_separate_runtime_allowlist() -> None:
    spec = _resolve(
        _stage(),
        runtime_overrides={
            "configuration": {"simulate_failure": True},
            "policies": {"timeout_ms": 500},
        },
    )

    assert spec.configuration["simulate_failure"] is True
    assert spec.policies.timeout_ms == 500


def test_forbidden_stage_override_has_a_stable_error() -> None:
    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(configuration_overrides={"temperature": 0.5}))

    assert exc_info.value.code == "PACKAGE_OVERRIDE_FORBIDDEN"
    assert exc_info.value.path == "/configuration/temperature"


def test_forbidden_runtime_override_is_not_granted_by_stage_allowlist() -> None:
    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(), runtime_overrides={"configuration": {"artifact_name": "changed.diff"}})

    assert exc_info.value.code == "PACKAGE_OVERRIDE_FORBIDDEN"
    assert exc_info.value.path == "/configuration/artifact_name"


def test_allowed_but_invalid_configuration_has_a_stable_error() -> None:
    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(configuration_overrides={"delay_ms": "slow"}))

    assert exc_info.value.code == "PACKAGE_CONFIGURATION_INVALID"
    assert exc_info.value.path == "/configuration/delay_ms"


def test_raw_secrets_are_rejected_before_plan_snapshotting() -> None:
    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(configuration_overrides={"api_key": "do-not-store-this"}))

    assert exc_info.value.code == "RAW_SECRET_FORBIDDEN"
    assert exc_info.value.path == "/configuration/api_key"


def test_failed_resolution_observation_exposes_only_a_stable_error_code() -> None:
    sink = InMemoryAdlcObservabilitySink()
    sentinel_value = "must-not-appear-in-the-observation"

    with pytest.raises(PackageResolutionError):
        _resolve(
            _stage(configuration_overrides={"api_key": sentinel_value}),
            resolver=_resolver(observability_sink=sink),
        )

    observation = sink.observations[-1]
    serialized = json.dumps(observation.model_dump(mode="json"))
    assert observation.event_type is AdlcObservationType.PACKAGE_RESOLUTION_COMPLETED
    assert observation.outcome is AdlcObservationOutcome.FAILED
    assert observation.error_code == "RAW_SECRET_FORBIDDEN"
    assert observation.source_workflow_stage_id == STAGE_ID
    assert sentinel_value not in serialized
    assert "Implement the approved requirement" not in serialized


def test_opaque_secret_references_are_preserved_without_resolution() -> None:
    spec = _resolve(_stage(secret_refs={"OPENAI_API_KEY": "secret:project/openai"}))

    assert spec.secret_refs == {"OPENAI_API_KEY": "secret:project/openai"}


def test_missing_trusted_reference_blocks_resolution() -> None:
    references = MOCK_REFERENCES - {"tool:mock-artifact"}

    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(), resolver=_resolver(references=references))

    assert exc_info.value.code == "CAPABILITY_NOT_REGISTERED"
    assert exc_info.value.details["reference"] == "tool:mock-artifact"


def test_incompatible_engine_blocks_resolution() -> None:
    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(), resolver=_resolver(engine_version="0.0.9"))

    assert exc_info.value.code == "PACKAGE_INCOMPATIBLE"


def test_resolved_digest_excludes_canvas_position_and_resolution_time() -> None:
    first = _resolve(_stage(position=StagePosition(x=0, y=0)))
    second = _resolver().resolve(
        _stage(position=StagePosition(x=999, y=-200)),
        workflow_definition_id=WORKFLOW_ID,
        workflow_definition_version=1,
        resolved_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )

    assert first.resolved_digest == second.resolved_digest
    assert first.resolved_node_spec_id == second.resolved_node_spec_id


def test_deprecated_package_requires_an_explicit_resolver_opt_in(tmp_path) -> None:
    source = _repository_root() / "adlc_components" / "packages" / "coding-agent" / "0.1.0" / "package.json"
    payload = deepcopy(json.loads(source.read_text(encoding="utf-8")))
    payload["status"] = "DEPRECATED"
    package_directory = tmp_path / "coding-agent" / "0.1.0"
    package_directory.mkdir(parents=True)
    (package_directory / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    resolver = NodePackageResolver(
        RepositoryNodePackageRegistry(tmp_path),
        StaticReferenceRegistry(MOCK_REFERENCES),
    )

    with pytest.raises(PackageResolutionError) as exc_info:
        _resolve(_stage(), resolver=resolver)

    assert exc_info.value.code == "PACKAGE_DEPRECATED"


def test_plan_example_snapshots_match_current_package_resolution() -> None:
    examples = _repository_root() / "adlc-contracts" / "workflow" / "v0.1" / "examples"
    workflow = WorkflowDefinition.model_validate_json(
        (examples / "workflow-definition.json").read_text(encoding="utf-8")
    )
    plan = ExecutionPlan.model_validate_json((examples / "execution-plan.json").read_text(encoding="utf-8"))
    resolver = _resolver()
    resolved = [
        resolver.resolve(
            stage,
            workflow_definition_id=workflow.workflow_definition_id,
            workflow_definition_version=workflow.version,
            workflow_policy_overrides=workflow.default_policies,
            resolved_at=RESOLVED_AT,
        )
        for stage in workflow.stages
    ]

    assert resolved == plan.resolved_node_specs

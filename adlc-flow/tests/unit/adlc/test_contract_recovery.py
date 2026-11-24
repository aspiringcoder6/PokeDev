"""H5D version isolation, durable evidence and fixed recovery routing; no models."""
# ruff: noqa: INP001, S101, PLR2004

from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from langflow.adlc import contract_execution as execution
from langflow.adlc.blueprints.models import PackageReference, WorkflowStage
from langflow.adlc.contract_execution_models import EXECUTION_PROFILE, RECOVERY_REF
from langflow.adlc.contract_execution_repository import ContractExecutionRepository
from langflow.adlc.harness_client import CONTRACT_RECOVERY_API_ROOT, HarnessClientError, HarnessHttpClient
from langflow.adlc.harness_models import HarnessPluginLockEntry
from langflow.adlc.packages.defaults import create_default_package_access_policy, create_default_package_resolver
from tests.unit.adlc import test_contract_execution as execution_fixture
from tests.unit.adlc.test_harness_client import _session_request

source = execution_fixture.source


def test_recovery_recipe_is_separate_optin_and_preserves_h5c(source, monkeypatch):
    monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "false")
    old_ref = PackageReference(package_id="coding-agent-contract-harness", version="0.1.0")
    new_ref = old_ref.model_copy(update={"version": "0.2.0"})
    policy = create_default_package_access_policy()
    assert policy.can_view_package(execution_fixture.OWNER, old_ref)
    assert not policy.can_view_package(execution_fixture.OWNER, new_ref)
    monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "true")
    assert create_default_package_access_policy().can_view_package(execution_fixture.OWNER, new_ref)
    stage = WorkflowStage.model_validate(
        {
            "stage_id": uuid4(),
            "stage_type": "IMPLEMENTATION",
            "name": "Recoverable coding",
            "objective": "Edit scoped JSON",
            "inputs": {"requirement": "Edit demo.json"},
            "expected_outputs": ["source_patch", "contract_reference"],
            "package_ref": new_ref,
            "configuration_overrides": {"approved_contract_ref": source.contract.reference.model_dump(mode="json")},
            "execution_profile_overrides": {},
            "policy_overrides": {},
            "secret_refs": {},
            "metadata": {},
            "position": {"x": 0, "y": 0},
        }
    )
    spec = create_default_package_resolver().resolve(
        stage, workflow_definition_id=uuid4(), workflow_definition_version=1, access_subject=execution_fixture.OWNER
    )
    assert spec.configuration["recovery_ref"] == RECOVERY_REF
    assert spec.configuration["submission_mode"] == "MANUAL"
    assert spec.execution_profile.model_ref == "model:my-codex/cx/gpt-5.6-luna"
    assert len(spec.configuration["plugin_lock"]) == 5
    assert execution.execution_release_matches(spec.configuration, "0.2.0")
    assert not execution.execution_release_matches(spec.configuration, "0.1.0")
    monkeypatch.setenv("ADLC_CONTRACT_RECOVERY_ENABLED", "false")
    with pytest.raises(execution.ContractError, match="RECOVERY_DISABLED"):
        execution.validate_configuration("coding-agent-contract-harness", spec.configuration, execution_fixture.OWNER)


def test_original_binding_and_proof_survive_repository_reopen_without_new_evidence(source, tmp_path):
    binding = execution_fixture.bind(source)
    proof = execution_fixture.proof_for(binding)
    source.store.report(owner_id=execution_fixture.OWNER, binding=binding, proof=proof)
    source.store.close()
    source.store = ContractExecutionRepository(tmp_path / "execution.sqlite3")
    saved_binding, saved_proof = source.store.get_by_attempt(binding.scope.attempt_id, owner_id=execution_fixture.OWNER)
    assert saved_binding == binding
    assert saved_proof == proof
    assert source.store.report(owner_id=execution_fixture.OWNER, binding=binding, proof=proof) == proof
    with pytest.raises(execution.ContractError, match="EVIDENCE_CONFLICT"):
        source.store.report(
            owner_id=execution_fixture.OWNER, binding=binding, proof=proof.model_copy(update={"artifact_id": uuid4()})
        )
    source.store.close()


@pytest.mark.parametrize("enabled", [False, True])
async def test_recovery_requests_route_once_to_new_api_and_never_fall_back_after_a_write(enabled):
    request = _session_request()
    request.execution.profile_ref = EXECUTION_PROFILE
    request.execution.operation = "contract-coding"
    request.execution.plugin_lock = [
        HarnessPluginLockEntry(
            plugin_id="vai-adlc-contract-recovery", version="0.1.0", required=True, content_digest="sha256:" + "a" * 64
        )
    ]
    seen = []

    def handler(incoming):
        seen.append((incoming.method, incoming.url.path))
        return httpx.Response(404, json={"error": {"code": "HARNESS_ROUTE_NOT_FOUND"}})

    client = HarnessHttpClient(
        transport=httpx.MockTransport(handler), contract_execution_enabled=True, contract_recovery_enabled=enabled
    )
    try:
        with pytest.raises(HarnessClientError):
            await client.create_session(request)
        assert seen == ([("POST", f"{CONTRACT_RECOVERY_API_ROOT}/sessions")] if enabled else [])
    finally:
        await client.close()


async def test_fresh_client_discovers_recovery_session_via_get_and_reconciles_only_that_fixed_root():
    from datetime import datetime, timezone

    request = _session_request()
    now = datetime.now(timezone.utc).isoformat()
    value = {
        "schema_version": "0.1",
        "session_id": "saved-session",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": request.idempotency_key,
        "submission_mode": "MANUAL",
        "status": "VERIFYING",
        "created_at": now,
        "updated_at": now,
    }
    seen = []

    def handler(incoming):
        seen.append((incoming.method, incoming.url.path))
        if not incoming.url.path.startswith(CONTRACT_RECOVERY_API_ROOT + "/"):
            return httpx.Response(404, json={"error": {"code": "HARNESS_SESSION_NOT_FOUND"}})
        if incoming.method == "POST":
            assert incoming.content == b"{}"
            return httpx.Response(200, json={**value, "status": "READY_FOR_SUBMISSION"})
        return httpx.Response(200, json=value)

    client = HarnessHttpClient(
        transport=httpx.MockTransport(handler),
        authoring_enabled=True,
        contract_execution_enabled=True,
        contract_recovery_enabled=True,
    )
    try:
        assert (await client.reconcile_contract_session("saved-session")).status == "READY_FOR_SUBMISSION"
        assert len(seen) == 5
        assert all(method == "GET" for method, _path in seen[:-1])
        assert seen[-1] == ("POST", f"{CONTRACT_RECOVERY_API_ROOT}/sessions/saved-session/reconcile")
    finally:
        await client.close()


@pytest.mark.parametrize("case", ["version", "missing-ref", "wrong-ref", "missing-lock", "optional-lock", "digest"])
def test_new_release_identity_cannot_be_inferred_or_downgraded(case):
    config = {
        "recovery_ref": RECOVERY_REF,
        "plugin_lock": [
            {
                "plugin_id": "vai-adlc-contract-recovery",
                "version": "0.1.0",
                "required": True,
                "content_digest": "sha256:" + "a" * 64,
            }
        ],
    }
    changed = deepcopy(config)
    version = "0.2.0"
    if case == "version":
        version = "0.3.0"
    elif case == "missing-ref":
        changed.pop("recovery_ref")
    elif case == "wrong-ref":
        changed["recovery_ref"] = "plugin:vai-adlc-contract-recovery/latest"
    elif case == "missing-lock":
        changed["plugin_lock"] = []
    elif case == "optional-lock":
        changed["plugin_lock"][0]["required"] = False
    else:
        changed["plugin_lock"][0]["content_digest"] = "sha256:forged"
    assert not execution.execution_release_matches(changed, version)

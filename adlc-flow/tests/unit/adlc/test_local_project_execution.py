# ruff: noqa: INP001, S101, SLF001
"""A selected source must survive compilation, recovery, and loop composition."""

from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

from langflow.adlc.blueprints.models import PlanStatus
from langflow.adlc.harness_client import HarnessClientError, HarnessHttpClient
from langflow.adlc.harness_models import HarnessPluginLockEntry
from langflow.adlc.local_projects import prepare_project_source, snapshot_path
from langflow.adlc.models import TaskResultStatus
from langflow.adlc.planning.errors import BlueprintParseError
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.adlc.planning.parser import parse_blueprint_flow
from tests.unit.adlc.planning.test_blueprint_planning import FIXED_TIME, _compiler, _context, _graph
from tests.unit.adlc.test_coding_agent import ProposalClient, contract_for, executor_for, request_for
from tests.unit.adlc.test_coding_agent import contracts as contracts  # noqa: PLC0414 - expose the pytest fixture
from tests.unit.adlc.test_coding_agent import spec as combined_spec  # noqa: F401 - register a pytest fixture
from tests.unit.adlc.test_harness_client import _session_request
from tests.unit.adlc.test_task_loop_live import FIX, Client, _executor, _ignore, _request, _spec
from tests.unit.adlc.test_task_loop_live import repository as repository  # noqa: PLC0414 - expose the pytest fixture


def test_server_project_context_overrides_browser_spoof_and_is_materialized():
    flow_id = uuid4()
    graph = _graph(flow_id)
    reference = {"project_id": str(uuid4()), "name": "Reviewed", "base_commit": "a" * 40, "source_ref": "pinned"}
    graph["adlc"]["metadata"] = {"adlc_local_project": {"source_path": "untrusted"}, "custom": "keep"}
    without_project = parse_blueprint_flow(graph, _context(flow_id))
    assert "adlc_local_project" not in without_project.metadata
    workflow = parse_blueprint_flow(graph, replace(_context(flow_id), local_project=reference))
    assert workflow.metadata == {"adlc_local_project": reference, "custom": "keep"}
    plan = _compiler().compile(workflow, plan_version=1, generated_by="owner-1", generated_at=FIXED_TIME)
    plan.status = PlanStatus.APPROVED
    plan.approved_by = "owner-1"
    plan.approved_at = FIXED_TIME
    definitions = materialize_task_definitions(plan)
    assert all(item.request_context["adlc_local_project"] == reference for item in definitions)


@pytest.mark.parametrize("version", ["0.2.1", "0.3.0"])
def test_new_coding_release_requires_a_server_selected_project(version):
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["package_ref"]["version"] = version
    graph["adlc"]["metadata"] = {"adlc_local_project": {"source_path": "client-folder"}}
    with pytest.raises(BlueprintParseError) as error:
        parse_blueprint_flow(graph, _context(flow_id))
    assert "LOCAL_PROJECT_REQUIRED" in {item.code for item in error.value.issues}


def test_old_harness_stage_requires_an_explicit_project_upgrade():
    flow_id = uuid4()
    graph = _graph(flow_id)
    graph["nodes"][0]["data"]["adlc"]["package_ref"]["version"] = "0.2.0"
    with pytest.raises(BlueprintParseError) as error:
        parse_blueprint_flow(graph, replace(_context(flow_id), local_project={"project_id": str(uuid4())}))
    assert "LOCAL_PROJECT_RELEASE_REQUIRED" in {item.code for item in error.value.issues}


async def test_selected_project_loop_uses_snapshot_and_rejects_commit_drift(repository, tmp_path, monkeypatch):  # noqa: F811 - pytest fixture injection
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_ROOTS", str(tmp_path))
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_SOURCE_ROOT", str(tmp_path / "snapshots"))
    reference = prepare_project_source(uuid4(), "Selected", str(repository))
    other_source = tmp_path / "other-source"
    other_source.mkdir()  # This global fallback is intentionally not a Git repository.
    client = Client(steps=({**FIX, "legacy.txt": None, "README.md": "Use add(a, b).\n"},))
    executor = _executor(tmp_path, other_source, client)
    request = _request(_spec(repository), context={"adlc_local_project": reference})
    assert executor._project_executor(request).workspace.source == snapshot_path(reference)
    result = await executor.execute(request, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    assert executor.workspace.source == other_source
    assert (repository / "README.md").read_text() == "Pending.\n"
    drift = _request(_spec(repository, base_commit="0" * 40), context={"adlc_local_project": reference})
    rejected = await executor.execute(drift, _ignore)
    assert rejected.error.code == "TASK_LOOP_PROJECT_COMMIT_MISMATCH"
    assert len(client.sessions) == 1


async def test_selected_harness_project_requires_the_exact_extension_before_dispatch():
    request = _session_request()
    request.execution.profile_ref = "harness-profile:adlc-coding-artifacts/0.1.0"
    request.context["adlc_local_project"] = {"project_id": str(uuid4())}
    paths = []

    def handler(incoming):
        paths.append(incoming.url.path)
        return httpx.Response(400, json={"detail": "test rejection"})

    client = HarnessHttpClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HarnessClientError, match="HARNESS_LOCAL_PROJECT_RELEASE_REQUIRED"):
            await client.create_session(request)
        assert not paths
        request.execution.plugin_lock = [
            HarnessPluginLockEntry(
                plugin_id="vai-adlc-local-projects",
                version="0.1.0",
                required=True,
                content_digest="sha256:" + "a" * 64,
            )
        ]
        with pytest.raises(HarnessClientError, match="HARNESS_REQUEST_REJECTED"):
            await client.create_session(request)
        assert paths == ["/api/v1/adlc-local-harness/sessions"]
    finally:
        await client.close()


async def test_selected_project_contract_and_loop_validate_the_original_proof(request, tmp_path, monkeypatch):
    store = request.getfixturevalue("contracts")
    spec = request.getfixturevalue("combined_spec")
    source = request.getfixturevalue("repository")
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_ROOTS", str(tmp_path))
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_SOURCE_ROOT", str(tmp_path / "snapshots"))
    reference = prepare_project_source(uuid4(), "Combined", str(source))
    other = tmp_path / "unrelated-source"
    other.mkdir()
    contract = contract_for(store)
    client = ProposalClient(steps=({**FIX, "README.md": "Use add(a, b).\n"},))
    executor = executor_for(tmp_path, other, client)
    task = request_for(spec, contract)
    task.context["adlc_local_project"] = reference
    task.metadata["plan_traceability"]["package_version"] = "0.2.1"
    result = await executor.execute(task, _ignore)
    assert result.status is TaskResultStatus.SUCCEEDED
    executor.validate_result(task, result, owner_id="owner")
    assert result.output["outputs"]["verification_report"]["checks"][0]["executed_tests"] == 2  # noqa: PLR2004 - protected suite has two tests
    assert (source / "README.md").read_text() == "Pending.\n"
    assert "PRIVATE_FILE_MUST_NOT_REACH_MODEL" not in str(client.prompts)
    assert (await executor.resume(task, _ignore)) == result
    assert len(client.sessions) == 1


async def test_restart_finds_local_session_with_reads_and_routes_one_submission():
    from datetime import datetime, timezone

    request = _session_request()
    now = datetime.now(timezone.utc).isoformat()
    session = {
        "session_id": "local-session",
        "correlation": request.correlation.model_dump(mode="json"),
        "idempotency_key": request.idempotency_key,
        "status": "READY_FOR_SUBMISSION",
        "submission_mode": "MANUAL",
        "created_at": now,
        "updated_at": now,
    }
    calls = []

    def handler(incoming):
        calls.append((incoming.method, incoming.url.path))
        if incoming.method == "GET" and incoming.url.path.startswith("/api/v1/adlc-local-harness/"):
            return httpx.Response(200, json=session)
        return httpx.Response(404, json={})

    client = HarnessHttpClient(
        transport=httpx.MockTransport(handler), authoring_enabled=False, contract_execution_enabled=False
    )
    try:
        assert (await client.get_session("local-session")).session_id == "local-session"
        with pytest.raises(HarnessClientError):
            await client.submit_session("local-session")
        assert calls == [
            ("GET", "/api/v1/adlc-harness/sessions/local-session"),
            ("GET", "/api/v1/adlc-local-harness/sessions/local-session"),
            ("POST", "/api/v1/adlc-local-harness/sessions/local-session/submit"),
        ]
    finally:
        await client.close()

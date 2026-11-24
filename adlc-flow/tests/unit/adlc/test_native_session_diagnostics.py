"""Release-pinned, payload-free native failure reporting; never invokes a model."""
# ruff: noqa: S101, INP001, EM101

from copy import deepcopy
from uuid import uuid4

import httpx
import pytest

from langflow.adlc.harness_demo import DemoHarnessClient
from langflow.adlc.harness_demo_models import REQUIREMENT, DemoError, digest
from tests.unit.adlc.test_harness_demo import service


def activity():
    return {
        "schema_version": "0.1",
        "event_count": 3,
        "event_types": {"counts": [{"label": "assistant/attempt", "count": 1}], "other": 0},
        "tool_calls": {"counts": [], "other": 0},
        "violations": [{"kind": "ASSISTANT_ATTEMPT", "count": 1}],
        "turn_end_count": 1,
        "completion_kinds": {"counts": [{"label": "completed", "count": 1}], "other": 0},
        "assistant_message_count": 1,
        "source_mismatch_count": 0,
        "interrupted_message_count": 0,
    }


@pytest.mark.parametrize("scenario", ["valid", "wrong_release", "wrong_session", "payload", "raw_name", "bool_count"])
async def test_native_diagnostics_are_bound_sanitized_and_never_retry(scenario):
    command = {
        "schema_version": "0.1",
        "session_id": str(uuid4()),
        "run_id": str(uuid4()),
        "stage": "PLAN",
        "provider": "my-codex",
        "model": "cx/gpt-5.6-luna",
        "timeout_ms": 180000,
    }
    result = {
        "session_id": command["session_id"],
        "run_id": command["run_id"],
        "stage": "PLAN",
        "request_digest": digest(command),
        "runtime_version": "0.1.1",
        "status": "FAILED",
        "error_code": "DEMO_NATIVE_ACTIVITY_INVALID",
        "usage": None,
        "native_activity": activity(),
    }
    expected = "DEMO_NATIVE_ACTIVITY_INVALID"
    if scenario == "wrong_release":
        result["runtime_version"] = "0.1.0"
        expected = "DEMO_NATIVE_BINDING_MISMATCH"
    elif scenario == "wrong_session":
        result["session_id"] = str(uuid4())
        expected = "DEMO_NATIVE_BINDING_MISMATCH"
    elif scenario == "payload":
        result["native_activity"]["messages"] = "PRIVATE_PAYLOAD"
        expected = "DEMO_NATIVE_DIAGNOSTICS_INVALID"
    elif scenario == "raw_name":
        result["native_activity"]["event_types"]["counts"][0]["label"] = "PRIVATE_EVENT"
        expected = "DEMO_NATIVE_DIAGNOSTICS_INVALID"
    elif scenario == "bool_count":
        result["native_activity"]["event_count"] = True
        expected = "DEMO_NATIVE_DIAGNOSTICS_INVALID"
    calls = []

    def native(request):
        calls.append(request.method)
        return httpx.Response(202 if request.method == "POST" else 200, json=deepcopy(result))

    client = DemoHarnessClient("http://127.0.0.1:3080", "t" * 40, transport=httpx.MockTransport(native))
    with pytest.raises(DemoError) as failure:
        await client.run(command)
    assert failure.value.code == expected
    assert calls == ["POST", "GET"]
    assert bool(failure.value.native_diagnostics) == (scenario == "valid")
    if scenario == "valid":
        assert failure.value.native_diagnostics["native_activity"] == activity()


async def test_native_failure_is_retained_in_owner_run_without_acceptance(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("owner", REQUIREMENT)
    session_id = uuid4()
    demo.bind(session_id, run["id"], "PLAN")
    diagnostics = {
        "session_id": str(session_id),
        "stage": "PLAN",
        "runtime_version": "0.1.1",
        "native_activity": activity(),
    }

    async def rejected(_):
        raise DemoError("DEMO_NATIVE_ACTIVITY_INVALID", 502, native_diagnostics=diagnostics)

    demo.client.run = rejected
    with pytest.raises(DemoError, match="DEMO_NATIVE_ACTIVITY_INVALID"):
        await demo.native(session_id)
    retained = demo.ledger.get(run["id"], "owner")
    assert retained["native_diagnostics"] == diagnostics
    assert retained["events"][-1]["stage"] == "native_diagnostics"
    assert "plan_digest" not in retained
    assert "commit" not in retained
    assert "completed" not in demo.scopes[str(session_id)]
    with pytest.raises(DemoError, match="DEMO_NOT_FOUND"):
        demo.ledger.get(run["id"], "other-owner")


async def test_reload_does_not_substitute_a_frozen_old_runtime(tmp_path):
    demo = service(tmp_path)
    run = await demo.create("owner", REQUIREMENT)
    run["workflow"]["runtime"]["runtime_ref"] = "runtime:harness-demo-scoped/0.1.0"
    demo.ledger.save(run)
    session_id = uuid4()
    demo.bind(session_id, run["id"], "PLAN")
    with pytest.raises(DemoError, match="DEMO_NATIVE_BINDING_MISMATCH"):
        await demo.native(session_id)
    assert not demo.client.commands
    assert demo.ledger.get(run["id"])["workflow"]["runtime"]["runtime_ref"].endswith("/0.1.0")

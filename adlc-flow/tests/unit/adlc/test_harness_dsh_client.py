# ruff: noqa: INP001, S101, S106, S108, PLR2004, SLF001

from __future__ import annotations

import builtins
from dataclasses import dataclass
from uuid import uuid4

import pytest
from dsh_web_sdk.errors import DshError, DshProtocolError

from langflow.adlc import harness_runtime
from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
from langflow.adlc.harness_client import (
    REQUEST_REJECTED,
    HarnessClientError,
    HarnessServerSettings,
)
from langflow.adlc.harness_dsh_client import (
    DEFAULT_GOAL_IDLE_GRACE_SECONDS,
    DEFAULT_IDLE_GRACE_SECONDS,
    DshHarnessClient,
    dsh_goal_enabled_from_environment,
    dsh_goal_idle_grace_seconds_from_environment,
    dsh_idle_grace_seconds_from_environment,
)
from langflow.adlc.harness_models import (
    HarnessCorrelation,
    HarnessExecutionSpec,
    HarnessSessionRequest,
    HarnessSessionStatus,
    HarnessSubmissionMode,
    TaskResultStatus,
)
from langflow.adlc.harness_runtime import HarnessRuntimeSettings, create_harness_client


@dataclass
class _FakeSessionState:
    running: bool = True
    cursor: int = 0
    final_text: str | None = None
    cancelled: bool = False


class _FakeDshSession:
    def __init__(self, state: _FakeSessionState, session_id: str) -> None:
        self.state = state
        self.session_id = session_id
        self.prompts: list[str] = []

    async def prompt(self, text: str, **_kwargs) -> bool:
        self.prompts.append(text)
        return True

    async def is_running(self) -> bool:
        return self.state.running

    async def cursor(self) -> int:
        return self.state.cursor

    async def final_text(self) -> str | None:
        return self.state.final_text

    async def cancel(self) -> bool:
        self.state.cancelled = True
        return True


class _FakeDshClient:
    def __init__(self) -> None:
        self.created: list[_FakeDshSession] = []
        self.sessions: dict[str, _FakeDshSession] = {}
        self.commands: list[tuple[str, dict]] = []
        self.rpc_error: DshError | None = None
        self.http_responses: dict[str, dict] = {}
        self.http_errors: dict[str, Exception] = {}
        self.http_calls: list[str] = []
        self._next = 0

    async def __aenter__(self) -> _FakeDshClient:  # noqa: PYI034 - test double
        return self

    async def create_session(self, *, cwd: str | None = None, **_kwargs) -> _FakeDshSession:  # noqa: ARG002
        self._next += 1
        session = _FakeDshSession(_FakeSessionState(), f"fx-{self._next}")
        self.sessions[session.session_id] = session
        self.created.append(session)
        return session

    def session(self, session_id: str) -> _FakeDshSession:
        return self.sessions[session_id]

    async def list_sessions(self) -> list[dict]:
        return [{"sessionId": session.session_id} for session in self.sessions.values()]

    async def rpc(self, method: str, args: dict, *, timeout: float | None = None) -> dict:  # noqa: ARG002
        if self.rpc_error is not None:
            raise self.rpc_error
        self.commands.append((method, dict(args)))
        return {
            "commandId": f"cmd-{len(self.commands)}",
            "result": {"kind": "success", "text": "Goal created\nStatus: active\nRounds: 0/256"},
        }

    async def http_get(self, path: str, *, timeout: float | None = None) -> dict:  # noqa: ARG002
        self.http_calls.append(path)
        if path in self.http_errors:
            raise self.http_errors[path]
        if path in self.http_responses:
            return self.http_responses[path]
        return {}


def _client(**kwargs) -> tuple[DshHarnessClient, _FakeDshClient]:
    fake = _FakeDshClient()
    settings = HarnessServerSettings(base_url="http://127.0.0.1:3080", api_token="dsh-token")
    kwargs.setdefault("goal_enabled", False)
    return DshHarnessClient(settings, dsh_client=fake, **kwargs), fake


def _request(idempotency_key: str = "run-1:task-1:attempt-1") -> HarnessSessionRequest:
    return HarnessSessionRequest(
        correlation=HarnessCorrelation(
            request_id=uuid4(),
            workflow_run_id=uuid4(),
            task_run_id=uuid4(),
            attempt_id=uuid4(),
        ),
        idempotency_key=idempotency_key,
        objective="Implement the feature.",
        input={"requirement": "Implement the feature."},
        execution=HarnessExecutionSpec(profile_ref="harness-profile:adlc-coding/0.1.0", operation="coding-task"),
        result_schema_ref="adlc://schemas/source-patch/0.1",
        submission_mode=HarnessSubmissionMode.AUTO,
    )


def _finish(state: _FakeSessionState, *, final_text: str | None, cursor: int = 7) -> None:
    state.running = False
    state.cursor = cursor
    state.final_text = final_text


async def test_create_session_sends_objective_prompt_and_projects_running() -> None:
    client, fake = _client()
    accepted = await client.create_session(_request())

    assert accepted.replayed is False
    assert accepted.session.status is HarnessSessionStatus.RUNNING
    assert accepted.session.result is None
    assert (await client.health())["ready"] is True
    assert fake.created[0].prompts
    assert "Implement the feature." in fake.created[0].prompts[0]


async def test_health_reports_plugin_lock_ready_when_all_dsh_plugins_loaded() -> None:
    client, fake = _client()
    fake.http_responses["/dsh-plugin-hub/installed"] = {
        "profile": "web",
        "installed": {
            "vai-sandbox": "git+http://example/vai-sandbox.git",
            "vai-taskloop": "git+http://example/vai-taskloop.git",
        },
        "loaded": ["vai-sandbox", "vai-taskloop"],
        "dshCapable": ["vai-sandbox", "vai-taskloop"],
    }

    health = await client.health()

    assert health["ready"] is True
    assert health["plugin_lock_ready"] is True
    inventory = health["plugin_integrity"]
    assert inventory["ready"] is True
    assert inventory["error_code"] is None
    assert {entry["plugin_id"] for entry in inventory["plugins"]} == {"vai-sandbox", "vai-taskloop"}
    assert all(entry["status"] == "EXACT" for entry in inventory["plugins"])
    assert fake.http_calls == ["/dsh-plugin-hub/installed"]


async def test_health_reports_plugin_lock_not_ready_when_a_plugin_is_unloaded() -> None:
    client, fake = _client()
    fake.http_responses["/dsh-plugin-hub/installed"] = {
        "profile": "web",
        "installed": {
            "vai-sandbox": "git+http://example/vai-sandbox.git",
            "vai-taskloop": "git+http://example/vai-taskloop.git",
        },
        "loaded": ["vai-taskloop"],
        "dshCapable": ["vai-sandbox", "vai-taskloop"],
    }

    health = await client.health()

    assert health["ready"] is True
    assert health["plugin_lock_ready"] is False
    inventory = health["plugin_integrity"]
    assert inventory["ready"] is False
    assert inventory["error_code"] == "HARNESS_PLUGIN_LOCK_NOT_READY"
    by_id = {entry["plugin_id"]: entry for entry in inventory["plugins"]}
    assert by_id["vai-sandbox"]["status"] == "MISSING"
    assert by_id["vai-taskloop"]["status"] == "EXACT"


async def test_health_reports_hub_unreachable_when_http_get_fails() -> None:
    from dsh_web_sdk.errors import DshTransportError

    client, fake = _client()
    fake.http_errors["/dsh-plugin-hub/installed"] = DshTransportError("connection refused")

    health = await client.health()

    assert health["ready"] is True
    assert health["plugin_lock_ready"] is False
    inventory = health["plugin_integrity"]
    assert inventory["ready"] is False
    assert inventory["error_code"] == "HARNESS_PLUGIN_HUB_UNREACHABLE"
    assert inventory["plugins"] == []


async def test_health_reports_invalid_payload_when_hub_returns_non_dict() -> None:
    client, fake = _client()
    fake.http_responses["/dsh-plugin-hub/installed"] = ["not", "a", "dict"]

    health = await client.health()

    assert health["ready"] is True
    assert health["plugin_lock_ready"] is False
    inventory = health["plugin_integrity"]
    assert inventory["ready"] is False
    assert inventory["error_code"] == "HARNESS_PLUGIN_HUB_INVALID_PAYLOAD"


async def test_create_session_replays_the_same_idempotency_key() -> None:
    client, fake = _client()
    first = await client.create_session(_request())
    replay = await client.create_session(_request())

    assert replay.replayed is True
    assert replay.session.session_id == first.session.session_id
    assert len(fake.created) == 1


async def test_get_session_reports_running_before_idle_grace() -> None:
    client, fake = _client(idle_grace_seconds=60)
    accepted = await client.create_session(_request())
    state = fake.sessions[accepted.session.session_id].state
    _finish(state, final_text="done")

    projection = await client.get_session(accepted.session.session_id)

    assert projection.status is HarnessSessionStatus.RUNNING
    assert projection.result is None


async def test_get_session_finalizes_success_with_final_text() -> None:
    client, fake = _client(idle_grace_seconds=0)
    accepted = await client.create_session(_request())
    _finish(fake.sessions[accepted.session.session_id].state, final_text="patch ready")

    projection = await client.get_session(accepted.session.session_id)

    assert projection.status is HarnessSessionStatus.SUCCEEDED
    assert projection.result is not None
    assert projection.result.status is TaskResultStatus.SUCCEEDED
    assert projection.result.output == {"final_text": "patch ready", "session_id": accepted.session.session_id}
    assert projection.result.error is None


async def test_get_session_finalizes_failure_without_final_text() -> None:
    client, fake = _client(idle_grace_seconds=0)
    accepted = await client.create_session(_request())
    _finish(fake.sessions[accepted.session.session_id].state, final_text=None)

    projection = await client.get_session(accepted.session.session_id)

    assert projection.status is HarnessSessionStatus.FAILED
    assert projection.result is not None
    assert projection.result.status is TaskResultStatus.FAILED
    assert projection.result.error is not None
    assert projection.result.error.code == "HARNESS_RESULT_MISSING"


async def test_final_file_blocks_are_captured_as_retained_source_patch() -> None:
    payloads = BoundedArtifactPayloadStore()
    client, fake = _client(idle_grace_seconds=0, artifact_payloads=payloads)
    accepted = await client.create_session(_request())
    final_text = (
        "Summary: done\n\n"
        '<adlc:file path="text_utils/slugify.py">\n'
        "def slugify(title: str) -> str:\n"
        '    return "-".join(title.lower().split())\n'
        "</adlc:file>\n"
    )
    _finish(fake.sessions[accepted.session.session_id].state, final_text=final_text)

    projection = await client.get_session(accepted.session.session_id)

    assert projection.result is not None
    assert len(projection.result.artifacts) == 1
    artifact = projection.result.artifacts[0]
    assert artifact.kind == "SOURCE_PATCH"
    assert artifact.metadata["capture"] == "dsh-final-message"
    snapshot = await run_service_read(payloads, artifact)
    assert snapshot.format == "opencode-vcs-diff-v1"
    assert snapshot.files[0].file == "text_utils/slugify.py"
    assert snapshot.files[0].additions == 2
    assert "+def slugify(title: str) -> str:" in snapshot.files[0].patch
    assert artifact.checksum.value == snapshot_checksum(snapshot)


async def test_file_capture_is_skipped_without_a_payload_store() -> None:
    client, fake = _client(idle_grace_seconds=0)
    accepted = await client.create_session(_request())
    final_text = 'Summary\n<adlc:file path="a.py">\nx = 1\n</adlc:file>'
    _finish(fake.sessions[accepted.session.session_id].state, final_text=final_text)

    projection = await client.get_session(accepted.session.session_id)

    assert projection.result is not None
    assert projection.result.artifacts == []


async def test_unsafe_file_paths_are_dropped() -> None:
    payloads = BoundedArtifactPayloadStore()
    client, fake = _client(idle_grace_seconds=0, artifact_payloads=payloads)
    accepted = await client.create_session(_request())
    final_text = (
        '<adlc:file path="../escape.py">\nx = 1\n</adlc:file>\n'
        '<adlc:file path="/absolute.py">\nx = 2\n</adlc:file>\n'
        '<adlc:file path="ok.py">\nx = 3\n</adlc:file>'
    )
    _finish(fake.sessions[accepted.session.session_id].state, final_text=final_text)

    projection = await client.get_session(accepted.session.session_id)

    assert projection.result is not None
    assert len(projection.result.artifacts) == 1
    payload = payloads.read(projection.result.artifacts[0])
    assert b'"ok.py"' in payload
    assert b"escape.py" not in payload
    assert b"absolute.py" not in payload


async def run_service_read(payloads: BoundedArtifactPayloadStore, artifact):
    from langflow.adlc.artifact_payload_store import SourcePatchSnapshot

    return SourcePatchSnapshot.model_validate_json(payloads.read(artifact))


def snapshot_checksum(snapshot) -> str:
    import hashlib
    import json

    content = json.dumps(
        {
            "format": snapshot.format,
            "files": [item.model_dump(mode="json") for item in snapshot.files],
            "reported_files": snapshot.reported_files,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(content).hexdigest()


async def test_cancel_session_finalizes_cancelled_result() -> None:
    client, fake = _client(idle_grace_seconds=0)
    accepted = await client.create_session(_request())
    session = fake.sessions[accepted.session.session_id]

    projection = await client.cancel_session(accepted.session.session_id)

    assert projection.status is HarnessSessionStatus.CANCELLED
    assert projection.result is not None
    assert projection.result.error is not None
    assert projection.result.error.code == "HARNESS_SESSION_CANCELLED"
    assert session.state.cancelled is True


async def test_unknown_session_is_rejected() -> None:
    client, _fake = _client()

    with pytest.raises(HarnessClientError) as exc_info:
        await client.get_session("missing")
    assert exc_info.value.code == REQUEST_REJECTED


async def test_factory_selects_dsh_transport_and_requires_token(monkeypatch) -> None:
    monkeypatch.setattr(
        harness_runtime,
        "DshHarnessClient",
        lambda settings, **kwargs: DshHarnessClient(settings, dsh_client=_FakeDshClient(), **kwargs),
    )
    dsh = create_harness_client(
        HarnessRuntimeSettings(
            enabled=True,
            server=HarnessServerSettings(base_url="http://127.0.0.1:3080", api_token="dsh-token"),
            transport="dsh",
        )
    )
    assert isinstance(dsh, DshHarnessClient)

    with pytest.raises(ValueError):  # noqa: PT011 - fail-closed factory contract
        create_harness_client(
            HarnessRuntimeSettings(
                enabled=True,
                server=HarnessServerSettings(api_token=None),
                transport="dsh",
            )
        )


def test_missing_optional_sdk_keeps_rest_available_and_rejects_dsh(monkeypatch) -> None:
    original_import = builtins.__import__

    def without_dsh_sdk(name, *args, **kwargs):
        if name == "dsh_web_sdk" or name.startswith("dsh_web_sdk."):
            raise ModuleNotFoundError(name=name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_dsh_sdk)
    settings = HarnessServerSettings(base_url="http://127.0.0.1:3080", api_token="dsh-token")
    rest = create_harness_client(HarnessRuntimeSettings(enabled=True, server=settings, transport="rest"))
    assert rest.settings == settings
    with pytest.raises(ValueError, match="DSH_SDK_UNAVAILABLE"):
        create_harness_client(HarnessRuntimeSettings(enabled=True, server=settings, transport="dsh"))
    assert DshHarnessClient(settings, dsh_client=_FakeDshClient()).settings == settings


async def test_compose_prompt_includes_structured_sections() -> None:
    client, fake = _client()
    request = _request()
    request = request.model_copy(
        update={
            "context": {"cwd": "/tmp/worktree"},
            "constraints": {"timeout_ms": 60000},
            "metadata": {"source": "plan"},
        }
    )
    await client.create_session(request)

    prompt = fake.created[0].prompts[0]
    assert "## Input" in prompt
    assert "## Constraints" in prompt
    assert "## Context" in prompt
    assert "/tmp/worktree" in prompt


async def test_goal_arms_at_first_idle_and_keeps_grace_extended() -> None:
    client, fake = _client(idle_grace_seconds=0, goal_enabled=True, goal_idle_grace_seconds=60)
    accepted = await client.create_session(_request())
    session_id = accepted.session.session_id
    state = fake.sessions[session_id].state

    # while the first turn is still running the goal must not be armed: a goal
    # armed while a turn runs never drives rounds afterwards
    projection = await client.get_session(session_id)
    assert projection.status is HarnessSessionStatus.RUNNING
    assert fake.commands == []
    assert client._goal_sessions == set()

    _finish(state, final_text="done")
    projection = await client.get_session(session_id)

    # armed at the first idle observation; the extended goal grace keeps the
    # session open while the driver prepares the next round
    assert [method for method, _args in fake.commands] == ["commands/execute"]
    _method, args = fake.commands[0]
    assert args["agentId"] == session_id
    assert args["line"].startswith("/goal Implement the feature.")
    assert session_id in client._goal_sessions
    assert projection.status is HarnessSessionStatus.RUNNING
    assert projection.result is None


async def test_goal_disabled_skips_command_rpc() -> None:
    client, fake = _client(goal_enabled=False)
    accepted = await client.create_session(_request())
    _finish(fake.sessions[accepted.session.session_id].state, final_text="done")
    await client.get_session(accepted.session.session_id)

    assert fake.commands == []
    assert client._goal_sessions == set()


async def test_goal_arm_failure_does_not_fail_result_projection() -> None:
    client, fake = _client(idle_grace_seconds=0, goal_enabled=True)
    accepted = await client.create_session(_request())
    session_id = accepted.session.session_id
    _finish(fake.sessions[session_id].state, final_text="patch ready")
    fake.rpc_error = DshProtocolError("commands/execute unavailable")

    projection = await client.get_session(session_id)

    assert projection.status is HarnessSessionStatus.SUCCEEDED
    assert projection.result is not None
    assert client._goal_sessions == set()


async def test_goal_objective_is_single_line_and_truncated() -> None:
    client, fake = _client(goal_enabled=True)
    request = _request().model_copy(
        update={
            "objective": "Implement\nthe  feature\twith\ttabs" + " x" * 500,
        }
    )
    accepted = await client.create_session(request)
    session_id = accepted.session.session_id
    _finish(fake.sessions[session_id].state, final_text="done")
    await client.get_session(session_id)

    _method, args = fake.commands[0]
    line = args["line"]
    assert "\n" not in line
    assert "\t" not in line
    assert "  " not in line
    assert len(line) <= 406  # noqa: PLR2004 - "/goal " prefix + 400-char objective


async def test_goal_session_finalizes_after_goal_grace_and_untracks() -> None:
    client, fake = _client(idle_grace_seconds=0, goal_enabled=True, goal_idle_grace_seconds=0)
    accepted = await client.create_session(_request())
    session_id = accepted.session.session_id
    state = fake.sessions[session_id].state
    _finish(state, final_text="done")

    projection = await client.get_session(session_id)

    assert projection.status is HarnessSessionStatus.SUCCEEDED
    assert projection.result is not None
    assert session_id not in client._goal_sessions


async def test_cancel_session_discards_goal_tracking() -> None:
    client, fake = _client(idle_grace_seconds=0, goal_enabled=True, goal_idle_grace_seconds=60)
    accepted = await client.create_session(_request())
    session_id = accepted.session.session_id
    _finish(fake.sessions[session_id].state, final_text="done")
    await client.get_session(session_id)
    assert session_id in client._goal_sessions

    await client.cancel_session(session_id)

    assert session_id not in client._goal_sessions


def test_goal_environment_parsers() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("ADLC_DSH_GOAL_ENABLED", raising=False)
        assert dsh_goal_enabled_from_environment() is True
        patch.setenv("ADLC_DSH_GOAL_ENABLED", "false")
        assert dsh_goal_enabled_from_environment() is False
        patch.setenv("ADLC_DSH_GOAL_ENABLED", "off")
        assert dsh_goal_enabled_from_environment() is False
        patch.setenv("ADLC_DSH_GOAL_ENABLED", "1")
        assert dsh_goal_enabled_from_environment() is True

        patch.delenv("ADLC_HARNESS_DSH_GOAL_IDLE_GRACE_SECONDS", raising=False)
        assert dsh_goal_idle_grace_seconds_from_environment() == DEFAULT_GOAL_IDLE_GRACE_SECONDS
        patch.setenv("ADLC_HARNESS_DSH_GOAL_IDLE_GRACE_SECONDS", "120")
        assert dsh_goal_idle_grace_seconds_from_environment() == 120.0  # noqa: PLR2004 - explicit override
        patch.setenv("ADLC_HARNESS_DSH_GOAL_IDLE_GRACE_SECONDS", "abc")
        assert dsh_goal_idle_grace_seconds_from_environment() == DEFAULT_GOAL_IDLE_GRACE_SECONDS
        patch.setenv("ADLC_HARNESS_DSH_GOAL_IDLE_GRACE_SECONDS", "-5")
        assert dsh_goal_idle_grace_seconds_from_environment() == DEFAULT_GOAL_IDLE_GRACE_SECONDS

        patch.delenv("ADLC_HARNESS_DSH_IDLE_GRACE_SECONDS", raising=False)
        assert dsh_idle_grace_seconds_from_environment() == DEFAULT_IDLE_GRACE_SECONDS

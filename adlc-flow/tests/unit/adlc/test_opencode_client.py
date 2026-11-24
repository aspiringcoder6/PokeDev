# ruff: noqa: INP001, S101, S105, S106

from __future__ import annotations

import json

import httpx
import pytest

from langflow.adlc.opencode_client import (
    OpenCodeClient,
    OpenCodeClientError,
    OpenCodeHttpClient,
    OpenCodeModelSelection,
    OpenCodeServerSettings,
)

_PENDING_MESSAGE_READ = 2
_EXPECTED_MESSAGE_READS = 3


async def test_http_client_uses_documented_session_endpoints_and_parses_result() -> None:
    requests: list[httpx.Request] = []
    message_reads = 0

    old_message = {
        "info": {
            "id": "msg_old",
            "role": "assistant",
            "finish": "stop",
        },
        "parts": [{"type": "text", "text": "Earlier result"}],
    }
    pending_message = {
        "info": {
            "id": "msg_step",
            "role": "assistant",
            "providerID": "anthropic",
            "modelID": "claude-test",
            "finish": "tool-calls",
        },
        "parts": [
            {"type": "step-start"},
            {"type": "tool", "state": {"status": "completed"}},
            {"type": "patch", "files": ["D:/workspace/src/a.py"]},
        ],
    }
    completed_message = {
        "info": {
            "id": "msg_final",
            "role": "assistant",
            "providerID": "anthropic",
            "modelID": "claude-test",
            "finish": "stop",
            "cost": 0.1,
            "tokens": {
                "input": 2,
                "output": 3,
                "reasoning": 1,
                "cache": {"read": 4, "write": 5},
            },
        },
        "parts": [
            {"type": "text", "text": "Done"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal message_reads
        requests.append(request)
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True, "version": "1.2.3"})
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "ses_1", "directory": "D:/workspace"})
        if request.url.path == "/session/ses_1/prompt_async" and request.method == "POST":
            body = json.loads(request.content)
            assert body["model"] == {"providerID": "anthropic", "modelID": "claude-test"}
            assert body["parts"] == [{"type": "text", "text": "Do work"}]
            return httpx.Response(204)
        if request.url.path == "/session/ses_1/message" and request.method == "GET":
            message_reads += 1
            if message_reads == 1:
                return httpx.Response(200, json=[old_message])
            if message_reads == _PENDING_MESSAGE_READ:
                return httpx.Response(200, json=[old_message, pending_message])
            return httpx.Response(200, json=[old_message, pending_message, completed_message])
        if request.url.path == "/vcs/diff":
            return httpx.Response(
                200,
                json=[
                    {
                        "file": "src/a.py",
                        "patch": "--- a/src/a.py\n+++ b/src/a.py\n",
                        "additions": 1,
                        "deletions": 1,
                        "status": "modified",
                    }
                ],
            )
        if request.url.path == "/session/ses_1/abort":
            return httpx.Response(200, json=True)
        if request.url.path == "/instance/dispose":
            return httpx.Response(200, json=True)
        return httpx.Response(404)

    settings = OpenCodeServerSettings(
        base_url="http://127.0.0.1:4096",
        username="opencode",
        password="server-secret",
    )
    client = OpenCodeHttpClient(settings, transport=httpx.MockTransport(handler), poll_interval_seconds=0)

    assert isinstance(client, OpenCodeClient)
    assert await client.health() == "1.2.3"
    session = await client.create_session(directory="D:/workspace", title="Task", timeout_ms=1000)
    result = await client.prompt(
        session.session_id,
        directory="D:/workspace",
        prompt="Do work",
        system="Stay scoped",
        model=OpenCodeModelSelection.parse("anthropic/claude-test"),
        agent="build",
        timeout_ms=1000,
    )
    diffs = await client.get_workspace_diff(directory="D:/workspace", timeout_ms=1000)
    await client.abort(session.session_id, directory="D:/workspace")
    await client.dispose_instance(directory="D:/workspace")

    assert result.message_id == "msg_final"
    assert result.text == "Done"
    assert result.changed_files == ("D:/workspace/src/a.py",)
    assert result.token_usage.reasoning_tokens == 1
    assert diffs[0].file == "src/a.py"
    assert diffs[0].status == "modified"
    assert diffs[0].patch.startswith("--- a/src/a.py")
    assert message_reads == _EXPECTED_MESSAGE_READS
    assert any(request.url.path.endswith("/prompt_async") for request in requests)
    assert requests[-1].url.path == "/instance/dispose"
    assert any(request.url.path == "/vcs/diff" and request.url.params.get("mode") == "git" for request in requests)
    assert not any(request.method == "POST" and request.url.path.endswith("/message") for request in requests)
    assert all(request.url.params.get("directory") == "D:/workspace" for request in requests[1:])
    assert all(request.headers.get("authorization", "").startswith("Basic ") for request in requests)
    assert "server-secret" not in repr(settings)


async def test_http_client_maps_async_assistant_error() -> None:
    message_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal message_reads
        if request.url.path == "/session/ses_error/message" and request.method == "GET":
            message_reads += 1
            if message_reads == 1:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "info": {
                            "id": "msg_error",
                            "role": "assistant",
                            "finish": None,
                            "error": {"name": "ProviderAuthError", "data": {"message": "must not escape"}},
                        },
                        "parts": [],
                    }
                ],
            )
        if request.url.path == "/session/ses_error/prompt_async" and request.method == "POST":
            return httpx.Response(204)
        return httpx.Response(404)

    client = OpenCodeHttpClient(
        OpenCodeServerSettings(),
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )

    with pytest.raises(OpenCodeClientError) as error:
        await client.prompt(
            "ses_error",
            directory="D:/workspace",
            prompt="Do work",
            system="Stay scoped",
            model=None,
            agent=None,
            timeout_ms=1000,
        )

    assert error.value.code == "OPENCODE_PROVIDER_AUTHENTICATION_FAILED"
    assert error.value.category == "AUTHENTICATION"
    assert "must not escape" not in str(error.value)


async def test_http_client_times_out_while_polling_for_async_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session/ses_slow/message" and request.method == "GET":
            return httpx.Response(200, json=[])
        if request.url.path == "/session/ses_slow/prompt_async" and request.method == "POST":
            return httpx.Response(204)
        return httpx.Response(404)

    client = OpenCodeHttpClient(
        OpenCodeServerSettings(),
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0.001,
    )

    with pytest.raises(OpenCodeClientError) as error:
        await client.prompt(
            "ses_slow",
            directory="D:/workspace",
            prompt="Do work",
            system="Stay scoped",
            model=None,
            agent=None,
            timeout_ms=10,
        )

    assert error.value.code == "OPENCODE_REQUEST_TIMEOUT"
    assert error.value.category == "TIMEOUT"
    assert error.value.retryable is True


@pytest.mark.parametrize(
    "url",
    [
        "ftp://localhost:4096",
        "http://example.com:4096",
        "https://user:secret@example.com",
        "https://example.com?password=secret",
    ],
)
def test_http_client_rejects_unsafe_server_urls(url: str) -> None:
    with pytest.raises(ValueError, match="OpenCode server"):
        OpenCodeHttpClient(OpenCodeServerSettings(base_url=url))


def test_settings_load_only_server_connection_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADLC_OPENCODE_SERVER_URL", "https://opencode.internal.example")
    monkeypatch.setenv("ADLC_OPENCODE_SERVER_USERNAME", "adlc")
    monkeypatch.setenv("ADLC_OPENCODE_SERVER_PASSWORD", "server-password")
    monkeypatch.setenv("ADLC_OPENCODE_MODEL", "anthropic/claude-test")
    monkeypatch.setenv("ADLC_OPENCODE_AGENT", "build")

    settings = OpenCodeServerSettings.from_environment()

    assert settings.base_url == "https://opencode.internal.example"
    assert settings.username == "adlc"
    assert settings.password == "server-password"
    assert settings.model == "anthropic/claude-test"
    assert settings.agent == "build"
    assert "server-password" not in repr(settings)


@pytest.mark.parametrize("model", ["claude", "/claude", "anthropic/", ""])
def test_model_selection_requires_provider_and_model(model: str) -> None:
    with pytest.raises(ValueError, match="provider/model"):
        OpenCodeModelSelection.parse(model)

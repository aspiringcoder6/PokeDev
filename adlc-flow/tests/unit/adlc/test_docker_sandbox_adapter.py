"""Unit tests for the DockerSandboxAdapter."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from langflow.adlc.adapters.docker_sandbox import (
    DockerSandboxAdapter,
    DockerSandboxConfig,
    DockerSandboxError,
    ERR_DOCKER_NOT_AVAILABLE,
)
from langflow.adlc.models import ExecutorTarget, TaskRequest


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_request() -> TaskRequest:
    return TaskRequest(
        request_id=uuid4(),
        workflow_run_id=uuid4(),
        task_run_id=uuid4(),
        attempt_id=uuid4(),
        task_definition_id=uuid4(),
        task_type="DOCKER_TEST",
        name="docker-test",
        executor=ExecutorTarget(service="sandbox", operation="docker"),
        input={},
        context={},
        dependency_task_run_ids=[],
        constraints={},
        idempotency_key=f"docker-{uuid4()}",
        requested_at=_utc_now(),
    )


class TestDockerSandboxConfig:
    def test_default_config(self):
        config = DockerSandboxConfig()
        assert config.image == "python:3.11-slim"
        assert config.cpu_limit is None
        assert config.memory_limit is None
        assert config.network_mode == "none"
        assert config.auto_remove is True
        assert config.pull_image is False

    def test_custom_config(self):
        config = DockerSandboxConfig(
            image="python:3.12",
            cpu_limit=2.0,
            memory_limit="1g",
            network_mode="bridge",
            auto_remove=False,
        )
        assert config.image == "python:3.12"
        assert config.cpu_limit == 2.0
        assert config.memory_limit == "1g"
        assert config.network_mode == "bridge"
        assert config.auto_remove is False


class TestDockerSandboxAdapter:
    def test_detects_docker_availability(self):
        adapter = DockerSandboxAdapter()
        # Should match shutil.which("docker") result.
        assert adapter.is_available == (shutil.which("docker") is not None)

    def test_service_name(self):
        adapter = DockerSandboxAdapter()
        assert adapter.service_name == "sandbox:docker"

    def test_list_active_sessions_initially_empty(self):
        adapter = DockerSandboxAdapter()
        assert adapter.list_active_sessions() == []

    def test_get_container_info_returns_none_for_unknown(self):
        adapter = DockerSandboxAdapter()
        assert adapter.get_container_info("unknown") is None

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_open_session_creates_container(self):
        """Test that open_session creates a Docker container."""
        adapter = DockerSandboxAdapter(
            config=DockerSandboxConfig(image="python:3.11-slim")
        )
        request = _make_request()
        session = asyncio.run(adapter.open_session(request))

        try:
            assert session.session_id.startswith("docker-")
            assert session.workspace_uri.startswith("docker://")
            assert session.metadata["adapter"] == "sandbox:docker"
            assert "container_id" in session.metadata
            assert session.metadata["image"] == "python:3.11-slim"
            assert session.metadata["disposable"] is True
            assert session.metadata["mock"] is False

            # Container should be tracked.
            assert len(adapter.list_active_sessions()) == 1
            info = adapter.get_container_info(session.session_id)
            assert info is not None
            assert info.container_id == session.metadata["container_id"]
        finally:
            asyncio.run(adapter.close_session(request, session))

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_close_session_removes_container(self):
        """Test that close_session removes the Docker container."""
        adapter = DockerSandboxAdapter(
            config=DockerSandboxConfig(image="python:3.11-slim")
        )
        request = _make_request()
        session = asyncio.run(adapter.open_session(request))
        container_id = session.metadata["container_id"]

        asyncio.run(adapter.close_session(request, session))

        # Container should no longer be tracked.
        assert len(adapter.list_active_sessions()) == 0
        assert adapter.get_container_info(session.session_id) is None

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_exec_in_container(self):
        """Test executing a command in the container."""
        adapter = DockerSandboxAdapter(
            config=DockerSandboxConfig(image="python:3.11-slim")
        )
        request = _make_request()
        session = asyncio.run(adapter.open_session(request))

        try:
            stdout, stderr, code = asyncio.run(
                adapter.exec_in_container(session, "echo hello")
            )
            assert "hello" in stdout
            assert code == 0
        finally:
            asyncio.run(adapter.close_session(request, session))

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_exec_in_unknown_session_raises(self):
        """Test that exec on unknown session raises an error."""
        from langflow.adlc.adapter_interfaces import SandboxSession

        adapter = DockerSandboxAdapter()
        session = SandboxSession(
            session_id="unknown",
            workspace_uri="docker://unknown",
        )
        with pytest.raises(DockerSandboxError) as exc_info:
            asyncio.run(adapter.exec_in_container(session, "echo test"))
        assert exc_info.value.code == "DOCKER_CONTAINER_NOT_FOUND"

    def test_open_session_without_docker_raises(self):
        """Test that open_session raises when Docker is not available."""
        # Create an adapter and force docker_available to False.
        adapter = DockerSandboxAdapter()
        adapter._docker_available = False

        request = _make_request()
        with pytest.raises(DockerSandboxError) as exc_info:
            asyncio.run(adapter.open_session(request))
        assert exc_info.value.code == ERR_DOCKER_NOT_AVAILABLE

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_multiple_sessions(self):
        """Test that multiple sessions can be opened simultaneously."""
        adapter = DockerSandboxAdapter(
            config=DockerSandboxConfig(image="python:3.11-slim")
        )
        sessions = []
        requests = []

        try:
            for _ in range(3):
                request = _make_request()
                session = asyncio.run(adapter.open_session(request))
                sessions.append(session)
                requests.append(request)

            assert len(adapter.list_active_sessions()) == 3
        finally:
            for request, session in zip(requests, sessions):
                asyncio.run(adapter.close_session(request, session))

        assert len(adapter.list_active_sessions()) == 0

    @pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    def test_session_metadata_includes_resource_limits(self):
        """Test that resource limits are included in session metadata."""
        adapter = DockerSandboxAdapter(
            config=DockerSandboxConfig(
                image="python:3.11-slim",
                cpu_limit=1.5,
                memory_limit="512m",
            )
        )
        request = _make_request()
        session = asyncio.run(adapter.open_session(request))

        try:
            assert session.metadata["cpu_limit"] == 1.5
            assert session.metadata["memory_limit"] == "512m"
        finally:
            asyncio.run(adapter.close_session(request, session))

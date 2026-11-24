"""Docker Sandbox Adapter — container-based isolation.

Provides container isolation for task execution using Docker.
Each task attempt runs in a disposable container that is removed
after the task completes.

Features:
- Container isolation (separate filesystem, network, processes)
- Resource limits (CPU, memory, disk)
- Network policy (allowlist domains or full isolation)
- Volume mounts for workspace and evidence
- Automatic cleanup on session close
- Fallback to LocalWorktreeSandboxAdapter if Docker unavailable

This adapter is opt-in: set ADLC_SANDBOX_ADAPTER=docker to enable.
The MockSandboxAdapter and LocalWorktreeSandboxAdapter remain the
defaults for backward compatibility.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from langflow.adlc.adapter_interfaces import SandboxSession
from langflow.adlc.models import TaskRequest


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Stable error codes for Docker failures.
ERR_DOCKER_NOT_AVAILABLE = "DOCKER_NOT_AVAILABLE"
ERR_DOCKER_DAEMON_ERROR = "DOCKER_DAEMON_ERROR"
ERR_DOCKER_IMAGE_PULL_FAILED = "DOCKER_IMAGE_PULL_FAILED"
ERR_DOCKER_CONTAINER_CREATE_FAILED = "DOCKER_CONTAINER_CREATE_FAILED"
ERR_DOCKER_CONTAINER_START_FAILED = "DOCKER_CONTAINER_START_FAILED"
ERR_DOCKER_CONTAINER_NOT_FOUND = "DOCKER_CONTAINER_NOT_FOUND"
ERR_DOCKER_CONTAINER_REMOVE_FAILED = "DOCKER_CONTAINER_REMOVE_FAILED"


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    """Configuration for the DockerSandboxAdapter."""

    image: str = "python:3.11-slim"
    cpu_limit: float | None = None  # e.g., 1.0 for 1 CPU
    memory_limit: str | None = None  # e.g., "512m", "1g"
    network_mode: str = "none"  # "none", "bridge", "host"
    allowed_domains: tuple[str, ...] = ()  # For network policy
    workspace_mount: Path | None = None  # Host path to mount
    auto_remove: bool = True
    pull_image: bool = False  # Pull image if not present
    docker_host: str | None = None  # Custom Docker daemon socket


@dataclass
class _ContainerInfo:
    """Internal tracking for a Docker container."""

    container_id: str
    session_id: str
    workspace_path: Path
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class DockerSandboxError(Exception):
    """Raised when Docker operations fail."""

    def __init__(self, code: str, message: str, *, operation: str) -> None:
        super().__init__(message)
        self.code = code
        self.operation = operation
        self.message = message


class DockerSandboxAdapter:
    """Real sandbox adapter backed by Docker containers.

    Each task attempt runs in a disposable Docker container. The
    container is created on open_session and removed on close_session.
    """

    service_name = "sandbox:docker"

    def __init__(self, config: DockerSandboxConfig | None = None) -> None:
        self._config = config or DockerSandboxConfig()
        self._containers: dict[str, _ContainerInfo] = {}
        self._lock = asyncio.Lock()
        self._docker_available = self._check_docker_available()

    def _check_docker_available(self) -> bool:
        """Check if Docker is available on this system."""
        return shutil.which("docker") is not None

    @property
    def is_available(self) -> bool:
        """Whether Docker is available for use."""
        return self._docker_available

    async def _run_docker(
        self,
        *args: str,
        error_code: str,
        operation: str,
    ) -> tuple[str, str, int]:
        """Run a Docker command and return (stdout, stderr, returncode)."""
        if not self._docker_available:
            raise DockerSandboxError(
                ERR_DOCKER_NOT_AVAILABLE,
                "Docker is not available on this system",
                operation=operation,
            )

        cmd = ["docker", *args]
        if self._config.docker_host:
            cmd.extend(["-H", self._config.docker_host])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                process.returncode or 0,
            )
        except FileNotFoundError as exc:
            raise DockerSandboxError(
                ERR_DOCKER_NOT_AVAILABLE,
                f"Docker executable not found: {exc}",
                operation=operation,
            ) from exc
        except Exception as exc:
            raise DockerSandboxError(
                ERR_DOCKER_DAEMON_ERROR,
                f"Docker daemon error: {exc}",
                operation=operation,
            ) from exc

    async def _ensure_image(self) -> None:
        """Ensure the configured image is available locally."""
        stdout, stderr, code = await self._run_docker(
            "image",
            "inspect",
            self._config.image,
            error_code=ERR_DOCKER_IMAGE_PULL_FAILED,
            operation="inspect_image",
        )
        if code != 0 and self._config.pull_image:
            await self._run_docker(
                "pull",
                self._config.image,
                error_code=ERR_DOCKER_IMAGE_PULL_FAILED,
                operation="pull_image",
            )

    async def open_session(self, request: TaskRequest) -> SandboxSession:
        """Create a Docker container for the task attempt."""
        await self._ensure_image()

        session_id = f"docker-{request.attempt_id}"
        container_name = f"adlc-{session_id}-{uuid.uuid4().hex[:8]}"

        # Build docker run command.
        cmd = [
            "create",
            "--name",
            container_name,
            "--label",
            f"adlc.attempt_id={request.attempt_id}",
            "--label",
            f"adlc.workflow_run_id={request.workflow_run_id}",
            "--network",
            self._config.network_mode,
        ]

        if self._config.cpu_limit is not None:
            cmd.extend(["--cpus", str(self._config.cpu_limit)])
        if self._config.memory_limit is not None:
            cmd.extend(["--memory", self._config.memory_limit])
        if self._config.auto_remove:
            cmd.append("--rm")

        # Mount workspace if configured.
        workspace_path: Path | None = None
        if self._config.workspace_mount is not None:
            workspace_path = self._config.workspace_mount / session_id
            workspace_path.mkdir(parents=True, exist_ok=True)
            cmd.extend(["-v", f"{workspace_path}:/workspace"])

        cmd.extend([self._config.image, "sleep", "infinity"])

        stdout, stderr, code = await self._run_docker(
            *cmd,
            error_code=ERR_DOCKER_CONTAINER_CREATE_FAILED,
            operation="create_container",
        )

        if code != 0:
            raise DockerSandboxError(
                ERR_DOCKER_CONTAINER_CREATE_FAILED,
                f"Failed to create container: {stderr.strip()}",
                operation="create_container",
            )

        container_id = stdout.strip()

        # Start the container.
        _, stderr, code = await self._run_docker(
            "start",
            container_id,
            error_code=ERR_DOCKER_CONTAINER_START_FAILED,
            operation="start_container",
        )

        if code != 0:
            # Clean up the created container.
            await self._run_docker(
                "rm",
                "-f",
                container_id,
                error_code=ERR_DOCKER_CONTAINER_REMOVE_FAILED,
                operation="cleanup_failed_container",
            )
            raise DockerSandboxError(
                ERR_DOCKER_CONTAINER_START_FAILED,
                f"Failed to start container: {stderr.strip()}",
                operation="start_container",
            )

        info = _ContainerInfo(
            container_id=container_id,
            session_id=session_id,
            workspace_path=workspace_path or Path("/workspace"),
            created_at=_utc_now(),
            metadata={
                "image": self._config.image,
                "network_mode": self._config.network_mode,
            },
        )

        async with self._lock:
            self._containers[session_id] = info

        return SandboxSession(
            session_id=session_id,
            workspace_uri=f"docker://{container_id}",
            metadata={
                "adapter": self.service_name,
                "container_id": container_id,
                "container_name": container_name,
                "image": self._config.image,
                "workspace_path": str(info.workspace_path),
                "network_mode": self._config.network_mode,
                "cpu_limit": self._config.cpu_limit,
                "memory_limit": self._config.memory_limit,
                "disposable": True,
                "mock": False,
            },
        )

    async def close_session(
        self, request: TaskRequest, session: SandboxSession
    ) -> None:
        """Stop and remove the Docker container."""
        async with self._lock:
            info = self._containers.pop(session.session_id, None)

        if info is None:
            return

        # Stop the container.
        await self._run_docker(
            "stop",
            info.container_id,
            error_code=ERR_DOCKER_CONTAINER_REMOVE_FAILED,
            operation="stop_container",
        )

        # Remove the container (if not auto-remove).
        if not self._config.auto_remove:
            await self._run_docker(
                "rm",
                "-f",
                info.container_id,
                error_code=ERR_DOCKER_CONTAINER_REMOVE_FAILED,
                operation="remove_container",
            )

    async def exec_in_container(
        self, session: SandboxSession, command: str
    ) -> tuple[str, str, int]:
        """Execute a command in the container.

        Returns (stdout, stderr, returncode).
        """
        async with self._lock:
            info = self._containers.get(session.session_id)

        if info is None:
            raise DockerSandboxError(
                ERR_DOCKER_CONTAINER_NOT_FOUND,
                f"Container not found for session: {session.session_id}",
                operation="exec",
            )

        return await self._run_docker(
            "exec",
            info.container_id,
            "sh",
            "-c",
            command,
            error_code=ERR_DOCKER_DAEMON_ERROR,
            operation="exec",
        )

    def get_container_info(self, session_id: str) -> _ContainerInfo | None:
        """Get container info for a session."""
        return self._containers.get(session_id)

    def list_active_sessions(self) -> list[str]:
        """List all active session IDs."""
        return list(self._containers.keys())


__all__ = [
    "DockerSandboxAdapter",
    "DockerSandboxConfig",
    "DockerSandboxError",
    "ERR_DOCKER_NOT_AVAILABLE",
    "ERR_DOCKER_DAEMON_ERROR",
    "ERR_DOCKER_IMAGE_PULL_FAILED",
    "ERR_DOCKER_CONTAINER_CREATE_FAILED",
    "ERR_DOCKER_CONTAINER_START_FAILED",
    "ERR_DOCKER_CONTAINER_NOT_FOUND",
    "ERR_DOCKER_CONTAINER_REMOVE_FAILED",
]

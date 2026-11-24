"""Opt-in OpenCode runtime composition and secret-safe readiness reporting."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from langflow.adlc.adapter_interfaces import AdapterBundle
from langflow.adlc.adapter_runtime import AdapterTaskExecutor
from langflow.adlc.coding_agent import CONTRACT_LOOP_SERVICE
from langflow.adlc.coding_agent_loop import create_contract_loop_executor
from langflow.adlc.executor_router import TaskExecutorRouter
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver
from langflow.adlc.harness_dsh_client import DshHarnessClient
from langflow.adlc.harness_executor import DeepSeekHarnessTaskExecutor
from langflow.adlc.harness_runtime import HarnessRuntimeSettings, create_harness_task_executor
from langflow.adlc.local_worktree_sandbox import LocalWorktreeSandboxAdapter, LocalWorktreeSandboxError
from langflow.adlc.mock_adapters import MockMemoryAdapter, MockTestingAdapter
from langflow.adlc.mock_executor import MockExecutor
from langflow.adlc.opencode_adapter import OpenCodeAgentAdapter
from langflow.adlc.opencode_client import (
    OpenCodeClientError,
    OpenCodeHttpClient,
    OpenCodeModelSelection,
    OpenCodeServerSettings,
)
from langflow.adlc.task_loop import TASK_LOOP_MOCK_SERVICE, MockTaskLoopExecutor, task_loop_mock_enabled
from langflow.adlc.task_loop_harness import HARNESS_CONTRACT_LOOP_SERVICE, HARNESS_LOOP_SERVICE
from langflow.adlc.task_loop_harness_executor import create_harness_loop_executor
from langflow.adlc.task_loop_live import TASK_LOOP_LIVE_SERVICE, create_live_task_loop_executor

if TYPE_CHECKING:
    from langflow.adlc.adapter_interfaces import TaskExecutor
    from langflow.adlc.artifact_payload_store import BoundedArtifactPayloadStore
    from langflow.adlc.harness_client import HarnessClient
    from langflow.adlc.opencode_client import OpenCodeClient

OPENCODE_ENABLED_ENV = "ADLC_OPENCODE_ENABLED"
OPENCODE_SOURCE_REPOSITORY_ENV = "ADLC_OPENCODE_SOURCE_REPOSITORY"
OPENCODE_WORKTREE_ROOT_ENV = "ADLC_OPENCODE_WORKTREE_ROOT"
OPENCODE_BASE_REF_ENV = "ADLC_OPENCODE_BASE_REF"
DSH_AGENT_ENABLED_ENV = "ADLC_AGENT_ADAPTER"
DSH_MEMORY_ENABLED_ENV = "ADLC_MEMORY_ADAPTER"
TESTING_ADAPTER_ENV = "ADLC_TESTING_ADAPTER"
SANDBOX_ADAPTER_ENV = "ADLC_SANDBOX_ADAPTER"
MOCK_PACKAGE_EXECUTOR_SERVICE = "agent-provider:mock"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class OpenCodeRuntimeSettings:
    """Non-secret activation and local-worktree settings."""

    enabled: bool
    source_repository: Path | None
    worktree_root: Path | None
    base_ref: str

    @classmethod
    def from_environment(cls) -> OpenCodeRuntimeSettings:
        source_value = os.getenv(OPENCODE_SOURCE_REPOSITORY_ENV)
        root_value = os.getenv(OPENCODE_WORKTREE_ROOT_ENV)
        return cls(
            enabled=opencode_execution_enabled(),
            source_repository=Path(source_value).expanduser().resolve() if source_value else None,
            worktree_root=Path(root_value).expanduser().resolve() if root_value else None,
            base_ref=os.getenv(OPENCODE_BASE_REF_ENV, "HEAD"),
        )


class OpenCodeRuntimeReadiness(BaseModel):
    """Credential-free readiness projection safe for authenticated API callers."""

    enabled: bool
    ready: bool
    service: str = OpenCodeAgentAdapter.service_name
    package: str = "coding-agent-opencode@0.1.0"
    server_ready: bool
    server_version: str | None = None
    model_configured: bool
    model_ref: str | None = None
    sandbox_ready: bool
    error_code: str | None = None


def opencode_execution_enabled() -> bool:
    """Return whether live OpenCode routing is explicitly enabled."""
    return os.getenv(OPENCODE_ENABLED_ENV, "").strip().lower() in _TRUE_VALUES


def select_testing_adapter() -> Any:
    """Pick the testing adapter for executor bundles (mock remains the default).

    Opt into the real pytest adapter with ``ADLC_TESTING_ADAPTER=real`` (or
    ``pytest``). Coverage is disabled in this wiring because worktree sandboxes
    rarely carry ``pytest-cov``; construct :class:`PytestTestingAdapter`
    explicitly when coverage measurement is required.
    """
    choice = os.getenv(TESTING_ADAPTER_ENV, "").strip().lower()
    if choice in {"real", "pytest"}:
        from langflow.adlc.adapters.real_testing import PytestConfig, PytestTestingAdapter

        return PytestTestingAdapter(config=PytestConfig(coverage_enabled=False))
    return MockTestingAdapter()


def select_memory_adapter(dsh_client: Any | None = None) -> Any:
    """Pick the memory adapter for executor bundles (mock remains the default).

    Opt in with ``ADLC_MEMORY_ADAPTER=real`` (SQLite-backed persistence) or
    ``=dsh`` (remote DSH plugin memory; requires a DSH harness client).
    """
    choice = os.getenv(DSH_MEMORY_ENABLED_ENV, "").strip().lower()
    if choice == "real":
        from langflow.adlc.adapters.real_memory import SQLiteMemoryAdapter

        return SQLiteMemoryAdapter()
    if choice == "dsh" and dsh_client is not None:
        from langflow.adlc.adapters.dsh_memory import DSHMemoryAdapter, DSHMemoryConfig

        return DSHMemoryAdapter(config=DSHMemoryConfig(dsh_client=dsh_client))
    return MockMemoryAdapter()


def select_sandbox_adapter(
    source_repository: Path,
    *,
    worktree_root: Path | None,
    base_ref: str,
) -> Any:
    """Pick the sandbox adapter for executor bundles (worktree remains default).

    Opt into disposable Docker containers with ``ADLC_SANDBOX_ADAPTER=docker``.
    """
    choice = os.getenv(SANDBOX_ADAPTER_ENV, "").strip().lower()
    if choice == "docker":
        from langflow.adlc.adapters.docker_sandbox import DockerSandboxAdapter

        return DockerSandboxAdapter()
    return LocalWorktreeSandboxAdapter(
        source_repository,
        workspace_root=worktree_root,
        base_ref=base_ref,
    )


def create_default_task_executor(
    settings: OpenCodeRuntimeSettings | None = None,
    *,
    artifact_payloads: BoundedArtifactPayloadStore | None = None,
    harness_settings: HarnessRuntimeSettings | None = None,
    harness_callbacks: HarnessCallbackReceiver | None = None,
    harness_client: HarnessClient | None = None,
) -> TaskExecutorRouter:
    """Compose mock routing plus explicitly enabled external executor bundles."""
    runtime = settings or OpenCodeRuntimeSettings.from_environment()
    mock_executor = MockExecutor()
    routes: dict[str, TaskExecutor] = {MOCK_PACKAGE_EXECUTOR_SERVICE: mock_executor}
    from langflow.adlc.workflow_plugins import SERVICE as PLUGIN_SERVICE
    from langflow.adlc.workflow_plugins import WorkflowPluginExecutor
    from langflow.adlc.workflow_plugins import enabled as workflow_plugins_enabled

    if workflow_plugins_enabled():
        routes[PLUGIN_SERVICE] = WorkflowPluginExecutor()
    from langflow.adlc.harness_workflow import SERVICE, create_workflow_executor

    native_workflow = create_workflow_executor()
    if native_workflow is not None:
        routes[SERVICE] = native_workflow
    if task_loop_mock_enabled():
        routes[TASK_LOOP_MOCK_SERVICE] = MockTaskLoopExecutor()
    loop_executor = create_live_task_loop_executor(artifact_payloads=artifact_payloads)
    if loop_executor is not None:
        routes[TASK_LOOP_LIVE_SERVICE] = loop_executor
    contract_loop_executor = create_contract_loop_executor(artifact_payloads=artifact_payloads)
    if contract_loop_executor is not None:
        routes[CONTRACT_LOOP_SERVICE] = contract_loop_executor
    for contract, service in ((False, HARNESS_LOOP_SERVICE), (True, HARNESS_CONTRACT_LOOP_SERVICE)):
        harness_loop = create_harness_loop_executor(contract=contract, artifact_payloads=artifact_payloads)
        if harness_loop is not None:
            routes[service] = harness_loop
    if runtime.enabled and runtime.source_repository is not None:
        try:
            sandbox = select_sandbox_adapter(
                runtime.source_repository,
                worktree_root=runtime.worktree_root,
                base_ref=runtime.base_ref,
            )
        except ValueError:
            sandbox = None
        if sandbox is not None:
            opencode_executor = AdapterTaskExecutor(
                AdapterBundle(
                    sandbox=sandbox,
                    memory=select_memory_adapter(),
                    testing=select_testing_adapter(),
                    agent=OpenCodeAgentAdapter.from_environment(artifact_payloads=artifact_payloads),
                )
            )
            routes[OpenCodeAgentAdapter.service_name] = opencode_executor

    # DSH agent adapter: opt-in via ADLC_AGENT_ADAPTER=dsh. Delegates task
    # execution to a remote DSH session that uses vai-sandbox, vai-testforce,
    # and vai_agentmemory plugins. No plugin code is downloaded locally.
    if os.getenv(DSH_AGENT_ENABLED_ENV, "").strip().lower() == "dsh":
        from langflow.adlc.adapters.dsh_agent import DSHAgentAdapter

        dsh_client = harness_client if isinstance(harness_client, DshHarnessClient) else None
        if dsh_client is None and harness_settings is not None and harness_settings.enabled:
            from langflow.adlc.harness_dsh_client import DshHarnessClient as _DshClient
            from langflow.adlc.harness_client import HarnessServerSettings

            server_settings = HarnessServerSettings.from_environment()
            dsh_client = _DshClient(server_settings)

        if dsh_client is not None:
            dsh_agent = DSHAgentAdapter(dsh_client)
            dsh_executor = AdapterTaskExecutor(
                AdapterBundle(
                    sandbox=sandbox or select_sandbox_adapter(
                        runtime.source_repository or Path.cwd(),
                        worktree_root=runtime.worktree_root,
                        base_ref=runtime.base_ref,
                    ),
                    memory=select_memory_adapter(dsh_client),
                    testing=select_testing_adapter(),
                    agent=dsh_agent,
                )
            )
            routes[DSHAgentAdapter.service_name] = dsh_executor
    callbacks = harness_callbacks or HarnessCallbackReceiver()
    harness_executor = create_harness_task_executor(
        callbacks,
        harness_settings,
        client=harness_client,
        artifact_payloads=artifact_payloads,
    )
    if harness_executor is not None:
        routes[DeepSeekHarnessTaskExecutor.service_name] = harness_executor
    return TaskExecutorRouter(mock_executor, routes=routes)


async def check_opencode_readiness(
    settings: OpenCodeRuntimeSettings | None = None,
    *,
    client: OpenCodeClient | None = None,
    sandbox: LocalWorktreeSandboxAdapter | None = None,
) -> OpenCodeRuntimeReadiness:
    """Check configuration, server health, and Git workspace availability without running a model."""
    runtime = settings or OpenCodeRuntimeSettings.from_environment()
    if not runtime.enabled:
        return OpenCodeRuntimeReadiness(
            enabled=False,
            ready=False,
            server_ready=False,
            model_configured=False,
            sandbox_ready=False,
            error_code="OPENCODE_EXECUTION_DISABLED",
        )

    server_settings = OpenCodeServerSettings.from_environment()
    model_configured = False
    if server_settings.model is not None:
        try:
            model_configured = OpenCodeModelSelection.parse(server_settings.model) is not None
        except ValueError:
            model_configured = False

    sandbox_ready = False
    sandbox_error: str | None = None
    configured_sandbox = sandbox
    if configured_sandbox is None and runtime.source_repository is not None:
        try:
            configured_sandbox = LocalWorktreeSandboxAdapter(
                runtime.source_repository,
                workspace_root=runtime.worktree_root,
                base_ref=runtime.base_ref,
            )
        except ValueError:
            sandbox_error = "OPENCODE_SANDBOX_CONFIGURATION_INVALID"
    if configured_sandbox is not None:
        try:
            await configured_sandbox.check_readiness()
            sandbox_ready = True
        except LocalWorktreeSandboxError as exc:
            sandbox_error = exc.code
    elif sandbox_error is None:
        sandbox_error = "OPENCODE_SOURCE_REPOSITORY_MISSING"

    server_ready = False
    server_version: str | None = None
    server_error: str | None = None
    try:
        configured_client = client or OpenCodeHttpClient(server_settings)
        server_version = await configured_client.health()
        server_ready = True
    except OpenCodeClientError as exc:
        server_error = exc.code
    except ValueError:
        server_error = "OPENCODE_SERVER_CONFIGURATION_INVALID"

    ready = model_configured and sandbox_ready and server_ready
    error_code: str | None = None
    if not model_configured:
        error_code = "OPENCODE_MODEL_NOT_CONFIGURED"
    elif not sandbox_ready:
        error_code = sandbox_error
    elif not server_ready:
        error_code = server_error

    return OpenCodeRuntimeReadiness(
        enabled=True,
        ready=ready,
        server_ready=server_ready,
        server_version=server_version,
        model_configured=model_configured,
        model_ref=server_settings.model,
        sandbox_ready=sandbox_ready,
        error_code=error_code,
    )


__all__ = [
    "MOCK_PACKAGE_EXECUTOR_SERVICE",
    "OPENCODE_BASE_REF_ENV",
    "OPENCODE_ENABLED_ENV",
    "OPENCODE_SOURCE_REPOSITORY_ENV",
    "OPENCODE_WORKTREE_ROOT_ENV",
    "OpenCodeRuntimeReadiness",
    "OpenCodeRuntimeSettings",
    "check_opencode_readiness",
    "create_default_task_executor",
    "opencode_execution_enabled",
]

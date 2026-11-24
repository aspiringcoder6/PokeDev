# ruff: noqa: INP001, S101

from __future__ import annotations

from pathlib import Path

from langflow.adlc.opencode_runtime import (
    MOCK_PACKAGE_EXECUTOR_SERVICE,
    OpenCodeRuntimeSettings,
    check_opencode_readiness,
    create_default_task_executor,
)


class _HealthyClient:
    async def health(self, *, timeout_ms: int = 5000) -> str:  # noqa: ARG002
        return "1.18.31"


class _ReadySandbox:
    async def check_readiness(self) -> None:
        return None


async def test_readiness_is_explicitly_disabled_without_touching_dependencies() -> None:
    readiness = await check_opencode_readiness(
        OpenCodeRuntimeSettings(
            enabled=False,
            source_repository=None,
            worktree_root=None,
            base_ref="HEAD",
        )
    )

    assert readiness.enabled is False
    assert readiness.ready is False
    assert readiness.error_code == "OPENCODE_EXECUTION_DISABLED"


async def test_readiness_reports_server_model_and_sandbox_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("ADLC_OPENCODE_MODEL", "aigateway/MiniMax/MiniMax-M3")
    readiness = await check_opencode_readiness(
        OpenCodeRuntimeSettings(
            enabled=True,
            source_repository=Path("source"),
            worktree_root=Path("worktrees"),
            base_ref="HEAD",
        ),
        client=_HealthyClient(),
        sandbox=_ReadySandbox(),  # type: ignore[arg-type]
    )

    assert readiness.ready is True
    assert readiness.server_ready is True
    assert readiness.server_version == "1.18.31"
    assert readiness.model_configured is True
    assert readiness.sandbox_ready is True
    assert readiness.error_code is None
    assert "password" not in readiness.model_dump()
    assert "api_key" not in readiness.model_dump()


async def test_readiness_identifies_a_missing_source_repository(monkeypatch) -> None:
    monkeypatch.setenv("ADLC_OPENCODE_MODEL", "aigateway/MiniMax/MiniMax-M3")
    readiness = await check_opencode_readiness(
        OpenCodeRuntimeSettings(
            enabled=True,
            source_repository=None,
            worktree_root=None,
            base_ref="HEAD",
        ),
        client=_HealthyClient(),
    )

    assert readiness.ready is False
    assert readiness.server_ready is True
    assert readiness.sandbox_ready is False
    assert readiness.error_code == "OPENCODE_SOURCE_REPOSITORY_MISSING"


def test_executor_factory_keeps_live_routing_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ADLC_OPENCODE_MODEL", "aigateway/MiniMax/MiniMax-M3")
    disabled = create_default_task_executor(
        OpenCodeRuntimeSettings(
            enabled=False,
            source_repository=None,
            worktree_root=None,
            base_ref="HEAD",
        )
    )
    enabled = create_default_task_executor(
        OpenCodeRuntimeSettings(
            enabled=True,
            source_repository=tmp_path / "source",
            worktree_root=tmp_path / "worktrees",
            base_ref="HEAD",
        )
    )

    assert MOCK_PACKAGE_EXECUTOR_SERVICE in disabled.available_services
    assert "agent-provider:opencode" not in disabled.available_services
    assert "agent-provider:opencode" in enabled.available_services

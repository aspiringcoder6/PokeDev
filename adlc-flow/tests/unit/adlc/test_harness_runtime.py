# ruff: noqa: INP001, S101, S106, S107

from __future__ import annotations

from typing import TYPE_CHECKING

from langflow.adlc.harness_attempts import SqliteTaskAttemptRepository
from langflow.adlc.harness_callbacks import HarnessCallbackReceiver, HarnessCallbackSettings
from langflow.adlc.harness_client import HarnessServerSettings
from langflow.adlc.harness_runtime import (
    HarnessRuntimeSettings,
    check_harness_readiness,
    create_harness_task_executor,
)
from langflow.adlc.opencode_runtime import OpenCodeRuntimeSettings, create_default_task_executor

if TYPE_CHECKING:
    from pathlib import Path


class _HealthyClient:
    async def health(self) -> dict[str, object]:
        return {
            "ready": True,
            "version": "0.1.0",
            "plugin_lock_ready": True,
            "plugin_integrity": {
                "schema_version": "0.1",
                "ready": True,
                "checked_at": "2026-09-27T00:00:00Z",
                "error_code": None,
                "plugins": [],
            },
        }


class _TamperedPluginClient:
    async def health(self) -> dict[str, object]:
        return {
            "ready": False,
            "version": "0.1.0",
            "plugin_lock_ready": False,
            "plugin_integrity": {
                "schema_version": "0.1",
                "ready": False,
                "checked_at": "2026-09-27T00:00:00Z",
                "error_code": "HARNESS_PLUGIN_INTEGRITY_FAILED",
                "plugins": [
                    {
                        "plugin_id": "vai-adlc-runtime",
                        "required": True,
                        "expected_version": "0.1.0",
                        "expected_digest": f"sha256:{'a' * 64}",
                        "installed_version": "0.1.0",
                        "installed_digest": f"sha256:{'b' * 64}",
                        "status": "DIGEST_MISMATCH",
                    }
                ],
            },
        }


def _durable_callbacks(path: Path, *, secret: str | None = "callback-secret") -> HarnessCallbackReceiver:
    return HarnessCallbackReceiver(
        HarnessCallbackSettings(secret=secret),
        attempts=SqliteTaskAttemptRepository(path),
    )


async def test_harness_readiness_requires_callback_server_and_durable_store(tmp_path: Path) -> None:
    callbacks = _durable_callbacks(tmp_path / "attempts.sqlite3")
    readiness = await check_harness_readiness(
        HarnessRuntimeSettings(enabled=True, server=HarnessServerSettings(api_token="token")),
        callbacks=callbacks,
        client=_HealthyClient(),
    )

    assert readiness.ready is True
    assert readiness.callback_ready is True
    assert readiness.attempt_store_ready is True
    assert readiness.server_ready is True
    assert readiness.plugin_lock_ready is True
    assert readiness.plugin_inventory is not None
    assert readiness.server_version == "0.1.0"


def test_harness_executor_factory_is_fail_closed_without_callback_secret() -> None:
    settings = HarnessRuntimeSettings(enabled=True, server=HarnessServerSettings(api_token="token"))

    assert (
        create_harness_task_executor(
            HarnessCallbackReceiver(HarnessCallbackSettings(secret=None)),
            settings,
            client=_HealthyClient(),
        )
        is None
    )


async def test_harness_readiness_is_fail_closed_without_api_token(tmp_path: Path) -> None:
    callbacks = _durable_callbacks(tmp_path / "attempts.sqlite3")
    settings = HarnessRuntimeSettings(enabled=True, server=HarnessServerSettings(api_token=None))

    readiness = await check_harness_readiness(settings, callbacks=callbacks, client=_HealthyClient())

    assert readiness.ready is False
    assert readiness.error_code == "HARNESS_API_TOKEN_NOT_CONFIGURED"
    assert create_harness_task_executor(callbacks, settings, client=_HealthyClient()) is None


async def test_harness_readiness_surfaces_installed_plugin_tampering(tmp_path: Path) -> None:
    callbacks = _durable_callbacks(tmp_path / "attempts.sqlite3")
    readiness = await check_harness_readiness(
        HarnessRuntimeSettings(enabled=True, server=HarnessServerSettings(api_token="token")),
        callbacks=callbacks,
        client=_TamperedPluginClient(),
    )

    assert readiness.ready is False
    assert readiness.plugin_lock_ready is False
    assert readiness.error_code == "HARNESS_PLUGIN_INTEGRITY_FAILED"
    assert readiness.plugin_inventory is not None
    assert readiness.plugin_inventory.plugins[0].status.value == "DIGEST_MISMATCH"


def test_default_executor_router_adds_harness_only_with_complete_activation(tmp_path: Path) -> None:
    callbacks = _durable_callbacks(tmp_path / "attempts.sqlite3")
    router = create_default_task_executor(
        OpenCodeRuntimeSettings(enabled=False, source_repository=None, worktree_root=None, base_ref="HEAD"),
        harness_settings=HarnessRuntimeSettings(
            enabled=True,
            server=HarnessServerSettings(api_token="harness-token"),
        ),
        harness_callbacks=callbacks,
        harness_client=_HealthyClient(),
    )

    assert "agent-provider:deepseek-harness" in router.available_services


async def test_harness_readiness_fails_closed_with_process_local_attempts() -> None:
    callbacks = HarnessCallbackReceiver(HarnessCallbackSettings(secret="callback-secret"))
    readiness = await check_harness_readiness(
        HarnessRuntimeSettings(enabled=True, server=HarnessServerSettings(api_token="token")),
        callbacks=callbacks,
        client=_HealthyClient(),
    )

    assert readiness.ready is False
    assert readiness.error_code == "HARNESS_ATTEMPT_STORE_NOT_CONFIGURED"

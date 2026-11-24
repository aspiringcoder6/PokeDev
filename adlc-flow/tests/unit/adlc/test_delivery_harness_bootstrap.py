"""Offline checks for scoped local reload settings. No Docker or provider calls."""

# ruff: noqa: INP001, S101, PLR2004 - offline pytest assertions.

import runpy
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def bootstrap(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    import check_delivery_harness
    import enable_delivery_iterations

    return check_delivery_harness, enable_delivery_iterations


def state():
    return {
        "Config": {
            "Env": [
                "ADLC_CONTRACT_EXECUTION_ENABLED=true",
                "ADLC_CONTRACT_TOOL_SECRET=offline-existing-fixture",
                "ADLC_HARNESS_DEMO_ENABLED=false",
                "ADLC_VERIFICATION_ENABLED=false",
                "ADLC_TASK_LOOP_HARNESS_ENABLED=false",
            ]
        },
        "Mounts": [
            {"Destination": target, "Source": source, "RW": False, "Type": "bind"}
            for target, source in (
                ("/app/artifact-source", "D:/existing/source"),
                ("/app/project-sources", "D:/existing/snapshots"),
            )
        ],
    }


def test_reload_preserves_source_scope_existing_features_and_verification_gate(bootstrap):
    _, enable = bootstrap
    before = state()
    saved = deepcopy(before)
    environment = enable.reload_environment(before, {"PATH": "fixture-path"})
    assert before == saved
    assert environment["PATH"] == "fixture-path"
    assert environment["ADLC_HARNESS_SOURCE_REPO"] == "D:/existing/source"
    assert environment["ADLC_LOCAL_PROJECT_SOURCE_ROOT"] == "D:/existing/snapshots"
    assert environment["ADLC_CONTRACT_EXECUTION_ENABLED"] == "true"
    assert environment["ADLC_CONTRACT_TOOL_SECRET"] == "offline-existing-fixture"  # noqa: S105 - offline fixture only.
    assert environment["ADLC_HARNESS_DEMO_ENABLED"] == "false"
    assert environment["ADLC_VERIFICATION_HARNESS_ENABLED"] == "false"
    assert environment["ADLC_TASK_LOOP_HARNESS_ENABLED"] == "true"
    assert len(environment["ADLC_HARNESS_ITERATION_API_TOKEN"].encode()) >= 32


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("invalid", ["missing", "writable"])
def test_reload_refuses_to_change_unknown_or_writable_source_mounts(bootstrap, index, invalid):
    _, enable = bootstrap
    before = state()
    if invalid == "missing":
        before["Mounts"].pop(index)
    else:
        before["Mounts"][index]["RW"] = True
    with pytest.raises(RuntimeError, match="read-only source mount"):
        enable.reload_environment(before, {})


def test_backend_receives_only_enabled_independent_iteration_credential(bootstrap):
    check, enable = bootstrap
    before = state()
    assert check.iteration_environment(before) == {}
    configured = enable.reload_environment(before, {})
    before["Config"]["Env"] = [f"{key}={value}" for key, value in configured.items()]
    received = check.iteration_environment(before)
    assert set(received) == {"ADLC_TASK_LOOP_HARNESS_ENABLED", "ADLC_HARNESS_ITERATION_API_TOKEN"}
    assert received["ADLC_HARNESS_ITERATION_API_TOKEN"] == configured["ADLC_HARNESS_ITERATION_API_TOKEN"]
    assert (
        enable.reload_environment(before, {})["ADLC_HARNESS_ITERATION_API_TOKEN"]
        == received["ADLC_HARNESS_ITERATION_API_TOKEN"]
    )


def test_workspace_can_start_offline_without_fabricating_runtime_credentials(bootstrap, monkeypatch):
    check, _ = bootstrap
    monkeypatch.setattr(check, "web_token", Mock(side_effect=RuntimeError("offline fixture")))
    monkeypatch.setenv("ADLC_BLUEPRINT_DSH_TOKEN", "unchanged-offline-fixture")
    monkeypatch.setenv("ADLC_BLUEPRINT_PROVIDER", "offline-provider")
    monkeypatch.setenv("ADLC_BLUEPRINT_MODEL", "offline-model")
    monkeypatch.setenv("ADLC_BLUEPRINT_CWD", "/offline-fixture")
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", Mock(return_value=False))
    import subprocess

    start = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(subprocess, "run", start)
    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(
            str(Path(__file__).resolve().parents[3] / "scripts/start_delivery_workspace.py"), run_name="__main__"
        )
    assert exit_status.value.code == 0
    assert start.call_count == 1
    import os

    assert os.environ["ADLC_BLUEPRINT_DSH_TOKEN"] == "unchanged-offline-fixture"  # noqa: S105 - not a credential.
    assert os.environ["ADLC_BLUEPRINT_MODEL"] == "cx/gpt-5.6-luna"

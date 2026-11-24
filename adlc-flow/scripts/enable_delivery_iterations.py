"""Explicit local Harness reload. Keeps credentials in memory and preserves existing mounts/flags."""

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from shutil import which

from check_delivery_harness import MIN_ITERATION_TOKEN_BYTES, docker_state

PRESERVED_KEYS = (
    "ADLC_CONTRACT_AUTHORING_ENABLED",
    "ADLC_CONTRACT_EXECUTION_ENABLED",
    "ADLC_CONTRACT_RECOVERY_ENABLED",
    "ADLC_CONTRACT_BASE_URL",
    "ADLC_CONTRACT_TOOL_SECRET",
    "ADLC_CONTRACT_UI_URL",
    "ADLC_HARNESS_DEMO_ENABLED",
    "ADLC_DEMO_API_TOKEN",
    "ADLC_DEMO_TOOL_SECRET",
    "ADLC_DEMO_BRIDGE_URL",
    "ADLC_CYCLE_PLANNING_ENABLED",
)


def reload_environment(state, inherited):
    """Never serialize this dictionary: it includes the independent iteration bearer."""
    values = dict(item.split("=", 1) for item in state["Config"]["Env"] if "=" in item)
    environment = dict(inherited)
    environment.update({key: values.get(key, "") for key in PRESERVED_KEYS})
    # The Compose variable names differ from the container variable names here.
    for key in ("ENABLED", "PROVIDER", "SANDBOX_IMAGE", "ALLOW_PRIVATE_HTTP"):
        variable = f"ADLC_VERIFICATION_{key}"
        compose_key = f"ADLC_VERIFICATION_HARNESS_{key}" if key in {"ENABLED", "PROVIDER"} else variable
        environment[compose_key] = values.get(variable, "")
    mounts = {item["Destination"]: item for item in state["Mounts"]}
    for target, key in (
        ("/app/artifact-source", "ADLC_HARNESS_SOURCE_REPO"),
        ("/app/project-sources", "ADLC_LOCAL_PROJECT_SOURCE_ROOT"),
    ):
        mount = mounts.get(target)
        if not mount or mount["RW"] or mount["Type"] != "bind":
            message = "Expected read-only source mount is absent; refusing to change the container."
            raise RuntimeError(message)
        environment[key] = mount["Source"].replace("\\", "/")
    existing = values.get("ADLC_HARNESS_ITERATION_API_TOKEN", "")
    environment["ADLC_TASK_LOOP_HARNESS_ENABLED"] = "true"
    environment["ADLC_HARNESS_ITERATION_API_TOKEN"] = (
        existing if len(existing.encode("utf-8")) >= MIN_ITERATION_TOKEN_BYTES else secrets.token_urlsafe(48)
    )
    return environment


def wait_ready(token):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            "http://127.0.0.1:3080/api/v1/adlc-harness-iterations/health",
            headers={"Authorization": "Bearer " + token},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - fixed loopback HTTP endpoint.
                health = json.load(response)
            if health.get("ready") is True:
                return health
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass
        time.sleep(1)
    message = "Harness did not confirm iteration readiness; no session or model prompt was created."
    raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reload-confirmed", action="store_true", required=True)
    parser.add_argument("--enable-cycle-planning", action="store_true")
    arguments = parser.parse_args()
    harness = Path(__file__).resolve().parents[2] / "agent-harness-server/deepseek-harness"
    state = docker_state()
    labels = state["Config"].get("Labels", {})
    if labels.get("com.docker.compose.project") != "deepseek-harness":
        message = "Unexpected Compose project; refusing to reload."
        raise RuntimeError(message)
    environment = reload_environment(state, os.environ)
    if arguments.enable_cycle_planning:
        environment["ADLC_CYCLE_PLANNING_ENABLED"] = "true"
    docker = which("docker")
    result = subprocess.run(  # noqa: S603 - explicit user-approved reload of one fixed local service, no shell.
        [
            docker,
            "compose",
            "--project-name",
            "deepseek-harness",
            "--file",
            str(harness / "docker-compose.yml"),
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "deepseek-harness",
        ],
        cwd=harness,
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = "Harness reload failed. Check Docker Desktop; no credential was printed."
        raise RuntimeError(message)
    subprocess.run(  # noqa: S603 - fixed, separate planning directory in the existing workspace mount.
        [
            docker,
            "exec",
            "--user",
            "1000",
            "deepseek-harness-bwrap",
            "mkdir",
            "-p",
            "/app/workspace/adlc-blueprint-planning",
        ],
        check=True,
        capture_output=True,
    )
    health = wait_ready(environment["ADLC_HARNESS_ITERATION_API_TOKEN"])
    print(json.dumps({key: health.get(key) for key in ("ready", "runtime", "plugin_digest")}, ensure_ascii=False))
    if arguments.enable_cycle_planning:
        from langflow.adlc.cycle_planning_client import HarnessPlanningClient
        from langflow.adlc.harness_client import HarnessServerSettings

        async def planning_readiness():
            client = HarnessPlanningClient(
                HarnessServerSettings(
                    base_url="http://127.0.0.1:3080", api_token=environment["ADLC_HARNESS_ITERATION_API_TOKEN"]
                )
            )
            try:
                await client.readiness()
            finally:
                await client.aclose()

        import asyncio

        asyncio.run(planning_readiness())
        print(json.dumps({"cycle_planning_ready": True, "model": "cx/gpt-5.6-luna", "model_prompt_sent": False}))


if __name__ == "__main__":
    main()

"""Read-only local readiness check. Never emits credentials or sends a model prompt."""

import asyncio
import json
import re
import subprocess
from shutil import which

from dsh_web_sdk import DshClient, RetryConfig

MIN_ITERATION_TOKEN_BYTES = 32


def docker_state():
    """Container metadata remains internal: Config.Env can contain credentials."""
    docker = which("docker")
    if docker is None:
        message = "Docker is unavailable."
        raise RuntimeError(message)
    result = subprocess.run(  # noqa: S603 - fixed local container inspection, no shell.
        [docker, "inspect", "deepseek-harness-bwrap"],
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)[0]


def iteration_environment(state=None):
    """Read only this adapter's credential into memory, never print or persist it."""
    state = state if state is not None else docker_state()
    values = dict(item.split("=", 1) for item in state["Config"]["Env"] if "=" in item)
    enabled = values.get("ADLC_TASK_LOOP_HARNESS_ENABLED", "").lower() in {"true", "1", "yes", "on"}
    token = values.get("ADLC_HARNESS_ITERATION_API_TOKEN", "")
    if not enabled or len(token.encode("utf-8")) < MIN_ITERATION_TOKEN_BYTES:
        return {}
    result = {"ADLC_TASK_LOOP_HARNESS_ENABLED": "true", "ADLC_HARNESS_ITERATION_API_TOKEN": token}
    if values.get("ADLC_CYCLE_PLANNING_ENABLED", "").lower() in {"true", "1", "yes", "on"}:
        result["ADLC_CYCLE_PLANNING_ENABLED"] = "true"
    return result


def web_token():
    docker = which("docker")
    if docker is None:
        message = "Docker is unavailable."
        raise RuntimeError(message)
    result = subprocess.run(  # noqa: S603 - fixed read-only Docker command; executable resolved locally.
        [docker, "logs", "--tail", "3000", "deepseek-harness-bwrap"],
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    tokens = re.findall(r"https?://[^\s]+[?&]token=([^\s]+)", result.stdout + result.stderr)
    if not tokens:
        message = "No current Harness web credential found; do not print raw logs."
        raise RuntimeError(message)
    return tokens[-1]


async def main():
    async with DshClient("http://127.0.0.1:3080", web_token(), retry=RetryConfig(max_attempts=1)) as client:
        catalogue = await client.rpc("session/modelCatalog", {})
        # Only routing metadata, no provider configuration or credentials.
        print(
            json.dumps(
                {
                    "catalogue_keys": list(catalogue),
                    "default": catalogue.get("default"),
                    "routableProviders": catalogue.get("routableProviders"),
                },
                ensure_ascii=False,
            )
        )
        presets = await client.rpc("agentPresets/list", {})
        print(json.dumps({"presets": [p["id"] for p in presets.get("presets", [])]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

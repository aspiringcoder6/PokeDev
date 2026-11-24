"""Start the local workspace; refresh Harness credentials when available, never print them."""

import os
import subprocess
from pathlib import Path

from check_delivery_harness import iteration_environment, web_token
from dotenv import load_dotenv

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root.parent / ".env", override=False)
    # Browsing durable plans/cycles must not require Docker or a live Harness.
    # Execution keeps its existing authenticated preflight; no substitute token
    # or model is invented when credentials cannot be refreshed.
    try:
        refreshed_web_token = web_token()
        refreshed_iteration = iteration_environment()
    except (RuntimeError, OSError, subprocess.SubprocessError):
        print(
            "Harness credentials were not refreshed; the workspace can start, "
            "but execution still requires runtime readiness."
        )
    else:
        os.environ["ADLC_BLUEPRINT_DSH_TOKEN"] = refreshed_web_token
        os.environ.update(refreshed_iteration)
    os.environ["ADLC_BLUEPRINT_PROVIDER"] = "my-codex"
    os.environ["ADLC_BLUEPRINT_MODEL"] = "cx/gpt-5.6-luna"
    os.environ["ADLC_BLUEPRINT_CWD"] = "/app/workspace/adlc-blueprint-planning"
    result = subprocess.run(  # noqa: S603 - fixed local backend executable and arguments, no shell or user-supplied command.
        [
            str(root / ".venv/Scripts/python.exe"),
            "-X",
            "utf8",
            "-m",
            "langflow.__main__",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            "7860",
            "--backend-only",
            "--env-file",
            str(root.parent / ".env"),
        ],
        check=False,
    )
    raise SystemExit(result.returncode)

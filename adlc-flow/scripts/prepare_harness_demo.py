"""Create isolated demo settings; optionally run one backend worker with existing app settings."""

import argparse
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

FLOW = Path(__file__).resolve().parents[1]
ROOT = FLOW.parent
ENV_FILE = FLOW / "data/harness-demo/demo.env"


def prepare():
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.exists():
        values = {
            "ADLC_HARNESS_DEMO_ENABLED": "true",
            "ADLC_DEMO_API_TOKEN": secrets.token_urlsafe(48),
            "ADLC_DEMO_TOOL_SECRET": secrets.token_urlsafe(48),
            "ADLC_DEMO_GITHUB_WEBHOOK_SECRET": secrets.token_urlsafe(48),
            "ADLC_DEMO_HARNESS_URL": "http://127.0.0.1:3080",
            "ADLC_DEMO_BRIDGE_URL": "http://host.docker.internal:7860",
            "ADLC_DEMO_SANDBOX_IMAGE": "python:3.12-alpine",
            "ADLC_DEMO_GITHUB_ENABLED": "false",
            "ADLC_DEMO_WEBHOOK_AUTO_PLAN": "false",
            "ADLC_DEMO_GITHUB_OWNER_ID": "",
            "ADLC_DEMO_GITHUB_REPOSITORY_ID": "",
            "ADLC_DEMO_MEMORY_PROJECT_ID": "",
        }
        descriptor = os.open(ENV_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("# Private local demo settings. No model/GitHub/provider keys.\n")
            stream.writelines(key + "=" + value + "\n" for key, value in values.items())
    print("Private demo settings preserved at: " + str(ENV_FILE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="store_true")
    parser.add_argument("--export-workflow", type=Path)
    args = parser.parse_args()
    prepare()
    if args.export_workflow:
        import json

        from langflow.adlc.harness_demo_models import WORKFLOW

        args.export_workflow.write_text(json.dumps(WORKFLOW, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.backend:
        # Keep the user's root settings, then override only the private dedicated demo settings.
        load_dotenv(ROOT / ".env", override=False)
        load_dotenv(ENV_FILE, override=True)
        import uvicorn

        # Signed Docker host callbacks need the bridge interface; ordinary app authentication stays enabled.
        uvicorn.run("langflow.main:create_app", factory=True, host="0.0.0.0", port=7860, workers=1)  # noqa: S104


if __name__ == "__main__":
    main()

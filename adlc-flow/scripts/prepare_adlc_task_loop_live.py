"""Create a new, small committed repository and a correctly pinned live-loop spec."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from langflow.adlc.task_loop_live_models import LiveLoopSpec

CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "adlc-contracts/task-loop/v0.2"


def prepare(root: Path) -> dict[str, str]:
    root = root.resolve()
    # Exclusively create a new destination: never reset or overwrite an existing checkout.
    root.mkdir(parents=True, exist_ok=False)
    source = root / "source"
    shutil.copytree(CONTRACT_ROOT / "fixture", source)
    for arguments in (
        ("init", "-q"),
        ("config", "user.name", "ADLC Task Loop Demo"),
        ("config", "user.email", "task-loop@example.invalid"),
        ("config", "core.autocrlf", "false"),
        ("add", "."),
        ("commit", "-qm", "Trusted specification and acceptance tests"),
    ):
        subprocess.run(["git", "-C", str(source), *arguments], check=True, capture_output=True)  # noqa: S603, S607
    commit_read = subprocess.run(  # noqa: S603
        ["git", "-C", str(source), "rev-parse", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    commit = commit_read.stdout.strip()
    payload = json.loads((CONTRACT_ROOT / "examples/task-loop-spec.json").read_text(encoding="utf-8"))
    payload["base_commit"] = commit
    spec = LiveLoopSpec.model_validate(payload)
    spec_path = root / "spec.json"
    spec_path.write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {"source": str(source), "spec": str(spec_path), "state_root": str(root / "state")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="New directory to create; an existing directory is rejected.")
    args = parser.parse_args()
    root = args.root or Path(tempfile.gettempdir()) / ("adlc-task-loop-" + uuid4().hex)
    print(json.dumps(prepare(root), indent=2))


if __name__ == "__main__":
    main()

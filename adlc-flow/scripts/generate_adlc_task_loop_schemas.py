"""Generate separately versioned task-loop schemas without changing frozen contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langflow.adlc.task_loop_live_models import LiveLoopCandidate, LiveLoopSpec, LiveLoopVerification
from langflow.adlc.task_loop_models import (
    MockTaskLoopConfiguration,
    TaskLoopCandidate,
    TaskLoopSpec,
    TaskLoopVerification,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "adlc-contracts/task-loop/v0.1"
MODELS = {
    "task-loop-spec.schema.json": TaskLoopSpec,
    "task-loop-candidate.schema.json": TaskLoopCandidate,
    "task-loop-verification.schema.json": TaskLoopVerification,
    "mock-configuration.schema.json": MockTaskLoopConfiguration,
}
LIVE_OUTPUT = ROOT / "adlc-contracts/task-loop/v0.2"
LIVE_MODELS = {
    "task-loop-spec.schema.json": LiveLoopSpec,
    "task-loop-candidate.schema.json": LiveLoopCandidate,
    "task-loop-verification.schema.json": LiveLoopVerification,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    entries = [(OUTPUT, filename, model) for filename, model in MODELS.items()]
    entries += [(LIVE_OUTPUT, filename, model) for filename, model in LIVE_MODELS.items()]
    for directory, filename, model in entries:
        target = directory / filename
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/task-loop/{directory.name}/{filename}",
            **model.model_json_schema(mode="validation"),
        }
        if args.check:
            if not target.exists() or json.loads(target.read_text(encoding="utf-8")) != schema:
                stale.append(filename)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if stale:
        raise SystemExit("Task-loop schemas out of sync: " + ", ".join(stale))
    print("Task-loop schemas checked." if args.check else "Generated task-loop schemas only.")


if __name__ == "__main__":
    main()

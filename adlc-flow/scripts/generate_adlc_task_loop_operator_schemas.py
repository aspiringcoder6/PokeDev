"""Generate additive Slice C read schemas; frozen execution contracts stay unchanged."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langflow.adlc.task_loop_inspection import RunOperatorControls, TaskLoopInspection

OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts/task-loop-operator/v0.1"
MODELS = {
    "task-loop-inspection.schema.json": TaskLoopInspection,
    "run-operator-controls.schema.json": RunOperatorControls,
}


def schema(filename: str, model) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://adlc.dev/contracts/task-loop-operator/v0.1/{filename}",
        **model.model_json_schema(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    for filename, model in MODELS.items():
        path = OUTPUT / filename
        expected = json.dumps(schema(filename, model), indent=2, ensure_ascii=False) + "\n"
        if arguments.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                print(f"Schema differs: {path}")
                return 1
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

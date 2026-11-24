"""Export additive unpriced Harness iteration schemas; published v0.1 stays frozen."""

import argparse
import json
from pathlib import Path

from langflow.adlc.task_loop_runtime_v2 import (
    LoopIterationOutcomeV2,
    LoopIterationRequestV2,
    LoopRuntimeBindingV2,
    LoopRuntimeCheckpointV2,
    LoopRuntimeSessionV2,
    LoopRuntimeUsageV2,
    LoopRuntimeViewV2,
)

MODELS = {
    "runtime-binding.schema.json": LoopRuntimeBindingV2,
    "iteration-request.schema.json": LoopIterationRequestV2,
    "iteration-outcome.schema.json": LoopIterationOutcomeV2,
    "runtime-session.schema.json": LoopRuntimeSessionV2,
    "runtime-usage.schema.json": LoopRuntimeUsageV2,
    "runtime-checkpoint.schema.json": LoopRuntimeCheckpointV2,
    "runtime-view.schema.json": LoopRuntimeViewV2,
}
OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts/task-loop-runtime/v0.2"


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/task-loop-runtime/v0.2/{name}",
            **model.model_json_schema(),
        }
        for name, model in MODELS.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schemas = generated()
    if not args.check:
        print(json.dumps(schemas, ensure_ascii=False))
        return
    for name, schema in schemas.items():
        path = OUTPUT / name
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != schema:
            msg = f"Harness iteration schema drift: {name}"
            raise SystemExit(msg)
    print(f"Harness iteration: {len(schemas)} schemas match runtime models.")


if __name__ == "__main__":
    main()

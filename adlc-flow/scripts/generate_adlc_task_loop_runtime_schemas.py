"""Export additive runtime contracts; never rewrite published loop/operator/package schemas."""

import argparse
import json
from pathlib import Path

from langflow.adlc.task_loop_runtime_models import (
    LoopCandidateReference,
    LoopIterationOutcome,
    LoopIterationRequest,
    LoopRuntimeBinding,
    LoopRuntimeCheckpoint,
    LoopRuntimeSession,
    LoopRuntimeUsage,
    LoopRuntimeView,
)

OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts/task-loop-runtime/v0.1"
MODELS = {
    "runtime-binding.schema.json": LoopRuntimeBinding,
    "candidate-reference.schema.json": LoopCandidateReference,
    "iteration-request.schema.json": LoopIterationRequest,
    "iteration-outcome.schema.json": LoopIterationOutcome,
    "runtime-session.schema.json": LoopRuntimeSession,
    "runtime-usage.schema.json": LoopRuntimeUsage,
    "runtime-checkpoint.schema.json": LoopRuntimeCheckpoint,
    "runtime-view.schema.json": LoopRuntimeView,
}


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/task-loop-runtime/v0.1/{name}",
            **model.model_json_schema(mode="validation"),
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
            message = f"Task-loop runtime schema drift: {name}"
            raise SystemExit(message)
    print(f"Task-loop runtime: {len(schemas)} schemas match runtime models.")


if __name__ == "__main__":
    main()

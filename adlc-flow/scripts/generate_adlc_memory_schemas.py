"""Export/check H6C closed schemas; preserve all published earlier versions."""

import argparse
import json
from pathlib import Path

from langflow.adlc.project_memory_models import (
    GatewayContext,
    GatewayStatus,
    MemoryBinding,
    MemoryBridgeCommand,
    MemoryCapabilities,
    MemoryChunk,
    MemoryQuery,
    MemoryRead,
    MemoryRecord,
    MemoryView,
)

MODELS = {
    "memory-binding.schema.json": MemoryBinding,
    "memory-bridge-command.schema.json": MemoryBridgeCommand,
    "memory-capabilities.schema.json": MemoryCapabilities,
    "memory-chunk.schema.json": MemoryChunk,
    "memory-query.schema.json": MemoryQuery,
    "memory-read.schema.json": MemoryRead,
    "memory-record.schema.json": MemoryRecord,
    "memory-view.schema.json": MemoryView,
    "gateway-context.schema.json": GatewayContext,
    "gateway-status.schema.json": GatewayStatus,
}
OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "project-memory" / "v0.1"


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/project-memory/v0.1/{name}",
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
        print(json.dumps(schemas, sort_keys=True, ensure_ascii=False))
        return
    for name, schema in schemas.items():
        if not (OUTPUT / name).is_file() or json.loads((OUTPUT / name).read_text(encoding="utf-8")) != schema:
            message = f"H6C schema drift: {name}"
            raise SystemExit(message)
    print(f"H6C: {len(schemas)} closed schemas match runtime models.")


if __name__ == "__main__":
    main()

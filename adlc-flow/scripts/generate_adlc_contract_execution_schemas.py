"""Generate only separately versioned H5C resources, never published H5A/H5B schemas."""

import argparse
import json
from pathlib import Path

from langflow.adlc.contract_execution_models import (
    ContractExecutionBinding,
    ContractExecutionBridgeCommand,
    ContractExecutionOutcome,
    ContractExecutionPolicy,
    ContractExecutionProof,
    ContractExecutionRead,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "adlc-contracts/documents/execution/v0.1"
MODELS = {
    "contract-execution-result.schema.json": ContractExecutionOutcome,
    "contract-execution-read.schema.json": ContractExecutionRead,
    "contract-execution-policy.schema.json": ContractExecutionPolicy,
    "contract-execution-proof.schema.json": ContractExecutionProof,
    "contract-execution-binding.schema.json": ContractExecutionBinding,
    "contract-execution-bridge.schema.json": ContractExecutionBridgeCommand,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for filename, model in MODELS.items():
        target = OUTPUT / filename
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/documents/execution/v0.1/{filename}",
            **model.model_json_schema(mode="validation"),
        }
        if args.check:
            if not target.exists() or json.loads(target.read_text(encoding="utf-8")) != schema:
                stale.append(filename)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if stale:
        raise SystemExit("H5C schemas out of sync: " + ", ".join(stale))
    print("H5C schemas checked." if args.check else "Generated H5C schemas only.")


if __name__ == "__main__":
    main()

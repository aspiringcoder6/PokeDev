"""Export/check the new H6B schemas without changing H4/H5/H6A schemas."""

import argparse
import json
from pathlib import Path

from langflow.adlc.replay_models import (
    CreateReplayPlan,
    ReplayCapabilities,
    ReplayPlan,
    ReplayRead,
    ReplayReceipt,
    ReplayReport,
)
from langflow.adlc.verification_models import ExactVerificationCommand

MODELS = {
    "create-replay-plan.schema.json": CreateReplayPlan,
    "exact-replay-command.schema.json": ExactVerificationCommand,
    "replay-capabilities.schema.json": ReplayCapabilities,
    "replay-plan.schema.json": ReplayPlan,
    "replay-read.schema.json": ReplayRead,
    "replay-receipt.schema.json": ReplayReceipt,
    "replay-report.schema.json": ReplayReport,
}
OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "verification-replay" / "v0.1"


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/verification-replay/v0.1/{name}",
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
        print(json.dumps(schemas, ensure_ascii=False, sort_keys=True))
        return
    for name, schema in schemas.items():
        if not (OUTPUT / name).is_file() or json.loads((OUTPUT / name).read_text(encoding="utf-8")) != schema:
            message = f"H6B schema drift: {name}"
            raise SystemExit(message)
    print(f"H6B: {len(schemas)} closed schemas match runtime models.")


if __name__ == "__main__":
    main()

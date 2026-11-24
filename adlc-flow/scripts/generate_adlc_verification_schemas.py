"""Generate/check H6A's separate closed schemas; never rewrite published H4/H5."""

import argparse
import json
from pathlib import Path

from langflow.adlc.verification_models import (
    CreateVerificationPlan,
    ExactVerificationCommand,
    ExecutionReceipt,
    VerificationCapabilities,
    VerificationPlan,
    VerificationRead,
    VerificationReport,
)

MODELS = {
    "create-verification-plan.schema.json": CreateVerificationPlan,
    "exact-verification-command.schema.json": ExactVerificationCommand,
    "execution-receipt.schema.json": ExecutionReceipt,
    "verification-capabilities.schema.json": VerificationCapabilities,
    "verification-plan.schema.json": VerificationPlan,
    "verification-read.schema.json": VerificationRead,
    "verification-report.schema.json": VerificationReport,
}
OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "verification" / "v0.1"


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/verification/v0.1/{name}",
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
        # stdout lets the editor/apply_patch own filesystem mutation.
        print(json.dumps(schemas, ensure_ascii=False, sort_keys=True))
        return
    for name, schema in schemas.items():
        if not (OUTPUT / name).is_file() or json.loads((OUTPUT / name).read_text(encoding="utf-8")) != schema:
            message = f"H6A schema drift: {name}"
            raise SystemExit(message)
    print(f"H6A: {len(schemas)} closed schemas match runtime models.")


if __name__ == "__main__":
    main()

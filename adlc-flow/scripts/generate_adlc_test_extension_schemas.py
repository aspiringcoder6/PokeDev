"""Export/check H6D sidecars without changing any published H4/H5/H6 profiles."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from langflow.adlc.test_extension_models import (
    ExtensionCapabilities,
    PerformanceBudget,
    ProposalBridgeCommand,
    ProposalCommand,
    ProposalDecision,
    ProposalRead,
    ProposalReference,
    ReplaySource,
    ScreenshotRead,
    ScreenshotUpload,
    TestPermissions,
    TestProposal,
)

MODELS = {
    "extension-capabilities.schema.json": ExtensionCapabilities,
    "performance-budget.schema.json": PerformanceBudget,
    "proposal-bridge-command.schema.json": ProposalBridgeCommand,
    "proposal-command.schema.json": TypeAdapter(ProposalCommand),
    "proposal-decision.schema.json": ProposalDecision,
    "proposal-read.schema.json": ProposalRead,
    "proposal-reference.schema.json": ProposalReference,
    "replay-source.schema.json": ReplaySource,
    "screenshot-read.schema.json": ScreenshotRead,
    "screenshot-upload.schema.json": ScreenshotUpload,
    "test-permissions.schema.json": TestPermissions,
    "test-proposal.schema.json": TestProposal,
}
OUTPUT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "test-extensions" / "v0.1"


def generated():
    return {
        name: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://adlc.dev/contracts/test-extensions/v0.1/{name}",
            **(model.json_schema() if isinstance(model, TypeAdapter) else model.model_json_schema(mode="validation")),
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
            message = f"H6D schema drift: {name}"
            raise SystemExit(message)
    print(f"H6D: {len(schemas)} closed schemas match runtime models.")


if __name__ == "__main__":
    main()

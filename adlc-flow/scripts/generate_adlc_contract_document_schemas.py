"""Generate/check H5A document and tool schemas; copy the same schemas into the plugin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langflow.adlc.contract_authoring_models import SkilltreeAuthoringOutcome
from langflow.adlc.contract_models import (
    TOOL_ARGUMENT_MODELS,
    ContractApprovalCommand,
    ContractBridgeCommand,
    ContractForkCommand,
    ContractPluginManifest,
    ContractRead,
    ContractReference,
    ContractToolCommand,
    ContractToolResult,
    SkilltreeDocument,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPOSITORY_ROOT / "adlc-contracts" / "documents" / "v0.1"
PLUGIN_ROOT = REPOSITORY_ROOT / "agent-harness-server" / "deepseek-harness" / "plugins" / "vai-adlc-skilltree"
SCHEMA_BASE_URI = "https://adlc.dev/contracts/documents/v0.1"
MODELS = {
    "skilltree-document.schema.json": SkilltreeDocument,
    "contract-read.schema.json": ContractRead,
    "contract-reference.schema.json": ContractReference,
    "contract-tool-command.schema.json": ContractToolCommand,
    "contract-tool-result.schema.json": ContractToolResult,
    "contract-approval-command.schema.json": ContractApprovalCommand,
    "contract-fork-command.schema.json": ContractForkCommand,
    "contract-bridge-command.schema.json": ContractBridgeCommand,
    "contract-plugin.schema.json": ContractPluginManifest,
    **{f"{name}.schema.json": model for name, model in TOOL_ARGUMENT_MODELS.items()},
}


def generate_schema(filename, model) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE_URI}/{filename}",
        **model.model_json_schema(mode="validation"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for filename, model in MODELS.items():
        schema = generate_schema(filename, model)
        targets = [OUTPUT_ROOT / filename]
        if filename == "skilltree-document.schema.json" or filename.startswith("skilltree_"):
            targets.append(PLUGIN_ROOT / "contracts" / filename)
        for target in targets:
            if args.check:
                if not target.exists() or json.loads(target.read_text(encoding="utf-8")) != schema:
                    mismatches.append(str(target.relative_to(REPOSITORY_ROOT)))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
    manifest = ContractPluginManifest.model_validate_json((PLUGIN_ROOT / "contract-plugin.json").read_bytes())
    # Separate H5B result resource. Never updates the published H5A plugin copies.
    result_target = OUTPUT_ROOT.parent / "authoring" / "v0.1" / "skilltree-authoring-result.schema.json"
    result_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://adlc.dev/contracts/documents/authoring/v0.1/skilltree-authoring-result.schema.json",
        **SkilltreeAuthoringOutcome.model_json_schema(mode="validation"),
    }
    if args.check:
        if not result_target.exists() or json.loads(result_target.read_text(encoding="utf-8")) != result_schema:
            mismatches.append(str(result_target.relative_to(REPOSITORY_ROOT)))
    else:
        result_target.parent.mkdir(parents=True, exist_ok=True)
        result_target.write_text(
            json.dumps(result_schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if manifest.plugin_id != "vai-adlc-skilltree":
        mismatches.append("contract-plugin identity")
    if mismatches:
        raise SystemExit("Contract schemas out of sync: " + ", ".join(mismatches))
    print(
        "H5A document/tool/plugin and H5B authoring-result schemas are in sync."
        if args.check
        else "Generated H5A document/tool and H5B authoring-result schemas."
    )


if __name__ == "__main__":
    main()

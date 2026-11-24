"""Generate standalone ADLC Harness v0.1 JSON Schemas from Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from langflow.adlc.harness_models import (
    HarnessArtifactRead,
    HarnessCallbackReceipt,
    HarnessInteractionReceipt,
    HarnessInteractionResponse,
    HarnessPluginInventory,
    HarnessReconciliationReport,
    HarnessResultDelivery,
    HarnessRunResultProjection,
    HarnessRunSessionProjection,
    HarnessSessionAccepted,
    HarnessSessionEvent,
    HarnessSessionRead,
    HarnessSessionRequest,
    HarnessSessionResult,
    HarnessSubmissionReceipt,
    HarnessVerificationReport,
    TaskAttemptRecord,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

SCHEMA_BASE_URI = "https://adlc.dev/contracts/harness/v0.1"
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "harness" / "v0.1"

MODELS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("artifact-read.schema.json", HarnessArtifactRead),
    ("session-request.schema.json", HarnessSessionRequest),
    ("session-event.schema.json", HarnessSessionEvent),
    ("session-read.schema.json", HarnessSessionRead),
    ("session-accepted.schema.json", HarnessSessionAccepted),
    ("interaction-response.schema.json", HarnessInteractionResponse),
    ("interaction-receipt.schema.json", HarnessInteractionReceipt),
    ("plugin-inventory.schema.json", HarnessPluginInventory),
    ("submission-receipt.schema.json", HarnessSubmissionReceipt),
    ("verification-report.schema.json", HarnessVerificationReport),
    ("session-result.schema.json", HarnessSessionResult),
    ("result-delivery.schema.json", HarnessResultDelivery),
    ("callback-receipt.schema.json", HarnessCallbackReceipt),
    ("task-attempt.schema.json", TaskAttemptRecord),
    ("run-session-projection.schema.json", HarnessRunSessionProjection),
    ("run-result-projection.schema.json", HarnessRunResultProjection),
    ("reconciliation-report.schema.json", HarnessReconciliationReport),
)


def generate_schema(filename: str, model: type[BaseModel]) -> dict[str, object]:
    generated = model.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{SCHEMA_BASE_URI}/{filename}",
        **generated,
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS:
        payload = json.dumps(generate_schema(filename, model), ensure_ascii=False, indent=2, sort_keys=True)
        output_path = OUTPUT_ROOT / filename
        output_path.write_text(f"{payload}\n", encoding="utf-8")
        print(f"generated {output_path}")


if __name__ == "__main__":
    main()

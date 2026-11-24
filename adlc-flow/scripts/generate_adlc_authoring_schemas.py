"""Generate the ADLC workflow v0.1 JSON Schemas from their Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from langflow.adlc.blueprints import ExecutionPlan, NodePackageDefinition, WorkflowDefinition

if TYPE_CHECKING:
    from pydantic import BaseModel

SCHEMA_BASE_URI = "https://adlc.dev/contracts/workflow/v0.1"
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "adlc-contracts" / "workflow" / "v0.1"

MODELS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("node-package.schema.json", NodePackageDefinition),
    ("workflow-definition.schema.json", WorkflowDefinition),
    ("execution-plan.schema.json", ExecutionPlan),
)


def generate_schema(filename: str, model: type[BaseModel]) -> dict[str, object]:
    """Build one standalone Draft 2020-12 schema with a stable canonical ID."""
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
        (OUTPUT_ROOT / filename).write_text(f"{payload}\n", encoding="utf-8")
        print(f"generated {OUTPUT_ROOT / filename}")


if __name__ == "__main__":
    main()

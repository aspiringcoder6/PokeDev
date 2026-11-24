"""Generate the unified agent's separate contract-loop evidence schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langflow.adlc.coding_agent_loop_models import CodingAgentContractVerification


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[2] / "adlc-contracts/coding-agent/v0.1/contract-verification.schema.json"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://adlc.dev/contracts/coding-agent/v0.1/contract-verification.schema.json",
        **CodingAgentContractVerification.model_json_schema(mode="validation"),
    }
    if args.check:
        if not target.exists() or json.loads(target.read_text(encoding="utf-8")) != schema:
            message = "Unified Coding Agent schema is out of sync."
            raise SystemExit(message)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Unified Coding Agent schema checked." if args.check else "Generated Unified Coding Agent schema.")


if __name__ == "__main__":
    main()

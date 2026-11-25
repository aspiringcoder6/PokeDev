"""ExplorationTrace step records, schema validation and the step coverage gate."""
import json
import jsonschema
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "exploration_trace.schema.json"


def validate_step(record):
    """Validate one step record against schemas/exploration_trace.schema.json."""
    jsonschema.validate(record, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def write_trace(session_dir, records):
    """Persist step records as JSONL so a crashed exploration still leaves evidence."""
    path = Path(session_dir) / "trace.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    return str(path)


def read_trace(session_dir):
    path = Path(session_dir) / "trace.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_coverage(required_steps, records):
    """Machine-readable step coverage: every required Gherkin step must be GROUNDED."""
    statuses = {r["step_id"]: r["status"] for r in records}
    coverage = [{"step_id": step_id, "status": statuses.get(step_id, "MISSING")} for step_id in required_steps]
    covered = sum(1 for c in coverage if c["status"] == "GROUNDED")
    return {
        "coverage": coverage,
        "required": len(required_steps),
        "covered": covered,
        "grounded": len(required_steps) > 0 and covered == len(required_steps),
        "deviated": [c["step_id"] for c in coverage if c["status"] == "DEVIATED"],
        "missing": [c["step_id"] for c in coverage if c["status"] == "MISSING"],
    }

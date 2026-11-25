"""Exploration session: total deadline, provenance and the owned-data registry."""
import json
import time
import uuid
from pathlib import Path

from .trace import validate_step


class ExplorerError(ValueError):
    pass


class DeviationError(Exception):
    """Action executed but the observed outcome did not match the step expectation."""


def _now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ExplorationSession:
    """One browser-grounded exploration run with a hard wall-clock budget."""

    def __init__(self, output_root="artifacts/automation/exploration", base_url="", actor="anonymous",
                 total_deadline_ms=600000, video=False, run_id=None):
        self.run_id = run_id or ("EXPLORE-" + uuid.uuid4().hex)
        self.root = Path(output_root).resolve() / self.run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.started_at = time.time()
        if int(total_deadline_ms) <= 0:
            raise ExplorerError("Exploration requires a positive total deadline")
        self.total_deadline_ms = int(total_deadline_ms)
        self.provenance = {"base_url": base_url, "actor": actor, "mode": "exploration", "video": bool(video)}
        self.owned = []
        self.records = []
        self._trace_path = self.root / "trace.jsonl"
        self._trace_path.write_text("", encoding="utf-8")

    def elapsed_ms(self):
        return int((time.time() - self.started_at) * 1000)

    def check_total_deadline(self):
        if self.elapsed_ms() > self.total_deadline_ms:
            raise ExplorerError(
                f"Exploration total deadline exceeded: {self.elapsed_ms()}ms > {self.total_deadline_ms}ms")

    def register_owned(self, entity_id, cleanup_path=None):
        """Persist immediately after each successful POST so cleanup survives a mid-run failure.

        cleanup_path=None marks an unresolved cleanup candidate — the promotion gate
        must block on it until a reviewed DELETE contract confirms it.
        """
        if entity_id is None or str(entity_id) in ("", ".", ".."):
            raise ExplorerError("Owned entity lacks ID; cleanup requires intervention")
        item = {"id": entity_id, "cleanup_path": cleanup_path or "", "resolved": bool(cleanup_path)}
        self.owned.append(item)
        (self.root / "owned.json").write_text(json.dumps(self.owned, indent=2), encoding="utf-8")

    def append_record(self, record):
        validate_step(record)
        self.records.append(record)
        with self._trace_path.open("a", encoding="utf-8") as trace:
            trace.write(json.dumps(record, ensure_ascii=False) + "\n")

    def finalize(self, status):
        summary = {"run_id": self.run_id, "status": status, **self.provenance,
                   "started_at": _now_ts(), "ended_at": _now_ts(), "duration_ms": self.elapsed_ms(),
                   "steps": len(self.records), "owned": self.owned}
        (self.root / "session_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

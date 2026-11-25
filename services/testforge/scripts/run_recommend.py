"""Agent 3 CLI — PRUN FAIL -> Recommendation REC-*.

Luồng:
    1. Tìm PRUN (theo id, hoặc --latest-fail = PRUN FAIL mới nhất)
    2. OptimizationAgent.analyze(performance_result, requirement, capacity_report)
    3. Validate theo schemas/recommendation.schema.json
    4. Ghi artifacts/automation/recommendations/REC-<id>.json

Ví dụ:
    python scripts/run_recommend.py --latest-fail
    python scripts/run_recommend.py --perf-run PRUN-1790424967
    python scripts/run_recommend.py --latest-fail --no-llm          # heuristic Zero-LLM
    python scripts/run_recommend.py --latest-fail --capacity       # nạp aggregated report
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent3.optimizer import OptimizationAgent, validate_recommendation  # noqa: E402

PERF_ROOT = PROJECT_ROOT / "artifacts" / "automation" / "performance"
REC_DIR = PROJECT_ROOT / "artifacts" / "automation" / "recommendations"


def find_perf_run(spec: str) -> Path:
    """spec = PRUN-<id> hoặc đường dẫn thư mục PRUN."""
    p = Path(spec)
    if p.is_dir():
        return p
    cand = PERF_ROOT / spec
    if cand.is_dir():
        return cand
    raise SystemExit("Không tìm thấy PRUN: {0}".format(spec))


def find_latest_fail() -> Path:
    best, best_mtime = None, -1.0
    for d in PERF_ROOT.glob("PRUN-*"):
        rf = d / "performance_result.json"
        if not rf.is_file():
            continue
        try:
            r = json.loads(rf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("overall_status") == "FAIL":
            mt = rf.stat().st_mtime
            if mt > best_mtime:
                best, best_mtime = d, mt
    if best is None:
        raise SystemExit("Không có PRUN FAIL nào trong {0}".format(PERF_ROOT))
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent 3: phân tích PRUN FAIL -> recommendation")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--perf-run", help="PRUN-<id> hoặc đường dẫn thư mục PRUN")
    src.add_argument("--latest-fail", action="store_true", help="PRUN FAIL mới nhất")
    ap.add_argument("--no-llm", action="store_true", help="Chỉ heuristic Zero-LLM (không gọi LLM)")
    ap.add_argument("--capacity", action="store_true",
                    help="Nạp aggregated report cùng perf_req_id (nếu có) làm evidence")
    ap.add_argument("--context", default="", help="Context thêm cho LLM (source/config/SQL...)")
    ap.add_argument("--out", default="", help="Ghi REC ra đường dẫn khác (mặc định thư mục chuẩn)")
    args = ap.parse_args()

    run_dir = find_perf_run(args.perf_run) if args.perf_run else find_latest_fail()
    rf = run_dir / "performance_result.json"
    result = json.loads(rf.read_text(encoding="utf-8"))
    req_path = run_dir / "requirement.json"
    requirement = None
    if req_path.exists():
        try:
            requirement = json.loads(req_path.read_text(encoding="utf-8"))
        except ValueError:
            requirement = None

    capacity = None
    if args.capacity:
        req_id = (result.get("perf_req_id") or "").lower()
        cap_path = PERF_ROOT / "aggregated_report_{0}.json".format(req_id or "unknown")
        if cap_path.exists():
            capacity = json.loads(cap_path.read_text(encoding="utf-8"))

    llm = None
    if args.no_llm:
        from src.agent1.healer.llm_client import OpenCodeChatClient
        llm = OpenCodeChatClient(base_url="", api_key="")  # available()=False -> heuristic
    agent = OptimizationAgent(llm_client=llm) if args.no_llm else OptimizationAgent()
    out = agent.analyze(result, requirement=requirement, capacity_report=capacity,
                        extra_context=args.context)
    if not out["ok"]:
        for e in out["errors"]:
            print("ERROR: {0}".format(e))
        return 2

    rec = out["recommendation"]
    errors = validate_recommendation(rec)
    REC_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REC_DIR / "{0}.json".format(rec["rec_id"])
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    print("REC: {0} (PRUN: {1})".format(rec["rec_id"], rec["perf_run_id"]))
    print("  issue : {0} observed={1} threshold={2} (+{3}%)".format(
        rec["issue_summary"]["metric"], rec["issue_summary"]["observed"],
        rec["issue_summary"]["threshold"], rec["issue_summary"]["deviation_percent"]))
    print("  model : {0} | prompt {1}".format(rec["llm_model"], rec["llm_prompt_version"]))
    for c in rec["likely_causes"]:
        print("  cause #{0} ({1}): {2}".format(c["rank"], c["confidence"], c["cause"][:100]))
    for r in rec["recommendations"]:
        print("  [{0}] {1} -> {2}".format(r["priority"], r["action"][:100], r["target"]))
    if errors:
        print("  (schema warnings: {0})".format("; ".join(errors[:2])))
    print("saved: {0}".format(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

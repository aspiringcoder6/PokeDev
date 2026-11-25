"""scripts/run_perf.py — CLI Agent 2: Performance Test orchestrator.

Luồng: functional gate check → load requirement → generate k6 (Zero-LLM) →
static validate (10 rule) → run k6 → threshold evaluate → performance_result.json.

Cách chạy:
    python scripts/run_perf.py --requirement opt/perf/perf_login.json --profile peak \
        --base-url http://localhost --users-json opt/perf/users.json

Gate: nếu functional_result mới nhất cũ hơn 1h hoặc gate_passed=False → chặn
trừ khi --approved-by override + --justification.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jsonschema

from src.agent2.k6_generator import generate_script
from src.agent2.perf_requirement import resolve_requirement
from src.agent2.reporter import save_report
from src.agent2.runner import run_k6
from src.agent2.static_validator import validate as static_validate
from src.agent2.threshold_evaluator import evaluate

ROOT = Path(__file__).resolve().parents[1]
RESULT_SCHEMA = ROOT / "schemas" / "performance_result.schema.json"
REQ_SCHEMA = ROOT / "schemas" / "performance_requirement.schema.json"


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _check_functional_gate(override_by="", justification="", staging_dir=None):
    """Đọc functional_result mới nhất → gate_passed? Override nếu có --approved-by."""
    if staging_dir and Path(staging_dir).is_dir():
        latest = Path(staging_dir)
    else:
        functional_root = ROOT / "artifacts" / "automation" / "staging"
        candidates = sorted([p for p in functional_root.glob("STAGING-*") if p.is_dir()], key=lambda p: p.stat().st_mtime)
        latest = candidates[-1] if candidates else None
    if not latest or not (latest / "summary.json").is_file():
        return {"passed": True, "note": "no functional_result found - allowing perf (dev mode)", "handoff": None}
    result = _load_json(latest / "summary.json")
    gate_passed = result.get("gate_passed", False)
    handoff = None
    if (latest / "performance_handoff.json").is_file():
        try:
            handoff = _load_json(latest / "performance_handoff.json")
        except Exception:
            handoff = None
    if gate_passed:
        return {"passed": True, "note": str(latest.name), "handoff": handoff}
    if override_by.strip() and justification.strip():
        return {"passed": True, "note": "OVERRIDE by {0}: {1}".format(override_by, justification),
                "override": {"approved_by": override_by, "justification": justification},
                "handoff": handoff}
    return {"passed": False, "note": "functional gate FAILED in {0}. Use --approved-by + --justification to override"
            .format(latest.name), "handoff": None}


def main():
    parser = argparse.ArgumentParser(description="Agent 2 Performance Test runner")
    parser.add_argument("--requirement", required=True, help="Path to perf requirement JSON")
    parser.add_argument("--profile", default="normal", choices=["normal", "peak", "stress",
                                                                 "smoke"])
    parser.add_argument("--tier", default=None, choices=["core", "crud", "heavy"],
                        help="Tier fallback if thresholds missing in requirement")
    parser.add_argument("--handoff", default=None, help="Path to performance_handoff.json")
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--users-json", default="opt/perf/users.json")
    parser.add_argument("--output", default="artifacts/automation/performance")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--approved-by", default="", help="HITL override khi functional FAIL hoặc threshold warning")
    parser.add_argument("--justification", default="", help="Lý do override")
    parser.add_argument("--staging-dir", default=None, help="Explicit path to STAGING run directory to check gate from")
    parser.add_argument("--override-thresholds", nargs="*", default=[],
                        help="Danh sách threshold names được HITL override sang WARNING")
    parser.add_argument("--capacity-report", action="store_true",
                        help="Sau khi chạy, tổng hợp capacity estimation từ mọi PRUN cùng perf_req_id")
    args = parser.parse_args()

    gate = _check_functional_gate(args.approved_by, args.justification, staging_dir=args.staging_dir)
    if not gate["passed"]:
        print(json.dumps({"error": "gate_blocked", "detail": gate["note"]}), file=sys.stderr)
        sys.exit(2)
    print(">>> Gate: {0}".format(gate["note"]))

    requirement = _load_json(args.requirement)
    endpoint = requirement.get("test_target", {}).get("endpoint", "")
    tier = args.tier or requirement.get("tier", "crud")
    requirement = resolve_requirement(endpoint, tier=tier, base_requirement=requirement)

    req_schema = _load_json(REQ_SCHEMA)
    req_errors = sorted(jsonschema.Draft202012Validator(req_schema).iter_errors(requirement),
                        key=str)
    if req_errors:
        print(json.dumps({"error": "invalid_requirement",
                          "details": [e.message for e in req_errors[:3]]}), file=sys.stderr)
        sys.exit(1)

    handoff = None
    if args.handoff and Path(args.handoff).is_file():
        handoff = _load_json(args.handoff)
        print(">>> Using explicit handoff from {0}".format(args.handoff))
    elif gate.get("handoff"):
        handoff = gate["handoff"]
        print(">>> Using verified handoff from functional gate")

    perf_req_id = requirement["perf_req_id"]
    run_dir = Path(args.output) / "PRUN-{0}".format(int(time.time()))
    run_dir.mkdir(parents=True, exist_ok=True)

    print(">>> Generating k6 script (Zero-LLM)...")
    script_text = generate_script(requirement, args.profile, handoff=handoff)
    script_path = run_dir / "{0}_{1}.js".format(perf_req_id.lower(), args.profile)
    script_path.write_text(script_text, encoding="utf-8")

    print(">>> Static validation (10 rule SVP01-SVP10)...")
    sv_result = static_validate(script_text, requirement)
    if not sv_result["valid"]:
        print(json.dumps({"error": "static_validation_failed",
                          "errors": sv_result["errors"][:5]}), file=sys.stderr)
        sys.exit(1)
    print("    SVP: PASS ({0} warnings)".format(len(sv_result["warnings"])))

    users_abs = str((ROOT / args.users_json).resolve())
    if not Path(users_abs).is_file():
        print("users.json not found at {0}".format(users_abs), file=sys.stderr)
        sys.exit(1)

    print(">>> Running k6 ({0}, profile={1})...".format(perf_req_id, args.profile))
    metrics = run_k6(str(script_path), base_url=args.base_url, users_json=users_abs,
                     output_dir=str(run_dir), timeout_seconds=args.timeout_seconds)
    print("    requests={total_requests}, p95={p95_ms}, rps={throughput_rps}".format(**metrics))

    print(">>> Evaluating thresholds...")
    trigger_override = gate.get("override")
    hitl_overrides = []
    if args.approved_by and args.override_thresholds:
        hitl_overrides.append({
            "approved_by": args.approved_by,
            "justification": args.justification or "Manual HITL threshold override",
            "thresholds_override": args.override_thresholds,
        })

    result = evaluate(
        requirement["thresholds"], metrics, perf_req_id, args.profile,
        script_ref=str(script_path), environment="local-docker",
        hitl_overrides=hitl_overrides,
    )
    if trigger_override:
        result["trigger_override"] = trigger_override

    schema = _load_json(RESULT_SCHEMA)
    jsonschema.validate(result, schema)

    ndjson_path = run_dir / "results.ndjson"
    saved = save_report(
        result=result,
        requirement=requirement,
        output_dir=run_dir,
        script_path=script_path,
        data_path=users_abs,
        ndjson_path=ndjson_path if ndjson_path.is_file() else None,
    )
    result_path = saved["result"]

    print("\n=== Performance Result ===")
    print("  PRUN: {0} | profile: {1}".format(result["perf_run_id"], result["profile"]))
    print("  metrics: p50={0}ms, p95={1}ms, p99={2}ms".format(
        result["metrics"].get("p50_ms"), result["metrics"].get("p95_ms"),
        result["metrics"].get("p99_ms")))
    print("  throughput: {0} rps | error_rate: {1} | requests: {2}".format(
        result["metrics"]["throughput_rps"], result["metrics"]["error_rate"],
        result["metrics"]["total_requests"]))
    for ev in result["threshold_evaluation"]:
        mark = "✓" if ev["result"] == "PASS" else ("⚠" if ev["result"] == "PASS_WITH_WARNING" else "✗")
        print("  {0} {1}: {2} vs {3} -> {4}".format(
            mark, ev["metric"], ev["actual"], ev["threshold"], ev["result"]))
    print("  overall: {0} | action: {1}".format(result["overall_status"], result["action"]))
    print("  result: {0}".format(result_path))

    if args.capacity_report:
        from src.agent2.capacity_estimator import estimate_capacity, save_aggregated_report
        cap = estimate_capacity(perf_req_id)
        cap_path = save_aggregated_report(cap)
        print("\n=== Capacity Estimation ({0} datapoints) ===".format(cap.get("datapoints", 0)))
        print("  peak_rps: {0} | max_concurrency: {1}".format(
            cap.get("estimated_peak_rps"), cap.get("estimated_max_concurrency")))
        print("  saturation: {0} at {1} VU".format(
            cap.get("saturation_observed"), cap.get("saturation_point_vus", "N/A")))
        for s in cap.get("bottleneck_signals", []):
            print("  signal: {0}".format(s))
        if cap.get("dev_recommendation"):
            print("  → {0}".format(cap["dev_recommendation"]))
        print("  report: {0}".format(cap_path))

    sys.exit(0 if result["overall_status"] in ("PASS", "PASS_WITH_WARNING") else 1)


if __name__ == "__main__":
    main()

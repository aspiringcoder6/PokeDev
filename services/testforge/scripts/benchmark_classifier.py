"""TestForge AI — M3.1 Day 4: Dev-set Classification Benchmark (BLIND).

Chạy N lần mỗi case C01-C06 qua pipeline rút gọn (generate -> execute -> analyze),
FailureAnalyzer KHÔNG nhận bất kỳ thông tin nào về fault/ground truth (blind).
Harness giữ ground truth và so sánh sau khi analyzer trả kết quả.

Output:
- artifacts/experiments/classification_report_dev.json
- Confusion matrix + accuracy + stability, in ra console

Sau khi dev-set đạt 6/6 + stable -> FREEZE failure_analyzer.py (Ngày 5 chỉ chạy eval).
"""

import argparse
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scripts.collect_failure_fixtures import CASES, run_one
from src.agent1.analyzer.failure_analyzer import FailureAnalyzer

REPORT_PATH = Path("artifacts/experiments/classification_report_dev.json")


def main() -> None:
    runs = 3
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])

    results = {}
    for case_id, case in CASES.items():
        tc = case["test_case"]
        fault = case.get("fault")
        perturb = case.get("perturb_oracle", False)
        timeout_ms = case.get("timeout_ms")

        predictions = []
        print(f"\n=== {case_id} (ground truth giữ ở harness: {case['ground_truth_type']}) ===")
        for run_no in range(1, runs + 1):
            start = time.time()
            record = run_one(tc, fault=fault, timeout_ms=timeout_ms, perturb_oracle=perturb)
            wall = round(time.time() - start, 1)
            exec_res = record["execution_result"]

            # BLIND: analyzer chỉ thấy execution_result + tc, không thấy case_id/ground truth
            blind_tc = {
                "test_case_id": tc["test_case_id"],
                "function_id": tc.get("function_id", "FUNC-USER-ADD"),
            }
            analysis = FailureAnalyzer.analyze(exec_res, blind_tc)

            predictions.append({
                "run": run_no,
                "control_status": "PASS",
                "failure_type": analysis["failure_type"],
                "confidence": analysis["confidence"],
                "healable": analysis["healable"],
                "recommended_action": analysis["recommended_action"],
                "reason": analysis["reason"][:140],
                "exec_status": exec_res["status"],
                "wall_seconds": wall,
            })
            print(f"  run {run_no}: exec={exec_res['status']:<6} predicted={analysis['failure_type']:<20} wall={wall}s")
        results[case_id] = {
            "ground_truth_type": case["ground_truth_type"],
            "expected_action": case["expected_action"],
            "predictions": predictions,
        }

    # ------------------------------------------------------------------
    # Tổng hợp: accuracy + stability + confusion matrix + C06 contract
    # ------------------------------------------------------------------
    correct = 0
    stable = 0
    matrix_rows = []
    for case_id, data in results.items():
        types = [p["failure_type"] for p in data["predictions"]]
        all_correct = all(t == data["ground_truth_type"] for t in types)
        is_stable = len(set(types)) == 1
        correct += 1 if all_correct else 0
        stable += 1 if is_stable else 0
        for t in types:
            matrix_rows.append((data["ground_truth_type"], t))

    c06 = results.get("C06", {})
    c06_contract = all(
        p["failure_type"] == "APPLICATION_DEFECT"
        and p["healable"] is False
        and p["recommended_action"] == "STOP_SELF_HEALING"
        for p in c06.get("predictions", [])
    )

    taxonomies = FailureAnalyzer.TAXONOMIES
    counter = Counter(matrix_rows)
    print(f"\n{'=' * 62}\nCONFUSION MATRIX (expected x predicted, N={runs} runs/case)\n{'=' * 62}")
    header = f"{'expected \\ predicted':<22}" + "".join(f"{t[:12]:>14}" for t in taxonomies)
    print(header)
    for gt in taxonomies:
        row = f"{gt:<24}"
        for t in taxonomies:
            row += f"{counter.get((gt, t), 0):>14}"
        print(row)

    print(f"\nDev-set accuracy (case-level): {correct}/6")
    print(f"Stability (cùng kết quả {runs}/{runs} runs): {stable}/6")
    unknown_count = sum(1 for _, t in matrix_rows if t == "UNKNOWN")

    report = {
        "phase": "M3.1 dev-set benchmark",
        "runs_per_case": runs,
        "results": results,
        "accuracy_cases": f"{correct}/6",
        "stability": f"{stable}/6",
        "unknown_count": unknown_count,
        "c06_contract_ok": all(
            p["failure_type"] == "APPLICATION_DEFECT"
            and p["recommended_action"] == "STOP_SELF_HEALING"
            for p in c06.get("predictions", [])
        ),
        "confusion_matrix": {f"{gt}->{pred}": count for (gt, pred), count in counter.items()},
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")

    gate = correct == 6 and stable == 6 and unknown_count == 0 and report["c06_contract_ok"]
    print(f"\n{'DEV GATE: ' + ('DAT — FREEZE failure_analyzer.py ngay (eval Ngày 5 chạy 1 lần duy nhất)' if gate else 'CHUA DAT — calibrate roi chay lai')}")


if __name__ == "__main__":
    main()

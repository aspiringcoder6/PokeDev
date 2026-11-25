"""TestForge AI — M3.1 Day 5: EVAL-SET Classification Benchmark (BLIND, chạy 1 lần).

6 variants với CƠ CHẾ fault KHÁC dev set (analyzer đã FROZEN — không tune lại):
  C01E  LOCATOR   : label drift (label "Email" -> "Correo"), khác dev (testid drift)
  C02E  LOCATOR   : accessible name "Save" -> "Guardar", khác dev ("Lưu")
  C03E  TIMING    : delayed visibility 2500ms (khác dev 1500ms), wait policy 600ms
  C04E  ASSERTION : oracle sai đặt TRỰC TIẾP trong controlled TC (không qua env perturb)
  C05E  TEST_DATA : invalid credentials — data lỗi nằm trong chính test data (không seed server)
  C06E  APP DEFECT: HTTP 503 (khác dev 500)

QUY TẮC: eval chạy ĐÚNG 1 LẦN sau khi freeze — không tune rule sau khi nhìn kết quả.
Output: artifacts/experiments/classification_report_eval.json
"""

import argparse
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_failure_fixtures import run_one
from src.agent1.analyzer.failure_analyzer import FailureAnalyzer

REPORT_PATH = Path("artifacts/experiments/classification_report_eval.json")

# Ground truth thuộc TẦNG HARNESS
EVAL_CASES = {
    "C01E": {
        "ground_truth_type": "LOCATOR",
        "expected_action": "HEAL",
        "fault": "C01E",
        "test_case": {
            "test_case_id": "TC-C01E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Email", "value": "eval-c01@test.com", "timeout_ms": 3000},
                {"order": 3, "action": "FILL", "target": "Name", "value": "Eval One"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C02E": {
        "ground_truth_type": "LOCATOR",
        "expected_action": "HEAL",
        "fault": "C02E",
        "test_case": {
            "test_case_id": "TC-C02E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Eval Two"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "eval-c02@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C03E": {
        "ground_truth_type": "TIMING",
        "expected_action": "RETRY",
        "fault": "C03E",
        "test_case": {
            "test_case_id": "TC-C03E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Eval Three"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "eval-c03@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 600},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C04E": {
        "ground_truth_type": "ASSERTION",
        "expected_action": "REVIEW",
        "fault": None,
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C04E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Eval Four"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "eval-c04@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            # Oracle sai đặt TRỰC TIẾP trong controlled TC (mechanism khác dev perturb env)
            "expected_results": ["User is deleted successfully"],
        },
    },
    "C05E": {
        "ground_truth_type": "TEST_DATA",
        "expected_action": "DATA_ISSUE",
        "fault": None,
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C05E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Login", "value": "hacker@evil.com"},
                {"order": 3, "action": "FILL", "target": "Passcode", "value": "wrng"},
                {"order": 4, "action": "CLICK", "target": "Login", "timeout_ms": 3000},
            ],
            "expected_results": ["Logged in as admin"],
        },
    },
    "C06E": {
        "ground_truth_type": "APPLICATION_DEFECT",
        "expected_action": "STOP",
        "fault": "C06E",
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C06E-001",
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Eval Six"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "eval-c06@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
}


def main() -> None:
    runs = 3
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])

    results = {}
    for case_id, case in EVAL_CASES.items():
        tc = case["test_case"]
        predictions = []
        print(f"\n=== EVAL {case_id} (harness-only ground truth: {case['ground_truth_type']}) ===")
        for run_no in range(1, runs + 1):
            start = time.time()
            record = run_one(
                tc, fault=case.get("fault"),
                timeout_ms=case.get("timeout_ms"), perturb_oracle=False,
            )
            wall = round(time.time() - start, 1)
            exec_res = record["execution_result"]
            blind_tc = {
                "test_case_id": tc["test_case_id"],
                "function_id": tc.get("function_id", "FUNC-USER-ADD"),
            }
            analysis = FailureAnalyzer.analyze(exec_res, blind_tc)
            predictions.append({
                "run": run_no,
                "failure_type": analysis["failure_type"],
                "confidence": analysis["confidence"],
                "healable": analysis["healable"],
                "recommended_action": analysis["recommended_action"],
                "reason": analysis["reason"][:160],
                "exec_status": exec_res["status"],
                "wall_seconds": wall,
            })
            print(f"  run {run_no}: exec={exec_res['status']:<6} predicted={analysis['failure_type']:<20} wall={wall}s")
        results[case_id] = {
            "ground_truth_type": case["ground_truth_type"],
            "expected_action": case["expected_action"],
            "predictions": predictions,
        }

    correct = 0
    stable = 0
    matrix_rows = []
    for case_id, data in results.items():
        types = [p["failure_type"] for p in data["predictions"]]
        correct += 1 if all(t == data["ground_truth_type"] for t in types) else 0
        stable += 1 if len(set(types)) == 1 else 0
        for t in types:
            matrix_rows.append((data["ground_truth_type"], t))

    counter = Counter(matrix_rows)
    taxonomies = FailureAnalyzer.TAXONOMIES
    print(f"\n{'=' * 62}\nEVAL CONFUSION MATRIX (expected x predicted, N={runs} runs/case)\n{'=' * 62}")
    print(f"{'expected \\ predicted':<22}" + "".join(f"{t[:12]:>14}" for t in taxonomies))
    for gt in taxonomies:
        row = f"{gt:<24}"
        for t in taxonomies:
            row += f"{counter.get((gt, t), 0):>14}"
        print(row)

    c06e = results.get("C06E", {}).get("predictions", [])
    report = {
        "phase": "M3.1 eval-set benchmark (single pass, analyzer FROZEN)",
        "runs_per_case": runs,
        "results": results,
        "accuracy_cases": f"{correct}/6",
        "stability": f"{stable}/6",
        "unknown_count": sum(1 for _, t in matrix_rows if t == "UNKNOWN"),
        "confusion_matrix": {f"{gt}->{pred}": count for (gt, pred), count in counter.items()},
        "c06e_contract_ok": all(
            p["failure_type"] == "APPLICATION_DEFECT"
            and p["recommended_action"] == "STOP_SELF_HEALING"
            for p in c06e
        ),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")
    print(f"EVAL ACCURACY: {correct}/6 (controlled-fixture accuracy — không claim generalization)")


if __name__ == "__main__":
    main()

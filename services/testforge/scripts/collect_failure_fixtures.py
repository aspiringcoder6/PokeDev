"""TestForge AI — M3.1 Ngày 2: thu fixtures lỗi THẬT cho C01-C03.

Với mỗi case chạy 2 lượt qua pipeline rút gọn (generate -> static -> execute -> verify):
  - control  : không fault (kỳ vọng PASS)
  - faulted  : fault active (kỳ vọng FAIL đúng ground truth)

Fixture lưu artifacts/experiments/fixtures/{case_id}.json. Ground truth CHỈ nằm
ở tầng harness (file này) — analyzer không được thấy case_id/ground truth.
KHÔNG chạy FailureAnalyzer ở bước thu thập (calibration ở Ngày 4).
"""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent1.generator.playwright_generator import PlaywrightGenerator
from src.agent1.generator.static_validator import StaticValidator
from src.agent1.generator.artifact_store import ArtifactStore
from src.agent1.executor.runner import PlaywrightExecutor
from scripts.fault_control import set_active_fault, clear_active_fault, reset_demo_store

FIXTURES_DIR = Path("artifacts/experiments/fixtures")
ARTIFACTS_DIR = "artifacts/automation"

BASE_TC = {
    "function_id": "FUNC-USER-ADD",
    "feature": "Add User",
    "type": "POSITIVE",
    "priority": "CRITICAL",
    "preconditions": [],
    "verification_strategy": {"ui": True},
}

# Ground truth thuộc TẦNG HARNESS — không truyền xuống analyzer
CASES = {
    "C01": {
        "ground_truth_type": "LOCATOR",
        "expected_action": "HEAL",
        "fault": "C01",
        "test_case": {
            "test_case_id": "TC-C01-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van A"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "c01@test.com"},
                {"order": 4, "action": "CLICK", "target": "data-testid=save-user", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C02": {
        "ground_truth_type": "LOCATOR",
        "expected_action": "HEAL",
        "fault": "C02",
        "test_case": {
            "test_case_id": "TC-C02-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van B"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "c02@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C03": {
        "ground_truth_type": "TIMING",
        "expected_action": "RETRY",
        "fault": "C03",
        "test_case": {
            "test_case_id": "TC-C03-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van C"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "c03@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 500},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C04": {
        "ground_truth_type": "ASSERTION",
        "expected_action": "REVIEW",
        "fault": None,
        "perturb_oracle": True,
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C04-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van D"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "c04@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C05": {
        "ground_truth_type": "TEST_DATA",
        "expected_action": "DATA_ISSUE",
        "fault": "C05",
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C05-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van E"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "existing@example.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
    "C06": {
        "ground_truth_type": "APPLICATION_DEFECT",
        "expected_action": "STOP",
        "fault": "C06",
        "timeout_ms": 8000,
        "test_case": {
            "test_case_id": "TC-C06-DEV-001",
            "test_data": {},
            "steps": [
                {"order": 1, "action": "OPEN", "target": "/home-page"},
                {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van F"},
                {"order": 3, "action": "FILL", "target": "Email", "value": "c06@test.com"},
                {"order": 4, "action": "CLICK", "target": "Save", "timeout_ms": 3000},
            ],
            "expected_results": ["User is created successfully"],
        },
    },
}


def run_one(tc: dict, fault: str = None, timeout_ms: int = None, perturb_oracle: bool = False) -> dict:
    """Chạy 1 lượt generate -> static -> save -> execute thật. Trả về record.

    - fault: fault id active trong demo app (C05/C06...) hoặc None
    - timeout_ms: test timeout cho Playwright (control nhanh assertion timeout)
    - perturb_oracle: bật FAULT_ASSERTION_PERTURB (C04 — fault phía pipeline, không phải app)
    """
    import os
    if fault:
        set_active_fault(fault)
    else:
        clear_active_fault()
    if perturb_oracle:
        os.environ["FAULT_ASSERTION_PERTURB"] = "1"
    else:
        os.environ.pop("FAULT_ASSERTION_PERTURB", None)

    record = {"mode": "control" if fault is None and not perturb_oracle else "faulted"}
    try:
        reset_demo_store()  # test isolation: store standalone server có thể còn data cũ
        executor_kwargs = {}
        if timeout_ms:
            executor_kwargs["timeout_ms"] = timeout_ms
        script = PlaywrightGenerator.generate_script(tc)
        static_res = StaticValidator.validate(script, tc)
        if not static_res["valid"]:
            return {"mode": record["mode"], "static_validation": static_res}
        saved = ArtifactStore.save_script(tc, script, artifacts_dir=ARTIFACTS_DIR)
        executor = PlaywrightExecutor(**executor_kwargs)
        exec_res = executor.execute_script(
            tc["test_case_id"], script, script_path=saved["spec_path"], real_runtime=True
        )
        return {
            "mode": record["mode"],
            "execution_result": exec_res,
        }
    finally:
        clear_active_fault()
        os.environ.pop("FAULT_ASSERTION_PERTURB", None)


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    summary = []

    for case_id, case in CASES.items():
        tc = case["test_case"]
        fault = case.get("fault")
        perturb = case.get("perturb_oracle", False)
        timeout_ms = case.get("timeout_ms")
        print(f"\n=== {case_id} (ground truth: {case['ground_truth_type']}) ===")

        control = run_one(tc, fault=None, timeout_ms=timeout_ms)
        print(f"  control : {control['execution_result']['status']}")

        faulted = run_one(tc, fault=case.get("fault"), timeout_ms=timeout_ms, perturb_oracle=perturb)
        exec_res = faulted["execution_result"]
        print(f"  faulted : {exec_res['status']}")
        print(f"    error : {str(exec_res.get('error'))[:140]}")
        print(f"    net   : {json.dumps(exec_res.get('network_events', [])[:3])}")
        print(f"    ui    : {json.dumps(exec_res.get('ui_evidence', {}).get('visible_messages', []), ensure_ascii=False)}")

        fixture = {
            "case_id": case_id,
            "ground_truth_type": case["ground_truth_type"],
            "expected_action": case["expected_action"],
            "control": control,
            "faulted": faulted,
        }
        out = FIXTURES_DIR / f"{case_id.lower()}_dev.json"
        out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved   : {out}")

        summary.append((case_id, control["execution_result"]["status"], faulted["execution_result"]["status"]))

    print(f"\n{'=' * 60}\nFIXTURE COLLECTION SUMMARY\n{'=' * 60}")
    for case_id, ctl, flt in summary:
        ok = ctl == "PASS" and flt in ("FAIL", "ERROR")
        print(f"  {case_id}: control={ctl:<6} faulted={flt:<6} {'OK' if ok else '!! KIEM TRA'}")


if __name__ == "__main__":
    summary = []
    main()

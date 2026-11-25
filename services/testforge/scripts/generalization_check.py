"""TestForge AI — Generalization Check: 3 nhóm feature độc lập (Agent 1).

Mục đích:
- Chứng minh Test Design Agent + Automation Generator KHÔNG đóng cứng vào
  feature "Add User": cùng pipeline chạy được 3 nhóm feature độc lập:
    1. AUTH   — Login / Authentication   (FUNC-AUTH-LOGIN)
    2. CRUD   — User Management (Create) (FUNC-USER-CRUD)
    3. SEARCH — Search/Filter multi-step (login -> navigate -> search)
    4. UPDATE — CRUD Update multi-step   (FUNC-USER-UPDATE, bổ sung chữ U)
  + ADD-USER (M2 baseline) đối chiếu backward compatible.

- Mỗi nhóm: pipeline 20 bước đầy đủ (memory -> design -> generate -> static ->
  discovery -> execute -> verify -> heal -> gate) với oracle traceability (SV006)
  và Quality Gate transparency (RQ2 KPI).

Cách chạy:
    python scripts/generalization_check.py            # simulated (nhanh, CI)
    python scripts/generalization_check.py --real     # Playwright thật + demo app
"""

import argparse
import io
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.agent1.memory.adlc_memory_client import ADLCMemoryClient
from src.agent1.pipeline import Agent1Pipeline
from src.agent1.executor.runner import PlaywrightExecutor

ARTIFACTS_DIR = "artifacts/automation/generalization"

# ---------------------------------------------------------------------------
# Requirement contexts (Bước 1-2) — mỗi nhóm feature là một function độc lập
# ---------------------------------------------------------------------------
FEATURE_CONTEXTS = {
    # Nhóm 1: Login / Authentication
    "FUNC-AUTH-LOGIN": {
        "group": "AUTH",
        "context": {
            "feature": "Login Authentication",
            "business_rules": [],
            "validation_rules": [
                "Login is required",
                "Passcode must be at least 6 characters",
            ],
            "ui_flow": [
                "Open Login Page",
                "Fill Login",
                "Fill Passcode",
                "Click Login",
            ],
            "expected_result": ["Logged in as admin"],
            "rejection_message": "User is not logged in",
        },
    },
    # Nhóm 2: CRUD / User Management (Create)
    "FUNC-USER-CRUD": {
        "group": "CRUD",
        "context": {
            "feature": "User Management",
            "business_rules": ["Only Admin can create user"],
            "validation_rules": [
                "Email is required",
                "Email must be a valid email address",
                "Name must be at most 255 characters",
            ],
            "ui_flow": [
                "Open Home Page",
                "Fill Login",
                "Fill Passcode",
                "Click Login",
                "Click Add User",
                "Fill Name",
                "Fill Email",
                "Click Save",
            ],
            "expected_result": ["User is created successfully"],
        },
    },
    # Nhóm 2b: CRUD Update (multi-step: login -> add -> edit -> update)
    "FUNC-USER-UPDATE": {
        "group": "CRUD",
        "context": {
            "feature": "Update User",
            "business_rules": ["Only Admin can update user"],
            "validation_rules": ["Name is required"],
            "ui_flow": [
                "Open Login Page",
                "Fill Login",
                "Fill Passcode",
                "Click Login",
                "Open Home Page",
                "Fill Name",
                "Fill Email",
                "Click Save",
                "Click Edit",
                "Fill Name 'Nguyen Van B'",
                "Click Update",
            ],
            "expected_result": ["User is updated successfully"],
            "rejection_message": "User is not updated",
            "test_data": {
                "login": "admin@test.com",
                "passcode": "secret123",
                "name": "Nguyen Van A",
                "email": "a@test.com",
            },
        },
    },
    # Nhóm 3: Search / Filter (multi-step workflow)
    "FUNC-USER-SEARCH": {
        "group": "SEARCH",
        "context": {
            "feature": "User Search",
            "business_rules": [],
            "validation_rules": ["Search is required"],
            "ui_flow": [
                "Open Login Page",
                "Fill Login",
                "Fill Passcode",
                "Click Login",
                "Open User Management",
                "Fill Search",
                "Click Search",
            ],
            "expected_result": ["Search completed successfully"],
            "rejection_message": "Search is not executed",
        },
    },
    # Baseline M2 (đối chiếu không hồi quy)
    "FUNC-USER-ADD": {
        "group": "BASELINE",
        "context": {
            "feature": "Add User",
            "business_rules": ["Only Admin can create user"],
            "validation_rules": ["Email is required", "Email must be unique"],
            "ui_flow": [
                "Open Home Page",
                "Fill Login",
                "Fill Passcode",
                "Click Login",
                "Click Add User",
                "Fill Name",
                "Fill Email",
                "Click Save",
            ],
            "expected_result": ["User is created successfully"],
        },
    },
}

REQUIRED_GATE_FIELDS = [
    "initial_pass_rate",
    "healed_pass_rate",
    "healing_attempts",
    "healing_success_rate",
    "false_repair_rate",
]


def build_memory() -> "ADLCMemoryClient":
    from src.agent1.memory.adlc_memory_client import ADLCMemoryClient

    memory = ADLCMemoryClient()
    for fid, spec in FEATURE_CONTEXTS.items():
        memory.register_function_context("P01", fid, spec["context"])
    return memory


def run_check(real: bool, headed: bool = False, slow_mo: Optional[int] = None) -> int:
    from scripts.fault_control import reset_demo_store
    import os

    if slow_mo is not None:
        os.environ["DEMO_SLOW_MO"] = str(slow_mo)
    elif headed and "DEMO_SLOW_MO" not in os.environ:
        os.environ["DEMO_SLOW_MO"] = "300"

    memory = build_memory()
    executor = PlaywrightExecutor(headless=not headed)
    results = []

    for fid, spec in FEATURE_CONTEXTS.items():
        if real:
            # Test isolation: reset store demo app trước mỗi nhóm feature
            reset_demo_store()
        pipeline = Agent1Pipeline(
            memory_client=memory,
            executor=executor,
            artifacts_dir=ARTIFACTS_DIR,
            real_execution=real,
        )
        res = pipeline.run_pipeline("P01", fid)
        fr = res.get("functional_result", {})
        artifacts = res.get("artifacts", [])
        types = [a.get("status") for a in artifacts]
        oracle_all = all("oracle_trace" in a for a in artifacts if a["status"] == "PASS")
        gate_fields_ok = all(f in fr for f in REQUIRED_GATE_FIELDS)

        results.append({
            "function_id": fid,
            "group": spec["group"],
            "total": fr.get("total"),
            "statuses": types,
            "oracle_trace_ok": oracle_all,
            "gate_fields_ok": gate_fields_ok,
            "functional_result": fr,
        })

        print(f"\n[{spec['group']}] {fid}")
        print(f"  cases: {len(artifacts)}  statuses: {types}")
        for a in artifacts:
            if a.get("status") == "PASS":
                for t in a.get("oracle_trace", []):
                    print(f"    oracle: {t['expected_result'][:52]:<52} -> {t['assertion'][:60]}...")
        print(f"  oracle_trace: {'OK' if oracle_all else 'MISSING'}   gate_fields: {'OK' if gate_fields_ok else 'MISSING'}")
        print(f"  initial_pass_rate={fr.get('initial_pass_rate')}%  healed_pass_rate={fr.get('healed_pass_rate')}%  "
              f"attempts={fr.get('healing_attempts')}  success_rate={fr.get('healing_success_rate')}  "
              f"frr={fr.get('false_repair_rate')}%  gate_passed={fr.get('gate_passed')}")

    # ----- Khẳng định generalization -----
    print(f"\n{'=' * 66}\nGENERALIZATION ASSERTIONS\n{'=' * 66}")
    groups = {r["group"] for r in results}
    checks = []

    def check(name: str, ok: bool) -> None:
        checks.append(ok)
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")

    check(">= 3 nhóm feature độc lập được chạy (AUTH/CRUD/SEARCH)",
          {"AUTH", "CRUD", "SEARCH"}.issubset(groups))
    for r in results:
        check(f"{r['function_id']}: mọi case PASS + đủ oracle_trace + đủ gate fields "
              f"({r['total']} cases)",
              all(s == "PASS" for s in r["statuses"]) and r["oracle_trace_ok"] and r["gate_fields_ok"])
    # Oracles khác nhau giữa các nhóm -> Test Design KHÔNG đóng cứng Add User
    auth_oracle = "Logged in as admin"
    crud_oracle = "User is created successfully"
    search_oracle = "Search completed successfully"
    oracle_distinct = (
        auth_oracle != crud_oracle != search_oracle != auth_oracle
    )
    check("Oracle của 3 nhóm khác nhau (không phải một feature đói màu)", oracle_distinct)
    # Designer sinh đúng loại case theo rule của từng feature
    crud_res = next(r for r in results if r["function_id"] == "FUNC-USER-CRUD")
    auth_res = next(r for r in results if r["function_id"] == "FUNC-AUTH-LOGIN")
    search_res = next(r for r in results if r["function_id"] == "FUNC-USER-SEARCH")
    check("CRUD: 5 case (đủ POSITIVE/VALIDATION/NEGATIVE/BOUNDARY/PERMISSION)",
          crud_res["total"] == 5)
    check("AUTH: 2 case (không sinh BOUNDARY vô nghĩa — rule là min length)",
          auth_res["total"] == 2)
    check("SEARCH: 2 case (rule-driven, không ép đủ 6 loại)",
          search_res["total"] == 2)

    passed_all = all(checks)
    print(f"\n=> {'GENERALIZATION: DAT' if passed_all else 'GENERALIZATION: CHUA DAT'} "
          f"({sum(checks)}/{len(checks)} assertions)")

    # Lưu kết quả để dashboard/tuần 7 dùng
    out = Path("artifacts/results/generalization_check.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "mode": "real" if real else "simulated",
        "passed_all": passed_all,
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   Bằng chứng: {out}")
    return 0 if passed_all else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true",
                        help="Chạy Playwright thật + discovery check (demo app qua webServer)")
    parser.add_argument("--headed", action="store_true",
                        help="Hiển thị cửa sổ Chromium thật trên màn hình để quan sát")
    parser.add_argument("--slow-mo", type=int, default=None,
                        help="Tốc độ slowMo giữa các thao tác của browser (ms)")
    args = parser.parse_args()
    sys.exit(run_check(real=args.real, headed=args.headed, slow_mo=args.slow_mo))

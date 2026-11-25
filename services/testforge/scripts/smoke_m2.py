"""TestForge AI — Smoke test M2: Requirement -> Test Cases -> Playwright Script -> Execute THAT -> Verification.

Chạy pipeline với real runtime (Playwright + Chromium) chống demo app N=3 lần
theo DoD của M2: ">= 2 flows end-to-end chạy ổn định".

Cách chạy:
    python scripts/smoke_m2.py            # 1 lượt
    python scripts/smoke_m2.py --runs 3   # N=3 lượt (DoD)
"""

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scripts.fault_control import reset_demo_store
from src.agent1.pipeline import Agent1Pipeline
from src.agent1.memory.adlc_memory_client import ADLCMemoryClient
from src.agent1.executor.runner import PlaywrightExecutor

ARTIFACTS_DIR = "artifacts/automation"

MEMORY_CONTEXT = {
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
}


def build_pipeline(headless: bool = True) -> Agent1Pipeline:
    memory = ADLCMemoryClient()
    memory.register_function_context(
        project_id="P01",
        function_id="FUNC-USER-ADD",
        context=MEMORY_CONTEXT,
    )
    executor = PlaywrightExecutor(headless=headless)
    return Agent1Pipeline(
        memory_client=memory,
        executor=executor,
        artifacts_dir=ARTIFACTS_DIR,
        real_execution=True,
    )


def main() -> None:
    runs = 1
    if "--runs" in sys.argv:
        runs = int(sys.argv[sys.argv.index("--runs") + 1])
    headed = "--headed" in sys.argv

    results = []
    for run_no in range(1, runs + 1):
        reset_demo_store()
        print(f"\n{'=' * 60}\nRUN {run_no}/{runs}\n{'=' * 60}")
        start = time.time()
        pipeline = build_pipeline(headless=not headed)

        def on_case_complete(art: dict) -> None:
            """Stream từng dòng TC ngay khi xử lý xong."""
            status = art.get("status")
            tc = art.get("test_case_id")
            extra = ""
            if "static_validation" in art:
                extra = f" | static: {art['static_validation']['errors'][0]['code']}"
            elif art.get("defect"):
                extra = f" | defect: {art['defect']['defect_id']}"
            elif art.get("proposal_source"):
                extra = f" | healed by {art.get('proposal_source')}"
            print(f"  {tc:<30} {status}{extra}", flush=True)

        result = pipeline.run_pipeline(
            project_id="P01", function_id="FUNC-USER-ADD",
            on_case_complete=on_case_complete,
        )
        wall_seconds = round(time.time() - start, 1)

        func_res = result.get("functional_result", {})
        defect_count = len(result.get("defect_reports", []))
        print(f"  {'-' * 58}")
        print(f"  TOTAL: {func_res.get('total')}   PASSED: {func_res.get('passed')}   FAILED: {func_res.get('failed')}")
        print(f"  HEALING: attempted={func_res.get('healing', {}).get('attempted')} successful={func_res.get('healing', {}).get('successful')}")
        print(f"  DEFECTS: {defect_count}")
        gate = f"OPEN -> {func_res.get('recommended_next_stage')}" if func_res.get("gate_passed") else "BLOCK"
        print(f"  STATUS: {func_res.get('status')}   GATE: {gate}   wall={wall_seconds}s")

        results.append({
            "run": run_no,
            "wall_seconds": wall_seconds,
            "status": func_res.get("status"),
            "gate_passed": func_res.get("gate_passed"),
            "healing": func_res.get("healing"),
        })

    print(f"\n{'=' * 60}\nM2 SMOKE SUMMARY (N={runs})\n{'=' * 60}")
    for r in results:
        print(f"  run {r['run']}: {r['status']:<12} gate={r['gate_passed']} wall={r['wall_seconds']}s")
    stable = all(r["status"] == "PASS" and r["gate_passed"] for r in results)
    print(f"  => {'STABLE - M2 DoD DAT' if stable else 'KHONG ON DINH - can kiem tra lai'}")
    return 0 if stable else 1


if __name__ == "__main__":
    sys.exit(main())

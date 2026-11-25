"""TestForge AI — M3.2 Day 2: Healing Benchmark trên 6 controlled cases.

Hai backend thực thi, cùng một healing graph:
  --backend local    (mặc định): Playwright local + fault qua demo_app/faults.json local
  --backend sandbox: Playwright chạy TRONG sandbox-kit container
                     (fault inject bằng cách ghi faults.json vào container;
                      spec push qua runWriteFile; evidence qua runReadFile)

Quy tắc xuyên suốt: fault VẪN ACTIVE khi retest — healing phải vượt qua fault,
không được tắt fault. C06: healer invocation phải = 0.
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_failure_fixtures import CASES as DEV_CASES
from scripts.fault_control import set_active_fault, clear_active_fault, reset_demo_store
from src.agent1.generator.playwright_generator import PlaywrightGenerator
from src.agent1.generator.static_validator import StaticValidator
from src.agent1.generator.artifact_store import ArtifactStore
from src.agent1.executor.runner import PlaywrightExecutor
from src.agent1.healer.graph import run_healing
from src.agent1.healer.state import OUTCOME_HEALED_PASS, OUTCOME_STOP_DEFECT

REPORT_PATH = Path("artifacts/experiments/healing_report_day2.json")
ARTIFACTS_DIR = "artifacts/automation"

EXPECTED_OUTCOMES = {
    "C01": OUTCOME_HEALED_PASS,
    "C02": OUTCOME_HEALED_PASS,
    "C03": OUTCOME_HEALED_PASS,
    "C04": "NOT_HEALABLE",
    "C05": "NOT_HEALABLE",
    "C06": OUTCOME_STOP_DEFECT,
}

SANDBOX_CONFIG_TS = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:8931',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  outputDir: './test-results',
  webServer: {
    command: 'python3 demo_app/server.py',
    url: 'http://127.0.0.1:8931/',
    reuseExistingServer: true,
    timeout: 30000,
  },
});
"""


class LocalBackend:
    """Backend local: Playwright subprocess + fault qua file local."""

    name = "local"

    def __init__(self, timeout_ms=None, headless: bool = True):
        self.executor = PlaywrightExecutor(
            **({"timeout_ms": timeout_ms} if timeout_ms else {}),
            headless=headless,
        )

    def setup(self):
        pass

    def set_fault(self, fault: str):
        reset_demo_store()  # test isolation: store standalone server có thể còn data cũ
        if fault:
            set_active_fault(fault)
        else:
            clear_active_fault()

    def clear_all(self):
        clear_active_fault()

    def run_spec(self, tc: dict, script: str, suffix: str = "") -> dict:
        saved = ArtifactStore.save_script(
            {**tc, "test_case_id": tc["test_case_id"] + suffix},
            script, artifacts_dir=ARTIFACTS_DIR,
        )
        return self.executor.execute_script(
            tc["test_case_id"], script, script_path=saved["spec_path"], real_runtime=True
        )

    def teardown(self):
        self.clear_all()


class SandboxBackend:
    """Backend sandbox: Playwright trong container qua Broker (fault qua faults.json nội bộ)."""

    name = "sandbox"

    def __init__(self, timeout_ms=None, session_id=None):
        from src.agent1.executor.sandbox_runner import SandboxExecutor
        self.sb = SandboxExecutor(
            timeout_ms=timeout_ms or PlaywrightExecutor.DEFAULT_TIMEOUT_MS,
            session_id=session_id or f"testforge-heal-{int(time.time())}",
        )
        self._ready = False

    def setup(self):
        import time as _t
        self.sb.start_session()
        sb_root = Path(__file__).resolve().parents[1] / "demo_app"
        self.sb.write_file("/workspace/playwright.config.ts", SANDBOX_CONFIG_TS)
        self.sb.write_file("/workspace/demo_app/index.html", (sb_root / "index.html").read_text(encoding="utf-8"))
        self.sb.write_file("/workspace/demo_app/server.py", (sb_root / "server.py").read_text(encoding="utf-8"))
        self.sb.write_file("/workspace/demo_app/faults.json", json.dumps({"active_fault": None}))
        self.sb.write_file("/workspace/package.json", json.dumps(
            {"name": "testforge-heal", "version": "1.0.0", "private": True,
             "devDependencies": {"@playwright/test": "1.63.0"}}, indent=2))
        res = self.sb.shell("cd /workspace && npm install --no-audit --no-fund", timeout=240)
        if res.get("exitCode") != 0:
            raise RuntimeError(f"[sandbox] npm install failed: {str(res.get('stderr'))[:300]}")
        self._ready = True

    def set_fault(self, fault: str):
        self.sb.write_file(
            "/workspace/demo_app/faults.json",
            json.dumps({"active_fault": fault} if fault else {"active_fault": None}),
        )

    def clear_all(self):
        self.sb.write_file("/workspace/demo_app/faults.json", json.dumps({"active_fault": None}))

    def run_spec(self, tc: dict, script: str, suffix: str = "") -> dict:
        spec_path = f"/workspace/specs/{tc['test_case_id']}{suffix}.spec.ts"
        self.sb.write_file(spec_path, script)
        return self.sb.execute_script(tc["test_case_id"], script, script_path=spec_path, real_runtime=True)

    def teardown(self):
        self.sb.stop_session()


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["local", "sandbox"], default="local")
    parser.add_argument("--tier2", choices=["heuristic", "llm"], default="heuristic",
                        help="llm = Tier 2 dùng LLM (fallback heuristic); heuristic = ngày 2")
    parser.add_argument("--headed", action="store_true",
                        help="(local only) hiện browser thật + slow-mo để khán giả thấy hành động")
    parser.add_argument("--case", choices=["C01", "C02", "C03", "C04", "C05", "C06", "all"], default="all",
                        help="Chạy riêng 1 case để demo nhanh (mặc định all)")
    parser.add_argument("--hold-ms", type=int, default=None,
                        help="Thời gian dừng màn hình browser sau mỗi lần chạy để quan sát (ms)")
    parser.add_argument("--slow-mo", type=int, default=None,
                        help="Tốc độ slowMo giữa các thao tác của browser (ms)")
    args = parser.parse_args()

    import os
    if args.headed:
        if args.slow_mo is not None:
            os.environ["DEMO_SLOW_MO"] = str(args.slow_mo)
        elif "DEMO_SLOW_MO" not in os.environ:
            os.environ["DEMO_SLOW_MO"] = "300"

        if args.hold_ms is not None:
            os.environ["DEMO_HOLD_MS"] = str(args.hold_ms)
        elif "DEMO_HOLD_MS" not in os.environ:
            os.environ["DEMO_HOLD_MS"] = "2500"

        print(f"\n[DEMO MODE ACTIVATED]")
        print(f"  Browser   : Headed (Hiển thị Chromium trực quan)")
        print(f"  SlowMo    : {os.environ.get('DEMO_SLOW_MO')}ms / thao tác")
        print(f"  Hold View : {os.environ.get('DEMO_HOLD_MS')}ms kèm Banner kết quả trên màn hình\n")

    tier2_healer = None
    llm_note = "heuristic"
    if args.tier2 == "llm":
        from src.agent1.healer.llm_client import OpenCodeChatClient
        from src.agent1.healer.tier2_ai_recovery import Tier2AIRecovery
        client = OpenCodeChatClient()
        if not client.available():
            print("[warn] LLM chưa cấu hình (OPENCODE_API_KEY/opencode.json) -> dùng heuristic")
        else:
            tier2_healer = Tier2AIRecovery(llm_client=client)
            llm_note = f"LLM {client.model} @ {client.base_url}"

    if args.backend == "sandbox":
        if args.headed:
            print("[warn] --headed chỉ áp dụng backend local (container không có display) -> bỏ qua")
        backend = SandboxBackend()
    else:
        backend = LocalBackend(headless=not args.headed)
    report = {"phase": f"M3.2 Day 3 — healing benchmark (backend={backend.name}, tier2={llm_note})", "cases": {}}

    try:
        backend.setup()
        cases_to_run = ["C01", "C02", "C03", "C04", "C05", "C06"] if args.case == "all" else [args.case]
        for case_id in cases_to_run:
            case = DEV_CASES[case_id]
            tc = case["test_case"]
            fault = case.get("fault")
            perturb = case.get("perturb_oracle", False)
            timeout_ms = case.get("timeout_ms")

            print(f"\n=== {case_id} (GT: {case['ground_truth_type']}) [{backend.name}] ===")

            # 1. Fault active (C04: không server fault — perturb qua env) + run thật
            backend.set_fault(fault)
            if perturb:
                os.environ["FAULT_ASSERTION_PERTURB"] = "1"
            else:
                os.environ.pop("FAULT_ASSERTION_PERTURB", None)
            script = PlaywrightGenerator.generate_script(tc)
            os.environ.pop("FAULT_ASSERTION_PERTURB", None)

            exec_res = backend.run_spec(tc, script)
            print(f"  initial run : {exec_res['status']} | {str(exec_res.get('error'))[:90]}")

            # 2. Healing (fault vẫn active; retest chạy trên cùng backend)
            def retest_runner(t_id: str, repaired_script: str) -> dict:
                return backend.run_spec(tc, repaired_script, suffix="-RETEST")

            t0 = time.time()
            healing = run_healing(
                test_case=tc,
                execution_result=exec_res,
                script_code=script,
                retest_runner=retest_runner,
                tier2_healer=tier2_healer,
                max_retries=3,
            )
            wall = round(time.time() - t0, 1)
            outcome = healing["outcome"]

            heal_stages = [e["stage"] for e in healing["healing_events"]]
            healer_invocations = sum(1 for e in heal_stages if e in ("tier1", "tier2"))
            print(f"  outcome     : {outcome} (wall={wall}s, retests={healing['retest_count']}, tiers={heal_stages})")
            if healing.get("proposal"):
                print(f"  proposal    : {healing['proposal'].get('strategy')} -> {healing['proposal'].get('new_locator')}")

            report["cases"][case_id] = {
                "ground_truth_outcome": EXPECTED_OUTCOMES[case_id],
                "outcome": outcome,
                "retest_count": healing["retest_count"],
                "stages": heal_stages,
                "healer_invocations": healer_invocations,
                "proposal": healing.get("proposal"),
                "tried_locators": healing.get("tried_locators", []),
                "healing_events": healing["healing_events"],
                "failure_analysis": healing.get("failure_analysis", {}),
            }
            backend.clear_all()
    finally:
        backend.clear_all()
        backend.teardown()

    # Tổng hợp
    print(f"\n{'=' * 62}\nHEALING BENCHMARK — SUMMARY (backend={backend.name})\n{'=' * 62}")
    hits = 0
    for case_id, data in report["cases"].items():
        ok = data["outcome"] == data["ground_truth_outcome"]
        hits += 1 if ok else 0
        print(f"  {case_id}: {data['outcome']:<14} (GT: {data['ground_truth_outcome']:<14}) "
              f"retests={data['retest_count']} healer_inv={data['healer_invocations']} {'OK' if ok else '!! MISS'}")

    c06_ok = True
    if "C06" in report["cases"]:
        c06 = report["cases"]["C06"]
        c06_ok = c06["outcome"] == OUTCOME_STOP_DEFECT and c06["healer_invocations"] == 0
        print(f"  C06 STOP contract (healer_invocation == 0): {'OK' if c06_ok else 'FAIL'}")
    report["summary"] = {"backend": backend.name, "tier2": llm_note, "hits": hits, "total": len(report["cases"]), "c06_stop_contract": c06_ok}
    out_name = f"healing_report_day3_{backend.name}_{args.tier2}.json"
    (Path("artifacts/experiments") / out_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: artifacts/experiments/{out_name}")
    print(f"=> {'DAY 2 GATE DAT' if hits == len(report['cases']) and c06_ok else 'CHUA DAT — kiem tra'}")
    return 0 if hits == len(report['cases']) and c06_ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""TestForge AI — Gate: chạy 6 controlled fixtures M3.1 BÊN TRONG sandbox-kit.

Khác biệt so với chạy local: fault inject bằng cách GHI faults.json vào container
(server demo app chạy trong container đọc faults.json của nó), spec push qua
runWriteFile, Playwright chạy qua runShellCommand, evidence đọc qua runReadFile.

Gate: prediction == ground truth cho cả 6 case (analyzer FROZEN, blind).
"""

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scripts.collect_failure_fixtures import CASES as DEV_CASES
from scripts.fault_control import clear_active_fault  # reset local file cho chắc
from src.agent1.executor.sandbox_runner import SandboxExecutor
from src.agent1.analyzer.failure_analyzer import FailureAnalyzer
from src.agent1.generator.playwright_generator import PlaywrightGenerator

REPORT_PATH = Path("artifacts/experiments/classification_report_sandbox.json")
CONFIG_TS = """import { defineConfig } from '@playwright/test';

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


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    results = {}
    hits = 0

    with SandboxExecutor(timeout_ms=8000, session_id=f"testforge-classify-{int(__import__('time').time())}") as sb:
        # Setup 1 lần: npm + config + demo app (kèm faults.json mặc định null)
        sb.start_session()
        sb.write_file("/workspace/playwright.config.ts", CONFIG_TS)
        demo_dir = Path(__file__).resolve().parents[1] / "demo_app"
        sb.write_file("/workspace/demo_app/index.html", (demo_dir / "index.html").read_text(encoding="utf-8"))
        sb.write_file("/workspace/demo_app/server.py", (demo_dir / "server.py").read_text(encoding="utf-8"))
        sb.write_file("/workspace/demo_app/faults.json", json.dumps({"active_fault": None}))
        sb.write_file("/workspace/package.json", json.dumps(
            {"name": "testforge-sandbox", "version": "1.0.0", "private": True,
             "devDependencies": {"@playwright/test": "1.63.0"}}, indent=2))
        sb.shell("cd /workspace && npm install --no-audit --no-fund", timeout=240)

        for case_id in ["C01", "C02", "C03", "C04", "C05", "C06"]:
            case = DEV_CASES[case_id]
            tc = case["test_case"]
            fault = case.get("fault")
            perturb = case.get("perturb_oracle", False)

            # 1. Fault thật: ghi faults.json TRONG container
            sb.write_file("/workspace/demo_app/faults.json",
                          json.dumps({"active_fault": fault} if fault else {"active_fault": None}))

            # 2. Generate (env perturb cho C04) + push spec
            if perturb:
                os.environ["FAULT_ASSERTION_PERTURB"] = "1"
            else:
                os.environ.pop("FAULT_ASSERTION_PERTURB", None)
            script = PlaywrightGenerator.generate_script(tc)
            os.environ.pop("FAULT_ASSERTION_PERTURB", None)
            sb.write_file(f"/workspace/specs/{tc['test_case_id']}.spec.ts", script)

            # 3. Execute trong sandbox
            exec_res = sb.execute_script(
                tc["test_case_id"], script,
                script_path=f"/workspace/specs/{tc['test_case_id']}.spec.ts",
                real_runtime=True,
            )

            # 4. Analyzer BLIND + đối chiếu
            blind_tc = {"test_case_id": tc["test_case_id"], "function_id": tc.get("function_id", "FUNC-USER-ADD")}
            analysis = FailureAnalyzer.analyze(exec_res, blind_tc)
            hit = analysis["failure_type"] == case["ground_truth_type"]
            hits += 1 if hit else 0
            print(f"{case_id}: exec={exec_res['status']:<6} predicted={analysis['failure_type']:<20} "
                  f"{'HIT ' if hit else 'MISS'} (GT: {case['ground_truth_type']})")
            if not hit:
                print(f"   reason: {analysis['reason'][:150]}")
            results[case_id] = {
                "ground_truth_type": case["ground_truth_type"],
                "predicted": analysis["failure_type"],
                "recommended_action": analysis["recommended_action"],
                "exec_status": exec_res["status"],
                "hit": hit,
            }

            # reset fault
            sb.write_file("/workspace/demo_app/faults.json", json.dumps({"active_fault": None}))

    print(f"\n{'=' * 60}\nSANDBOX CLASSIFICATION GATE: {hits}/6")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {REPORT_PATH}")
    print(f"=> {'GATE DAT — analyzer chạy đúng trong sandbox' if hits == 6 else 'CHUA DAT'}")


if __name__ == "__main__":
    main()

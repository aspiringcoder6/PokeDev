"""TestForge AI — Gherkin In, Results Out (học từ TestZeus Hercules).

Tester viết Gherkin chuẩn ngành -> hệ thống tự:
    parse (Zero-LLM) -> đăng ký function context -> pipeline 20 bước
    -> JUnit XML + Proofs bundle + Functional Result / Quality Gate.

Cách chạy:
    python scripts/run_gherkin.py --input opt/gherkin/demo_app.feature            # simulated
    python scripts/run_gherkin.py --input opt/gherkin/demo_app.feature --real     # Playwright thật
"""

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.agent1.executor.runner import PlaywrightExecutor
from src.agent1.memory.adlc_memory_client import ADLCMemoryClient
from src.agent1.normalizer.gherkin_parser import GherkinParser
from src.agent1.pipeline import Agent1Pipeline

ARTIFACTS_DIR = "artifacts/automation/gherkin"


def run(feature_path: str, real: bool) -> int:
    from scripts.fault_control import reset_demo_store

    text = Path(feature_path).read_text(encoding="utf-8")
    scenarios = GherkinParser.parse(text)
    if not scenarios:
        print("KHONG tim thay scenario nao trong file Gherkin.")
        return 1

    print(f"Gherkin In: {feature_path}")
    print(f"  -> {len(scenarios)} scenario(s) sau parse/expand:")
    for sc in scenarios:
        print(f"    - {sc['function_id']}: {sc['scenario']}")

    memory = ADLCMemoryClient()
    for sc in scenarios:
        memory.register_function_context(
            project_id="P01",
            function_id=sc["function_id"],
            context=GherkinParser.to_function_context(sc),
        )

    executor = PlaywrightExecutor(headless=True)
    suites_xml = []
    results_summary = []

    for sc in scenarios:
        if real:
            # Test isolation (Hercules: mỗi scenario là unit-of-work độc lập)
            reset_demo_store()
        pipeline = Agent1Pipeline(
            memory_client=memory,
            executor=executor,
            artifacts_dir=ARTIFACTS_DIR,
            real_execution=real,
        )
        res = pipeline.run_pipeline("P01", sc["function_id"])
        fr = res.get("functional_result", {})
        artifacts = res.get("artifacts", [])
        reports = res.get("reports", {})

        from src.agent1.reporter.junit_reporter import JUnitReporter
        suites_xml.append(JUnitReporter.build_testsuite(fr, artifacts))

        results_summary.append({
            "scenario": sc["scenario"],
            "function_id": sc["function_id"],
            "status": fr.get("status"),
            "gate_passed": fr.get("gate_passed"),
            "initial_pass_rate": fr.get("initial_pass_rate"),
            "healed_pass_rate": fr.get("healed_pass_rate"),
            "junit": reports.get("junit_xml"),
            "proofs": reports.get("proofs_dir"),
        })

        print(f"\n[{sc['scenario']}]")
        print(f"  total={fr.get('total')} passed={fr.get('passed')} failed={fr.get('failed')}"
              f"  initial={fr.get('initial_pass_rate')}% healed={fr.get('healed_pass_rate')}%"
              f"  attempts={fr.get('healing_attempts')} frr={fr.get('false_repair_rate')}%")
        print(f"  gate={'OPEN -> ' + str(fr.get('recommended_next_stage')) if fr.get('gate_passed') else 'BLOCK'}")

    # Merge mọi suite vào 1 file XML (pattern per-scenario -> merge của Hercules)
    if suites_xml:
        merged_path = Path(ARTIFACTS_DIR) / "junit" / "gherkin_results.xml"
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        merged_path.write_text(
            JUnitReporter.build_xml_string(suites_xml, name="TestForge AI — Gherkin Run"),
            encoding="utf-8",
        )
        print(f"\nJUnit XML (merged): {merged_path}")
        print(f"Proofs: {Path(ARTIFACTS_DIR) / 'proofs'}")

    all_pass = all(r["gate_passed"] for r in results_summary)
    print(f"\n=> GHERKIN RUN: {'DAT — gate OPEN cho Agents kế tiếp' if all_pass else 'KHONG DAT — gate BLOCK'}")
    if any(r["status"] == "ERROR" for r in results_summary):
        return 2
    return 0 if all_pass or not real else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Đường dẫn file .feature")
    parser.add_argument("--real", action="store_true", help="Chạy Playwright thật + demo app")
    args = parser.parse_args()
    sys.exit(run(args.input, args.real))

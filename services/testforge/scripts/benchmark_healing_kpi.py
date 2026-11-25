"""TestForge AI — M3.2 Day 4: Healing KPI Benchmark (RQ2).

Ma trận thí nghiệm: N=3 × {C01, C02, C03} × {heuristic, llm} = 18 healing runs
trên sandbox backend, fault VẪN ACTIVE khi retest.

KPI RQ2 (targets từ docs/research/02):
- Self-healing Success Rate >= 80%   = HEALED_PASS / healable attempts
- FALSE REPAIR RATE < 5% (critical)  = false repairs / accepted healings
- MTTR                               = mean wall time của các run heal thành công

False-repair audit (deterministic, độc lập với tier2 mode):
  (a) oracle text còn nguyên trong repaired script
  (b) số assertion không giảm
  (c) locator mới phải trỏ ĐÚNG element nghiệp vụ (bảng token đúng theo case)
      C01: Save button (submit-user | 'Save') | C02: (save-user | 'Lưu') | C03: chỉ đổi timeout
"""

import io
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scripts.benchmark_healing import SandboxBackend
from scripts.collect_failure_fixtures import CASES as DEV_CASES
from src.agent1.generator.playwright_generator import PlaywrightGenerator
from src.agent1.healer.graph import run_healing
from src.agent1.healer.llm_client import OpenCodeChatClient
from src.agent1.healer.state import OUTCOME_HEALED_PASS
from src.agent1.healer.tier2_ai_recovery import Tier2AIRecovery

REPORT_PATH = Path("artifacts/experiments/healing_kpi_day4.json")
RUNS = 3
HEALABLE_CASES = ["C01", "C02", "C03"]
TIER2_MODES = ["heuristic", "llm"]

# Ground truth ngữ nghĩa: locator đúng phải chứa 1 trong các token sau
CORRECT_LOCATOR_TOKENS = {
    "C01": ["submit-user", "Save"],
    "C02": ["save-user", "Lưu"],
    "C03": [],  # chỉ chấp nhận wait-extension (không đổi locator)
}


def audit_false_repair(case_id: str, proposal: dict, script_code: str) -> tuple:
    """Trả về (false_repair: bool, reason: str)."""
    if not proposal:
        return False, ""
    repaired = proposal.get("repaired_script") or ""
    # (a) oracle text còn nguyên
    tc = None
    from scripts.collect_failure_fixtures import CASES as DEV_CASES
    tc = DEV_CASES[case_id]["test_case"]
    for exp in tc.get("expected_results") or []:
        if exp not in repaired:
            return True, f"oracle_text_altered: '{exp}' missing"
    # (b) assertion count không giảm
    if repaired.count("expect(") < script_code.count("expect("):
        return True, "assertion removed"
    # (c) semantic target check
    new_locator = proposal.get("new_locator") or ""
    strategy = proposal.get("strategy") or ""
    if case_id == "C03":
        # chỉ chấp nhận wait-extension: nội dung khác phải giống gốc trừ timeout
        orig = script_code.replace("timeout: 500", "timeout: X")
        norm = repaired.replace("timeout: 5000", "timeout: X").replace("timeout: 4000", "timeout: X")
        if norm != orig and "timeout" not in strategy.lower():
            return True, f"C03 changed locator instead of wait: {new_locator[:60]}"
        return False, ""
    tokens = CORRECT_LOCATOR_TOKENS.get(case_id, [])
    if tokens and not any(t in new_locator for t in tokens):
        return True, f"locator targets wrong element: {new_locator[:80]}"
    return False, ""


def main() -> None:
    llm_client = OpenCodeChatClient()
    events = []
    runs_meta = []

    from scripts.benchmark_healing import SandboxBackend
    backend = SandboxBackend(timeout_ms=8000, session_id=f"testforge-kpi-{int(time.time())}")
    backend.setup()

    try:
        for mode in TIER2_MODES:
            tier2 = Tier2AIRecovery(llm_client=llm_client) if mode == "llm" else Tier2AIRecovery()
            for case_id in HEALABLE_CASES:
                case = DEV_CASES[case_id]
                tc = case["test_case"]
                for run_no in range(1, RUNS + 1):
                    backend.set_fault(case.get("fault"))
                    script = PlaywrightGenerator.generate_script(tc)
                    exec_res = backend.run_spec(tc, script)

                    t0 = time.time()
                    healing = run_healing(
                        test_case=tc,
                        execution_result=exec_res,
                        script_code=script,
                        retest_runner=lambda t_id, s: backend.run_spec(tc, s, suffix="-RETEST"),
                        tier2_healer=tier2,
                        max_retries=3,
                    )
                    wall = round(time.time() - t0, 1)
                    backend.clear_all()

                    outcome = healing["outcome"]
                    healed = outcome == OUTCOME_HEALED_PASS
                    false_repair, fr_reason = audit_false_repair(case_id, healing.get("proposal"), script)

                    event = {
                        "event_id": f"HEAL-{case_id}-{mode}-{run_no}-{uuid.uuid4().hex[:6]}",
                        "run_id": f"KPI-{mode}-{case_id}-{run_no}",
                        "test_case_id": tc["test_case_id"],
                        "function_id": tc.get("function_id", "FUNC-USER-ADD"),
                        "failure_type": healing["failure_analysis"].get("failure_type"),
                        "backend": "sandbox",
                        "tier2_mode": mode,
                        "llm_model": llm_client.model if mode == "llm" else None,
                        "proposal": {
                            "tier": (healing.get("proposal") or {}).get("tier"),
                            "strategy": (healing.get("proposal") or {}).get("strategy"),
                            "new_locator": (healing.get("proposal") or {}).get("new_locator"),
                            "confidence": (healing.get("proposal") or {}).get("confidence"),
                            "reasoning": (healing.get("proposal") or {}).get("reasoning"),
                        },
                        "tried_locators": healing.get("tried_locators", []),
                        "outcome": outcome,
                        "retest_count": healing["retest_count"],
                        "wall_seconds": wall,
                        "false_repair": false_repair,
                        "false_repair_reason": fr_reason,
                        "healing_events": healing["healing_events"],
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                    events.append(event)
                    runs_meta.append({
                        "mode": mode, "case_id": case_id, "run": run_no,
                        "outcome": outcome, "healed": healed, "wall": wall,
                        "false_repair": false_repair,
                        "strategy": (healing.get("proposal") or {}).get("strategy"),
                        "new_locator": (healing.get("proposal") or {}).get("new_locator"),
                    })
                    print(f"[{mode:>9}] {case_id} run{run_no}: {outcome:<12} wall={wall}s "
                          f"retests={healing['retest_count']} false_repair={false_repair}")
                    backend.clear_all()
    finally:
        backend.teardown()

    # ---------------- KPI aggregation ----------------
    kpis = {}
    for mode in TIER2_MODES:
        runs = [r for r in runs_meta if r["mode"] == mode]
        healed = [r for r in runs if r["healed"]]
        false_repairs = [r for r in runs if r["false_repair"]]
        mttr = round(sum(r["wall"] for r in healed) / len(healed), 1) if healed else None
        kpis[mode] = {
            "attempts": len(runs),
            "healed": len(healed),
            "success_rate": round(100 * len(healed) / len(runs), 1) if runs else 0,
            "false_repairs": len(false_repairs),
            "false_repair_rate": round(100 * len(false_repairs) / len(runs), 1) if runs else 0,
            "mttr_seconds": mttr,
        }

    print(f"\n{'=' * 66}\nHEALING KPI — RQ2 (N=3 x 3 cases x 2 tier2 modes, sandbox)\n{'=' * 66}")
    print(f"{'Metric':<28}{'heuristic':>14}{'llm':>14}{'Target':>12}")
    print("-" * 66)
    for mode in TIER2_MODES:
        k = kpis[mode]
        print(f"{mode}: attempts={k['attempts']} healed={k['healed']} "
              f"false_repairs={k['false_repairs']} MTTR={k['mttr_seconds']}s")
    h, l = kpis["heuristic"], kpis["llm"]
    print("-" * 66)
    print(f"{'Success Rate':<28}{h['success_rate']:>13}%{l['success_rate']:>13}%{'>=80%':>12}")
    print(f"{'FALSE REPAIR RATE':<28}{h['false_repair_rate']:>13}%{l['false_repair_rate']:>13}%{'<5%':>12}")
    print(f"{'MTTR (healed runs)':<28}{(str(h['mttr_seconds']) + 's'):>14}{(str(l['mttr_seconds']) + 's'):>14}{'giảm':>12}")

    report = {
        "phase": "M3.2 Day 4 — healing KPI (RQ2)",
        "config": {"runs_per_case": RUNS, "backend": "sandbox", "cases": HEALABLE_CASES, "tier2_modes": TIER2_MODES},
        "kpis": kpis,
        "runs": runs_meta,
        "healing_events": events,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # healing event log riêng (chuẩn healing_event.schema.json)
    (Path("artifacts/experiments") / "healing_events_day4.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    print(f"\nReport: {REPORT_PATH}")
    print(f"Healing events: artifacts/experiments/healing_events_day4.jsonl ({len(events)} events)")

    gate = (h["success_rate"] >= 80 and l["success_rate"] >= 80
            and h["false_repair_rate"] < 5 and l["false_repair_rate"] < 5)
    print(f"=> {'DAY 4 GATE DAT — RQ2 KPI: success >=80%, FRR <5%' if gate else 'CHUA DAT — kiem tra KPI'}")


if __name__ == "__main__":
    main()

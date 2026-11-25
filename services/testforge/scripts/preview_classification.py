"""Preview phân loại trên fixtures thật (Day 3 verification, trước benchmark Day 4)."""

import glob
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.agent1.analyzer.failure_analyzer import FailureAnalyzer

hits = 0
total = 0
for path in sorted(glob.glob("artifacts/experiments/fixtures/*_dev.json")):
    fixture = json.load(open(path, encoding="utf-8"))
    exec_res = fixture["faulted"]["execution_result"]
    tc = {"test_case_id": f"TC-{fixture['case_id']}-DEV", "function_id": "FUNC-USER-ADD"}
    res = FailureAnalyzer.analyze(exec_res, tc)
    hit = res["failure_type"] == fixture["ground_truth_type"]
    hits += 1 if hit else 0
    total += 1
    action = res["recommended_action"]
    print(f"{fixture['case_id']}: gt={fixture['ground_truth_type']:<20} "
          f"predicted={res['failure_type']:<20} {'HIT ' if hit else 'MISS'} action={action}")
print(f"\n=> {hits}/{total} đúng (preliminary — benchmark chính thức ở Day 4, N=3)")

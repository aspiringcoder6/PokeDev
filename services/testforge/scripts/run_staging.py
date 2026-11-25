"""Run reviewed staging contracts, without demo resets or simulated fallback."""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.agent1.staging import preflight, run_suite


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output", default="artifacts/automation/staging")
    parser.add_argument("--keep-runs", type=int, default=20)
    parser.add_argument("--headed", action="store_true", help="Chạy browser hiển thị giao diện")
    parser.add_argument("--slowmo", type=int, default=0, help="Độ trễ mỗi thao tác (ms) để kịp quan sát")
    args = parser.parse_args()
    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))
        suite = json.loads(Path(args.suite).read_text(encoding="utf-8-sig"))
        preflight(profile)
        result = run_suite(profile, suite, args.output, keep_runs=args.keep_runs, headed=args.headed, slowmo=args.slowmo)
    except Exception as exc:
        from src.agent1.reporter.junit_reporter import JUnitReporter
        error = f"Staging configuration/runtime error: {type(exc).__name__}: {exc}"
        directory = Path(args.output) / ("ERROR-" + uuid.uuid4().hex)
        try:
            directory.mkdir(parents=True)
            summary = {"status": "ERROR", "gate_passed": False, "exit_code": 2, "error": error}
            (directory / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            (directory / "junit.xml").write_text(JUnitReporter.from_functional_result(summary,
                [{"test_case_id": "SETUP-ERROR", "status": "ERROR", "error": error}]), encoding="utf-8")
        except OSError:
            print("Could not persist failure report", file=sys.stderr)
        print(error, file=sys.stderr)
        return 2
    print(json.dumps({"output_dir": result["output_dir"], **result["functional_result"]}, indent=2))
    return result["functional_result"]["exit_code"]


if __name__ == "__main__":
    sys.exit(main())

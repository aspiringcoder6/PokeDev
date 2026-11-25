"""G3 entrypoint: promote một exploration run thành regression asset.

Yêu cầu HITL: --approved-by <tên reviewer> + promotion.json phải promoted=true.
Bundle (profile + suite + manifest) ghi vào opt/staging/generated/ chờ review
merge; --run chạy thử bundle qua đúng run_suite (full pipeline reviewed).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent1.explorer.regression import build_regression_asset


def main():
    parser = argparse.ArgumentParser(description="Promote exploration run -> regression asset")
    parser.add_argument("--session", required=True)
    parser.add_argument("--profile", required=True,
                        help="Reviewed staging profile để tái sử dụng locators/routes/actors")
    parser.add_argument("--approved-by", required=True, help="Tên reviewer (HITL bắt buộc)")
    parser.add_argument("--requirement-ref", default="")
    parser.add_argument("--out-dir", default="opt/staging/generated")
    parser.add_argument("--run", action="store_true",
                        help="Chạy thử bundle qua run_suite ngay sau khi sinh")
    args = parser.parse_args()

    from src.agent1.staging import run_suite

    asset = build_regression_asset(args.session, args.profile, args.approved_by,
                                   requirement_ref=args.requirement_ref or None)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    short = asset["suite"]["cases"][0]["test_case_id"]
    profile_path = out_dir / "{0}.profile.json".format(short)
    suite_path = out_dir / "{0}.suite.json".format(short)
    manifest_path = out_dir / "{0}.manifest.json".format(short)
    profile_path.write_text(json.dumps(asset["profile"], indent=2, ensure_ascii=False), encoding="utf-8")
    suite_path.write_text(json.dumps(asset["suite"], indent=2, ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(json.dumps(asset["manifest"], indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"profile": str(profile_path), "suite": str(suite_path),
                      "manifest": str(manifest_path),
                      "case_id": short}, indent=2))

    if args.run:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        result = run_suite(profile, suite)
        summary = result["functional_result"]
        print(json.dumps({"run_id": summary.get("run_id"), "gate_passed": summary.get("gate_passed"),
                          "exit_code": summary.get("exit_code"),
                          "output_dir": result["output_dir"]}, indent=2))
        sys.exit(summary.get("exit_code", 1))


if __name__ == "__main__":
    main()

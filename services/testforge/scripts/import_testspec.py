"""CLI: nhập test spec 5 cột (Function ID | Feature | Precondition | Steps | Expected Result)
thành suite draft + profile draft cho HITL duyệt — KHÔNG tự đè file reviewed, KHÔNG chạy gate.

Ví dụ:
  python scripts/import_testspec.py --spec opt/testspec/tteamflow_projects.sample.csv ^
      --profile config/tteamflow.staging.docker.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent1.testspec import build_suite, parse_spec


def main():
    parser = argparse.ArgumentParser(description="Import 5-column test spec -> suite draft")
    parser.add_argument("--spec", required=True, help="CSV/TSV/JSON/XLSX theo 5 cột chuẩn")
    parser.add_argument("--profile", default="",
                        help="Profile đã review để tái sử dụng locator (tuỳ chọn)")
    parser.add_argument("--out-suite", default="",
                        help="Đường dẫn ghi suite draft (mặc định: opt/staging/generated/)")
    parser.add_argument("--out-profile", default="",
                        help="Đường dẫn ghi profile additions (mặc định: cạnh suite)")
    parser.add_argument("--name", default="", help="Ghi đè tên suite")
    args = parser.parse_args()

    profile = {}
    if args.profile:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8-sig"))

    try:
        rows = parse_spec(args.spec)
    except ValueError as exc:
        raise SystemExit("Spec error: {0}".format(exc))

    result = build_suite(rows, profile=profile, source=args.spec)
    if args.name:
        result["suite"]["name"] = args.name

    spec_stem = Path(args.spec).stem
    out_suite = Path(args.out_suite) if args.out_suite else \
        Path("opt/staging/generated/{0}.draft.suite.json".format(spec_stem))
    out_profile = Path(args.out_profile) if args.out_profile else \
        out_suite.with_name("{0}.draft.profile.json".format(spec_stem))
    out_suite.parent.mkdir(parents=True, exist_ok=True)
    out_suite.write_text(json.dumps(result["suite"], indent=2, ensure_ascii=False),
                         encoding="utf-8")
    out_profile.write_text(json.dumps(result["profile_additions"], indent=2,
                                      ensure_ascii=False), encoding="utf-8")

    report = {
        "suite": str(out_suite),
        "profile_additions": str(out_profile),
        "review_status": result["suite"]["review_status"],
        "stats": result["stats"],
        "clean": result["clean"],
        "warnings": result["warnings"],
        "next_step": "Review draft files, remap requirement_refs, set draft locators, "
                     "then merge manually (system never promotes on its own).",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())

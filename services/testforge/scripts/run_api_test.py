#!/usr/bin/env python
"""Chạy một testcase API (oracle API, nhóm 4.33+) — không LLM, deterministic.

Usage:
  python scripts/run_api_test.py --testcase artifacts/library/FUNC-433-1.json \
      --base-url http://localhost:7004 [--token <bearer>] [--out result.json]

Testcase cần có khối "api_request" (xem src/agent1/explorer/api_explorer.py).
Exit code: 0 = PASS, 1 = FAIL/ERROR, 2 = contract không hợp lệ.
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent1.explorer.api_explorer import ApiExplorer, ApiRequestError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run API testcase (oracle API)")
    parser.add_argument("--testcase", required=True,
                        help="Path tới testcase JSON ('-' để đọc stdin)")
    parser.add_argument("--base-url",
                        default=os.environ.get("TESTFORGE_API_BASE", "http://localhost:7004"),
                        help="Base URL backend (mặc định env TESTFORGE_API_BASE)")
    parser.add_argument("--token", default=os.environ.get("TESTFORGE_API_TOKEN", ""),
                        help="Bearer token gắn vào Authorization nếu có")
    parser.add_argument("--out", default="", help="Ghi kết quả JSON ra file")
    args = parser.parse_args()

    if args.testcase == "-":
        testcase = json.loads(sys.stdin.read())
    else:
        testcase = json.loads(Path(args.testcase).read_text(encoding="utf-8"))

    extra_headers = {}
    if args.token:
        extra_headers["Authorization"] = "Bearer {0}".format(args.token)

    try:
        result = ApiExplorer().run(testcase, args.base_url, extra_headers or None)
    except ApiRequestError as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False))
        return 2

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

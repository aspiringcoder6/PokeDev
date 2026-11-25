"""Composer CLI — khép vòng tự động: cognee chunks -> 5-field -> (tùy chọn) explore.

Luồng:
    1. POST {broker}/api/v1/fetch-testcase  -> raw chunks từ Agent Memory (cognee)
    2. TestcaseComposer.compose             -> LLM soạn 5-field + validate IN001-IN005
    3. Lưu artifacts/inputs/<function_id>.json (cùng đường dẫn broker materialize)
    4. --submit: POST {broker}/api/v1/explore với input_inline (chạy explorer)

Ví dụ:
    python scripts/compose_testcase.py --dataset testforge-TNQD-P01 ^
        --query "4.6.2.2 Tìm kiếm nhanh phát động phong trào" --function-id FUNC-PTT-SEARCH-QUICK

    # soạn xong chạy luôn explorer (headed để xem):
    python scripts/compose_testcase.py --dataset testforge-TNQD-P01 ^
        --query "4.6.2.7 Sửa phát động phong trào" --function-id FUNC-PTT-EDIT ^
        --submit --base-url http://localhost:4200 --api-url http://localhost:7004 ^
        --email admin@example.com --headed --slowmo 400
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys_path = str(PROJECT_ROOT)
if sys_path not in ("",) and sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from src.agent1.composer.composer import TestcaseComposer  # noqa: E402


def _broker_post(url: str, token: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit("HTTP {0} từ broker: {1}".format(exc.code, detail))


def main() -> int:
    ap = argparse.ArgumentParser(description="Compose 5-field Standard Test Input từ cognee chunks")
    ap.add_argument("--dataset", required=True, help="Dataset id/tên, VD testforge-TNQD-P01")
    ap.add_argument("--query", required=True, help="Câu truy vấn ngữ cảnh, VD '4.6.2.2 Tìm kiếm nhanh'")
    ap.add_argument("--function-id", default="", help="function_id bắt buộc (bỏ trống để LLM tự đặt)")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--broker-url", default=os.environ.get("TESTFORGE_BROKER_URL", "http://127.0.0.1:9099"))
    ap.add_argument("--token", default=os.environ.get("TESTFORGE_BROKER_TOKEN", ""))
    ap.add_argument("--attempts", type=int, default=2, help="Số lần retry LLM khi sai schema")
    ap.add_argument("--grounding-threshold", type=float, default=0.5,
                    help="Chặn testcase khi độ che phủ < threshold (0 = chỉ cảnh báo)")
    ap.add_argument("--judge", action="store_true",
                    help="Bật LLM thẩm định: đối chiếu 5-field với đoạn gốc (1 call thêm)")
    ap.add_argument("--save", action="store_true", help="Lưu artifacts/inputs/<function_id>.json")
    ap.add_argument("--submit", action="store_true", help="Gọi explore với input_inline sau khi compose")
    ap.add_argument("--base-url", default="", help="URL SUT (bắt buộc khi --submit)")
    ap.add_argument("--api-url", default="", help="URL API backend (bắt buộc khi --submit)")
    ap.add_argument("--email", default="", help="Email actor (bắt buộc khi --submit)")
    ap.add_argument("--headed", action="store_true", help="Browser hiển thị khi explore")
    ap.add_argument("--slowmo", type=int, default=0, help="Trễ mỗi action (ms)")
    ap.add_argument("--quiet", action="store_true",
                    help="Machine-readable: tiến trình/grounding ra stderr, CHỈ JSON 5-field ra stdout")
    args = ap.parse_args()

    def say(msg: str) -> None:
        print(msg, file=sys.stderr if args.quiet else sys.stdout)

    if not args.token:
        raise SystemExit("Thiếu token: đặt TESTFORGE_BROKER_TOKEN hoặc --token")

    say("[1/3] fetch-testcase từ Agent Memory (qua broker)...")
    recall = _broker_post(
        args.broker_url.rstrip("/") + "/api/v1/fetch-testcase",
        args.token,
        {"dataset": args.dataset, "query": args.query, "function_id": args.function_id, "top_k": args.top_k},
    )
    chunks = recall.get("chunks") or []
    say("  chunks: {0}".format(len(chunks)))
    for i, c in enumerate(chunks):
        say("    chunk {0}: {1} chars (doc={2})".format(i + 1, len(c.get("text") or ""), str(c.get("document_id"))[:8]))

    say("[2/3] LLM compose 5-field...")
    result = TestcaseComposer(
        max_attempts=args.attempts,
        grounding_threshold=args.grounding_threshold,
        enable_judge=args.judge,
    ).compose(chunks, query=args.query, function_id=args.function_id, dataset=args.dataset)
    prov = result.get("provenance") or {}
    say("  ok={0} grounded={1} (ratio={2} threshold={3}) attempts={4} model={5}".format(
        result["ok"], result["grounded"], result["grounded_ratio"],
        result.get("grounding_threshold"), result["attempts"], prov.get("llm_model")))
    if (prov.get("judge") or {}).get("skipped"):
        say("  judge: skipped ({0})".format(prov["judge"]["skipped"]))
    elif prov.get("judge"):
        say("  judge: match={0} differences={1}".format(
            prov["judge"].get("match"), prov["judge"].get("differences")))
    for g in (prov.get("grounding") or []):
        say("    grounding {0:.2f}  {1}".format(g["ratio"], g["text"]))
    if not result["ok"]:
        for e in result["errors"]:
            say("  ERROR: {0}".format(e))
        return 2

    std = result["standard_input"]
    if args.quiet:
        print(json.dumps(std, ensure_ascii=False))
        return 0
    print(json.dumps(std, ensure_ascii=False, indent=2))

    out_path = None
    if args.save:
        out_dir = PROJECT_ROOT / "artifacts" / "inputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "{0}.json".format(std["function_id"])
        out_path.write_text(json.dumps(std, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[3/3] Đã lưu {0}".format(out_path))
    elif not args.submit:
        print("[3/3] (không lưu — dùng --save hoặc --submit)")

    if args.submit:
        missing = [n for n, v in (("base_url", args.base_url), ("api_url", args.api_url), ("email", args.email)) if not v]
        if missing:
            raise SystemExit("--submit cần thêm: " + ", ".join("--" + m for m in missing))
        print("[submit] POST /api/v1/explore (input_inline, function_id={0})...".format(std["function_id"]))
        job = _broker_post(
            args.broker_url.rstrip("/") + "/api/v1/explore",
            args.token,
            {
                "input_inline": std,
                "base_url": args.base_url,
                "api_url": args.api_url,
                "email": args.email,
                "headed": bool(args.headed),
                "slowmo": int(args.slowmo),
            },
            timeout=60,
        )
        print(json.dumps(job, ensure_ascii=False, indent=2))
        print("Poll: GET {0}/api/v1/result/{1}".format(args.broker_url.rstrip("/"), job.get("job_id")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

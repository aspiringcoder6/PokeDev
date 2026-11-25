"""Batch compose — quét các mục chức năng PTYC -> thư viện 5-field Standard Test Input.

Dùng TestcaseComposer (LLM + grounding blocking + judge) cho từng mục:
    fetch-testcase (chunks cognee) -> compose -> save opt/../artifacts/library/<fid>.json

Nguồn danh sách mục: opt/ptyc_sections.json (tạo từ full-text PTYC, có num/name/group).

Ví dụ:
    # pilot nhóm Phong trào (12 mục):
    python scripts/batch_compose.py --group 4.6.2
    # một mục cụ thể:
    python scripts/batch_compose.py --sections 4.6.2.4
    # toàn bộ (176 mục, chạy đêm):
    python scripts/batch_compose.py --all
    # chạy lại chỉ các mục FAIL ở lần trước:
    python scripts/batch_compose.py --all --retry-failed
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent1.composer.composer import TestcaseComposer  # noqa: E402

SECTIONS_FILE = PROJECT_ROOT / "opt" / "ptyc_sections.json"
LIBRARY_DIR = PROJECT_ROOT / "artifacts" / "library"
SUMMARY_PATH = PROJECT_ROOT / "artifacts" / "library" / "_batch_summary.json"


def _broker_post(url: str, token: str, payload: dict, timeout: int = 120) -> dict:
    """POST lên broker. 401/403 -> SystemExit (token sai — fail fast);
    lỗi tạm thời (5xx/network) -> RuntimeError để batch skip mục, chạy tiếp."""
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
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        if exc.code in (401, 403):
            raise SystemExit("Token bị từ chối ({0}): {1}".format(exc.code, detail))
        raise RuntimeError("broker {0}: {1}".format(exc.code, detail))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise RuntimeError("không gọi được broker: {0}".format(exc))


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch compose 5-field từ các mục chức năng PTYC")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--group", help="Nhóm chức năng, VD 4.6.2")
    src.add_argument("--sections", help="Danh sách số mục cách nhau bởi dấu phẩy, VD 4.6.2.4,4.6.2.7")
    src.add_argument("--all", action="store_true", help="Toàn bộ mục trong sections file")
    ap.add_argument("--dataset", default="testforge-TNQD-P01")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--broker-url", default=os.environ.get("TESTFORGE_BROKER_URL", "http://127.0.0.1:9099"))
    ap.add_argument("--token", default=os.environ.get("TESTFORGE_BROKER_TOKEN", ""))
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--grounding-threshold", type=float, default=0.5)
    ap.add_argument("--judge", action="store_true", help="Bật LLM thẩm định (1 call thêm/mục)")
    ap.add_argument("--limit", type=int, default=0, help="Giới hạn số mục (pilot)")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Chỉ chạy lại các mục FAIL trong _batch_summary.json trước đó")
    args = ap.parse_args()

    if not args.token:
        raise SystemExit("Thiếu token: đặt TESTFORGE_BROKER_TOKEN hoặc --token")

    sections = json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))
    if args.group:
        targets = [s for s in sections if s["group"] == args.group]
    elif args.sections:
        wanted = {s.strip() for s in args.sections.split(",")}
        targets = [s for s in sections if s["num"] in wanted]
    else:
        targets = list(sections)

    prev_failures = set()
    if args.retry_failed and SUMMARY_PATH.exists():
        prev = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        prev_failures = {
            r["num"] for r in prev.get("results", [])
            if r.get("status") in ("failed", "error", "no_chunks")
        }
        targets = [s for s in targets if s["num"] in prev_failures]

    if not targets:
        raise SystemExit("Không có mục nào khớp lựa chọn")
    if args.limit:
        targets = targets[: args.limit]

    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    print("Batch compose {0} muc (dataset={1} judge={2} threshold={3})".format(
        len(targets), args.dataset, args.judge, args.grounding_threshold))

    results = []
    for i, sec in enumerate(targets, 1):
        fid = sec["function_id"]
        out_path = LIBRARY_DIR / "{0}.json".format(fid)
        if out_path.exists():
            print("[{0}/{1}] {2} SKIP (da co: {3})".format(i, len(targets), sec["num"], fid))
            results.append({"num": sec["num"], "function_id": fid, "status": "skipped"})
            continue
        query = "{0} {1}".format(sec["num"], sec["name"])
        t0 = time.time()
        print("[{0}/{1}] {2} {3}".format(i, len(targets), sec["num"], sec["name"][:60]))
        try:
            recall = _broker_post(
                args.broker_url.rstrip("/") + "/api/v1/fetch-testcase",
                args.token,
                {"dataset": args.dataset, "query": query, "function_id": fid, "top_k": args.top_k},
            )
            chunks = recall.get("chunks") or []
            if not chunks:
                print("    NO_CHUNKS — skip")
                results.append({"num": sec["num"], "function_id": fid, "status": "no_chunks"})
                continue
            res = TestcaseComposer(
                max_attempts=args.attempts,
                grounding_threshold=args.grounding_threshold,
                enable_judge=args.judge,
            ).compose(chunks, query=query, function_id=fid, dataset=args.dataset)
        except SystemExit:
            raise
        except Exception as exc:  # một mục lỗi không được phá cả batch
            print("    ERROR: {0}: {1}".format(type(exc).__name__, str(exc)[:120]))
            results.append({"num": sec["num"], "function_id": fid, "status": "error",
                            "error": "{0}: {1}".format(type(exc).__name__, str(exc)[:200])})
            continue

        elapsed = round(time.time() - t0, 1)
        if res["ok"]:
            out_path.write_text(
                json.dumps(res["standard_input"], ensure_ascii=False, indent=2), encoding="utf-8")
            judge = (res["provenance"].get("judge") or {})
            print("    OK  ratio={0} attempts={1} judge={2} ({3}s) -> {4}".format(
                res["grounded_ratio"], res["attempts"],
                "match" if judge.get("match") else ("skip" if judge else "-"), elapsed, fid))
            results.append({"num": sec["num"], "function_id": fid, "status": "ok",
                            "ratio": res["grounded_ratio"], "attempts": res["attempts"],
                            "judge": bool(judge.get("match")), "elapsed_s": elapsed})
        else:
            print("    FAIL attempts={0}: {1}".format(
                res["attempts"], "; ".join(res["errors"][:2])[:160]))
            results.append({"num": sec["num"], "function_id": fid, "status": "failed",
                            "errors": res["errors"][:3], "elapsed_s": elapsed})

    ok_n = sum(1 for r in results if r["status"] == "ok")
    fail_n = sum(1 for r in results if r["status"] == "failed")
    skip_n = sum(1 for r in results if r["status"] == "skipped")
    err_n = sum(1 for r in results if r["status"] in ("error", "no_chunks"))
    ratios = [r["ratio"] for r in results if r["status"] == "ok"]
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": args.dataset,
        "total": len(targets), "ok": ok_n, "failed": fail_n,
        "skipped": skip_n, "error": err_n,
        "avg_ratio": round(sum(ratios) / len(ratios), 3) if ratios else None,
        "results": results,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n===== TONG KET =====")
    print("ok={0} failed={1} skipped={2} error={3} | avg_ratio={4}".format(
        ok_n, fail_n, skip_n, err_n, summary["avg_ratio"]))
    print("summary: {0}\nlibrary: {1}".format(SUMMARY_PATH, LIBRARY_DIR))
    return 0 if fail_n == 0 and err_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

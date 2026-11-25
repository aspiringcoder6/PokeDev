"""Static validation cho k6 script — 10 rule (docs/architecture/05_agent2_performance.md §6).

Thiết kế ghi "k6 Static Validation" với 8 mục `✓` + 2 mục `✗` = 10 rule thực thi.
Mỗi rule là deterministic (regex hoặc subprocess); không cần chạy k6.

Rule severities:
- ERROR (script bị bác, không chạy): SVP01, SVP05, SVP06 (hardcode host trong
  http call), SVP08 (hardcoded credentials), SVP02/03/04/07
- WARNING: SVP10 (missing sleep)

Output:
{
  "valid": bool,           # True khi không có ERROR
  "errors": [{"code","rule","message"}],
  "warnings": [...],
}
"""
import re
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def _check_node_syntax(script_text: str) -> Dict[str, Any]:
    """SVP01 — node --check trên file tạm (đóng fd trước khi subprocess chạy)."""
    node = shutil.which("node")
    if not node:
        return {"ok": True, "note": "node not found - skipped"}
    fd, tmp = tempfile.mkstemp(suffix=".mjs")
    try:
        os.close(fd)
        Path(tmp).write_text(script_text, encoding="utf-8")
        proc = subprocess.run([node, "--check", tmp], capture_output=True, timeout=15)
    finally:
        try:
            Path(tmp).unlink(missing_ok=True)
        except PermissionError:
            pass
    if proc.returncode != 0:
        return {"ok": False, "stderr": (proc.stderr or b"").decode("utf-8", "ignore")[-300:]}
    return {"ok": True}


# Map Performance Requirement threshold -> (k6 metric expr prefix, comparator)
_PERF_TO_K6 = [
    ("p50_ms_max",          "http_req_duration", "p(50)<"),
    ("p95_ms_max",          "http_req_duration", "p(95)<"),
    ("p99_ms_max",          "http_req_duration", "p(99)<"),
    ("error_rate_max",      "http_req_failed",    "rate<"),
    ("throughput_rps_min",  "http_reqs",          "rate>"),
]


def validate(script_text: str, requirement: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Chạy 10 rule up front. Returns dict có 'valid' + errors/warnings."""
    errors: List[Dict[str, str]] = []
    warnings: List[str] = []
    text = script_text or ""

    # SVP01 — cú pháp
    syntax = _check_node_syntax(text)
    if not syntax["ok"]:
        errors.append({"code": "SVP01", "rule": "syntax",
                       "message": "node --check fail: " + syntax.get("stderr", "")})

    # SVP02 — import k6/http
    if "from 'k6/http'" not in text:
        errors.append({"code": "SVP02", "rule": "import_k6_http",
                       "message": "Thiếu import http từ 'k6/http'"})

    # SVP03 — export const options + stages
    if not re.search(r"export\s+const\s+options\s*=", text) or "stages:" not in text:
        errors.append({"code": "SVP03", "rule": "options_stages",
                       "message": "Thiếu export const options với stages"})

    # SVP04 — export default function
    if not re.search(r"export\s+default\s+function", text):
        errors.append({"code": "SVP04", "rule": "default_function",
                       "message": "Thiếu export default function()"})

    # SVP05 — thresholds khớp Performance Requirement
    if requirement:
        thr = requirement.get("thresholds") or {}
        for key, _metric, expr_prefix in _PERF_TO_K6:
            if key in thr and expr_prefix not in text:
                errors.append({
                    "code": "SVP05", "rule": "threshold_match",
                    "message": "Threshold {0} trong requirement nhưng '{1}' thiếu trong script"
                               .format(key, expr_prefix)})

    # SVP06 — BASE_URL dùng __ENV
    if "__ENV.BASE_URL" not in text:
        errors.append({"code": "SVP06", "rule": "base_url_env",
                       "message": "BASE_URL phải qua __ENV, không hardcode"})

    # SVP07 — ít nhất 1 check()
    if "check(" not in text:
        errors.append({"code": "SVP07", "rule": "check_call",
                       "message": "Phải có ít nhất 1 lệnh check()"})

    # SVP08 — SharedArray cho test data
    if "SharedArray" not in text:
        errors.append({"code": "SVP08", "rule": "shared_array",
                       "message": "Dữ liệu test phải qua SharedArray, không inline"})

    # SVP09 — ERROR: hardcoded credentials (literal có quote; user.X ref không match)
    cred = re.search(r"(email|password|api[_-]?key|token)\s*:\s*(['\"])([^'\"]+)\2", text)
    if cred and not cred.group(3).startswith("user."):
        errors.append({"code": "SVP09", "rule": "hardcoded_credentials",
                       "message": "Phát hiện thông tin đăng nhập hardcode "
                                  "'{0}: ...' (dùng user.* từ SharedArray)".format(cred.group(1))})

    # SVP10 — WARNING: thiếu sleep()
    if "sleep(" not in text:
        warnings.append("SVP10: thiếu sleep() - có thể tạo tải không thực tế")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


__all__ = ["validate"]

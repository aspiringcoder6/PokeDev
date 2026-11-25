"""k6 runner — subprocess + NDJSON aggregation → metrics dict.

Sử dụng `k6 run --out json` (stream NDJSON) thay vì `--summary-export` vì
summary-export thiếu p(99). Phương pháp nearest-rank cho percentile, deterministic.
"""
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _percentile(sorted_values: list, pct: float) -> Optional[float]:
    """Nearest-rank percentile. None nếu rỗng."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def parse_ndjson(ndjson_path: str) -> Dict[str, Any]:
    """Phân tích kết quả k6 JSON output → metrics dict khớp performance_result schema."""
    durations = []
    total_requests = 0
    failed_requests = 0
    max_vus = 0
    first_ts = None
    last_ts = None

    with open(ndjson_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "Point":
                continue
            metric = entry.get("metric", "")
            data = entry.get("data") or {}
            value = data.get("value")
            ts_str = data.get("time", "")

            if metric == "http_req_duration":
                durations.append(float(value))
            elif metric == "http_reqs":
                total_requests += int(value)
            elif metric == "http_req_failed":
                failed_requests += int(value)
            elif metric == "vus_max":
                max_vus = max(max_vus, int(value))

            if ts_str:
                if first_ts is None:
                    first_ts = ts_str
                last_ts = ts_str

    durations.sort()

    duration_seconds = _timespan_seconds(first_ts, last_ts)
    throughput = total_requests / duration_seconds if duration_seconds > 0 else 0.0
    error_rate = failed_requests / total_requests if total_requests > 0 else 0.0

    return {
        "p50_ms": _percentile(durations, 50),
        "p95_ms": _percentile(durations, 95),
        "p99_ms": _percentile(durations, 99),
        "throughput_rps": round(throughput, 2),
        "error_rate": round(error_rate, 4),
        "total_requests": total_requests,
        "failed_requests": failed_requests,
        "max_concurrent_vus": max_vus,
        "duration_seconds": round(duration_seconds, 1),
        "duration_samples": len(durations),
    }


def _timespan_seconds(first_ts: Optional[str], last_ts: Optional[str]) -> float:
    """Khoảng thời gian giữa 2 ISO timestamp (ms precision via fromisoformat,
    fallback strptime giây cho timestamp không parse được)."""
    if not first_ts or not last_ts:
        return 0.0
    try:
        from datetime import datetime
        t1 = datetime.fromisoformat(str(first_ts))
        t2 = datetime.fromisoformat(str(last_ts))
        return (t2 - t1).total_seconds()
    except (ValueError, TypeError):
        pass
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        t1 = time.strptime(str(first_ts)[:19], fmt)
        t2 = time.strptime(str(last_ts)[:19], fmt)
        return time.mktime(t2) - time.mktime(t1)
    except (ValueError, TypeError):
        return 0.0


def run_k6(script_path: str, base_url: str = "http://localhost",
           users_json: str = "users.json", output_dir: str = ".",
           timeout_seconds: int = 600,
           k6_executable: Optional[str] = None) -> Dict[str, Any]:
    """Chạy k6 + aggregate metrics. Returns {"metrics": ..., "exit_code": ..., "stderr_tail": ...}."""
    k6 = k6_executable or shutil.which("k6") or _default_k6_path()
    if not Path(k6).is_file():
        raise FileNotFoundError("k6 executable not found: {0}. Cài k6 trước.".format(k6))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ndjson_path = str(output_dir / "results.ndjson")

    env = {**os.environ, "BASE_URL": base_url, "USERS_JSON": users_json}
    cmd = [k6, "run", script_path, "--out", "json={0}".format(ndjson_path), "--quiet"]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds, env=env)

    metrics = parse_ndjson(ndjson_path) if Path(ndjson_path).is_file() else {
        "p50_ms": None, "p95_ms": None, "p99_ms": None,
        "throughput_rps": 0, "error_rate": 1.0,
        "total_requests": 0, "failed_requests": 0, "max_concurrent_vus": 0,
        "duration_seconds": 0, "duration_samples": 0,
    }
    metrics["exit_code"] = proc.returncode
    metrics["stderr_tail"] = (proc.stderr or b"").decode("utf-8", "ignore")[-300:]
    return metrics


def _default_k6_path() -> str:
    candidate = Path.home() / "AppData" / "Local" / "k6" / "k6-v0.57.0-windows-amd64" / "k6.exe"
    return str(candidate)


__all__ = ["run_k6", "parse_ndjson", "_percentile"]

"""Capacity Estimator — tổng hợp N PRUN cùng perf_req_id → ước tính capability.

Phân tích kỷ luật Little's Law và saturation curve để ước tính:
- Throughput trần (peak rps)
- Số VU tới hạn (saturation point) — nơi throughput bắt đầu giảm khi VU tăng
- Max concurrency ước tính (Little: C = λ × W)
- Bottleneck signals (CPU-bound flag khi p95 tăng quá mức tuyến tính)
- Recommendation hints cho Agent 3

Input: thư mục artifacts/automation/performance/ chứa các PRUN-* có cùng perf_req_id.
Output: aggregated_report.json trong cùng thư mục.
"""
import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
_PERF_ROOT = ROOT / "artifacts" / "automation" / "performance"


def _load_runs(perf_req_id: str, perf_root: Optional[Path] = None,
               limit: int = 10) -> List[Dict[str, Any]]:
    """Tải các PRUN có cùng perf_req_id, sắp xếp theo executed_at tăng dần."""
    root = perf_root or _PERF_ROOT
    if not root.is_dir():
        return []
    runs = []
    for prun_dir in root.iterdir():
        if not prun_dir.is_dir() or not prun_dir.name.startswith("PRUN-"):
            continue
        result_path = prun_dir / "performance_result.json"
        if not result_path.is_file():
            continue
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("perf_req_id") != perf_req_id:
            continue
        runs.append(data)
    runs.sort(key=lambda r: r.get("executed_at", ""))
    return runs[-limit:] if len(runs) > limit else runs


def _little_max_concurrency(peak_rps: float, avg_response_ms: float) -> int:
    """C = λ × W. λ=throughput(rps), W=response(s)."""
    if peak_rps <= 0 or avg_response_ms <= 0:
        return 0
    return max(1, int(peak_rps * (avg_response_ms / 1000.0)))


def _detect_saturation(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Phát hiện saturation: điểm throughput bắt đầu giảm khi VU tăng."""
    if len(runs) < 2:
        return {"detected": False, "reason": "cần ít nhất 2 datapoints"}

    curve = []
    for r in runs:
        vus = (r.get("metrics") or {}).get("max_concurrent_vus", 0)
        rps = (r.get("metrics") or {}).get("throughput_rps", 0)
        p95 = (r.get("metrics") or {}).get("p95_ms", 0) or 1
        if vus > 0:
            curve.append({"vus": vus, "rps": rps, "p95_ms": p95})

    if len(curve) < 2:
        return {"detected": False, "reason": "không đủ dữ liệu VU valid"}

    curve.sort(key=lambda d: d["vus"])

    best_per_vu = {}
    for d in curve:
        v = d["vus"]
        if v not in best_per_vu or d["rps"] > best_per_vu[v]["rps"]:
            best_per_vu[v] = d
    deduped = sorted(best_per_vu.values(), key=lambda d: d["vus"])
    if len(deduped) < 2:
        return {"detected": False, "reason": "cần ít nhất 2 mức VU khác nhau"}

    peak_rps = max(d["rps"] for d in deduped)
    peak_point = next(d for d in deduped if d["rps"] == peak_rps)

    for i in range(1, len(deduped)):
        if deduped[i]["rps"] < deduped[i - 1]["rps"] * 0.9:
            return {
                "detected": True,
                "saturation_vus": deduped[i]["vus"],
                "peak_vus": peak_point["vus"],
                "peak_rps": peak_rps,
                "throughput_drop_pct": round(
                    (1 - deduped[i]["rps"] / peak_rps) * 100, 1),
                "curve": curve,
            }

    return {"detected": False, "peak_vus": peak_point["vus"], "peak_rps": peak_rps,
            "curve": curve}


def _detect_bottleneck(runs: List[Dict[str, Any]]) -> List[str]:
    """Heuristic bottleneck signals cho Agent 3."""
    signals = []
    if len(runs) < 2:
        return signals

    baseline = min(runs, key=lambda r: (r.get("metrics") or {}).get("max_concurrent_vus", 999))
    highest = max(runs, key=lambda r: (r.get("metrics") or {}).get("max_concurrent_vus", 0))

    bm = baseline.get("metrics") or {}
    hm = highest.get("metrics") or {}

    if bm.get("p95_ms", 0) > 0 and hm.get("p95_ms", 0) > 0:
        vu_ratio = (hm.get("max_concurrent_vus", 1) / max(1, bm.get("max_concurrent_vus", 1)))
        p95_ratio = hm["p95_ms"] / max(1, bm["p95_ms"])
        if vu_ratio > 1 and p95_ratio > vu_ratio * 2:
            signals.append(
                "CPU-bound suspected: p95 increased {0:.1f}x under {1:.1f}x load increase".format(
                    p95_ratio, vu_ratio))

    if bm.get("throughput_rps", 0) > 0 and hm.get("throughput_rps", 0) > 0:
        if hm["throughput_rps"] < bm["throughput_rps"] * 0.9:
            signals.append("Throughput decreased at higher VU — system beyond saturation")

    error_rates = [(r.get("metrics") or {}).get("error_rate", 0) for r in runs]
    if all(er == 0 for er in error_rates):
        signals.append("Error rate 0% under all loads tested — degradation is latency, not correctness")
    elif max(error_rates) > 0.05:
        signals.append("Error rate exceeded 5% under peak load — possible crash/circuit-breaker")

    return signals


def _build_recommendation(saturation: Dict, bottleneck: List[str],
                          peak_rps: float) -> str:
    """Sinh human-readable recommendation cho developer."""
    parts = []
    if not_sat := not saturation.get("detected"):
        if saturation.get("peak_rps"):
            parts.append("Throughput đỉnh: {0:.2f} rps tại {1} VU.".format(
                saturation["peak_rps"], saturation["peak_vus"]))
        parts.append("Chưa quan sát saturation — cần thêm datapoints ở VU cao hơn.")
    else:
        parts.append("Throughput đỉnh {0:.2f} rps tại {1} VU.".format(
            saturation["peak_rps"], saturation["peak_vus"]))
        parts.append("Saturation tại {0} VU — throughput giảm {1}%. Trên ngưỡng này = xếp hàng chờ CPU.".format(
            saturation["saturation_vus"], saturation.get("throughput_drop_pct", 0)))

    if bottleneck:
        parts.append("Signals: " + "; ".join(bottleneck))

    if any("CPU-bound" in s for s in bottleneck):
        parts.append("Khuyến nghị: giảm bcrypt cost, async hashing, hoặc scale ngang auth-service.")
    return " ".join(parts)


def estimate_capacity(perf_req_id: str,
                      perf_root: Optional[Path] = None,
                      limit: int = 10) -> Dict[str, Any]:
    """Phân tích khả năng chịu tải qua N lần chạy gần nhất.

    Returns: aggregated report (dict) với:
    - datapoints: mảng kết quả rút gọn
    - throughput_curve: [(vus, rps, p95_ms)]
    - estimated_peak_rps / saturation_point / max_concurrency
    - bottleneck_signals (cho Agent 3)
    - dev_recommendation (human-readable)
    """
    runs = _load_runs(perf_req_id, perf_root, limit)
    if not runs:
        return {"perf_req_id": perf_req_id, "error": "không tìm thấy PRUN nào"}

    datapoints = []
    for r in runs:
        m = r.get("metrics") or {}
        datapoints.append({
            "perf_run_id": r.get("perf_run_id"),
            "profile": r.get("profile"),
            "vus": m.get("max_concurrent_vus", 0),
            "p50_ms": m.get("p50_ms"),
            "p95_ms": m.get("p95_ms"),
            "p99_ms": m.get("p99_ms"),
            "throughput_rps": m.get("throughput_rps"),
            "error_rate": m.get("error_rate"),
            "overall_status": r.get("overall_status"),
            "executed_at": r.get("executed_at"),
        })

    saturation = _detect_saturation(runs)
    bottleneck = _detect_bottleneck(runs)

    peak_rps = saturation.get("peak_rps") or max(
        (d["throughput_rps"] or 0) for d in datapoints)
    avg_response = sum((d["p50_ms"] or 0) for d in datapoints) / len(datapoints)
    estimated_concurrency = _little_max_concurrency(peak_rps, avg_response)

    report = {
        "perf_req_id": perf_req_id,
        "generated_at": _local_iso_now(),
        "datapoints": len(datapoints),
        "datapoint_details": datapoints,
        "throughput_curve": [
            {"vus": d["vus"], "rps": d["throughput_rps"], "p95_ms": d["p95_ms"]}
            for d in datapoints
        ],
        "estimated_peak_rps": round(peak_rps, 2),
        "estimated_max_concurrency": estimated_concurrency,
        "saturation_observed": saturation.get("detected", False),
        "saturation_point_vus": saturation.get("saturation_vus"),
        "peak_throughput_vus": saturation.get("peak_vus"),
        "throughput_drop_pct_at_saturation": saturation.get("throughput_drop_pct"),
        "bottleneck_signals": bottleneck,
        "dev_recommendation": _build_recommendation(saturation, bottleneck, peak_rps),
    }
    return report


def _local_iso_now() -> str:
    """Timestamp local kèm offset múi giờ thật (không hardcode +07:00)."""
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def save_aggregated_report(report: Dict[str, Any],
                           perf_root: Optional[Path] = None) -> Path:
    """Ghi aggregated_report.json vào thư mục performance."""
    root = perf_root or _PERF_ROOT
    root.mkdir(parents=True, exist_ok=True)
    out = root / "aggregated_report_{0}.json".format(
        (report.get("perf_req_id") or "unknown").lower())
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


__all__ = ["estimate_capacity", "save_aggregated_report"]

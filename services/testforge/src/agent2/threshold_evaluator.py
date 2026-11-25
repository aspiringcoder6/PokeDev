"""Threshold evaluator (3-Tier) — so sánh metrics vs thresholds → Performance Result.

3-trạng thái (Plan 24 §1.4):
- actual ≤ target → PASS
- target < actual ≤ acceptable_max (hoặc acceptable_min ≤ actual < target) → PASS_WITH_WARNING
- actual > acceptable_max (hoặc actual < acceptable_min) → FAIL

Threshold cũ (số đơn): PASS/FAIL nhị phân (backward compat).
HITL Override: --approved-by + --justification → đè FAIL → PASS_WITH_WARNING + audit log.

Đầu ra khớp `schemas/performance_result.schema.json`.
"""
import time
import uuid
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+07:00", time.localtime())


def _eval_single(actual, threshold, comparator) -> str:
    """Threshold dạng số đơn → PASS/FAIL."""
    if actual is None:
        return "SKIP"
    if comparator == "<":
        return "PASS" if actual <= threshold else "FAIL"
    return "PASS" if actual >= threshold else "FAIL"


def _eval_3tier(actual, target, acceptable_bound, comparator) -> str:
    """Threshold dạng {target, acceptable_max/acceptable_min} → PASS/WARNING/FAIL."""
    if actual is None:
        return "SKIP"
    if comparator == "<":
        if actual <= target:
            return "PASS"
        if actual <= acceptable_bound:
            return "PASS_WITH_WARNING"
        return "FAIL"
    else:  # ">" (throughput, minimum)
        if actual >= target:
            return "PASS"
        if actual >= acceptable_bound:
            return "PASS_WITH_WARNING"
        return "FAIL"


def _eval_threshold(raw_threshold, actual, comparator) -> str:
    """Phân loại threshold → chọn evaluator phù hợp."""
    if isinstance(raw_threshold, dict):
        target = raw_threshold.get("target")
        bound = raw_threshold.get("acceptable_max") or raw_threshold.get("acceptable_min")
        if target is not None and bound is not None:
            return _eval_3tier(actual, target, bound, comparator)
        if target is not None:
            return _eval_single(actual, target, comparator)
    return _eval_single(actual, raw_threshold, comparator)


def evaluate(thresholds: Dict[str, Any], metrics: Dict[str, Any],
             perf_req_id: str, profile: str, script_ref: str = "",
             environment: str = "local-docker",
             hitl_overrides: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Đánh giá từng threshold, tổng hợp Performance Result (schema-valid).

    Args:
        hitl_overrides: [{"approved_by": "...", "justification": "...",
                          "thresholds_override": ["p99_ms_max", ...]}]
                         Threshold trong danh sách bị ép PASS_WITH_WARNING.
    """
    evals: List[Dict[str, Any]] = []
    violated_fail: List[str] = []
    warnings: List[str] = []
    hitl = hitl_overrides or []
    override_set = set()
    for h in hitl:
        override_set.update(h.get("thresholds_override") or [])

    mapping = [
        ("p50_ms_max",         metrics.get("p50_ms"),         "<"),
        ("p95_ms_max",         metrics.get("p95_ms"),         "<"),
        ("p99_ms_max",         metrics.get("p99_ms"),         "<"),
        ("error_rate_max",     metrics.get("error_rate"),     "<"),
        ("throughput_rps_min", metrics.get("throughput_rps"), ">"),
    ]

    for metric_id, actual, comparator in mapping:
        if metric_id not in thresholds:
            continue

        result = _eval_threshold(thresholds[metric_id], actual, comparator)

        if metric_id in override_set and result in ("FAIL", "PASS_WITH_WARNING"):
            result = "PASS_WITH_WARNING"

        if result == "FAIL":
            violated_fail.append(metric_id)
        elif result == "PASS_WITH_WARNING":
            warnings.append(metric_id)

        # Record threshold/actual values for result schema
        raw = thresholds[metric_id]
        if isinstance(raw, dict):
            thr_display = raw.get("target")
        else:
            thr_display = raw

        evals.append({
            "metric": metric_id,
            "threshold": thr_display,
            "actual": actual,
            "result": result,
        })

    if violated_fail:
        overall = "FAIL"
        action = "TRIGGER_OPTIMIZATION_AGENT"
    elif warnings:
        overall = "PASS_WITH_WARNING"
        action = "REPORT_WITH_WARNING"
    else:
        overall = "PASS"
        action = "REPORT_ONLY"

    result = {
        "perf_run_id": "PRUN-{0}".format(uuid.uuid4().hex[:8]),
        "perf_req_id": perf_req_id,
        "profile": profile,
        "executed_at": _now_iso(),
        "duration_actual_seconds": metrics.get("duration_seconds", 0),
        "environment": environment,
        "metrics": {
            "p50_ms": metrics.get("p50_ms"),
            "p95_ms": metrics.get("p95_ms"),
            "p99_ms": metrics.get("p99_ms"),
            "throughput_rps": metrics.get("throughput_rps"),
            "error_rate": metrics.get("error_rate"),
            "total_requests": metrics.get("total_requests", 0),
            "failed_requests": metrics.get("failed_requests", 0),
            "max_concurrent_vus": metrics.get("max_concurrent_vus", 0),
        },
        "threshold_evaluation": evals,
        "overall_status": overall,
        "violated_thresholds": violated_fail + warnings,
        "action": action,
        "script_ref": script_ref,
        "trigger_override": None,
    }
    if hitl:
        result["hitl_overrides"] = hitl
    return result


__all__ = ["evaluate"]

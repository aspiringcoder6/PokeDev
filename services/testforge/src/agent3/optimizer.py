"""Agent 3 — Optimization/Recommendation Agent (M4).

Trigger: PerformanceResult.overall_status == FAIL (threshold Agent 2 vi phạm),
hoặc caller yêu cầu phân tích thủ công. Đặc tả: docs/architecture/06_agent3_optimization.md.

Nguyên tắc (khớp Confidence Calibration của đặc tả):
- Dùng "Likely Cause" + confidence 0..1 — KHÔNG khẳng định Root Cause.
- KHÔNG auto-fix code trong MVP; output chỉ là khuyến nghị có validation_plan.
- issue_summary + evidence dựng DETERMINISTIC từ metrics/thresholds của PRUN
  (số liệu không để LLM bịa); LLM chỉ đề xuất likely_causes/recommendations.
- LLM trả rác / không có key -> fallback heuristic (Zero-LLM) vẫn ra REC hợp lệ.
- Output bắt buộc đi qua schemas/recommendation.schema.json — không hợp lệ -> ok=False.
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agent1.healer.llm_client import OpenCodeChatClient, extract_json_object

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "recommendation.schema.json"
PROMPT_VERSION = "optimization-v1"

_VALID_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}


def validate_recommendation(rec: Dict[str, Any]) -> List[str]:
    """Validate REC theo schema. Returns: list lỗi (rỗng = hợp lệ)."""
    try:
        import jsonschema
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        return [e.message for e in sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(rec), key=str)]
    except ImportError:
        return [] if rec.get("rec_id") else ["jsonschema chưa cài — không validate được"]


def _deviation_pct(observed: float, threshold: float) -> float:
    """Lệch % so với threshold (observed > threshold là xấu với latency/error)."""
    if threshold <= 0:
        return 0.0
    return round((observed - threshold) / threshold * 100.0, 1)


class OptimizationAgent:
    """Phân tích PRUN FAIL -> Recommendation REC (LLM + fallback heuristic)."""

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        prompt_version: str = PROMPT_VERSION,
    ):
        self.llm = llm_client if llm_client is not None else OpenCodeChatClient(timeout_seconds=120)
        self.prompt_version = prompt_version

    # ------------------------------------------------------------------
    def analyze(
        self,
        performance_result: Dict[str, Any],
        requirement: Optional[Dict[str, Any]] = None,
        capacity_report: Optional[Dict[str, Any]] = None,
        extra_context: str = "",
    ) -> Dict[str, Any]:
        """PerformanceResult -> REC. Không raise; trả {"ok", "recommendation", "errors"}."""
        perf_run_id = str(performance_result.get("perf_run_id") or "PRUN-unknown")
        perf_req_id = str(performance_result.get("perf_req_id") or "")

        violations = self._violations(performance_result)
        if not violations:
            return {"ok": False, "recommendation": None,
                    "errors": ["NO_VIOLATION: PRUN không có threshold nào FAIL — Agent 3 chỉ chạy khi FAIL"]}
        issue, evidence = self._issue_and_evidence(performance_result, violations)
        if capacity_report:
            evidence += self._capacity_evidence(capacity_report)

        base = {
            "rec_id": "REC-{0}".format(uuid.uuid4().hex[:8]),
            "perf_run_id": perf_run_id,
            "perf_req_id": perf_req_id,
            "generated_at": _local_iso_now(),
            "issue_summary": issue,
            "evidence": evidence,
            "limitations": [],
            "next_steps": [],
        }

        llm = self.llm
        use_llm = bool(getattr(llm, "available", lambda: bool(llm))())
        if use_llm:
            rec, llm_err = self._analyze_llm(base, performance_result, requirement, capacity_report, extra_context)
            if rec is not None:
                return {"ok": True, "recommendation": rec, "errors": []}
            # LLM hỏng/rác -> heuristic fallback
        rec = self._heuristic(base, performance_result, capacity_report)
        errors = [llm_err] if use_llm and llm_err else (["LLM_NO_USABLE_OUTPUT: fallback heuristic"] if use_llm else [])
        return {"ok": True, "recommendation": rec, "errors": errors}

    # ------------------------------------------------------------------
    # Deterministic: violations + issue_summary + evidence từ số liệu thật
    # ------------------------------------------------------------------
    @staticmethod
    def _violations(performance_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = performance_result.get("threshold_evaluation") or []
        return [r for r in rows if r.get("result") == "FAIL"]

    def _issue_and_evidence(
        self, performance_result: Dict[str, Any], violations: List[Dict[str, Any]]
    ) -> tuple:
        """Issue nặng nhất (theo deviation) + evidence từ số liệu thật (không để LLM bịa)."""
        worst = max(violations, key=lambda r: abs(self._deviation(r)))
        issue = {
            "metric": str(worst.get("metric") or "unknown"),
            "observed": str(worst.get("actual")),
            "threshold": str(worst.get("threshold")),
            "deviation_percent": self._deviation(worst),
        }
        return issue, self._evidence(performance_result, violations)

    _NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

    @classmethod
    def _num(cls, text: Any) -> Optional[float]:
        m = cls._NUM_RE.search(str(text or ""))
        return float(m.group(0)) if m else None

    @classmethod
    def _deviation(cls, row: Dict[str, Any]) -> float:
        """deviation_percent: lấy sẵn trong row, thiếu thì tự tính từ actual/threshold."""
        try:
            return round(float(row.get("deviation_percent")), 1)
        except (TypeError, ValueError):
            pass
        actual, thr = cls._num(row.get("actual")), cls._num(row.get("threshold"))
        if actual is not None and thr:
            return round((actual - thr) / thr * 100.0, 1)
        return 0.0

    @staticmethod
    def _evidence(
        performance_result: Dict[str, Any], violations: List[Dict[str, Any]]
    ) -> List[str]:
        m = performance_result.get("metrics") or {}
        lines = ["profile={0} endpoint={1}".format(
            performance_result.get("profile"), performance_result.get("endpoint") or "?")]
        for r in violations:
            lines.append("VIOLATED {0}: actual={1} threshold={2}".format(
                r.get("metric"), r.get("actual"), r.get("threshold")))
        for key in ("p50_ms", "p95_ms", "p99_ms", "throughput_rps", "error_rate",
                    "total_requests", "max_concurrent_vus"):
            if m.get(key) is not None:
                lines.append("{0}={1}".format(key, m[key]))
        return lines

    @staticmethod
    def _capacity_evidence(capacity_report: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        for sig in (capacity_report.get("bottleneck_signals") or []):
            text = sig if isinstance(sig, str) else json.dumps(sig, ensure_ascii=False)
            lines.append("capacity_signal: {0}".format(text))
        if capacity_report.get("saturation_observed"):
            lines.append("saturation tai {0} VU (drop {1}%)".format(
                capacity_report.get("saturation_point_vus"),
                capacity_report.get("throughput_drop_pct_at_saturation")))
        return lines

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------
    def _analyze_llm(
        self,
        base: Dict[str, Any],
        performance_result: Dict[str, Any],
        requirement: Optional[Dict[str, Any]],
        capacity_report: Optional[Dict[str, Any]],
        extra_context: str,
    ) -> tuple:
        system = (
            "Bạn là Agent 3 (Optimization Agent) trong pipeline TestForge AI. Input là "
            "kết quả chạy k6 FAIL threshold. Nhiệm vụ: đề xuất NGUYÊN NHÂN KHẢ NĂI "
            "(likely causes, kèm confidence 0.0-1.0) và KHUYẾN NGHỊ có thể làm ngay.\n"
            "Quy tắc bắt buộc:\n"
            "1. Chỉ dùng thông tin trong dữ liệu được cung cấp; thiếu dữ liệu thì ghi "
            "vào limitations — KHÔNG suy đoán.\n"
            "2. Dùng 'likely cause', KHÔNG khẳng định root cause.\n"
            "3. Không đề xuất sửa code tự động; mỗi khuyến nghị phải có validation_plan "
            "(chạy lại workload nào, so sánh metric nào).\n"
            "4. Confidence 0.0-1.0; priority chỉ HIGH/MEDIUM/LOW.\n"
            "5. Trả về DUY NHẤT JSON object với các key: likely_causes (array), "
            "recommendations (array), limitations (array), next_steps (array). "
            "Không kèm chữ ngoài JSON."
        )
        payload = {
            "issue_summary": base["issue_summary"],
            "evidence": base["evidence"],
            "performance_result": performance_result,
        }
        if requirement:
            payload["performance_requirement"] = requirement
        if capacity_report:
            payload["capacity_report_signals"] = {
                "bottleneck_signals": capacity_report.get("bottleneck_signals"),
                "saturation_observed": capacity_report.get("saturation_observed"),
                "estimated_peak_rps": capacity_report.get("estimated_peak_rps"),
            }
        if extra_context:
            payload["developer_context"] = extra_context
        user = json.dumps(payload, ensure_ascii=False, indent=1)
        content = self.llm.chat(system, user)
        obj = extract_json_object(content) if content else None
        if obj is None or not isinstance(obj.get("likely_causes"), list) \
                or not isinstance(obj.get("recommendations"), list):
            return None, None

        rec = dict(base)
        rec["llm_model"] = str(getattr(self.llm, "model", "") or "unknown")
        rec["llm_prompt_version"] = self.prompt_version
        rec["likely_causes"] = self._normalize_causes(obj.get("likely_causes"))
        rec["recommendations"] = self._normalize_recommendations(obj.get("recommendations"))
        rec["limitations"] = [str(x) for x in (obj.get("limitations") or [])][:8]
        rec["next_steps"] = [str(x) for x in (obj.get("next_steps") or [])][:8] or \
            ["Developer reviews recommendations",
             "Implement HIGH priority fix",
             "Re-run same k6 workload và so sánh metric trước/sau"]
        errors = validate_recommendation(rec)
        if errors:
            return None, "; ".join(errors[:3])
        return rec, None

    # ------------------------------------------------------------------
    # Heuristic fallback (Zero-LLM) — luôn ra REC hợp lệ
    # ------------------------------------------------------------------
    def _heuristic(
        self, base: Dict[str, Any],
        performance_result: Dict[str, Any],
        capacity_report: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        m = performance_result.get("metrics") or {}
        err = float(m.get("error_rate") or 0.0)
        p95, p99 = m.get("p95_ms") or 0, m.get("p99_ms") or 0
        metric = base["issue_summary"]["metric"]

        causes: List[Dict[str, Any]] = []
        if err >= 0.05:
            causes.append({
                "rank": 1, "confidence": 0.7,
                "cause": "Lỗi request hàng loạt ({0:.0%}) — khả năng auth/user pool hoặc "
                         "môi trường SUT chưa sẵn sàng cho tải".format(err),
                "evidence": ["error_rate={0}".format(err)],
                "supporting_code_ref": None,
            })
        if metric in ("p95_ms", "p99_ms") and p99 > 0:
            if p95 and p99 > 2 * p95:
                causes.append({
                    "rank": len(causes) + 1, "confidence": 0.55,
                    "cause": "Tail latency: p99 gấp {0:.1f}x p95 — outlier request (GC, lock, cold cache)".format(p99 / p95),
                    "evidence": ["p95_ms={0}".format(p95), "p99_ms={0}".format(p99)],
                    "supporting_code_ref": None,
                })
            causes.append({
                "rank": len(causes) + 1, "confidence": 0.6,
                "cause": "Latency vượt threshold ở mức tải hiện tại — nghi ngờ CPU-bound "
                         "(hash/encrypt per-request) hoặc thiếu index DB",
                "evidence": ["{0}={1}".format(metric, base["issue_summary"]["observed"]),
                             "capacity_signals={0}".format(
                                 (capacity_report or {}).get("bottleneck_signals") or "n/a")],
                "supporting_code_ref": None,
            })
        if not causes:
            causes.append({
                "rank": 1, "confidence": 0.4,
                "cause": "Metric {0} vi phạm threshold — cần APM/profiling để định vị".format(metric),
                "evidence": base["evidence"][:2],
                "supporting_code_ref": None,
            })

        rec = dict(base)
        rec["llm_model"] = "heuristic-fallback"
        rec["llm_prompt_version"] = self.prompt_version
        rec["likely_causes"] = causes
        rec["recommendations"] = [{
            "priority": "HIGH" if err >= 0.05 else "MEDIUM",
            "action": "Kiểm tra bottleneck signals, bật APM/profiling cho endpoint rồi "
                      "re-run workload sau khi sửa; ưu tiên xử lý error_rate trước latency",
            "target": "endpoint={0}".format(performance_result.get("endpoint") or "n/a"),
            "expected_impact": "Giảm {0} về dưới threshold {1}".format(
                metric, base["issue_summary"]["threshold"]),
            "effort_estimate": "chưa đánh giá — cần profiling data",
            "validation_plan": "Re-run PRUN profile={0} same workload; so sánh {1} trước/sau".format(
                performance_result.get("profile"), metric),
        }]
        rec["limitations"] = [
            "Phân tích heuristic Zero-LLM từ metrics PRUN — chưa có source/SQL/APM",
            "Confidence của likely_causes là ước lượng, cần xác minh bằng profiling",
        ]
        rec["next_steps"] = [
            "Developer reviews recommendations",
            "Thu thập profiling/APM data cho endpoint",
            "Re-run same k6 workload sau thay đổi và so sánh metric",
        ]
        return rec

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_causes(raw: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for i, c in enumerate(raw or []):
            if not isinstance(c, dict):
                continue
            conf = c.get("confidence")
            try:
                conf = min(1.0, max(0.0, float(conf)))
            except (TypeError, ValueError):
                conf = 0.3
            out.append({
                "rank": len(out) + 1,
                "cause": str(c.get("cause") or "")[:300],
                "confidence": round(conf, 2),
                "evidence": [str(e) for e in (c.get("evidence") or [])][:5],
                "supporting_code_ref": c.get("supporting_code_ref") or None,
            })
        return out[:5]

    @staticmethod
    def _normalize_recommendations(raw: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in (raw or []):
            if not isinstance(r, dict):
                continue
            priority = str(r.get("priority") or "").upper()
            out.append({
                "priority": priority if priority in _VALID_PRIORITIES else "MEDIUM",
                "action": str(r.get("action") or "")[:400],
                "target": str(r.get("target") or "")[:200],
                "expected_impact": str(r.get("expected_impact") or "")[:300],
                "effort_estimate": str(r.get("effort_estimate") or "")[:100],
                "validation_plan": str(r.get("validation_plan") or "")[:300],
            })
        return out[:5]


# ----------------------------------------------------------------------
# Helpers module-level
# ----------------------------------------------------------------------
def _local_iso_now() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


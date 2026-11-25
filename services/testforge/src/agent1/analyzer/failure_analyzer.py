"""Failure Analyzer (Bước 14 & Bước 15) — v1.1 evidence-aware.

Nhiệm vụ:
- Phân loại lỗi thành 8 loại (Failure Taxonomies):
  1. LOCATOR      2. TIMING       3. SCRIPT      4. TEST_DATA
  5. ASSERTION    6. ENVIRONMENT  7. APPLICATION_DEFECT  8. UNKNOWN
- Phân biệt Test Issue (có thể tự sửa) vs Application Defect (lỗi ứng dụng).
- v1.1 (M3.1): đọc evidence từ execution_result (network_events, ui_evidence.dom_probe)
  — BẮT BUỘC vì error string của Playwright không đủ để phân biệt
  LOCATOR (element drift/missing) vs TIMING (element ẩn/trễ) vs TEST_DATA (server 4xx).
- BLIND: analyzer KHÔNG bao giờ nhận fault ID — chỉ thấy production evidence.

> ⚠️ **FROZEN — M3.1 Day 4** (`artifacts/experiments/classification_report_dev.json`)
> Rules đã đóng băng trên dev set C01-C06: accuracy 6/6, stability 6/6, UNKNOWN=0.
> KHÔNG hiệu chỉnh rule nào nữa trước khi chạy eval set (Ngày 5, đúng 1 lần).

Nguyên tắc phân loại (thứ tự ưu tiên):
1. APPLICATION_DEFECT : network event >= 500 HOẶC thông điệp lỗi server rõ ràng
2. ENVIRONMENT        : connection refused / network unreachable
3. TEST_DATA          : UI message từ server xác nhận data issue (409/credentials)
4. ASSERTION          : expect()/oracle timeout, UI bình thường, network 2xx
5. TIMING vs LOCATOR  : dom_probe phân biệt (element tồn tại-ẩn vs drift/missing)
6. SCRIPT / UNKNOWN   : fallback
"""

import re
from typing import Any, Dict, List, Optional, Tuple


class FailureAnalyzer:
    """Bộ phân tích nguyên nhân gốc khi test bị FAIL."""

    TAXONOMIES = [
        "LOCATOR",
        "TIMING",
        "SCRIPT",
        "TEST_DATA",
        "ASSERTION",
        "ENVIRONMENT",
        "APPLICATION_DEFECT",
        "UNKNOWN",
    ]

    # Server-side data issue signals (từ ui_evidence.visible_messages / error)
    TEST_DATA_PATTERNS = [
        "must be unique", "duplicate", "invalid credentials", "user not found",
        "foreign key", "already exists", "đã tồn tại",
    ]
    # Server/application crash signals (KHÔNG dùng "500" trần — bắt nhầm "Timeout 500ms")
    APP_DEFECT_PATTERNS = [
        "http 500", "internal server error", "http 502", "http 503",
        "database error", "exception thrown",
    ]
    ENVIRONMENT_PATTERNS = [
        "connection refused", "err_connection", "target closed", "network timeout",
        "net::err",
    ]

    @classmethod
    def analyze(
        cls,
        execution_result: Dict[str, Any],
        test_case: Dict[str, Any],
        dom_snapshot: Optional[str] = None,
        network_logs: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Phân tích lỗi và phân loại taxonomy dựa trên evidence.

        Args:
            execution_result: ExecutionResult (có thể chứa network_events + ui_evidence)
            test_case: Test case đang chạy
            dom_snapshot: DOM/ARIA snapshot (legacy param, tùy chọn)
            network_logs: Network log dạng text (legacy param, tùy chọn)

        Returns:
            Dict cấu trúc FailureAnalysis v1.1 (reason, evidence_refs, recommended_action)
        """
        error_msg = str(execution_result.get("error", ""))
        error_lower = error_msg.lower()
        test_case_id = test_case.get("test_case_id", "TC-UNKNOWN")
        func_id = test_case.get("function_id", "FUNC-UNKNOWN")

        ui_evidence = execution_result.get("ui_evidence") or {}
        visible_messages = [str(m) for m in (ui_evidence.get("visible_messages") or [])]
        visible_lower = " | ".join(visible_messages).lower()
        dom_probe = ui_evidence.get("dom_probe") or []
        net_events = execution_result.get("network_events") or []

        extra_logs = " ".join(str(x) for x in [network_logs] if network_logs)
        haystack = f"{error_lower} {visible_lower} {extra_logs.lower()}"

        def build(failure_type: str, confidence: float, healable: bool,
                  root_cause: str, reason: str, action: str) -> Dict[str, Any]:
            return {
                "failure_id": f"FAIL-{test_case_id}-001",
                "test_case_id": test_case_id,
                "function_id": func_id,
                "failure_type": failure_type,
                "confidence": confidence,
                "healable": healable,
                "root_cause": root_cause,
                "reason": reason,
                "evidence": {
                    "error_message": execution_result.get("error"),
                    "failed_step": execution_result.get("failed_step"),
                    "visible_messages": visible_messages,
                    "dom_snapshot": dom_snapshot,
                },
                "evidence_refs": list(execution_result.get("artifacts") or []) + ["network-events", "ui-evidence"],
                "recommended_action": action,
            }

        # 1. APPLICATION_DEFECT — network 5xx hoặc server crash signal rõ ràng
        five_xx = sorted({
            int(e.get("status")) for e in net_events
            if isinstance(e, dict) and str(e.get("status", "")).isdigit() and int(e.get("status", 0)) >= 500
        })
        app_pattern = next((p for p in cls.APP_DEFECT_PATTERNS if p in haystack), None)
        if five_xx or app_pattern:
            how = (f"HTTP {five_xx} observed on network" if five_xx
                   else f"server error pattern '{app_pattern}'")
            return build(
                "APPLICATION_DEFECT", 0.99, False,
                "Application returned a server error (HTTP 5xx / unhandled exception)",
                f"Application defect: {how}", "STOP_SELF_HEALING",
            )

        # 2. ENVIRONMENT
        if any(p in error_lower for p in cls.ENVIRONMENT_PATTERNS):
            return build(
                "ENVIRONMENT", 0.90, False,
                "Environment or network connectivity error",
                f"Infrastructure signal in error: {error_msg[:120]}", "RETRY_ENVIRONMENT",
            )

        # 3. TEST_DATA — server từ chối data (409) hoặc data-issue signal
        data_signal = any(
            isinstance(e, dict) and e.get("status") == 409 for e in net_events
        ) or any(p in visible_lower or p in error_lower for p in cls.TEST_DATA_PATTERNS)
        if data_signal:
            return build(
                "TEST_DATA", 0.90, False,
                "Test data conflicts with pre-existing state (server rejected data)",
                f"Data issue signal: {(visible_lower or error_msg)[:120]}",
                "DATA_ISSUE_REPORT",
            )

        # 4. Element-level ACTION failure (locator.click/fill timeout) — TIMING vs LOCATOR qua dom_probe
        # Gate theo failing operation: lỗi action có prefix "locator.click:" / "locator.fill:".
        # KHÔNG dùng presence của "expect(" trong error — source-context của Playwright
        # luôn chèn 6 dòng code quanh lỗi, chứa expect() kể cả khi fail ở action.
        if re.search(r"locator\.(click|fill|selectoption):\s*timeout", error_lower):
            element_result = cls._classify_element_failure(error_lower, dom_probe)
            if element_result:
                failure_type, reason, root_cause = element_result
                return build(
                    failure_type,
                    0.92 if failure_type == "LOCATOR" else 0.85,
                    True,
                    root_cause,
                    reason,
                    "TIER_1_OR_2_LOCATOR_HEAL" if failure_type == "LOCATOR" else "TIER_1_RETRY",
                )

        # 5. ASSERTION family: oracle expect(...) failed — UI hành xử bình thường
        if ("expect(locator)." in error_lower
                or "tobevisible() failed" in error_lower
                or 'expect "' in error_lower):
            return build(
                "ASSERTION", 0.85, False,
                "Assertion failed: UI text/state does not match expected oracle",
                f"Assertion oracle not satisfied: {error_msg[:120]}", "REVIEW_ASSERTION",
            )

        # 6. SCRIPT
        if any(p in error_lower for p in ["syntaxerror", "typeerror", "cannot read properties of undefined", "is not a function"]):
            return build(
                "SCRIPT", 0.90, True,
                "Script implementation or syntax error",
                f"Script error signal: {error_msg[:120]}", "TIER_2_AI_SCRIPT_HEAL",
            )

        # 7. Legacy keyword fallback (không có dom_probe — simulated runs cũ)
        if any(p in error_lower for p in ["not found", "waiting for selector", "strict mode violation", "locator"]):
            return build(
                "LOCATOR", 0.92, True,
                "Element locator not found or selector changed in DOM",
                f"Locator signal (no probe): {error_msg[:120]}", "TIER_1_OR_2_LOCATOR_HEAL",
            )
        if any(p in error_lower for p in ["waiting for element to be visible", "navigation timeout"]):
            return build(
                "TIMING", 0.85, True,
                "Race condition or element render timeout",
                f"Timing signal (no probe): {error_msg[:120]}", "TIER_1_RETRY",
            )

        # 8. UNKNOWN
        return build(
            "UNKNOWN", 0.50, False,
            "Insufficient evidence to determine failure type",
            f"No discriminating evidence in: {error_msg[:120]}", "ESCALATE_HUMAN_REVIEW",
        )

    # ------------------------------------------------------------------
    # Evidence helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _has_5xx(net_events: List[Dict[str, Any]]) -> bool:
        for e in net_events or []:
            try:
                if int(e.get("status", 0)) >= 500:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @classmethod
    def _classify_element_failure(
        cls, error_lower: str, dom_probe: List[Dict[str, Any]]
    ) -> Optional[Tuple[str, str, str]]:
        """Phân loại TIMING vs LOCATOR cho lỗi element-level (click/fill timeout).

        Trả về (failure_type, reason, root_cause) hoặc None nếu không suy ra được.
        Quyết định dựa trên dom_probe (không dựa error string một mình):
        - Technical locator (getByTestId) không thấy testid trong DOM probe  -> LOCATOR
          (element có thể vẫn tồn tại với attribute đã drift — chức năng còn nguyên)
        - Semantic locator (getByRole/getByLabel/getByText name X):
            - Không có element nào khớp text X                -> LOCATOR (drift/removed)
            - Khớp nhưng hidden                               -> TIMING (delayed visibility)
            - Khớp và visible                                 -> TIMING (transient)
        """
        if not dom_probe:
            return None

        waiting = re.search(
            r"waiting for (getbytestid|getbyrole|getbylabel|getbytext|locator)\((.+?)\)",
            error_lower,
        )
        if not waiting:
            return None

        kind, raw_arg = waiting.group(1), waiting.group(2)

        if kind == "getbytestid":
            match = re.search(r"'([^']+)'", raw_arg)
            target_testid = match.group(1) if match else ""
            if not target_testid:
                return None
            match_elem = next((p for p in dom_probe if p.get("testid") == target_testid), None)
            if match_elem is None:
                return (
                    "LOCATOR",
                    f"Technical locator getByTestId('{target_testid}') absent from DOM probe (attribute drift)",
                    "Element identified by test ID is missing from DOM — selector drift",
                )
            if not match_elem.get("visible", True):
                return (
                    "TIMING",
                    f"Element with test ID '{target_testid}' exists but hidden at failure time (delayed visibility)",
                    "Element temporarily unavailable beyond test wait policy",
                )
            return (
                "TIMING",
                f"Element with test ID '{target_testid}' exists and visible — transient failure",
                "Element available; failure likely transient — retry appropriate",
            )

        if kind in ("getbyrole", "getbylabel", "getbytext"):
            match = re.search(r"name:\s*'([^']+)'", raw_arg) or re.search(r"'([^']+)'", raw_arg)
            target_text = match.group(1) if match else ""
            if not target_text:
                return None
            match_elem = next(
                (p for p in dom_probe if target_text.lower() in str(p.get("text", "")).lower()),
                None,
            )
            if match_elem is None:
                return (
                    "LOCATOR",
                    f"No element with accessible name '{target_text}' found in DOM probe (semantic drift)",
                    "Element identified by accessible name is missing or renamed",
                )
            if not match_elem.get("visible", True):
                return (
                    "TIMING",
                    f"Element '{target_text}' exists but hidden at failure time (delayed visibility)",
                    "Element temporarily unavailable beyond test wait policy",
                )
            return (
                "TIMING",
                f"Element '{target_text}' exists and visible — transient failure",
                "Element available; failure likely transient — retry appropriate",
            )

        return None

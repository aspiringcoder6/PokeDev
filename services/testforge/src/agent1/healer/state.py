"""HealingState — hợp đồng state cho LangGraph healing orchestration (M3.2).

State chạy qua các node: analyze -> tier1 -> tier2 -> validate -> retest.
Mọi node chỉ đọc/ghi qua state này — không dùng biến cục bộ ẩn.
"""

from typing import Any, Dict, List, Optional, TypedDict


class HealingState(TypedDict, total=False):
    # ---- Inputs (pipeline cung cấp) ----
    test_case: Dict[str, Any]
    execution_result: Dict[str, Any]
    script_code: str

    # ---- Bước 14-15: phân loại (analyzer FROZEN từ M3.1) ----
    failure_analysis: Dict[str, Any]

    # ---- Bước 16: repair proposal ----
    proposal: Optional[Dict[str, Any]]
    proposal_source: str            # "tier1" | "tier2" | ""
    rejected_reasons: List[str]     # lý do validate từ chối proposal

    # ---- Bước 17: retest loop ----
    retest_result: Optional[Dict[str, Any]]
    retest_count: int
    max_retries: int
    tried_locators: List[str]       # các locator đã đề xuất + retest FAIL (chống vòng lặp)

    # ---- Outcome ----
    outcome: str                    # HEALED_PASS | STOP_DEFECT | NOT_HEALABLE | FAILED_HEAL | REJECTED
    healing_events: List[Dict[str, Any]]   # audit log theo trình tự node đi qua


# Outcomes chuẩn (routing mục tiêu cho M3.1 acceptance)
OUTCOME_HEALED_PASS = "HEALED_PASS"
OUTCOME_STOP_DEFECT = "STOP_DEFECT"
OUTCOME_NOT_HEALABLE = "NOT_HEALABLE"
OUTCOME_FAILED = "FAILED_HEAL"
OUTCOME_REJECTED = "REJECTED"

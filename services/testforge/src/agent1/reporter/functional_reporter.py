"""Functional Result Reporter (Bước 20).

Nhiệm vụ:
- Tổng hợp kết quả toàn bộ quá trình kiểm thử của Agent 1.
- Xuất Functional Result cho ADLC Orchestrator đánh giá Quality Gate.
"""

from typing import Any, Dict, List, Optional


class FunctionalReporter:
    """Tổng hợp kết quả Functional Testing và đánh giá cổng chất lượng (Quality Gate)."""

    @classmethod
    def compile_functional_result(
        cls,
        run_id: str,
        feature: str,
        total: int,
        passed: int,
        failed: int,
        healing_attempted: int = 0,
        healing_successful: int = 0,
        healing_rejected: int = 0,
        defect_ids: Optional[List[str]] = None,
        initial_passed: Optional[int] = None,
        execution_mode: str = "unknown",
    ) -> Dict[str, Any]:
        """Tổng hợp kết quả kiểm thử chức năng.

        Args:
            run_id: Mã lần chạy
            feature: Tên tính năng kiểm thử
            total: Tổng số test cases
            passed: Số test cases vượt qua (bao gồm sau healing)
            failed: Số test cases thất bại
            healing_attempted: Số lần thử self-heal
            healing_successful: Số lần self-heal thành công (retest PASS)
            healing_rejected: Số proposal bị anti-cheat gate chặn (false repair tiềm năng)
            defect_ids: Danh sách defect IDs phát hiện
            initial_passed: Số TC PASS ngay lần đầu (trước healing) — KPI transparency

        Returns:
            Dict cấu trúc FunctionalResult + healing transparency (RQ2):
            initial_pass_rate, healed_pass_rate, healing_attempts,
            healing_success_rate, false_repair_rate.

            proposal_rejection_rate = rejected / attempted.
            false_repair_rate remains null without an independent ground-truth audit.
        """
        defects = defect_ids or []
        has_critical_defects = len(defects) > 0

        # Trạng thái tổng quan
        if min(total, passed, failed) < 0 or passed + failed != total:
            raise ValueError("Inconsistent result counts")
        if passed == total and total > 0 and not defects and execution_mode in ("local", "sandbox"):
            status = "PASS"
            gate_passed = True
            next_stage = "PERFORMANCE_TESTING"
        elif passed > 0 and failed > 0:
            status = "PARTIAL_FAIL"
            gate_passed = False
            next_stage = "BLOCK" if has_critical_defects else "REVIEW"
        else:
            status = "FAIL"
            gate_passed = False
            next_stage = "BLOCK"
        if execution_mode == "simulated" and not defects and (passed == total or passed == 0):
            status = "SIMULATED"
            gate_passed = False
            next_stage = "BLOCK"

        # KPI transparency (không để healing "che" chất lượng sinh test ban đầu):
        # Ví dụ: Initial 7/10 PASS -> healed 2 -> Final 9/10 PASS
        initial = initial_passed if initial_passed is not None else passed - healing_successful
        healing_success_rate = (
            round(100 * healing_successful / healing_attempted, 1) if healing_attempted else None
        )
        false_repair_rate = (
            round(100 * healing_rejected / healing_attempted, 1) if healing_attempted else 0.0
        )

        return {
            "run_id": run_id,
            "feature": feature,
            "total": total,
            "passed": passed,
            "failed": failed,
            "initial_pass_rate": round(100 * initial / total, 1) if total else None,
            "healed_pass_rate": round(100 * passed / total, 1) if total else None,
            "healing_attempts": healing_attempted,
            "healing_success_rate": healing_success_rate,
            "false_repair_rate": None,
            "proposal_rejection_rate": false_repair_rate,
            "execution_mode": execution_mode,
            "healing": {
                "attempted": healing_attempted,
                "successful": healing_successful,
                "rejected": healing_rejected,
                "success_rate": healing_success_rate,
            },
            "defects": defects,
            "status": status,
            "gate_passed": gate_passed,
            "recommended_next_stage": next_stage,
        }

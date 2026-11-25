"""Retest Manager (Bước 17).

Nhiệm vụ:
- Chạy lại Playwright script sau khi áp dụng Repair Proposal.
- Nếu retest PASS: Accept healing, lưu vào audit log.
- Nếu retest FAIL: Reject repair proposal, chuyển tiếp hoặc dừng theo max_retry.
"""

from typing import Any, Callable, Dict, Optional


class RetestManager:
    """Quản lý vòng lặp retest và xác thực bản sửa chữa."""

    def __init__(self, max_retry: int = 2):
        self.max_retry = max_retry

    def retest_repair(
        self,
        test_case_id: str,
        repair_proposal: Dict[str, Any],
        execute_fn: Callable[[str, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Thực hiện chạy lại script đã sửa và quyết định chấp nhận hay từ chối.

        Args:
            test_case_id: Mã test case
            repair_proposal: Đề xuất sửa đổi từ Tier 1 hoặc Tier 2
            execute_fn: Hàm thực thi runner(test_case_id, repaired_script)

        Returns:
            Dict kết quả Retest và trạng thái ACCEPT/REJECT
        """
        repaired_script = repair_proposal.get("repaired_script", "")
        retest_result = execute_fn(test_case_id, repaired_script)

        is_passed = retest_result.get("status") == "PASS"

        return {
            "test_case_id": test_case_id,
            "retest_status": "PASS" if is_passed else "FAIL",
            "healing_accepted": is_passed,
            "tier_used": repair_proposal.get("tier"),
            "strategy": repair_proposal.get("strategy"),
            "execution_details": retest_result,
        }

"""Defect Reporter (Bước 18 & Bước 19).

Nhiệm vụ:
- Bước 18: Kích hoạt khi Failure Analyzer xác nhận APPLICATION_DEFECT -> STOP SELF-HEALING.
- Bước 19: Xuất báo cáo Defect Report chi tiết cho developer tái hiện và sửa lỗi.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class DefectReporter:
    """Bộ tạo báo cáo lỗi ứng dụng."""

    @classmethod
    def create_defect_report(
        cls,
        function_id: str,
        test_case_id: str,
        expected: str,
        actual: str,
        evidence: Optional[List[str]] = None,
        severity: str = "HIGH",
        environment: str = "staging",
        reproduction_steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Tạo Defect Report chuẩn hóa theo schema.

        Args:
            function_id: Mã chức năng
            test_case_id: Mã test case phát hiện lỗi
            expected: Kết quả kỳ vọng
            actual: Kết quả thực tế quan sát được
            evidence: Danh sách file bằng chứng (screenshot, trace, logs)
            severity: Mức độ nghiêm trọng (BLOCKER, CRITICAL, HIGH, MEDIUM, LOW)
            environment: Môi trường xảy ra lỗi
            reproduction_steps: Các bước tái hiện

        Returns:
            Dict cấu trúc DefectReport
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        defect_id = f"DEFECT-{function_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        return {
            "defect_id": defect_id,
            "function_id": function_id,
            "test_case_id": test_case_id,
            "expected": expected,
            "actual": actual,
            "classification": "APPLICATION_DEFECT",
            "severity": severity,
            "evidence": evidence or ["screenshot.png", "trace.zip"],
            "environment": environment,
            "reproduction_steps": reproduction_steps or [],
            "created_at": now_iso,
        }

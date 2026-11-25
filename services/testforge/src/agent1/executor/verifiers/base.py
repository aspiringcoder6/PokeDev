"""Verifier Contract (Bước 12).

Định nghĩa hợp đồng thống nhất cho mọi tầng xác minh (UI / API / DB):
- VerifierResult: kết quả chuẩn hóa trả về từ mỗi verifier
- BaseVerifier: interface chung, tầng mới (email, queue...) kế thừa và cài đặt verify()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

VALID_VERIFIER_STATUSES = ("PASS", "FAIL", "ERROR", "SKIPPED", "SIMULATED")


@dataclass
class VerifierResult:
    """Kết quả chuẩn của một tầng xác minh."""

    tier: str                     # "UI" | "API" | "DB" | tên tầng mở rộng
    status: str                   # "PASS" | "FAIL" | "SKIPPED"
    reason: str = ""
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "status": self.status,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


class BaseVerifier(ABC):
    """Interface cơ sở cho các tầng xác minh (Bước 12.x)."""

    tier: str = "BASE"

    def verify(
        self,
        execution_result: Optional[Dict[str, Any]] = None,
        verification_strategy: Optional[Dict[str, Any]] = None,
        expected_targets: Optional[Any] = None,
    ) -> VerifierResult:
        """Thực hiện xác minh một tầng, trả về VerifierResult chuẩn.

        Args:
            execution_result: Kết quả thực thi từ PlaywrightExecutor
            verification_strategy: Cấu hình bật/tắt + tham số cho tầng này
            expected_targets: Mục tiêu mong đợi (từ Internal Test Context Bước 3.5)

        Returns:
            VerifierResult
        """
        raise NotImplementedError("Verifier must implement verify()")

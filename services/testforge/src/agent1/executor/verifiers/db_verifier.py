"""DB Verifier (Bước 12.3 — Optional).

Nhiệm vụ:
- Kiểm tra persistence trực tiếp trong database (giải quyết pain point verify thủ công).
- Tách DbConnector interface: chỉ cần cài fetch(query) -> list/dict/int để nối
  SQLAlchemy / psycopg / driver tùy ý, không phụ thuộc engine.

Lưu ý:
- Giai đoạn MVP ưu tiên PostgreSQL qua SQLAlchemy; các DB khác nối qua connector riêng.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .base import BaseVerifier, VerifierResult


class DbConnector(ABC):
    """Interface kết nối database cho DB Verifier."""

    @abstractmethod
    def fetch(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Thực thi query đọc dữ liệu và trả về danh sách bản ghi."""
        raise NotImplementedError


class DbVerifier(BaseVerifier):
    """Tầng xác minh CSDL (12.3)."""

    tier = "DB"

    def __init__(self, connector: Any = None):
        """
        Args:
            connector: Đối tượng cài DbConnector (fetch). None -> DB check luôn SKIPPED.
        """
        self.connector = connector

    def verify(
        self,
        execution_result: Optional[Dict[str, Any]] = None,
        verification_strategy: Optional[Dict[str, Any]] = None,
        expected_targets: Optional[Dict[str, Any]] = None,
    ) -> VerifierResult:
        """Xác minh persistence trong DB.

        Args:
            db_query: Câu truy vấn kiểm tra (e.g. SELECT * FROM users WHERE email = ...)
            expected_count: Số bản ghi mong đợi (mặc định 1)
            db_connector: Connector cài fetch() — không có -> SKIPPED

        Returns:
            VerifierResult tier=DB
        """
        strat = verification_strategy or {}
        enabled = strat.get("enabled", False)
        db_query = (expected_targets or {}).get("query") or strat.get("query")
        params = (expected_targets or {}).get("params", strat.get("params"))

        if not enabled and not db_query:
            return VerifierResult(tier=self.tier, status="SKIPPED", reason="DB verification not requested")

        if not self.connector or not db_query:
            return VerifierResult(tier=self.tier, status="ERROR", reason="Required DB connector or query missing")

        expected_count = int((expected_targets or {}).get("expected_count", strat.get("expected_count", 1)))

        try:
            if hasattr(self.connector, "fetch"):
                rows: List[Dict[str, Any]] = self.connector.fetch(db_query, params) if params is not None else self.connector.fetch(db_query)
            elif callable(self.connector):
                # Backward compatible: connector dạng callable cũ (query) -> list
                rows = self.connector(db_query, params) if params is not None else self.connector(db_query)
            else:
                return VerifierResult(
                    tier=self.tier,
                    status="FAIL",
                    reason="DB connector must implement fetch(query) or be callable",
                    evidence=[db_query],
                )
        except Exception as ex:  # noqa: BLE001 - ghi nhận mọi lỗi connector vào kết quả
            return VerifierResult(
                tier=self.tier,
                status="FAIL",
                reason=f"DB query error: {str(ex)}",
                evidence=[db_query],
            )

        actual_count = len(rows) if isinstance(rows, list) else int(rows)
        if actual_count != expected_count:
            return VerifierResult(
                tier=self.tier,
                status="FAIL",
                reason=f"DB records mismatch: expected {expected_count}, got {actual_count}",
                evidence=[db_query],
            )

        expected_fields = (expected_targets or {}).get("expected_fields", strat.get("expected_fields"))
        if expected_fields is not None:
            from .api_verifier import APIVerifier
            if not isinstance(rows, list) or not rows:
                return VerifierResult(tier=self.tier, status="FAIL", reason="DB field verification requires rows")
            for row in rows:
                check = APIVerifier().verify({"api_response": {"status_code": 200, "body": row}},
                    {"enabled": True, "expected_payload": expected_fields})
                if check.status != "PASS":
                    return VerifierResult(tier=self.tier, status="FAIL", reason="DB field mismatch")

        return VerifierResult(
            tier=self.tier,
            status="PASS",
            reason=f"DB persistence verified ({actual_count} record(s))",
            evidence=[db_query],
        )

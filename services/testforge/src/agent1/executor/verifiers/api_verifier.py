"""API Verifier (Bước 12.2 — Optional).

Nhiệm vụ:
- Kiểm tra response API backend sau khi test case chạy xong.
- So sánh status code (mặc định 200) và (tùy chọn) payload key/value.
- Không có api_response -> SKIPPED.
"""

from typing import Any, Dict, List, Optional

from .base import BaseVerifier, VerifierResult


class APIVerifier(BaseVerifier):
    """Tầng xác minh API (12.2)."""

    tier = "API"

    def verify(
        self,
        execution_result: Optional[Dict[str, Any]] = None,
        verification_strategy: Optional[Dict[str, Any]] = None,
        expected_targets: Optional[Dict[str, Any]] = None,
    ) -> VerifierResult:
        """Xác minh response API.

        Args:
            api_response qua verification_strategy hoặc expected_targets:
                {"enabled": true, "expected_status": 200, "expected_payload": {...}}
            execution_result.api_response: {"status_code": int, "body": {...}}

        Returns:
            VerifierResult tier=API, SKIPPED nếu không yêu cầu
        """
        strat = verification_strategy or {}
        if not strat.get("enabled"):
            return VerifierResult(tier=self.tier, status="SKIPPED", reason="API verification disabled")

        api_response: Optional[Dict[str, Any]] = (execution_result or {}).get("api_response")
        if api_response is None:
            return VerifierResult(tier=self.tier, status="ERROR", reason="Required API response was not captured")

        expected_status = strat.get("expected_status", 200)
        actual_status = api_response.get("status_code")

        if actual_status != expected_status:
            return VerifierResult(
                tier=self.tier,
                status="FAIL",
                reason=f"API status mismatch: expected {expected_status}, got {actual_status}",
                evidence=[f"status_code={actual_status}"],
            )

        # Tùy chọn: đối chiếu payload
        expected_payload: Dict[str, Any] = strat.get("expected_payload") or {}
        body: Dict[str, Any] = api_response.get("body") or {}
        missing = object()
        mismatched: List[str] = []
        def compare(actual, expected, path):
            if isinstance(expected, dict):
                if not isinstance(actual, dict):
                    mismatched.append(f"{path}: expected object")
                    return
                for key, value in expected.items():
                    compare(actual.get(key, missing), value, f"{path}.{key}")
            elif type(actual) is not type(expected) or actual != expected:
                mismatched.append(f"{path}: missing or unexpected value/type")
        compare(body, expected_payload, "body")
        if mismatched:
            return VerifierResult(
                tier=self.tier,
                status="FAIL",
                reason=f"API payload mismatch: {', '.join(mismatched)}",
                evidence=[str(api_response.get("body"))],
            )

        return VerifierResult(
            tier=self.tier,
            status="PASS",
            evidence=[f"status_code={actual_status}"],
        )

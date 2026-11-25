"""UI Verifier (Bước 12.1 — Core MVP).

Nhiệm vụ:
- Đối chiếu kết quả thực thi UI với expected targets.
- MVP: Playwright assertions chạy bên trong script, nên trạng thái UI phụ thuộc
  trực tiếp vào execution_result["status"].
- Khi runtime thật cung cấp observed evidence (observed_texts), đối chiếu thêm
  TEXT_VISIBLE / TEXT_ABSENT từ Internal Test Context (Bước 3.5).
"""

from typing import Any, Dict, List, Optional

from .base import BaseVerifier, VerifierResult


class UIVerifier(BaseVerifier):
    """Tầng xác minh giao diện (12.1)."""

    tier = "UI"

    def verify(
        self,
        execution_result: Optional[Dict[str, Any]] = None,
        verification_strategy: Optional[Dict[str, Any]] = None,
        expected_targets: Optional[List[Dict[str, str]]] = None,
    ) -> VerifierResult:
        """Xác minh kết quả UI.

        Args:
            execution_result: ExecutionResult từ runner
            verification_strategy: {"ui": true/false}
            expected_ui_targets: Danh sách {type: TEXT_VISIBLE|TEXT_ABSENT, value}

        Returns:
            VerifierResult tier=UI
        """
        exec_res = execution_result or {}
        artifacts = exec_res.get("artifacts") or []
        if exec_res.get("status") in ("ERROR", "SKIPPED", "SIMULATED"):
            return VerifierResult(tier=self.tier, status="ERROR" if exec_res["status"] != "SIMULATED" else "SIMULATED", reason=str(exec_res.get("error") or "UI was not executed"))

        # MVP: PASS/FAIL do Playwright assertions quyết định trong script
        ui_pass = exec_res.get("status") == "PASS"
        reason = "" if ui_pass else str(exec_res.get("error") or "UI assertion mismatch")

        # Nếu runtime cung cấp observed texts -> đối chiếu expected targets chi tiết
        observed = exec_res.get("observed_texts")
        if expected_targets and observed is not None:
            for target in expected_targets:
                value = str(target.get("value", ""))
                is_visible = any(value in str(txt) for txt in observed)
                if target.get("type") == "TEXT_VISIBLE" and not is_visible:
                    ui_pass = False
                    reason = f"Expected text not visible: '{value}'"
                elif target.get("type") == "TEXT_ABSENT" and is_visible:
                    ui_pass = False
                    reason = f"Unexpected text is visible: '{value}'"

        return VerifierResult(
            tier=self.tier,
            status="PASS" if ui_pass else "FAIL",
            reason=reason,
            evidence=list(artifacts or []),
        )

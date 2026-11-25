"""Result Verification Engine (Bước 12 & Bước 13) — Orchestrator.

Nhiệm vụ:
- Điều phối 3 tầng xác minh độc lập (mỗi tầng một verifier):
    12.1. UI Verifier  (Core MVP)  -> verifiers/ui_verifier.py
    12.2. API Verifier (Optional)  -> verifiers/api_verifier.py
    12.3. DB Verifier  (Optional)  -> verifiers/db_verifier.py (DbConnector interface)
- Bước 13. Tổng hợp PASS/FAIL:
    Expected == Actual -> PASS
    Expected != Actual -> FAIL
- Giữ nguyên signature verify() cho tương thích ngược với pipeline và tests.
"""

from typing import Any, Dict, List, Optional

from .verifiers.api_verifier import APIVerifier
from .verifiers.base import VerifierResult
from .verifiers.db_verifier import DbVerifier
from .verifiers.ui_verifier import UIVerifier


class VerificationEngine:
    """Bộ điều phối xác minh đa tầng (UI, API, DB)."""

    def __init__(self, db_connector: Optional[Any] = None, verifiers: Optional[List[Any]] = None):
        """Khởi tạo engine với các verifier mặc định hoặc tùy chọn.

        Args:
            db_connector: Đối tượng cài DbConnector.fetch() cho tầng DB (tùy chọn)
            verifiers: Danh sách verifier tùy chỉnh (mặc định: UI + API + DB)
        """
        self.verifiers: List[Any] = verifiers or [
            UIVerifier(),
            APIVerifier(),
            DbVerifier(connector=db_connector),
        ]

    def verify(
        self,
        execution_result: Dict[str, Any],
        verification_strategy: Optional[Dict[str, Any]] = None,
        api_response: Optional[Dict[str, Any]] = None,
        db_query: Optional[str] = None,
        expected_db_count: Optional[int] = None,
        internal_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Điều phối các tầng xác minh và tổng hợp kết quả cuối cùng (Bước 13).

        Args:
            execution_result: Kết quả chạy test từ PlaywrightExecutor
            verification_strategy: {"ui": true, "api": {...}, "db": {...}}
            api_response: Response API thu thập được (tùy chọn)
            db_query: Câu truy vấn DB kiểm tra persistence (tùy chọn)
            expected_db_count: Số bản ghi mong đợi (tùy chọn)
            internal_context: Internal Test Context (Bước 3.5) chứa expected targets

        Returns:
            Dict: {final_status, ui_status, api_status, db_status, reason, results}
        """
        strat = verification_strategy or {"ui": True}

        # Gắn api_response vào execution_result để API Verifier đọc
        exec_res = dict(execution_result or {})
        if api_response is not None:
            exec_res["api_response"] = api_response

        # 12.1 UI — expected targets lấy từ Internal Test Context nếu có
        ui_targets = None
        if internal_context:
            ui_targets = (internal_context.get("verification") or {}).get("ui")
        ui_res = self._run_tier("UI", exec_res, strat, expected_targets=ui_targets)

        # 12.2 API
        api_cfg = dict(strat.get("api") or {})
        api_res = self._run_tier("API", exec_res, api_cfg)

        # 12.3 DB
        db_cfg = dict(strat.get("db") or {})
        db_targets: Dict[str, Any] = {}
        if db_query:
            db_targets["query"] = db_query
            db_cfg["enabled"] = True  # có db_query -> cho phép chạy DB check
        if expected_db_count is not None:
            db_targets["expected_count"] = expected_db_count
        elif db_cfg.get("expected_count") is not None:
            db_targets["expected_count"] = db_cfg["expected_count"]
        db_res = self._run_tier("DB", exec_res, db_cfg, expected_targets=db_targets)

        # Bước 13: PASS/FAIL tổng hợp
        by_tier = {r.tier: r for r in [ui_res, api_res, db_res]}
        failed_tiers = [r for r in [ui_res, api_res, db_res] if r.status in ("FAIL", "ERROR", "SIMULATED")]

        final_status = "ERROR" if any(r.status == "ERROR" for r in failed_tiers) else ("FAIL" if failed_tiers else "PASS")

        reasons: List[str] = []
        if ui_res.status != "PASS":
            reasons.append(f"UI Failed: {ui_res.reason or 'Assertion mismatch'}")
        if api_res.status in ("FAIL", "ERROR"):
            reasons.append("API Failed: status/payload mismatch")
        if db_res.status in ("FAIL", "ERROR"):
            reasons.append(f"DB Failed: records mismatch or query error ({db_res.reason})")

        return {
            "final_status": final_status,
            "ui_status": by_tier["UI"].status,
            "api_status": by_tier["API"].status,
            "db_status": by_tier["DB"].status,
            "reason": "; ".join(reasons) if reasons else "All verification layers passed successfully",
            "results": [r.to_dict() for r in [ui_res, api_res, db_res]],
        }

    # ------------------------------------------------------------------
    # Điều phối nội bộ theo tier
    # ------------------------------------------------------------------
    def _run_tier(
        self,
        tier: str,
        exec_res: Dict[str, Any],
        tier_config: Dict[str, Any],
        expected_targets: Any = None,
    ) -> VerifierResult:
        """Tìm verifier tương ứng tier trong danh sách và thực thi.

        - UI: luôn chạy (core MVP)
        - API/DB: chỉ khi config bật, ngược lại SKIPPED
        """
        verifier = next((v for v in self.verifiers if v.tier == tier), None)
        if verifier is None:
            required = tier == "UI" or tier_config.get("enabled")
            return VerifierResult(tier=tier, status="ERROR" if required else "SKIPPED", reason=f"No verifier registered for {tier}")

        if tier != "UI" and not tier_config.get("enabled"):
            # API/DB không được bật trong strategy -> bỏ qua
            return VerifierResult(tier=tier, status="SKIPPED", reason=f"{tier} verification disabled")

        try:
            result = verifier.verify(execution_result=exec_res, verification_strategy=tier_config, expected_targets=expected_targets)
            if result.status not in ("PASS", "FAIL", "ERROR", "SIMULATED"):
                return VerifierResult(tier=tier, status="ERROR", reason="Required verifier did not execute")
            return result
        except Exception as exc:
            return VerifierResult(tier=tier, status="ERROR", reason=f"Verifier error: {type(exc).__name__}")

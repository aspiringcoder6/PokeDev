"""Self-healing Tầng 1: Deterministic Recovery (Bước 16.1).

Đặc điểm:
- Không dùng LLM.
- Retry có kiểm soát (auto-wait, backoff).
- Fallback danh sách locator đã lưu từ các lần chạy PASS trước.
- Semantic fallback theo role/label/text.
"""

from typing import Any, Dict, List, Optional
from ..generator.locator_policy import LocatorPolicy


class Tier1DeterministicHealer:
    """Tự phục hồi cấp độ 1: Xác định dựa trên quy tắc (Rule-based & History)."""

    def __init__(self, locator_history: Optional[Dict[str, List[str]]] = None):
        """Khởi tạo với lịch sử locator mapping: {element_key: [locators]}."""
        self.locator_history = locator_history or {}

    def attempt_recovery(
        self,
        failed_target: str,
        failed_action: str,
        script_content: str,
    ) -> Optional[Dict[str, Any]]:
        """Thử tìm locator thay thế từ lịch sử hoặc semantic priority.

        Args:
            failed_target: Element gây lỗi
            failed_action: Hành động (CLICK, FILL, ...)
            script_content: Nội dung script hiện tại

        Returns:
            Dict chứa repair proposal hoặc None nếu không tìm được
        """
        # 1. Kiểm tra lịch sử locator thay thế
        known_alternatives = self.locator_history.get(failed_target, [])
        for alt in known_alternatives:
            if alt not in script_content:
                return {
                    "tier": 1,
                    "strategy": "KNOWN_LOCATOR_FALLBACK",
                    "old_target": failed_target,
                    "new_locator": alt,
                    "confidence": 0.95,
                    "repaired_script": script_content.replace(failed_target, alt),
                }

        # 2. Semantic fallback theo locator policy
        fallback_loc = LocatorPolicy.generate_locator(failed_target, strategy_preference="TEXT")
        if fallback_loc not in script_content:
            return {
                "tier": 1,
                "strategy": "SEMANTIC_TEXT_FALLBACK",
                "old_target": failed_target,
                "new_locator": fallback_loc,
                "confidence": 0.80,
                "repaired_script": script_content.replace(f"getByRole('button', {{ name: '{failed_target}' }})", fallback_loc),
            }

        return None

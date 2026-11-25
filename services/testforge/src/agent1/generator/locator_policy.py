"""Locator Strategy & Priority Policy (Bước 8).

Quy tắc ưu tiên:
1. getByRole: Semantic, accessibility-friendly
2. getByLabel: Form controls
3. getByText: Text content
4. getByTestId: Test attributes
5. CSS: Class / attribute selectors
6. XPath: Last resort
"""

from typing import Dict, List, Optional


class LocatorPolicy:
    """Quản lý và sinh locator code theo chính sách ưu tiên semantic."""

    PRIORITY_LEVELS = [
        "ROLE",      # Priority 1
        "LABEL",     # Priority 2
        "TEXT",      # Priority 3
        "TESTID",    # Priority 4
        "CSS",       # Priority 5
        "XPATH",     # Priority 6
    ]

    @classmethod
    def generate_locator(
        cls,
        target: str,
        role: Optional[str] = None,
        strategy_preference: Optional[str] = None,
    ) -> str:
        """Sinh Playwright locator code dựa trên target text/selector và role.

        Args:
            target: Chuỗi mô tả hoặc selector của element
            role: Tùy chọn vai trò ARIA (button, link, textbox, heading)
            strategy_preference: Ép dùng chiến lược cụ thể (dùng khi self-healing fallback)

        Returns:
            Chuỗi mã nguồn Playwright locator (e.g. `page.getByRole('button', { name: 'Save' })`)
        """
        strat = strategy_preference or cls._infer_best_strategy(target, role)

        if strat == "XPATH" or target.startswith("//") or target.startswith("(//"):
            return f"page.locator('{target}')"

        if strat == "CSS" or target.startswith(".") or target.startswith("#") or "[" in target:
            return f"page.locator('{target}')"

        if strat == "TESTID" or target.startswith("data-testid="):
            clean_id = target.replace("data-testid=", "").strip("'\"")
            return f"page.getByTestId('{clean_id}')"

        # Ép chiến lược cụ thể khi caller yêu cầu (self-healing fallback / form fields)
        if strategy_preference == "LABEL":
            clean_name = target.replace(" field", "").replace(" Field", "").strip()
            return f"page.getByLabel('{clean_name or target}')"

        if strategy_preference == "TEXT":
            return f"page.getByText('{target}')"

        if strat == "ROLE" and role:
            return f"page.getByRole('{role}', {{ name: '{target}' }})"

        # Phân tích target để đoán role
        target_lower = target.lower()
        button_keywords = [
            "button", "btn", "submit", "save", "add", "delete", "login",
            "search", "update", "edit", "logout", "register", "send",
        ]
        if any(b in target_lower for b in button_keywords):
            clean_name = target.replace("Button", "").replace("button", "").strip()
            return f"page.getByRole('button', {{ name: '{clean_name or target}' }})"

        if any(f in target_lower for f in ["field", "input", "email", "password", "username", "name"]):
            clean_name = target.replace("field", "").replace("Field", "").strip()
            return f"page.getByLabel('{clean_name or target}')"

        # Mặc định ưu tiên getByText
        return f"page.getByText('{target}')"

    @classmethod
    def _infer_best_strategy(cls, target: str, role: Optional[str]) -> str:
        """Suy luận chiến lược tối ưu nhất."""
        if target.startswith("//"):
            return "XPATH"
        if target.startswith(".") or target.startswith("#") or ("[" in target and "]" in target):
            return "CSS"
        if "data-testid" in target:
            return "TESTID"
        if role:
            return "ROLE"
        return "TEXT"

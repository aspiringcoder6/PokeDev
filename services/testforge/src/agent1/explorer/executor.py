"""Chạy StepDecision bằng Playwright high-level APIs với timeout bounded.

Locator luôn dựng từ element đã ground trên ARIA snapshot (role + name, exact) —
không bao giờ CSS/XPath tự chế. Đây là điều kiện để spec tổng hợp (G2) replay được.
"""
from .session import DeviationError
from .grounding import CLICK_ROLES, INPUT_ROLES


class DecisionExecutor:
    def execute(self, driver, decision, chosen, timeout_ms):
        """chosen: {role, name} từ grounding (hoặc {kind: css/text} từ HITL) — None với OPEN/ASSERT."""
        page = driver.page
        action = decision.selected_action
        if action == "OPEN":
            page.goto(decision.value or decision.target, timeout=timeout_ms)
            try:
                # SPA render async sau load — chờ mạng lặng để ARIA snapshot phản ánh UI thật
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                page.wait_for_timeout(300)
            except Exception:
                pass
        elif action in ("CLICK", "SUBMIT"):
            self._guard(chosen, CLICK_ROLES, action)
            self._locator(page, chosen).click(timeout=timeout_ms)
            # modal/dialog có animation ~300ms + render -> 400ms không đủ ổn định
            self._settle(page, timeout_ms, ms=800)
        elif action == "FILL":
            self._guard(chosen, INPUT_ROLES, action)
            self._locator(page, chosen).fill(decision.value, timeout=timeout_ms)
            self._settle(page, timeout_ms)
        elif action == "SELECT":
            self._guard(chosen, INPUT_ROLES, action)
            self._locator(page, chosen).select_option(decision.value, timeout=timeout_ms)
            self._settle(page, timeout_ms)
        elif action == "PRESS":
            # Nhấn phím Enter (ví dụ kích hoạt tìm kiếm trong ô đã FILL) — không cần element
            page.keyboard.press("Enter")
            self._settle(page, timeout_ms, ms=800)
        elif action == "ASSERT":
            self.assert_visible(page, decision.target, timeout_ms,
                                expect_absent=decision.value == "absent")
        else:
            raise ValueError("Unsupported action: {0}".format(action))

    @staticmethod
    def _locator(page, chosen):
        kind = chosen.get("kind", "role")
        if kind == "css":
            return page.locator(chosen["value"]).first
        if kind == "text":
            return page.get_by_text(chosen["value"]).first
        return page.get_by_role(chosen["role"], name=chosen["name"], exact=True).first

    @staticmethod
    def _settle(page, timeout_ms, ms=400):
        """UI cập nhật async sau action (modal mở, list refetch) — chờ ngắn trước khi
        snapshot cho step kế được capture, tránh grounding trên UI cũ."""
        try:
            page.wait_for_timeout(ms)
        except Exception:
            pass

    @staticmethod
    def _guard(chosen, allowed, action):
        if chosen is None:
            raise ValueError(
                "Grounding mismatch for {0}: no locator resolved".format(action))
        if chosen.get("kind", "role") != "role":
            return
        if chosen.get("role") not in allowed:
            raise ValueError(
                "Grounding mismatch for {0}: target is not an interactive element".format(action))

    @staticmethod
    def assert_visible(page, text, timeout_ms, expect_absent=False):
        try:
            locator = page.get_by_text(text).first
            if expect_absent:
                if locator.is_visible():
                    raise AssertionError("Text is still visible: {0}".format(text))
                return
            locator.wait_for(state="visible", timeout=timeout_ms)
        except AssertionError:
            raise
        except Exception as exc:
            raise DeviationError("ASSERT failed: '{0}' not visible".format(text)) from exc

"""Step -> action decision. Deterministic pattern first, LLM only as fallback.

StepDecision chỉ là ĐỀ XUẤT điều hướng (intent->action). Nó không phải oracle:
executor vẫn phải ground trên ARIA snapshot thật trước khi chạy action.
"""
import re
from dataclasses import dataclass

from src.agent1.explorer.grounding import parse_snapshot, prune_snapshot
from src.agent1.healer.llm_client import OpenCodeChatClient, extract_json_object

ALLOWED_ACTIONS = {"OPEN", "CLICK", "FILL", "SELECT", "SUBMIT", "ASSERT", "PRESS"}


class NavigationError(Exception):
    """Không navigator nào map được step — explorer phải FAIL, không được đoán."""


@dataclass
class StepDecision:
    selected_action: str
    target: str = ""
    value: str = ""
    reasoning: str = ""
    source: str = "pattern"


class PatternNavigator:
    """Deterministic intent extraction từ step text có giá trị quoted."""

    _PATTERNS = [
        (re.compile(r'open\s+"([^"]+)"', re.IGNORECASE), "OPEN"),
        (re.compile(r'fill\s+"([^"]+)"\s+with\s+empty', re.IGNORECASE), "FILL_EMPTY"),
        (re.compile(r'fill\s+"([^"]+)"\s+with\s+"([^"]*)"', re.IGNORECASE), "FILL"),
        (re.compile(r'type\s+"([^"]*)"\s+into\s+"([^"]+)"', re.IGNORECASE), "TYPE_INTO"),
        (re.compile(r'click\s+"([^"]+)"', re.IGNORECASE), "CLICK"),
        (re.compile(r'press\s+"([^"]+)"', re.IGNORECASE), "CLICK"),
        # Phím Enter (thường sau FILL ô tìm kiếm) — phải khớp trước CLICK "press x"
        (re.compile(r'press\s+(?:the\s+)?enter(?:\s+key)?|nhấn\s+(?:phím\s+)?enter|ấn\s+enter|bấm\s+enter', re.IGNORECASE), "PRESS"),
        (re.compile(r'should\s+(?:not\s+see|not\s+expect)\s+"([^"]+)"', re.IGNORECASE), "ASSERT_ABSENT"),
        (re.compile(r'should\s+(?:see|expect)\s+"([^"]+)"', re.IGNORECASE), "ASSERT"),
        (re.compile(r'i\s+expect\s+"([^"]+)"', re.IGNORECASE), "ASSERT"),
    ]

    # "Nhấn xem 1 bản ghi trong danh sách" — không có quoted value, quyết định
    # trên snapshot thật (dòng dữ liệu đầu tiên) để không phụ thuộc LLM.
    _RECORD_INTENT = re.compile(
        r'(?:xem|nhấn|ấn|bấm|chọn|mở)\s+(?:vào\s+)?(?:1|một|one)?\s*bản\s+ghi'
        r'|(?:click|view|open|select)\s+(?:on\s+)?(?:a|the)\s+record',
        re.IGNORECASE)

    def propose(self, step_text, aria_snapshot, current_url):
        for pattern, action in self._PATTERNS:
            match = pattern.search(step_text)
            if not match:
                continue
            if action == "OPEN":
                return StepDecision("OPEN", value=match.group(1), source="pattern")
            if action == "FILL":
                return StepDecision("FILL", target=match.group(1), value=match.group(2), source="pattern")
            if action == "FILL_EMPTY":
                return StepDecision("FILL", target=match.group(1), value="", source="pattern")
            if action == "TYPE_INTO":
                return StepDecision("FILL", target=match.group(2), value=match.group(1), source="pattern")
            if action == "CLICK":
                return StepDecision("CLICK", target=match.group(1), source="pattern")
            if action == "PRESS":
                return StepDecision("PRESS", target="Enter", source="pattern")
            if action == "ASSERT_ABSENT":
                return StepDecision("ASSERT", target=match.group(1), value="absent", source="pattern")
            return StepDecision("ASSERT", target=match.group(1), source="pattern")
        if self._RECORD_INTENT.search(step_text):
            target = self._first_record_target(aria_snapshot)
            if target:
                return StepDecision("CLICK", target=target, source="pattern")
        return None

    @staticmethod
    def _first_record_target(aria_snapshot):
        """Tên ARIA của dòng dữ liệu đầu tiên trong bảng (không phải header).

        Bảng enterprise VN (ng-vts/antd): header row gộp tên cột (bắt đầu 'STT'),
        dòng dữ liệu bắt đầu bằng số thứ tự. Bỏ qua cả dòng 'Không có dữ liệu'.
        """
        rows = [e for e in parse_snapshot(aria_snapshot or "")
                if e["role"] == "row" and e["name"].strip()]
        data_rows = [r for r in rows
                     if not r["name"].strip().upper().startswith("STT")
                     and "không có dữ liệu" not in r["name"].lower()
                     and "no data" not in r["name"].lower()]
        if not data_rows:
            return ""
        numbered = [r for r in data_rows if r["name"].strip()[:1].isdigit()]
        return (numbered or data_rows)[0]["name"].strip()


class LLMNavigator:
    """LLM fallback cho step không khớp pattern. Không key -> propose trả None."""

    SYSTEM_PROMPT = (
        "You map ONE Gherkin step (possibly written in natural language) to ONE browser action. "
        "Decide by ACTION TYPE first:\n"
        "- opening/navigating to a page -> OPEN (value = URL)\n"
        "- typing a value into a field -> FILL (target = the field's accessible name in the snapshot; "
        "value = the text to type, usually the quoted string in the step)\n"
        "- activating a control (button/link) -> CLICK (target = its accessible name)\n"
        "- pressing the Enter key (often to trigger search) -> PRESS (target = \"Enter\", no element needed)\n"
        "- verifying text is visible -> ASSERT (target = the exact text)\n"
        "Rules:\n"
        "1. target MUST be copied verbatim from an accessible name in the ARIA snapshot "
        "(keep any trailing '*' of required fields).\n"
        "2. A search/filter box is NOT a form field: if the step asks to enter a VALUE into a form "
        "(name, key, email...), pick the form textbox inside the dialog, never a search box.\n"
        "3. Never invent elements that are absent from the snapshot.\n"
        "4. If the form/dialog the step refers to is ALREADY open (its fields are visible in the "
        "snapshot), act on the step directly: FILL the field it names. Do NOT click the "
        "open/new button again.\n"
        "5. A confirm/save/create step means SUBMIT: pick the submit button INSIDE the same "
        "dialog as the fields that were just filled.\n"
        "Respond with ONLY a JSON object:\n"
        '{"action": "OPEN|CLICK|FILL|SELECT|SUBMIT|ASSERT|PRESS", '
        '"target": "<accessible name for CLICK/FILL/SELECT, or expected visible text for ASSERT, or \"Enter\" for PRESS>", '
        '"value": "<URL for OPEN, text to type for FILL, empty otherwise>", '
        '"reasoning": "<one short sentence>"}'
    )
    MAX_SNAPSHOT_CHARS = 24000

    def __init__(self, client=None):
        self.client = client or OpenCodeChatClient()

    def propose(self, step_text, aria_snapshot, current_url):
        if not self.client.available():
            return None
        snapshot = prune_snapshot(aria_snapshot, self.MAX_SNAPSHOT_CHARS)
        user_prompt = "Step: {0}\nCurrent URL: {1}\nARIA snapshot:\n{2}".format(
            step_text, current_url, snapshot)
        # Gateway free-tier đôi lúc lỗi tạm thời: thử tối đa 2 lần trước khi bỏ qua
        for _ in range(2):
            content = self.client.chat(self.SYSTEM_PROMPT, user_prompt)
            data = extract_json_object(content)
            if data:
                break
        if not data:
            return None
        action = str(data.get("action", "")).upper().strip()
        if action not in ALLOWED_ACTIONS:
            return None
        return StepDecision(
            selected_action=action,
            target=str(data.get("target", "")).strip(),
            value=str(data.get("value", "")).strip(),
            reasoning=str(data.get("reasoning", "")).strip(),
            source="llm",
        )


class CompositeNavigator:
    """Thử từng navigator theo thứ tự; cái đầu trả quyết định thắng."""

    def __init__(self, navigators):
        self._navigators = list(navigators)

    def propose(self, step_text, aria_snapshot, current_url):
        for navigator in self._navigators:
            decision = navigator.propose(step_text, aria_snapshot, current_url)
            if decision is not None:
                return decision
        raise NavigationError("No navigation decision for step: {0}".format(step_text))

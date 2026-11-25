"""Self-healing Tầng 2: AI/Heuristic Recovery (Bước 16.2) — v2 evidence-based.

Ngày 2 (M3.2): heuristic DỰA TRÊN EVIDENCE (dom_probe), chưa dùng LLM:
- Parse failed locator từ error ("waiting for getByTestId('x')" / "getByRole(... name 'y')")
- Chọn candidate từ dom_probe (chỉ element VISIBLE):
    A. testid chứa token của locator hỏng   (C01: 'Save' button sau khi testid drift)
    B. text chứa token                       (C02: nút "Lưu" giữ testid save-user)
- Hidden element (C03): đề xuất TĂNG action timeout (không đổi locator) —
  element tồn tại, chỉ là delayed visibility
- exclude_locators: bỏ các locator đã thử và retest FAIL (graph truyền vào)

Bất biến (guardrail):
- KHÔNG BAO GIỜ sửa/bỏ assertion, không đổi expected oracle
- Action ASSERT -> luôn None
- Proposal chưa được coi là thành công cho đến khi retest PASS (graph đảm bảo)
- LLM client (Ngày 3) sẽ THAY heuristic chọn candidate, không thay guardrail
"""

import json
import re
from typing import Any, Dict, List, Optional

from .llm_client import extract_json_object


class Tier2AIRecovery:
    """Tự phục hồi cấp độ 2: sửa locator dựa trên DOM probe evidence."""

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client  # Ngày 3: OpenCode client (ChatOpenAI pattern)

    def generate_repair_proposal(
        self,
        test_case: Dict[str, Any],
        failed_step: int,
        error_message: str,
        ui_evidence: Optional[Dict[str, Any]],
        script_content: str,
        exclude_locators: Optional[list] = None,
    ) -> Optional[Dict[str, Any]]:
        """Sinh repair proposal: LLM (nếu cấu hình) -> fallback heuristic evidence-based.

        Bất biến: LLM KHÔNG thay guardrail — proposal vẫn phải qua validate gate
        (SV rules + assertion count + oracle intact) và retest PASS mới được chấp nhận.

        Returns: proposal dict hoặc None (không có evidence đủ tin / guardrail chặn).
            exclude_locators: Các locator đã thử và retest FAIL (tránh vòng lặp)
        """
        steps = test_case.get("steps") or []
        if failed_step > len(steps) or failed_step < 1:
            return None
        step = steps[failed_step - 1]

        # Guardrail tuyệt đối: không sửa assertion oracle
        if step.get("action") == "ASSERT":
            return None

        # Ưu tiên LLM (Ngày 3) — fail/parse lỗi/garbage -> fallback heuristic
        llm_proposal = None
        if self.llm_client is not None:
            llm_proposal = self._propose_with_llm(
                test_case, failed_step, error_message, ui_evidence, script_content, exclude_locators
            )
            if llm_proposal:
                return llm_proposal

        probe = (ui_evidence or {}).get("dom_probe") or []
        if not probe:
            return None

        match = re.search(
            r"waiting for (getByTestId|getByRole|getByLabel|getByText)\((.+?)\)",
            error_message or "",
        )
        if not match:
            return None
        kind, raw_arg = match.group(1), match.group(2)
        value_match = re.search(r"name:\s*'([^']+)'", raw_arg) or re.search(r"'([^']+)'", raw_arg)
        if not value_match:
            return None
        value = value_match.group(1)
        token = (value.split("-")[0] if kind.lower() == "getbytestid" else value).lower().strip()
        if not token:
            return None

        exclude = set(exclude_locators or [])

        # Ưu tiên 1: hidden element tồn tại khớp token hoặc step timeout quá ngắn (delayed visibility)
        hidden_target = self._find_hidden_target(probe, token)
        step_timeout = step.get("timeout_ms")
        if hidden_target is not None or (step_timeout and int(step_timeout) <= 1000):
            timeout_proposal = self._propose_extended_timeout(test_case, failed_step, script_content)
            if timeout_proposal:
                return timeout_proposal

        # Ưu tiên 2: ứng viên visible khớp token -> sửa locator
        candidates = self._rank_candidates(probe, token, exclude)
        if not candidates:
            return None

        locator_kind, identifier, confidence = candidates[0]
        new_loc = self._to_locator(locator_kind, identifier)
        match_check = re.search(
            r"waiting for (getByTestId|getByRole|getByLabel|getByText)\((.+?)\)",
            error_message or "",
        )
        repaired = self._replace_old_locator(script_content, match_check.group(1),
                                             match_check.group(2), new_loc) \
            if match_check else script_content
        if repaired == script_content:
            return None

        return {
            "tier": 2,
            "strategy": "DOM_PROBE_SEMANTIC_REPAIR" if locator_kind in ("testid", "role") else "DOM_PROBE_TEXT_FALLBACK",
            "failed_step": failed_step,
            "old_target": value,
            "new_locator": new_loc,
            "alternative_locators": [self._to_locator(k, i) for k, i, _ in candidates[1:]],
            "confidence": confidence,
            "reasoning": f"DOM probe found matching element ({locator_kind}='{identifier}') for failed '{value}'",
            "repaired_script": repaired,
        }

    # ------------------------------------------------------------------
    # LLM path (Ngày 3)
    # ------------------------------------------------------------------
    LLM_SYSTEM_PROMPT = (
        "You are a strict test-automation repair assistant for Playwright scripts.\n"
        "You receive: the failing step (action + target), the Playwright error, a DOM probe "
        "(list of interactive elements: tag/text/testid/visible), the failing code line, and "
        "locators already tried and failed.\n"
        "Reply with ONLY a JSON object, no prose:\n"
        '{"strategy": "replace_locator" | "extend_wait", '
        '"new_locator": "page.getByRole(...)" (only for replace_locator), '
        '"new_timeout_ms": <int> (only for extend_wait), '
        '"confidence": <0..1>, "reasoning": "<one sentence>"}\n'
        "Hard rules you MUST obey:\n"
        "1. NEVER modify, weaken, or remove assertions or expected results.\n"
        "2. new_locator must be a single valid Playwright locator expression starting with 'page.' "
        "(getByRole, getByLabel, getByTestId, getByText, locator).\n"
        "3. Never suggest changing business expected outcomes.\n"
        "4. If evidence is insufficient, reply {\"strategy\": \"give_up\"}."
    )

    def _propose_with_llm(
        self,
        test_case: Dict[str, Any],
        failed_step: int,
        error_message: str,
        ui_evidence: Optional[Dict[str, Any]],
        script_content: str,
        exclude_locators: Optional[list],
    ) -> Optional[Dict[str, Any]]:
        """Gọi LLM sinh proposal; parse + kiểm tra; None -> fallback heuristic."""
        steps = test_case.get("steps") or []
        step = steps[failed_step - 1]
        probe = (ui_evidence or {}).get("dom_probe") or []

        failing_line = ""
        lines = script_content.splitlines()
        marker = f"// Step {failed_step}:"
        for i, line in enumerate(lines):
            if marker in line:
                failing_line = "\n".join(lines[i:i + 2])
                break

        user_prompt = (
            f"Failing step {failed_step}: action={step.get('action')} target='{step.get('target')}'\n"
            f"Playwright error:\n{error_message[:600]}\n\n"
            f"DOM probe:\n{json.dumps(probe[:20], ensure_ascii=False)}\n\n"
            f"Failing code:\n{failing_line}\n\n"
            f"Locators already tried and FAILED (do not repeat): {list(exclude_locators or [])}\n"
        )
        raw = self.llm_client.chat(self.LLM_SYSTEM_PROMPT, user_prompt)
        parsed = extract_json_object(raw)
        if not parsed:
            return None

        strategy = (parsed.get("strategy") or "").strip()
        confidence = parsed.get("confidence", 0.6)
        try:
            confidence = max(0.0, min(float(confidence), 1.0))
        except (TypeError, ValueError):
            confidence = 0.6
        reasoning = str(parsed.get("reasoning") or "")[:200]

        # Strategy 1: extend_wait (element tồn tại nhưng ẩn — C03)
        if strategy == "extend_wait":
            return self._apply_extended_wait(
                test_case, failed_step, script_content, parsed.get("new_timeout_ms"), confidence, reasoning
            )

        # Strategy 2: replace_locator
        match = re.search(
            r"waiting for (getByTestId|getByRole|getByLabel|getByText)\((.+?)\)",
            error_message or "",
        )
        if not match:
            return None
        new_locator = str(parsed.get("new_locator") or "").strip()
        if strategy != "replace_locator" or not new_locator:
            return None
        if new_locator in (exclude_locators or []):
            return None
        # Guardrail cứng trước khi build repaired script
        if not new_locator.startswith("page.") or "expect(" in new_locator or "goto(" in new_locator:
            return None
        repaired = self._replace_old_locator(script_content, match.group(1),
                                             match.group(2), new_locator)
        if repaired == script_content:
            return None
        return {
            "tier": 2,
            "strategy": "LLM_LOCATOR_REPAIR",
            "failed_step": failed_step,
            "old_target": self._old_locator_expr(match.group(1), match.group(2)) or match.group(2),
            "new_locator": new_locator,
            "confidence": confidence,
            "reasoning": reasoning or "LLM locator repair",
            "repaired_script": repaired,
        }

    def _apply_extended_wait(
        self, test_case, failed_step, script_content, new_timeout_ms, confidence, reasoning
    ) -> Optional[Dict[str, Any]]:
        step = test_case["steps"][failed_step - 1]
        old_ms = step.get("timeout_ms")
        if not old_ms:
            return None
        try:
            new_ms = int(new_timeout_ms) if new_timeout_ms else max(int(old_ms) * 8, 5000)
        except (TypeError, ValueError):
            new_ms = max(int(old_ms) * 8, 5000)
        new_ms = min(new_ms, 25000)
        old_expr = f"timeout: {int(old_ms)}"
        if old_expr not in script_content:
            return None
        return {
            "tier": 2,
            "strategy": "LLM_WAIT_EXTENSION",
            "failed_step": failed_step,
            "old_locator": None,
            "new_locator": f"timeout {old_ms}ms -> {new_ms}ms",
            "confidence": confidence,
            "reasoning": reasoning or f"Element exists but hidden; extend wait to {new_ms}ms",
            "repaired_script": script_content.replace(old_expr, f"timeout: {new_ms}", 1),
        }

    # ------------------------------------------------------------------
    def _rank_candidates(self, probe, token: str, exclude: set):
        """Sắp xếp ứng viên: (locator_kind, identifier, confidence)."""
        ranked = []
        for p in probe:
            if not p.get("visible", True):
                continue
            tid = (p.get("testid") or "").lower()
            text = (p.get("text") or "").lower()
            entries = []
            if tid and token in tid:
                entries.append(("testid", p["testid"], 0.85))
            elif text and token in text:
                if (p.get("tag") or "") == "button":
                    entries.append(("role", p["text"], 0.82))
                else:
                    entries.append(("text", p["text"], 0.7))
            for e in entries:
                loc = self._to_locator(e[0], e[1])
                if loc not in exclude:
                    ranked.append(e)
        # ưu tiên confidence cao trước
        ranked.sort(key=lambda e: -e[2])
        return ranked

    @staticmethod
    def _find_hidden_target(probe, token: str):
        for p in probe:
            if not p.get("visible", True):
                text = (p.get("text") or "").lower()
                tid = (p.get("testid") or "").lower()
                if token in text or token in tid:
                    return p
        return None

    def _propose_extended_timeout(self, test_case, failed_step, script_content) -> Optional[Dict[str, Any]]:
        """C03: element tồn tại nhưng ẩn (delayed visibility) -> tăng action timeout."""
        step = test_case["steps"][failed_step - 1]
        timeout_ms = step.get("timeout_ms")
        if not timeout_ms:
            return None
        new_timeout = max(int(timeout_ms) * 8, 5000)
        old_expr = f"timeout: {int(timeout_ms)}"
        if old_expr not in script_content:
            return None
        return {
            "tier": 2,
            "strategy": "ACTIONABILITY_WAIT_EXTENSION",
            "failed_step": failed_step,
            "old_locator": None,
            "new_locator": f"timeout {timeout_ms}ms -> {new_timeout}ms",
            "confidence": 0.8,
            "reasoning": f"Element exists but hidden at failure time; extend wait to {new_timeout}ms",
            "repaired_script": script_content.replace(old_expr, f"timeout: {new_timeout}", 1),
        }

    @staticmethod
    def _old_locator_expr(kind: str, raw_arg: str) -> str:
        kind_l = kind.lower()
        if kind_l == "getbytestid":
            value = re.search(r"'([^']+)'", raw_arg)
            return f"page.getByTestId('{value.group(1)}')" if value else ""
        if kind_l == "getbyrole":
            value = re.search(r"name:\s*'([^']+)'", raw_arg)
            if not value:
                return ""
            return f"page.getByRole('button', {{ name: '{value.group(1)}' }})"
        if kind_l == "getbylabel":
            value = re.search(r"'([^']+)'", raw_arg)
            return f"page.getByLabel('{value.group(1)}')" if value else ""
        if kind_l == "getbytext":
            value = re.search(r"'([^']+)'", raw_arg)
            return f"page.getByText('{value.group(1)}')" if value else ""
        return ""

    @staticmethod
    def _replace_old_locator(script_content: str, kind: str, raw_arg: str, new_locator: str) -> str:
        """Thay locator cũ 1 lần, chấp nhận biến thể { name: 'X', exact: true } (spec explorer).

        Fallback chuỗi literal nếu regex không khớp — giữ tương thích spec generator cũ.
        """
        value_match = re.search(r"name:\s*'([^']+)'", raw_arg) or re.search(r"'([^']+)'", raw_arg)
        if not value_match:
            return script_content
        value = re.escape(value_match.group(1))
        kind_l = (kind or "").lower()
        if kind_l == "getbyrole":
            role_match = re.search(r"getByRole\('([a-z]+)'", raw_arg, re.IGNORECASE)
            role = role_match.group(1) if role_match else "button"
            pattern = r"page\.getByRole\('{0}', \{{[^}}]*name: '{1}'[^}}]*\}}\)".format(
                re.escape(role), value)
        elif kind_l == "getbytestid":
            pattern = r"page\.getByTestId\('{0}'\)".format(value)
        elif kind_l == "getbylabel":
            pattern = r"page\.getByLabel\('{0}'\)".format(value)
        elif kind_l == "getbytext":
            pattern = r"page\.getByText\('{0}'\)".format(value)
        else:
            return script_content
        replaced = re.sub(pattern, lambda _m: new_locator, script_content, count=1)
        if replaced != script_content:
            return replaced
        old_expr = Tier2AIRecovery._old_locator_expr(kind, raw_arg)
        if old_expr and old_expr in script_content:
            return script_content.replace(old_expr, new_locator, 1)
        return script_content

    @staticmethod
    def _to_locator(kind: str, identifier: str) -> str:
        if kind == "testid":
            return f"page.getByTestId('{identifier}')"
        if kind == "role":
            return f"page.getByRole('button', {{ name: '{identifier}' }})"
        return f"page.getByText('{identifier}')"

"""Gherkin Input Parser (Bước 0 — Gherkin In, Results Out).

Học từ kiến trúc TestZeus Hercules: tester viết Gherkin chuẩn ngành, hệ thống
tự chuyển thành Standard Test Input (5 trường) cho pipeline 20 bước.

Khác biệt so với Hercules (dẫn theo docs của họ):
- Hercules xử lý Gherkin như "prose cho LLM" (regex split scenario, LLM tự đoán).
- TestForge parse DETERMINISTIC (Zero-LLM): mỗi scenario -> 1 function context
  hợp lệ ngay trước khi đụng LLM; Scenario Outline + Examples được expand
  bằng biến <placeholder> — không để LLM tự chế test data.

Mapping (Bước 0 -> Bước 3):
- Feature: <name>                          -> feature
- Background: Given ...                    -> precondition (mọi scenario kế thừa)
- Scenario/Scenario Outline: <title>       -> function_id FUNC-<SLUG>
- Given ...                                -> precondition
- When/Then/And/But ...                    -> steps (canonical text)
- Then I should see "<text>"               -> expected_result (oracle contract)
- Examples: | col |                        -> expand <col> placeholders (Outline)

Structured steps được phát sinh theo định dạng canonical mà InputNormalizer
hiểu sẵn: "Open X", "Fill Field 'value'", "Click Save", "Wait N seconds".
"""

import re
from typing import Any, Dict, List, Optional

SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")
QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")


class GherkinParser:
    """Parser Gherkin deterministic -> Standard Test Input per scenario."""

    STEP_KEYWORDS = ("given", "when", "then", "and", "but")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, gherkin_text: str) -> List[Dict[str, Any]]:
        """Parse văn bản .feature thành danh sách scenario.

        Returns:
            Mỗi scenario: {
                "function_id", "feature", "scenario", "tags",
                "precondition", "steps", "expected_result",
                "structured_steps", "test_data", "source_text"
            }
        """
        lines = cls._clean_lines(gherkin_text or "")
        feature_name = ""
        background: Dict[str, Any] = {"precondition": [], "steps": []}
        scenarios: List[Dict[str, Any]] = []
        tags: List[str] = []

        idx = 0
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()

            if stripped.startswith("@"):
                tags.extend(t for t in stripped[1:].split() if t)
                idx += 1
                continue

            if stripped.lower().startswith("feature:"):
                feature_name = stripped.split(":", 1)[1].strip()
                idx += 1
                continue

            if stripped.lower().startswith("background:"):
                block, idx = cls._read_block(lines, idx + 1)
                bg = cls._parse_step_block(block)
                background["precondition"] = bg["given"]
                background["steps"] = bg["when_then"]
                continue

            if stripped.lower().startswith(("scenario:", "scenario outline:")):
                is_outline = stripped.lower().startswith("scenario outline:")
                title = stripped.split(":", 1)[1].strip()
                block, idx = cls._read_block(lines, idx + 1)
                steps_block, examples = cls._split_examples(block)
                parsed = cls._parse_step_block(steps_block)

                scenarios.append({
                    "function_id": cls._slug(f"{feature_name or 'Feature'}-{title}"),
                    "feature": feature_name or title,
                    "scenario": title,
                    "tags": list(tags),
                    "precondition": background["precondition"] + parsed["given"],
                    "steps": background["steps"] + parsed["when_then"],
                    "expected_result": parsed["then"],
                    "structured_steps": background["steps"] + parsed["structured"],
                    "examples": examples if is_outline else [],
                    "source_text": "\n".join(block),
                })
                tags = []
                continue

            idx += 1

        # Scenario Outline: expand Examples -> mỗi row một scenario độc lập
        expanded: List[Dict[str, Any]] = []
        for sc in scenarios:
            if not sc["examples"]:
                expanded.append(sc)
                continue
            for row_no, row in enumerate(sc["examples"], start=1):
                expanded.append(cls._expand_outline(sc, row, row_no))
        return expanded

    # ------------------------------------------------------------------
    # Line-level helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _clean_lines(text: str) -> List[str]:
        lines = []
        for raw in text.splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(stripped)
        return lines

    @staticmethod
    def _read_block(lines: List[str], start: int) -> tuple:
        """Đọc block cho tới keyword cấu trúc tiếp theo (Feature/Background/Scenario/Examples)."""
        block: List[str] = []
        i = start
        while i < len(lines):
            low = lines[i].lower()
            if low.startswith(("feature:", "background:", "scenario:", "scenario outline:")):
                break
            block.append(lines[i])
            i += 1
        return block, i

    @staticmethod
    def _split_examples(block: List[str]) -> tuple:
        """Tách Examples table (Scenario Outline) khỏi phần steps."""
        for i, line in enumerate(block):
            if line.lower().startswith("examples:"):
                rows = [l for l in block[i + 1:] if l.startswith("|")]
                return block[:i], GherkinParser._parse_examples_table(rows)
        return block, []

    @staticmethod
    def _parse_examples_table(rows: List[str]) -> List[Dict[str, str]]:
        """Bảng Examples: hàng đầu là header, các hàng sau là data."""
        if not rows:
            return []
        def cells(row: str) -> List[str]:
            return [c.strip() for c in row.strip().strip("|").split("|")]
        header = cells(rows[0])
        return [dict(zip(header, cells(r))) for r in rows[1:]]

    @classmethod
    def _parse_step_block(cls, block: List[str]) -> Dict[str, Any]:
        """Phân loại Given/When/Then + sinh structured steps + oracle.

        Quy ước (giống hành vi assertion của Hercules nhưng deterministic):
        - Then/And "I should see ..."  -> oracle nghiệp vụ (SV006), KHÔNG sinh step
          (assertion do Generator phát sinh từ expected_result — tránh trùng lặp).
        - And/But sau Then nhưng mang hành động (fill/click/open) -> vẫn là step.
        """
        given: List[str] = []
        when_then: List[str] = []
        then_oracles: List[str] = []
        structured: List[Dict[str, Any]] = []
        order = 0
        last_keyword = "given"

        for line in block:
            low = line.lower()
            keyword = next((k for k in cls.STEP_KEYWORDS if low.startswith(k + " ")), None)
            if keyword is None:
                continue  # description/docs trong block — bỏ qua
            body = line[len(keyword):].strip()

            if keyword == "given":
                given.append(body)
                last_keyword = "given"
                continue

            # And/But kế thừa ngữ cảnh của Then
            if keyword in ("and", "but"):
                if last_keyword == "then" and not cls._is_action_step(body):
                    oracle = cls._extract_oracle(body)
                    if oracle:
                        then_oracles.append(oracle)
                    continue
                keyword = "when"  # hành động nối tiếp When

            if keyword == "then":
                oracle = cls._extract_oracle(body)
                if oracle:
                    then_oracles.append(oracle)
                last_keyword = "then"
                continue

            # When/And hành động
            when_then.append(body)
            structured.append(cls._to_structured_step(body, order))
            order += 1
            last_keyword = "when"

        return {"given": given, "when_then": when_then, "then": then_oracles, "structured": structured}

    @staticmethod
    def _is_action_step(body: str) -> bool:
        """And/But sau Then nhưng là hành động thật (không phải assertion)."""
        low = body.lower()
        return low.startswith((
            "i fill", "i enter", "i type", "i click", "i press",
            "i open", "i go to", "i navigate", "i select", "i wait",
            "i upload", "i submit",
        ))

    # ------------------------------------------------------------------
    # Step structuring (canonical cho InputNormalizer + Generator)
    # ------------------------------------------------------------------
    @classmethod
    def _to_structured_step(cls, body: str, order: int) -> Dict[str, Any]:
        """Chuyển bước Gherkin thành structured step + canonical text.

        LƯU Ý: regex giá trị chạy trên body GỐC (giữ nguyên hoa/thường của
        test data — "Nguyen Van A" không bị lowercase).
        """
        low = body.lower()

        # WAIT: "I wait 3 seconds"
        wait_match = re.search(r"wait\s+(\d+)\s*second", low)
        if wait_match:
            return {"order": order + 1, "action": "WAIT", "target": "Condition", "value": int(wait_match.group(1))}

        # OPEN: "I open (the) X (page)" / "I am on the X page"
        if low.startswith(("i open", "i am on", "i go to", "i navigate")):
            open_match = re.search(r"(?:open|am on|go to|navigate to)\s+(?:the\s+)?(.+?)(?:\s+page)?$", body, re.IGNORECASE)
            if open_match:
                target = open_match.group(1).strip()
                return {"order": order + 1, "action": "OPEN", "target": target.title(), "value": None}

        # FILL: 'I fill "Field" with "value"' — value rỗng "" là hợp lệ (VALIDATION)
        fill_match = re.search(
            r"(?:fill|enter|type)\s+(?:\"([^\"]*)\"|'([^']*)')\s+(?:with|into|in)\s+(?:the\s+)?(?:\"([^\"]*)\"|'([^']*)')",
            body,
            re.IGNORECASE,
        )
        if fill_match:
            first = fill_match.group(1) if fill_match.group(1) is not None else fill_match.group(2)
            second = fill_match.group(3) if fill_match.group(3) is not None else fill_match.group(4)
            return {"order": order + 1, "action": "FILL", "target": str(first).title(), "value": second}

        # CLICK: 'I click "Button"' / "I click the Save button"
        click_match = re.search(r"click\s+(?:the\s+)?(?:\"([^\"]+)\"|'([^']+)'|([a-z0-9 _-]+?))\s*(?:button)?$", low)
        if click_match:
            target = click_match.group(1) or click_match.group(2) or click_match.group(3)
            return {"order": order + 1, "action": "CLICK", "target": str(target).strip().title(), "value": None}

        # Fallback: canonical text thô — InputNormalizer tự dò action
        return {"order": order + 1, "action": "ASSERT", "target": body, "value": None}

    @staticmethod
    def _extract_oracle(then_body: str) -> Optional[str]:
        """Trích oracle text: ưu tiên chuỗi trong ngoặc kép (UI message contract)."""
        match = QUOTED.search(then_body)
        if match:
            return match.group(1) or match.group(2)
        # Không có quote -> dùng cả câu làm oracle (sau khi bỏ "I should see")
        text = re.sub(r"^i\s+should\s+(see|not\s+see)\s+", "", then_body, flags=re.IGNORECASE).strip()
        return text or None

    # ------------------------------------------------------------------
    # Scenario Outline expansion
    # ------------------------------------------------------------------
    @classmethod
    def _expand_outline(cls, scenario: Dict[str, Any], row: Dict[str, str], row_no: int) -> Dict[str, Any]:
        """Thay <placeholder> bằng giá trị Examples -> scenario độc lập.

        Deterministic: test data đến từ Examples table, LLM không được tự chế.
        """
        def substitute(text: str) -> str:
            for key, value in row.items():
                text = text.replace(f"<{key}>", value)
            return text

        structured = []
        for step in scenario["structured_steps"]:
            structured.append({
                "order": step["order"],
                "action": step["action"],
                "target": substitute(str(step["target"])),
                "value": substitute(str(step["value"])) if step.get("value") is not None else None,
            })

        expected = [substitute(e) for e in scenario["expected_result"]]
        return {
            "function_id": f"{scenario['function_id']}-EX{row_no:02d}",
            "feature": scenario["feature"],
            "scenario": substitute(scenario["scenario"]),
            "tags": scenario["tags"],
            "precondition": [substitute(p) for p in scenario["precondition"]],
            "steps": [substitute(s) for s in scenario["steps"]],
            "expected_result": expected,
            "structured_steps": structured,
            "test_data": dict(row),
            "source_text": scenario["source_text"],
        }

    # ------------------------------------------------------------------
    # Integration: -> ADLC Memory context (hợp đồng Bước 1-3 không đổi)
    # ------------------------------------------------------------------
    @classmethod
    def to_function_context(cls, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Scenario -> context đăng ký được vào ADLCMemoryClient.

        steps ở dạng canonical text mà InputNormalizer hiểu sẵn:
        "Open Login Page" / "Fill Name 'Nguyen Van A'" / "Click Save" / "Wait 2".
        """
        canonical_steps = [cls.structured_to_canonical(s) for s in scenario["structured_steps"]]
        return {
            "feature": scenario["feature"],
            "scenario": scenario.get("scenario", ""),
            "tags": scenario.get("tags", []),
            "business_rules": [],
            "validation_rules": [],
            "ui_flow": canonical_steps,
            "precondition": scenario.get("precondition", []),
            "expected_result": scenario.get("expected_result", []),
            "test_data": scenario.get("test_data", {}),
            "rejection_message": "",
        }

    @staticmethod
    def structured_to_canonical(step: Dict[str, Any]) -> str:
        """Structured step -> canonical text (round-trip ổn định qua Normalizer)."""
        action = step.get("action", "")
        target = step.get("target", "")
        value = step.get("value")
        if action == "OPEN":
            return f"Open {target}"
        if action == "FILL":
            return f"Fill {target} '{value}'" if value is not None else f"Fill {target}"
        if action == "CLICK":
            return f"Click {target}"
        if action == "SUBMIT":
            return f"Click {target}"
        if action == "WAIT":
            return f"Wait {value} seconds"
        return f"Assert {target}"

    @staticmethod
    def _slug(text: str) -> str:
        return SAFE_ID.sub("-", text).strip("-")[:60]

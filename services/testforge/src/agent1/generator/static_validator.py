"""Static Validator (Bước 9).

Nhiệm vụ:
- Kiểm tra mã Playwright script sinh ra TRƯỚC khi thực thi (chặn rác sớm).
- Zero-LLM, hoàn toàn deterministic theo quy tắc SV001 - SV006:
  - SV001: Import `test, expect` từ '@playwright/test'
  - SV002: Metadata header đầy đủ (@test_case_id, @function_id)
  - SV003: Có ít nhất một khối test(...)
  - SV004: Cấu trúc cú pháp cơ bản (ngoặc {}, (), [] cân bằng)
  - SV005: Chỉ chứa các lời gọi Playwright được cho phép (action whitelist)
  - SV006: Có ít nhất một assertion khi test case có expected_results
- Lỗi script bị chặn tại đây sẽ KHÔNG được đưa vào executor (tránh tốn tài nguyên browser).
"""

import re
from typing import Any, Dict, List, Optional


class StaticValidator:
    """Kiểm tra tĩnh mã nguồn Playwright script do Automation Generator sinh ra."""

    REQUIRED_IMPORT = "import { test, expect } from '@playwright/test';"
    REQUIRED_META_TAGS = ["@test_case_id", "@function_id"]

    # Whitelist token Playwright hợp lệ cho dòng "await ..." (Bước 8 action mapping
    # + evidence preamble M3.1)
    PLAYWRIGHT_CALL_TOKENS = [
        "page.goto(", "page.getByRole(", "page.getByLabel(", "page.getByText(",
        "page.getByTestId(", "page.locator(", "page.waitForTimeout(", "expect(",
        "page.on(", "page.evaluate(", "testInfo.attach(",
    ]

    # Deny-list: lời gọi nguy hiểm/không thuộc scope automation test
    FORBIDDEN_TOKENS = [
        "process.", "require(", "child_process", "eval(", "new Function",
        "fs.", "import(", "globalThis", "__dirname", "Buffer.",
        "setTimeout(", "setInterval(", "fetch(",
    ]

    @classmethod
    def validate(
        cls,
        script_code: str,
        test_case: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Kiểm tra tĩnh script Playwright.

        Args:
            script_code: Mã nguồn TypeScript của spec
            test_case: Test case gốc (đối chiếu metadata, tùy chọn)

        Returns:
            {"valid": bool, "errors": [{"code", "line", "message"}]}
        """
        errors: List[Dict[str, Any]] = []
        script = script_code or ""
        lines = script.splitlines()

        # SV001: import bắt buộc
        if cls.REQUIRED_IMPORT not in script:
            errors.append({
                "code": "SV001",
                "line": 1,
                "message": "Missing required import: " + cls.REQUIRED_IMPORT,
            })

        # SV002: metadata header
        for tag in cls.REQUIRED_META_TAGS:
            if tag not in script:
                errors.append({
                    "code": "SV002",
                    "line": 1,
                    "message": f"Missing metadata tag '{tag}' in script header",
                })

        # SV003: khối test(...)
        if not re.search(r"\btest\(\s*['\"].*['\"]", script):
            errors.append({
                "code": "SV003",
                "line": 1,
                "message": "Script must contain at least one test() block",
            })

        # SV004: cân bằng ngoặc (bỏ qua nội dung trong chuỗi)
        code_no_strings = cls._strip_strings_and_comments(script)
        for open_ch, close_ch, name in [("{", "}", "braces"), ("(", ")", "parentheses"), ("[", "]", "brackets")]:
            if code_no_strings.count(open_ch) != code_no_strings.count(close_ch):
                errors.append({
                    "code": "SV004",
                    "line": 1,
                    "message": f"Unbalanced {name} in generated script",
                })

        # SV005: hybrid check —
        #   a) dòng "await ..." phải chứa lời gọi Playwright hợp lệ (action whitelist)
        #   b) mọi dòng khác không được chứa lời gọi nguy hiểm (deny-list)
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                continue
            if stripped.startswith("import") or stripped.startswith("test.describe") or stripped.startswith("test("):
                continue
            if stripped.startswith("});") or stripped in ("})", "});", "}", "{"):
                continue

            forbidden = next((f for f in cls.FORBIDDEN_TOKENS if f in line), None)
            if forbidden:
                errors.append({
                    "code": "SV005",
                    "line": idx,
                    "message": f"Forbidden call '{forbidden}' in statement: '{stripped[:80]}'",
                })
                continue

            if stripped.startswith("await ") and not any(token in line for token in cls.PLAYWRIGHT_CALL_TOKENS):
                errors.append({
                    "code": "SV005",
                    "line": idx,
                    "message": f"Unsupported statement: '{stripped[:80]}'",
                })

        # SV006 v2: ORACLE TRACEABILITY — mỗi expected_result phải có assertion
        # ĐÚNG NGHIỆP VỤ (expect(page.getByText('<expected>'))), không chỉ đủ số lượng.
        # Chặn được AI "gian lận" kiểu: expect(true).toBeTruthy() — đủ count, sai oracle.
        expected_results = (test_case or {}).get("expected_results") or []
        from .playwright_generator import PlaywrightGenerator
        for oracle in (test_case or {}).get("ui_oracles", []):
            if PlaywrightGenerator.ui_assertion(oracle, test_case) not in script:
                errors.append({"code": "SV006", "line": 1, "message": "Typed oracle removed or altered"})
        for exp in expected_results:
            if not exp:
                continue
            # Chấp nhận cả form escaped (generator escape quote/backslash khi nhúng JS)
            # và form .first() (parity với executor Python, chống strict mode violation)
            escaped = str(exp).replace("\\", "\\\\").replace("'", "\\'")
            candidates = (
                f"expect(page.getByText('{exp}'))",
                f"expect(page.getByText('{escaped}'))",
                f"expect(page.getByText('{exp}').first())",
                f"expect(page.getByText('{escaped}').first())",
            )
            if not any(c in script for c in candidates):
                errors.append({
                    "code": "SV006",
                    "line": 1,
                    "message": f"Oracle assertion missing/mismatched for expected: '{str(exp)[:60]}'",
                })

        return {"valid": len(errors) == 0, "errors": errors}

    @classmethod
    def _strip_strings_and_comments(cls, code: str) -> str:
        """Bỏ nội dung chuỗi và comment để đếm ngoặc chính xác."""
        # Match strings and comments in a single scan: https:// inside a string
        # must not start a line comment and erase the rest of the statement.
        tokens = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`(?:[^`\\]|\\.)*`|//[^\n]*|/\*[\s\S]*?\*/"
        return re.sub(tokens, "", code)

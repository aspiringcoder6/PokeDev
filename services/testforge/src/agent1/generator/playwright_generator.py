"""Automation Generator & Playwright Script Artifact (Bước 8 & Bước 10).

Nhiệm vụ:
- Chuyển đổi Structured Test Case -> Playwright Test Script (TypeScript).
- Áp dụng chính sách LocatorPolicy.
- Sinh metadata đầy đủ (test_case_id, function_id, script_version, generated_at).
"""

import os
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from .locator_policy import LocatorPolicy


class PlaywrightGenerator:
    """Sinh mã nguồn Playwright test script từ Structured Test Case."""

    DEFAULT_SCRIPT_VERSION = "1.0.0"
    DEFAULT_GENERATOR_MODEL = "deterministic-v2"

    @staticmethod
    def _js_quote(value: Any) -> str:
        """Nhúng giá trị vào chuỗi JS an toàn (escape backslash + quote)."""
        text = str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\r", "\\r").replace("\n", "\\n")
        return f"'{text}'"

    @classmethod
    def locator(cls, target, test_case, preference=None):
        mapping = test_case.get("locators", {})
        if target not in mapping:
            if test_case.get("strict_mapping"):
                raise ValueError(f"Locator mapping required: {target}")
            return LocatorPolicy.generate_locator(target, strategy_preference=preference) if preference else LocatorPolicy.generate_locator(target)
        item = mapping[target]
        scope = "page"
        if item.get("scope_testid"):
            scope += f".getByTestId({cls._js_quote(item['scope_testid'])})"
        if item.get("scope_css"):
            scope += f".locator({cls._js_quote(item['scope_css'])})"
        kind, value = item["by"], cls._js_quote(item["value"])
        if kind == "role":
            return f"{scope}.getByRole({value}, {{ name: {cls._js_quote(item['name'])}, exact: true }})"
        if kind == "css":
            return f"{scope}.locator({value})"
        methods = {"label": "getByLabel", "testid": "getByTestId", "text": "getByText"}
        if kind not in methods:
            raise ValueError(f"Unsupported locator strategy: {kind}")
        options = ", { exact: true }" if kind in ("label", "text") else ""
        return f"{scope}.{methods[kind]}({value}{options})"

    @classmethod
    def ui_assertion(cls, oracle, test_case):
        kind = oracle["type"]
        value = json.dumps(oracle.get("expected"), ensure_ascii=False)
        timeout = int(oracle.get("timeout_ms", 5000))
        if kind == "URL":
            return f"await expect(page).toHaveURL({value}, {{ timeout: {timeout} }});"
        loc = cls.locator(oracle["target"], test_case)
        matchers = {"TEXT": "toHaveText", "VALUE": "toHaveValue", "COUNT": "toHaveCount"}
        if kind in ("VISIBLE", "ABSENT"):
            return f"await expect({loc}).{'toBeVisible' if kind == 'VISIBLE' else 'toBeHidden'}({{ timeout: {timeout} }});"
        if kind not in matchers:
            raise ValueError(f"Unsupported oracle type: {kind}")
        return f"await expect({loc}).{matchers[kind]}({value}, {{ timeout: {timeout} }});"

    @classmethod
    def metadata_header(cls, tc_id, func_id, feature, script_version=DEFAULT_SCRIPT_VERSION,
                        generator_model=DEFAULT_GENERATOR_MODEL, extra_meta=None):
        """Header metadata + import — dùng chung cho generator và explorer synthesizer."""
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = [
            ("test_case_id", tc_id), ("function_id", func_id), ("feature", feature),
            ("script_version", script_version), ("generated_at", now_iso),
            ("generator_model", generator_model),
        ] + list((extra_meta or {}).items())
        lines = ["/**"] + [" * @{0} {1}".format(k, v) for k, v in meta] + [" */"]
        return "\n".join(lines) + "\nimport { test, expect } from '@playwright/test';\n"

    @classmethod
    def evidence_prelude(cls, describe_label, test_title):
        """const networkEvents + describe + beforeEach listener + mở test block."""
        return (
            "\nconst networkEvents: Array<{ method: string; url: string; status: number }> = [];\n\n"
            "test.describe(" + cls._js_quote(describe_label) + ", () => {\n"
            "  test.beforeEach(async ({ page }) => {\n"
            "    page.on('response', (response) => {\n"
            "      networkEvents.push({\n"
            "        method: response.request().method(),\n"
            "        url: response.url(),\n"
            "        status: response.status()\n"
            "      });\n"
            "    });\n"
            "  });\n\n"
            "  test(" + cls._js_quote(test_title) + ", async ({ page }) => {\n"
        )

    @classmethod
    def evidence_footer(cls):
        """afterEach: attach evidence.json (network + UI probe). KHÔNG đóng block —
        caller tự thêm banner (demo) rồi đóng afterEach + describe."""
        return """
  });

  test.afterEach(async ({ page }, testInfo) => {
    let visibleMessages: string[] = [];
    let domProbe: Array<{ tag: string; text: string; testid: string | null; visible: boolean }> = [];
    try {
      visibleMessages = await page.locator('#status div').allTextContents();
      domProbe = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('button, [role="button"], input')).map((el) => ({
          tag: el.tagName.toLowerCase(),
          text: (el.textContent || '').trim().slice(0, 60),
          testid: el.getAttribute('data-testid'),
          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
        }));
      });
    } catch (e) {
      visibleMessages = [];
      domProbe = [];
    }
    await testInfo.attach('evidence.json', {
      body: JSON.stringify({
        network_events: networkEvents,
        ui_evidence: {
          visible_messages: visibleMessages,
          dom_probe: domProbe,
          page_url: page.url()
        }
      }, null, 2),
      contentType: 'application/json'
    });
"""

    @classmethod
    def generate_script(
        cls,
        test_case: Dict[str, Any],
        script_version: str = DEFAULT_SCRIPT_VERSION,
        generator_model: str = DEFAULT_GENERATOR_MODEL,
    ) -> str:
        """Sinh mã nguồn TypeScript hoàn chỉnh cho một test case.

        Args:
            test_case: Dữ liệu Structured Test Case
            script_version: Phiên bản script
            generator_model: Tên model/generator

        Returns:
            Chuỗi mã nguồn TypeScript của file spec
        """
        tc_id = test_case.get("test_case_id", "TC-UNKNOWN")
        func_id = test_case.get("function_id", "FUNC-UNKNOWN")
        feature = test_case.get("feature", "Feature")
        steps = test_case.get("steps", [])
        expected_results = test_case.get("expected_results", [])
        test_data = test_case.get("test_data", {})
        now_iso = datetime.now(timezone.utc).isoformat()

        # C04 controlled fault (M3.1, chỉ active qua env từ benchmark harness):
        # perturb oracle text -> assertion chắc chắn không khớp UI -> ASSERTION failure.
        # Production không bao giờ set env này.
        if os.environ.get("FAULT_ASSERTION_PERTURB") == "1" and expected_results:
            expected_results = [f"{expected_results[0]} [ORACLE-PERTURBED]"] + list(expected_results[1:])

        # Build metadata header + evidence preamble (M3.1: network + UI evidence)
        header = cls.metadata_header(tc_id, func_id, feature, script_version, generator_model) \
            + cls.evidence_prelude("{0} - {1}".format(feature, tc_id),
                                   "{0}: {1}".format(tc_id, feature))

        body_lines: List[str] = []

        # Generate action steps
        for step in steps:
            action = step.get("action", "").upper()
            target = step.get("target", "")
            value = step.get("value")
            timeout_ms = step.get("timeout_ms")

            if action == "OPEN":
                target = test_case.get("routes", {}).get(target, target)
                if test_case.get("strict_mapping") and not target.startswith(("/", "http://", "https://")):
                    raise ValueError(f"Route mapping required: {target}")
                url = target if target.startswith("/") or target.startswith("http") else f"/{target.lower().replace(' ', '-')}"
                body_lines.append(f"    // Step {step.get('order', 1)}: Navigate to {target}")
                body_lines.append(f"    await page.goto({cls._js_quote(url)});")

            elif action == "CLICK":
                loc = cls.locator(target, test_case)
                click_opts = f"{{ timeout: {int(timeout_ms)} }}" if timeout_ms else ""
                body_lines.append(f"    // Step {step.get('order', 1)}: Click {target}")
                body_lines.append(f"    await {loc}.click({click_opts});")

            elif action == "FILL":
                # value rỗng("") là hợp lệ (VALIDATION: bắt buộc) — chỉ fallback
                # khi step không khai báo value (None)
                val = value if value is not None else test_data.get(target.lower(), "Sample Value")
                loc = cls.locator(target, test_case, "LABEL")
                fill_args = f"{cls._js_quote(val)}, {{ timeout: {int(timeout_ms)} }}" if timeout_ms else cls._js_quote(val)
                body_lines.append(f"    // Step {step.get('order', 1)}: Fill {target}")
                body_lines.append(f"    await {loc}.fill({fill_args});")

            elif action == "SELECT":
                loc = cls.locator(target, test_case, "LABEL")
                body_lines.append(f"    // Step {step.get('order', 1)}: Select {target}")
                body_lines.append(f"    await {loc}.selectOption({cls._js_quote(value or '')});")

            elif action == "SUBMIT":
                loc = cls.locator(target or "Submit", test_case)
                submit_opts = f"{{ timeout: {int(timeout_ms)} }}" if timeout_ms else ""
                body_lines.append(f"    // Step {step.get('order', 1)}: Submit form")
                body_lines.append(f"    await {loc}.click({submit_opts});")

            elif action == "PRESS":
                # Nhấn phím (Enter) — không cần locator element
                key = cls._js_quote(target or value or "Enter")
                body_lines.append(f"    // Step {step.get('order', 1)}: Press {key} key")
                body_lines.append(f"    await page.keyboard.press({key});")

            elif action == "WAIT":
                body_lines.append(f"    // Step {step.get('order', 1)}: Wait for condition")
                body_lines.append(f"    await page.waitForTimeout({int(value or 1000)});")

            elif action == "ASSERT":
                loc = cls.locator(target or value or "Text", test_case)
                body_lines.append(f"    // Step {step.get('order', 1)}: Assert {target}")
                # .first() khớp ngữ nghĩa executor Python (get_by_text(...).first) —
                # tránh strict mode violation khi text xuất hiện ở nhiều element
                body_lines.append(f"    await expect({loc}.first()).toBeVisible();")
            elif action == "UPLOAD":
                loc = cls.locator(target, test_case, "LABEL")
                body_lines.append(f"    await {loc}.setInputFiles({cls._js_quote(value)});")
            else:
                raise ValueError(f"Unsupported action: {action}")

        # Generate assertions from expected_results
        body_lines.append("    // Assertions")
        for exp in expected_results:
            # .first() tránh strict mode violation (text trùng ở nhiều element)
            body_lines.append(
                f"    await expect(page.getByText({cls._js_quote(exp)}).first()).toBeVisible();"
            )
        for oracle in test_case.get("ui_oracles", []):
            body_lines.append("    " + cls.ui_assertion(oracle, test_case))

        # Evidence collection hook (M3.1): UI evidence + network events -> attachment
        evidence_footer = cls.evidence_footer()

        demo_hold_ms = 0
        try:
            demo_hold_ms = int(os.environ.get("DEMO_HOLD_MS", "0"))
        except (ValueError, TypeError):
            demo_hold_ms = 0

        if demo_hold_ms > 0:
            evidence_footer += f"""
    try {{
      await page.evaluate((isPass) => {{
        const banner = document.createElement('div');
        banner.id = 'demo-result-banner';
        banner.style.position = 'fixed';
        banner.style.top = '16px';
        banner.style.left = '50%';
        banner.style.transform = 'translateX(-50%)';
        banner.style.backgroundColor = isPass ? '#15803d' : '#b91c1c';
        banner.style.color = '#ffffff';
        banner.style.padding = '12px 28px';
        banner.style.borderRadius = '10px';
        banner.style.fontSize = '18px';
        banner.style.fontWeight = 'bold';
        banner.style.boxShadow = '0 6px 16px rgba(0,0,0,0.4)';
        banner.style.zIndex = '999999';
        banner.style.fontFamily = 'Arial, sans-serif';
        banner.textContent = isPass ? 'PASS - XAC MINH THANH CONG' : 'FAIL - TIMEOUT (LOCATOR KHONG HOP LE)';
        document.body.appendChild(banner);
      }}, testInfo.status === 'passed');
      await page.waitForTimeout({demo_hold_ms});
    }} catch (e) {{
    }}
"""

        evidence_footer += """  });
});
"""

        return header + "\n".join(body_lines) + evidence_footer

    @classmethod
    def build_oracle_trace(cls, test_case: Dict[str, Any]) -> List[Dict[str, str]]:
        """SV006 — Oracle Traceability Record: mapping expected_result -> assertion.

        Mỗi expected_result nghiệp vụ phải ánh xạ được tới chính xác assertion
        Playwright sinh ra trong script. Đây là guard mạnh hơn việc đếm expect():
        chặn các "assertion rác" kiểu expect(true).toBeTruthy() vì nó không
        trace về được đúng oracle text.

        Returns:
            Danh sách record: {expected_result, assertion, locator_strategy}
        """
        trace: List[Dict[str, str]] = []
        for exp in test_case.get("expected_results", []):
            if not exp:
                continue
            trace.append({
                "expected_result": exp,
                "assertion": f"expect(page.getByText('{exp}')).toBeVisible()",
                "locator_strategy": "getByText",
            })
        return trace

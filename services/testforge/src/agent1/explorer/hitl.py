"""Tier-3 HITL: khi step DEVIATED/FAILED, QA cấp locator thủ công — bounded retry.

Hai kênh (chốt họp G1):
- overlay: tiêm HTML input vào chính trang web (headed) — QA Inspect rồi dán locator
  vào trang, KHÔNG dùng native prompt() vì Playwright chặn mọi dialog qua CDP
  (dialog không bao giờ render UI cho người dùng).
- stdin: CLI prompt khi headless/CI.

Locator thủ công bắt buộc có prefix để agent dựng lại Playwright high-level API
(fidelity replay được giữ nguyên trong spec tổng hợp):
  role=button|name=Tạo dự án   -> page.get_by_role("button", name="...", exact=True)
  css=#project-name            -> page.locator("#project-name")
  text=Tạo thành công          -> page.get_by_text("...")
"""
import time

HITL_MAX_RETRIES = 2
DEFAULT_TIMEOUT_MS = 120000

_INJECT_JS = """(msg) => {
  const old = document.getElementById('__tf_hitl');
  if (old) old.remove();
  window.__tf_hitl_value = null;
  const box = document.createElement('div');
  box.id = '__tf_hitl';
  box.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;'
    + 'background:#1e293b;color:#e2e8f0;padding:14px;border-radius:8px;'
    + 'font:13px/1.5 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.4);width:360px';
  const label = document.createElement('div');
  label.textContent = msg;
  label.style.marginBottom = '8px';
  const input = document.createElement('input');
  input.id = '__tf_hitl_in';
  input.placeholder = 'role=button|name=... | css=... | text=...';
  input.style.cssText = 'width:100%;box-sizing:border-box;padding:6px;border-radius:4px;'
    + 'border:1px solid #475569;background:#0f172a;color:#e2e8f0';
  const row = document.createElement('div');
  row.style.cssText = 'margin-top:8px;text-align:right';
  const ok = document.createElement('button');
  ok.id = '__tf_hitl_ok';
  ok.textContent = 'OK';
  ok.style.cssText = 'padding:4px 14px;border-radius:4px;border:0;background:#2563eb;color:#fff;cursor:pointer';
  const skip = document.createElement('button');
  skip.id = '__tf_hitl_skip';
  skip.textContent = 'Bỏ qua';
  skip.style.cssText = 'padding:4px 14px;border-radius:4px;border:0;background:#475569;color:#fff;cursor:pointer;margin-left:6px';
  ok.onclick = () => { window.__tf_hitl_value = document.getElementById('__tf_hitl_in').value; };
  skip.onclick = () => { window.__tf_hitl_value = ''; };
  row.appendChild(ok);
  row.appendChild(skip);
  box.appendChild(label);
  box.appendChild(input);
  box.appendChild(row);
  document.body.appendChild(box);
  input.focus();
  return true;
}"""
_POLL_JS = "() => window.__tf_hitl_value === undefined ? null : window.__tf_hitl_value"
_REMOVE_JS = "() => { const el = document.getElementById('__tf_hitl'); if (el) el.remove(); }"


class ManualLocatorAssist:
    """Kênh hỏi QA một locator. Trả về chuỗi raw hoặc None khi bỏ qua/hết giờ."""

    def __init__(self, page, channel="auto", timeout_ms=DEFAULT_TIMEOUT_MS, input_fn=None):
        self.page = page
        self.channel = channel
        self.timeout_ms = timeout_ms
        self._input_fn = input_fn or input

    def request(self, message):
        channel = self.channel
        if channel == "auto":
            channel = "overlay" if self._overlay_available() else "stdin"
        if channel == "overlay":
            return self._overlay_request(message)
        return self._stdin_request(message)

    def _overlay_available(self):
        try:
            return bool(self.page.evaluate("() => Boolean(document.body)"))
        except Exception:
            return False

    def _overlay_request(self, message):
        try:
            self.page.evaluate(_INJECT_JS, message)
        except Exception:
            return self._stdin_request(message)
        deadline = time.time() + self.timeout_ms / 1000.0
        while time.time() < deadline:
            try:
                value = self.page.evaluate(_POLL_JS)
            except Exception:
                return None
            if value is not None:
                try:
                    self.page.evaluate(_REMOVE_JS)
                except Exception:
                    pass
                return value if value.strip() else None
            time.sleep(0.4)
        try:
            self.page.evaluate(_REMOVE_JS)
        except Exception:
            pass
        return None

    def _stdin_request(self, message):
        try:
            raw = self._input_fn("HITL {0}\nlocator> ".format(message))
        except (EOFError, KeyboardInterrupt):
            return None
        return raw.strip() if raw and raw.strip() else None


def parse_manual_locator(raw):
    """role=button|name=X | css=#a | text=abc -> dict; sai format -> None."""
    text = str(raw).strip()
    lowered = text.lower()
    if lowered.startswith("role="):
        body = text[5:]
        role, _, rest = body.partition("|")
        role = role.strip()
        name = ""
        if rest.strip().lower().startswith("name="):
            name = rest.strip()[5:].strip()
        if not role:
            return None
        return {"kind": "role", "role": role, "name": name}
    if lowered.startswith("css="):
        value = text[4:].strip()
        return {"kind": "css", "value": value} if value else None
    if lowered.startswith("text="):
        value = text[5:].strip()
        return {"kind": "text", "value": value} if value else None
    return None


def manual_element(parsed):
    """Parsed locator -> element cho executor."""
    if parsed["kind"] == "role":
        return {"kind": "role", "role": parsed["role"], "name": parsed["name"]}
    return {"kind": parsed["kind"], "value": parsed["value"]}


def manual_candidate(parsed):
    """Candidate cho trace (strategy phải nằm trong enum của trace schema)."""
    if parsed["kind"] == "role":
        return {"strategy": "role", "value": parsed["role"], "name": parsed["name"], "score": 1.0}
    strategy = "css" if parsed["kind"] == "css" else "text"
    return {"strategy": strategy, "value": parsed["value"], "score": 1.0}


def manual_js_expr(parsed):
    if parsed["kind"] == "role":
        name = parsed["name"].replace("\\", "\\\\").replace("'", "\\'")
        return "page.getByRole('{0}', {{ name: '{1}', exact: true }})".format(parsed["role"], name)
    value = parsed["value"].replace("\\", "\\\\").replace("'", "\\'")
    if parsed["kind"] == "css":
        return "page.locator('{0}')".format(value)
    return "page.getByText('{0}')".format(value)

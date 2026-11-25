"""Login per-case cho Explorer/Replay — storageState riêng từng scenario.

Hai lối:
- API login (mặc định): POST {api_url}/auth/login với email/password form data —
  khớp SUT tteamflow.
- UI login (password == "ui"): SUT không có endpoint login chuẩn (VD TNQD login
  qua portal + nút đăng nhập nhanh) — mở browser, thực hiện đăng nhập trên trang
  login thật rồi lưu storageState.
"""
import json
import os
from pathlib import Path


def browser_extra_headers():
    """Headers HTTP bổ sung cho mọi browser context (login + explore).

    SUT kiểu TNQD lấy identity từ header do gateway (APISIX) inject
    (X-Username, X-User-Id...) — chạy trực tiếp (không qua gateway) cần tự
    truyền. Đọc JSON từ env TESTFORGE_BROWSER_EXTRA_HEADERS,
    VD: TESTFORGE_BROWSER_EXTRA_HEADERS={"X-Username": "admin"}.
    Trả {} khi env rỗng/sai JSON (an toàn cho SUT có gateway thật).
    """
    raw = os.environ.get("TESTFORGE_BROWSER_EXTRA_HEADERS", "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v not in (None, "")}


def login_and_save_state(pw, api_url, email, password, state_path, base_url=""):
    """Login bằng API (hoặc UI khi password=='ui'), trả Bearer token, ghi state."""
    if str(password).strip().lower() == "ui":
        return _ui_login(pw, base_url or api_url, email, state_path)
    request = pw.request.new_context()
    response = request.post(
        api_url.rstrip("/") + "/auth/login",
        data={"email": email, "password": password},
    )
    if not response.ok:
        # Fallback UI: SUT dev có thể chỉ hỗ trợ đăng nhập trên trang (portal/SSO)
        request.dispose()
        return _ui_login(pw, base_url or api_url, email, state_path)
    body = response.json()
    data = body.get("data") or body
    token = data.get("accessToken") or data.get("access_token") or ""
    state = request.storage_state()
    request.dispose()
    # Backend gắn Secure cho refresh cookie; chạy HTTP thuần (docker :80) Chromium
    # từ chối set cookie Secure -> SPA mất phiên ngay bootstrap (rớt về /login).
    # Chuẩn hoá giống tteamflow_session.py: secure=False khi api_url là http.
    if api_url.startswith("http://"):
        for cookie in state.get("cookies", []):
            cookie["secure"] = False
    Path(state_path).write_text(json.dumps(state), encoding="utf-8")
    return token


def _ui_login(pw, base_url, email, state_path):
    """Đăng nhập trên trang login thật của SUT rồi lưu storageState.

    Chiến lược (không SUT-specific cứng):
    1. Ưu tiên nút "đăng nhập nhanh" (label chứa 'Đăng nhập nhanh' hoặc 'Dev quick').
    2. Không có thì đi form chuẩn: input username/email + password -> submit.
    Xác định thành công: URL rời khỏi các trang auth (/auth*, /login).
    """
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(extra_http_headers=browser_extra_headers())
    page = context.new_page()
    try:
        page.goto(base_url.rstrip("/") + "/", timeout=45000)
        # Đợi nút đăng nhập nhanh hoặc form password xuất hiện (SPA render chậm,
        # networkidle bất định với vite HMR -> dùng selector cụ thể)
        quick = None
        try:
            page.wait_for_selector("text=Đăng nhập nhanh", timeout=20000)
            quick = page.locator("button, a").filter(has_text="Đăng nhập nhanh").first
        except Exception:
            quick = None
        if quick is not None and quick.count():
            quick.click()
        else:
            user_field = page.locator(
                'input[type="email"], input[name="username"], '
                'input[formcontrolname="userName"]').first
            pass_field = page.locator('input[type="password"]').first
            user_field.wait_for(state="visible", timeout=20000)
            user_field.fill(email)
            pass_field.fill(str(email).split("@")[0] + "@Dev2026")
            page.keyboard.press("Enter")
        # Thành công = URL rời trang auth (VD /tnqd/dashboard)
        try:
            page.wait_for_url(
                lambda url: not any(seg in url for seg in ("/auth", "/login")),
                timeout=25000,
            )
        except Exception as exc:
            raise SystemExit(
                "UI login không rời được trang auth sau 25s (url={0}): {1}".format(
                    page.url, exc))
        state = context.storage_state()
        Path(state_path).write_text(json.dumps(state), encoding="utf-8")
        return ""
    finally:
        context.close()
        browser.close()

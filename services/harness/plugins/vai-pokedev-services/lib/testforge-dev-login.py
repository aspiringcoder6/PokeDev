"""Fixed read-only TNQD smoke, using TestForge's real recorder in its worker image."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

TARGET = "http://10.0.10.195:3011/tnqd/dashboard"
MARKER = "POKEDEV_TESTFORGE_RESULT:"


def main():
    identity = str(UUID(sys.argv[1]))
    result = {"schema_version": "0.1", "check_id": identity,
              "framework": "TestForge TraceRecorder", "auth_mode": "DEV_BUTTON",
              "target_url": TARGET, "verification_evidence": False, "execution_complete": False}
    browser = None
    try:
        sys.path.insert(0, "/app")
        from playwright.sync_api import sync_playwright, expect
        from src.agent1.explorer.playwright_driver import PlaywrightDriver
        from src.agent1.explorer.recorder import TraceRecorder
        from src.agent1.explorer.session import ExplorationSession

        class PrivateDriver(PlaywrightDriver):
            def storage_entries(self):
                return []  # Browser credentials never enter trace files or the PokeDev response.

        session = ExplorationSession(output_root="pokedev-testforge-evidence", base_url=TARGET,
                                     actor="dev-quick-login", total_deadline_ms=100000,
                                     run_id="POKEDEV-" + identity)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.route("**/*", lambda route: route.abort() if route.request.method in {"PUT", "PATCH", "DELETE"} else route.continue_())
            driver = PrivateDriver(page, actor="dev-quick-login")
            recorder = TraceRecorder(session, driver, step_deadline_ms=25000)

            def open_dashboard(_driver):
                page.goto(TARGET, wait_until="domcontentloaded", timeout=20000)
                if urlsplit(page.url).netloc != urlsplit(TARGET).netloc:
                    raise AssertionError("Trang chuyển sang địa chỉ ngoài phạm vi kiểm tra.")

            login = {"dev_button_clicked": False}

            def dev_login(_driver):
                button = page.get_by_role("button", name=re.compile("Đăng nhập nhanh Dev", re.I))
                button.wait_for(state="visible", timeout=15000)
                button.click(timeout=10000)
                login["dev_button_clicked"] = True
                page.wait_for_url(re.compile(r"/tnqd/dashboard(?:[/?#]|$)"), timeout=15000)
                if urlsplit(page.url).netloc != urlsplit(TARGET).netloc:
                    raise AssertionError("Đăng nhập chuyển sang địa chỉ ngoài phạm vi.")

            def heading(_driver):
                expect(page.get_by_text("THANH NIÊN QUÂN ĐỘI", exact=True).first).to_be_visible(timeout=10000)

            def navigation(_driver):
                expect(page.get_by_role("link", name="Dashboard", exact=True)).to_be_visible(timeout=10000)

            def embedded_content(_driver):
                frames = [frame for frame in page.frames if frame != page.main_frame and frame.frame_element().is_visible()]
                if not frames:
                    raise AssertionError("Dashboard chưa hiển thị khung nội dung nhúng.")
                for frame in frames[:5]:
                    text = frame.locator("body").inner_text(timeout=8000).strip()
                    if not text:
                        raise AssertionError("Khung nội dung dashboard đang trống.")
                    if re.search(r"\bNot Found\b|Cannot GET|ERR_CONNECTION", text, re.I):
                        raise AssertionError("Nội dung nhúng của dashboard trả về Not Found hoặc lỗi kết nối.")

            actions = [
                ("Mở dashboard TNQD", "OPEN", open_dashboard),
                ("Đăng nhập bằng nút Đăng nhập nhanh Dev", "CLICK", dev_login),
                ("Hiển thị tiêu đề THANH NIÊN QUÂN ĐỘI", "ASSERT", heading),
                ("Hiển thị điều hướng Dashboard", "ASSERT", navigation),
                ("Nội dung dashboard không có lỗi Not Found", "ASSERT", embedded_content),
            ]
            for index, (label, action, callback) in enumerate(actions, 1):
                recorder.record(f"STEP-1-{index}", label, action, callback,
                                target=label, observed_extra=login if index == 2 else None)
            summary = session.finalize(required_steps=[f"STEP-1-{i}" for i in range(1, 6)])
            result.update(execution_complete=True, native_run_id=session.run_id,
                          native_summary=summary, dev_button_clicked=login["dev_button_clicked"],
                          checks=[{"id": row["step_id"], "label": row["user_intent"], "status": row["status"],
                                   "error": row.get("observed_ui", {}).get("error")}
                                  for row in session.records],
                          artifact_directory=str(session.root),
                          screenshots=sum(bool(row.get("observed_ui", {}).get("screenshot")) for row in session.records))
            context.close()
            browser.close()
            browser = None
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:1800]
    result["checks_total"] = len(result.get("checks", []))
    result["checks_passed"] = sum(row["status"] == "GROUNDED" for row in result.get("checks", []))
    result["application_passed"] = result["execution_complete"] and result["checks_total"] == 5 and result["checks_passed"] == 5
    encoded = json.dumps(result, ensure_ascii=False)
    Path("pokedev-testforge-result.json").write_text(encoded, encoding="utf-8")
    print(MARKER + encoded, flush=True)
    return 0 if result["execution_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

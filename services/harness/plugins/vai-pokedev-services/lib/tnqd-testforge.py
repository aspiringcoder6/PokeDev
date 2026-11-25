"""Real TestForge recorder in its worker image, on the bound TNQD Sandbox artifact."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen
from urllib.parse import parse_qs,urlsplit

TARGET="http://127.0.0.1:8088/"

def main():
    sys.path.insert(0,"/app")
    from playwright.sync_api import sync_playwright,expect
    from src.agent1.explorer.playwright_driver import PlaywrightDriver
    from src.agent1.explorer.recorder import TraceRecorder
    from src.agent1.explorer.session import ExplorationSession
    binding=json.loads(urlopen(TARGET+"__pokedev/binding").read())
    assert binding["preview_id"]==sys.argv[1]
    result={**binding,"framework":"TestForge TraceRecorder","backend_java_verified":False,"rbac_backend_verified":False,"verification_evidence":False}
    session=ExplorationSession(output_root="tnqd-evidence",base_url=TARGET,actor="tnqd-readonly-fixture",total_deadline_ms=145000,run_id="TNQD-"+sys.argv[1])
    class PrivateDriver(PlaywrightDriver):
        def storage_entries(self):return []
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(viewport={"width":1440,"height":960})
        page=context.new_page();requests=[];errors=[]
        page.on("request",lambda request:requests.append(request.url) if "/youths/filter" in request.url else None)
        page.on("pageerror",lambda error:errors.append(str(error)[:600]))
        recorder=TraceRecorder(session,PrivateDriver(page,actor="tnqd-readonly-fixture"),step_deadline_ms=20000)
        keyword=lambda:page.get_by_placeholder("Tìm kiếm theo Họ và tên, Số CCCD",exact=True)
        def open_app(_):
            page.goto(TARGET,wait_until="domcontentloaded")
            page.get_by_role("button",name="Đăng nhập nhanh Dev").click(timeout=15000)
            expect(keyword()).to_be_visible(timeout=15000)
            expect(page.locator(".pagination-left")).to_contain_text("45",timeout=15000)
        def reset_page(_):
            page.locator("vts-pagination").get_by_text("3",exact=True).click()
            expect(page.locator(".pagination-item-active, .vts-pagination-item-active").first).to_contain_text("3")
            keyword().fill("DEMO-AN")
            expect(page.locator("tbody")).to_contain_text("DEMO-AN",timeout=10000)
            expect(page.locator(".pagination-left")).to_contain_text("3")
            last=parse_qs(urlsplit(requests[-1]).query)
            assert last.get("page")==["0"],"Đổi từ khóa chưa về trang đầu"
        def latest_query(_):
            keyword().fill("DEMO-AN")
            keyword().press("Enter")
            page.wait_for_timeout(120)
            keyword().fill("DEMO-BINH")
            keyword().press("Enter")
            expect(page.locator("tbody")).to_contain_text("DEMO-BINH",timeout=10000)
            page.wait_for_timeout(1100)
            expect(page.locator("tbody")).not_to_contain_text("DEMO-AN")
            expect(page.locator(".pagination-left")).to_contain_text("4")
        def empty(_):
            keyword().fill("DEMO-KHONG-CO")
            expect(page.locator(".no-data-wrapper")).to_be_visible(timeout=10000)
            expect(page.locator(".pagination-left")).to_contain_text("0")
        def error_retry(_):
            keyword().fill("DEMO-ERROR")
            expect(page.get_by_text("Lỗi đọc dữ liệu demo. Vui lòng thử lại.",exact=False).first).to_be_visible(timeout=10000)
            keyword().fill("DEMO-BINH")
            expect(page.locator("tbody")).to_contain_text("DEMO-BINH",timeout=10000)
        def readonly(_):
            expect(page.get_by_role("button",name="Thêm mới",exact=True)).to_have_count(0)
            assert not [u for u in requests if not u.startswith(TARGET)],"Request ngoài Sandbox"
        def mobile(_):
            page.set_viewport_size({"width":390,"height":844})
            expect(keyword()).to_be_visible()
            keyword().fill("DEMO-AN")
            expect(page.locator("tbody")).to_contain_text("DEMO-AN",timeout=10000)
            bounds=keyword().bounding_box()
            assert bounds and bounds["x"]>=0 and bounds["x"]+bounds["width"]<=391,"Ô tìm kiếm tràn viewport 390px"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"),"Trang tràn ngang"
        actions=[("AC00-LOAD","Mở Angular thật và nhận đủ 45 hồ sơ mẫu",open_app),("AC01-BROWSER","Tìm từ trang 3 trở về trang đầu, đúng ba hồ sơ",reset_page),("AC06-BROWSER","Truy vấn mới thắng khi phản hồi cũ trả chậm",latest_query),("AC07-BROWSER","Danh sách rỗng hiển thị rõ, tổng số bằng 0",empty),("AC08-BROWSER","Thông báo lỗi đọc và tìm lại thành công",error_retry),("AC11-BROWSER","Profile chỉ đọc không hiện thao tác thêm mới",readonly),("AC12-BROWSER","Tìm kiếm dùng được ở viewport 390px",mobile)]
        for index,(_,label,callback) in enumerate(actions,1):
            recorder.record("STEP-1-"+str(index),label,"ASSERT",callback,target=label)
        summary=session.finalize(required_steps=["STEP-1-"+str(i) for i in range(1,len(actions)+1)])
        tests=[{"id":actions[i][0],"label":row["user_intent"],"status":"PASS" if row["status"]=="GROUNDED" else "FAIL",**({"error":str(row.get("observed_ui",{}).get("error","Assertion failed"))[:1200]} if row["status"]!="GROUNDED" else {})} for i,row in enumerate(session.records)]
        result.update(tests=tests,total=len(tests),passed=sum(t["status"]=="PASS" for t in tests),native_run_id=session.run_id,artifact_directory=str(session.root),summary=summary,page_errors=errors)
        context.close();browser.close()
    Path("tnqd-testforge-result.json").write_text(json.dumps(result,ensure_ascii=False),encoding="utf8")
    print("TNQD_TESTFORGE:"+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":main()

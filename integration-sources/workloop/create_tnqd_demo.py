"""Create/reuse the owned TNQD demo delivery through authenticated PokeDev APIs."""
from pathlib import Path
import json
from uuid import uuid4
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "adlc-flow/data/tnqd-live/demo-session.json"

def main():
    credentials = dotenv_values(ROOT / ".env.pokedev-login")
    with httpx.Client(base_url="http://127.0.0.1:7860", timeout=90, trust_env=False) as client:
        login = client.post("/api/v1/login", data={"username": credentials["POKE_DEV_USERNAME"], "password": credentials["POKE_DEV_PASSWORD"]})
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        if RECORD.exists():
            record = json.loads(RECORD.read_text(encoding="utf8"))
        else:
            title = "TNQD — Workloop cải thiện tìm kiếm"
            flow = client.post("/api/v1/flows/", json={"name": title, "data": {"nodes": [], "edges": []}, "description": "Demo TNQD: tài liệu Memory, task chi tiết, DAG song song và Sandbox."})
            flow.raise_for_status()
            requirement = ("Triển khai pilot TNQD tìm kiếm danh sách cán bộ, đoàn viên, thanh niên trên source tnqd-sut@791910a9d11c5884e057cf09cc07bd62c2175558. "
                "Khi đổi điều kiện tìm kiếm thì về trang đầu; chuyển trang chủ động giữ đúng trang. Nối loading thật, phân biệt rỗng/lỗi và ngăn phản hồi cũ kể cả Promise tải quyền. "
                "Dùng ba mẫu memoryTestDocs; Memory cung cấp context có nguồn, BA điền spec, Planner tạo nhiều task cụ thể. "
                "Cho Developer/Tester chạy song song trên snapshot/checkout riêng; khóa test từ yêu cầu và Verify độc lập sau khi nhận đủ artifact. "
                "Build source Angular thật; demo với 45 hồ sơ giả lập và profile quyền chỉ đọc, không tuyên bố đã chứng nhận backend Java hay RBAC server. "
                "Deploy Sandbox, chạy TestForge, trả UI gọn gàng cùng bằng chứng song song/DAG/phụ thuộc. Cập nhật tài liệu theo phát hiện đã kiểm chứng và đọc lại trong context mới. "
                "Được phép chạy nghiệm thu demo, dừng ở bản thay đổi chờ bàn giao; không tự merge hay phát hành vào TNQD đang dùng.")
            created = client.post("/api/v1/adlc/deliveries", json={"flow_id": flow.json()["id"], "title": title, "requirement": requirement})
            created.raise_for_status()
            identity = created.json()["id"]
            view = client.get("/api/v1/adlc/deliveries/" + identity); view.raise_for_status()
            record = {"delivery_id": identity, "flow_id": flow.json()["id"], "cycle_id": view.json()["cycle"]["id"], "run_id": str(uuid4())}
            RECORD.write_text(json.dumps(record, indent=2), encoding="utf8")
        response = client.post("/api/v1/adlc/deliveries/" + record["delivery_id"] + "/tnqd-demo/plan", json={"cycle_id": record["cycle_id"], "run_id": record["run_id"]})
        response.raise_for_status()
        print(json.dumps({**record, "state": response.json()["state"], "url": "http://127.0.0.1:7860/work/" + record["delivery_id"] + "?view=results"}, ensure_ascii=False))

if __name__ == "__main__":
    main()

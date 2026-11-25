# Duo Workflow Standalone Broker

Broker là thành phần trung gian (HTTP & WebSocket Gateway) giúp kết nối và định tuyến các yêu cầu hành động giữa **Coding Agent (Langflow)** và **Standalone Executor (Runner)** chạy trong môi trường CI/CD.

## Kiến trúc Giao tiếp
```
┌─────────────────┐             ┌─────────────────┐             ┌─────────────────┐
│  Coding Agent   │───[HTTP]───>│     Broker      │<───[WS]─────│   Standalone    │
│   (Langflow)    │             │  (Port 8000)    │             │    Executor     │
└─────────────────┘             └─────────────────┘             └─────────────────┘
```

1. **Standalone Executor** (CI Runner) chủ động kết nối lên cổng `/ws` của Broker và truyền các tham số: `session_id`, `flow_id`, `goal`.
2. **Broker** tiếp nhận kết nối, ánh xạ session và tự động trigger cuộc gọi HTTP POST tới **Langflow API** để chạy Flow.
3. Trong quá trình chạy, **Coding Agent** gọi các tool bằng cách gửi HTTP POST `/execute` kèm `session_id` tới Broker.
4. **Broker** định tuyến lệnh qua WebSocket xuống **Executor** tương ứng để chạy trực tiếp trên Workspace.
5. Khi **Langflow** chạy xong, Broker nhận được phản hồi HTTP và gửi sự kiện kết thúc (`type: completed`) để **Executor** tự đóng kết nối và thoát an toàn.

---

## Yêu cầu Hệ thống
* Python 3.10+
* Các thư viện: `fastapi`, `uvicorn`, `pydantic`

## Cài đặt thư viện
Bạn có thể cài đặt các dependencies bằng `pip` hoặc `uv`:
```bash
pip install fastapi uvicorn pydantic
# Hoặc dùng uv:
uv pip install fastapi uvicorn pydantic
```

---

## Cấu hình Biến môi trường
Trước khi chạy Broker, cấu hình các biến môi trường sau nếu cần thiết:

| Biến môi trường | Ý nghĩa | Giá trị mặc định |
| :--- | :--- | :--- |
| `LANGFLOW_SERVICE_URL` | URL dịch vụ Langflow | `http://localhost:7860` |
| `LANGFLOW_SERVICE_TOKEN` | Token xác thực (API Key) của Langflow | *Trống* |

---

## Hướng dẫn Chạy
Chạy Broker bằng lệnh sau từ thư mục chứa file `broker.py`:
```bash
python broker.py
# Hoặc sử dụng uvicorn trực tiếp:
uvicorn broker:app --host 0.0.0.0 --port 8000 --reload
```

Sau khi khởi chạy thành công, Broker sẽ hoạt động tại địa chỉ: `http://localhost:8000`.

---

## Chi tiết API Endpoints

### 1. HTTP GET `/`
Kiểm tra trạng thái Broker và lấy danh sách các runner/session đang kết nối.
* **Response**:
  ```json
  {
    "status": "ok",
    "active_runners_count": 1,
    "active_sessions": ["test-session-001"]
  }
  ```

### 2. WebSocket `/ws`
Endpoint kết nối dành cho các Standalone Executor.
* **Payload lúc đăng ký (register)**:
  ```json
  {
    "type": "register",
    "role": "executor",
    "sessionid": "unique-session-id",
    "flowid": "langflow-flow-uuid",
    "goal": "Nhiệm vụ cần thực hiện..."
  }
  ```

### 3. HTTP POST `/execute`
Endpoint dành cho Coding Agent gửi yêu cầu hành động xuống Executor.
* **Payload**:
  ```json
  {
    "session_id": "unique-session-id",
    "action": {
      "runCommand": {
        "command": "npm test"
      }
    }
  }
  ```

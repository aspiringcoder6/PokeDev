# Kiểm tra bộ local PokeDev

Ngày kiểm tra: **25/11/2026**. Môi trường: Windows, Docker Desktop Linux engine, Python 3.14 cho backend.

## Kết quả

- `python deploy/local/stack.py build`: build đủ 6 image PokeDev: app, Harness, Sandbox broker, VFS, Memory và TestForge.
- `python deploy/local/stack.py up --no-build`: khởi động đủ 10 service trong project `pokedev-local`; helper cập nhật phiên Harness cho backend.
- Backend `/health_check`: `status=ok`, `db=ok`, `chat=ok`, dùng PostgreSQL 17 và Redis.
- Giao diện: trang gốc có title PokeDev; JavaScript/CSS đã build được phục vụ với HTTP 200.
- Harness: native API phản hồi có xác thực, plugin lock hợp lệ; SDK Python đăng nhập và đọc capabilities thành công. Tools Sandbox/TestForge sẵn sàng.
- Sandbox: tạo container `python:3.12-alpine`, thực thi Python, nhận `pokedev-smoke-ok` với exit code 0; xóa phiên/container thử thành công.
- OpenSandbox: `/health` trả HTTP 200.
- Memory API: `/health` trả HTTP 200. MCP khởi tạo phiên và liệt kê được 5 tools.
- TestForge: health HTTP 200, kết nối Memory thành công; k6 chạy được; Chromium headless mở và đọc nội dung trang thử thành công.
- Backend chạy trực tiếp trên máy: SQLite, UI và `/health_check` hoạt động trước khi chuyển sang kiểm tra Docker.

## Kiểm tra hồi quy

| Nhóm | Kết quả |
|---|---|
| Khởi tạo cấu hình, cách ly thông tin đăng nhập, reconnect helper | 5 passed |
| Cấu hình model Harness, xử lý ký tự YAML và cấu hình thiếu | 3 passed |
| Backend services, executor router và Harness client | 24 passed |
| Product-cycle migration với SQLite | 5 passed |
| Product-cycle migration với PostgreSQL | 4 passed |

PostgreSQL viết lại biểu thức CHECK và báo index đi kèm UNIQUE constraint khác SQLite. Migration đã được sửa để so sánh biểu thức sau khi PostgreSQL chuẩn hóa và loại index trùng constraint. Các kiểm tra vẫn xác nhận từ chối schema có CHECK bị nới lỏng, thiếu index hoặc bảng đã có dữ liệu. Các test PostgreSQL dùng schema riêng và rollback sau mỗi test; không xóa database local.

Manifest đã đối chiếu SHA-256 cho 2.047 file service snapshot. Không phát hiện token theo các mẫu GitHub/Slack hoặc private key trong snapshot; không có file source cần cho build bị Git bỏ qua.

## Chưa được kiểm chứng bằng model thật

Chưa cấu hình API key/provider/model hoặc repository nghiệp vụ, nên chưa chạy tác vụ LLM có phí. Harness phục vụ bình thường nhưng `execution_ready`, `driver_ready`, `artifacts_ready` hiện là `false`; cần cấu hình theo [hướng dẫn Harness](../services/harness/README.md).

Memory API/MCP hoạt động, nhưng bộ bridge PokeDev chưa có đủ các tool `memory_health`, `memory_remember`, `memory_context`. Luồng live project dùng Workloop và adapter nghiệp vụ Gitea cũng chưa được chuyển đổi trong đợt thiết lập local này. Xem phạm vi trong [README](../Readme.md).

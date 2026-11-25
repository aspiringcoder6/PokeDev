# vai-taskloop

> **Subagent Contract Task Loop Plugin for DeepSeek Harness (DSH)**  
> Biểu mẫu giao việc & ký hợp đồng chuẩn mực cho Subagent (Subagent-Driven Development).

---

## 🌟 Tính năng

1. **Giao việc chuẩn hóa theo Subagent-Driven Development:**
   - Dựa trên template chuẩn [`implementer-prompt.md`](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/implementer-prompt.md).
   - Đầy đủ 3 phần cấu trúc nghiêm ngặt:
     - **Phần 1: Nhiệm vụ** (Tên task, số thứ tự Task $N$, model bắt buộc).
     - **Phần 2: Tệp và thư mục** (Task brief `BRIEF_FILE`, Thư mục làm việc, Tệp báo cáo `REPORT_FILE`).
     - **Phần 3: Bối cảnh** (Scene-setting, dependencies, architectural context).
2. **Giao diện tối giản (Minimal Editorial Paper):**
   - Thiết kế theo chuẩn giao diện biểu mẫu thanh lịch (`Form giao việc cho Subagent (1).html`).
   - Hỗ trợ 2 chế độ: **Chỉnh sửa** (Form input) và **Xem trước** (Render tài liệu Markdown theo dòng thời gian).
   - Nút **Sao chép prompt** với validation model bắt buộc.
3. **Tích hợp Native DeepSeek Harness Client:**
   - Đăng ký tab `sidebarRightTabs` (bắt các file `*.task.json`, `*.taskloop.json`, `task-*.json`).
   - Tự động mở khung tab khi Agent gọi tool tạo hoặc cập nhật task qua Server-Sent Events (SSE).
4. **5 Atomic Tools cho AI Agent:**
   - `taskloop_create_task`: Khởi tạo contract task mới.
   - `taskloop_get_task`: Lấy thông tin task và prompt đã render.
   - `taskloop_update_task`: Cập nhật trạng thái hoặc các trường dữ liệu.
   - `taskloop_add_comment`: Thêm ghi chú review / câu hỏi làm rõ.
   - `taskloop_export_prompt`: Xuất chuỗi prompt hoàn chỉnh để gửi cho Subagent.

---

## 🛠 HTTP Endpoints

| Method | Endpoint | Mô tả |
|---|---|---|
| `GET` | `/api/taskloop/viewer/*` | Giao diện form tương tác |
| `GET` | `/api/taskloop/events?session=...` | Luồng SSE phát sự kiện real-time |
| `GET` | `/api/taskloop/current?session=...&file=...` | Lấy dữ liệu contract JSON hiện tại |
| `POST` | `/api/taskloop/save?session=...` | Lưu dữ liệu biểu mẫu từ người dùng |

---

## 📄 License
MIT © vAiPlatform Team

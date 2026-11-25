---
name: vai-taskloop
description: >
  Kỹ năng quản lý vòng lặp giao việc và thực thi Subagent chuẩn mực (Subagent-Driven Development).
  Cung cấp quy trình ký hợp đồng task chặt chẽ 3 phần, lựa chọn model tối ưu, kiểm soát chất lượng qua TDD,
  tự động render và đồng bộ giao diện form tương tác thời gian thực.
---

# vai-taskloop — Cẩm Nang Giao Việc & Vòng Lặp Subagent (v1.0)

> **Nguyên tắc số 1 (Hợp đồng rõ ràng):** Mọi công việc giao cho Subagent phải được định nghĩa chặt chẽ qua Task Contract gồm 3 phần: **Nhiệm vụ & Model**, **Tệp & Thư mục**, **Bối cảnh kiến trúc**.  
> **Nguyên tắc số 2 (Độc lập tác chiến):** Subagent tự chịu trách nhiệm thực thi toàn bộ task được giao. **TUYỆT ĐỐI KHÔNG** để Subagent tự spawn thêm subagent con hoặc tự sinh reviewer. Việc review là thẩm quyền của Controller!  
> **Nguyên tắc số 3 (Bằng chứng kiểm thử - TDD Evidence):** Hoàn thành công việc phải đi kèm bằng chứng lệnh chạy test (`RED` -> `GREEN`) và diff sạch sẽ.  
> **Nguyên tắc số 4 (Minh bạch khi bế tắc):** Nếu gặp rào cản kiến trúc hoặc thiếu thông tin, dừng lại và báo cáo ngay với trạng thái `BLOCKED` hoặc `NEEDS_CONTEXT`.

---

## 1. Cấu Trúc Hợp Đồng Giao Việc (3 Phần Chặt Chẽ)

Mỗi Task trong vòng lặp phải tuân theo mẫu chuẩn `implementer-prompt.md`:

### Phần 1: Nhiệm vụ (Task Specification)
- **Tên task (`name`):** Mô tả ngắn gọn, hành động rõ ràng (ví dụ: `Thêm API auth JWT`, `Tối ưu query PostgreSQL`).
- **Số thứ tự (`n`):** Số thứ tự task trong kế hoạch tổng thể ($1, 2, 3...$).
- **Lựa chọn Model (`model`):**
  - `haiku`: Các task đơn giản, viết boilerplate, tạo CRUD cơ bản, sửa lỗi chính tả, viết script phụ trợ.
  - `sonnet`: Các tính năng chính, tích hợp module, refactor logic, viết unit test phức tạp.
  - `opus` / `deepseek-chat`: Bài toán thuật toán phức tạp, thiết kế kiến trúc lõi, xử lý concurrency hoặc failover nhạy cảm.

### Phần 2: Tệp và Thư mục (Workspace & Artifacts)
- **Task brief (`brief`):** Đường dẫn tới file đặc tả chi tiết (ví dụ: `docs/plans/task-1-brief.md`).
- **Thư mục làm việc (`dir`):** Đường dẫn gốc subagent thao tác (ví dụ: `/app/workspace`).
- **Tệp báo cáo (`report`):** Nơi subagent ghi lại toàn bộ nhật ký kết quả và bằng chứng test (ví dụ: `reports/task-1-report.md`).

### Phần 3: Bối cảnh kiến trúc (`ctx`)
- Vị trí của task trong toàn bộ hệ thống.
- Các module hoặc task tiền nhiệm mà task này kế thừa.
- Các ràng buộc phi chức năng (bảo mật, hiệu năng, không phá vỡ API cũ).

---

## 2. Bảng 5 Công Cụ Quản Lý TaskLoop (Agent Tools)

| Tool | Mục đích | Tham số cốt lõi |
|---|---|---|
| `taskloop_create_task` | Khởi tạo hợp đồng task mới, tự động render prompt và cập nhật Form web | `n`, `name`, `model`, `brief`, `dir`, `report`, `ctx` |
| `taskloop_get_task` | Đọc toàn bộ hợp đồng hiện tại cùng prompt template đã ráp thông số | _(không tham số)_ |
| `taskloop_update_task` | Cập nhật tiến độ (`status`), điều chỉnh yêu cầu hoặc bổ sung bối cảnh | `status`, `name`, `model`, `brief`, `dir`, `report`, `ctx` |
| `taskloop_add_comment` | Ghi nhận phản hồi của người dùng hoặc controller vào hợp đồng | `author`, `text` |
| `taskloop_export_prompt` | Xuất chuỗi prompt hoàn chỉnh chuẩn bị dispatch cho Subagent | _(không tham số)_ |

---

## 3. Vòng Đời Thực Thi Vòng Lặp (Execution Lifecycle)

```
[1. Lập Hợp đồng] -> [2. Soạn Task Brief] -> [3. Dispatch Subagent] -> [4. Subagent TDD & Báo cáo] -> [5. Controller Review & Chốt]
```

### Bước 1: Khởi tạo Hợp đồng Task
Gọi `taskloop_create_task` để đưa dữ liệu vào hệ thống và kích hoạt giao diện Form web:
```json
{
  "n": "1",
  "name": "Triển khai Auth Controller",
  "model": "sonnet",
  "brief": "docs/plans/task-1-brief.md",
  "dir": "/app/workspace",
  "report": "reports/task-1-report.md",
  "ctx": "Nối tiếp cấu trúc DB ở Task 0, sử dụng bcrypt và JWT chuẩn."
}
```

### Bước 2: Chuẩn bị Task Brief
Viết nội dung đầy đủ vào file brief được chỉ định (`docs/plans/task-1-brief.md`):
- Acceptance Criteria chi tiết.
- Danh sách file cần sửa / tạo mới.
- Các ca kiểm thử cần pass.

### Bước 3: Dispatch Subagent
Lấy prompt qua `taskloop_export_prompt` (hoặc dùng prompt tạo sẵn) và chuyển cho Subagent thực thi.

### Bước 4: Subagent Thực thi & Tự Review (Self-Review)
Subagent tuân thủ nghiêm ngặt 6 bước:
1. Đọc kỹ Task Brief.
2. Viết kiểm thử theo TDD (nếu yêu cầu).
3. Triển khai code tính năng.
4. Xác minh kiểm thử toàn diện.
5. Tự đọc lại git diff của chính mình (Self-review).
6. Ghi báo cáo đầy đủ vào `report` và phản hồi tóm tắt dưới 15 dòng với status:
   - `DONE`: Hoàn thành xuất sắc, test pass 100%.
   - `DONE_WITH_CONCERNS`: Đã xong nhưng có điểm nghi ngại về kiến trúc.
   - `BLOCKED`: Gặp lỗi tắc nghẽn không thể tự giải quyết.
   - `NEEDS_CONTEXT`: Thiếu thông tin hoặc đặc tả chưa rõ ràng.

### Bước 5: Controller Đánh giá & Hoàn tất
- Nếu đạt yêu cầu: Gọi `taskloop_update_task({ "status": "DONE" })`.
- Nếu có lỗi hoặc cần chỉnh sửa: Gọi `taskloop_add_comment` ghi chú điểm cần sửa, sau đó dispatch lại để Subagent khắc phục.

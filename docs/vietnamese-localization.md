# Giao diện tiếng Việt

Ứng dụng mặc định dùng tiếng Việt khi chưa có lựa chọn ngôn ngữ được lưu.
Người dùng có thể đổi ngôn ngữ tại **Cài đặt → Chung → Ngôn ngữ**; lựa chọn
được giữ lại khi tải lại trang. Các mã như `vi-VN` được chuẩn hóa thành `vi`.

## Phạm vi

- Điều hướng, dự án, thư viện package, trình dựng workflow và cấu hình giai đoạn.
- Blueprint, đề xuất và phê duyệt kế hoạch, lịch sử và chi tiết lượt chạy.
- Harness, đặc tả, xác minh, replay, bộ nhớ và báo cáo.
- Studio, đăng nhập, cài đặt, chat, trình sửa thành phần và thông báo.
- Tên hiển thị, mô tả, hướng dẫn trường và mẫu khởi đầu do backend cung cấp.

Giữ các thuật ngữ phổ biến như API, SDK, Git, branch, commit, token, workflow,
Agent, model, Blueprint và sandbox cùng tên sản phẩm. Tên dự án, nội dung do
người dùng nhập, đường dẫn, mã nguồn và các định danh API được giữ nguyên.
Trạng thái được dịch khi hiển thị; giá trị gửi tới backend không đổi.

## Duy trì bản dịch

| Nguồn | Vai trò |
| --- | --- |
| `adlc-flow/frontend/src/locales/vi.json` | 2.370 khóa của giao diện dùng i18next hiện có |
| `adlc-flow/frontend/src/locales/vi-ui.json` | Nội dung giao diện ADLC và các chuỗi trước đây viết trực tiếp |
| `adlc-flow/langflow/locales/vi.json` | 2.657 khóa metadata thành phần và mẫu khởi đầu |
| `adlc-flow/frontend/src/i18n/ui.ts` | Dịch nhãn hiển thị, trạng thái và ngày giờ |

Với giao diện dùng khóa có sẵn, bổ sung bản dịch vào `vi.json` tương ứng với
`en.json`. Với nội dung ADLC, dùng `translateUi("English source")` và thêm
chuỗi nguồn cùng bản dịch vào `vi-ui.json`. Giữ nguyên placeholder `{{...}}`,
thẻ định dạng và đoạn mã. `useUiLocale()` giúp thành phần dùng `translateUi`
cập nhật ngay khi người dùng đổi ngôn ngữ; thành phần đã dùng `useTranslation`
không cần thêm hook này. Không dịch khóa dữ liệu, giá trị trạng thái hoặc nội
dung người dùng để gửi qua API.

Backend tự nạp locale `vi` từ tệp JSON và dùng header `Accept-Language` của
frontend. Khi đổi ngôn ngữ, danh mục thành phần được tải lại để cập nhật metadata.

## Kiểm tra

Các bài kiểm tra kiểm tra độ phủ khóa, placeholder, đổi ngôn ngữ, lựa chọn đã
lưu, tìm package bằng tiếng Việt, nội dung người dùng và việc giữ nguyên định
danh API. Luồng Studio được kiểm tra trên trình duyệt ở 1.440 px và 390 px,
qua các bước tạo yêu cầu, duyệt kế hoạch, chạy mô phỏng và bàn giao. Kiểm tra
này sử dụng dữ liệu mô phỏng của Studio, không gọi nhà cung cấp AI trực tiếp.

Kết quả kiểm tra ngày 17/10/2026: 1.115 bài frontend trong 104 bộ kiểm tra và
17 bài backend liên quan đạt. Bản build production thành công. So sánh TypeScript
ghi nhận 281 lỗi đã có trước và không có lỗi mới do bản Việt hóa. Kiểm tra
trình duyệt không ghi nhận lỗi JavaScript hoặc cuộn ngang ở hai kích thước trên;
lựa chọn tiếng Anh được giữ đúng sau khi tải lại trang.

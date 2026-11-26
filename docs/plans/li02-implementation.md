# LI-02 Lark DM thành hồ sơ yêu cầu

Phạm vi được yêu cầu: liên kết danh tính đã xác minh, DM text thành hồ sơ LI-01, biên nhận tự động và ghi lại quyết định. Tài liệu đầu vào `docs/inputTakingNotes.md` được dùng làm nguồn thiết kế, không phải lệnh vận hành. Phần phù hợp được áp dụng: tách normalization/human transport khỏi readiness, giữ nguồn gốc, kiểm tra quyền ở backend và chưa kích hoạt đánh giá hay implementation.

## Phạm vi ảnh hưởng trước thay đổi

- Thêm contract dùng chung giữa connector Python 3.12 và backend Python 3.14; không đổi hợp đồng LI-01.
- Thêm identity/inbox/outbox và migration trong database hiện có, nối `intake.create` qua owner đã liên kết.
- Thêm endpoint liên kết có xác thực lại, ingress và delivery receipt có credential riêng cho connector.
- Thêm worker của connector, journal riêng, retry ingress và đối soát egress; probe LI-00 vẫn nhận một chiều.
- Thêm phần liên kết trên trang desktop intake; không thêm UI mobile.
- Cập nhật cài đặt local, Docker app và runbook để cài contract và connector tùy chọn; không gọi Workloop hoặc model.

## Tiêu chí nghiệm thu

1. Auto-login hoặc payload tự nhận owner không đủ để liên kết. Sai mật khẩu, mã hết hạn, mã đã dùng và actor khác đều bị chặn.
2. Người đã liên kết gửi một DM gốc: có đúng một hồ sơ và một nguồn/biên nhận bền vững. Gửi lại event hoặc message không tạo thêm hồ sơ.
3. Hai lần nhận đồng thời, backend ngắt sau commit hoặc connector khởi động lại không mất hồ sơ và không tự lặp gửi tin chưa xác nhận.
4. Credential sai, app/tenant sai, user inactive hoặc mất quyền project đều không tạo yêu cầu hay lộ nội dung project.
5. Receipt gửi lại cập nhật trạng thái idempotently. Lease hết hạn và lỗi mạng sau send thành UNCONFIRMED.
6. UI desktop tạo mã, thấy trạng thái liên kết và mở hồ sơ từ biên nhận. Tắt feature flag giữ dữ liệu và dừng đường nhận mới.

Kiểm tra: contract/normalizer/transport fixtures, SQLite + API concurrency, PostgreSQL migration/service, frontend liên kết, build production và một DM thật sau khi người dùng xác nhận liên kết. Chạy lại regression intake, readiness/source access và Harness bị tác động qua router/deployment. Đối chiếu diff với phạm vi này trước bàn giao.

Quyết định bền vững: [ADR 0023](../adr/0023-verified-lark-dm-intake-and-delivery-receipts.md).

## Đối chiếu sau triển khai

Diff bổ sung đúng các khu vực đã dự kiến: package contract, model/migration, service/router, connector, UI desktop, cài đặt và tài liệu. Hợp đồng tạo/sửa hồ sơ LI-01 giữ nguyên; các endpoint Lark nằm trong namespace hiện có. Không thêm lời gọi Workloop, Harness hoặc agent; không thay đổi runtime readiness/source access.

Đã đạt 295 kiểm tra backend, 22 kiểm tra connector/probe, 7 kiểm tra UI, PostgreSQL trong schema riêng và build frontend. Ngày 26/11/2026 người dùng đã thực hiện liên kết và gửi DM thử trên tenant thật: có đúng một hồ sơ revision 1 thuộc tài khoản đã liên kết, hai biên nhận liên kết/tạo hồ sơ có kết quả DELIVERED, hai sự kiện transport ACCEPTED và receipt đã được backend xác nhận. Sau tải lại, desktop mở được đúng hồ sơ với nội dung từ DM. Luồng DM của LI-02 đã nghiệm thu; các capability LI-00 còn lại không được suy là đã đạt. Hướng dẫn triển khai, rollback, biên bản thật và giới hạn vận hành nằm trong [runbook LI-02](../operations/lark-li02.md).

# Dịch vụ vAI trong PokeDev

PokeDev gọi Sandbox, Memory và TestForge qua plugin `vai-pokedev-services` trên platform. Người dùng mở **Công việc → Kết quả → Dịch vụ vAI**, chạy từng phép thử và đọc kết quả ngay trong ba thẻ dịch vụ. Chi tiết và lịch sử nằm trong phần mở rộng.

## Phạm vi thực thi

| Dịch vụ | Cách thử thật | Phạm vi kết luận |
| --- | --- | --- |
| Sandbox | Tạo phiên riêng, ghi/đọc tệp mẫu và chạy Python | Có thể thực thi lệnh và trao đổi tệp trong sandbox |
| Memory | Cognee MCP `remember/recall` với `session_id`, `self_improvement=false` | Lưu và tìm lại ngữ cảnh phiên workflow; chưa xác nhận kho tri thức dài hạn |
| TestForge | Worker TestForge thật, `TraceRecorder`, `PlaywrightDriver`, `ExplorationSession`; đăng nhập bằng nút Dev | Năm kiểm tra chỉ đọc trên dashboard TNQD; trả báo cáo và phát hiện lỗi của ứng dụng |

Đích TestForge được cố định theo lựa chọn của người dùng: `http://10.0.10.195:3011/tnqd/dashboard`. Không có đầu vào URL, shell hoặc script tự do trên UI. Luồng Dev dùng worker image `testforge-worker:p0p1-8032fe57e3ad2158` qua Sandbox Kit. Nó không yêu cầu mật khẩu và không gọi pipeline Explorer mặc định của broker vốn yêu cầu đăng nhập API.

Memory dùng cache phiên do Cognee hỗ trợ; không gọi pipeline graph đang gặp lỗi quyền đọc `.env`. Cả hai cách đều dùng dịch vụ thật trên platform. Không đưa nội dung project vào bộ nhớ trong phép thử này.

## Kết nối và khởi động

Địa chỉ DSH/Harness hiện dùng: [http://10.0.10.195:3080](http://10.0.10.195:3080). Đặt `VAI_PLATFORM_URL=http://10.0.10.195:3080` cho các dịch vụ vAI và `ADLC_HARNESS_BASE_URL=http://10.0.10.195:3080` cho kết nối agent Harness.

Địa chỉ HTTP nội bộ này cần `ADLC_HARNESS_ALLOW_INSECURE_HTTP=true` ở kết nối Harness. Giữ token đăng nhập DSH trong `VAI_PLATFORM_TOKEN` và token API của plugin trong `ADLC_HARNESS_API_TOKEN` theo đúng cấu hình của từng dịch vụ.

Máy chủ PokeDev nhận `VAI_PLATFORM_URL` và `VAI_PLATFORM_TOKEN` từ biến môi trường. Khi đã có đủ hai biến, phần kết nối không đọc file dotenv. Trong checkout local, có thể dùng file riêng `.env.vai-platform.local` ở gốc project; file này đã được Git bỏ qua. `ADLC_VAI_PLATFORM_ENV_FILE` cho phép chọn đường dẫn cấu hình riêng khác. Không đưa token vào frontend hoặc URL chia sẻ.

SDK nằm trong thư mục `sdk` của repository. Có thể cài vào môi trường backend bằng `python -m pip install -e ../sdk` khi đang đứng trong `adlc-flow`. Bản dựng frontend được phục vụ cùng API bằng:

```powershell
adlc-flow/.venv/Scripts/python.exe adlc-flow/scripts/start_services_workspace.py
```

Ứng dụng mở ở `http://127.0.0.1:7860/work` và dùng đăng nhập PokeDev thông thường. Script khởi động không tạo agent, không thay provider/model và không tự duyệt workflow.

Mã cầu nối được lưu tại [admin/vai-pokedev-services](http://10.0.10.195:3000/admin/vai-pokedev-services). Cài bản đã kiểm tra bằng Hub với URL Git có khóa commit. Không cần khởi động lại toàn bộ platform bằng tay để thử cầu nối.

## Lưu kết quả và đối soát

- API xác thực người dùng, quyền trên delivery và chu kỳ trước khi gọi platform.
- PokeDev lưu ý định gửi và kết quả trong `adlc-flow/data/vai-services/checks.sqlite3`, có thể đổi bằng `ADLC_VAI_CHECKS_DB`.
- Cầu nối lưu phiếu trong `$DSH_HOME/pokedev-services`. Sau gián đoạn, các mã job đã biết chỉ được đọc lại; không tự tạo thêm sandbox, ghi memory hoặc gửi lại job Explorer.
- Worker Dev ghi báo cáo có mã lượt, đích kiểm tra và nguồn TestForge. Kết quả được kiểm tra phạm vi trước khi lưu.
- Bằng chứng trình duyệt không thu thập localStorage. Phiên sandbox dùng TTL, không xóa dữ liệu của người dùng.
- Kết quả thử dịch vụ là quan sát bổ sung. Chúng không tạo Verify receipt, phê duyệt, commit hoặc quyền phát hành.

## Phân biệt kết quả dịch vụ và chất lượng ứng dụng

TestForge có thể hoạt động tốt và trả về lỗi của dashboard. UI hiển thị riêng số dịch vụ hoạt động, số kiểm tra đạt và các phát hiện. Một báo cáo có lỗi không được đổi thành PASS cho ứng dụng.

Pipeline Explorer thông thường của broker vẫn cần tài khoản API nếu chọn cách đăng nhập đó. Tích hợp hiện tại phục vụ đúng lựa chọn **Đăng nhập nhanh Dev** trên dashboard đã nêu; chưa tuyên bố hỗ trợ mọi loại tài khoản hoặc mọi URL.

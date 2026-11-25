# Tích hợp intake và requirement readiness

Ngày 25/11/2026. Đã kiểm tra bản ghép giữa intake LI-01 (`3159af2`) và `Phuc/specification` (`7b9b33623444f689db28adb1c500059980ddf3f0`). Quyết định tích hợp branch đầy đủ, giữ readiness tắt mặc định cho đến khi cấu hình các dịch vụ và kênh tương tác thật.

## Các branch đã rà

| Branch và commit | Phạm vi | Quyết định |
|---|---|---|
| `codex/pokedev-fork-prep` tại `3159af2` | Hồ sơ intake, API và UI desktop, migration, probe Lark nhận sự kiện | Giữ làm đường tiếp nhận hiện tại |
| `Phuc/specification` tại `7b9b336` | Source access GitHub/Lark bằng app, readiness ba giai đoạn, câu hỏi và xác nhận, phân tích tác động, policy và handoff | Tích hợp sau kiểm tra kết hợp |
| `Phuc/specification-plan-b` tại `5635036` | Bản tách workflow readiness; vẫn import `source_access` đã bỏ khỏi branch | Không merge riêng; các file nghiệp vụ tương ứng đã có trong branch đầy đủ |

Plan B chưa chạy độc lập: router ứng dụng import readiness, còn readiness import bộ `source_access` không có trên branch đó. Branch đầy đủ cung cấp cả hai phần. Không xóa hay ghi đè branch của người đóng góp.

## Kết quả kiểm tra bản ghép

280 kiểm tra backend đã đạt trên môi trường PokeDev Python 3.14: 215 source access, 37 readiness, 14 intake và 14 Harness. Có hai cảnh báo cấu hình pytest `timeout`/`timeout_method` do môi trường kiểm tra không cài plugin timeout; các bài kiểm tra vẫn chạy hết. Ruff kiểm tra lỗi Python và import đã đạt.

Xung đột router đến từ thay đổi cùng file và khác line ending. Bản ghép giữ cả `/api/v1/adlc/intake` và `/api/v1/adlc/requirement-readiness`, cùng các router có sẵn. Các prompt readiness được bỏ dòng trống dư ở cuối file. Nội dung vendored được giữ nguyên để không đổi hash trong manifest.

Chạy lại từ gốc repository:

```powershell
$env:PYTHONPATH="$PWD/adlc-flow"
adlc-flow/.venv/Scripts/python.exe -m pytest -o addopts='' --confcutdir=adlc-flow/tests/unit/adlc adlc-flow/tests/unit/adlc/source_access adlc-flow/tests/unit/adlc/requirement_readiness adlc-flow/tests/unit/adlc/test_requirement_intake.py adlc-flow/tests/unit/adlc/test_harness_client.py -q
```

Đây là kiểm tra bằng fixture, database thử và lệnh native vô hại. Kiểm tra tenant GitHub/Lark thật, model và Spec Kit/OpenSpec vẫn cần cấu hình riêng theo [hướng dẫn readiness](requirement-readiness.md) và [source access](source-access.md).

## Ranh giới nối với các slice Lark

Intake LI-01 tiếp tục là hồ sơ riêng của user PokeDev. Readiness dùng service principal và source grant do backend cấu hình; hiện chưa có adapter tự chuyển hồ sơ intake sang readiness. HumanBridge cho chat/web cũng chưa được nối vào runtime mặc định. Vì vậy merge source chưa tạo ra vòng hỏi–đáp Lark đang hoạt động.

LI-02 cần liên kết danh tính đã xác minh và binding hội thoại trước. LI-04 sẽ tái sử dụng `ReadinessService`, `DshAgentRunner` và cơ chế câu hỏi đã lưu, bổ sung adapter từ intake và HumanBridge thay vì dựng một engine thứ hai. LI-06 sẽ dùng `SourceGateway`/reader hiện có, với grant suy ra từ project PokeDev và quyền người nhận. Không lấy nội dung mà bot đọc được làm bằng chứng mọi người trong nhóm đều có quyền xem.

Readiness dừng ở assessment/handoff. Chuyển kết quả đó thành Spec draft native vẫn thuộc LI-08. Quyết định chốt brief, chọn phương án và cho thực thi là những bước riêng.

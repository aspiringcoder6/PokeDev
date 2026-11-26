# Hồ sơ yêu cầu và kiểm chứng Lark

Cập nhật ngày 26/11/2026. LI-01 đã có backend và giao diện desktop để tạo, sửa và xem lịch sử yêu cầu. LI-02 đã có liên kết danh tính, DM intake và biên nhận tự động; kiểm tra tự động/PostgreSQL/build cùng thử liên kết, tạo hồ sơ và đối soát biên nhận trên tenant thật đã đạt. Xem [runbook LI-02](operations/lark-li02.md) và [ADR 0023](adr/0023-verified-lark-dm-intake-and-delivery-receipts.md). LI-00 đã qua kiểm tra offline và DM hai chiều trên tenant thật; các bài thử mention, callback, tài liệu và phục hồi còn chờ. Xem [biên bản pilot](operations/lark-pilot-20261125.md) và [kế hoạch các slice tiếp theo](plans/lark-intake-slices.md).

Đã rà và tích hợp phần source access/readiness từ `Phuc/specification` sau 280 kiểm tra kết hợp. Các module này là nền cho LI-04/LI-06, còn tắt mặc định và chưa nối với intake hoặc Lark HumanBridge. Xem [biên bản tích hợp](operations/branch-integration-20261125.md).

## Chạy và xem hồ sơ

Đặt `POKEDEV_INTAKE_ENABLED=true` trong `.env`, khởi động backend theo [README](../Readme.md), rồi mở [Tiếp nhận yêu cầu](http://127.0.0.1:7862/intake). Mẫu `.env.example` đã bật phần này; backend mặc định tắt khi không có cấu hình.

Mỗi hồ sơ có tiêu đề, mô tả, phạm vi cần làm, ngoài phạm vi, ràng buộc, tiêu chí nghiệm thu và giả định. Hồ sơ thuộc riêng người tạo. Có thể chưa gắn project; nếu gắn, project phải nằm trong catalog native mà người đó có quyền đọc. Project được giữ nguyên sau khi tạo. Khi quyền project bị thu hồi, hồ sơ gắn project đó không còn xuất hiện hoặc truy cập được.

Mỗi lần lưu tạo một phiên bản mới. Khi hai người dùng cùng tài khoản hoặc hai tab sửa từ cùng phiên bản, server chỉ nhận một lần sửa; tab còn lại giữ bản nháp và cho tải bản mới sau xác nhận. Nếu chưa biết lần lưu đã thành công hay chưa, giao diện giữ nguyên lệnh để thử lại và đối soát.

Tạo hồ sơ chỉ lưu yêu cầu. Nó chưa gọi model, tạo WorkflowRun, phê duyệt công việc hoặc bắt đầu thực thi. Thông tin nhập vào chưa được coi là brief đã chốt. LI-02 thêm đường nhận DM; chức năng agent hỏi lại, tài liệu có trích dẫn và card sẽ được nối qua các slice tiếp theo.

## API và lưu trữ

Các endpoint dùng xác thực PokeDev hiện có, cùng namespace ổn định `/api/v1/adlc/intake`:

| Phương thức | Đường dẫn | Kết quả |
|---|---|---|
| GET | `/projects` | Project native được phép chọn |
| GET | `/requests?limit=50&offset=0` | Danh sách riêng của người tạo |
| POST | `/requests` | Tạo bằng `command_id`, `project_id` tùy chọn và `content` |
| GET | `/requests/{id}` | Phiên bản hiện tại |
| PUT | `/requests/{id}` | Sửa bằng `command_id`, `expected_revision` và `content` |
| GET | `/requests/{id}/history` | Lịch sử, phân trang bằng `before_revision` và `limit` |
| POST | `/requests/{id}/cancel` | Hủy theo revision, vẫn giữ lịch sử; chưa có nút hủy trên UI |

`command_id` là UUID, được đặt tên riêng theo người dùng. Gửi lại đúng lệnh trả receipt cũ với `replayed=true`; dùng cùng ID cho đầu vào khác trả 409. Mỗi lệnh tạo/sửa/hủy lưu hồ sơ, snapshot lịch sử và receipt trong cùng transaction. Cập nhật dùng điều kiện revision ở database. API không nhận `owner_id` từ client.

Migration `li01a2b3c4d5` tạo ba bảng `adlc_intake_request`, `adlc_intake_revision`, `adlc_intake_command`, nối tiếp nhánh migration nghiệp vụ `h8b1c2d3e4f5`. Bảng được tạo trước bởi bootstrap chỉ được nhận lại nếu schema đúng và bảng rỗng. Migration từ chối downgrade phá lịch sử; tắt phần nghiệp vụ bằng feature flag, giữ dữ liệu để có thể bật lại.

## Kết quả kiểm tra

| Phần | Kết quả ngày 25/11/2026 |
|---|---|
| Backend | 14 kiểm tra: lưu bền vững, receipt, revision, quyền, rollback, migration, API đồng thời |
| Frontend | 4 kiểm tra: tạo, retry cùng lệnh, giữ nháp khi 409, hồ sơ đã hủy chỉ đọc |
| PostgreSQL 17 | Đạt: schema riêng, nhận migration, tạo, replay, sửa, lịch sử và danh sách; rollback cả schema thử |
| Frontend production | Build thành công; có cảnh báo kích thước bundle từ bộ frontend hiện có |
| Desktop trên backend local | Đạt: tạo demo, sửa thành phiên bản 2, tải lại và mở nội dung phiên bản 1 |
| Probe Lark | 6 kiểm tra offline; WebSocket thật, DM vào journal và biên nhận thử đã đối chiếu trên Lark Web |

Lệnh kiểm tra backend và frontend từ gốc repository:

```powershell
adlc-flow/.venv/Scripts/python.exe -m pytest --noconftest adlc-flow/tests/unit/adlc/test_requirement_intake.py -q
Push-Location adlc-flow/frontend
npx jest src/features/requirement-intake/intake-page.test.tsx --runInBand
Pop-Location
python deploy/local/stack.py frontend
```

`--noconftest` tách bộ kiểm tra intake khỏi cấu hình integration chung. Kiểm tra này không gọi dịch vụ model có phí.

`deploy/local/check_intake_postgres.py` là bài thử tùy chọn chạy trong app container với `POKEDEV_TEST_POSTGRES=1`. Script tạo schema riêng có tên ngẫu nhiên, dùng transaction và rollback toàn bộ; không dùng dữ liệu public làm fixture. Khi app image cũ hơn source, cần build lại app hoặc bind mount source mới chỉ cho container thử.

Bản đã thử trực tiếp dùng SQLite riêng của PokeDev. App image Docker chưa được build lại trong đợt LI-02 này. Muốn dùng code mới trong Docker, chạy `python deploy/local/stack.py build app` rồi khởi động app theo README; dừng backend trực tiếp trước để tránh trùng cổng. Bộ kiểm tra PostgreSQL LI-02 dùng source mới trong container thử và rollback schema thử, không thay thế bước build image triển khai.

## Bước tiếp theo

Luồng DM LI-02 đã nghiệm thu trên tenant thật. Tiếp tục các bài thử LI-00 còn lại. LI-03 bổ sung định tuyến nhóm/thread. LI-04 sẽ nối native Harness để agent đặt câu hỏi và tiếp tục từ câu trả lời đã lưu. Tài liệu `inputTakingNotes.md` được dùng để giữ ranh giới normalization/human transport và readiness; đối chiếu cụ thể nằm trong runbook LI-02.

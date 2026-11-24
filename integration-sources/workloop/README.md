# Workloop trong PokeDev

Demo TNQD đã chạy thực tế: [báo cáo, ảnh và hướng dẫn trình bày](../../docs/report/pokedev-tnqd-demo-20261023.md).
Profile này dùng `tnqd_worker.py` và Workloop thật cho 17 task từ Planner; TaskLoop
có thể bổ sung 5 bước xử lý một phát hiện TestForge, giữ nguyên bộ test rồi build
và deploy artifact mới. `prepare_tnqd.py` ghép đúng module `tnqd-sut` vào workspace
Angular đầy đủ. UI và lệnh `tnqd_control.py` dùng các API có kiểm tra quyền sở hữu;
refresh không tạo lại lượt chạy. `export_tnqd_demo.py` chỉ xuất khi source, archive,
suite, TestForge và tài liệu đọc lại đều khớp digest.

PokeDev chạy DAG bằng **Workloop thật**, pin các repo trong `source-lock.json`.
Mỗi lượt có một tiến trình và SQLite riêng, tránh xung đột giữa LFX được vendor
trong Workloop và LFX đang phục vụ ứng dụng PokeDev.

Thiết lập source sau khi cấu hình `.env.vai-platform.local` tại gốc project:

```powershell
adlc-flow/.venv/Scripts/python.exe integration-sources/workloop/bootstrap.py
```

Bootstrap clone ba repo về `adlc-flow/data/workloop/runtime`, checkout đúng commit,
không lưu token trong Git config hoặc URL. Không chạy script trong repo, không
bật automation, webhook, lịch chạy hoặc Foreman của các factory. Không thay các
dependency của PokeDev bằng bộ requirements riêng của Workloop.

Trong **Công việc → Kết quả → Workflow & ứng dụng chạy thử**:

- **PokeDev / candidate-preview**: Workloop DAG đối chiếu candidate native đã
  hoàn tất, chạy lại test bảo vệ trong Sandbox mới, khởi động app và kiểm tra
  năm thao tác HTTP. Luồng này dùng gateway dịch vụ, không giả lập agent và
  không gọi thêm model. Cần bridge `vai-pokedev-services >=0.4.1` trên Harness.
- **factory-wilson**: nhận đủ bảy template. `hello2`, `pingpong`, `task-api` được
  bật cho workspace riêng theo lượt chạy. Các template còn lại cần xác định
  source và phạm vi trước. Gateway dùng DSH/TaskLoop thật; mỗi node tối đa 360
  giây, không tự re-arm, tổng lượt tối đa khoảng 15 phút. Chưa có trần token/giá.
- **factory-test**: nhận 17 workflow thử chính Workloop. Chúng tham chiếu source,
  môi trường audit và fault-injection riêng nên chỉ hiển thị để rà soát, chưa
  được bật làm workflow của sản phẩm cá nhân.

Adapter bổ sung hai điều kiện cho đường chạy native: truyền đầu vào của DAG vào
brief (upstream chỉ đọc context để báo cáo) và dừng nếu không chọn được model
đã thông báo. Trạng thái `completed` của engine không đủ để báo đạt: PokeDev
còn kiểm tra toàn bộ node terminal thành công, scope, source hash và receipt
test/HTTP tương ứng. Không tự duyệt hoặc chuyển chu kỳ phát triển.

Intent lưu trước khi khởi chạy. Xem lại hoặc gửi đúng ID cũ không tạo worker
mới. Mất phản hồi giữ trạng thái cần đối soát; không tự chạy lại model hay
deploy. Preview hết hạn sau một giờ, trong khi kết quả test vẫn được giữ lại.

Broker hiện trả port Docker chỉ dùng được trên máy chủ. PokeDev chuyển tiếp các
yêu cầu HTTP giới hạn qua bridge tới ứng dụng trong Sandbox, rồi mở một origin
`localhost` riêng trên máy đang chạy PokeDev. Token không được chuyển đến trình
duyệt hay app. Cổng chỉ bind loopback, kiểm tra Host/Origin và tự đóng khi hết hạn.
Mở tab mới hoặc xem nhúng đều dùng ứng dụng từ xa, không khởi chạy một bản app
khác ở local. Cách xem này phục vụ PokeDev chạy trên máy hiện tại; nếu triển khai
PokeDev lên máy chủ cho nhiều thiết bị truy cập, cần cấu hình ingress preview
riêng trước khi cung cấp link công khai.

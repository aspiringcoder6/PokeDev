# Chạy LI-02 nhận yêu cầu qua Lark

Cập nhật 26/11/2026. LI-02 có backend, connector và giao diện desktop để liên kết tài khoản, chuyển DM text thành hồ sơ riêng và gửi biên nhận tự động. Kiểm tra offline, PostgreSQL và build đã đạt; kiểm tra liên kết và DM thật đang chuẩn bị. Các quyết định nằm trong [ADR 0023](../adr/0023-verified-lark-dm-intake-and-delivery-receipts.md).

## Cài và chạy local

Từ thư mục gốc PokeDev:

```powershell
# Cài backend và package contract dùng chung, build UI
python deploy/local/stack.py setup

# Cài connector Python 3.12 riêng
python deploy/local/stack.py lark-setup
```

Đặt cấu hình riêng của app PokeDev trong `.env`:

```dotenv
POKEDEV_INTAKE_ENABLED=true
POKEDEV_LARK_INTAKE_ENABLED=true
POKEDEV_LARK_APP_ID=your-app-id
POKEDEV_LARK_APP_SECRET=your-app-secret
POKEDEV_LARK_TENANT_KEY=your-verified-tenant-key
POKEDEV_LARK_BACKEND_URL=http://127.0.0.1:7862
POKEDEV_PUBLIC_URL=http://127.0.0.1:7862
```

`stack.py init` sinh `POKEDEV_LARK_CONNECTOR_SECRET` riêng nếu chưa có. Giữ cùng giá trị này ở backend và connector, khác credential Harness hoặc ADLC. `tenant_key` lấy từ sự kiện đã xác minh của app, không dùng tên tổ chức hiển thị. Backend chỉ chấp nhận đúng app và tenant đã cấu hình. Connector dùng HTTPS cho backend ngoài loopback; API Lark luôn dùng domain quốc tế và kiểm tra TLS.

Trong hai terminal:

```powershell
python deploy/local/stack.py run
```

```powershell
python deploy/local/stack.py lark
```

Chỉ chạy một consumer WebSocket cho app. Dừng `probe.py --listen` trước khi bật connector LI-02; probe LI-00 nhận tin để kiểm chứng, không chuyển việc vào backend. Connector được chạy riêng trên máy trong slice này; profile Docker cho connector thuộc LI-10. Nếu dùng backend Docker, build lại `app` để có code và package contract mới rồi dùng cổng loopback đã publish.

## Liên kết tài khoản

1. Mở [Tiếp nhận yêu cầu](http://127.0.0.1:7862/intake), chọn Liên kết Lark.
2. Kiểm tra đúng tài khoản PokeDev, chọn project được phép hoặc để Chưa gắn dự án.
3. Xác nhận mật khẩu PokeDev. Tài khoản local được tạo bởi bộ cài dùng `LANGFLOW_SUPERUSER_PASSWORD` trong `.env`; giữ mật khẩu riêng, không gửi qua Lark.
4. Gửi nguyên lệnh `/link ...` được tạo tới bot PokeDev trong DM. Mã dùng một lần, hết hạn sau 10 phút. Hai phía chỉ lưu digest của mã; nội dung raw được loại trước khi journal sự kiện.
5. Chờ bot xác nhận liên kết, rồi gửi một tin văn bản mới để tạo yêu cầu. Mỗi DM gốc tạo một hồ sơ riêng; reply trong thread và các đầu vào khác chưa tạo yêu cầu ở LI-02.

Auto-login của UI không đủ để tạo liên kết: endpoint vẫn kiểm tra mật khẩu native. Không khớp tài khoản theo tên hoặc email trong Lark. User không hoạt động, mã hết hạn/đã dùng, project không được phép hoặc một danh tính Lark đã gắn với tài khoản khác đều bị chặn. Sau 5 lần sai mật khẩu, tài khoản phải đợi 5 phút trước khi thử lại. Đợt này dùng tài khoản PokeDev có mật khẩu native; reauthentication qua SSO sẽ cần adapter riêng.

Tin nhắn đến sau liên kết được chuẩn hóa thành nội dung LI-01 và giữ tham chiếu app/tenant/event/message/chat/sender. Chưa có project thì hồ sơ vẫn là bản nháp riêng của chủ tài khoản. Biên nhận có link mở đúng hồ sơ trong PokeDev; nó chỉ xác nhận đã nhận yêu cầu. Không tạo readiness run, gọi model, duyệt Spec hoặc thực thi code.

## Độ bền và đối soát

Connector ghi journal SQLite riêng tại `adlc-flow/data/local/lark-connector/transport.sqlite3` trước khi callback SDK trả về. Khi backend ngắt, sự kiện vẫn PENDING; sau khôi phục được gửi lại với cùng danh tính. Backend chống lặp theo app/tenant/event và message, lưu hồ sơ, nguồn và outbox trong cùng transaction. Contract Python dùng chung nằm ở [adlc-contracts/lark-intake/v0.1](../../adlc-contracts/lark-intake/v0.1/README.md).

Outbox claim từng tin, cấp lease 60 giây và kiểm tra lại user/link/quyền project. Connector lưu send intent rồi mới gọi Lark; UUID gửi giữ ổn định. Receipt đã biết kết quả được gửi lại nếu backend chưa xác nhận, không gửi lại tin nhắn. Lỗi từ chối xác định như rate limit được retry có giới hạn, tối đa 5 lượt. Lỗi mạng sau send, response chưa xác định hoặc lease hết hạn chuyển sang UNCONFIRMED.

Giữ nguyên journal, receipt và UNCONFIRMED để đối chiếu tin nhắn trên Lark. Chưa có màn hình vận hành để cho retry các tin chưa rõ kết quả; không đổi tay trạng thái thành PENDING hoặc xóa journal để gửi lại. Gỡ liên kết cần mật khẩu, tăng revision và chặn biên nhận riêng còn chờ. Gửi đã bắt đầu được giữ để đối soát theo lease.

Tắt `POKEDEV_LARK_INTAKE_ENABLED` rồi dừng connector và khởi động lại backend để ngừng nhận việc mới; hồ sơ và lịch sử vẫn còn. Migration `li02a2b3c4d5` nối tiếp LI-01, thêm ba bảng mới và không có downgrade xóa lịch sử.

## Đối chiếu tài liệu đầu vào

`docs/inputTakingNotes.md` mô tả pipeline sau chuẩn hóa và loại phần nhận input/human transport khỏi phạm vi của nó. LI-02 đảm nhận đúng phần ranh giới đó. Các nguyên tắc được dùng: credential phía backend, nguồn có định danh, quyền theo project và không coi phản hồi là phê duyệt. Collector/verifier, hai reviewer, impact và Human Gates tiếp tục thuộc runtime readiness đã tích hợp và các slice LI-04/LI-06/LI-08.

Ghi chú "chưa triển khai runtime" trong tài liệu nguồn phản ánh thời điểm ghi chú. Repository hiện đã có source readiness và source access từ `Phuc/specification`; chúng vẫn cần nối với intake và cấu hình live. Tài liệu gốc được giữ nguyên.

## Kiểm tra

- 295 kiểm tra backend đã đạt, gồm 15 ca LI-02 và regression intake, source access, readiness, Harness.
- 22 kiểm tra connector/probe đã đạt: journal, retry ingress, kết quả gửi, process interruption, receipt replay và contract dùng chung.
- 7 kiểm tra UI đã đạt; build production thành công.
- PostgreSQL: migration/adoption, liên kết, DM dedupe, outbox và receipt đã đạt trong schema thử được rollback toàn bộ.
- Desktop local: đã mở biểu mẫu liên kết, đối chiếu đúng tài khoản native và trường xác nhận mật khẩu. Liên kết/DM thật: chờ xác nhận của người dùng; không suy từ bài thử giả lập thành live acceptance.

Lệnh backend:

```powershell
adlc-flow/.venv/Scripts/python.exe -m pytest -o addopts='' --confcutdir=adlc-flow/tests/unit/adlc adlc-flow/tests/unit/adlc/source_access adlc-flow/tests/unit/adlc/requirement_readiness adlc-flow/tests/unit/adlc/test_requirement_intake.py adlc-flow/tests/unit/adlc/test_lark_intake.py adlc-flow/tests/unit/adlc/test_harness_client.py -q
```

Lệnh connector (cài pytest riêng cho môi trường thử):

```powershell
uv pip install --python services/lark-connector/.venv/Scripts/python.exe 'pytest>=8,<9'
services/lark-connector/.venv/Scripts/python.exe -m pytest services/lark-connector/test_probe.py services/lark-connector/test_connector.py -q
```

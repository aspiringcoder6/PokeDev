# Chạy LI-03: nhóm, thread và nguồn hội thoại

Cập nhật 26/11/2026. Đã đạt kiểm tra tự động, PostgreSQL, build, desktop, hai thread nhóm có @mention và bổ sung vào hồ sơ DM cũ trên tenant thật. Nhóm pilot vẫn yêu cầu @bot; chưa xác minh hỗ trợ reply không @. Phạm vi và tiêu chí: [kế hoạch LI-03](../plans/li03-implementation.md). Quyết định: [ADR 0024](../adr/0024-explicit-lark-conversation-routing.md).

## Chuẩn bị và cấu hình

Giữ app/bot, tenant, credential và liên kết LI-02 riêng của PokeDev. Chỉ cần ba quyền pilot đã phát hành: DM vào bot, @mention trong nhóm và gửi tin dưới danh nghĩa bot. Quyền @mention không tự bảo đảm nhận mọi reply không @. Không tự thêm scope đọc toàn bộ nhóm.

Cài contract mới cho backend và connector từ gốc repository (backend đã có môi trường local):

```powershell
uv pip install --python adlc-flow/.venv/Scripts/python.exe --no-deps -e adlc-contracts/lark-intake/v0.1
python deploy/local/stack.py lark-setup
# Chỉ đọc bot ID; không in secret/token và không mở WebSocket thứ hai
services/lark-connector/.venv/Scripts/python.exe services/lark-connector/connector.py --bot-info
```

Đặt bot ID vừa xác minh vào `POKEDEV_LARK_BOT_OPEN_ID`. Bật phần hội thoại trước, để nhóm tắt trong lúc xác định đúng nhóm pilot:

```dotenv
POKEDEV_LARK_CONVERSATIONS_ENABLED=true
POKEDEV_LARK_GROUPS_ENABLED=false
POKEDEV_LARK_BOT_OPEN_ID=ou_your_verified_bot_id
POKEDEV_LARK_GROUPS_JSON={}
```

Dừng connector LI-02 và backend rồi khởi động backend mới trước, connector sau. Chỉ một consumer WebSocket cho app. Migration `li03a2b3c4d5` nối LI-02; bootstrap nhận lại schema mới nếu đúng và rỗng, sau đó backfill binding/alias cho DM CREATED cùng biên nhận DELIVERED trước đây. Nội dung, lịch sử và receipt digest LI-02 không bị viết lại.

```powershell
python deploy/local/stack.py run
```

```powershell
python deploy/local/stack.py lark
```

Trong nhóm pilot đã được người dùng cho phép và có bot, gửi `@PokeDev /probe`. Đây là lệnh khám phá tường minh: chỉ ghi metadata native vào journal/inbox, không tạo hồ sơ hoặc gửi nội dung nhóm lên backend. Kiểm tra chat ID của đúng sự kiện, tenant/app và sender khớp tài khoản đã liên kết, rồi thêm đúng nhóm đó:

```dotenv
POKEDEV_LARK_GROUPS_ENABLED=true
POKEDEV_LARK_GROUPS_JSON={"oc_your_pilot_chat":{"project_id":null,"unmentioned_replies_verified":false}}
```

`project_id: null` tạo bản nháp riêng chưa gắn project. Nếu chọn UUID project, mọi actor phải có quyền native trên project đó; lệnh chọn hồ sơ cũng phải cùng context project của nhóm. Một nhóm có một context rõ ràng, DM dùng project đã chọn khi liên kết tài khoản. Không lấy project từ tên nhóm hoặc tự cấp quyền cho các thành viên. Khởi động lại cả backend và connector sau sửa cấu hình. Việc thêm nhóm thật là thao tác mở đường nhận/gửi ở nhóm đó; chỉ cấu hình nhóm đã được chủ hệ thống cho phép.

## Cách dùng

- DM gốc hoặc @mention văn bản gốc trong nhóm đã cấu hình tạo hồ sơ mới.
- Reply vào tin gốc/biên nhận đã được theo dõi để bổ sung cho hồ sơ đó. Trong nhóm, luôn @bot để chắc chắn app nhận được sự kiện.
- `/new <nội dung>` tạo hồ sơ độc lập theo yêu cầu tường minh, kể cả khi đang ở một thread.
- `/intake <UUID hồ sơ> <nội dung>` chọn đúng hồ sơ hoặc liên kết nguồn mới với một hồ sơ đang có. Tài khoản liên kết phải là chủ hồ sơ và còn quyền project. Có thể lấy lệnh cho đúng UUID trong mục Nguồn hội thoại của trang hồ sơ.
- Khi root/parent/thread mâu thuẫn hoặc chưa có binding, bot yêu cầu chọn; không tự gán vào hồ sơ mới nhất.
- Nếu sau này xác minh và bật nhận reply không @ cho một nhóm, backend chỉ nhận reply có binding đã biết; root hoặc thread lạ không @ bị bỏ qua, không tạo hồ sơ hay biên nhận.
- Mở hồ sơ trong PokeDev, xem Nguồn hội thoại và bấm Cập nhật tin để tải các lời bổ sung. Phân trang mỗi 50 tin; thông tin source native có phần mở chi tiết. Đây là nguồn hội thoại riêng, chưa tự sửa brief hay trả lời câu hỏi của agent LI-04.

Biên nhận nhóm chỉ xác nhận thao tác và có link bảo vệ bởi quyền native. Không trích brief, liệt kê project/hồ sơ riêng hoặc cấp quyền cho người trong nhóm. Người khác bấm link vẫn phải qua kiểm tra owner/project. `/link` chỉ dùng trong DM; mã lỡ gửi trong nhóm được tiêu thụ mà không tạo liên kết, cần tạo mã mới bằng xác thực lại trên PokeDev. Nếu trang vẫn hiển thị mã cũ, tải lại trang rồi chọn Liên kết Lark để xác nhận mật khẩu và tạo mã mới.

## Tương thích và phục hồi

Contract v1 và endpoint LI-02 giữ nguyên. Model v2 nằm trong module riêng và đi qua endpoint `/v2`. Connector mới đọc/đối soát journal v1 bằng đúng protocol cũ; claim v1 không nhận route cần v2. Binding và alias provider receipt được lưu cùng transaction nghiệp vụ. Mỗi tin bổ sung có inbox/source riêng nên hai reply đồng thời không ghi đè nhau; brief revision giữ nguyên đến khi người dùng lưu.

Native message, root, parent và thread ID được giữ riêng. Bot receipt có alias chỉ sau khi Lark trả provider receipt hợp lệ. Nếu gửi không rõ kết quả, vẫn UNCONFIRMED, không tự gửi lại. Trước các thay đổi quyền/liên kết, ingress và claim dùng cùng thứ tự khóa user native như reauthentication trên PostgreSQL; SQLite dựa vào transaction và retry xung đột. Một lần gửi đã bắt đầu vẫn phải đối soát nếu quyền bị thu hồi sau claim.

Để ngừng nhóm, tắt `POKEDEV_LARK_GROUPS_ENABLED`; để ngừng luồng v2, tắt `POKEDEV_LARK_CONVERSATIONS_ENABLED`, dừng connector và khởi động lại backend/connector theo v1. Giữ code backend mới để bộ lọc v1 tiếp tục loại các delivery v2 còn chờ. Nếu buộc rollback binary về bản trước LI-03, tắt toàn bộ Lark intake và dừng connector trước; không để backend cũ claim outbox v2. Không downgrade xóa bảng, xóa journal hoặc sửa UNCONFIRMED thành PENDING. Nguồn đã lưu vẫn đọc được qua API private khi tắt nhận mới.

Backend Docker phải build lại `app`; profile Docker cho connector vẫn thuộc LI-10. Pilot native giữ database riêng tại `data/pokedev.db`. Các bài thử PostgreSQL tạo schema riêng rồi rollback toàn bộ, không thay đổi schema/dữ liệu nghiệp vụ public.

## Bằng chứng và giới hạn

| Phần | Kết quả |
|---|---|
| Backend | 316 kiểm tra đạt, gồm 21 ca LI-03 và regression LI-01/LI-02, source access, readiness, Harness; hai cảnh báo pytest timeout là cấu hình có sẵn |
| Connector/probe | 34 kiểm tra đạt; gồm protocol v1/v2 cùng journal, bot identity, thread send, intent/receipt recovery và discovery không chứa body |
| Desktop component | 12 kiểm tra đạt; nguồn hiển thị dạng text, đổi hồ sơ không giữ nguồn cũ, thu hồi quyền xóa nội dung đã tải và phân trang đúng request |
| PostgreSQL | Đạt migration/adoption, backfill DM và biên nhận LI-02, hai thread, DM reply, dedupe, outbox và receipt; rollback schema thử |
| Production build | Đạt; có cảnh báo kích thước bundle từ frontend kế thừa |
| Native migration | Giữ liên kết đang có, backfill một conversation, hai alias và một route từ hồ sơ DM LI-02; không viết lại brief hoặc receipt cũ |
| Desktop thật | A và B có hai nguồn riêng; DM cũ có ba nguồn sau hai tin bổ sung; cả ba brief vẫn revision 1 |

Thời gian dưới đây theo Asia/Saigon, ngày 26/11/2026. Nhóm PokeDev LI-03 Pilot chỉ được bật sau khi `/probe` khớp app, tenant và người dùng đã liên kết. Context project là bản nháp riêng chưa gắn project.

| Bước pilot | Kết quả |
|---|---|
| 09:11 — `/probe` có mention đúng bot | Chỉ metadata được ghi, không tạo yêu cầu hoặc biên nhận nghiệp vụ |
| 09:14 — `[Demo LI-03 A] Báo cáo doanh thu` | Một hồ sơ A riêng; biên nhận DELIVERED |
| 09:15 — `[Demo LI-03 B] Quản lý đơn hàng` | Một hồ sơ B khác A; biên nhận DELIVERED |
| 09:15 — reply có @ trong A, `Xuất CSV theo tháng` | APPENDED vào A, giữ parent/root/thread native; không đổi brief |
| 15:07 — reply có @ trong B, `lọc theo trạng thái` | APPENDED vào B; không xuất hiện trong A; biên nhận DELIVERED |
| 15:25:05 — `/intake` chọn hồ sơ Demo LI-02 trong DM thật | APPENDED vào hồ sơ cũ; không tạo thêm hồ sơ; biên nhận DELIVERED |
| 15:25:38 — Reply vào biên nhận bot Demo LI-02 trong DM thật | APPENDED vào cùng hồ sơ; parent khớp provider receipt đã lưu; biên nhận DELIVERED |
| Hai reply không @ nhìn thấy trên Lark Web | Chưa có event tương ứng được lưu ở connector; vẫn yêu cầu @bot và giữ `unmentioned_replies_verified=false` |
| Các tin gắn nhãn DM ban đầu | Quan sát Chrome cho thấy chúng nằm trong nhóm, không có @; không dùng các tin này làm bằng chứng DM hay kết luận lỗi định tuyến |

Sau khi lượt làm việc bị ngắt, dịch vụ native được khởi động lại. Các sự kiện và biên nhận đã biết kết quả vẫn được giữ, không gửi lại. Sau hai phép thử DM, cả tám outbox của LI-02/LI-03 đều DELIVERED; tổng số hồ sơ vẫn là bốn. Web API bot vẫn truy cập được; các lỗi kết nối WS trước đó không được coi là lỗi credential. Không sửa routing hoặc cấu hình VPN.

Ảnh desktop lưu riêng tại `adlc-flow/data/local/evidence/lark-li03-thread-a.jpg`, `lark-li03-thread-b.jpg` và `lark-li03-dm.jpg`; không đưa journal, database, credential hoặc ảnh hội thoại vào Git. Lệnh downstream và kết quả audit: [REGRESSION.md](../REGRESSION.md). Chưa đo độ trễ end-to-end, chưa kiểm chứng SDK redelivery bằng lỗi thật, chưa thêm card/file/nguồn tài liệu hoặc agent LI-04.

Nguồn API chính thức: [SDK event model](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/im/v1/model/event_message.py), [SDK reply request](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/api/im/v1/model/reply_message_request_body.py), [bot identity trong CLI chính thức](https://github.com/larksuite/cli/blob/main/shortcuts/common/runner.go). Bản triển khai khóa `lark-oapi==1.9.0`; model đã cài được đối chiếu trực tiếp. Việc thấy field trong SDK không được coi là khả năng nhận/gửi thật của tenant.

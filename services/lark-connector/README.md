# Kiểm chứng kết nối Lark cho PokeDev

LI-02 có thêm `connector.py` cho nhận DM vào hồ sơ và biên nhận tự động qua backend. Xem [hướng dẫn LI-02](../../docs/operations/lark-li02.md). Nội dung bên dưới dành cho probe LI-00; dừng probe trước khi bật connector cho cùng app.

LI-03 dùng wire v2 cho nhóm/thread, source history và `/probe` khám phá nhóm tường minh. Xem [hướng dẫn LI-03](../../docs/operations/lark-li03.md). Giữ journal hiện có để connector đối soát receipt v1; không chạy hai consumer cho cùng app.

Trạng thái ngày 25/11/2026: đã kiểm tra offline, phát hành bot PokeDev 0.1.0 cho một thành viên pilot và kiểm chứng DM hai chiều trên Lark thật. Tin nhắn của người dùng đã vào journal; một biên nhận thử đã được gửi vào đúng DM và đối chiếu trên Lark Web. `probe.py` vẫn chỉ nhận sự kiện, chưa tự phản hồi, tạo hồ sơ PokeDev hay gọi agent. Xem [biên bản pilot](../../docs/operations/lark-pilot-20261125.md).

## Cài và chạy trên máy

Chạy từ thư mục gốc PokeDev. Môi trường Python 3.12 riêng giúp SDK Lark không thay đổi dependencies của backend Python 3.14.

```powershell
$env:UV_CACHE_DIR="$PWD/adlc-flow/data/local/cache/uv"
uv venv --python 3.12 services/lark-connector/.venv
uv pip sync --python services/lark-connector/.venv/Scripts/python.exe services/lark-connector/requirements.lock.txt

# In phiên bản và trạng thái kiểm tra; không kết nối mạng
services/lark-connector/.venv/Scripts/python.exe services/lark-connector/probe.py
```

Tạo Custom App riêng cho PokeDev trong [Lark Developer Console](https://open.larksuite.com/app), bật Bot và chuẩn bị đăng ký `im.message.receive_v1`. Chỉ cấp các quyền tương ứng với bài thử đã chọn. Thông tin đăng nhập và phạm vi cấp quyền do chủ tenant xác nhận.

Điền credential của app PokeDev vào `.env` tại gốc repository hoặc biến môi trường:

```dotenv
POKEDEV_LARK_APP_ID=
POKEDEV_LARK_APP_SECRET=
```

```powershell
# Kết nối outbound WebSocket tới LarkSuite quốc tế
services/lark-connector/.venv/Scripts/python.exe services/lark-connector/probe.py --listen
```

Chọn chế độ nhận sự kiện qua kết nối dài trong console sau khi probe kết nối. Dừng bằng `Ctrl+C`. Không cần mở cổng public, tạo tunnel hoặc thay đổi VPN để chạy bài thử WS này.

Journal mặc định nằm ở `adlc-flow/data/local/lark-probe/events.sqlite3`, được Git bỏ qua. Có thể chọn đường dẫn riêng bằng `--journal`. Console chỉ in loại sự kiện, kết quả ghi mới và thời gian ghi; không in nội dung hoặc token. Journal vẫn chứa nội dung hội thoại sau khi che các trường credential, vì vậy chỉ dùng tin nhắn thử và giữ file trên máy. Dữ liệu thử không được lấy từ ADLC.

## Quyết định SDK và transport cho LI-00

- Khóa `lark-channel-sdk==1.4.0`, `lark-oapi==1.9.0`, `websockets==15.0.1` trong môi trường riêng. Channel SDK đang được giữ để đánh giá, chưa nằm trên đường nhận của probe.
- Probe gọi trực tiếp event dispatcher của `lark-oapi`, cấu hình domain `https://open.larksuite.com` rõ ràng. Không dựa vào mặc định Feishu.
- SQLite WAL và `synchronous=FULL` ghi journal trước khi callback trả về. Khóa chống ghi trùng gồm app, tenant và event ID; khi payload thiếu event ID, probe dùng hash và ghi rõ `payload_hash`. Đây chưa phải hợp đồng chống lặp callback cho production.
- Nhánh `MessageType.CARD` trong source WS của phiên bản đã khóa trả về ngay. Event dispatcher vẫn xử lý được `card.action.trigger` dạng EVENT trong bài thử tổng hợp. Vì vậy chưa chốt card qua WS; cần thử đúng loại card trên tenant. HTTPS callback hoặc trả lời trên web là các phương án cần đánh giá nếu WS không đạt.
- Không dùng SDK dedup trong bộ nhớ làm căn cứ hoàn tất xử lý nghiệp vụ. LI-02 sẽ bổ sung inbox/outbox và chuyển sự kiện sang backend bằng lệnh có receipt bền vững.

SHA256 của `lark_oapi/ws/client.py` đã kiểm tra:

```text
ce05f37d012929721b6484e419340c2ae9ab707510e2cb414123984816df1614
```

## Kết quả offline

| Kiểm tra | Kết quả |
|---|---|
| Khóa phiên bản và cấu hình domain LarkSuite | Đạt |
| Cùng event ID ở tenant khác có journal riêng | Đạt |
| Dừng process đột ngột sau commit, trước callback return; chạy lại không ghi trùng | Đạt |
| SDK dispatcher ghi journal trước khi trả về; lỗi sau commit rồi nhận lại không ghi trùng | Đạt, payload tổng hợp |
| Dispatcher xử lý card event và trả response | Đạt, payload tổng hợp; chưa kiểm chứng WS |
| Che trường credential và không báo đạt cho bài thử live chưa chạy | Đạt |

6 kiểm tra pytest đã đạt. Bài thử lỗi trước ACK chứng minh độ bền của journal và thứ tự trong callback; hành vi ACK, redelivery và reconnect từ server Lark cần bài thử live riêng.

```powershell
uv pip install --python services/lark-connector/.venv/Scripts/python.exe 'pytest>=8,<9'
services/lark-connector/.venv/Scripts/python.exe -m pytest services/lark-connector/test_probe.py -q
```

## Ma trận kiểm tra trên tenant thật

`NOT_RUN` nghĩa là chưa thực hiện; không suy từ kết quả offline thành hỗ trợ live. Khi chạy, ghi app type, phiên bản SDK, phạm vi quyền đã cấp, loại payload/transport và độ trễ. Fixture đưa vào Git phải là dữ liệu tổng hợp đã bỏ định danh riêng tư và credential.

| Capability | Trạng thái | Bằng chứng cần có |
|---|---|---|
| Kết nối WebSocket | Đạt trên tenant thật | Developer Console xác nhận Connected; mode đã lưu |
| Bật Bot và đăng ký sự kiện | Đạt | Version 0.1.0 Released, đúng ba tenant scope, `im.message.receive_v1` |
| Nhận DM | Đạt | Một event text/p2p đúng app và nội dung thử đã commit; ghi journal 15 ms, chưa đo ACK đầu cuối |
| Nhận @mention trong nhóm | NOT_RUN | App có mặt trong nhóm, đúng người gửi và chat |
| Reply không @mention | NOT_RUN | Event thật với phạm vi quyền cụ thể; phân biệt root/parent/thread |
| Reply trong DM | Đạt với biên nhận thử | Provider trả thành công, chat ID khớp nguồn, receipt lưu local và tin hiển thị trong Lark Web |
| Card callback | NOT_RUN | Loại card, frame EVENT/CARD hoặc HTTPS, action ID, actor, deadline |
| Form submit | NOT_RUN | Schema câu trả lời và callback thật |
| Đọc Doc/Wiki được phép | NOT_RUN | Bot/user authorization, phiên bản nội dung, locator |
| Tài liệu bị từ chối | NOT_RUN | Không lấy nội dung và không đưa ra chat |
| Redelivery và reconnect | NOT_RUN | Dừng trước/sau commit và ACK, đối soát số event duy nhất |

LI-00 chỉ hoàn tất khi có biên bản tenant thật và chốt transport. Liên kết danh tính, tạo hồ sơ từ DM và biên nhận thuộc LI-02; vòng agent hỏi–đáp thuộc LI-04.

## Nguồn chính thức

- [Channel SDK](https://github.com/larksuite/channel-sdk-python) và [giới hạn dedup](https://github.com/larksuite/channel-sdk-python/blob/main/docs/dedup-architecture.md).
- [Mẫu WS của OpenAPI SDK](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/samples/ws/sample.py) và [source WS](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/ws/client.py). Các nhánh Git có thể thay đổi; kết quả ở trên gắn với bản cài đã khóa và hash đã ghi.
- [lark-channel-sdk trên PyPI](https://pypi.org/project/lark-channel-sdk/1.4.0/) và [lark-oapi trên PyPI](https://pypi.org/project/lark-oapi/1.9.0/).

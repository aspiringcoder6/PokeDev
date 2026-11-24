# Dịch vụ cục bộ: Sandbox Kit, TestForge và Agent Memory

Các nguồn do người dùng yêu cầu được giữ riêng dưới
`integration-sources/broker-services/`; Harness, container và dữ liệu hiện có
không bị thay thế. Sandbox Kit và TestForge là bản clone đầy đủ; memory dùng
một checkout nông (shallow), tập trung vào mã nguồn của cùng repository đã
yêu cầu, vì tải toàn bộ lịch sử bị treo. Kiểm tra revision chính xác bằng
`git rev-parse HEAD` trong từng thư mục.

## Bảng dịch vụ và endpoint cục bộ

| Dịch vụ | Endpoint cục bộ | Vai trò |
| --- | --- | --- |
| Sandbox Kit broker | `http://127.0.0.1:8000` | API quản lý và thực thi có phạm vi; bắt buộc bearer token |
| OpenSandbox lifecycle | `http://127.0.0.1:8080` | Tạo Docker sandbox; API key độc lập |
| VFS | Mạng Compose riêng, cổng 8001 | Tệp workspace SQLite; cố ý không công bố ra host |
| TestForge broker | `http://127.0.0.1:9099/api/v1/health` | Broker chạy test job có xác thực; đã cài Chromium và k6 |
| Cognee API | `http://127.0.0.1:8010` | API memory thực tế từ fork đã yêu cầu |
| Cognee MCP | `http://127.0.0.1:8011/mcp` | MCP server cục bộ tùy chọn, profile `mcp` |

## Khởi động / khởi động lại

Chỉ khởi động/khởi động lại đúng stack sở hữu này:

```powershell
cd D:\coding\ADLC
.\deploy\harness-brokers\start.ps1 -Build -MemoryMcp
```

Cấu hình dịch vụ riêng tư được sinh tại `deploy/harness-brokers/.env` nếu
chưa có, không được in ra, bị Git bỏ qua và được giữ nguyên khi chạy setup
lặp lại. Token khác nhau cho lifecycle, sandbox broker, TestForge và tài
khoản memory cục bộ ban đầu. Không dùng lại model key. Hạn chế Windows ACL
của tệp riêng tư này trên máy dùng chung. Build context loại bỏ tường minh
các tệp env, metadata Git, cơ sở dữ liệu, mã ADLC không liên quan và thông
tin xác thực.

## Những thay đổi cần thiết cho vận hành Windows/cục bộ

- Sandbox Kit hiện tại thực tế dùng OpenSandbox, không phải Docker runner
  cũ của nó. Docker Desktop ở đây chỉ expose runc, nên **cấu hình cục bộ
  riêng này** không giả vờ là deployment gVisor thượng nguồn. Không có Docker
  daemon, firewall, VPN hay cấu hình server thượng nguồn nào bị thay đổi.
- Entrypoint của image OpenSandbox đọc `/etc/opensandbox/config.toml`; mount
  cục bộ dùng đúng đường dẫn đó. Các biến kết nối SDK là
  `OPEN_SANDBOX_DOMAIN` và `OPEN_SANDBOX_API_KEY`; proxy giúp tránh các vấn
  đề reachability của bridge Docker Desktop. Các biến này theo SDK đã cài,
  không phải alias env đoán mò.
- Phiên Python độc lập khởi tạo `/workspace` trước khi chờ công việc.
- Các route API Sandbox Kit thượng nguồn thiếu xác thực bearer bắt buộc. Một
  wrapper deployment yêu cầu broker token được sinh riêng trên `/api/*`.
  Dashboard có thể được xem, nhưng các thao tác dashboard không xác thực tùy
  ý cố ý không được cấp. Không tắt wrapper này chỉ để làm UI chạy được.
- Control plane lifecycle đáng tin cần socket của Docker để quản lý
  container; socket này không bao giờ được mount vào sandbox của agent hay
  Harness. Mọi listener trên host chỉ lắng nghe loopback. Các endpoint sandbox
  tạo lúc runtime được quản lý riêng; đây không phải cô lập egress/LAN được
  chứng nhận. runc không phải bảo đảm kiểu VM/chống mã độc.
- Build VFS bao gồm compiler cần cho phụ thuộc SQLite native của nó.
- TestForge dùng broker từ mã nguồn của nó cùng Chromium và k6 thực tế, và
  không gặp các vấn đề: token dùng chung mẫu, thiếu `opt/broker.env`, hay
  script tải release hard-code.
- API/MCP memory dùng chung một image gọn build từ fork thực tế, chỉ có phụ
  thuộc API dạng văn bản. Các thành phần mở rộng document/vision và bundle
  extension hàng GB không được nạp sẵn. Model/extension tùy chọn có thể được
  tải khi dùng lần đầu. Không cấu hình key LLM/embedding/provider trả phí.
  `AUTO_FEEDBACK=false` ngăn feedback tự động cho lượt đã trả lời; caching
  bình thường vẫn giữ bật.

Tham chiếu cấu hình:
[cấu hình server chính thức của OpenSandbox](https://github.com/opensandbox-group/OpenSandbox/blob/main/server/configuration.md).

## Biến môi trường và token chính

- `deploy/harness-brokers/.env` — tệp riêng tư sinh tự động, chứa token cho
  lifecycle, sandbox broker, TestForge và tài khoản memory cục bộ ban đầu;
  bị Git ignore và không được in ra console.
- `OPEN_SANDBOX_DOMAIN` / `OPEN_SANDBOX_API_KEY` — biến kết nối SDK của
  OpenSandbox, theo đúng SDK đã cài, không phải alias đoán mò.
- `AUTO_FEEDBACK=false` — tắt feedback tự động trong image memory; caching
  bình thường vẫn bật.

## Healthcheck

Các URL health để theo dõi sau khi stack đã lên:

- Sandbox Kit broker: `http://127.0.0.1:8000` (bearer token bắt buộc trên
  `/api/*`).
- OpenSandbox lifecycle: `http://127.0.0.1:8080`.
- TestForge broker: `http://127.0.0.1:9099/api/v1/health`.
- Cognee API: `http://127.0.0.1:8010`; Cognee MCP: `http://127.0.0.1:8011/mcp`.

Chạy smoke script ở mục trên để kiểm tra health/auth và vòng đời sandbox
trong một lượt; kết quả ghi ra `adlc-flow/data/harness-brokers-smoke.json`.

## Lỗi thường gặp

- **Yêu cầu quản lý sandbox trả 401** — route `/api/*` bắt buộc bearer token
  sinh riêng; đây là hành vi đúng của wrapper deployment, không phải lỗi.
  Không tắt wrapper để "cho UI chạy được".
- **`docker compose down` làm mất dữ liệu** — không bao giờ thêm `-v`;
  named volumes giữ memory, VFS và test artifact lâu dài.
- **Không thấy VFS trên host** — cổng 8001 nằm trong mạng Compose riêng và
  cố ý không được công bố ra host.
- **Tải repository đầy đủ bị treo** — memory dùng checkout nông; kiểm tra
  revision bằng `git rev-parse HEAD` trong từng thư mục nguồn.
- **Lo mất cấu hình khi tái chạy setup** — không xảy ra: tệp `.env` riêng
  tư được giữ nguyên khi setup lặp lại.

## Smoke test và bằng chứng

```powershell
cd D:\coding\ADLC
.\adlc-flow\.venv\Scripts\python.exe deploy\harness-brokers\smoke.py --sandbox --output adlc-flow\data\harness-brokers-smoke.json
```

Lệnh này thăm dò health/auth cục bộ và tùy chọn tạo đúng một sandbox dùng
một lần với tên tường minh, chạy một lệnh Python print cố định rồi xoá
**chỉ phiên đó**. Nó không gọi model, không truy cập AUT production, không
clone/push mã nguồn của người dùng, không phê duyệt một lần chạy thật, và
không thay đổi bộ xác minh đã đóng băng.

Browser runtime của TestForge có thể được kiểm tra với HTML nội bộ, tách
biệt khỏi pipeline sinh test. Một handshake memory server/MCP trống nhưng
khoẻ không chứng minh ingestion, retrieval, cô lập multi-tenant hay tương
thích model thành công. Báo cáo các mức kiểm chứng này riêng biệt trong phần
trình bày.

## Kết nối Harness / ADLC sau này

Việc các dịch vụ này online không có nghĩa là cấp quyền dùng tool thô trong
mọi phiên, hay âm thầm thay thế các worker binding được bảo vệ của H6. Giữ
allowlist tool demo theo từng model và scope thuộc sở hữu server.

Để có một binding cục bộ được xem xét, container Harness dùng
`host.docker.internal`, không phải `127.0.0.1`, cho các endpoint trên host.
Chỉ forward những cổng callback tường minh cần thiết; không tắt firewall hay
mở toàn bộ traffic mạng riêng. Secret của broker thuộc về credential service
hoặc publisher của nó, không bao giờ nằm trong prompt/artifact. UI plugin
memory hiện có vẫn tách biệt với một project gateway read-only có thực thi.
Xem `harness-session-demo.md` về ranh giới đó.

Dừng stack này mà không xoá memory/tệp/artifact:

```powershell
docker compose --env-file deploy/harness-brokers/.env -f deploy/harness-brokers/compose.yml --profile mcp down
```

Không thêm `-v`: named volumes chứa memory, VFS và test artifact lâu dài.

## Đã xác minh ngày 2026-10-14

Cả bốn endpoint health cục bộ trả về HTTP 200. Cấp phát sandbox + thực thi
Python trả về exitCode 0; container đã tạo được xoá đúng. Yêu cầu quản lý
sandbox không ký trả 401. TestForge khởi chạy Chromium bằng Playwright
1.64.0 và vượt một assertion với HTML nội bộ, với k6 hiện diện. Cognee API
báo ready; MCP khởi tạo là Cognee 0.5.6 và trả về năm tên tool. Không chạy
model trả phí, ingestion/retrieval memory hay mutation GitHub.

Revision/danh tính image được giữ trong
`deploy/harness-brokers/source-lock.json`. Output smoke thực tế là
`adlc-flow/data/harness-brokers-smoke-final.json`.

## Nguồn tổng hợp

Tài liệu này được dịch và biên tập từ các file sau (lưu trữ trên nhánh git
`agentHarness`, đọc bằng `git show agentHarness:docs/<file>`):

- `docs/harness-brokers-local.md` — Local Sandbox Kit, TestForge and Agent
  Memory services (runbook khởi động dịch vụ cục bộ).

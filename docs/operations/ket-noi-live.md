# Kết nối Harness trực tiếp (live)

Về điểm vào Workflows có kết nối và hai cổng phê duyệt của con người trong
lần chạy, xem [Harness → GitHub workflow](../demos/harness-workflow-github.md).
Việc tạo workflow không khởi động model, issue hay push; việc chạy nó không
cần tunnel webhook.

Workspace sản phẩm là [Agent Harness](http://localhost:3000/harness/). Hồ sơ
thực thi hiện tại vẫn cố ý giới hạn: Python pagination, một tệp mã nguồn ghi
được, bốn acceptance check bất biến, và chỉ `my-codex / cx/gpt-5.6-luna`.
Việc bỏ các nhãn "demo" chỉ mang tính trình diễn không chứng nhận các yêu
cầu tùy ý, cũng không biến thiết lập cục bộ thành một deployment production.

## Phạm vi và thông tin xác thực

- Repository GitHub sở hữu: `aspiringcoder6/vanguard`. Upstream gốc không
  phải đích publish. Các lần chạy mới đóng băng repository và yêu cầu đã
  chọn.
- Nhánh được publish: chỉ nhánh mới `codex/harness-session-<run-prefix>`.
  Không cập nhật nhánh main, không force-push, không phê duyệt của con người
  tự động, hay retry ngầm định.
- Memory: một binding owner/project chuyên biệt, suy ra từ owner UUID ADLC
  tường minh và `github:<owner/repository>`. Đây là namespace kết nối, không
  phải một bản ghi project ADLC mới tạo.
- Giữ `adlc-flow/data/harness-demo/demo.env` và mọi JSON kết nối riêng tư ở
  trạng thái ignored và chỉ operator cục bộ đọc được. Không in, tải lên,
  commit hay dán thông tin xác thực của chúng. Credential của provider
  không bao giờ vào sandbox của agent.
- Xác thực CLI phải có quyền ghi issue/nội dung và quyền quản lý webhook của
  repository. Chỉ có credential Git clone là không đủ.

Các định danh tool `demo_*` nội bộ theo phiên bản, route API và receipt
trước đó giữ nguyên. UI hiển thị nhãn dễ đọc và bảo toàn bằng chứng gốc
nguyên văn.

## Khởi động các kết nối hiện có

Docker Desktop, Harness đã cấu hình, và Cognee API phải đang chạy sẵn. Từ
`D:/coding/ADLC/adlc-flow`, dùng terminal riêng cho các tiến trình dài hạn
bên dưới. Không khởi động worker trùng lặp vào cùng một ledger.

```powershell
$env:PYTHONPATH=(Get-Location).Path
.\.venv\Scripts\python.exe scripts\prepare_harness_demo.py --backend
```

```powershell
$env:PYTHONPATH=(Get-Location).Path
.\.venv\Scripts\python.exe scripts\harness_connections.py --serve memory
```

```powershell
$env:PYTHONPATH=(Get-Location).Path
.\.venv\Scripts\python.exe scripts\harness_connections.py --serve webhook
```

Giữ frontend ở cổng 3000. Memory gateway chỉ lắng nghe `127.0.0.1:8012`;
webhook edge ở `127.0.0.1:17862`. Cả hai đều không expose OpenAPI/docs.
Backend giữ ở 7860; Harness ở 3080. Việc khởi động broker được tài liệu hóa
riêng và không biến các tool thô SandboxKit/TestForge/Cognee thành verifier
được bảo vệ.

## Cấp phát không phải là khởi động lại

`scripts/harness_connections.py` cung cấp `--configure-github`,
`--configure-memory`, `--check-memory`, `--create-webhook`,
`--update-webhook` và `--create-issue`.

Các lệnh cấu hình yêu cầu owner UUID ADLC tường minh và repository slug;
cấu hình GitHub còn yêu cầu repository ID dạng số đã xác minh. Cấp phát
memory nhận chính xác commit nguồn của project cho provenance của ghi chú;
revision backend Cognee đã kiểm toán là một pin riêng. Dùng `--help` để xem
tên tham số. Các lệnh này chỉ cập nhật cài đặt riêng tư, không phải `.env`
ở gốc workspace.

Setup ghi một intent trước mỗi mutation bên ngoài. Một intent chưa hoàn tất
đòi hỏi operator kiểm tra tài khoản/dataset/issue/hook từ xa, chứ không phải
xoá intent rồi retry mù quáng. Setup memory đã hoàn tất đọc lại các pin hiện
có; setup issue CLI đã hoàn tất báo cáo issue đã lưu mà không tạo thêm. UI
hỗ trợ tạo các issue riêng biệt tiếp sau đó. Thay đổi cấu hình GitHub/memory
yêu cầu khởi động lại backend khi không có lần chạy nào đang hoạt động;
không yêu cầu thay đổi release plugin native đã đóng băng.

## Memory thực sự làm gì

Gateway xác thực tới Cognee API thực, lấy các tài liệu thô được operator pin
từ một tài khoản/dataset cô lập, kiểm tra bytes/digest và owner/project của
chúng, và trả về các chunk có trích nguồn tương thích H6C. Xếp hạng là
lexical. Nó không gọi graph indexing của Cognee, semantic search, embeddings,
synthesis, mutation MCP thô, hay bất kỳ route model nào. `cognify_status`
báo tính khả dụng của tài liệu đã pin, không phải tuyên bố rằng một knowledge
graph đã được xây.

Ghi chú hết hạn sau tối đa bảy ngày. Ghi chú hết hạn không thể truy xuất;
xoá vật lý khỏi storage backend là một nhiệm vụ vòng đời riêng. Memory là
ngữ cảnh mang tính tham vấn, không bao giờ là ủy quyền hay bằng chứng Verify
độc lập. Gateway đã cấu hình gặp lỗi thì bước đó thất bại; không có fallback
cục bộ âm thầm.

Bằng chứng không chứa secret được giữ trong
`data/harness-connections/memory-readback.json` và
`memory-gateway-check.json`. Các JSON gateway/registry/intent riêng tư chứa
credential và phải ở lại máy cục bộ.

## Ingress HTTPS chỉ dành cho webhook

Endpoint công khai chính xác là `https://<reviewed-host>/webhooks/github/issues`.
Edge xác thực HMAC raw-body của GitHub trước khi chỉ forward sự kiện
issue/ping tới endpoint webhook ADLC loopback cố định. Yêu cầu không ký bị
từ chối; `/`, `/docs`, UI, API ADLC thông thường, memory và sandbox không
được forward. ADLC còn kiểm tra tên/ID số repository operator đã đóng băng,
sự kiện, label và binding owner. Định danh issue khử trùng lặp các sự kiện
opened/labeled/redelivered. Label là `adlc-harness`, kèm tương thích label cũ.

Cloudflare Quick Tunnel khởi động thủ công hiện tại chỉ nhắm tới edge này.
Hostname sinh ra là tạm thời, không có SLA production, và biến mất khi tiến
trình dừng. Nó không phải giải pháp hosting production. Để dùng lâu dài, cấp
phát hostname ổn định/named tunnel đã được xem xét và chỉ cập nhật webhook sở
hữu; không expose frontend hay control plane của broker.
`--update-webhook <new-HTTPS-endpoint>` đối chiếu hook sở hữu đã lưu chính
xác với GitHub trước khi cập nhật URL của nó. Nó không tạo hook khác, không
mở rộng sự kiện, không tắt kiểm tra TLS hay phát lại các lần giao issue.
Acknowledge không rõ ràng chặn retry tự động và giữ lại intent cập nhật.
Xem [giới hạn của Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
và [xác thực chữ ký của GitHub](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).

Metadata intent và acknowledge của hook/issue được giữ trong thư mục kết
nối bị ignore. Acknowledge POST/push không rõ ràng được kiểm tra, không bao
giờ tự động retry. Khởi động lại một helper không đăng ký thêm webhook khác.

## Checkpoint thực tế từ issue đến kết quả

1. Tạo issue pagination cố định, không chứa thông tin nhạy cảm, trên fork
   sở hữu, gắn label `adlc-harness`. Kiểm tra delivery ID/trạng thái thực tế
   của GitHub, không phải payload bịa ra.
2. Sự kiện có chữ ký tạo một lần chạy logic scoped theo owner và có thể bắt
   đầu planning thật của orchestrator. Nó dừng ở cổng phê duyệt của con
   người cho kế hoạch chính xác.
3. Owner đọc và phê duyệt kế hoạch đó trong ADLC. Agent Harness sau đó viết
   brief, nạp skill đã pin, nhớ lại memory thật của project và chỉnh sửa qua
   Docker sandbox không mạng. Tự kiểm của agent không phải bằng chứng độc lập.
4. Verify độc lập tái dựng candidate với các check đã đóng băng trong một
   container riêng. Agent chỉ báo cáo và commit candidate mã nguồn đã xác
   minh đó.
5. Owner xem xét commit, candidate, xác minh và target digest chính xác rồi
   phê duyệt publishing. Orchestrator fast-forward cục bộ và chỉ push nhánh
   làm việc mới. Xác minh remote SHA của nó bằng với commit đã phê duyệt.

Trước khi cả hai cổng phê duyệt của con người và xác nhận remote SHA hoàn
tất, không báo toàn bộ luồng issue → push GitHub là thành công. Kết quả được
giữ lại tồn tại qua việc phiên native hoàn tất; restart không bao giờ âm
thầm phát lại các lời gọi model hay việc publish.

## Phục hồi writer và phiên mới tường minh

Plugin native đã đóng băng giữ một `writer.lease`. Sau khi container restart
không sạch, health endpoint của nó kiểm tra cấu hình, không phải việc lease
cũ còn khả dụng hay không. Job bị từ chối báo
`DEMO_HARNESS_WRITER_LEASE_BLOCKED` khi phản hồi native là `EEXIST`; mã
native không rõ vẫn được sanitize.

Trước khi phục hồi một lease, xác nhận writer trước đó đã dừng, lease có
trước container hiện tại, và các job đã giữ đều ở trạng thái cuối. Bảo toàn
marker cũ trong một kho lưu trữ có tên và giữ mọi job/receipt. Không bao giờ
gỡ lease của một writer đang sống hay vứt journal để một thao tác trông có
vẻ thành công.

UI của lần chạy thất bại cung cấp "Tạo phiên mới từ yêu cầu này". Nó tạo
một **bản nháp** mới gắn với cùng owner, yêu cầu và issue/repository GitHub
đã chọn, kèm vết `restart_of`. Nó không phát lại sự kiện GitHub issue,
không khởi động model, không sao chép candidate/commit, hay thừa kế các phê
duyệt của con người. Yêu cầu lặp lại trả về cùng một lần chạy mới. Một intent
restart chưa hoàn tất đã lưu đòi hỏi operator kiểm tra. Operator sau đó tường
minh bắt đầu planning và con người phê duyệt kế hoạch chính xác mới. Lần chạy
thất bại ban đầu giữ nguyên và đọc được.

Worktree của task-loop pin `core.autocrlf=false` **và** `core.eol=lf` theo
từng lệnh Git; không có cài đặt Git toàn cục hay attribute thượng nguồn nào
bị thay đổi. Điều này tái tạo các byte LF đã đóng băng kể cả khi repository
dùng `* text=auto` trên Windows. Vòng lặp kiểm tra checkout WORKSPACE_EDIT
với tests/candidate đã đóng băng trước khi mở phiên model, rồi lặp lại guard
tệp được bảo vệ sau lần lặp và Verify. Attribute `eol=crlf` không tương thích
tường minh không bị ghi đè hay chuẩn hóa âm thầm để được chấp nhận: nó thất
bại trước khi agent bắt đầu. Xem
[quy tắc attribute end-of-line của Git](https://git-scm.com/docs/gitattributes).

## Release native và chẩn đoán được giữ lại

Các phiên scoped hiện pin native `vai-adlc-demo-session@0.1.1`, plugin
digest chính xác của nó, và `runtime:harness-demo-scoped/0.1.1`. Bundle
0.1.0 và lock gốc được lưu trữ nguyên byte ngoài cây plugin đang hoạt động
tại `integration-sources/plugin-releases/vai-adlc-demo-session/0.1.0`
(digest gốc
`sha256:42169d89fff111c2e46492f4cec30f96073070f040903f2c2269c133258fe0b5`).
Journal logic/native cũ và các phê duyệt của con người không bị viết lại.
Runtime đã đóng băng của một lần chạy cũ không thể bị thay âm thầm bằng
0.1.1: dispatch native thất bại trước lời gọi model khi binding đã lưu khác
nhau. Hãy bắt đầu một lần chạy mới thay vì sao chép phê duyệt cũ sang một
runtime khác.

Journal native mới giữ một tóm tắt `native_activity` có giới hạn, không
chứa payload: số đếm sự kiện, tool ID đã biết, phân loại từ chối, phân loại
hoàn thành, và số đếm nguồn model/ngắt. Tên không đáng tin được gán nhãn
SHA-256. Không expose nội dung tin nhắn, đối số tool, payload ngoại lệ hay
credential. ADLC xác thực phiên bản và binding request/phiên/lần
chạy/giai đoạn chính xác trước khi giữ chẩn đoán; trường không rõ hay nhãn
tùy ý bị từ chối. Owner thấy tóm tắt này trong "Chẩn đoán phiên" ngay cả
sau khi native SDK đã bị dọn dẹp. Các guard attempt, compaction, recall,
thay thế surface và tool ngoài giai đoạn giữ nguyên. Observability không
phải là chấp nhận, Verify, hay quyền retry.

Reload yêu cầu dừng các lần chạy Harness khác và kiểm tra các job native đã
giữ ở trạng thái cuối. Xác nhận health có xác thực báo release 0.1.1 và
plugin lock đã cài là chính xác trước khi bắt đầu một lần chạy logic
**mới**. Một thất bại từ 0.1.0 không có vết sự kiện hồi tưởng; không bịa ra
vết đó hay tái sử dụng cổng của nó.

## Kết quả live đã xác nhận — 2026-10-14

Lần chạy logic `e129fd2e-401d-46ab-aa5c-b6d5c0497ee9` đạt `SUCCEEDED` sau
cả hai phê duyệt owner chính xác. Nó giữ issue #1 và delivery GitHub có chữ
ký gốc `520616e4-c7d3-11f1-9a22-7559407c2e79` qua dòng dõi restart tường
minh. Không dùng issue mới hay webhook tổng hợp để phục hồi các phiên thất
bại.

Cả ba giai đoạn native dùng `my-codex / cx/gpt-5.6-luna` trên release 0.1.1
với usage được đo, một lượt hoàn thành, nguồn model khớp và không có vi
phạm chính sách nào được ghi nhận. Agent viết brief của nó, nạp skill đã
pin, nhớ lại chunk gateway Cognee thực tế scoped theo project, và chỉnh sửa
qua Docker không mạng. Verify Docker độc lập chạy cả bốn acceptance test
được bảo vệ với exit status 0. Memory và tự kiểm của agent không phải bằng
chứng độc lập.

Commit handoff `d9c1592a2aed4ebb5fb3c52ab3e5a5124898b055` chỉ thay đổi
`app.py` so với baseline nhiệm vụ đã đóng băng. Sau khi con người phê duyệt
handoff digest
`sha256:62069a31e4b80a44260a197a62e703a041b8faaedbd04c84a3f14b5a0974fe09`,
ADLC fast-forward nhánh integration cục bộ và push nhánh làm việc mới
[`codex/harness-session-e129fd2e401d`](https://github.com/aspiringcoder6/vanguard/tree/codex/harness-session-e129fd2e401d).
Một lượt đọc GitHub API riêng xác nhận remote SHA bằng với commit đã phê
duyệt; `main` giữ nguyên `bdc4349474eb2565e47c9e2a3f26fd1dce246896`. Nhánh
làm việc gồm fixture nhiệm vụ hai tệp ban đầu (`app.py` và
`test_acceptance.py` đã đóng băng) cùng bản sửa mã nguồn đơn của agent.
Không tạo PR, không merge nhánh upstream/default, và không xảy ra force push.

Điều này chứng minh luồng issue pagination có giới hạn → kết quả được giữ →
publish nhánh làm việc đã phê duyệt, chứ không phải chứng nhận Vanguard toàn
phần hay hosting production. Các giới hạn tunnel tạm thời, projection memory
lexical, chi phí model bằng 0 và độ bao phủ bốn check vẫn áp dụng. Việc từ
chối hoạt động 0.1.0 cũ không thể được chẩn đoán hồi tưởng; lần chạy mới
thành công không thiết lập nguyên nhân của nó.

## Nguồn tổng hợp

Tài liệu này được dịch và biên tập từ các file sau (lưu trữ trên nhánh git
`agentHarness`, đọc bằng `git show agentHarness:docs/<file>`):

- `docs/harness-live-connections.md` — Live Agent Harness connections
  (runbook kết nối live, gồm phần phục hồi writer và phiên mới tường minh).

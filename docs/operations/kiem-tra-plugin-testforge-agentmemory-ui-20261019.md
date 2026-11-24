# Kiểm tra TestForge và AgentMemory trong ứng dụng

Ngày kiểm tra: **19/10/2026, Asia/Saigon**.

**Kết luận cập nhật sau khi bật VPN: cả hai plugin gọi health thành công và trả kết quả trên UI Harness.** TestForge trả `status: ok`, backend phiên bản `1.5`; AgentMemory kết nối MCP thành công, trả `status: ok` từ Cognee `0.5.6`. Kết quả được đối chiếu với bản ghi tool thật và phần IN/OUT trên UI. PokeDev/ADLC vẫn báo `testforge_ready: false`; chưa xác nhận chạy job kiểm thử hoặc sử dụng dữ liệu memory trong luồng sản phẩm.

## Kết quả mới nhất sau VPN

| Hạng mục | Kết quả |
| --- | --- |
| Container Harness | Khởi động container hiện có; DSH `0.1.5-rc.2` |
| TestForge | UI Plugins hiển thị `vai_testforge`: **Enabled / Running** |
| AgentMemory | UI Plugins hiển thị `vai_agentmemory`: **Enabled / Running** |
| Gọi từ chat Harness | Lượt thứ hai của phiên thật, đúng một lần `testforge_health` và một lần `memory_health` |
| TestForge trả về | `status: ok`, backend `1.5`, `jobs_active: 0`, `auth_required: true` |
| AgentMemory trả về | `status: ok`, Cognee `0.5.6`, độ trễ lần gọi `929 ms` |
| Hiển thị trên UI | Hai kết quả IN/OUT thật, JSON và tóm tắt bằng tiếng Việt |
| PokeDev | Đăng nhập thành công bằng tài khoản đã có; mở được màn hình Harness và trạng thái dịch vụ |
| API Replay của ADLC | `enabled: false`, `worker_ready: false`, `testforge_ready: false` |
| Memory trong PokeDev | Chế độ `REVIEWED_GATEWAY`; là ranh giới ADLC riêng, không tự biến thành sáu tool thô của plugin mới |

Phiên kiểm tra native: `session-269d0740-b57c-4ea7-afc3-4205bd4503fd`, workspace trống `/app/workspace/plugin-ui-check-20261019`, route model có sẵn `my-codex / cx/gpt-5.6-luna`. Lượt trước VPN có hai tool lỗi; lượt sau VPN, khoảng **16:15–16:16**, có hai tool thành công với `isError: false`. Lịch sử cả hai lượt được giữ riêng; không dùng kết quả mới để ghi đè bằng chứng lỗi cũ. Không ghép phiên native này vào một `WorkflowRun` ADLC giả.

Health TestForge xác nhận broker phản hồi và tự báo có k6; chưa chạy k6 hoặc job nào để kiểm chứng chức năng. `auth_required: true` cho biết backend yêu cầu xác thực; health đạt không chứng minh các thao tác được bảo vệ đã được cấp quyền. Health AgentMemory xác nhận MCP initialize và danh mục tool, không đọc/ghi/xóa dữ liệu tenant.

## Lịch sử kết nối trước và sau VPN

Trước khi người dùng bật VPN, cả Windows lẫn container không truy cập được các dịch vụ tại `10.0.10.195`. UI nhận `Error: fetch failed` từ TestForge và `memory MCP unreachable ... Connect Timeout Error` từ AgentMemory. Kết nối tới Gitea cổng 3000 từ container cũng timeout, còn đường container → backend trên máy chủ (`host.docker.internal:7860/health`) trả HTTP 200.

Sau khi người dùng thông báo đã bật VPN, Windows và container truy cập được TestForge health (HTTP 200); bare GET tới AgentMemory MCP trả HTTP 406 do giao thức/Accept header, không phải lỗi mất kết nối. Lời gọi `memory_health` qua MCP đúng giao thức sau đó trả `status: ok`. Hai lời gọi health từ chính phiên Harness Docker đều thành công.

Firewall hiện có của container **đã cho phép** đích `10.0.10.195/32` trước quy tắc chặn dải private. Không sửa firewall, mở rộng quyền mạng, thay endpoint hoặc cài lại plugin trong lượt thử sau VPN. Kết quả cho thấy kết nối được khôi phục sau khi bật VPN, không xác định sâu thiết bị hoặc tuyến mạng gây ra timeout trước đó.

## Giới hạn tích hợp PokeDev

Việc cài package vào profile web làm các tool khả dụng cho phiên Harness theo chính sách phiên. Nó không tự nối toàn bộ hành vi TestForge vào cơ chế Replay/Verify của ADLC, hoặc thay gateway memory theo project.

API Replay thực tế trả các blocker:

- `BACKEND_SOURCE_AND_REVISION_REQUIRED`
- `BROKER_REACHABILITY_UNCONFIRMED`
- `TYPED_MATERIALIZATION_EVIDENCE_IDEMPOTENCY_CANCEL_REQUIRED`
- `NO_MODEL_NO_HEAL_ROUTING_UNREVIEWED`

API được gọi lại sau VPN vẫn trả đầy đủ các blocker trên. Màn hình phiên Harness của PokeDev báo `DEMO_HARNESS_NOT_READY`; API tương ứng vẫn có `ready: false`, Memory dùng `REVIEWED_GATEWAY`. Chưa chạy một workflow mới, không duyệt kế hoạch hay dùng báo cáo của agent làm Verify PASS. Kết nối backend đã thông nhưng vẫn cần adapter/binding phù hợp trước khi kết luận kết quả backend xuất hiện đầy đủ trong luồng sản phẩm ADLC.

## Phạm vi UI và tác động của lần kiểm tra

Đã quan sát trực tiếp bằng trình duyệt giao diện Harness, trạng thái plugin, cuộc hội thoại gọi tool và trang Harness của PokeDev. PokeDev được phục vụ bằng bản frontend production đã có cùng API tại `http://127.0.0.1:7860`; không tuyên bố đã build hoặc kiểm tra toàn bộ mã frontend mới nhất.

Lệnh khởi động frontend phát triển bị hệ thống duyệt tự động từ chối và không trả lý do cụ thể. Để tiếp tục theo cách ít quyền hơn, lần kiểm tra dùng API backend với thư mục frontend đã build; không chạy lại lệnh khởi động dev server bị chặn.

Đã bật container Harness hiện có và một backend PokeDev dùng một worker để kiểm tra. Không thay provider/model, endpoint, secret, permission hay recipe. Chỉ tạo một workspace trống và một phiên kiểm tra, sau đó gửi lượt health thứ hai vào cùng phiên. Đối chiếu SHA-256 sau lượt VPN xác nhận **383 tệp đã được bảo vệ vẫn không thay đổi**. Không chạy test job/performance, không truy xuất/ghi/xóa memory, không merge/push hoặc tự duyệt của con người. Hai UI được giữ mở để người dùng xem lại.

## Bằng chứng

[Bản ghi mới nhất sau VPN](../report/plugin-check-20261019/evidence-after-vpn.json) giữ metadata, hai kết quả tool và readiness ADLC được gọi lại. [Bản ghi trước VPN](../report/plugin-check-20261019/evidence.json) giữ nguyên hai lỗi kết nối. Các bản ghi công bố không chứa token, cookie, mật khẩu hay toàn bộ prompt hệ thống.

![Kết quả thành công và tóm tắt trên Harness sau VPN](../report/plugin-check-20261019/harness-health-after-vpn-summary.png)

![TestForge được nạp trong Harness](../report/plugin-check-20261019/harness-testforge-loaded.png)

![AgentMemory được nạp trong Harness](../report/plugin-check-20261019/harness-agentmemory-loaded.png)

![Lịch sử trước VPN: hai tool trả lỗi mạng trên UI](../report/plugin-check-20261019/harness-health-network-errors.png)

![Trạng thái tích hợp trên PokeDev](../report/plugin-check-20261019/pokedev-harness-readiness.png)

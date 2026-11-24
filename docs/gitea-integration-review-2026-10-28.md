# Repo Gitea liên quan tới vAIPlatform và Slack

Đối chiếu ngày 28/10/2026: liệt kê 37 repo truy cập được, kiểm tra cây nguồn
nhóm liên quan và đọc các phần Slack, lifecycle, workflow, dịch vụ kiểm chứng
và triển khai. Các kết luận bên dưới dựa trên commit đã cố định, không mặc
định commit mới nhất trong Git đã được triển khai lên máy chủ.

## Các nguồn chính

| Repo | Commit đã đọc | Vai trò và phần có thể dùng |
|---|---|---|
| [workloop](http://10.0.10.195:3000/admin/workloop) | `f59eec39` | Bot Slack, Confluence, tài liệu chờ duyệt, lifecycle, workflow/job, báo cáo và MCP. Đây là nơi nối phản hồi và trạng thái về Slack. |
| [factory-wilson](http://10.0.10.195:3000/admin/factory-wilson) | `38e9e6e`, cập nhật `2feeca4c` | Persona và cấu hình factory; runtime sau đồng bộ có 24 workflow. Bot đọc persona mỗi tin nhắn, có thể cập nhật hướng dẫn mà không khởi động lại. |
| [workloop-skill](http://10.0.10.195:3000/admin/workloop-skill) | `d9783623` | Playbook thiết kế graph, điều kiện, vòng sửa có giới hạn, tiêu chí chất lượng và phân loại rủi ro. Dùng để thiết kế trải nghiệm chỉnh workflow. |
| [vai-taskloop](http://10.0.10.195:3000/admin/vai-taskloop) | `74722a91` | Contract task, bình luận, cập nhật trạng thái và SSE. Phù hợp màn task và các điểm cần người phản hồi. |
| [vai-pokedev-services](http://10.0.10.195:3000/admin/vai-pokedev-services) | `85e7f66b` | API kiểm chứng dự án, Sandbox, TestForge, preview, protected tests và biên nhận có ràng buộc source/kế hoạch. vAIPlatform đang sử dụng nhóm dịch vụ này. |
| [agent-harness-server](http://10.0.10.195:3000/admin/agent-harness-server) | `585f1f1c` | Hạ tầng Harness, plugin, Docker và runbook vận hành máy chủ. Có thông tin đăng nhập SSH bằng khóa và script triển khai Harness. |

Các repo hỗ trợ: `phoenix-observability` phục vụ trace và quan sát;
`vai_agentmemory` phục vụ bộ nhớ; `vai-sandbox`, `vai-testforge`, `vai-secrets`
và `vai-webhook` cung cấp các dịch vụ/plugin thành phần. `vanguard` bổ sung
tài liệu thiết kế chất lượng và cổng kiểm soát.

Repo local của giao diện hiện tại có origin GitHub `VDT-2026/VDT-ADLC`, nhánh
`agentHarness`. Nó đang kết nối các dịch vụ trên; danh sách Gitea được kiểm tra
chưa có repo riêng tên ADLC/vAIPlatform cho bản giao diện local này.

## Những phần Workloop đã có

- Bot nhận DM và @mention; cùng channel/thread dùng chung phiên hội thoại
  và lifecycle. MCP ghi tài liệu Confluence vào danh mục để giao diện đọc.
- Trạng thái `needs_changes` và `review_comment` đã được lưu trong database.
  Bot có poller đọc yêu cầu sửa, đánh thức lại đúng phiên rồi gửi bản cập nhật
  vào cùng thread. Có thể nối thao tác **Yêu cầu sửa** từ giao diện vAIPlatform
  qua cơ chế hiện có, sau khi kiểm tra quyền, phiên bản và chống gửi trùng.
- Cổng duyệt tài liệu của Workloop gọi dispatch workflow khi nhận `approved`.
  Vì vậy không thể dùng thao tác đó như một nút chỉ ghi nhận quyết định trong
  vAIPlatform; cần tránh tạo hai lượt chạy cho cùng một quyết định.
- MCP có `get_run`, `get_report`, `pause_run`, `resume_run` cho job Workloop.
  Chưa thấy API nhận trạng thái lượt chạy native vAIPlatform trong nguồn đã đọc.
  Đã nối trạng thái native qua báo cáo Confluence riêng: vAIPlatform xuất ảnh
  chụp tiến độ theo lifecycle, bot tìm và đọc báo cáo của đúng thread khi được
  hỏi. Việc này dùng các công cụ Confluence và `factory_sync` đã có.

Nguồn: [bot Slack](http://10.0.10.195:3000/admin/workloop/src/commit/f59eec39ba3e31c3b715907362df4abb313a82b5/src/workloop/backend/slack_bot.py),
[lifecycle API](http://10.0.10.195:3000/admin/workloop/src/commit/f59eec39ba3e31c3b715907362df4abb313a82b5/src/workloop/backend/api/v1/lifecycle_api.py),
[MCP](http://10.0.10.195:3000/admin/workloop/src/commit/f59eec39ba3e31c3b715907362df4abb313a82b5/src/workloop/backend/mcp_server.py).

## Thay đổi mới so với lần đọc trước

Từ `561232ef` đến `f59eec39`, Gitea trả về bốn commit:

- Sửa RPC kiểm tra kết nối DSH của bot để gửi đúng dạng tham số.
- Ghi bản sao sự kiện Socket Mode vào webhook store, khử trùng theo event ID;
  giao diện có nguồn để hiển thị tin nhắn Slack đã nhận.
- Sửa xử lý Git safe-directory cho thư mục factory gắn vào container.
- Sửa đọc verdict review, phát hiện phiên còn hoạt động và xử lý stall/timeout:
  hết số lần sửa phải bị chặn, không tự coi là đạt.

Đây là thay đổi trong mã nguồn. Cần kiểm tra image/commit đang chạy để xác nhận
máy chủ đã nhận các bản sửa này.

## Cách tiếp tục đã xác minh và triển khai

Repo trực tiếp giải quyết việc cập nhật hành vi bot là **factory-wilson**.
Workloop đọc `agents/orchestrator.md` mỗi tin nhắn và có công cụ MCP
`factory_sync` để nạp lại repo đang dùng. Vì vậy nhận định trước đó rằng phải
có SSH để bot trả lời tiến độ là quá hạn chế: trường hợp này có thể làm qua
cấu hình và công cụ đang chạy.

Đã cập nhật riêng persona trên Gitea tại commit
`2feeca4c353c8031705b39db517e265f714eedf7`, giữ các thay đổi upstream mới nhất,
đồng bộ và kiểm tra runtime ở đúng commit đó. Bot được hướng dẫn tìm báo cáo
`vAIPlatform status <lifecycle>`, kiểm tra channel/thread rồi tóm tắt trạng
thái với thời điểm và link. Hỏi trạng thái không được tạo thêm tài liệu, duyệt
hoặc dispatch công việc. Không thay model hay khởi động lại Workloop.
Lần kiểm tra cuối runtime đã ở `59d77572`, thêm một commit upstream sau lần
triển khai; persona tra cứu trạng thái vẫn khớp bản đã nạp.

Bản local xuất báo cáo qua MCP Confluence hiện có; đã tạo 3 trang riêng,
không sửa tài liệu yêu cầu gốc. Bộ đồng bộ kiểm tra mỗi 15 giây khi server
chạy; đây là trạng thái định kỳ, không phải cập nhật Slack trực tiếp theo
từng sự kiện. Xem [hành trình và cấu hình](slack-document-journey.md).

## Khi cần thay mã server hoặc container

[Runbook máy chủ](http://10.0.10.195:3000/admin/agent-harness-server/src/commit/585f1f1c44e5b3315108018e941f6dd3012eb244/docs/deployment.md)
ghi SSH tới `root@10.0.10.195` bằng khóa `App.pem`; ví dụ đường dẫn trên máy
người vận hành là `C:\Users\Admin\App.pem`. Cổng 2222 trong tài liệu là SSH của
Gitea. Chưa tìm thấy khóa trong thư mục SSH hiện tại và bốn vị trí App.pem đã
kiểm tra trên máy này; chưa thực hiện đăng nhập SSH.

Workloop có Dockerfile, script khởi động container và docker-compose riêng.
Script `deploy_to_server.sh` trong agent-harness-server triển khai Harness.
Workflow Gitea của Workloop đã đọc là `lint-docs`; chưa thấy workflow triển
khai Workloop trong cấu hình này. Gitea có runner `sandbox-runner` nhưng đang
offline tại thời điểm kiểm tra. Compose được lưu chưa publish cổng MCP 8107,
trong khi dịch vụ MCP đó đang truy cập được, nên phải đối chiếu cách chạy thực
tế trước khi cập nhật container.

Thay đổi mã Python, image, cổng hoặc biến môi trường Workloop vẫn cần một
đường triển khai server được cấp quyền. Cách nạp persona ở trên đã đủ cho
việc trả lời trạng thái qua báo cáo hiện tại và không cần đường triển khai đó.

## Trạng thái vAIPlatform local

Đã build và khởi động lại bản giao diện desktop với hộp **Yêu cầu & tài liệu**,
tự đồng bộ, gắn project/channel, đọc Confluence, duyệt theo phiên bản và chuyển
sang kế hoạch/lượt chạy. Kiểm tra HTTP sau triển khai đọc được 3 tài liệu,
Confluence v8 và Harness sẵn sàng; asset đang phục vụ khớp bản build. Các kiểm
thử liên quan đã qua (72 backend, 55 giao diện); TypeScript giữ nguyên 285 lỗi nền,
không thêm chẩn đoán mới. Các ID project/workflow/run đã có được giữ nguyên.

Đã push riêng thay đổi persona vào factory-wilson và nạp cấu hình trên Workloop.
Ngày 29/10, sau phản hồi Slack do người dùng cung cấp, đã triển khai tiếp
`6b283177`: hỗ trợ chỉ rõ mã/link yêu cầu từ thread khác trong cùng channel,
đưa lựa chọn khi chưa xác định yêu cầu và không suy ra trạng thái từ việc
thiếu báo cáo. Runtime đã xác nhận nội dung; chưa xác nhận câu trả lời bot
thực tế sau bản sửa này. Không tự gửi tin nhắn Slack, chưa chạy yêu cầu nghiệp
vụ Military Youth. Các thay đổi local khác chưa được push.

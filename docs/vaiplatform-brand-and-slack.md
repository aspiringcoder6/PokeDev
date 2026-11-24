# vAIPlatform: Project mới và bot Slack hiện có

Cập nhật **28/10/2026**, giao diện desktop. Người dùng chọn dùng bot Workloop hiện có để **hỏi đáp và soạn tài liệu trước**.

## Điều hướng

- **Tổng quan workspace** (`/work`) chứa dashboard và hàng chờ cần xử lý.
- Bấm **Project mới** trong sidebar để mở `/work?view=new-project`. Trang này chứa kết nối/tạo repo Gitea, điều phối toàn workspace, workflow gói và các chức năng xây dựng mới/chu kỳ hiện có.
- Liên kết cũ `view=advanced` và `tools_project` tiếp tục mở phần điều phối và giữ bộ lọc thư mục.
- Chọn một project để dùng công việc, issue, workflow và các chức năng riêng của project.

## Thương hiệu

Tên hiển thị đổi thành **vAIPlatform** ở header, đăng nhập/đăng ký, màn tải, các trang và thông báo liên quan, tiêu đề trình duyệt, manifest và tên file tải mới.

Logo lấy từ [Workloop: frontend/public/brand/logo.svg](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/frontend/public/brand/logo.svg). Bốn path tạo biểu tượng được giữ nguyên; màu sáng dùng màu chữ hiện tại để phù hợp với theme của app. Biểu tượng dùng chung ở header, đăng nhập, tải trang và favicon. Tên hiển thị dùng đúng cách viết `vAIPlatform`.

Định danh API, khóa dữ liệu trình duyệt và định danh workflow đã lưu được giữ để tương thích với dữ liệu hiện có.

## Đối chiếu Workloop và MCP

Trang [Workloop tại cổng 8903](http://10.0.10.195:8903/workloop) tương ứng mã nguồn trong [admin/workloop](http://10.0.10.195:3000/admin/workloop), nhánh `agent-docs-langflow-dag`. Đã đối chiếu giao diện, logo, routes và [docker-compose.yml](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/docker-compose.yml), khai báo frontend cổng 8903 và backend cổng 8100. Commit nguồn tham chiếu đọc trong lượt này là `561232efe4e6d880bfe8262bc924c0a7c84a83ca`; không có endpoint xác nhận commit đã build trên máy chủ.

MCP `http://10.0.10.195:8107/mcp` đã hoàn tất bắt tay và trả danh sách công cụ. Server tự nhận `workloop-factory`, version `1.30.0`. Công cụ `integration_webhook_list` xác nhận Workloop đã đăng ký nguồn Slack.

Các phần liên quan:

- [slack_bot.py](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/src/workloop/backend/slack_bot.py): DM hoặc @mention, một thread dùng cùng phiên hội thoại, hỏi làm rõ và gọi agent soạn tài liệu; gửi link tài liệu chờ duyệt.
- [mcp_server.py](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/src/workloop/backend/mcp_server.py): công cụ workflow, agent, Gitea, Confluence và tích hợp.
- [webhooks/router.py](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/src/workloop/webhooks/router.py): đăng ký nguồn và health của connector. Connector chỉ ghi sự kiện được tắt khi bot hội thoại riêng đang nhận Socket Mode để tránh giành sự kiện.

## Cách dùng Slack trong app

Mở **Cài đặt → Slack & Workloop** (`/settings/integrations`) bằng tài khoản quản trị workspace.

1. Bấm **Kiểm tra kết nối** để đọc trạng thái Workloop, MCP và đăng ký Slack hiện tại.
2. Bấm **Mở bot trên Slack**. App ID từ link người dùng cung cấp là `A0CA54Q7FV3`, tên app `vai-orchestrator-agent`, workspace `adlcfactory`.
3. Gửi DM hoặc mời bot vào channel và @mention bot. Trả lời tiếp trong cùng thread.
4. Có thể chọn project và nhập ý tưởng ở **Chuẩn bị yêu cầu**. Bấm **Sao chép yêu cầu**, rồi dán vào hội thoại với bot. Nội dung kèm tên/repo project đã chọn và yêu cầu duyệt tài liệu trước triển khai.

Nút mở bot dùng [cách deep link chính thức của Slack](https://docs.slack.dev/interactivity/deep-linking/): `https://slack.com/app_redirect?app=A0CA54Q7FV3`. Chọn workspace `adlcfactory` nếu Slack đang mở workspace khác. Có thể bổ sung Team ID trong cấu hình server để mở thẳng đúng workspace.

“Đã có cấu hình” xác nhận Workloop có đăng ký Slack. Trạng thái này chưa chứng minh bot đã trả lời một tin nhắn cụ thể. API health của connector cũng không xác nhận sức khỏe của tiến trình bot riêng. Giao diện giữ nhãn phản hồi bot chưa được kiểm chứng cho đến khi kiểm tra hội thoại thực tế. Lượt triển khai này không tự gửi tin nhắn lên Slack.

## Cấu hình và quyền

Các địa chỉ được cấu hình trên server:

```dotenv
VAI_WORKLOOP_URL=http://10.0.10.195:8903
VAI_WORKLOOP_MCP_URL=http://10.0.10.195:8107/mcp
VAI_SLACK_APP_ID=A0CA54Q7FV3
# Tùy chọn: Team ID của workspace Slack, ví dụ T...
VAI_SLACK_TEAM_ID=
```

`GET /api/v1/adlc/live/integrations/workloop` yêu cầu đăng nhập rõ ràng và quyền quản trị workspace. Chỉ server quyết định địa chỉ đích; trình duyệt không truyền URL tùy ý. Kết quả chỉ chứa trạng thái và link, không chuyển token, phần token đã mask, payload sự kiện hoặc nội dung hội thoại ra trình duyệt.

Tích hợp dùng kết nối bot đang có tại Workloop. Không tạo connector Socket Mode thứ hai, không đổi credential hoặc cài lại Slack App. Chế độ hiện tại chỉ hỏi đáp/soạn tài liệu; việc cho bot chạy công việc vAIPlatform là phạm vi cần duyệt sau.

## Kiểm chứng

Các kiểm tra bao gồm điều hướng Project mới, dashboard không tải công cụ xây dựng, giữ liên kết cũ, thương hiệu đăng nhập/header, phân quyền kết nối, kết nối mất tạm thời, ẩn dữ liệu cache khi mất quyền, và soạn nội dung theo project. Kiểm tra thực tế đã đọc được Workloop/MCP và đăng ký Slack mà không khởi chạy workflow hoặc model.

Log, ảnh và biên bản kiểm tra cục bộ lưu ở `adlc-flow/data/vaiplatform-slack-check/`.

# Đề xuất dashboard và Slack cho PokeDev

Trạng thái cập nhật **28/10/2026**: người dùng đã duyệt và triển khai **phần 1 + 2** — dashboard workspace và hàng chờ “Cần bạn xử lý”. Xem [hướng dẫn và cách tính số liệu](workspace-dashboard-and-inbox.md). Các mục **3–5 tiếp tục chờ duyệt**.

## Kết quả đọc repo

| Nguồn | Phiên bản đã đọc | Kết quả |
|---|---|---|
| `admin/agent-harness-server` | `master`, `585f1f1c44e5b3315108018e941f6dd3012eb244` | Repo triển khai Harness, cấu hình plugin, webhook Gitea/GitHub, Secrets, Sandbox, TestForge và quan sát hệ thống. Không thấy dashboard trong ảnh hoặc một bot Slack hoàn chỉnh ở cây mã của nhánh này. |
| `admin/workloop` | `agent-docs-langflow-dag`, `54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8` | Có dashboard tương ứng ảnh, màn Integration, connector Slack Socket Mode, bot trò chuyện qua Harness và tài liệu thiết kế duyệt qua Slack. |

Nguồn cụ thể:

- [DashboardTab.tsx](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/frontend/src/workloop-tabs/DashboardTab.tsx): số việc 7 ngày, tỷ lệ hoàn tất, số workflow/chờ duyệt/webhook, biểu đồ 28 ngày, trạng thái, danh sách cần xử lý, phân bố job.
- [WorkloopSections.tsx](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/frontend/src/workloop-tabs/WorkloopSections.tsx): Runs/timeline, approval, Integration catalog, cấu hình webhook.
- [slack_bot.py](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/src/workloop/backend/slack_bot.py): nhận DM hoặc @mention, dùng `(channel, thread)` để tìm/tạo phiên Harness, trả lời vào thread, theo dõi yêu cầu soạn tài liệu bất đồng bộ và yêu cầu sửa.
- [connector.py](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/src/workloop/webhooks/connector.py): Socket Mode nhận sự kiện, bỏ tin bot, lưu sự kiện và định danh thread vào DB.
- [router.py](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/src/workloop/webhooks/router.py), [verify.py](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/src/workloop/webhooks/verify.py): cấu hình, kiểm tra token, danh sách sự kiện và trạng thái connector.
- [Thiết kế Slack bot](http://10.0.10.195:3000/admin/workloop/src/commit/54c1a2ae6931b4a8dc4a1302657ce9a81a4e79a8/docs/slack-bot-thiet-ke-va-kich-ban.md): thiết kế thread/run, duyệt có phiên bản, chuỗi sự kiện và audit.
- [Cấu hình Harness](http://10.0.10.195:3000/admin/agent-harness-server/src/commit/585f1f1c44e5b3315108018e941f6dd3012eb244/deepseek-harness/plugins/patch.yml): plugin và quy tắc webhook đang được khai báo trong repo triển khai.

Đây là xác nhận từ mã nguồn. Chưa xác minh bot Slack đang chạy hoặc workspace Slack cụ thể đã được kết nối.

## Phạm vi đề xuất để duyệt

### 1. Dashboard tổng quan workspace

Đặt khối điều hành ở đầu **Tổng quan workspace**, giữ các chức năng workflow gói/chu kỳ hiện có ở bên dưới. Không thêm tab toàn cục bắt buộc phải chọn project mới có dữ liệu.

- Lượt chạy trong 7/28 ngày; đang chạy; hoàn tất; cần phản hồi; lỗi/cần đối soát; số project và workflow đã lưu.
- Biểu đồ hoạt động theo ngày, phân bố trạng thái, phân bố công việc Developer/Tester/Reviewer.
- Lọc khoảng thời gian và project. Bấm số liệu mở đúng danh sách hiện có.
- Dùng các lượt chạy PokeDev mà người xem có quyền truy cập. Job/session con của Harness được trình bày riêng khi cần, không cộng lặp thành nhiều lượt chạy.
- Tỷ lệ thành công ghi rõ mẫu số và thời gian; `BLOCKED`, `UNCONFIRMED`, chờ duyệt không được tính thành công. Dùng múi giờ thống nhất.
- Có trạng thái tải/lỗi/chưa có dữ liệu và mốc cập nhật. Dịch vụ mất kết nối không trở thành số 0 thành tích. Chi phí ước tính giữ nhãn ước tính theo đơn giá đã cấu hình.

Nghiệm thu: số tổng khớp lịch sử/thống kê hiện có, không đọc lộ project khác, chuyển tới đúng bộ lọc, không tự chạy agent khi mở dashboard.

### 2. Hàng chờ “Cần bạn xử lý”

Đưa các việc thực sự cần người dùng vào một danh sách trên Tổng quan, dùng chung nguồn với thông báo hiện tại:

- Câu hỏi hoặc xin quyền của Harness; cổng duyệt workflow; kế hoạch chờ duyệt.
- Đề xuất xử lý issue; lượt chạy cần đối soát/phục hồi; bước bàn giao PR cần quyết định.
- Hiện project, lý do đang chờ, thời gian chờ và hành động phù hợp: Xem / Trả lời / Duyệt / Đối soát.
- Liên kết thẳng tới câu hỏi hoặc bước duyệt; không yêu cầu người dùng tự tìm trong lịch sử.

Nghiệm thu: không trùng một yêu cầu ở nhiều dòng, yêu cầu đã xử lý được cập nhật, chỉ hiển thị hành động người dùng có quyền thực hiện; giữ các kiểm tra phiên bản và trạng thái trả lời chưa chắc chắn của API hiện có.

### 3. Slack thông báo theo project — ưu tiên giai đoạn đầu

Trong Cài đặt project, chọn channel và loại sự kiện cần nhận: cần trả lời, chờ duyệt, hoàn tất, lỗi/cần phục hồi, PR sẵn sàng. Mỗi lượt chạy có một thread, cập nhật vào đúng thread thay vì tạo nhiều tin rời.

- Tin ngắn có tên project, trạng thái, lý do và liên kết mở đúng màn hình web.
- Có bật/tắt theo project, tránh lặp cùng sự kiện, và ghi nhận gửi thành công/thất bại.
- Không đưa token, nội dung file hoặc log nhạy cảm vào thông báo.
- Giai đoạn này các quyết định vẫn thực hiện ở web UI đã có phân quyền.

Nghiệm thu: đúng channel/project, thử lại không gửi trùng, lỗi Slack không làm chặn lượt chạy, tắt cấu hình thì ngừng gửi. Cần Slack App/channel; nếu nhiều thành viên sử dụng liên kết thì cần địa chỉ PokeDev dùng chung, vì `127.0.0.1` chỉ trỏ tới máy của người nhận.

### 4. Slack hai chiều — duyệt riêng sau mục 3

Trả lời câu hỏi của Harness, chọn phương án, duyệt hoặc yêu cầu sửa ngay trong thread bằng nút hoặc biểu mẫu. Có thể nhận yêu cầu mới từ @mention nhưng trước hết tạo đề xuất, tuân theo chính sách project.

- Dùng lại cùng API/trạng thái ở web UI; không có một luồng thực thi riêng bỏ qua quyền hoặc chính sách.
- Liên kết tài khoản Slack với người dùng PokeDev và giới hạn theo project/channel.
- Mỗi nút gắn đúng yêu cầu, phiên bản và lượt chạy. Nút cũ hoặc yêu cầu đã trả lời trên web không được thực hiện lần hai.
- Duyệt, phản hồi, lỗi gửi và nguồn thao tác đều vào lịch sử. Không suy diễn “đồng ý” từ emoji/tin nhắn không xác định rõ yêu cầu.

Nghiệm thu: người không có quyền bị chặn; hai người bấm hoặc Slack gửi lại sự kiện vẫn chỉ có một tác dụng; quyết định trên web và Slack đồng bộ; không tự merge/deploy vì một tin nhắn thông thường.

### 5. Trạng thái kết nối và nhật ký sự kiện

Đặt trong Cài đặt, có trạng thái thật của Harness, Gitea, model và Slack; tách **đã cấu hình**, **đã xác minh kết nối**, **lỗi**, **đang tắt**. Có mốc kiểm tra cuối và cách xử lý phù hợp.

Nhật ký trigger cho biết issue/webhook nào tạo đề xuất hoặc lượt chạy, rule nào khớp, sự kiện nào trùng/bị từ chối. Có thể phát triển webhook Gitea để giảm độ trễ của cơ chế phát hiện issue hiện tại, nhưng phải dùng chung cơ chế chống chạy lặp và chính sách tự duyệt của project.

Nghiệm thu: không đánh dấu “đã kết nối” chỉ vì có cấu hình; mất VPN hiện trạng thái chưa xác minh; dữ liệu bí mật chỉ xử lý ở backend; chế độ nhận webhook không chấp nhận secret rỗng.

## Những điểm cần chuyển đổi, không sao chép nguyên trạng

- Dashboard nguồn tính `BLOCKED` trong tỷ lệ “hoàn tất”; PokeDev cần định nghĩa số liệu phù hợp với trạng thái và bằng chứng kiểm chứng của mình.
- “Tải theo agent” trong nguồn nhóm theo node/flow; không phải đo mức sử dụng tài nguyên hoặc số agent đang chạy thực tế. PokeDev nên ghi tên số liệu đúng dữ liệu mình có.
- Integration catalog có nút chỉ hiện gợi ý; có cấu hình cũng có thể được hiện là active. Lưu cấu hình webhook còn lưu cả khi kết quả verify thất bại. Cần trạng thái và thao tác kết nối đầy đủ nếu tích hợp.
- Connector Slack nhận/lưu sự kiện và bot hỏi đáp là hai đường mã riêng; cấu hình tránh chạy đồng thời để không nhận trùng. Chưa thấy handler `block_actions` thực hiện duyệt trực tiếp trong bot đã đọc; tài liệu thiết kế rộng hơn phần bot hiện có.
- Danh tính người duyệt, binding project/run và chống thực hiện lặp phải lấy từ PokeDev. Không dùng trường tên người duyệt tự gửi trong payload làm bằng chứng phân quyền.
- Không bật các nhánh nhận webhook bỏ kiểm chữ ký khi secret chưa cấu hình.

## Thứ tự khuyến nghị

**1 + 2 trước**, sau đó **3** để có thông báo ngoài trình duyệt. Mục **4** cần thiết kế quyền và binding Slack kỹ hơn, nên duyệt thành một bước riêng. Mục **5** có thể ghép phần kiểm tra kết nối cần thiết vào mục 3; mở rộng nhật ký/webhook sau.

Tất cả thay đổi giao diện đề xuất đều dành cho desktop.

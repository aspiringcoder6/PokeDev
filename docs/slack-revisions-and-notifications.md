# Góp ý tài liệu và thông báo Slack

Giao diện desktop dùng bot Workloop hiện có. Không mở thêm kết nối Socket
Mode và không thay model Netmind đang dùng. Thông báo được gửi bằng Web API
của chính bot sau khi quản trị viên lưu Bot User OAuth Token trong
**Cài đặt → Slack & Workloop → Thông báo Slack chủ động**.

## Kết nối gửi thông báo

Lấy token của app `A0CA54Q7FV3` tại
[OAuth & Permissions](https://api.slack.com/apps/A0CA54Q7FV3/oauth).
Dùng **Bot User OAuth Token** bắt đầu bằng `xoxb-`, có quyền `chat:write`.
Bot phải có quyền gửi vào channel của yêu cầu. Không cần cài lại bot đang
hoạt động chỉ để sao chép token hiện có.

vAIPlatform gọi `auth.test`, kiểm tra đây là bot trong workspace được cấu hình
và hiển thị danh tính bot. Token được mã hóa bằng cơ chế mã hóa khóa API của
ứng dụng, lưu theo chủ sở hữu trong `intake.sqlite3`, không trả lại qua API.
Chỉ quản trị viên được đọc trạng thái kết nối, thay hoặc xóa token.

Lưu kết nối không khởi chạy agent. Những yêu cầu đã bật thông báo sẽ tiếp tục
gửi các mốc cần chú ý. Khi thay kết nối, chỉ tin bị Slack từ chối rõ ràng và
vẫn khớp trạng thái hiện tại mới được đưa lại vào hàng chờ.

## Gửi yêu cầu sửa tài liệu trên web

1. Mở **Yêu cầu & tài liệu**, chọn yêu cầu và đọc nội dung Confluence.
2. Nhập góp ý trong **Yêu cầu bot sửa tài liệu**, bấm **Gửi yêu cầu sửa về bot**.
3. Server kiểm tra quyền, lifecycle, channel/thread, tài liệu và dấu vân tay
   phiên bản đang xem. Lưu mã thao tác trước khi gửi cho Workloop.
4. vAIPlatform gọi Spec agent hiện có qua Workloop MCP `call_agent`, lưu
   `invocation_id` thật và kiểm tra đúng lượt bằng `call_agent_status`.
   Góp ý mới không phụ thuộc poller `needs_changes` cũ của Workloop, vốn chỉ
   chuyển tiếp một lần cho cùng invocation nguồn. Đích tài liệu, lifecycle,
   channel và thread đều lấy từ nguồn đã kiểm tra. Spec chỉ được yêu cầu
   sửa tài liệu, không chạy workflow triển khai.
5. Lượt phải kết thúc thành công và Confluence phải có phiên bản/nội dung
   mới thì giao diện mới báo **Tài liệu đã có phiên bản mới**. Thay đổi của
   người khác trong lúc bot còn chạy không tự hoàn tất lượt sửa. Quyết định
   duyệt cũ bị bỏ và cần xem lại. Lượt native đã chạy giữ bản yêu cầu đóng băng.

Nếu một bản sửa đăng ký invocation/document mới trong cùng lifecycle và
cùng trang Confluence, lần góp ý tiếp theo chọn invocation thật mới nhất.
Không tạo bản ghi nguồn giả để ép poller chạy lại. Trong lúc chờ bản mới,
không cho gửi thêm góp ý hoặc duyệt bản cũ. Một lệnh lập kế hoạch chưa được
đối soát cũng chặn thay đổi tài liệu.

Mất phản hồi khi gửi góp ý giữ trạng thái **Chưa xác nhận**. Nút kiểm tra
tiến độ chỉ đối soát biên nhận; không tự gửi lại lệnh có thể đã khởi chạy
model. Với yêu cầu cũ chưa có biên nhận, có thể gắn mã invocation lấy từ
phản hồi Slack trong phần chi tiết, sau khi kiểm tra cùng nguồn và thời điểm.
Agent lỗi hoặc kết thúc mà không sửa trang được báo rõ; người dùng có thể
gửi lượt mới với mã thao tác mới. Chức năng này không gọi API duyệt
`approved` của Workloop và không dispatch workflow triển khai.

## Thông báo chủ động

Bật **Thông báo trong hội thoại Slack** ở chi tiết từng yêu cầu. Đích gửi là
channel và thread nguồn đã kiểm tra, không nhận địa chỉ gửi tùy ý từ trình
duyệt. Khi bật, bot có thể gửi xác nhận trạng thái hiện tại; sau đó gửi các mốc:

- Bắt đầu lập kế hoạch hoặc thực hiện.
- Kế hoạch chờ duyệt; câu hỏi hoặc cổng cần người phản hồi.
- Lượt lỗi, cần đối soát hoặc hoàn tất.
- Tài liệu đang sửa, sửa lỗi hoặc có phiên bản mới; thay đổi bàn giao PR/merge.

Tin gồm trạng thái, số task/câu hỏi/kiểm tra và link báo cáo/web/PR khi có.
Không đưa source, log hoặc nội dung câu hỏi vào tin. Việc tăng số task hoàn
tất hoặc nhịp cập nhật sơ đồ không tạo tin liên tục. Câu hỏi mới được nhận ra
bằng mã request, kể cả khi số câu hỏi đang chờ không đổi.

Hàng chờ lưu bền vững theo chủ sở hữu và yêu cầu. Tin chờ đã lỗi thời được
thay thế bằng trạng thái mới. Tắt thông báo hủy tin còn chờ; không thu hồi
tin đã gửi. Nếu lưu quy tắc tự gắn channel, các tài liệu mới kế thừa lựa chọn
chia sẻ tiến độ và thông báo của yêu cầu dùng để tạo quy tắc.

Slack trả giới hạn tốc độ thì đợi `Retry-After`. Mất phản hồi hoặc khởi động
lại đúng lúc gửi giữ **Chưa xác nhận**, không tự phát lại tin đó. Trạng thái
gửi thành công cần phản hồi Slack có đúng channel và mã thời gian tin nhắn.
Lỗi lấy kết nối hoặc timeout trước khi gửi nội dung được thử lại sau 60 giây;
timeout trong lúc ghi/đọc phản hồi vẫn giữ **Chưa xác nhận** để tránh gửi trùng.
Mã thời gian được lưu trong biên nhận để nút **Mở thông báo đã gửi** mở đúng
tin nhắn đã được Slack xác nhận. Tin cũ chưa lưu biên nhận hoặc tin chưa xác
nhận không được gán link thành công giả.
Ngừng gửi khi tài khoản/quyền project không còn hợp lệ hoặc khi chưa giải mã
được token. Thay đổi channel/thread nguồn sẽ tắt thông báo để người dùng xem
lại đích gửi.

## Project BE đã chuẩn bị

Project `tcct-be-military-youth` được kết nối với `admin/tcct-be-military-youth`.
Repo chính là module ở thư mục gốc. Môi trường có thể ghép nguồn `.` vào một
thư mục của workspace; repo khung và các thư viện được đọc tại commit cố định.
Cache của repo khung chỉ cần Git objects, không tạo thêm một working tree lớn.

`deploy/prepare_be_project.py` chuẩn bị profile Java 21/Maven, ghép module vào
`modules/military-youth`, lấy các JAR đã có từ `tnqd-sut` và giữ đường dẫn
`../../lib` theo POM. Temurin 21 được cố định URL/SHA-256 và kiểm tra checksum
trước khi giải nén trong môi trường thử. Không ghi đè POM hoặc code nghiệp vụ.
Runtime Java được đặt trong thư mục tạm của môi trường thử, ngoài workspace
đồng bộ. Các file khởi động/cấu hình Maven được chuẩn hóa CRLF thành LF tại
đó; source Git vẫn giữ nguyên. Unit test bỏ các lớp `*IntegrationTest` cần
hạ tầng riêng; trạng thái này được phân biệt với kiểm thử API tích hợp.

Profile dùng unit test và đóng gói Maven thật. Preview BE chưa được bật; việc
khởi động API với database/quyền người dùng cần được nghiệm thu riêng.
Kiểm tra môi trường không phải một lượt agent thực hiện tính năng.

## Lưu trữ và kiểm chứng

Giữ `intake.sqlite3`, database project/workflow/run và khóa mã hóa server khi
sao lưu để khôi phục token đã mã hóa. Giữ cấu hình trong `.env.remote` và
thư mục cấu hình server ở nơi riêng; không đưa token hoặc khóa vào Git.

API mới: `/adlc/live/intake/{id}/revision`, `/adlc/live/intake/{id}/revision/check`,
`/adlc/live/intake/{id}/notifications`,
`/adlc/live/integrations/slack-notifications`. Tất cả yêu cầu đăng nhập;
quyền ghi/thực thi và quyền quản trị được kiểm tra trước thao tác bên ngoài.

Bằng chứng nằm ở `adlc-flow/data/slack-actions-check/`. Các kiểm thử kiểm tra
phiên bản/quyền, gửi trùng, hồi phục, giới hạn tốc độ, đích gửi, bảo mật token,
archive Git thật và thao tác giao diện. Kiểm thử mô phỏng Slack không thay
thế cho lần gửi thật sau khi người dùng cung cấp token. Cần kiểm chứng bot
sửa tài liệu và phản hồi trong Slack bằng một góp ý thực tế; không sửa tài
liệu đã duyệt chỉ để tạo kết quả kiểm thử giả.

Kiểm chứng thực tế ngày 29/10/2026, giờ Việt Nam:

- Lượt cũ `ag-033034-dbb664` bắt đầu 10:30, lỗi 10:35. Đã đối soát biên
  nhận vào yêu cầu #3; không còn để giao diện chờ vô hạn.
- Lượt có biên nhận `ag-095930-8f555e` gửi lúc 16:59, hiện `FAILED`.
  Nhật ký Harness xác nhận route Netmind/GLM-5.3-Flash, đọc Confluence thành
  công nhưng hai phản hồi sau đó có `outputTokens=0`. Trang vẫn phiên bản 8.
  UI hiện lỗi, mở lại ô góp ý; chưa nghiệm thu sửa tài liệu thành công.
- Thông báo chủ động đã gửi và đọc lại từ API Slack, đúng bot, channel,
  thread và mã tin nhắn. Tin xác nhận lúc 16:24 có mã
  `1793265861.825169`; thông báo lỗi gần nhất lúc 17:08 có biên nhận
  `1793268486.227229`. Nút trên web dẫn tới đúng tin trong thread nguồn.
- Danh mục Workloop có thể ghi `generated` ngay cả khi agent lỗi, không có
  link Confluence. Đây không phải bằng chứng có tài liệu hoặc đã triển khai.

Xem [tình trạng sẵn sàng quay demo](slack-demo-readiness-2026-10-29.md) để
phân biệt các bước đã nghiệm thu với phần còn cần chạy thật.

Cập nhật lúc 21:21 GMT+7: trang nguồn đã sang phiên bản 9, hiện chỉ có dòng
thông báo đang cập nhật. Người dùng xác nhận đang sửa và yêu cầu giữ nguyên.
vAIPlatform nhận bản mới, bỏ quyết định duyệt và giữ biên nhận agent cũ ở
`FAILED`; không tự coi phiên bản mới do người khác tạo là sửa thành công.

## Khi Internet bị đưa qua VPN nhưng không ra được Slack

VPN hiện truy cập bình thường; đây là ghi chú cho lỗi gián đoạn có thể tái
diễn. Kiểm tra kết nối trước khi đổi token. Không tự áp dụng route hoặc đổi
VPN; chế độ Apply bên dưới chỉ dùng khi người dùng yêu cầu rõ ràng.

`deploy/repair_slack_connection.ps1` mặc định chỉ in kế hoạch, không sửa mạng.
Script giải DNS hiện tại của `slack.com`, kiểm tra gateway Wi-Fi đang có và
chuẩn bị các route `/32` tạm thời cho riêng các địa chỉ đó. Không sửa profile
OpenVPN, không thay default gateway và không thay cấu hình Harness/Gitea.

Chỉ người dùng có quyền Administrator mới áp dụng bằng `-Mode Apply` sau
khi đã xem phương án. Các route dùng `ActiveStore`, hết hiệu lực khi khởi
động lại. `-Mode Undo` chỉ xóa các route khớp biên nhận của script. DNS Slack
có thể đổi, nên đây là biện pháp tạm để kiểm chứng kết nối trên máy hiện tại.
Việc chạy chế độ Plan không xác nhận đã sửa được đường truyền.

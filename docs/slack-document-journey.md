# Yêu cầu từ Slack trong vAIPlatform

vAIPlatform dùng bot Workloop hiện có để tiếp nhận ý tưởng và soạn tài liệu.
Tài liệu được đồng bộ vào **Yêu cầu & tài liệu** ở workspace và từng project.
Không cần gửi link Confluence cho người vận hành để nhập lại.

## Hành trình trên giao diện desktop

1. Nhắn `vai-orchestrator-agent` qua DM hoặc @mention trong channel Slack.
   Trả lời các câu hỏi trong cùng thread để bot tạo tài liệu Confluence.
2. Mở `/work?view=requests`. Khi ứng dụng đang mở, danh sách và thông báo
   được cập nhật mỗi 10 giây từ danh mục tài liệu Workloop.
3. Mở tài liệu để xem nội dung và phiên bản Confluence, cùng link hội thoại
   Slack. Chọn project Gitea, nhập chỉ dẫn bổ sung và lưu phạm vi.
   Quản trị viên có thể bật tự gắn các tài liệu mới từ channel vào project này.
4. Chọn **Duyệt cho project** hoặc **Từ chối**. Quyết định triển khai lưu
   người duyệt, thời điểm, project, repo, phiên bản và dấu vân tay nội dung.
   Thay đổi tài liệu hoặc phạm vi sẽ yêu cầu duyệt lại.
   Nếu cần sửa nội dung, dùng **Yêu cầu bot sửa tài liệu** để gửi góp ý về
   đúng thread Slack; đợi bản mới rồi xem lại và duyệt.
5. Chọn workflow đã lưu hoặc để agent đề xuất theo tài liệu, rồi bấm
   **Lập kế hoạch**. Hệ thống tạo flow, delivery và lượt chạy thuộc project
   theo cùng đường thực thi với yêu cầu được nhập trên web.
6. Xem tài liệu, chỉnh sơ đồ task nếu cần, rồi **Duyệt & thực hiện** kế hoạch.
   Theo dõi sơ đồ trạng thái, vòng review, câu hỏi, quyền và cổng duyệt ngay
   trên web. Các điểm cần người xử lý xuất hiện trong chuông thông báo.
7. Kiểm tra môi trường project, kết quả test, preview, thay đổi source và
   bàn giao Gitea trong lượt chạy. PR giữ nguồn tài liệu và phiên bản đã duyệt.
8. Bật **Tiến độ cho bot Slack** trong chi tiết yêu cầu. vAIPlatform tạo một
   báo cáo Confluence riêng, rồi cập nhật trạng thái tài liệu/lượt chạy, task,
   câu hỏi đang chờ, kết quả kiểm tra và PR. Quản trị viên có thể lưu lựa chọn
   chia sẻ cùng quy tắc channel để áp dụng cho yêu cầu mới.
9. Trong thread Slack gốc, hỏi **Kiểm tra tiến độ trên vAIPlatform**. Bot tìm
   báo cáo theo lifecycle, kiểm tra đúng channel/thread, đọc và trả lời cùng
   thời điểm cập nhật và link báo cáo. Không cần gửi link thủ công.
   Để trả lời trong cùng hội thoại, bấm số **replies** dưới tin nhắn yêu cầu
   rồi nhập vào khung **Thread**. Gửi ở ô nhập chính của channel tạo hội thoại
   mới, có mã lifecycle khác.
   Có thể hỏi ở thread khác trong cùng channel bằng mã lifecycle hoặc link
   hội thoại/tài liệu cụ thể. Nếu chưa chỉ rõ yêu cầu và thread mới chưa có
   báo cáo, bot đưa các lựa chọn cùng channel để chọn, không tự suy đoán.

Có thể bật **Thông báo trong hội thoại Slack** để bot chủ động báo các mốc
cần chú ý. Quản trị viên nhập mã bot trong Cài đặt → Slack & Workloop.
Xem [góp ý tài liệu, cấu hình và thông báo](slack-revisions-and-notifications.md).

## Phạm vi tích hợp hiện tại

- Bot vẫn hoạt động tại Workloop. Không tạo bot hay kết nối Socket Mode thứ hai.
- Tự đồng bộ bắt đầu khi một người có quyền mở vAIPlatform; đây là polling,
  chưa phải webhook đẩy từ Slack. Không cần giữ trang tài liệu đang mở.
- Danh mục nguồn chung được quản trị viên tiếp nhận. Dữ liệu local và lượt chạy
  được tách theo chủ sở hữu; các thao tác tiếp tục kiểm tra quyền project và
  quyền thực thi. Project nhóm yêu cầu adapter riêng như luồng thực thi hiện có.
- **Duyệt cho project** là quyết định của vAIPlatform. Trạng thái duyệt của
  Workloop hiển thị riêng. API duyệt của Workloop hiện tự dispatch workflow;
  vAIPlatform không gọi API đó để tránh tạo thêm một lượt chạy ngoài lựa chọn
  của người dùng.
- Bot đọc trạng thái native qua báo cáo Confluence, không truy vấn trực tiếp
  database vAIPlatform. Khi server local đang chạy, bộ đồng bộ kiểm tra thay
  đổi mỗi 15 giây; lượt đang hoạt động có bản cập nhật thời gian tối đa mỗi
  120 giây khi trạng thái không đổi. Đây là ảnh chụp trạng thái, không phải
  luồng sự kiện thời gian thực về Slack. Sơ đồ chạy trên web dùng cơ chế hiện có.
- Báo cáo tách khỏi tài liệu yêu cầu đã duyệt, có ràng buộc chủ sở hữu,
  document và lifecycle. Không ghi đè tài liệu nghiệp vụ. Quyền tài khoản và
  project được kiểm tra trước khi xuất; không xuất source, log hoặc nội dung
  câu hỏi. Chỉ quản trị viên được bật/tắt việc chia sẻ ra Confluence hiện tại.
- Tắt chia sẻ ngừng cập nhật, giữ trang báo cáo để tra cứu lịch sử. Lỗi đồng bộ
  hiện trên web và có thể thử lại. Bot phải nêu thời điểm báo cáo, không tự
  kết luận thành công từ một tài liệu đã duyệt hoặc một kết quả chưa xác nhận.
- Nội dung Confluence có thể đọc tới 60.000 ký tự. Tổng tài liệu và chỉ dẫn
  chuyển vào một kế hoạch giới hạn 20.000 ký tự theo contract delivery hiện có;
  yêu cầu dài cần chia nhỏ và không bị cắt âm thầm.
- Một lượt đã tạo giữ nguyên nội dung đã duyệt. Phiên bản mới có thể lập lượt
  kế tiếp sau khi lượt trước thành công hoặc thất bại; lịch sử cũ vẫn còn.
- Bấm lại sau lỗi mạng dùng cùng mã yêu cầu và cùng run/flow, không tạo một
  lượt khác. Có thể bỏ yêu cầu lập kế hoạch chưa tạo run rồi chọn lại phạm vi.
- Mất kết nối giữ nội dung đã lưu để đọc; duyệt và lập kế hoạch cần kiểm tra
  lại nguồn và phiên bản trực tiếp. Không có kết quả test giả hoặc duyệt tự động.

## Cấu hình và khôi phục

Các địa chỉ Workloop/MCP và Slack App ID lấy từ cấu hình server hiện có
(`VAI_WORKLOOP_URL`, `VAI_WORKLOOP_MCP_URL`, `VAI_SLACK_APP_ID`, tùy chọn
`VAI_SLACK_TEAM_ID`). Thông tin đăng nhập Confluence tiếp tục do Workloop quản lý.
`VAI_SLACK_WORKSPACE_URL` mặc định là `https://adlcfactory.slack.com/`, dùng
để tạo link về đúng hội thoại. `VAI_WORKSPACE_PUBLIC_URL` là địa chỉ mở web
trong báo cáo; mặc định `http://127.0.0.1:7861` chỉ mở đúng từ máy đang chạy app.
Đặt địa chỉ có thể truy cập chung nếu muốn thành viên khác mở từ Slack.
Giữ database `adlc-flow/data/live-projects/intake.sqlite3` cùng các database
project, workflow và lượt chạy khi sao lưu hoặc dựng lại ứng dụng. Database
intake chứa tài liệu cache, quyết định, liên kết channel, lệnh lập kế hoạch,
liên kết báo cáo và trạng thái đồng bộ để khởi động lại không tạo trang trùng.

API thuộc `/api/v1/adlc/live/intake`. Các API này yêu cầu đăng nhập,
không nhận URL server hay công cụ MCP tùy ý từ trình duyệt. Chỉ công cụ
Confluence tìm/đọc/tạo/cập nhật trang đã đăng ký trong Workloop được sử dụng.
API bật/tắt báo cáo là `POST /{document_id}/progress` với `enabled`.

## Cấu hình bot đã triển khai ngày 28/10/2026

Workloop đọc `agents/orchestrator.md` ở mỗi lượt hội thoại, kể cả phiên Slack
đã có. Repo [factory-wilson](http://10.0.10.195:3000/admin/factory-wilson)
đã được cập nhật phần tra cứu báo cáo ở commit `2feeca4c`; công cụ `factory_sync`
đã nạp và xác nhận đúng commit lúc triển khai. Lần kiểm tra cuối đợt đầu, runtime đã
tiến thêm một commit upstream (`59d77572`); nội dung persona vẫn khớp bản đã
triển khai. Không cần SSH, runner Gitea hoặc khởi động lại container cho thay
đổi hướng dẫn này.

Script `deploy/connect_slack_status.py` mặc định chỉ kiểm tra; `--apply` cập
nhật riêng persona bằng SHA hiện tại và nạp lại Factory. Script kiểm tra
Factory/runtime trước khi đồng bộ và giữ bản sao cấu hình agent đã đọc.
Thay phần hướng dẫn đã có cần `--expected-status-sha` trùng dấu vân tay phần
đang chạy; phần persona upstream khác được giữ nguyên. Nội dung thay đổi
ngoài bản đã kiểm tra sẽ chặn triển khai thay vì ghi đè.
Không cần cấp lại token Slack hay đưa thông tin Confluence về trình duyệt.

Ba yêu cầu đã có được bật báo cáo. Ví dụ:
[báo cáo yêu cầu 3](https://manhhungnguyenzwh.atlassian.net/wiki/spaces/SD/pages/3866626).
Hiện chúng chưa gắn project và chưa có lượt chạy native vAIPlatform; đây là
trạng thái thực được báo cáo. Người dùng đã cung cấp câu trả lời thực tế từ
Slack: bot tìm thấy ba báo cáo nhưng không lấy chúng làm kết quả cho một
thread mới (`lc-F9SRKP-6597911929`). Phản hồi đó xác nhận bot đang đọc hướng
dẫn mới, đồng thời cho thấy cần hỗ trợ chọn yêu cầu từ hội thoại khác.
Đã bổ sung định tuyến theo mã/link và phân biệt **thiếu báo cáo** với trạng
thái **NOT_STARTED** có bằng chứng. Cần kiểm chứng tiếp câu trả lời sau bản
cập nhật này; không tự gửi tin nhắn Slack để thử.
Ngày 29/10/2026, bản hướng dẫn tra cứu từ thread khác đã được triển khai ở
commit `6b28317702baddf732f50631ff748f3087dc504b`; runtime xác nhận đúng commit
và đúng nội dung persona. 6 kiểm thử bảo vệ cập nhật Factory và 12 kiểm thử
đồng bộ tiến độ đã qua. Truy vấn thực tế bằng lifecycle tìm thấy đúng báo cáo
cùng channel, khác thread của câu hỏi mới; chưa xác nhận câu trả lời Slack
thực tế sau lần cập nhật này.
Ba trang giữ nguyên ID khi cập nhật và đều được tìm thấy bằng truy vấn bot;
tài liệu nguồn vẫn là phiên bản 8. Build desktop và 127 kiểm thử liên quan
(72 backend, 55 giao diện) đã qua. Kiểm tra qua HTTP xác nhận app phục vụ đúng
asset đã build; chưa thực hiện kiểm tra hình ảnh trong trình duyệt.

Kịch bản Military Youth dùng để nghiệm thu và quay video cho hành trình này.
Nó không phải một hành vi cố định hay dữ liệu giả trong ứng dụng.

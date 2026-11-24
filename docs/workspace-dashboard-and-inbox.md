# Dashboard workspace và hàng chờ cần xử lý

Phần 1 + 2 của [đề xuất dashboard và Slack](dashboard-slack-review-2026-10-27.md), được người dùng duyệt và triển khai ngày **28/10/2026**. Giao diện dành cho desktop.

## Cách dùng

Mở **Tổng quan workspace** tại `/work`. Các chức năng kết nối repo, workflow gói và chu kỳ phát triển được chuyển sang nút **Project mới** trong sidebar (`/work?view=new-project`). Xem [cập nhật điều hướng và Slack](vaiplatform-brand-and-slack.md).

- Chọn **7 ngày** hoặc **28 ngày**, cùng một project hoặc tất cả project.
- Bấm thẻ số liệu, cột của một ngày hoặc trạng thái để mở lịch sử có bộ lọc tương ứng. Danh sách này dùng chỉ mục đầy đủ của dashboard, có tìm kiếm và tải thêm từng 50 lượt.
- Thẻ **Đang thực hiện** mở các lượt còn hoạt động ở mọi thời điểm, gồm lập kế hoạch và chờ phản hồi.
- Thẻ **Cần bạn xử lý** đưa tới hàng chờ hiện tại. Tìm theo tên việc, project hoặc lý do, và lọc theo loại việc.
- Bấm nút cập nhật để đọc lại ngay. Dashboard và lịch sử lọc tự cập nhật mỗi 10 giây khi được mở.

## Ý nghĩa số liệu

| Số liệu | Cách tính |
|---|---|
| Lượt tạo trong 7/28 ngày | Một lượt vAIPlatform được tính một lần theo ngày tạo ở múi giờ Việt Nam, GMT+7. |
| Tỷ lệ thành công | `SUCCEEDED / (SUCCEEDED + FAILED)` trong nhóm lượt được tạo trong khoảng đã chọn, dựa trên trạng thái hiện tại. Khi mẫu số bằng 0, hiển thị `—`. |
| Đang thực hiện | Các lượt `PLANNING` hoặc `RUNNING` hiện tại, kể cả lượt được tạo trước khoảng ngày đã chọn. |
| Cần bạn xử lý | Số yêu cầu và việc cần quyết định hiện tại, kể cả của lượt cũ. |
| Nhịp độ công việc | Các lượt nhóm theo ngày tạo; màu thành công thể hiện trạng thái thành công hiện tại của nhóm đó. |
| Trạng thái lượt chạy | Hoàn tất, đang thực hiện, chờ phản hồi/duyệt, cần đối soát, lỗi và trạng thái khác. |
| Công việc theo vai trò | Task thực thi trong nhóm lượt đã chọn: Developer, Tester, Reviewer, điều phối/kiểm chứng và vai trò khác. Bỏ qua task dùng lại phiên từ lượt trước. Các cột nhỏ phân biệt hoàn tất, chạy, chờ và trạng thái khác. |

`BLOCKED`, `UNCONFIRMED` và lượt đang chờ không được tính thành công. Trạng thái kết thúc của lượt được ưu tiên nếu node còn lưu trạng thái chờ cũ. Job hoặc session con của Harness không được cộng thêm thành lượt vAIPlatform.

Một lượt có thể có nhiều việc cần xử lý khác nhau. Một yêu cầu trùng từ nhiều nguồn chỉ xuất hiện một lần. Lượt thiếu ngày tạo hợp lệ được ghi nhận ở thông báo chất lượng dữ liệu và không được đưa vào biểu đồ theo ngày.

## Các việc trong hàng chờ

| Loại | Nơi liên kết mở tới |
|---|---|
| Câu hỏi, xin quyền, cổng duyệt workflow | Lượt chạy và đúng thẻ yêu cầu, được đưa vào vùng nhìn thấy và nhận focus. |
| Kế hoạch chờ duyệt | Tab **Tài liệu & Memory** của lượt chạy. |
| Đề xuất từ issue Gitea | Issue và đề xuất tương ứng trong project. |
| Cần đối soát/phục hồi | Mục **Phục hồi lượt chạy**, có tiến trình đã lưu nếu sẵn có. |
| Lượt lỗi hoặc bị chặn | Chi tiết lượt chạy và bằng chứng để xem cách xử lý. |
| Bàn giao | Thay đổi chưa xuất nhánh hoặc mục PR đã xuất. Trạng thái Gitea mới nhất được kiểm tra khi mở mục đó. |
| Workflow gói cần duyệt | Màn chi tiết workflow gói hiện có. Lịch sử được đọc qua các trang để giữ cả yêu cầu nằm ngoài 100 lượt gần nhất. |

Lỗi của lượt đã có lượt thử lại, hoặc đã được đóng bằng thao tác đóng lượt gián đoạn, được bỏ khỏi hàng chờ. Lịch sử vẫn giữ các lượt này. Bàn giao đã ghi nhận `MERGED` hoặc `CLOSED` không còn được nhắc.

Liên kết câu hỏi đã xử lý thông báo rằng yêu cầu không còn trong hàng chờ. Sau khi trả lời thành công, dashboard được làm mới. Phản hồi đang gửi hoặc chưa xác nhận chỉ mở trạng thái để đối soát; hàng chờ không đưa ra thao tác gửi lại.

## Quyền và trạng thái kết nối

API `GET /api/v1/adlc/live/dashboard?days=7|28&project_id=<optional UUID>` trả dữ liệu theo tài khoản đăng nhập và các project/lượt chạy mà tài khoản có quyền đọc. Project được chọn nhưng không còn quyền hoặc không tồn tại sẽ trả lỗi; không chuyển ngầm thành toàn bộ workspace. API không trả đường dẫn cache hoặc nội dung file dự án.

Nhãn hành động dựa trên quyền hiện tại; các màn trả lời, duyệt, phục hồi và bàn giao tiếp tục kiểm tra quyền và trạng thái tại thời điểm thao tác. Dashboard chỉ tạo liên kết tới các màn này. Mở dashboard không tạo lượt chạy, gọi model, xuất nhánh hoặc merge PR.

- Khi cập nhật tạm lỗi, dữ liệu đã đọc được giữ kèm thông báo và mốc cập nhật cũ.
- Khi phản hồi là 401/403/404, số liệu hoặc lịch sử lưu tạm được ẩn.
- Khi một nguồn yêu cầu chưa đọc được, hiển thị cảnh báo; tổng hàng chờ dùng `≥ N` hoặc `—` và không kết luận hàng chờ đã trống.
- Nếu đang có lượt hoạt động và mất kết nối nhận yêu cầu Harness, hiển thị trạng thái kết nối gián đoạn.
- Thời điểm chờ không có bằng chứng được hiển thị **Chưa có mốc chờ**.

## Kiểm chứng và phạm vi

Các kiểm tra bao gồm tổng và lịch sử vượt 100 lượt, phân quyền theo owner/project/flow, ranh giới ngày GMT+7, yêu cầu cũ, loại trừ phản hồi chưa chắc chắn, và giữ lịch sử sau thử lại/đóng lượt. Kiểm tra trình duyệt desktop đối chiếu số liệu thật; các tình huống trả lời câu hỏi, mở kế hoạch và phục hồi dùng dữ liệu chặn trong trình duyệt để không tác động các lượt đang lưu của người dùng.

Bằng chứng chạy kiểm tra, ảnh desktop và kết quả build lưu cục bộ ở `adlc-flow/data/workspace-dashboard-check/`. Tài liệu nguồn Workloop và khác biệt trong cách tính nằm trong đề xuất đã liên kết ở trên.

Các mục 3–5 của đề xuất (Slack và trang tích hợp/nhật ký mở rộng) tiếp tục chờ duyệt.

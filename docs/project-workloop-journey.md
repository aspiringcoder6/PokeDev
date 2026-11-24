# Hành trình công việc và Workloop trong project

Giao diện desktop tại `/work` kết nối yêu cầu, tài liệu, duyệt, thực thi, kiểm chứng và bàn giao. Chọn một lượt trong project để mở hành trình. Bấm từng chặng để mở nội dung tương ứng.

## Theo dõi lượt vAIPlatform / Harness

- Canvas tiến trình hiển thị task, phụ thuộc thực tế, nhánh có điều kiện và vòng sửa. Các task hệ thống như kiểm chứng và bàn giao xuất hiện cùng task trong kế hoạch.
- Lượt đang chạy cập nhật mỗi 3 giây, kể cả khi tab ở nền. Mất kết nối hiển thị dữ liệu đã lưu và thời điểm cập nhật cuối.
- Bấm task để xem các bước, tiêu chí nghiệm thu, phạm vi file, kết quả và session. Đường dẫn giữ task và tab đang chọn.
- Có thu phóng, kéo bố trí trong phiên xem, bản đồ nhỏ, lọc làm nổi bật trạng thái, danh sách thay thế và chế độ mở rộng. **Theo dõi** tập trung vào task đang chạy hoặc cần xử lý. `Esc` thoát chế độ mở rộng.
- Diễn biến lấy mốc thời gian thật đã lưu và trình bày theo giờ Việt Nam (UTC+7). Không tạo mốc giả cho các chặng chưa có bằng chứng.
- Chỉ hoàn tất thực thi/kiểm chứng chưa có nghĩa PR đã hợp nhất. Chặng bàn giao mở luồng Gitea hiện có.

## Liên kết các lượt từ Workloop dùng chung

Trong **Công việc** của một project, quản trị viên bấm **Liên kết lượt Workloop**, chọn một trong 100 lượt gần nhất hoặc nhập mã `job-…`, đặt tên công việc và xác nhận đúng repo.

Workloop hiện không lưu đầy đủ repo/context trong các job cũ. Vì vậy không tự gán theo tên workflow. Một job chỉ liên kết với một tài khoản/project. Các API đọc và điều khiển đều kiểm tra quyền project ở server; quyền ghi còn cần quyền thực thi. Chỉ quản trị viên được xem danh sách job dùng chung chưa liên kết.

Lượt liên kết có URL `/work?project=<id>&workloop_job=<job-id>`. Thêm `task=<node-id>` hoặc `tab=reports|context|attention` để mở đúng nội dung.

Giao diện cung cấp sơ đồ, trạng thái từng task, diễn biến, câu hỏi/xin quyền theo hợp đồng được hỗ trợ, báo cáo và điều khiển. Thông báo Workloop đã liên kết cũng xuất hiện trong chuông chung và tổng quan workspace. Dashboard giữ riêng số lượt Workloop **đã chạy xong** với số lượt vAIPlatform **đã kiểm chứng**.

## Hợp đồng trạng thái và thao tác

| Nguồn | Hiển thị / hành vi |
|---|---|
| Job `in_progress` | Đang chạy; có Tạm dừng và Dừng. |
| Job `completed` | Đã chạy xong; cần xem báo cáo và bằng chứng. Không tự gán SUCCEEDED. |
| Job `suspended` | Đã tạm dừng; có Tiếp tục qua API resume. |
| Job `interrupted` / `failed` | Đã ngắt / Lỗi. Không dùng API resume dành riêng cho suspended. |
| Node `DONE_WITH_CONCERNS` | Có lưu ý; không tô như kết quả sạch. |
| Gửi signal thành công | Đã gửi, chờ trạng thái nguồn xác nhận; không lập tức đổi job sang tạm dừng/dừng. |
| Không rõ kết quả gửi | Lưu UNCERTAIN, khóa gửi lặp và đối soát. Mã thao tác được lưu bền vững, không tự phát lại sau khởi động. |
| Yêu cầu agent | Đọc lại request và digest, xác thực đầy đủ câu trả lời, gắn người phản hồi từ tài khoản đăng nhập. Dạng chưa hỗ trợ hiện rõ và không có nút phê duyệt suy đoán. |

Sơ đồ Workloop đọc spec từ `admin/factory-wilson` tại **commit Factory đã ghi trên job**, không dùng bản workflow mới nhất để minh họa một lượt cũ. Nếu chưa lấy được đúng nguồn, chỉ hiển thị task quan sát được và báo chưa có cạnh phụ thuộc. Có bộ nhớ đệm khi nguồn tạm mất kết nối; các nút điều khiển bị khóa khi dữ liệu cũ.

Các vòng review `--r1`, `--r2` được gom vào task gốc trên sơ đồ, vẫn giữ diễn biến từng vòng. Trạng thái kết thúc từ node được ưu tiên khi bản tổng hợp cuối còn ghi `IN_PROGRESS`; task chưa có kết quả cuối trong một job đã kết thúc hiện **Cần đối soát**. Cổng duyệt đọc thêm review record được tham chiếu từ chính event của job, xác minh gate/contract trước khi cho phép phản hồi. Quyết định duyệt từ kênh khác được cập nhật trong project.

## Cấu hình và lưu trữ

- `VAI_WORKLOOP_URL`: frontend/proxy hiện có, mặc định `http://10.0.10.195:8903`.
- `VAI_WORKLOOP_FACTORY_REPOSITORY`: repo Factory dùng để đọc spec tại commit đã pin, mặc định `admin/factory-wilson`.
- Kết nối Gitea dùng cấu hình server hiện có. Không gửi token hoặc raw context/event tới trình duyệt. Báo cáo được lọc các dạng thông tin xác thực phổ biến.
- Liên kết, ảnh chụp dữ liệu công khai và nhật ký lệnh lưu tại `adlc-flow/data/live-projects/workloop.sqlite3`. Giữ tệp này cùng bản sao lưu project nếu cần khôi phục liên kết.
- GET reports của Workloop hiện có thể đồng bộ Factory để đọc báo cáo Harness; chỉ tải khi mở Báo cáo hoặc bấm đọc lại, không gọi mỗi nhịp cập nhật sơ đồ.

Không thay đổi bot Slack: bot hiện có vẫn phục vụ hỏi đáp và soạn tài liệu. Giao diện mới không tự gửi tin hoặc tự bật thực thi từ Slack. Việc chỉnh/xuất bản registry Factory, agent và các tích hợp dùng chung vẫn là các hạng mục riêng; không tự sửa toàn bộ cấu hình từ một project.

## Kiểm tra

Kiểm thử dữ liệu, quyền, trạng thái, idempotency, tình huống mất kết nối và UI ở `test_project_workloop.py`, `execution-model.test.ts`, `project-workloop.test.tsx`, cùng các kiểm thử hồi quy lượt chạy, phản hồi và dashboard. Bằng chứng build, kiểm tra desktop và kết nối nguồn lưu trong `adlc-flow/data/project-workloop-journey-check/`.

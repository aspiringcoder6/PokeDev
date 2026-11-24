# Môi trường, phục hồi và bàn giao Gitea

Triển khai E + F + G cho vAIPlatform desktop ngày 27/10/2026. Giao diện mobile không thuộc phạm vi; lựa chọn desktop đã được lưu trong [AGENTS.md](../AGENTS.md) để áp dụng cho công việc sau.

## E — Môi trường của từng project

Chọn project → **Môi trường**. Lưu tên, thư mục chạy lệnh, các lệnh cài dependency, kiểm thử và build. Mỗi dòng là một lệnh với đối số, không phải một đoạn shell; tách `&&` hoặc pipe thành các dòng riêng. Có tối đa 8 lệnh, mỗi lệnh chờ 5–600 giây. Ít nhất một lệnh kiểm thử là bắt buộc. Không nhập token/mật khẩu vào các ô này.

Nếu repo chính chỉ chứa module, chọn thêm repo khung và đường dẫn ghép module. Commit để trống được giải quyết thành commit cụ thể khi lưu; chỉnh sửa cấu hình sau đó không thay đổi lượt đang chạy. Ví dụ Military Youth:

| Trường | Ví dụ |
| --- | --- |
| Repo chính | `admin/tnqd-sut` |
| Repo khung | `admin/tcct-fe-base` |
| Module nguồn | `FE/military-youth-develop` |
| Vị trí trong khung | `src/app/modules/military-youth` |
| Thư mục chạy lệnh | `.` |

Lệnh Angular cụ thể vẫn cần được kiểm tra với dependency và trình duyệt trong Sandbox. Chọn repo khung chưa chứng minh ứng dụng đã build hoặc kiểm thử thành công. Không tự sửa cấu hình demo tài liệu của Military Youth sang Angular trong lần cập nhật này.

**Kiểm tra môi trường** đóng gói source hiện tại, chạy cài đặt/test/build thật trong Sandbox của Harness và lưu log theo mã kiểm tra. Không khởi chạy model. Baseline lỗi vẫn có thể được dùng để lập kế hoạch sửa; kết quả baseline không phải bằng chứng cho bản vá chưa được tạo. Các kết quả kiểm tra được giữ sau khi tải lại trang.

Môi trường được chụp cùng lượt mới và đưa vào digest kế hoạch. Lệnh của môi trường thay cho bộ lệnh kiểm chứng của lượt đó; preview cũng dùng cấu hình môi trường. Canvas vẫn quyết định task, phạm vi file, thứ tự, nhánh và cổng duyệt. Project chưa lưu môi trường giữ luồng hiện có. Retry giữ môi trường đã chụp của lượt nguồn.

Repo khung được đọc tại commit cố định. Archive được tạo theo thứ tự và timestamp cố định, giữ binary assets, thay toàn bộ thư mục module đã ánh xạ để không giữ file bị xóa. File agent được sửa và nhánh bàn giao vẫn thuộc repo chính. Từ chối đường dẫn thoát workspace, symlink, ánh xạ chồng nhau/cùng đích, source vượt giới hạn và file môi trường riêng tư.

## F — Phục hồi một lượt bị gián đoạn

Các lượt mới lưu checkpoint có kiểm tra binding và checksum: source/plan/model/môi trường, đầu ra task, source đã áp dụng, phiên Agent, kết quả kiểm chứng, bộ test đã khóa và vị trí trong vòng sửa.

- Mở lại ứng dụng khi worker còn sống: vAIPlatform nhận lại việc theo dõi đúng tiến trình đó. Không mở worker thứ hai.
- Worker ghi PID thực của mình; việc nhận lại kiểm tra cả đường dẫn chương trình và manifest đúng lượt. Dừng một lượt xử lý cả cây tiến trình con trên Windows và chỉ xác nhận sau khi chúng đã dừng.
- Worker đã mất: lượt hiện **Cần đối soát**, có thông báo và mục **Tiếp tục từ tiến trình đã lưu**. Chọn **Tiếp tục lượt này** để tiếp tục cùng run.
- Task hoàn tất được dùng lại. Task đã gửi cho Harness tiếp tục đợi đúng contract/session, kiểm tra lại binding của đầu vào và artifact; không gửi lại prompt đã nhận hoặc có thể đã nhận.
- Source phục hồi được dựng trong candidate riêng từ commit đóng băng rồi áp dụng các thay đổi trong checkpoint. Không tái sử dụng thư mục có thể đã ghi dở. Giữ bộ test đã khóa và vị trí vòng review; không chạy lại Developer/Tester đã hoàn tất trong vòng đó.
- Yêu cầu kiểm chứng đang gửi giữ cùng job ID và archive. Cổng duyệt tiếp tục ràng buộc với đúng source/plan; source khác không dùng được quyết định cũ.
- Giới hạn thời gian tự động đã dùng không được đặt lại khi phục hồi. Khi ứng dụng nhận lại worker còn sống, đồng hồ hoạt động của worker tiếp tục được theo dõi.

Nếu không thể tiếp tục, chọn ô **Dừng các phiên của lượt này và giữ kết quả để xem lại**, rồi **Dừng và giữ kết quả**. Chỉ dừng các phiên đã ghi nhận thuộc lượt đó. Nếu VPN mất hoặc chưa xác nhận việc hủy, giữ trạng thái cần đối soát và nút **Đối soát dừng**. Chỉ cho phép lượt mới sau khi xác nhận đã dừng; log, source và checkpoint vẫn được giữ.

Checkpoint chỉ có với các lượt bắt đầu sau bản cập nhật. Lượt cũ không được giả lập checkpoint. Nếu gián đoạn đúng lúc mở phiên chưa ghi nhận được việc gửi, đầu vào bị thay đổi hoặc Sandbox không còn bằng chứng, ứng dụng yêu cầu đối soát/dừng thay vì tự tạo công việc trùng. Native Agent có thể tiếp tục trên Harness khi ứng dụng mất kết nối; số liệu chưa quan sát được không được coi là bằng chứng hoàn tất.

## G — Pull Request và merge có kiểm soát

1. Sau khi lượt chạy thành công, mở **Thay đổi source** → **Xuất kết quả thành nhánh Gitea**.
2. Mở **Bàn giao Gitea** → **Xem nội dung PR**. Nội dung gồm yêu cầu, issue liên quan, phiên bản workflow/môi trường, source, kế hoạch, file và bằng chứng kiểm thử.
3. Xem nội dung, đánh dấu xác nhận rồi **Tạo Pull Request**. PR đã tạo được dùng lại; giữ intent trước khi gửi để không tự tạo trùng khi mất phản hồi.
4. Xem CI và review của đúng commit trên PR. vAIPlatform chặn khi head thay đổi, nhánh đích đã tiến lên từ baseline, CI chưa đạt/thiếu kiểm tra bắt buộc, review chưa đủ hoặc có yêu cầu sửa, PR đóng/nháp/xung đột.
5. Đánh dấu đồng ý merge và chọn đóng issue nếu muốn. Nếu repo không có CI, cần xác nhận riêng rằng đã xem bằng chứng Sandbox. **Duyệt và merge** gửi đúng head commit, không dùng force merge, không xóa nhánh hay thay quy tắc bảo vệ.

Gitea kiểm tra lại quy tắc bảo vệ khi nhận lệnh merge. Kiểm tra base của vAIPlatform là lần đọc trước khi gửi; API Gitea không cung cấp tham số so sánh-và-ghi cho base. Với repo dùng chung nên bật bảo vệ nhánh, chặn nhánh lỗi thời và CI bắt buộc để server kiểm soát thay đổi đồng thời. Nếu nhánh đích thay đổi, tạo lượt trên baseline mới và kiểm chứng lại.

Nếu mất phản hồi khi tạo PR hoặc merge, giữ yêu cầu và dùng **Cập nhật Gitea** để đối soát. Không tự gửi lặp một lệnh merge chưa rõ kết quả. Lỗi bị Gitea từ chối rõ ràng được tách khỏi mất phản hồi để người dùng có thể sửa điều kiện rồi thử lại. Đóng issue chỉ chạy sau khi đã xác nhận merge và có lựa chọn đóng của người dùng; việc đọc trạng thái không tự đóng issue.

Các route đều giữ phạm vi chủ sở hữu và quyền project/flow. Lưu môi trường cần quyền sửa project; kiểm tra, phục hồi, dừng, tạo PR và merge cần quyền thực thi tương ứng. Đọc thống kê, mở trang và quét issue không tự tạo PR, merge hoặc gửi bình luận.

## Kiểm chứng và tái dựng

- Kiểm thử backend gồm môi trường/CAS, archive Git thật, checkpoint/binding, phục hồi contract không gửi prompt, tiến trình review, dừng phiên, quyền API và các điều kiện PR.
- Kiểm thử giao diện gồm lưu module, baseline lỗi, xem PR trước khi gửi, xác nhận merge/thiếu CI và tiếp tục cùng run.
- Kiểm chứng phục hồi dùng engine Workloop và phương thức Driver thật: tiêm lỗi kết nối sau Developer/Tester, ghi/đọc checkpoint, dựng candidate Git mới, tiếp tục cùng run và chạy kiểm thử độc lập. Developer và Tester mỗi bên chỉ chạy một lần. Provider và vận chuyển Sandbox trong kiểm chứng này được mô phỏng; không phải một lượt Netmind thật bị ngắt.
- [verify_project_lifecycle.py](../deploy/verify_project_lifecycle.py) là smoke opt-in: một repo riêng chứa code mẫu, một SQLite riêng, baseline chạy thật trên Harness, CI lỗi ngăn merge, CI đạt cho merge, đóng issue và phát lại lệnh không tạo trùng. Không tạo native model session hay chèn run giả vào cơ sở dữ liệu ứng dụng.
- Repo kiểm thử được lưu trữ sau khi hoàn thành; [PR kiểm thử](http://10.0.10.195:3000/admin/pokedev-lifecycle-smoke-20261027-10998b/pulls/2) giữ bằng chứng bàn giao. Không thay source Military Youth hoặc các repo người dùng bởi smoke này.
- Dữ liệu xác nhận và log nằm tại `adlc-flow/data/project-lifecycle-check/`; bản sao SQLite trước cập nhật nằm trong thư mục `private/` bên trong đó. Thông tin kết nối vẫn dùng `.env.remote` và không được đưa vào tài liệu hoặc bundle.

Kết quả cuối: **182 kiểm thử backend**, **154 kiểm thử giao diện trong 23 suite** đã qua; bản dựng production và kiểm tra trực tiếp giao diện desktop đã qua. Kiểm tra kiểu dữ liệu toàn repo còn **285 lỗi có sẵn**, không có lỗi mới so với bản trước thay đổi; không coi toàn repo đã qua type-check. Bản dựng Windows dùng [build_frontend.ps1](../deploy/build_frontend.ps1) để giới hạn bộ nhớ và số luồng của công cụ build.

# Điều kiện, duyệt kết quả và thống kê project

Triển khai C + D trong PokeDev desktop, ngày 27/10/2026. Dùng Harness và Gitea qua VPN, model Netmind đã cấu hình.

## Thiết kế workflow có kiểm soát

Chọn project → **Workflow** → **Tạo workflow có điều kiện & duyệt kết quả**. Mẫu gồm Developer và Tester độc lập, Kiểm chứng, Điều kiện và Cổng duyệt. Điền file Developer được sửa và file test mới của Tester; kiểm tra các lệnh trong **Kiểm chứng & preview**, rồi lưu. Workflow được chọn khi tạo yêu cầu hoặc trong cài đặt tự động hóa từ issue.

Canvas có ba loại node mới:

- **Kiểm chứng**: chạy các lệnh và browser check đã duyệt, với bộ test giữ nguyên. Node phải chờ tất cả Tester. Kết quả lỗi kiểm thử có thể chuyển sang Điều kiện/Cổng duyệt; lỗi hạ tầng hoặc bằng chứng không khớp dừng lượt chạy.
- **Điều kiện**: nhận một đầu vào, kiểm tra “Kiểm thử đạt”, “Task đã hoàn tất” hoặc “Review đã duyệt”. Phải nối đủ **Đúng** và **Không khớp**. Dữ liệu chưa xác nhận không được coi là kiểm thử đạt hoặc đã duyệt. Hai nhánh có thể cùng tới một cổng duyệt, như trong mẫu.
- **Cổng duyệt**: chọn người dùng hoặc Agent review độc lập. Nhánh **Đã duyệt** đi tiếp; **Yêu cầu sửa** quay về Developer phía trước. Đặt 0 nếu chỉ duyệt/dừng, hoặc 1–3 vòng nếu có đường quay lại.

Hệ thống chỉ chấp nhận vòng sửa có một Developer, có Kiểm chứng trong vòng, không lồng/chồng vòng duyệt và không thoát ra ngoài trước cổng duyệt. Tổng số lượt thực hiện theo cấu hình không vượt 100. Bộ test do Tester tạo được khóa từ lần kiểm chứng đầu, không viết lại trong vòng sửa. Workflow có điều khiển không chạy thêm vòng sửa ngầm ngoài canvas.

Các nhánh không được chọn hiện **SKIPPED** và không khởi chạy Agent. Với nhiều đầu vào thường, có thể chọn cần tất cả hoặc một nhánh; đầu ra có điều kiện vẫn phải khớp nhánh đã nối. Runner giữ bước kiểm chứng cuối trước bàn giao; dùng lại bằng chứng khi toàn bộ source vẫn khớp kết quả kiểm chứng đã đạt.

Workflow cũ giữ cách thực hiện hiện có. Bản mới dùng graph version 2; mỗi lượt giữ riêng bản workflow và digest kế hoạch đã duyệt. Sửa template không thay đổi lượt đang chạy.

## Trả lời tại cổng duyệt

Thông báo chung và trang lượt chạy hiển thị yêu cầu duyệt. **Thay đổi source** và **Test & Verify** có diff/bằng chứng trước khi cần quyết định.

- **Duyệt kết quả** chỉ xuất hiện khi kiểm thử đã đạt cho đúng source đang chờ duyệt.
- **Yêu cầu sửa** cần mô tả ít nhất 5 ký tự; phản hồi chuyển tới Developer của vòng sửa.
- **Dừng lượt này** kết thúc lượt và giữ dữ liệu đã có.

Agent review chỉ có thể duyệt khi bằng chứng kiểm thử thực còn khớp source. Hết giới hạn sửa sẽ đưa về người dùng; khi kiểm thử chưa đạt chỉ có thể dừng ở bước này.

Quyết định được lưu trong SQLite, ràng buộc với người sở hữu, project, lượt chạy, phiên bản kế hoạch, source và lần duyệt. Gửi lại cùng một câu trả lời không tạo quyết định thứ hai. Một lượt retry cần quyết định mới; kết quả duyệt của lượt cũ không được tái sử dụng. Cổng duyệt của ứng dụng có thể trả lời mà không phụ thuộc websocket câu hỏi native, nhưng lượt chạy phải còn hợp lệ và đang chờ đúng kết quả. Nếu worker mất tín hiệu sau restart, hệ thống giữ trạng thái cần đối soát; không tự bỏ qua cổng duyệt.

Thời gian chờ người dùng không tiêu hao hạn mức thời gian hoạt động của lượt tự động. Câu hỏi và yêu cầu quyền native hiện có tiếp tục dùng hộp trả lời/thông báo chung.

## Đọc thống kê

Chọn project → **Thống kê**, với cửa sổ 7, 30 hoặc 90 ngày:

- Tỷ lệ thành công tính trên lượt SUCCEEDED + FAILED; lượt cần đối soát hiển thị riêng.
- Thời gian làm việc dùng đồng hồ hoạt động nếu lượt có ghi nhận, hoặc suy từ các mốc thời gian, trừ chờ người và chờ duyệt kế hoạch. Lượt cần đối soát không được suy thành thời gian hoạt động đã xác nhận.
- Các câu hỏi chờ đồng thời chỉ tính thời gian hợp nhất, tránh cộng hai lần. Số lần cần người và số task sửa/kiểm chứng dựa trên bản ghi thực hiện.
- Token đọc từ projection của session trên Harness, chỉ lưu session đã gắn với lượt chạy trong project và được phép xem. Không đếm lại session tái sử dụng; tổng project khử trùng session.
- Bảng lịch sử nối issue → phiên bản workflow đã dùng → lượt chạy → diff, kiểm thử và quyết định duyệt.

Nút **Cập nhật số liệu** chỉ đọc telemetry; không khởi chạy Agent. Ứng dụng cũng ghi nhận projection khi worker kết thúc. Session lịch sử có thể không còn trên Harness; trường hợp không có số liệu hiển thị **Chưa có dữ liệu**, không dùng 0 để thay thế. Dữ liệu cache đã ghi nhận được giữ khi mất VPN. Số session đo được/tổng session luôn đi kèm số token.

### Bảng giá

Mở **Bảng giá dùng để ước tính**, nhập đúng provider/model và nguồn hoặc ngày áp dụng giá. Bốn đơn giá USD cho mỗi 1 triệu token gồm đầu vào thường, đọc cache, ghi cache và đầu ra. Chỉ nhập 0 khi giá loại đó thực sự bằng 0. Bảng giá có kiểm tra phiên bản để tránh tab cũ ghi đè thay đổi mới.

Không có giá Netmind mặc định và không suy giá Netmind từ giá của nhà cung cấp khác. Chi phí chỉ là **ước tính theo giá người dùng cấu hình**, không phải hóa đơn. Khi thiếu giá hoặc token, hiển thị chưa có dữ liệu hoặc mức bao phủ một phần. Bảng giá không thay đổi model hay quyền tự động hóa của project.

## Kiểm chứng triển khai

- 149 kiểm thử backend và 144 kiểm thử giao diện đã qua; bản dựng production đã tạo thành công. Kiểm tra kiểu dữ liệu toàn repo còn 285 lỗi có sẵn ngoài các file tính năng được kiểm tra; không coi toàn repo đã qua type-check.
- Các bài kiểm tra backend bao gồm nhánh được chọn/bỏ qua, kế hoạch bị sửa, vòng lặp không hợp lệ, giới hạn sửa, bộ test giữ nguyên, câu trả lời bền vững và quyền truy cập project.
- Bài kiểm tra dùng Workloop engine thật và các phương thức Driver thật: kiểm thử độc lập tại máy báo lỗi, một vòng sửa, kiểm thử đạt, Agent review duyệt, hoàn tất. Provider native và vận chuyển Sandbox được mô phỏng riêng trong bài kiểm tra này; không coi đây là một lượt chạy Netmind thật.
- Giao diện desktop kiểm tra với dữ liệu lịch sử thật, đọc telemetry Harness qua VPN; các tình huống lưu canvas, nhập giá và trả lời cổng duyệt dùng fixture riêng, không thêm issue, lượt chạy hay bật tự động trong dữ liệu người dùng.

Nguồn xây dựng ý tưởng và commit đã đối chiếu được ghi trong [đánh giá factory-wilson/workloop](gitea-integration-review-2026-10-26.md). Hướng dẫn A + B: [phân loại issue và chính sách rủi ro](issue-triage-risk-policy.md).

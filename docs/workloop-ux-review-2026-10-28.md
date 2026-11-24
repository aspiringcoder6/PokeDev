# Khảo sát Workloop và định hướng UI/UX cho vAIPlatform

Ngày khảo sát: **28/10/2026**, desktop 1280×720. Đã thao tác trên `http://10.0.10.195:8903/`, đối chiếu API tại cổng 8100, MCP tại cổng 8107 và mã nguồn `admin/workloop`, nhánh `agent-docs-langflow-dag`, commit `561232efe4e6d880bfe8262bc924c0a7c84a83ca`.

Đợt này là khảo sát để duyệt hướng phát triển. Không khởi chạy, tạm dừng, tiếp tục, duyệt hoặc xóa job thật; không đổi tích hợp hay gửi tin Slack. Chưa nghiệm thu thực thi các thao tác ghi chỉ vì API đã khai báo chúng.

## Kết luận sản phẩm

Workloop có nền thực thi, workflow, agent, tài liệu, duyệt và tích hợp. Web hiện bao phủ tốt việc xem một phần dữ liệu; nhiều thao tác tạo, chỉnh, điều khiển và theo dõi kết quả chưa thành một hành trình đầy đủ. Một số số liệu và nhãn trạng thái còn sai.

Định hướng phù hợp cho **vAIPlatform**: giao diện làm việc và điều khiển thống nhất theo project, dùng khả năng thực thi của Workloop. Người dùng đi qua một chuỗi liên tục:

**Yêu cầu → hỏi làm rõ → tài liệu → duyệt → workflow/phiên bản → chạy → trả lời/phê duyệt phát sinh → kiểm chứng → bàn giao PR.**

Slack là kênh trao đổi và thông báo tùy chọn. Web cung cấp đầy đủ thao tác cho người muốn làm việc trong ứng dụng.

## Những gì đã trải nghiệm

| Khu vực | Thao tác kiểm tra | Quan sát |
|---|---|---|
| Dashboard | Xem số liệu, đồ thị, hàng chờ; đối chiếu Runs và MCP | Hiện 11 job lỗi, 0 hoàn tất, 0 đang chạy. Cùng nhóm 11 job thực tế có 2 đang chạy, 5 completed, 2 interrupted, 2 failed. |
| Canvas | Mở workflow, bấm **+ Task**, mở task `implement`, mở danh sách workflow | **+ Task** hiện thông báo chưa nối API ghi. Tên/model/brief trong inspector chỉ đọc. Có 23 workflow để chọn nhưng thiếu luồng cấu hình và chạy ngay từ đây. |
| New Workloop | Bấm nút khi đang ở canvas; đối chiếu handler | Không tạo wizard hoặc bản nháp mới. Handler đưa về khung canvas mặc định. |
| Runs | Chuyển Timeline/Bảng, mở job bị ngắt `job-42e4c54092b3` | Detail chủ yếu là các event và JSON. Không có thanh điều khiển, báo cáo kết quả theo node hoặc hướng xử lý rõ cho job này. URL vẫn là `/runs`. |
| Factory | Xem cấu hình, danh sách workflow và phiên bản | Chủ yếu đọc cấu hình và bấm Sync. Chưa có luồng xem thay đổi → chỉnh → kiểm tra → xuất bản cấu hình. |
| Agents | Xem danh mục/persona | Giao diện ghi rõ chỉ đọc, sửa qua Git; mặc định mở một bản persona dài. |
| Duyệt | Xem Chờ duyệt và Tất cả | Có 2 tài liệu PTYC đã duyệt, link Confluence, lifecycle và workflow được phép chạy. Chưa có bước chuyển tiếp rõ tới job thực hiện và sản phẩm của tài liệu đó. Không có tài liệu pending để thử duyệt thực tế. |
| Webhook | Xem nguồn, sự kiện, trạng thái rule | Xem được event và kết quả ignored/matched. Màn hình ghi rõ không có thao tác ghi. URL nhận webhook được hiển thị cần sửa/kiểm chứng. |
| Automation | Xem 4 rule, lọc theo loại duyệt | Có trigger, workflow và cổng duyệt; chưa có tạo/chỉnh/bật/tắt rule trên web. |
| Integration | Bấm **Kết nối** trên Confluence | Chỉ hiện thông báo chưa cấu hình; không mở quy trình nhập, kiểm tra và lưu kết nối. |
| Tìm kiếm | Bấm biểu tượng tìm kiếm | Không mở tìm kiếm. Thanh command palette được ghi là sắp ra mắt. |

Các ảnh đối chiếu lưu trong `adlc-flow/data/workloop-ux-audit-20261028/`. Không dùng trạng thái `completed` làm bằng chứng mọi yêu cầu và kiểm thử đã đạt.

## Các khoảng trống cần ưu tiên

### WUX-01 · P0 — Dữ liệu trạng thái phải đáng tin

Dashboard đang dùng trạng thái của task (`DONE`, `DONE_WITH_CONCERNS`, `IN_PROGRESS`, `BLOCKED`) để phân loại job. API job trả `completed`, `in_progress`, `interrupted`, `failed`. Do khác cả từ vựng lẫn chữ hoa/thường, các job rơi vào nhóm lỗi.

Nguồn: [DashboardTab.tsx](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/frontend/src/workloop-tabs/DashboardTab.tsx). Đã đối chiếu bằng `list_runs` qua MCP và bảng Runs.

Cần:

- Chuẩn hóa theo từng loại dữ liệu: job, node, yêu cầu duyệt. Chỉ chuyển hoa/thường chưa đủ.
- Phân biệt **hoàn tất thực thi** và **đạt kiểm chứng** khi đưa vào vAIPlatform.
- Tổng trạng thái phải bằng tổng job trong cùng phạm vi; thẻ số liệu mở được danh sách tương ứng.
- “Tải theo agent” hiện nhóm theo tên workflow. Đổi tên đúng ý nghĩa hoặc lấy dữ liệu task/agent thật.
- Thống nhất giờ hiển thị. Cùng job `job-f7481f4d…`, Timeline hiện 10:28 nhưng Bảng hiện 03:28 mà không ghi UTC.

### WUX-02 · P0 — Màn điều khiển lượt chạy

Mở job cần thấy ngay: đang ở bước nào, đang chờ gì, lý do lỗi/bị ngắt, bằng chứng gần nhất và hành động tiếp theo.

Backend/MCP có các khả năng liên quan nhưng màn Runs chưa nối đầy đủ:

| Khả năng | Nguồn hiện có | Yêu cầu UI |
|---|---|---|
| Chạy workflow | API `/flows/{name}/run`, MCP `run_workflow` | Form project/repo, yêu cầu, tài liệu đã duyệt, phiên bản; kiểm tra trước khi chạy. |
| Tạm dừng / dừng | API `/monitor/jobs/{id}/signal`, MCP `pause_run` | Hiển thị đang yêu cầu và xác nhận đã nhận lệnh; tạm dừng có hiệu lực tại ranh giới xử lý của engine. |
| Tiếp tục | API `/monitor/jobs/{id}/resume`, MCP `resume_run` | Chỉ cho phép khi backend xác nhận có thể tiếp tục. Hiện API yêu cầu trạng thái `suspended`; không gắn nút Resume cho mọi job bị ngắt/lỗi. |
| Xem sản phẩm | API `/monitor/jobs/{id}/reports`, MCP `get_report` | Báo cáo theo node, bằng chứng test, commit/PR, quan ngại và phần chưa hoàn tất. |
| Hỏi người / xin quyền | API `/monitor/jobs/{id}/approvals` và `/answer` | Hiện đúng câu hỏi, phương án, lý do xin quyền và form phản hồi theo yêu cầu hiện tại. |

Chạy lại sau lỗi cần chốt rõ hợp đồng tạo lượt mới/phục hồi và phạm vi bước được chạy lại. Không suy diễn khả năng này từ việc có một nút chạy workflow.

### WUX-03 · P1 — Tạo và chỉnh workflow thành thao tác hoàn chỉnh

Nguồn: [WorkflowPage.tsx](http://10.0.10.195:3000/admin/workloop/src/commit/561232efe4e6d880bfe8262bc924c0a7c84a83ca/frontend/src/workflow/WorkflowPage.tsx). Inspector dùng `readOnly`; **+ Task** chỉ hiện toast chưa nối `/configure`. Backend và MCP đã có cấu hình workflow.

Trong vAIPlatform nên dùng canvas chỉnh sửa hiện có, bổ sung:

- Tạo từ mẫu hoặc bản trống, nhân bản, tìm mẫu theo mục tiêu và khả năng thực thi.
- Form task: kết quả mong đợi, bước thực hiện, tiêu chí nghiệm thu, phạm vi file, agent/model và đầu vào/đầu ra.
- Cấu hình project/repo và các tham số còn thiếu; thông tin kết nối được giải quyết phía server.
- Kiểm tra luồng trước khi lưu/chạy, xem thay đổi, lưu phiên bản và chọn phiên bản xuất bản.
- Trình bày riêng bản thiết kế và lượt thực thi; sửa thiết kế không làm thay đổi đầu vào của lượt đang chạy.

Canvas vAIPlatform đã có nhiều thao tác này cho workflow nội bộ. Phần cần bổ sung là chuyển đổi và lưu vào đúng registry/hợp đồng thực thi Workloop.

### WUX-04 · P1 — Cần bạn xử lý bao phủ cả Workloop

Workloop có nhiều nguồn quyết định: tài liệu, review, automation approval và câu hỏi/xin quyền trong một job. Runs đang đọc approvals từ automation; câu hỏi của job có API riêng. Màn Duyệt tập trung vào spec docs.

Hàng chờ vAIPlatform đã có form trả lời cho lượt nội bộ. Cần adapter cho job Workloop để:

- Gom yêu cầu theo project, mức ưu tiên và thời gian chờ.
- Mở đúng tài liệu/node/câu hỏi cùng bằng chứng cần quyết định.
- Trả lời trên web, kiểm tra lại trạng thái trước khi gửi, phản ánh kết quả đã được backend xác nhận.
- Giữ đúng người, project, job, node và ID yêu cầu; quyền thao tác được xác minh phía server.

### WUX-05 · P1 — Nối yêu cầu, tài liệu, job và kết quả

Hai tài liệu đã duyệt có lifecycle và workflow nhưng người xem chưa có đường liên tục tới job và báo cáo triển khai. Runs lại ưu tiên tên workflow/job và JSON event.

Một **Công việc** trong project nên hiển thị:

1. Nguồn yêu cầu: web, Slack hoặc Gitea issue.
2. Hội thoại và các câu trả lời làm rõ.
3. Phiên bản tài liệu và quyết định duyệt.
4. Workflow/phiên bản thực thi cùng repo/nhánh đã chọn.
5. Job, tiến độ node và yêu cầu đang chờ.
6. Kiểm thử, báo cáo, thay đổi source và PR/bàn giao.

Mỗi phần có liên kết trực tiếp có thể chia sẻ. Chi tiết job phải có URL riêng; không bắt người nhận tìm lại một dòng trong `/runs`.

### WUX-06 · P2 — Cấu hình dịch vụ, agent và tự động hóa

- **Integration:** nút Kết nối/Ngắt kết nối hiện chỉ đổi thông báo gợi ý. Cần quy trình cấu hình, kiểm tra thật, lưu, xem lỗi và kiểm tra cuối. Tách đã cấu hình, dịch vụ phản hồi, bot nhận/trả lời và nguồn webhook nhận sự kiện.
- **Agent:** danh mục có vai trò/model/công cụ/khả năng, xem persona ở mục nâng cao; tạo bản nháp, kiểm tra và xuất bản thay đổi có phiên bản.
- **Factory:** hiển thị repo/nhánh/commit đang dùng, thay đổi chưa đồng bộ và kết quả sync.
- **Automation:** sửa trigger, điều kiện, hành động và chính sách duyệt theo project; xem thử rule sẽ khớp thế nào trước khi bật. Phần này cần bổ sung API ghi nếu Workloop hiện chỉ cung cấp danh sách rule.

Có hai điểm tích hợp cần kiểm tra/sửa trước khi làm wizard:

- UI Webhook hiện cho URL `:8903/api/v1/webhooks/slack`. GET trả 404. OpenAPI khai báo `/webhooks/{source}`; GET `:8100/webhooks/slack` trả 405 với `Allow: POST`. Chưa gửi POST sự kiện thật. Cần thống nhất URL public và proxy trước khi cho người dùng sao chép.
- MCP `integration_webhook_set` trong nguồn đang gọi POST, trong khi OpenAPI sống khai báo PUT cho lưu nguồn. Chưa thử thay cấu hình thực tế trong đợt này.

### WUX-07 · P3 — Tương tác và tính nhất quán

Tìm kiếm thật theo project/job/tài liệu/PR, thông báo có liên kết xử lý, bộ lọc có thể chia sẻ, trạng thái tải/lỗi/cũ rõ ràng, thuật ngữ thống nhất, phím tắt desktop phù hợp hệ điều hành. Các nút chưa có chức năng cần nói rõ khả năng hoặc được triển khai đầy đủ.

## Áp dụng vào vAIPlatform hiện tại

Tận dụng các phần đã có: sidebar theo project, dashboard/hàng chờ, canvas chỉnh sửa, form task/tiêu chí/phạm vi file, trả lời agent, xem bằng chứng, phục hồi và bàn giao Gitea. Các phần đó hiện phục vụ các lượt đã được vAIPlatform quản lý; không tự bao phủ mọi job của Workloop tại cổng 8903.

Cần một cầu nối dữ liệu và thao tác có ràng buộc:

**Tài khoản/project vAIPlatform ↔ repo ↔ workflow Workloop/phiên bản ↔ job ↔ lifecycle/tài liệu ↔ nguồn Slack/issue.**

Workloop đảm nhận thực thi. vAIPlatform đảm nhận hành trình người dùng, kiểm tra quyền theo project, trình bày bằng chứng và gửi hành động tới đúng nguồn thực thi. Slack và web cùng truy về một Công việc khi đã có liên kết này.

## Lộ trình đề xuất để duyệt

| Đợt | Phạm vi | Nghiệm thu chính |
|---|---|---|
| **1. Dữ liệu và điều khiển** | Cầu nối project/job, chuẩn hóa trạng thái, màn chi tiết run, tạm dừng/dừng/tiếp tục đúng trạng thái, báo cáo và yêu cầu người dùng. | Số liệu khớp nguồn; mở thẳng đúng job; yêu cầu phản hồi xử lý trên web; giao diện chỉ báo thao tác thành công sau xác nhận backend. |
| **2. Chuẩn bị và xây dựng** | Yêu cầu/hỏi làm rõ trên web, tài liệu/duyệt, canvas có lưu phiên bản vào Workloop, form chọn repo và tham số, kiểm tra trước chạy. | Hoàn thành một công việc từ yêu cầu đến kết quả trong vAIPlatform; người dùng không cần gõ lệnh MCP cho các bước thông thường. |
| **3. Vận hành thuận tiện** | Agent/Factory/Integration/Automation có chỉnh sửa và kiểm tra, tìm kiếm và thông báo thống nhất. | Tạo/sửa cấu hình qua web, thấy kết quả kiểm tra và ảnh hưởng trước khi áp dụng; lần được từ sự kiện tới công việc tương ứng. |

Ưu tiên **đợt 1**. Chất lượng hiển thị và điều khiển thực thi phải được xác nhận trước khi mở rộng thêm số lượng màn hình.

## Bằng chứng và giới hạn khảo sát

- Có 6 ảnh desktop, bản OpenAPI, danh sách công cụ MCP, tóm tắt trạng thái 11 job và kết quả kiểm tra route trong `adlc-flow/data/workloop-ux-audit-20261028/`.
- Nhóm job tại thời điểm đối chiếu: **2 in_progress, 5 completed, 2 interrupted, 2 failed**. Các job đang chạy có thể đổi trạng thái sau khảo sát.
- Không có spec doc pending để nghiệm thu quyết định duyệt thực tế. Không khởi tạo job hoặc câu hỏi giả trên dịch vụ dùng chung.
- Các API/MCP được liệt kê là khả năng đã xác minh có khai báo; thao tác ghi cần được nghiệm thu bằng kịch bản riêng khi triển khai.
- Phiên bản nguồn đã pin để đối chiếu hành vi quan sát; dịch vụ chưa cung cấp commit build để xác nhận chính xác commit đã deploy.

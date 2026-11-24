# Đề xuất tích hợp factory-wilson và workloop

Ngày đối chiếu: 26/10/2026. **Cập nhật 27/10/2026: A, B, C và D đã được người dùng duyệt và triển khai vào PokeDev desktop.** Xem [hướng dẫn phân loại issue và chính sách rủi ro](issue-triage-risk-policy.md) và [điều kiện, cổng duyệt, thống kê project](workflow-controls-and-project-metrics.md). Nội dung bên dưới giữ lại bản đánh giá ban đầu; mã nguồn của hai repo không được thay trực tiếp vào runtime hiện tại.

## Bản đã đọc

| Repo | Nhánh | Commit |
| --- | --- | --- |
| [factory-wilson](http://10.0.10.195:3000/admin/factory-wilson) | main | `bb5cb561d06fd9845f87044f045b6c241a77c01a` |
| [workloop](http://10.0.10.195:3000/admin/workloop) | agent-docs-langflow-dag | `d4370ca8ec38648175d74b50b862e48b8676392c` |

Danh sách cây mã đã được đọc đủ các trang Gitea. Nhận xét dựa trên file cấu hình, mã backend/frontend và tài liệu tại các commit này. Các báo cáo smoke test và metrics trong repo là bằng chứng lịch sử do repo ghi lại, không phải kết quả đo hệ thống đang chạy hôm nay.

## Phần issue đã thực hiện theo yêu cầu hiện tại

Trong PokeDev, chọn project rồi mở **Issue Gitea** hoặc **Cài đặt**.

- Mặc định: theo dõi issue mở mỗi 60 giây, lưu đề xuất và hiện thông báo; người dùng chọn **Lập kế hoạch**, xem kế hoạch rồi **Duyệt & thực hiện**.
- Từng project có thể chọn **Tự duyệt và thực hiện**, bộ lọc nhãn và workflow đã tạo trên canvas. Bật tự động cần xác nhận rõ trong cài đặt; áp dụng cả issue đang mở khớp bộ lọc.
- Chế độ tự động xử lý lần lượt, dùng lại luồng lập kế hoạch, kiểm thử, bằng chứng và kết quả hiện có. Câu hỏi và quyền công cụ đi qua phần phản hồi của người dùng đã có.
- Mỗi đề xuất gắn với project, số issue và bản nội dung. Trước khi lập kế hoạch và trước khi tự thực hiện, ứng dụng đọc lại issue. Đổi nội dung hoặc đóng issue ngăn việc tự duyệt kế hoạch cũ; lịch sử lượt chạy được giữ.
- Tắt theo dõi/tự động ngăn các lần khởi chạy tự động tiếp theo. Công việc đã bắt đầu tiếp tục theo vòng đời hiện có, không bị hủy giữa chừng bởi việc đổi cài đặt.
- Có thao tác bỏ qua/đưa lại đề xuất. Một issue lỗi không tự lặp vô hạn. Mất VPN giữ dữ liệu đã nhận và hiển thị trạng thái kết nối.
- Xuất bản kết quả giữ bước duyệt hiện có. Theo dõi issue dùng quyền đọc Gitea; không tự gửi bình luận, đóng issue hay merge code.

Đây là tính năng trong ứng dụng PokeDev hiện tại. Các quy tắc và cơ chế Foreman của factory-wilson không được bật theo cấu hình repo.

## A — Phân loại issue trước khi giao việc

**Nguồn đã có mã:** [TriageAgent của workloop](http://10.0.10.195:3000/admin/workloop/src/commit/d4370ca8ec38648175d74b50b862e48b8676392c/src/workloop/modules/triage_agent/triage_agent/agent.py). Module có chế độ heuristic hoặc LLM, ngưỡng tin cậy, lý do phân loại và kết quả `needs_human` kèm câu hỏi. Lớp automation của repo đã có điểm nối triage vào work request.

**Đề xuất:** mỗi đề xuất issue hiển thị “Làm ngay”, “Cần viết/làm rõ đặc tả”, hoặc “Cần bạn trả lời”, kèm lý do và câu hỏi còn thiếu. Chế độ tự động chỉ đi tiếp khi có đủ thông tin theo chính sách project. Dùng chung hộp thông báo hiện có, lưu câu trả lời vào bản yêu cầu của lượt chạy.

**Lợi ích:** giảm việc agent lập kế hoạch dựa trên issue quá mơ hồ; người dùng thấy vì sao hệ thống đề xuất làm việc đó.

**Phạm vi cần duyệt:** lựa chọn heuristic/Netmind, điều kiện chuyển sang hỏi người, nơi lưu quyết định và cách đưa câu trả lời vào kế hoạch. Module hiện có giữ audit trong bộ nhớ; tích hợp cần lưu bền vững theo project và lượt chạy. Không dùng độ tin cậy của LLM làm quyền thực hiện duy nhất.

**Ưu tiên:** cao. **Quy mô:** vừa.

## B — Tự duyệt theo mức rủi ro

**Nguồn:** [risk-tiers trong factory-wilson](http://10.0.10.195:3000/admin/factory-wilson/src/commit/bb5cb561d06fd9845f87044f045b6c241a77c01a/skills/workloop-skill/references/risk-tiers.md) và [GateKeeper của workloop](http://10.0.10.195:3000/admin/workloop/src/commit/d4370ca8ec38648175d74b50b862e48b8676392c/src/workloop/modules/fix_loop_gate/gate.py). Tài liệu factory chia R0–R3 theo khả năng hoàn tác, phạm vi ảnh hưởng, tác động ra ngoài và độ nhạy; lấy yếu tố cao nhất. GateKeeper có quyết định, người duyệt và dấu kiểm cho quy tắc tự duyệt, nhưng việc lưu bền vững thuộc ứng dụng tích hợp.

**Đề xuất:** thêm lựa chọn “Tự làm thay đổi ít rủi ro” bên cạnh hai chế độ đang có. Ví dụ sửa tài liệu hoặc code trong phạm vi đã giới hạn có thể chạy; thay đổi quyền, dữ liệu nhạy cảm, môi trường dùng chung hoặc phát hành sản phẩm luôn đưa về người duyệt. Có giới hạn số lượt và thời gian cho từng project.

**Lợi ích:** tự động hóa có phạm vi rõ hơn một công tắc bật/tắt cho mọi loại issue.

**Phạm vi cần duyệt:** bảng phân loại cụ thể, đường dẫn được phép, giới hạn lượt/thời gian và các hành động bắt buộc có người duyệt. Giữ dấu vết quy tắc, phiên bản chính sách và bằng chứng đã duyệt. Không nhập nguyên cấu hình `approval: auto` từ factory vì ý nghĩa HITL của runtime đó khác với việc người dùng duyệt kế hoạch trong PokeDev.

**Ưu tiên:** cao, phù hợp làm cùng A. **Quy mô:** vừa đến lớn.

## C — Điều kiện và vòng review có giới hạn trên canvas

**Nguồn đã có mã:** [ConditionNode trong workloop](http://10.0.10.195:3000/admin/workloop/src/commit/d4370ca8ec38648175d74b50b862e48b8676392c/src/workloop/engine/condition_task.py). [Tài liệu factory về điều kiện và cạnh ngược](http://10.0.10.195:3000/admin/factory-wilson/src/commit/bb5cb561d06fd9845f87044f045b6c241a77c01a/skills/workloop-skill/references/conditions-and-back-edges.md) mô tả nhánh theo trạng thái, cổng review và trần số vòng sửa. Báo cáo rev53 của workloop cũng nêu các lỗi từng xảy ra ở resume và review gate; cần kiểm thử riêng khi áp dụng.

**Đề xuất:** thêm node “Điều kiện” và “Duyệt kết quả” vào canvas của project: kiểm thử đạt thì đi tiếp, cần sửa thì quay về node được chỉ định, hết số vòng thì hỏi người. Hiển thị điều kiện và số vòng trên graph.

**Khoảng cách hiện tại:** worker PokeDev đã có tối đa ba lần kiểm chứng và hai lần sửa tự động. Phần mới là đưa chính sách này thành phần cấu hình trên canvas và hỗ trợ nhánh rõ ràng; không xây thêm một vòng sửa ngầm song song. Canvas hiện tại kiểm tra DAG nên hỗ trợ cạnh quay lại cần thay đổi cả mô hình và bộ kiểm tra, không chỉ vẽ thêm cạnh.

**Phạm vi cần duyệt:** schema node/cạnh, trần vòng, cơ chế dừng/resume, kiểm thử không bỏ qua cổng duyệt sau restart và cách giữ nguyên bản workflow cho từng lượt chạy.

**Ưu tiên:** sau A/B. **Quy mô:** lớn.

## D — Chi phí, thời gian và các điểm cần con người

**Nguồn đã có mã:** [metrics và observability API của workloop](http://10.0.10.195:3000/admin/workloop/src/commit/d4370ca8ec38648175d74b50b862e48b8676392c/src/workloop/backend/api/v1/metrics.py). Có thống kê jobs, kết nối Phoenix, dữ liệu token theo session và phần tính/ước lượng chi phí. Tài liệu “8 tab” là bản kế hoạch rộng hơn; không coi tất cả nội dung trong đó là tính năng đã hoàn thiện.

**Đề xuất:** bảng thống kê theo project: tỷ lệ hoàn thành, thời gian chờ người phản hồi, thời gian thực hiện, số vòng sửa, token/chi phí và liên kết bằng chứng từ issue đến lượt chạy. Hiển thị rõ số đo thực tế, ước tính hoặc chưa có dữ liệu.

**Lợi ích:** biết chế độ tự động có tiết kiệm công sức và thời gian hay đang lặp lỗi/tốn tài nguyên.

**Phạm vi cần duyệt:** dữ liệu/session được phép đọc từ Harness/Phoenix, cách tính giá Netmind đã được xác nhận, thời gian giữ dữ liệu và phạm vi hiển thị theo project. Dữ liệu tổng hợp của toàn factory cần được lọc quyền trước khi hiện trong PokeDev.

**Ưu tiên:** có thể làm độc lập sau A. **Quy mô:** vừa.

## Thứ tự đề nghị

**A + B + C + D đã được duyệt và thực hiện.** C bổ sung graph version 2 với nhánh có kiểu và vòng sửa giới hạn; workflow cũ giữ cách chạy hiện có. D dùng telemetry gắn với project, hiển thị số liệu thiếu và chỉ ước tính chi phí khi người dùng nhập đơn giá. Không bổ sung giao diện mobile theo yêu cầu.

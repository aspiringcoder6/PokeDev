# Tích hợp Coding Agent và Orchestrator ↔ Agent Harness

> Tài liệu tham chiếu tổng hợp từ hai văn bản gốc trên nhánh `agentHarness`: cách coding agent chạy việc đơn / hợp đồng đã duyệt / task loop, và cách tích hợp orchestrator với agent harness. Các bảng cấu hình, cờ bật, route API và kết quả xác minh được giữ nguyên như bản gốc; văn xuôi viết lại bằng tiếng Việt.

## Nội dung

- **Phần I — Coding Agent**: bốn tùy chọn cung cấp (việc đơn, hợp đồng, task loop, kết hợp), cấu hình giai đoạn, hành vi lần chạy kết hợp, cờ runtime cần thiết, workflow cũ và bản ghi xác minh.
- **Phần II — Orchestrator ↔ agent harness**: hành vi tích hợp, giải quyết xung đột khi merge, kết quả xác minh, giới hạn còn lại.
- **Phần III — Liên quan đến local project**: mối nối với cơ chế dự án cục bộ và xác minh flow trực tiếp.

---

## Phần I — Coding Agent: việc đơn, hợp đồng đã duyệt và task loop

`coding-agent@0.3.0` là bản phát hành công khai mới, bật tùy chọn (opt-in), hiển thị khi `ADLC_TASK_LOOP_HARNESS_ENABLED=true`.

Nó bổ sung một lựa chọn runtime vòng lặp (loop runtime) tường minh giữa Harness/OpenCode. Nếu không có cờ đó, bản phát hành `0.2.1` hiện có vẫn khả dụng với các công tắc gốc của nó.

Cách dùng: chọn một local project, bắt đầu với một requirement, rồi gắn một hợp đồng đã duyệt (approved contract), bật xác minh lặp lại, hoặc dùng cả hai cùng lúc. Các phiên bản hiện có giữ nguyên ngữ nghĩa routing/nguồn gốc. Xem [local projects](luc-chay-va-phuc-hoi.md) và phần thiết lập Harness adapter trong bản gốc `task-loop-harness-adapter.md`.

### I.1 Bốn tùy chọn cung cấp

| Tùy chọn được cung cấp | Thực thi | Hoàn thành |
| --- | --- | --- |
| Requirement | Coding profile Harness hiện có | Source patch được chụp và review gửi kết quả theo cấu hình |
| Requirement và hợp đồng đã duyệt | Guarded Harness contract profile | Bằng chứng hợp đồng ràng buộc và source patch được chụp |
| Đặc tả task loop, kèm requirement tùy chọn | Runtime mới được chọn cho từng vòng lặp: đề xuất (proposal) của Harness trong 0.3.0 hoặc OpenCode hiện có | Các kiểm tra hành vi được bảo vệ ĐẠT, sau đó là review của con người |
| Hợp đồng đã duyệt và đặc tả task loop, kèm requirement tùy chọn | Các đề xuất file của runtime mới được chọn được kernel áp dụng | Các vị từ (predicate) hợp đồng **và** các kiểm tra hành vi được bảo vệ đều ĐẠT, sau đó là review của con người |

### I.2 Cấu hình giai đoạn (stage)

Với phiên bản hiện có: chọn **Coding Agent · 0.2.1** trong trình soạn thảo giai đoạn.

- Mô tả công việc trong `requirement`.
- Trường hợp đồng đã duyệt là tùy chọn.
- **Repeat until checks pass** bật độc lập đầu vào đặc tả task-loop; nó vẫn khả dụng khi một hợp đồng đã được gắn.
- `base_commit` của đặc tả vòng lặp phải khớp revision đã review của project được chọn.

Với adapter mới: chọn **Coding Agent · 0.3.0**, rồi **Loop runtime → Harness · file proposals**.

Bản phát hành này thêm `loop_runtime` (mặc định `HARNESS`) vào các trường công khai dưới đây.

- Nâng cấp tường minh một giai đoạn cũ sẽ giữ nguyên `OPENCODE`.
- Thay đổi runtime đòi hỏi một kế hoạch (plan) mới được chấp nhận.
- Harness chỉ đề xuất thêm/thay thế (additions/replacements), không có xóa/thay đổi mode.
- Harness từ chối `max_total_cost` trước khi tạo session.
- Mức sử dụng token (token usage) của SDK được giữ lại; giá cả là không xác định, không phải 0.
- Mọi runtime tùy chọn được chọn phải được bật độc lập.

Cấu hình công khai chỉ chứa các trường sau:

```json
{
  "approved_contract_ref": null,
  "task_loop_enabled": false,
  "submission_mode": "MANUAL"
}
```

Một `configuration_overrides` rỗng dùng các mặc định đó.

- Việc đơn giản không cần hợp đồng hay cấu hình vòng lặp.
- `AUTO` submission khả dụng cho việc đơn giản.
- Gắn hợp đồng hoặc bật vòng lặp đòi hỏi `MANUAL`.

### I.3 Gắn hợp đồng đã duyệt

Để gắn hợp đồng, sao chép tham chiếu đã được owner phê duyệt thực tế từ ADLC.

Tham chiếu chứa chính xác bốn trường: `document_type`, `contract_id`, `revision` và `content_digest`. Hãy dùng revision đã duyệt và digest của nó.

Các tham chiếu sau đây xác minh THẤT BẠI:

- tham chiếu dạng bản nháp (draft);
- tham chiếu của owner khác (foreign-owner);
- tham chiếu đã bị sửa đổi (modified);
- tham chiếu dạng không được hỗ trợ (unsupported);
- tham chiếu chưa được phê duyệt (unapproved).

### I.4 Bật task loop

Để bật vòng lặp:

1. Đặt `task_loop_enabled: true`.
2. Cung cấp `inputs.task_loop_spec`.

Một đặc tả được cung cấp trực tiếp cũng bật vòng lặp trong quá trình biên dịch. Nếu đặc tả đến qua một workflow edge, cờ phải đã được bật trước để kế hoạch đòi hỏi đầu vào đó. `requirement` tùy chọn bổ sung cho đặc tả đầy đủ ở mỗi vòng lặp.

Đặc tả dùng [schema task-loop v0.2 hiện có](../../adlc-contracts/task-loop/v0.2/task-loop-spec.schema.json), gồm:

- một Git commit được ghim (pinned);
- các đường dẫn ghi (writable paths) chính xác;
- các tiêu chí chấp nhận (acceptance criteria) ánh xạ tới các check đã đăng ký;
- số vòng lặp có giới hạn.

Các check dùng runner được bảo vệ `verifier:python-unittest/0.1.0` và các file test được theo dõi. Agent không thể sửa các file test đó.

`max_iterations` của đặc tả cung cấp giới hạn số lần thử mặc định; một policy override có thẩm quyền tường minh có thể giảm nó.

### I.5 Lần chạy kết hợp

Với một lần chạy kết hợp, cung cấp cả tham chiếu đã duyệt lẫn đặc tả vòng lặp trên cùng một giai đoạn này. Mọi đường dẫn ghi phải cũng được hợp đồng cho phép. Hợp đồng đã duyệt được kiểm tra lại trong lúc thực thi và cả trong phục hồi (recovery).

### I.6 Một lần chạy kết hợp làm gì

Một `TaskRun` sở hữu toàn bộ các vòng lặp.

Mỗi vòng lặp bắt đầu một session mới với:

- toàn bộ requirement;
- toàn bộ đặc tả;
- toàn bộ hợp đồng đã duyệt;
- các file trong phạm vi hiện tại;
- các phát hiện có giới hạn từ các lần kiểm tra trước.

Hội thoại trước đó bị loại trừ. Các chỉnh sửa tích lũy trên cùng một base commit được ghim.

Cơ chế bảo vệ phía kernel:

- Executor kết hợp tạo một dự án Git riêng rỗng cho phiên model.
- Nó yêu cầu quyền công cụ session deny-all.
- Nó đòi hỏi server xác nhận các quyền đó trước khi gửi prompt.
- Model trả về một đề xuất file JSON có giới hạn.
- Kernel xác minh mọi đường dẫn và toàn bộ ứng viên tích lũy trước khi áp dụng bất kỳ thay đổi file nguồn nào.

Các hành vi sau bị từ chối:

- các đường dẫn được bảo vệ (protected paths);
- các đường dẫn bị hợp đồng loại trừ;
- vi phạm chỉ-đọc (read-only violations);
- xóa file (deletions);
- thay đổi file-mode;
- hoạt động công cụ (tool activity).

Nếu capability server này không khả dụng, việc thực thi dừng lại trước khi gửi prompt cho model.

Hình dạng quyền session của OpenCode theo [các kiểu API sinh chính thức](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/sdk/js/src/v2/gen/types.gen.ts). Quyền session được hợp nhất vào lựa chọn công cụ trong [bản triển khai request chính thức](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/opencode/src/session/llm/request.ts).

### I.7 Xác minh hai nhóm

Các test hành vi được bảo vệ chạy trên ứng viên đã chụp.

Kernel cũng đánh giá các vị từ hợp đồng được hỗ trợ:

- patch không rỗng;
- ứng viên không đổi;
- JSON thay đổi hợp lệ.

Cả hai nhóm phải ĐẠT.

- Một vị từ hợp đồng thất bại sẽ lặp lại cùng nhiệm vụ trong phạm vi ngân sách của nó, ngay cả khi mọi test hành vi đều ĐẠT.
- Các tiêu chí hợp đồng dạng ngôn ngữ tự nhiên vẫn thuộc review của con người.

### I.8 Kết quả thành công và phục hồi

Kết quả thành công bao gồm:

- `source_patch`;
- `candidate`;
- `verification_report`;
- `contract_reference`;
- `contract_verification_report`.

[Báo cáo hợp đồng](../../adlc-contracts/coding-agent/v0.1/README.md) bổ sung gắn tham chiếu đã duyệt và chính sách với cùng đặc tả và digest ứng viên.

Coordinator xác minh kết quả bền vững trước khi chấp nhận, rồi chờ phê duyệt cuối cùng của con người.

Về phục hồi:

- Các checkpoint SQLite bảo tồn các lần thử, candidate overlays, mức sử dụng và cả hai báo cáo xác minh.
- Phục hồi từ một checkpoint xác minh hoàn thành dùng bằng chứng đã lưu mà không lặp lại model hay test.
- Một lần gọi model bị gián đoạn được xử lý theo các quy tắc phục hồi vòng lặp bảo thủ hiện có.
- Thay đổi requirement, đặc tả, hợp đồng hay cấu hình thực thi sẽ vô hiệu hóa việc tái sử dụng một checkpoint không tương thích.

### I.9 Run Detail và điều khiển vòng lặp

Delivery C bổ sung một dòng thời gian vòng lặp tự động trong Run Detail, gồm:

- các session mới;
- dòng dõi (lineage) ứng viên;
- các check hành vi và hợp đồng;
- mức sử dụng;
- các lý do dừng;
- các thất bại lặp lại.

Pause, resume và cancel tái dùng các điều khiển coordinator. Các patch trước có thể được review từ vòng lặp của chúng; phê duyệt cuối cùng xác định đúng candidate và đòi hỏi patch được giữ lại của nó phải khả dụng. Phản hồi review được bảo tồn và hiển thị sau phê duyệt hoặc từ chối.

Xem Delivery C trong bản gốc `task-loop-delivery-c.md` về hành vi điều khiển, API đọc có xác thực, độ bao phủ restart, và xử lý lịch sử một phần.

### I.10 Các cờ runtime cần thiết

Các công tắc triển khai hiện có vẫn được dùng. Khởi động lại backend sau khi thay đổi chúng.

| Tính năng | Công tắc và dịch vụ cần thiết |
| --- | --- |
| Thực thi đơn giản | `ADLC_HARNESS_ENABLED=true` và Harness server/profile đã cấu hình |
| Thực thi hợp đồng không vòng lặp | Harness cộng `ADLC_CONTRACTS_ENABLED=true`, `ADLC_CONTRACT_EXECUTION_ENABLED=true` và `ADLC_CONTRACT_RECOVERY_ENABLED=true` cho contract profile được ghim |
| Task loop | `ADLC_TASK_LOOP_OPENCODE_ENABLED=true`, một `ADLC_TASK_LOOP_SOURCE_REPOSITORY` đã commit, các đường dẫn state/worktree bền vững, và OpenCode server/model đã cấu hình |
| Hợp đồng và task loop cùng lúc | Cấu hình task-loop cộng `ADLC_CONTRACTS_ENABLED=true` và `ADLC_CONTRACT_EXECUTION_ENABLED=true`; vòng lặp sở hữu sổ phục hồi (recovery ledger) riêng của nó |
| Harness task loop (0.3.0) | `ADLC_TASK_LOOP_HARNESS_ENABLED=true` trong cả ADLC và Harness, một API token vòng lặp riêng khớp, bundle plugin native chính xác, nguồn/check đáng tin và đường dẫn vòng lặp bền vững; không cần OpenCode hay callback |
| Harness hợp đồng và task loop (0.3.0) | Cấu hình Harness-loop cộng `ADLC_CONTRACTS_ENABLED=true` và `ADLC_CONTRACT_EXECUTION_ENABLED=true` |

Nguyên tắc ủy quyền:

- Package hợp nhất hiển thị khi hoặc Harness hoặc runtime task-loop được bật.
- Ủy quyền được kiểm tra theo triển khai được chọn và các tham chiếu chính xác của nó.
- Bật một runtime không ủy quyền mọi tính năng tùy chọn.
- Một tính năng được yêu cầu nhưng không khả dụng sẽ thất bại tường minh.

Vòng lặp giữ model OpenCode ghim từ Delivery B. Thực thi đơn giản và chỉ-hợp-đồng giữ các Harness profile đã phát hành và plugin lock của chúng. Package công khai mới hợp nhất cấu hình và orchestration trong khi giữ các tích hợp runtime hiện có.

[Ranh giới vòng lặp trung lập runtime](../task-loop/bien-gioi-runtime.md) tách cả hai chế độ vòng lặp khỏi lớp truyền provider. [Adapter Harness native](../task-loop/bien-gioi-runtime.md) bổ sung các route 0.3.0 bật tùy chọn tường minh bên cạnh các route OpenCode gốc. Run Detail hiển thị runtime đã checkpoint thực tế và các giới hạn kế toán.

Lưu ý ranh giới: chụp dữ liệu, Verify được bảo vệ, bằng chứng hợp đồng và phê duyệt vẫn nằm trong ADLC. Đây không phải là tuyên bố rằng mọi plugin Harness có một vòng đời hợp nhất; ký duyệt live SDK/provider thực tế vẫn đang chờ. Không có migration hay fallback tự động.

Về an toàn workspace:

- Đây là các worktree phát triển đáng tin cậy trên máy cục bộ.
- Unittest thực thi mã Python của ứng viên trên host.
- Các kiểm soát tiến trình hiện có và môi trường đã làm sạch không phải là một container mã độc.
- Baseline nguồn, các check được bảo vệ, và provider runtime đã cấu hình phải đáng tin.
- Xem các ranh giới workspace Delivery B trong bản gốc `task-loop-delivery-b.md`.

### I.11 Các workflow cũ và ví dụ

Danh mục package mặc định trình bày Coding Agent hợp nhất.

Các phiên bản chính xác cũ vẫn được đăng ký cho các workflow đã lưu và kế hoạch đã chấp nhận:

- `coding-agent-deepseek-harness`
- `coding-agent-contract-harness`
- `task-loop-opencode`

`GET /api/v1/adlc/node-packages?include_legacy=true` gồm các định nghĩa đó đã được ủy quyền; đọc theo phiên bản chính xác vẫn khả dụng.

Khi sửa một giai đoạn cũ, **Use unified Coding Agent** giữ nguyên requirement/đặc tả, tham chiếu đã duyệt, tên, objective, và các ngân sách lần thử/timeout được hỗ trợ. Việc lưu thay đổi đòi hỏi một kế hoạch mới được biên dịch và phê duyệt. Các kế hoạch đã chấp nhận hiện có không bị viết lại.

Các kế hoạch được sinh ra cũng giữ nguyên hợp đồng đã duyệt, cấu hình vòng lặp, đặc tả, và các chính sách được hỗ trợ của giai đoạn. Cả hai triển khai planner đều bảo tồn phiên bản package chính xác. Một giai đoạn vòng lặp vẫn là một nhiệm vụ đề xuất duy nhất; xác minh từ chối việc tách đặc tả hay đổi gán package của nó.

Export và trình diễn live-loop hiện dùng `coding-agent@0.2.0`:

```powershell
cd adlc-flow
.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop_live --spec <spec.json> --export-workflow <workflow.json>
```

Tạo kho mẫu/đặc tả theo hướng dẫn chuẩn bị Delivery B. Thực thi live của trình diễn chờ review của con người thực tế sau khi các check ĐẠT.

Chạy các check offline thực thi, hợp đồng, package, API, persistence và tương thích từ thư mục gốc kho:

```powershell
.\adlc-flow\scripts\test-adlc-task-loop.ps1 -Regression
```

Các check này dùng kho Git thật và xác minh hành vi thật với các phản hồi model mô phỏng. Chúng không xác lập một lần chạy live provider thành công.

### I.12 Bản ghi xác minh — 2026-10-10

Xác minh gồm Delivery C:

- **375 backend/test tương thích** ĐẠT qua kiểm tra hồi quy (regression) và các kiểm tra operator có trọng tâm.
- **73 frontend test** ĐẠT.
- Cân bằng schema task-loop, Coding Agent và operator ĐẠT.
- Các kiểm tra lint/format executor có trọng tâm ĐẠT.
- Kiểm tra whitespace thay đổi có theo dõi ĐẠT.
- Các file planner thay đổi không tạo phát hiện lint nào ngoài các vấn đề hiện có.
- Kiểm tra type frontend có trọng tâm tìm thấy 0 lỗi trong 17 file thuộc sở hữu; vẫn báo 15 lỗi dependency không liên quan ở nơi khác.
- Một lần chạy live model vẫn chưa được xác minh.

---

## Phần II — Tích hợp Orchestrator và agent harness

Tích hợp được xác minh ngày 2026-10-09.

Việc này hoàn tất merge đang tiến triển trên `agentHarness`, kết hợp `7a9cc0d` với `origin/orchestrator` tại `84fde0a`.

Scheduler và harness giờ dùng chung một đường thực thi. Merge bảo tồn control plane của orchestrator trong khi khôi phục:

- định danh lần thử (attempt) bền vững của harness;
- các quyết định của con người;
- xác minh hợp đồng;
- review source-patch.

### II.1 Hành vi tích hợp

| Lĩnh vực | Kết quả |
| --- | --- |
| Lập lịch | Thứ tự dependency, giới hạn đồng thời, cạnh điều kiện success/failure/always, hành vi router/join/barrier/delay, retry tự động với backoff, pause/resume/cancel, và deadline cùng tồn tại với thực thi harness. Materialization kế hoạch mang ngân sách đồng thời và giữ xác minh hợp đồng. |
| Restart recovery | Phục hồi quan sát request và lần thử nguyên bản đã đóng băng. Kết quả đã ký được chấp nhận trong thời gian chết được nhận từ callback ledger; một phiên live đang tồn tại được tiếp tục qua observer của executor. Phục hồi thiếu hoặc không được hỗ trợ đòi hỏi retry tường minh và không tự khởi chạy một phiên thay thế. |
| Quyết định của con người | Tương tác harness và các phê duyệt vòng đời sống sót qua restart. Hoàn thành offline vẫn vượt qua các kiểm tra bằng chứng hợp đồng và cổng phê duyệt. Tiếp tục phê duyệt và sự kiện ngoài tái dùng scheduler đang hoạt động. |
| Lịch sử bền vững | Snapshot kho giữ revision của nó cho optimistic write fencing. Một lần ghi snapshot bắt buộc thất bại sẽ dừng dispatch. Lịch sử harness cục bộ hiện có và cấu hình `ADLC_RUN_DB_PATH` tường minh vẫn dùng được; cài đặt mới dùng Langflow SQL run snapshots. |
| Artifacts | Executor, trình nhập callback, và review API dùng chung artifact store bền vững có giới hạn. Tra cứu source-patch có thể phân giải các lần thử lịch sử trong khi giữ phạm vi owner. |
| Đề xuất của planner | Cả sáu route API đề xuất được đăng ký. Thanh công cụ blueprint mở các đề xuất nhiệm vụ, hỗ trợ xác minh/tái sinh/từ chối, và chuyển một đề xuất đã duyệt thành pipeline kế hoạch bất biến hiện có. Bắt đầu một lần chạy vẫn là một hành động riêng. Provider MOCK/LLM đã cấu hình được tôn trọng và định danh đề xuất được cô lập theo owner. |
| Vòng đời ứng dụng | Startup khôi phục các lần chạy trước khi khởi động các trigger định lịch. Shutdown dừng trigger và observer, và giải phóng các service singleton. Trigger cron/webhook, xử lý phê duyệt SLA, quality gate, biểu thức, metrics, và thông báo vẫn khả dụng. |
| UI lần chạy và kế hoạch | Đồ thị dependency kế hoạch, hoạt động nhiệm vụ, attempts, artifacts, và review source-patch được hợp nhất. Các kế hoạch đã lưu cũ không có metadata executor hiển thị an toàn. |

### II.2 Giải quyết xung đột và dọn dẹp

- Kết hợp triển khai scheduler trong `run_service.py` với phục hồi harness, ngữ cảnh biên soạn/thực thi hợp đồng, tiếp nhận kết quả đã ký, và truy cập artifact.
- Kết hợp các import API và giữ các route hợp đồng/phục hồi có phạm vi owner trong khi nối các đề xuất planner và cấu trúc dịch vụ ứng dụng.
- Giữ cả xác minh hợp đồng lẫn truyền ngân sách đồng thời trong materializer.
- Loại bỏ cơ sở dữ liệu runtime attempts khỏi việc theo dõi Git và giữ lại file cục bộ. Các cơ sở dữ liệu runtime cục bộ vẫn bị ignore.
- Giữ các ADR H5 đã chấp nhận và tài liệu v0.2 đang đề xuất. Đánh số lại ADR v0.2 đề xuất thành `0016` để tránh `0012` đã được chấp nhận, và cập nhật các liên kết của nó.
- Loại bỏ các marker xung đột có sẵn trong `.env.example` tới trong khi giữ cả cấu hình thông báo operator lẫn cấu hình source-repo harness.
- Khôi phục các test phục hồi harness mà nhánh orchestrator đã bỏ qua.

### II.3 Kết quả xác minh

- Bộ test backend ADLC và controller kết hợp: **584 test ĐẠT**.
- Độ bao phủ frontend blueprint, proposal-to-run, plan detail, run detail, attempts, API client, và lịch sử: **64 test ĐẠT qua 8 suites**.
- Build production frontend: **ĐẠT**.
- So sánh type frontend với revision `agentHarness` gốc: **282 lỗi hiện có trước và sau; không tạo lỗi mới**. Kiểm tra type toàn kho vì vậy không sạch, dù build thành công.
- Migration orchestrator `99685e5e0f03`: được xác minh là một Alembic head; cả bốn bảng mới được nâng cấp và hạ cấp thành công trong SQLite cô lập.
- Cơ sở dữ liệu lần chạy cục bộ hiện có: **24 snapshot được xác minh thành công** ở chế độ chỉ đọc, không resume bất kỳ lần chạy nào.
- Các kiểm tra lint ĐẠT cho các file runtime giải quyết xung đột và tích hợp.

Độ bao phủ phục hồi gồm: callback thời gian chết, kết quả chấp nhận muộn, khôi phục cổng phê duyệt, tiếp tục tương tác, lần thử không khả dụng, snapshot đóng băng, lỗi ghi, xung đột revision, khôi phục đồng thời, và lựa chọn factory ứng dụng giữa lưu trữ lần chạy hiện có so với mới. Bộ hồi quy Git chụp/callback/restart harness đồng hành cũng ĐẠT với checkout khả dụng.

### II.4 Các giới hạn còn lại

- Adapter DSH vẫn là một tích hợp tùy chọn. Import SDK của nó là lazy nên startup REST/mock thông thường hoạt động mà không cần `dsh_web_sdk`. SDK đó không có trong môi trường này; chọn trực tiếp nó trả về `DSH_SDK_UNAVAILABLE`. Hành vi adapter DSH được test với client được tiêm (injected), không phải gateway live hay model trả phí.
- Ánh xạ session của adapter DSH gateway vẫn nằm trong tiến trình, và nó không cung cấp đầy đủ ngữ nghĩa submission/interaction của REST harness.
- Các bản nháp đề xuất vẫn nằm trong tiến trình. Các execution plan đã duyệt được lưu trữ qua kho lưu kế hoạch SQL hiện có; persistence bản nháp là công việc tương lai riêng.
- Các schema v0.2 control-flow/compensation/durable-event vẫn là tài liệu đang đề xuất. Merge này không tuyên bố đã triển khai đầy đủ runtime của chúng.
- Kiểm tra cơ sở dữ liệu dùng SQLite cô lập, không phải một cơ sở dữ liệu triển khai. Build production vẫn báo các cảnh báo chunk-size và mixed import hiện có.
- Các thay đổi cục bộ hiện có trong `agent-harness-server` được bảo tồn và bị loại khỏi merge này. Không có nhánh remote nào được đẩy.

---

## Phần III — Liên quan đến local project

Các nội dung ở Phần I áp dụng trực tiếp lên cơ chế local project và xác minh flow trực tiếp.

Để chạy coding agent trên một dự án cục bộ:

1. Chọn local project qua **Projects → Open local folder**.
2. Kế hoạch được review sẽ ghim project ID, tên hiển thị, commit, và tham chiếu nguồn đã xác minh.
3. Sau đó lần chạy mới được cho phép trên nguồn đó.

Chi tiết đầy đủ về local project, gắn kết nguồn/runtime, và kết quả kiểm tra live nằm trong tài liệu [lực chạy và phục hồi](luc-chay-va-phuc-hoi.md).

## Nguồn tổng hợp

Tài liệu này được tổng hợp từ các file sau (lưu trữ trên nhánh git `agentHarness`, đọc bằng `git show agentHarness:docs/<file>`):

- `docs/coding-agent-unified.md` — Coding Agent: simple work, approved contracts, and task loops (Phần I)
- `docs/orchestrator-harness-integration.md` — Orchestrator and agent harness integration (Phần II)

# Task loop: ba đợt bàn giao

Tài liệu này tổng hợp ba đợt bàn giao (Delivery A, B, C) của task loop ADLC thành
một dòng thời gian duy nhất. Cả ba đợt đều được triển khai và kiểm định, ghi nhận
vào ngày 2026-10-10 (Asia/Saigon):

- **Đợt A** — task loop mock deterministic: chứng minh đầy đủ cơ chế lặp
  (iteration), candidate và các lý do dừng bằng mock agent, không gọi model.
- **Đợt B** — task loop OpenCode thực: một session OpenCode mới cho mỗi attempt,
  candidate tích lũy lưu trong SQLite, các kiểm tra unittest được bảo vệ chạy
  thật trong worktree Git tách biệt.
- **Đợt C** — tích hợp operator: timeline iteration, các control
  (pause/resume/cancel/retry/recover), API đọc và cổng phê duyệt cuối trong
  Run Detail.

Sau ba đợt này, biên giới runtime (2026-10-13) và adapter Harness native
proposal-only (2026-10-14) tiếp tục chuẩn hóa phần thực thi; chi tiết nằm trong
[bien-gioi-runtime.md](bien-gioi-runtime.md).

## Bối cảnh chung

Task loop trong ADLC là cơ chế hoàn thành một nhiệm vụ lập trình bằng cách lặp:
mỗi vòng lặp (iteration) mở một session agent mới, thu về một candidate (bản
chụp nội dung file tích lũy), chạy các kiểm tra độc lập bên trong ADLC, và lặp
tiếp khi kiểm tra còn TRƯỢT trong phạm vi ngân sách (budget) cho phép.

Ba đợt bàn giao chia sẻ các bất biến sau:

- Một specification (đặc tả) cố định, được ghim digest, điều khiển đúng một
  `TaskRun` ADLC (một lần chạy nhiệm vụ).
- Mỗi iteration là một `TaskRequest`/attempt mới kèm một session agent mới;
  session chỉ nhận đúng một message khởi tạo và có ID riêng.
- Prompt luôn chứa toàn bộ spec đã validate, digest SHA-256 chuẩn tắc của spec,
  candidate đứng ngay trước đó, và chỉ các phát hiện kiểm tra TRƯỢT gần nhất;
  ghi chú của agent và lịch sử hội thoại đến bị loại khỏi prompt.
- Candidate có định danh ổn định, digest nội dung và liên kết parent tường minh;
  snapshot bao gồm cả thao tác thêm, sửa và xóa file.
- Coordinator hiện có lên lịch attempt kế tiếp khi executor trả về
  `TASK_LOOP_CHECKS_FAILED` với `retryable=true`; candidate ĐẠT toàn bộ kiểm
  tra đi tới cổng phê duyệt của con người `AFTER_TASK`; chỉ phê duyệt mới hoàn
  tất nhiệm vụ và workflow.
- Không schema nhiệm vụ/workflow/state-machine nào bị đóng băng thay đổi; mọi
  bổ sung đều mang tính cộng thêm (additive).

## Đợt A — Task loop mock deterministic (2026-10-10)

### Mục tiêu

Chứng minh cơ chế task loop hoàn chỉnh bằng một mock agent deterministic: ba
iteration đi từ kiểm tra TRƯỢT một phần đến ĐẠT toàn bộ, dừng đúng tại cổng
phê duyệt của con người, không gọi model và không đụng đến repository thật.

### Phạm vi

- Demo tự dựng plan mẫu trong bộ nhớ: build, validate, phê duyệt và
  materialize; chỉ ghép các mock executor và dùng in-memory run repository.
- Không nạp `.env`, không kích hoạt provider thật, không sửa checkout
  repository, không gọi model.
- Gói opt-in `task-loop@0.1.0` mang nhãn **Task Loop (Mock)**.

### Thiết kế

Kịch bản demo sinh ra một artifact phép cộng qua ba iteration:

| Iteration | Thay đổi của candidate | Tiêu chí mock | Kết quả |
| --- | --- | --- | --- |
| 1 | Thêm `math_utils.py` | 1/3 ĐẠT | Retry |
| 2 | Giữ nguyên phần cài đặt, thêm `settings.json` | 2/3 ĐẠT | Retry |
| 3 | Giữ cả hai file, thêm `README.md`, xóa `legacy.txt` | 3/3 ĐẠT | Chờ phê duyệt cuối |

Quy tắc prompt và session:

- Mỗi prompt chứa toàn bộ spec đã validate, digest SHA-256 chuẩn tắc của spec,
  candidate đứng trước đó một cách chính xác, và chỉ các phát hiện của tiêu chí
  TRƯỢT gần nhất.
- Ghi chú của agent và lịch sử hội thoại đến bị loại trừ.
- Mỗi session có ID khác nhau và đúng một message khởi tạo.
- Prompt vượt quá kích thước sẽ thất bại trước khi session được tạo; spec không
  bao giờ bị cắt ngắn.

Định danh và lịch sử candidate:

- Candidate có định danh ổn định, digest nội dung và liên kết parent tường minh.
- Snapshot bao gồm thêm, sửa và xóa file.
- Đọc lịch sử luôn trả về bản sao, nên việc xem một candidate không thể làm
  thay đổi iteration kế tiếp.
- Bằng chứng iteration vẫn tra cứu được qua `MockTaskLoopExecutor.history()` và
  được gắn vào metadata của kết quả cuối (terminal result) mà không nhân bản
  byte prompt/file vào từng mục lịch sử.

### Endpoint và state mới

Đợt A không thêm endpoint HTTP nào; trạng thái candidate/session và biên lai
idempotency (idempotency receipts) đều là process-local. Việc xuất workflow chỉ
là một `WorkflowDefinition` để kiểm tra bằng mắt, không phải canvas JSON của
Langflow, và vẫn dùng được với compiler/materializer hiện có.

### Chạy demo

Từ thư mục `adlc-flow`, dùng virtual environment hiện có:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop --output ..\examples\task-loop-mock-report.json
```

Kết quả mong đợi: TRƯỢT (1/3), TRƯỢT (2/3), ĐẠT (3/3), sau đó `WAITING_APPROVAL`.
Demo build, validate, phê duyệt và materialize plan mẫu của chính nó trong bộ
nhớ. Nó không nạp `.env`, không kích hoạt provider thật, không sửa checkout
repository và không gọi model.

Để chạy đủ vòng hoàn tất với người duyệt được mô phỏng tường minh:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop --simulate-approval --output ..\examples\task-loop-mock-approved-report.json
```

Báo cáo sẽ gắn nhãn phê duyệt này là mô phỏng; đó không phải chữ ký của con
người hay model thật.

Định nghĩa workflow sẵn sàng kiểm tra cũng có thể tạo lại:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop --export-workflow ..\examples\task-loop-mock-workflow.json
```

### Gói opt-in và hành vi dừng

- Gói `task-loop@0.1.0` bị ẩn theo chính sách gói mặc định; executor factory
  cũng bỏ qua route của nó. Đặt `ADLC_TASK_LOOP_MOCK_ENABLED=true` trước khi
  khởi động backend để bật cả hai, và khởi động lại sau khi đổi flag.
- Demo standalone tự chèn route mock và chính sách truy cập tường minh nên
  không cần flag môi trường.
- Ngân sách iteration thực tế là giá trị nhỏ hơn giữa `TaskLoopSpec.max_iterations`
  và `max_attempts` của chính sách retry đã phân giải. Trong ví dụ demo, cả hai
  đều là 3.
- Spec và toàn bộ mock script được ghim digest ở attempt đầu tiên; đổi bất kỳ
  thứ nào giữa chừng sẽ thất bại trước khi session mới được tạo.

| Lý do dừng | Hành vi |
| --- | --- |
| `TASK_LOOP_CHECKS_FAILED` | Tự động retry trong khi ngân sách iteration còn. |
| `TASK_LOOP_BUDGET_EXHAUSTED` | Làm thất bại attempt và ngừng lặp tự động. |
| `TASK_LOOP_STALLED` | Dừng sau số lượng candidate TRƯỢT không đổi liên tiếp đã cấu hình. |
| `TASK_LOOP_CONTEXT_BUDGET_EXCEEDED` | Thất bại trước khi tạo session. |
| `TASK_LOOP_SPEC_CHANGED` / `TASK_LOOP_POLICY_CHANGED` | Từ chối trôi (drift) của mục tiêu cố định hoặc chính sách thực thi. |
| `TASK_LOOP_STATE_UNAVAILABLE` | Từ chối iteration coordinator về sau khi checkpoint in-memory của nó thiếu. |
| `IDEMPOTENCY_CONFLICT` | Từ chối giao lại (redelivery) xung đột; giao lại giống hệt sẽ phát lại kết quả đã lưu. |

Coordinator hiện có hiển thị nhiệm vụ thất bại không được xử lý như một workflow
tạm dừng (paused) để can thiệp. Một loop đã dừng không thể tạo thêm session nào
nữa trong cùng nhiệm vụ; cần một lần chạy kế nhiệm (successor run). Hành vi hủy
lần chạy và từ chối phê duyệt giữ nguyên như cũ.

### Kiểm thử

```powershell
.\scripts\test-adlc-task-loop.ps1 -Regression
.\.venv\Scripts\python.exe -m scripts.generate_adlc_task_loop_schemas --check
```

Test runner tắt các provider đã cấu hình và chọn application data store
in-memory. Các kiểm tra bao gồm:

- Đường coordinator/phê duyệt ba attempt, file tích lũy và thao tác xóa.
- Reset ngữ cảnh (context), giao trùng (duplicate delivery), trôi spec và trôi
  script, toàn vẹn candidate.
- Ngân sách, đình trệ tiến độ (stalled progress), checkpoint thiếu, đồng bộ
  schema (schema parity), hành vi gói/routing opt-in.
- Chế độ regression còn kiểm lại phần planning, orchestration, persistence và
  API hiện có.

### Giới hạn

Đây là bằng chứng **MOCK**: verifier so sánh nội dung file khai báo một cách
chính xác. Nó không thực thi code, không chạy kiểm tra hành vi và không chứng
minh tuân thủ ngôn ngữ tự nhiên; phán định cuối cùng vẫn thuộc về con người.

- State candidate/session và biên lai idempotency là process-local.
- Ngân sách ký tự ở đây chỉ mô hình hóa giới hạn ngữ cảnh; kế toán token, chi
  phí và thời gian tổng thể cần runtime thật của Đợt B.
- Mở rộng `WHILE` chung cho v0.2 vẫn là một tính năng control-flow riêng.

## Đợt B — Task loop OpenCode thực (2026-10-10)

### Mục tiêu

Thay mock bằng agent thật: `task-loop-opencode@0.1.0`, nhãn **Task Loop
(OpenCode)**, chạy một session OpenCode mới cho mỗi attempt ADLC, lưu candidate
tích lũy vào SQLite, và chạy các kiểm tra unittest được bảo vệ thật trong một
worktree Git detached khác. Coordinator hiện có lặp lại các kiểm tra TRƯỢT
trong ngân sách và dừng tại `WAITING_APPROVAL` khi tất cả ĐẠT. Phê duyệt cuối
cùng vẫn bắt buộc là của con người.

### Phạm vi

- Các giai đoạn (stage) mới và live demo dùng tùy chọn task-loop trên gói hợp
  nhất `coding-agent@0.2.0`; một hợp đồng đã phê duyệt (approved contract) có
  thể gắn vào cùng giai đoạn đó.
- Gói gốc của Đợt B vẫn đăng ký cho các workflow hiện có.
- Provider được ghim vào profile `aigateway/MiniMax/MiniMax-M3` hiện có của
  repository. Tuyên bố "đã pass test" của provider không bao giờ được dùng làm
  bằng chứng nghiệm thu.
- Mỗi prompt gồm spec cố định đầy đủ, candidate trước đó và output kiểm tra
  TRƯỢT có chặn giới hạn; các hội thoại trước và tóm tắt của agent bị loại.
  Bất kỳ báo cáo compaction nào của OpenCode cũng làm iteration đó vô hiệu.

### Endpoint và state mới

SQLite của task loop ghi lại — trước bất kỳ callback cuối nào — các dữ liệu:

- Fingerprint của request gốc, số iteration, session ID.
- Byte candidate, review patch và bằng chứng kiểm tra (verification evidence).

Kernel lock và reservation giao dịch ngăn giao trùng hoặc hai executor riêng
lẽ cùng khởi chạy một attempt. Candidate ĐẠT tạo ra một `SOURCE_PATCH` được
giữ lại, tương thích với endpoint review giới hạn theo owner (owner-scoped)
hiện có. Thời hạn giữ payload review tiêu chuẩn vẫn là 24 giờ; candidate và
bằng chứng nằm trong database task loop.

### Cấu hình

Gói live bị ẩn mặc định. Đặt các giá trị sau vào môi trường backend rồi khởi
động lại:

```dotenv
ADLC_TASK_LOOP_OPENCODE_ENABLED=true
ADLC_TASK_LOOP_SOURCE_REPOSITORY=D:/coding/task-loop-demo/source
ADLC_TASK_LOOP_STATE_ROOT=D:/coding/task-loop-demo/state
# Tùy chọn; mặc định là STATE_ROOT/worktrees.
ADLC_TASK_LOOP_WORKTREE_ROOT=D:/coding/task-loop-demo/state/worktrees
ADLC_OPENCODE_SERVER_URL=http://127.0.0.1:4096
ADLC_OPENCODE_SERVER_USERNAME=opencode
ADLC_OPENCODE_SERVER_PASSWORD=<mật khẩu server được quản lý riêng>
```

Quy tắc bắt buộc:

- Thư mục gốc worktree phải nằm ngoài checkout nguồn.
- Nguồn phải chứa đúng commit được ghi trong spec.
- ADLC gửi model của gói tường minh đến OpenCode; không có fallback tự động sang
  model khác. OpenCode tiếp tục sở hữu provider credential của riêng nó.
- Flag `ADLC_OPENCODE_ENABLED` hiện có độc lập với gói này.

### Chuẩn bị và chạy fixture live nhỏ

Từ `adlc-flow`, chuẩn bị một repository mới mà không cần gọi model:

```powershell
$env:PYTHONPATH = (Get-Location).Path
$demo = .\.venv\Scripts\python.exe -m scripts.prepare_adlc_task_loop_live | ConvertFrom-Json
```

Fixture bắt đầu với một hàm cộng sai, tài liệu chưa đầy đủ và một file lỗi thời.
Ba test đã commit xác minh hành vi được yêu cầu. Lệnh chuẩn bị trả về đường dẫn
nguồn mới, đường dẫn spec đã ghim và một thư mục state riêng biệt; các thư mục
đích đã tồn tại bị từ chối.

Với một OpenCode server riêng đang chạy, đã xác thực, thực thi live smoke:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop_live `
  --spec $demo.spec --source $demo.source --state-root $demo.state_root `
  --output ..\examples\task-loop-live-report.json
```

Lệnh này gọi provider thật. Nó dừng tại cổng review và không phê duyệt hay merge
candidate. Owner/database standalone của nó chỉ để smoke test; với review
operator bình thường, dùng workflow đã export qua các API
workflow/plan/run đã xác thực của ứng dụng.

Export workflow mà không gọi provider:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_adlc_task_loop_live `
  --spec $demo.spec --export-workflow ..\examples\task-loop-live-workflow.json
```

### Kiểm tra độc lập và recovery bền vững

Spec liệt kê các đường ghi (writable paths) chính xác và các kiểm tra đã đăng
ký `verifier:python-unittest/0.1.0`. Quy tắc hình thái:

- Test phải tồn tại trong commit đã ghim và không được phép ghi đè.
- Mỗi tiêu chí nghiệm thu gọi tên một kiểm tra, và mọi kiểm tra phải được ánh
  xạ.
- Bản capture bao gồm thay đổi và xóa so với commit đã ghim, chứ không chỉ các
  chỉnh sửa của iteration cuối.

Việc kiểm tra tái dựng một worktree thứ hai từ commit và overlay đã lưu, chạy
một entry point unittest đáng tin trong Python isolated mode, sau đó mở các
module của candidate cho import của project. Quy tắc thất bại đóng (fail
closed):

- Lệnh nhận một môi trường nhỏ không chứa provider secret.
- Suite rỗng và suite bị bỏ qua toàn bộ đều coi là TRƯỢT.
- Timeout kết thúc toàn bộ cây tiến trình runner.
- Verifier từ chối mọi thay đổi lên candidate hoặc test được bảo vệ trong lúc
  kiểm tra.

### Recovery sau interrupt

Nếu coordinator mất một callback cuối thành công, một Retry tường minh trước
tiên sẽ nhận kết quả thành công đã lưu cho attempt gốc; nó không cấp session
mới và không tiêu thêm iteration nào.

| Giai đoạn đã lưu | Hành vi recovery |
| --- | --- |
| Reserved / agent đang chạy | Abort session đã biết nếu có thể, giữ lại candidate hoàn chỉnh cuối cùng, và báo `ADLC_RECOVERY_TASK_LOOP_INTERRUPTED`. Cần một attempt tường minh mới. |
| Candidate đã capture | Tái dựng và kiểm tra đúng những byte đó mà không gọi model lại. |
| Đã kiểm tra (verified) | Tiêu dùng bằng chứng đã lưu và hoàn tất attempt gốc mà không chạy lại model hay test. |
| Finished | Trả về đúng kết quả đã lưu. |
| Chờ phê duyệt cuối | Khôi phục cùng candidate và cổng review từ run database của coordinator. |

Các đại lượng được ghim xuyên suốt các iteration: spec, đường dẫn nguồn, commit,
model, lựa chọn agent, workspace root và chính sách attempt. Trôi cấu hình,
định danh request xung đột, checkpoint hỏng, sửa ngoài phạm vi và bằng chứng
không hợp lệ đều thất bại đóng (fail closed).

### Ngân sách và dừng

Các giới hạn iteration, stall, context và thời gian trôi (elapsed-time) đều dừng
loop. Giới hạn token/chi phí tùy chọn dùng usage được báo cáo cho session mới,
bao gồm cả các lượt gọi tool; chúng được kiểm tra giữa các iteration và sau
lần gọi hiện tại, nhưng không cung cấp điểm cắt chi tiêu cứng bên trong một lần
gọi provider. Provider lỗi và lần gọi bị gián đoạn yêu cầu retry tường minh.

### Kiểm thử

```powershell
.\scripts\test-adlc-task-loop.ps1 -Regression
```

Kiểm tra offline dùng worktree Git thật và tiến trình Python thật, với provider
được stub. Phạm vi bao gồm: sửa/xóa tích lũy, hành vi TRƯỢT → ĐẠT (fail-to-pass),
giao trùng, hủy, timeout test, suite rỗng/bị bỏ qua, trôi/hỏng dữ liệu, ngân
sách, test được bảo vệ, loại trừ credential, di chuyển HEAD của nguồn, recovery
attempt gốc và cổng review cuối bền vững.

Kết quả kiểm định Đợt B: **214 kiểm tra focused/compatibility ĐẠT**, schema
parity, kiểm tra lint/format, và smoke chuẩn bị fixture/export workflow không
gọi model. Hai cảnh báo pytest còn lại liên quan đến cấu hình timeout-plugin
tùy chọn.

### Giới hạn

- OpenCode health probe trong môi trường này trả về `OPENCODE_SERVER_UNAVAILABLE`;
  smoke model thật chưa được chạy. Đợt B bổ sung adapter live và kiểm định hành
  vi runtime của nó ở chế độ offline.
- Đây là profile phát triển đáng tin cậy cục bộ (trusted-development). Worktree
  cô lập thay đổi filesystem nhưng không phải container hay ranh giới bảo mật
  trước mã độc.
- Việc kiểm tra dùng Python runtime của backend, hỗ trợ candidate UTF-8 có chặn
  giới hạn và các kiểm tra unittest.
- Đăng ký runner chung, candidate nhị phân/lớn và cấp phát dependency vẫn là
  việc tương lai. Đợt C cung cấp editor hợp nhất, timeline operator, các control
  và tích hợp review cuối.

## Đợt C — Tích hợp operator (2026-10-10)

### Mục tiêu

Hoàn tất tích hợp sản phẩm trên gói hợp nhất `coding-agent@0.2.0`. Giai đoạn
Coding Agent đã cung cấp requirement, hợp đồng đã phê duyệt tùy chọn và spec
task-loop tùy chọn; các tùy chọn này ghép được trong cùng một lần chạy, không
cần thêm node Task Loop nào.

Đợt C thống nhất giai đoạn công khai và workflow operator, không thống nhất mọi
runtime thực thi. Biên giới runtime-neutral về sau chuẩn hóa ngữ nghĩa
iteration/candidate/checkpoint; loop sản xuất vẫn dùng OpenCode trong khi các
lần chạy chỉ requirement/contract dùng Harness (xem
[bien-gioi-runtime.md](bien-gioi-runtime.md)).

### Thiết kế: Run Detail

- Mỗi nhiệm vụ dạng loop hiển thị timeline iteration tự động. Mỗi mục ghi nhận
  session mới, candidate, candidate parent, các đường thay đổi tích lũy, kết
  quả kiểm tra đã ghi, thời lượng, token, chi phí báo cáo và lý do dừng.
- Behavioral test và các predicate hợp đồng được hỗ trợ hiển thị cùng nhau.
  So sánh dạng mock được gắn nhãn tường minh và không bịa usage của provider.
- Patch của candidate trước đó mở được từ đúng iteration của nó, qua endpoint
  artifact owner-scoped hiện có với byte đã lưu kèm checksum. Xem patch cũ
  không cấp quyền phê duyệt.
- Panel review cuối hiển thị đúng candidate và digest của nó; phê duyệt vòng
  đời vẫn khóa cho đến khi patch đã capture hiện tại đọc được. Nhận xét review
  được lưu cùng phê duyệt hoặc từ chối và vẫn hiển thị về sau.
- Các kiểm tra TRƯỢT lặp lại được nhóm theo định danh kiểm tra và iteration.
  Các phát hiện này có thể dẫn hướng cải thiện spec, tooling hay verifier
  trong một lần chạy kế nhiệm tường minh. Spec và candidate đã chấp nhận không
  bị chế độ xem operator sửa đổi.

### Controls

- **Pause**: chặn lần dispatch kế tiếp; iteration đang chạy kết thúc tại biên
  giới an toàn hiện có.
- **Resume**: tiếp tục một lần pause của người dùng bằng session mới kế tiếp.
  Không thể khởi động lại loop đã dừng hay vượt ngân sách thời gian đã biết.
- **Cancel run (hủy lần chạy)**: dùng coordinator cancellation và bảo toàn bản
  ghi iteration, kể cả phần việc chưa xong.
- **Retry iteration**: chỉ xuất hiện khi nhiệm vụ TRƯỢT đang pause có thể tiếp
  tục trong các giới hạn còn lại.
- **Recover saved result**: nhận một attempt gốc đã kiểm tra khi callback của
  nó bị mất, không cần gọi model thêm lần nào.
- Loop bị stall hoặc cạn ngân sách vẫn giữ candidate và các phát hiện cho một
  lần chạy mới. Phê duyệt hay từ chối luôn là quyết định của con người.

Giới hạn thời lượng dùng wall-clock tính từ iteration đầu tiên, kể cả thời gian
pause. Usage do provider báo cáo; chi phí theo đơn vị provider báo cáo. Đọc
timeline không bao giờ gọi provider, chạy test, tạo worktree hay giữ chỗ cho
attempt khác.

### Endpoint và state mới

Các endpoint đọc đã xác thực:

```text
GET /api/v1/adlc/runs/{run_id}/controls
GET /api/v1/adlc/runs/{run_id}/tasks/{task_run_id}/task-loop
GET /api/v1/adlc/runs/{run_id}/artifacts/{artifact_id}
```

- Quyền sở hữu lần chạy và cặp run/task được kiểm tra trước mọi lần đọc
  checkpoint hay patch.
- Phản hồi là một phép chiếu đóng, có chặn giới hạn, tối đa 100 iteration; loại
  trừ nội dung prompt, nội dung file, stdout/stderr của test, tham số thực thi,
  credential và đường dẫn host/worktree.
- Loop live và kết hợp đọc một ledger nhất quán có checksum. Một sealed
  inspection reference giữ quyền truy cập trong khi coordinator dọn request
  đang hoạt động giữa các attempt.
- Tra cứu lịch sử vẫn khả dụng sau restart với dispatch provider đã tắt, dùng
  `ADLC_TASK_LOOP_STATE_ROOT` đã cấu hình. Các lần đọc này mở database ở chế độ
  read-only và không tự tạo store còn thiếu.
- Lịch sử thiếu, hỏng hoặc không tương thích bị gắn nhãn không đầy đủ một cách
  tường minh. Một iteration đã lưu, hợp lệ, vẫn có thể hiển thị nhưng không cho
  retry iteration. Checkpoint cũ không có sealed reference có thể có lịch sử
  thiếu trong lúc pause giữa hai attempt. Lịch sử mock giữ giới hạn process-local
  của Đợt A.
- Các schema operator cộng thêm (`task-loop-operator/v0.1`) tách biệt với các
  hợp đồng thực thi đóng băng và các gói đã phát hành hiện có.

### Kiểm thử

Chạy bộ offline isolated hiện có từ `adlc-flow`:

```powershell
.\scripts\test-adlc-task-loop.ps1 -Regression
```

Kiểm tra slice C bao gồm: projection timeline, truy xuất patch cũ, restart với
provider tắt, dữ liệu hỏng, ownership, biên giới pause/resume, hủy, guard cho
loop đã dừng, recovery callback, ngân sách thời gian trôi, bằng chứng mock và
bằng chứng kết hợp hợp đồng/test. Kiểm tra frontend bao gồm navigation race,
định danh patch theo scope, lịch sử một phần, review gating, phản hồi và các
hành động operator.

Kết quả kiểm định ngày 2026-10-10: **375 test backend/compatibility** và
**73 test frontend** ĐẠT trên bộ regression và các kiểm tra operator focused.
Cả ba họ schema khớp với generator của chúng; các file backend thay đổi ĐẠT
lint và format. Type check frontend focused báo 0 lỗi trong 17 file thuộc sở
hữu; 15 lỗi dependency không liên quan còn lại ở nơi khác.

### Giới hạn

Provider reply được mô phỏng trong test; các lệnh kiểm tra Git và Python thật
vẫn chạy thật. Live model smoke vẫn chưa được xác nhận trong đợt này.

## Dòng thời gian tiếp theo

Sau ba đợt trên, hai bước chuẩn hóa tiếp theo mở rộng phần thực thi của task
loop:

- **2026-10-13** — biên giới runtime-neutral: tách các lời gọi OpenCode trực
  tiếp khỏi loop kernel qua port `TaskLoopRuntime`
  (`open_iteration`/`run_iteration`/`close_iteration`).
- **2026-10-14** — adapter Harness native proposal-only, opt-in, với lựa chọn
  runtime `HARNESS | OPENCODE` trên `coding-agent@0.3.0`.

Chi tiết đầy đủ, bảng tiêu chí và checklist nghiệm thu nằm trong
[bien-gioi-runtime.md](bien-gioi-runtime.md).

## Nguồn tổng hợp

Tài liệu này được tổng hợp từ ba file nguồn, lưu trữ trên nhánh git
`agentHarness` (xem bằng `git show agentHarness:docs/<file>`):

- `docs/task-loop-delivery-a.md` — Task loop — Delivery A (2026-10-10).
- `docs/task-loop-delivery-b.md` — Task loop — Delivery B (2026-10-10).
- `docs/task-loop-delivery-c.md` — Task loop — Delivery C: operator integration
  (2026-10-10).

# Biên giới runtime của task loop và adapter Harness

Tài liệu này hợp nhất hai bước chuẩn hóa runtime của task loop ADLC:

- **Phần 1** — *replaceable iteration runtime* (2026-10-13): tách các lời gọi
  OpenCode API trực tiếp ra khỏi loop kernel bằng port trung lập runtime
  (runtime-neutral).
- **Phần 2** — *native Harness proposal-only task loop adapter* (2026-10-14):
  đăng ký opt-in cho production và lựa chọn runtime trên `coding-agent@0.3.0`.

Phần 1 **không** di chuyển các loop sang DeepSeek Harness và không tuyên bố
rằng mọi plugin Harness đã dùng chung một runtime. Bản release cũ vẫn chạy
OpenCode; đường Harness mới có conformance offline, còn sign-off live với
SDK/provider thật vẫn đang chờ.

## Phần 1 — Replaceable iteration runtime (2026-10-13)

### Vấn đề và vị trí

Bước này loại bỏ các lời gọi OpenCode API trực tiếp ra khỏi loop kernel của
task loop. Cả loop thông thường lẫn loop hợp đồng đã phê duyệt (approved
contract) giờ cùng gọi một port `TaskLoopRuntime` duy nhất; phần hạ tầng đặc
thù của OpenCode nằm phía sau port đó. Bước này không di chuyển các loop sang
DeepSeek Harness và không tuyên bố rằng mọi plugin Harness đã dùng chung một
runtime. Các bản release cũ vẫn dùng OpenCode; đường Harness mới tại thời
điểm này mới có conformance offline, sign-off live với model/provider thật
còn chờ Phần 2.

### Triển khai

Cả loop thông thường và loop hợp đồng đã phê duyệt cùng gọi chung port
`TaskLoopRuntime`:

```text
open_iteration
run_iteration
close_iteration
```

Phân trách nhiệm sau khi tách:

- `OpenCodeTaskLoopRuntime` sở hữu các lời gọi HTTP của OpenCode, kiểm tra
  freshness/model, phát hiện compaction/tool, tổng hợp usage và giải mã
  proposal.
- `TaskLoopExecutor` trung lập sở hữu ngân sách (budget), worktree, capture
  candidate tích lũy, reservation/checkpoint SQLite, các kiểm tra độc lập và
  kết quả nhiệm vụ.
- `LiveTaskLoopExecutor` vẫn là entry point tương thích OpenCode đã phát hành;
  loop hợp đồng kế thừa từ kernel trung lập, không phải một provider loop thứ
  hai.

Một [protocol có phiên bản](../../adlc-contracts/task-loop-runtime/v0.1/README.md)
ghim adapter/model, tương quan request/session/kết quả và niêm phong (seal)
tham chiếu candidate/bằng chứng vào attempt bền vững. Hồi đáp của runtime
không có trường PASS/phê duyệt nào: runtime chỉ đề xuất việc làm, mọi phê
duyệt thuộc về ADLC. Behavioral test và contract predicate được bảo vệ vẫn
chạy trong ADLC; review thủ công, control của operator và recovery giữ nguyên
nguyên trạng.

Một adapter fixture offline độc lập cài đặt đủ cả hai mode mà không cần
OpenCode client. Nó thực thi Git/Python verification thật, iteration
TRƯỢT → ĐẠT (fail-to-pass), ép thực thi hợp đồng, thương trùng
(dedupe) và recovery khi restart. Đây là conformance, **không** phải một
adapter Harness hay một lần chạy model live thành công.

### UI và tương thích

- Run Detail hiển thị adapter/model/protocol đã checkpoint cạnh timeline.
- Binding thiếu, legacy hay đang chờ không tự bịa tạo (invent) định danh.
- Sự cố khi đọc runtime không che dấu lịch sử hiện có.
- Editor giải thích rằng các loop vẫn dùng OpenCode qua protocol trung lập;
  công việc chỉ requirement/contract giữ nguyên các profile Harness sẵn có.

Quy tắc quản trị và tương thích:

- Endpoint runtime owner-scoped mới là thụ động và không lộ nội dung (passive,
  content-free). Đọc lịch sử vẫn hoạt động khi dispatch bị tắt.
- Operator schema đóng băng, các kế hoạch đã chấp nhận, phiên bản gói, model
  pinning và Harness lock giữ nguyên.
- Bằng chứng captured/verified kiểu legacy được recovery theo policy OpenCode
  gốc mà không ghi lại prompt hay viết lại lịch sử.
- Các iteration mới có thể pin transactional adapter gốc đó trong khi vẫn bảo
  toàn attempt/kết quả cũ.
- Không thêm `.env` selector, token, model key hay fallback nào.
- Restart/rebuild backend và frontend ADLC để load thay đổi này; Harness tự
  thân không thay đổi. Test offline không cần model trả phí. Live test được
  ủy quyền riêng biệt phải giữ ràng buộc `my-codex / cx/gpt-5.6-luna` của
  người dùng; các profile cũ không bị âm thầm sửa đổi.

### Quy tắc cắm adapter

- Composition code đáng tin có thể cung cấp adapter đã đăng ký qua
  `TaskLoopExecutor(runtime=...)` hoặc `ContractTaskLoopExecutor(runtime=...)`.
- Chấp nhận chính xác một adapter hoặc một OpenCode client legacy, không nhận
  cả hai.
- Không chấp nhận import do workflow chấp ý (workflow-authored), URL, agent
  hay model tùy ý.
- Đăng ký production và ủy quyền compiler phải đi trước khi deploy; production
  ở bước này vẫn chỉ đăng ký OpenCode.
- Loop đang chạy từ chối trôi (drift) adapter/model/agent/capability; muốn
  thay thế phải cần một nhiệm vụ/lần chạy mới được phê duyệt.
- Local runner vẫn là profile phát triển đáng tin cậy (trusted-development),
  **không** phải sandbox phòng chống mã độc.

### Tiêu chí nghiệm thu adapter Harness

Adapter Harness chỉ được công nhận sau khi hội đủ các mục:

1. Đăng ký đúng adapter/profile chính xác kèm ủy quyền compiler; bảo toàn các
   kế hoạch đã phát hành và lock; tuyệt đối không fallback ngầm.
2. Mở một session Harness **mới hoàn toàn** cho **một iteration** duy nhất,
   với spec đã đóng băng (frozen), hợp đồng đã phê duyệt và candidate hiện
   tại. Không kế thừa lịch sử hội thoại hay tóm tắt nào.
3. Xác nhận (acknowledge) định danh/tính năng của command trước khi gửi
   prompt. Với contract, bắt buộc có tool restriction thật hoặc biên giới
   proposal-only tương đương đã được audit; prompt chỉ "xin" tool restriction
   là không đủ.
4. Trả về đề xuất (proposal) có giới hạn kèm usage đầy đủ của đúng
   session/model/command đã xác nhận. Success, Verify, Submit hay callback
   status của Harness đều không dùng làm bằng chứng nghiệm thu vòng lặp.
5. Capture candidate, protected check, checkpoint và cổng phê duyệt của con
   người giữ nguyên tại ADLC. Workspace từ xa cần một materializer đã được
   review hoặc một phương thức vận chuyển proposal-only.
6. Giải phóng (release) đúng session đã bind. Vượt qua các kiểm tra thương
   trùng (dedupe), interrupt, recovery captured/verified, phủ nhận
   path/contract, ngân sách và drift; sau đó mới đến smoke live được ủy quyền
   và sign-off UI.

Chỉ sau những tiêu chí trên, deployment mới được phép nói Task Loop dùng
Harness. Muốn tuyên bố "Harness hoàn toàn thống nhất" còn cần thêm bằng
chứng rằng các profile plugin khác chia sẻ đúng ngữ nghĩa thực thi/recovery
mong muốn. Riêng protocol này là chưa đủ.

### Kiểm thử (2026-10-13)

`adlc-flow/scripts/test-adlc-task-loop.ps1 -Regression` nay bao gồm
conformance runtime trung lập và tám kiểm tra additive schema parity, song
song với các test loop/coordinator/API, persistence và Harness compatibility.
Phía frontend bao gồm runtime identity, dữ liệu invalid/cross-task, outage
fallback, editor copy, timeline và Run Detail. Không dùng model thật,
callback, phê duyệt hay nguồn của người dùng nào.

Kiểm định ngày 2026-10-13:

- **413 test backend/compatibility** ĐẠT không loại trừ gì, trong đó có
  **34 test runtime-boundary**.
- **72 test frontend** ĐẠT; cả tám kiểm tra additive runtime schema, parity
  schema loop/operator/Coding Agent hiện có và production frontend build đều
  ĐẠT.
- Focused source lint/format và kiểm tra whitespace ĐẠT. Kiểm tra TypeScript
  toàn cục vẫn báo các diagnostic không liên quan sẵn có của project; không
  file runtime/timeline/editor/API/type nào bị thay đổi có diagnostic tương
  ứng.
- Assertion dọn tiến trình hậu duệ (descendant cleanup) chỉ truy vấn fixture
  con của chính nó bằng Windows process handle read-only, tránh quyền
  `tasklist` máy-wide; access denied không bao giờ được coi là thành công.
- Không model live hay iteration Harness đã deploy nào được kiểm thử.

## Phần 2 — Native Harness proposal-only task loop adapter (2026-10-14)

### Vị trí

Loop thông thường và loop hợp đồng đã phê duyệt giờ có một **adapter
iteration Harness native** opt-in. Đây là một cài đặt chồng lên cùng kernel
ADLC:

- Không phải một fallback OpenCode.
- Không phải vòng đời one-shot Harness Submit/callback sẵn có.
- Adapter đã cài đặt và được kiểm thử offline; sign-off live với SDK/provider
  thật vẫn là việc riêng.
- Các profile plugin Harness khác vẫn có ngữ nghĩa thực thi/recovery riêng.

### Hợp đồng thực thi

`coding-agent@0.3.0` thêm một lựa chọn công khai duy nhất:

```text
loop_runtime: HARNESS | OPENCODE
```

Các giai đoạn (stage) mới mặc định chọn `HARNESS`. Nâng cấp tường minh một
giai đoạn cũ sẽ giữ nguyên OpenCode loop hiện có của nó; muốn dùng Harness
phải chủ động lựa chọn, biên dịch lại và chấp nhận một kế hoạch mới. Mọi
định nghĩa 0.2.0/0.2.1 cũ, kế hoạch đã chấp nhận, plugin bundle và lock đều
không đổi.

Cả hai biến thể Harness đều dùng
`TaskLoopRuntime.open_iteration/run_iteration/close_iteration`:

1. ADLC bind các yếu tố đã phê duyệt: spec/contract, revision đã ghim,
   iteration, request và parent candidate. Snapshot hiện tại cùng các phát
   hiện kiểm tra TRƯỢT có chặn giới hạn tạo thành một prompt hoàn toàn mới.
2. `vai-adlc-task-loop@0.1.0` giữ chỗ (reserve) một UUID/digest chính xác và
   mở một agent mới hoàn toàn. Provider/model được ghim cứng vào
   `my-codex / cx/gpt-5.6-luna`. Trước khi publish, bước setup cài đặt một
   tool allowlist rỗng kèm denial guard. Lời xác nhận (acknowledgement) đến
   trước bất kỳ prompt nào.
3. Chính xác một followup native trả về một file proposal JSON có chặn giới
   hạn. Adapter bác bỏ mọi hoạt động tool, compaction, retry, provenance
   sai, usage thiếu hoặc turn thất bại.
4. ADLC validate phạm vi và nội dung tích lũy trước khi ghi vào một worktree
   dùng một lần, capture patch thật, thực thi protected unittest check và
   contract predicate, rồi niêm phong (seal) candidate/bằng chứng vào
   checkpoint bền vững sẵn có.
5. Kiểm tra TRƯỢT có thể sinh một iteration mới trong ngân sách của ADLC.
   Candidate ĐẠT vẫn chờ phê duyệt cuối của con người trong ADLC; Harness
   không thể phê duyệt, Verify, Submit hay callback loop này. Run Detail giữ
   timeline và từng patch đã capture một cách độc lập.

### Dạng proposal

Proposal có dạng:

```json
{"files":{"relative/path":"complete replacement UTF-8 text"}}
```

- File bị bỏ qua nghĩa là không thay đổi.
- Profile này chỉ hỗ trợ thêm/thay thế, không hỗ trợ xóa (deletion) hay đổi
  file-mode.
- Protected test không được chỉnh sửa.
- Loop thông thường chỉ gửi các file ghi được và đầu vào protected test đã
   đăng ký; loop hợp đồng đã phê duyệt tuân thêm phạm vi đọc (read scope) của
   hợp đồng.
- Toàn bộ cây nguồn, lịch sử provider, hội thoại trước đó và đường dẫn host
   đều vắng mặt trong proposal.

### Usage và versioning

Phiên bản iteration protocol [v0.2](../../adlc-contracts/task-loop-runtime/v0.2/README.md)
giữ nguyên protocol v0.1 đã phát hành. Event native của SDK báo cáo số token
nhưng không cung cấp chi phí tiền tệ chính thức. Vì vậy:

- v0.2 biểu diễn giá này bằng `cost:null` kèm `cost_reporting:UNAVAILABLE`,
  tuyệt không bịa ra con số 0.
- `max_total_cost` bị bác bỏ trước khi tạo session native.
- Các ngân sách iteration, context, token và thời lượng vẫn được áp đặt.
- Thiếu usage native thì chặn nghiệm thu; đó không phải bằng chứng của một
  lượt gọi model miễn phí.

Bundle digest chính xác của nhà phát hành được ghim trong gói 0.3.0, policy
adapter của ADLC và `plugins/adlc-task-loop.plugin-lock.json`. Readiness đòi
hỏi đúng bundle mới đó và bundle integrity-helper 0.3.0 nguyên vẹn. Không
bao giờ sửa méo mismatch bằng cách tắt integrity check.

### Bật cục bộ

Không có gì tự động thay đổi `.env` đang dùng, provider key hay dịch vụ đang
chạy. Trước tiên hãy dùng một **repo demo đã commit** đáng tin, có các test
Python được bảo vệ đã theo dõi. Ở phía ADLC, cấu hình:

```dotenv
ADLC_TASK_LOOP_HARNESS_ENABLED=true
ADLC_HARNESS_BASE_URL=http://127.0.0.1:3080
ADLC_HARNESS_ITERATION_API_TOKEN=<random-secret-riêng-biệt-ít-nhất-32-byte>
ADLC_TASK_LOOP_SOURCE_REPOSITORY=D:/coding/task-loop-demo/source
ADLC_TASK_LOOP_STATE_ROOT=D:/coding/task-loop-demo/state
ADLC_TASK_LOOP_WORKTREE_ROOT=D:/coding/task-loop-demo/state/worktrees
```

Sinh một secret mới cục bộ (không dán kết quả vào log/chat):

```powershell
$taskRandomBytes = [byte[]]new(32)
$taskRandom = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $taskRandom.GetBytes($taskRandomBytes) } finally { $taskRandom.Dispose() }
[Convert]::ToBase64String($taskRandomBytes)
```

Cấu hình **đúng token riêng biệt** và feature flag tương ứng cho Harness.
Credential vault sẵn có có thể cấp `ADLC_HARNESS_ITERATION_API_TOKEN`;
Compose cũng chỉ forward đúng token và flag này. Không tái dùng model key, API
token one-shot cũ, callback secret hay owner JWT. Giữ secret ra khỏi mount mà
source/model đọc được và dùng deployment vault được bảo vệ khi có profile
broad-tool khác dùng chung host. Đây là profile phát triển đáng tin cậy
(trusted-development), không phải sandbox chống mã độc hay model host đa
tenant cách ly.

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
docker compose --env-file ../../.env up -d
```

Khởi động lại backend/frontend ADLC theo quy trình sẵn có. API iteration mới
luôn nói REST protocol chuyên dụng của nó, bất kể giá trị cũ
`ADLC_HARNESS_TRANSPORT=dsh`; nó không cần callback URL/secret hay remote
source mount. Cấu hình source/project hiện có vẫn điều khiển capture và
Verify của ADLC; hãy chọn/review đúng revision ghim cục bộ.

Trong ADLC, chọn `Coding Agent · 0.3.0`, bật **Repeat until checks pass**,
chọn **Harness · file proposals** và cung cấp spec task-loop với
`max_total_cost:null`. Compile → chấp nhận kế hoạch → chạy. Trong Run Detail
lưu ý runtime/model/protocol thật và thông báo về mức giá chưa biết, rồi
soi kỹ cả protected check lẫn patch đã capture trước khi phê duyệt cuối.
Với hợp đồng đã phê duyệt, bật thêm `ADLC_CONTRACTS_ENABLED` và
`ADLC_CONTRACT_EXECUTION_ENABLED`; OpenCode không cần bật.

Không có fallback ngầm: model/scope/release/token Harness không khả dụng là
một thất bại tường minh, không phải lời mời bật OpenCode, nới lỏng allowlist
hay vượt qua Verify.

### Interrupt và recovery của operator

Intent/outcome native được ghi journal riêng dưới
`/app/data/adlc-iteration-ledger`:

- Ledger có một writer, hai slot hoạt động, 64 bản ghi có chặn giới hạn, kèm
  hủy theo deadline tự động cho từng session. Outcome đã hoàn tất sống sót
  qua restart; `GET` luôn là thụ động.
- Process dừng nhưng còn session hoạt động chưa xác nhận: trả `INTERRUPTED`,
  `released:false`. Không native resume, không recreate, không model retry
  ngầm.
- HTTP ambiguous là kết quả cuối cùng (terminal) thay vì tự động dispatch thêm
  attempt khác.
- Timeout hoặc restart khi còn session native mà usage chưa biết và chưa có
  candidate captured cũng dừng loop; hệ thống không tạo attempt mới tiêu
  ngân sách token chưa được tính. Recovery captured candidate/proof vẫn khả
  dụng mà không cần model call thêm.
- Lease single-writer được trả khi tắt sạch. Sau sự cố: dừng và xác nhận process
  cũ đã chết, lưu trữ (archive) ledger/lease, đối chiếu (reconcile) attempt
  ADLC bị ảnh hưởng rồi mới cho phép writer mới. Không có cơ chế chiếm lease
  PID cũ tự động hay xóa bằng chứng tự động.
- Journal terminal chỉ được lưu offline sau khi bảo toàn bằng chứng yêu cầu.
  Không tự tay viết lại proof cũ hay đánh dấu một native cancellation chưa rõ
  ràng là confirmed.
- ADLC recovery từ `CANDIDATE_CAPTURED` hoặc `VERIFIED` dùng đúng
  candidate/proof gốc mà không tạo prompt native mới. Thay đổi runtime,
  contract, spec hay release đã ghim đòi hỏi một kế hoạch/lần chạy kế nhiệm
  đã được chấp nhận.
- Unittest host-side chạy candidate Python: baseline/check đáng tin là bắt
  buộc, y như với loop OpenCode hiện có.

### Kiểm thử và live sign-off

```powershell
cd D:\coding\ADLC
.\adlc-flow\scripts\test-adlc-task-loop.ps1 -Regression
cd agent-harness-server\deepseek-harness
node --test plugins/vai-adlc-task-loop/tests/iteration.test.mjs
```

Cross-language Python test dùng Node handler/driver/protocol thật với một
ephemeral loopback HTTP server và native SDK giả; Git capture, protected
check, contract enforcement, phê duyệt thủ công, duplicate delivery và
recovery đều là fixture thật. Không repo người dùng nào bị sửa, không phê
duyệt thật nào được submit, không model trả phí nào được gọi.

Sign-off live yêu cầu: readiness đã xác thực trên Harness vừa
rebuilt/khởi động, đúng route `my-codex / cx/gpt-5.6-luna``,
acknowledgement/provenance/usage native zero-tool, hai iteration mới hoàn
toàn, protected check đi từ TRƯỢT sang ĐẠT, và một phê duyệt con người
tường minh trong ADLC. Container dừng hay fixture offline thành công không
phải một lần chạy model live thành công.

### Kết quả kiểm định (2026-10-14)

- **444 kiểm tra backend/compatibility** ĐẠT, gồm **31 kiểm tra cross-language
  Harness adapter**.
- **20 kiểm tra local-project** ĐẠT; **88 kiểm tra frontend** ĐẠT.
- **23 kiểm tra native plugin mới + 31 kiểm tra Harness compatibility gốc**
  ĐẠT.
- Cả hai release runtime schema và parity schema loop/operator/Coding Agent
  hiện có ĐẠT; aggregate schema native mới và publisher bundle lock khớp chính
  xác.
- Focused lint, format và tracked-change whitespace ĐẠT. TypeScript toàn cục
  vẫn báo diagnostic không liên quan sẵn có của repository (645 dòng); không
  file runtime/editor/timeline/API/type nào bị thay đổi có diagnostic tương
  ứng.
- Không có lệnh gọi model trả phí, phê duyệt con người thật, thay đổi
  provider key hay chỉnh sửa `.env` đang hoạt động nào được thực hiện.
- Production frontend build ĐẠT với cấu hình project không đổi. Lần chạy song
  song đầu tiên cạn memory Windows; lần chạy lại thành công dùng bound memory
  theo command Go/Node và concurrency (`GOMAXPROCS=2`, `GOMEMLIMIT=768MiB`,
  `GOGC=50`, Node heap `3072 MiB`) mà không đổi cài đặt build của project.
  Các warning chunk-size/Tailwind/import sẵn có vẫn còn.
- Sign-off trình duyệt thật/native provider thật vẫn đang chờ.

## Nguồn tổng hợp

Tài liệu này được tổng hợp từ hai file nguồn, lưu trữ trên nhánh git
`agentHarness` (xem bằng `git show agentHarness:docs/<file>`):

- `docs/task-loop-runtime-boundary.md` — Task Loop: replaceable iteration
  runtime (2026-10-13) → Phần 1.
- `docs/task-loop-harness-adapter.md` — Task Loop Harness adapter
  (2026-10-14) → Phần 2.

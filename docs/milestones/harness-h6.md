# Milestone H6: bằng chứng độc lập, replay đóng băng, project memory và test proposal

> Ngày: 2026-10-12 → 2026-10-13 (Asia/Saigon). Bốn đợt: H6A → H6B → H6C → H6D.
> Tài liệu lõi tiếng Việt tổng hợp từ bốn tài liệu milestone của nhánh `agentHarness`
> (xem mục Nguồn tổng hợp ở cuối; bản gốc đã được hấp thụ vào đây và gỡ khỏi `docs/`).
> Tiếp nối chuỗi H4–H5 (`harness-h4-h5.md`); phần quyền theo project
> và bốn role thuộc Milestone H7, xem `harness-h7a-team-roles.md`.
>
> ⚠️ Quy ước link: đường dẫn tương đối như `../adr/...` hay `../../adlc-contracts/...` trỏ tới file
> trong cây repo hiện tại; các tài liệu nguồn gốc tiếng Anh được lưu trữ trên nhánh `agentHarness`.

## Vị trí trong tiến trình tổng thể

H4–H5 đã làm cho artifact, contract và bằng chứng thực thi trở nên máy-đọc-được, không thể do model tự khai báo. H6 trả
lời câu hỏi tiếp theo: **ai xác nhận rằng thay đổi của agent thật sự đúng, bằng bằng chứng nào, và bằng chứng đó đứng
vững ra sao sau khi Harness offline?** Bốn đợt của H6, mỗi đợt một ranh giới schema đóng riêng trong `adlc-contracts/`:

- **H6A** — Tái lập đáng tin (trusted reproduction): owner đóng băng kế hoạch xác minh, phê duyệt đúng digest, chạy
  reproducer được bảo vệ, giữ lại evidence ĐẠT/TRƯỢT trong ADLC kể cả khi Harness đã offline. Ranh giới:
  `adlc-contracts/verification/v0.1/`.
- **H6B** — Replay đóng băng: replay HTTP-JSON thật trên target fixture chỉ loopback, suite bắt buộc bất biến, chuẩn bị
  điều kiện để nối TestForge thật về sau. Ranh giới: `adlc-contracts/verification-replay/v0.1/`.
- **H6C** — Project memory tư vấn: read-only gateway được bảo vệ, truy ngữ cảnh theo owner/project, không dùng model,
  không bao giờ là evidence. Ranh giới: `adlc-contracts/project-memory/v0.1/`.
- **H6D** — UI evidence dùng chung và test proposal proposal-only: sáu tool authoring có kiểm soát, lineage kế nhiệm bất
  biến, ảnh PNG tham chiếu không đổi được kết luận. Ranh giới: `adlc-contracts/test-extensions/v0.1/`.

Nguyên tắc xuyên suốt: báo cáo độc lập **không hồi tố** thay đổi `TaskResult` coding gốc, workflow status hay bằng chứng
H5; memory luôn là `ADVISORY_UNTRUSTED`; mọi hành động ghi cần owner đăng nhập tường minh; TestForge thật, trình duyệt
live và thực thi performance vẫn bị chặn tới khi có chứng nhận riêng. Cổng orchestration tiêu thụ evidence này là bước
tích hợp về sau.

---

## Milestone H6A — Tái lập đáng tin và evidence được lưu giữ

> Trạng thái: **✅ đã triển khai — nền tảng JSON-fixture opt-in** (2026-10-12). Chứng nhận live Remote Sandbox Kit,
> kiểm thử ứng dụng và nối orchestrator gate còn pending. Xem [ADR 0017](../adr/0017-independent-reproduction-and-evidence-foundation.md)
> và [kế hoạch tích hợp](../reference/tich-hop-vanguard-plugin.md).

### Mục tiêu

Owner có thể: đóng băng (freeze) một **kế hoạch xác minh** từ một thay đổi JSON đã được capture và chấp nhận, gắn với
một tiêu chí roadmap đã phê duyệt; phê duyệt **đúng digest** của kế hoạch đó; chạy reproducer được bảo vệ; xem đối chiếu
expected/observed; rồi Submit một báo cáo **ĐẠT hoặc TRƯỢT** như một hành động riêng biệt. Cả evidence thành công lẫn
thất bại đều còn lại trong ADLC sau khi Harness offline hoặc được dọn dẹp. Run Detail có panel **Verify** mới; Harness
có tab **Verify** read-only nhúng cùng renderer được bảo vệ bởi owner cho đúng source session — nó không nhận credential
ADLC và không có quyền phê duyệt. Tab Contracts hiện có vẫn hoạt động như trước.

Pipeline độc lập:

```text
accepted captured JSON patch + pinned base commit + approved contract reference
  → new immutable verification plan (no execution)
  → explicit owner approval of that exact digest (no execution)
  → persist execution intent → protected observer actually executes required cases
  → authenticated receipt → deterministic expected/observed comparison
  → prepared evidence preview → explicit Submit → retained ADLC report
```

### Phạm vi làm / không làm

**Làm:** kế hoạch xác minh bất biến từ candidate JSON đã capture; phê duyệt digest tường minh; thực thi qua observer
được bảo vệ; so sánh xác định (deterministic) expected/observed; evidence checksummed được lưu giữ; Submit báo cáo độc
lập trong ADLC. **Không làm:** chạy code project, cài dependency, thực thi lệnh tùy ý, deploy, replay TestForge suite,
mở port ứng dụng hay dùng memory làm evidence; không hồi tố thay đổi `TaskResult` coding gốc, trạng thái workflow, bằng
chứng H5 hay signed callback; Submit công bố báo cáo độc lập trong ADLC, không phải thành công deployment/SDK.

### Thiết kế chính

#### "ĐẠT" có nghĩa là gì — chính xác từng bit

Profile `verification-profile:json-fixture/0.1.0` xác minh **bằng nhau scalar** tại 1–16 JSON pointer trong **một file
JSON bị thay đổi**. UI khởi đầu với một predicate; API cho phép tới 16 case định danh riêng, ánh xạ tới các tiêu chí
roadmap đã phê duyệt khác nhau. Giá trị expected được con người đóng băng/phê duyệt, không do reproducer suy ra.
`unittest` Python được bảo vệ chỉ nhận thấy candidate data và định danh pointer; ADLC so sánh giá trị observed với kỳ
vọng đã đóng băng, giữ boolean `true` khác số `1`, và giữ "pointer thiếu" khác `null` tường minh.

Ví dụ tiêu chí cố định: "fixture phản hồi có `answer` bằng 42." Candidate `{"answer":42}` với kế hoạch `/answer == 42`
cho kết quả ĐẠT; cùng candidate đó, **được tái lập thực sự**, với tiêu chí đã phê duyệt `/answer == 43` cho một lần so
sánh TRƯỢT thật sự. Reproducer không nhận `42` lẫn `43` làm đáp án expected. Pointer bị thiếu là observed TRƯỢT; dữ liệu
không hỗ trợ/không phải scalar, thực thi không đầy đủ hoặc thiếu receipt cho trạng thái `NOT VERIFIED`, không phải
ĐẠT/TRƯỢT đoán mò.

Văn bản của roadmap đã phê duyệt được hiển thị nhưng **không được enforce về mặt ngữ nghĩa**; hai cờ báo cáo
`natural_language_enforced=false` và `contract_fully_verified=false` được khai báo tường minh. Con người phải ánh xạ kỳ
vọng một cách trung thực tới một tiêu chí đã định nghĩa trước; prototype này không thể chứng minh rằng một scalar nhập
tay nắm bắt toàn bộ ý nghĩa của tiêu chí đó.

#### Contracts, services và persistence

- Ranh giới schema đóng mới: [verification v0.1](../../adlc-contracts/verification/v0.1/README.md).
- Các module ADLC `verification_models`, `verification_candidate`, `verification_repository`, `verification_client` và
  các route `/api/v1/adlc` được ủy quyền cho owner.
- Hai plugin tuỳ chọn mới: `vai-adlc-sandbox-runtime@0.1.0` và `vai-adlc-verify-ui@0.1.0`. Recipe, lock và plugin
  implementation H4/H5 đã publish **giữ nguyên bytes**.
- Archive SQLite mới, mặc định `adlc-flow/data/adlc-verifications.sqlite3`: scope owner/run, 200 records / 32 MiB, kế
  hoạch đóng bất biến, thay đổi trạng thái nguyên tử, kiểm tra integrity. Đọc được phân trang; lọc theo source
  attempt/session xảy ra **trước** phân trang; restore archive không khởi động model hay thực thi nào. Tạo kế hoạch sao
  chép tường minh canonical JSON có giới hạn vào archive **mới** này cho tái lập/lưu giữ; nó không kéo dài hay hồi sinh
  patch bytes H4 — patch H4 hết hạn/không khả dụng thì không tạo được kế hoạch mới. Candidate data H6 có quota và vòng
  xoay retention thủ công riêng, tách khỏi TTL source-patch sẵn có của H4.
- Worker journal ghi **trước** khi thực thi. Tối đa 3 job đồng thời và 50 thư mục được lưu giữ; 64 KiB candidate, 128
  KiB transport receipt/evidence và timeout thực thi 1–60 giây. Download evidence xác minh digest trả về **và cả bytes
  thực tải xuống**.
- Một process worker cho mỗi thư mục dữ liệu được bảo vệ. Giữ thư mục đó và secret worker/broker độc lập không bị
  candidate và tool model thông thường tiếp cận. Hash lưu trữ phát hiện hỏng dữ liệu, không chặn quản trị viên ác ý;
  publisher/worker vẫn là bên được tin tưởng. Danh tính kế hoạch/candidate/source patch/commit/runner được lưu giữ
  **riêng biệt**: đổi source attempt hay captured artifact sẽ chặn approve/execute/submit nhắm vào kế hoạch cũ. Kế hoạch
  đã phê duyệt không có endpoint sửa (tạo kế hoạch/ID mới; evidence cũ vẫn đọc được). Các thao tác yêu cầu owner đăng
  nhập tường minh; AUTO_LOGIN/service key không thể approve, execute hay Submit; `approved_by` khai trong command bị từ
  chối, không được coi là chứng thực.

#### Route ADLC chính

Các đường dẫn dưới đây tương đối với `/api/v1/adlc`:

| Route | Ý nghĩa |
| --- | --- |
| GET `/verification-capabilities` | Tính năng, human-login và readiness của worker; không dispatch |
| GET `/runs/{run}/verification-candidates` | Thay đổi JSON đã capture thuộc sở hữu + tham chiếu đã phê duyệt |
| GET/POST `/runs/{run}/verifications` | Kế hoạch đã lưu / tạo bản nháp |
| POST `/runs/{run}/verifications/{plan}/{approve,execute,reconcile,submit}` | Các command tách biệt theo đúng digest |
| GET `/runs/{run}/verifications/{plan}/evidence` | Kế hoạch/receipt/báo cáo canonical được bảo vệ bởi owner, có checksum |
| GET `/harness-sessions/{session}/verifications` | Chiếu chính xác source attempt/session thuộc sở hữu |

Worker chỉ mở `/api/v1/adlc-harness-verify/{health,executions}` và `GET .../executions/{execution_id}`. Receipt dùng
HMAC domain-separated với **token worker riêng biệt**; không tái dùng key callback, model-provider hay contract-tool
hiện có. Chuỗi UI/JSON được escape, không phải HTML thực thi được.

#### Hành vi lỗi và restart

| Điều kiện | Kết quả |
| --- | --- |
| Tất cả case bắt buộc được tái lập và thỏa mãn đúng kỳ vọng | Đã chuẩn bị kết quả ĐẠT; chờ Submit |
| Tái lập hợp lệ đầy đủ nhưng mâu thuẫn kỳ vọng đã đóng băng | Đã chuẩn bị kết quả TRƯỢT; được lưu giữ và có thể Submit |
| Case thiếu/không có/trùng/ngoài dự kiến, lệch candidate/runner, chữ ký sai | `NOT VERIFIED`, không kết luận báo cáo |
| Timeout process con thực sự hoặc lỗi tái lập | `NOT VERIFIED`, không kết luận báo cáo |
| Mất response tạo job bên ngoài / crash trước khi có evidence hoàn chỉnh | `DISPATCH UNCERTAIN`; không tự retry/tạo lại |
| Đã có receipt hoàn chỉnh sau restart | Tiếp nhận đúng receipt đó; không chạy lại candidate/model |
| Có checkpoint observer nguyên tử nhưng chưa quan sát được OS exit gốc | Tiếp nhận evidence hoàn thành gắn sẵn với `completion_mode=durable-checkpoint`, `exit_code=null`; UI giải thích điều này |
| Journal/archive hỏng | Fail closed; không bao giờ bịa badge hay âm thầm reset evidence |
| Worker/Harness offline hoặc feature bị tắt sau khi đã lưu giữ | Báo cáo ĐẠT/TRƯỢT đã hoàn tất trong ADLC vẫn đọc/tải được |

Reconcile chỉ **đọc** execution/checkpoint đã ghi. POST Execute lặp lại không dispatch thêm job khi ADLC đã ghi intent.
Recovery không bao giờ tự Submit kết quả. Không dọn dẹp phá hủy theo kiểu đoán; archive đầy chặn ghi mới cho tới khi
operator sao lưu và chủ động xoay vòng retention. Session remote thử nghiệm yêu cầu TTL 180; việc enforce thực tế vẫn
cần được rà soát.

### Rollout và giới hạn

**Pilot cục bộ: không cần model hay Docker cho việc xác minh.** Feature mặc định **tắt**; lượt thay đổi không sửa
`.env`, key, database live, dịch vụ đang chạy, provider/model, firewall hay VPN.

1. Dùng một patch Harness đã chấp nhận từ một **local project đã pin** (tích hợp H4/local-project), thay đổi một file
   JSON nhỏ ví dụ `h6a-fixture.json`. Mount host-folder thường không có tham chiếu pin `adlc_local_project` thì không đủ
   điều kiện; cần một roadmap đã phê duyệt có acceptance criterion nối tới run/source task.
2. Đăng nhập ADLC tường minh với `LANGFLOW_AUTO_LOGIN=false`; không đặt user/role giả trong blueprint hay cấu hình UI.
3. Tự sinh token worker ngẫu nhiên độc lập (≥32 bytes). Giữ bí mật; đặt cùng một giá trị trong môi trường backend ADLC
   và môi trường worker.
4. Với process backend ADLC, đặt/restart với:

```dotenv
ADLC_VERIFICATION_ENABLED=true
ADLC_VERIFICATION_WORKER_URL=http://127.0.0.1:3081/api/v1/adlc-harness-verify
ADLC_VERIFICATION_WORKER_TOKEN=<your-independent-random-token>
```

5. Trong một terminal PowerShell riêng, khởi động worker JSON-only tuỳ chọn. Worker cố tình **không đọc `.env`**; tự
   nhập các giá trị môi trường trong terminal đó:

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
$env:ADLC_VERIFICATION_ENABLED='true'
$env:ADLC_VERIFICATION_PROVIDER='local-fixture'
$env:ADLC_VERIFICATION_WORKER_TOKEN='<same-independent-token>'
$env:ADLC_VERIFICATION_PYTHON='D:\coding\ADLC\adlc-flow\.venv\Scripts\python.exe'
node scripts\run-h6a-fixture-worker.mjs
```

Script chỉ bind **127.0.0.1:3081**; probe runner cố định và Python ≥3.10 trước khi start, không in credential, lưu job
trong `%LOCALAPPDATA%/ADLC/verification-worker` ngoài các mount project/Docker; override bên trong repository/source
root bị từ chối. Giữ archive backend và secret ngoài các source mount model có thể đọc. Adapter local-fixture chỉ chạy
publisher code trên JSON; nó **không phải security sandbox** cho kiểm thử ứng dụng tùy ý. Nếu ADLC chạy trong Docker,
không expose listener này ra public chỉ để gọi được: chọn một deployment private đã được rà soát trước khi bật.

6. Restart frontend/backend. Trong Run Detail → Verify: xác nhận "protected local fixture subprocess", rồi Create plan →
   chọn captured JSON/tiêu chí đã phê duyệt → pointer `/answer` → expected `42` → Save draft → soát đúng tham chiếu →
   Approve → Run → xem đối chiếu → Submit; dùng một **kế hoạch mới** với expected `43` để chứng minh TRƯỢT thật trên
   cùng candidate — cả hai kiểm tra không cần model.
7. Tab Verify native của Harness đến từ các dòng plugin được bổ sung; refresh/restart Harness để nạp. Nó dùng
   `ADLC_CONTRACT_UI_URL` public hiện có (mặc định localhost:3000); nếu iframe chặn auth, tự đăng nhập qua ADLC. Worker
   standalone không cần bật execution adapter trong container vì backend URL trỏ port 3081.

Compose **không** chuyển credential ký/broker của worker sang container model. Adapter Harness thử nghiệm có opt-in
riêng `ADLC_VERIFICATION_HARNESS_ENABLED/PROVIDER`, chỉ nhận credential từ publisher vault được bảo vệ và từ chối
provider local-fixture trong container model dùng chung; chỉ bật cờ backend/pilot không thể bật xác minh trong container
hay lộ signing key. Dòng plugin model-host thường cũng thiếu `publisherIsolation`, execution endpoint của nó vẫn đóng;
xuất bản remote phải dùng một instance execution-plane được bảo vệ riêng, không khai
`publisherIsolation=separate-execution-plane` trên Harness dùng chung để né guard này. Chỉ khi sau này cần một lần chạy
coding live mới cho source candidate, dùng provider/model đã phê duyệt **`my-codex / cx/gpt-5.6-luna`**; các bước kiểm
tra H6A không gọi nó chút nào.

**Remote Sandbox Kit — đã có implementation, rollout live bị chặn.** Rà soát read-only `/openapi.json` của broker được
cung cấp thấy các route Management create, detail và Agent execute/read/write dạng generic, nhưng schema response thành
công không định kiểu, không có security scheme được tài liệu hóa và không có contract idempotency/reconciliation kết quả
thực thi — chưa đủ để chứng nhận tenant isolation, image identity đáng tin hay thực thi gián đoạn an toàn. Adapter yêu
cầu **credential broker scoped riêng**, image đã pin, session ID trả về chính xác và image attestation, evidence có giới
hạn, scratch path run-scoped cố định và thực thi hoàn thành thực sự; không gửi lệnh do model sinh ra. Kết quả create
chưa rõ vẫn uncertain; restart không bao giờ phát create hay shell execution khác. Không bật trên URL broker plaintext
public. Kích hoạt/sign-off remote cần: source/revision backend, routing tenant/owner có xác thực, workspace dùng một lần
và giới hạn network/host-mount, image attestation thật, đọc job/result có cấu trúc và giới hạn, retention/cleanup
scoped. H6B sau đó bổ sung replay TestForge đóng băng và candidate target đáng tin trước khi nối một orchestrator gate
bắt buộc; memory giữ mức tư vấn ở slice riêng về sau. **Không có job remote nào được gửi** trong lượt triển khai này.

### Kiểm chứng

Chạy từ `adlc-flow` (mọi thư mục test, credential và process thuộc sở hữu của test):

```powershell
$env:PYTHONPATH='D:\coding\ADLC\adlc-flow'
$env:ADLC_VERIFICATION_DB_PATH=''
$env:ADLC_VERIFICATION_WORKER_URL=''
$env:ADLC_VERIFICATION_WORKER_TOKEN=''
.\.venv\Scripts\python.exe -m pytest tests/unit/adlc/test_verification.py tests/unit/api/v1/test_adlc_verification.py -q
.\.venv\Scripts\python.exe scripts/generate_adlc_verification_schemas.py --check
```

Từ `deepseek-harness`:

```powershell
$env:ADLC_H6A_TEST_PYTHON='D:\coding\ADLC\adlc-flow\.venv\Scripts\python.exe'
node --test plugins/vai-adlc-sandbox-runtime/tests/*.test.mjs plugins/vai-adlc-verify-ui/tests/*.test.mjs
```

Từ `adlc-flow/frontend`:

```powershell
node node_modules/jest/bin/jest.js src/components/adlc/VerificationPanel/index.test.tsx src/controllers/API/verification.test.ts src/pages/RunDetailPage/index.test.tsx --runInBand
node node_modules/vite/bin/vite.js build
node node_modules/vite/bin/vite.js --config tests/verification-viewer-preview/vite.config.mjs
```

Preview offline: `http://127.0.0.1:4178/tests/verification-viewer-preview/index.html` — dùng đúng component dùng chung
và client native nhưng với **fixture records minh họa**, tự intercept API, không bao giờ thực hiện phê duyệt/model call
thật; banner ghi rõ điều đó. Query `?mode=draft` kích hoạt các control riêng; `?host=harness` hiện pane native read-only
hẹp; `?theme=light` đổi theme sáng. Phạm vi xác minh gồm: HTTP Node thật → subprocess Python được bảo vệ → receipt có
xác thực → bộ so sánh xác định ADLC → archive SQLite cho cả ĐẠT/TRƯỢT; tái dựng Git source thật đã pin; từ chối
owner/session và stale attempt; timeout, evidence thiếu/zero, mất dispatch, recovery checkpoint, download checksum và
biên hành động UI dùng chung. Test API candidate-freezer dùng fixture seam; tái dựng Git chạy riêng trên Git repo
test-owned thật. Không dùng model trả phí, remote sandbox, project/database production hay phê duyệt người thật.

Kết quả (2026-10-12): **42** backend check H6A, **27** worker/native-plugin check mới, **7** schema khớp runtime model
và **79** test component/Run Detail/evidence-download ĐẠT; frontend production build đạt; regression node rộng hơn đạt
95 check. Backend regression không lọc đạt **703** với hai thất bại ngoài H6A (`tasklist` bị **Access denied** trong
test inventory child-process Windows sẵn có; test đăng ký route sẵn có giả định mọi dòng router FastAPI có `.methods`
trong khi môi trường này trả `_IncludedRouter`). Với hai test legacy đó được loại trừ tường minh, rerun rộng hơn đạt
**707** check (2 loại trừ); thêm 28 regression API Harness-result/H5 ĐẠT. Ruff/Biome scoped đạt. TypeScript toàn repo
còn 283 diagnostic, không cái nào nằm trong các path H6A đã sửa.

### Trạng thái

✅ **Đã triển khai** (nền tảng JSON-fixture, opt-in). Chưa có: chứng nhận live Remote Sandbox Kit, kiểm thử ứng dụng
thật, nối orchestrator gate.

---

## Milestone H6B — Replay đóng băng và readiness TestForge

> Trạng thái: **✅ pilot fixture HTTP-JSON đóng băng cục bộ đã triển khai; tích hợp TestForge thật bị chặn**.
> Triển khai/xác thực 2026-10-12–13 (Asia/Saigon); rà soát upstream 2026-10-12. Xem
> [ADR 0018](../adr/0018-frozen-http-replay-and-testforge-readiness.md).

### Mục tiêu

Trên nền H6A, đợt này bổ sung **replay HTTP thật**, suite bắt buộc bất biến, đối chiếu evidence chính xác và lịch sử UI.
Nó **không** chạy ứng dụng của project và không tuyên bố client TestForge được cung cấp chính là backend của nó. Kế
hoạch tích hợp staging/browser còn lại được giữ tường minh trong [kế hoạch tích
hợp](../reference/tich-hop-vanguard-plugin.md).

Đối chiếu repository được cung cấp: nhánh master Gitea đã được kiểm tra read-only và vẫn trỏ tới
`8c892b2491bc6f8be0f2b439fe782707b7ad169a`, đúng revision source đã tải. Cây đệ quy chứa
`deepseek-harness/plugins/vai-testforce/{lib,skills,package.json}`; skill/client của nó mô tả một Windows FastAPI broker
riêng tại `http://10.0.10.195:9099` cùng các script như `replay_spec.py` / `run_staging.py`, nhưng các implementation
broker/runner đó **không nằm trong repository đó**. OpenAPI đọc từ workstation này bị timeout: khả năng truy cập chưa
xác nhận, không kết luận dịch vụ chết. Interface legacy nhận broker-host path cho `session`, `profile`, `suite`, tham
chiếu mật khẩu account và cleanup template; client retry POST, đi theo redirect và trả trạng thái job/log tail mà không
có sổ cái assertion/evidence hoàn thành có kiểu. Không có upload/materialization đã review, artifact fetch có xác thực,
idempotency lookup hay cancellation contract nào được cung cấp. Chưa gửi job nào, chưa cài raw plugin, chưa đọc secret,
chưa đổi provider/model, chưa đổi VPN/firewall hay mở port public.

### `localhost` là tương đối theo góc nhìn của caller

| Caller / dịch vụ | Diễn giải đúng trong môi trường phát triển |
| --- | --- |
| Backend ADLC và worker H6B cùng trên Windows host | ADLC gọi `http://127.0.0.1:3082/api/v1/adlc-harness-replay`; worker chỉ bind loopback. Pilot này không cần Docker. |
| Browser / pane Verify của Harness | Nó tải trang frontend ADLC được bảo vệ bởi owner. Native plugin không có worker key hay approval proxy. Cùng một `ReplayPanel` render cả hai mặt. |
| Harness trong Docker | `localhost` nghĩa là container đó, không phải máy Windows. H6B cố tình **không** được cài ở đó làm publisher ký; không chuyển secret vào container chứa model. |
| Broker TestForge `10.0.10.195:9099` của mentor | Địa chỉ remote private, không phải localhost của máy này. Cần backend source/deployment và route mạng có ủy quyền trước khi tích hợp. Không đoán port mapping public hay tắt control bảo mật. |

Trỏ `ADLC_REPLAY_WORKER_URL` vào dịch vụ legacy `/api/v1/replay` **không phải** là tích hợp. H6B v0.1 chỉ chấp nhận
worker được bảo vệ cục bộ nói contract đóng mới. TestForge thật cần một bộ capability adapter/backend đã review cùng
provider/profile đăng ký riêng.

### Thiết kế chính

- Profile mới: `verification-profile:http-json-replay/0.1.0`; runner mới: `runner:adlc-http-json-replay/0.1.0`, pin
  SHA-256 `b181341587bdc60dde4be167d9504af960927cb173046cd26886bd27ae250803`; package execution-plane mới:
  `vai-adlc-replay-runtime@0.1.0` (chỉ CLI được bảo vệ riêng); [bảy schema
  đóng](../../adlc-contracts/verification-replay/v0.1/README.md) khớp runtime.

Vòng đời:

```text
Owned captured pinned JSON candidate + approved contract reference
  -> frozen draft suite (1–16 required cases, immutable expected values/config)
  -> explicit owner approves exact plan digest
  -> durable execution intent
  -> protected disposable authenticated loopback JSON target
  -> real GET /fixture requests + unittest assertions + JUnit
  -> validate bindings, coverage, scalar types and all evidence in ADLC
  -> READY_FOR_SUBMISSION preview (PASS or genuine FAIL)
  -> owner Submit -> independent retained replay report
```

Target chỉ nhận **candidate bytes**, không nhận giá trị expected. Test runner nhận suite đã phê duyệt và kiểm tra HTTP
status cùng bằng nhau scalar theo JSON pointer. Nó ghi danh tính instance và digest response/candidate cho từng case.
Credential fixture ngẫu nhiên theo process nằm trong memory và không bao giờ được trả về UI/log/evidence. Chỉ
process/socket thuộc sở hữu được dọn; không có template DELETE hay account production. Runner có giới hạn thời gian sống
riêng, song song với timeout của publisher. File candidate là **data**, không bao giờ được import/thực thi.

Case ánh xạ tới tham chiếu contract node/index chính xác. Con người phải bảo đảm assertion nhập tay đại diện đúng tiêu
chí trước khi phê duyệt. Tuân thủ ngôn ngữ tự nhiên không được suy ra: `natural_language_enforced=false`,
`contract_fully_verified=false`, `application_verified=false`. Không chấp nhận healing, required skips, lệnh/URL tùy ý,
model call, stress/load, code checkout hay browser automation. Suite/oracle đổi thì cần bản nháp mới và phê duyệt mới.
**Khi nào có kết luận nhị phân:** cần receipt hoàn thành có xác thực cộng JUnit an toàn chính xác; case
zero/thiếu/thừa/trùng/skip, lỗi, sai runner/target/suite/config, XML entity, candidate thay đổi hay evidence thiếu đều
chặn kết luận. Lỗi assertion hoàn thành thật sự được giữ là TRƯỢT; lỗi transport/timeout là `NOT_VERIFIED` hoặc
uncertain, không bao giờ ĐẠT.

**Huỷ là một trạng thái riêng:** lưu `CANCEL_REQUESTED` **trước** khi liên hệ worker. Chỉ xác nhận có xác thực, gắn đúng
process con, xác nhận exit của nó mới chuyển thành `CANCELLED`. Suite đã phê duyệt nhưng chưa dispatch có thể huỷ ngay.
Publisher restart mà không có process ownership thì không bao giờ kill PID lưu/unproven hay giả vờ orphan đã dừng;
checkpoint hoàn thành đã lưu vẫn có thể được tiếp nhận với `exit_code=null`, và evidence hoàn thành thắng race huỷ muộn.
Không polling/đọc/restart nào tạo thêm job; yêu cầu thực thi trùng bị từ chối sau khi intent đã ghi; worker ID trùng trả
lại intent/kết quả gốc; mất POST response là uncertain, không phải quyền retry. Huỷ/quan sát lần thử coding cũ hơn được
phép cho mục đích dọn dẹp/lịch sử; approval, thực thi và Submit yêu cầu source hiện tại còn "tươi"; truy cập chéo
owner/chéo session vẫn bị từ chối. Submit lưu giữ record độc lập này: không viết lại `TaskResult` coding, không gửi
callback legacy khác, không mở quality gate workflow, không deploy, commit hay push gì cả. Ghép node TESTING/quality
gate của workflow vẫn là pilot H6E về sau.

#### Storage, endpoints và UI

- Archive mới mặc định: `adlc-flow/data/adlc-replays.sqlite3`, bảng `adlc_verification_replays`; H6A giữ nguyên
  table/database, schema và runner bytes của mình. Quota retention replay mặc định 200 records / 32 MiB; đợt này **không
  có** purge evidence tự động. Giới hạn candidate 64 KiB, JUnit 32 KiB, evidence JSON chấp nhận 256 KiB — evidence quá
  cỡ chặn việc nhận, không âm thầm cắt assertion. Admission worker: 3 job active và 50 thư mục job đã lưu có giới hạn;
  journal private được checksum và ghi nguyên tử.
- Read API: `/api/v1/adlc/replay-capabilities`, `/runs/{run_id}/replays`,
  `/harness-sessions/{source_session_id}/replays`. Đọc run/session theo scope owner và có phân trang; mở record đang
  active chỉ quan sát evidence sẵn có (batch tối đa 3).
- Hành động owner: `POST /runs/{run_id}/replays` và
  `/runs/{run_id}/replays/{plan_id}/{approve|execute|reconcile|cancel|submit}` với đúng digest.
- Download có xác thực đã lưu giữ: `/runs/{run_id}/replays/{plan_id}/evidence/{json|junit}`. Browser kiểm tra SHA của
  bytes thực trước khi tải; không bao giờ fetch URL artifact tùy ý hay thực thi HTML/XML của runner.
- `ReplayPanel` hiển thị đúng suite/candidate/config, giá trị expected so observed, coverage bắt buộc, instance đã đóng,
  XML preview, độ chắc chắn của huỷ và Submit thủ công; projection unknown/không đầy đủ fallback về raw text đã escape,
  không kết luận và không hành động.
- Tab Verify native hiện có của Harness nhúng `/contracts/harness/<source-session>/?view=verification`; ADLC render H6A
  + H6B ở đó ở chế độ read-only, mọi thay đổi của con người vẫn trong ADLC đã đăng nhập tường minh.
- `testforge_ready=false` cùng một blocker remote-readiness hiển thị là **cố ý**, kể cả khi pilot cục bộ đã sẵn sàng.
  Patch/compose Harness chính và plugin lock cũ không bị H6B thay đổi.

### Rollout và giới hạn

Giữ credential worker, publisher code đã cài và journal private ngoài tầm với của agent và candidate source mount; không
đặt key của nó vào `.env` trong repository mà agent đọc được; dùng cấu hình backend private nếu chính ADLC là candidate
source. Lượt này **không** thêm secret hay kích hoạt feature thật vào `.env`. Backend ADLC — cấu hình riêng tư rồi
restart:

```dotenv
ADLC_REPLAY_ENABLED=true
ADLC_REPLAY_WORKER_URL=http://127.0.0.1:3082/api/v1/adlc-harness-replay
ADLC_REPLAY_WORKER_TOKEN=<separate-random-key-at-least-32-bytes>
```

Bắt buộc owner đăng nhập tường minh (`LANGFLOW_AUTO_LOGIN=false`); auto-login/service/provider key không thể phê duyệt
hay chạy suite. Cấu hình H4/H5/H6A hiện có giữ độc lập; build/restart frontend bình thường để thấy panel mới trong Run
Detail. Terminal PowerShell được bảo vệ riêng với **cùng key worker chuyên dụng**:

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
$env:ADLC_REPLAY_ENABLED='true'
$env:ADLC_REPLAY_PROVIDER='local-http-fixture'
$env:ADLC_REPLAY_WORKER_TOKEN='<same-dedicated-worker-key>'
$env:ADLC_REPLAY_PYTHON='D:\coding\ADLC\adlc-flow\.venv\Scripts\python.exe'
node scripts\run-h6b-replay-worker.mjs
```

Worker không nạp `.env`. Journal mặc định `%LOCALAPPDATA%/ADLC/replay-worker`, ngoài cây source;
`ADLC_REPLAY_WORKER_DATA_DIR` (tuỳ chọn) cũng phải ngoài mọi mount repository/candidate/model — kiểm tra real-path chặn
thư mục source và symlink alias. Một publisher cho mỗi thư mục private; nếu 3082 bị chiếm, đặt `ADLC_REPLAY_PORT` và URL
backend tương ứng. Publisher từ chối kích hoạt plugin trong container dùng chung; key của nó không phải provider key
OpenCode/9router, không phải Harness API key hay JWT người. Pilot thật đầu tiên: dùng local project đã pin thuộc sở hữu
owner, có lần chạy coding hoàn thành với thay đổi `fixture.json` đã capture (ví dụ `{"answer":42}`) và một tiêu chí đã
phê duyệt nói rõ phản hồi mong đợi. Trong Run Detail:

1. Tạo frozen replay suite; chọn candidate JSON đã capture và contract đã phê duyệt chính xác.
2. Thêm case bắt buộc; ánh xạ mỗi tiêu chí duy nhất, pointer, expected JSON scalar và HTTP status.
3. Save draft; soát suite/candidate/config đã đóng băng và raw JSON.
4. Tick ô review → Approve đúng replay suite → Run approved replay.
5. Soát coverage đầy đủ, giá trị phản hồi, target đã đóng và JUnit; Submit tường minh.
6. Để chứng minh TRƯỢT thật, tạo/phê duyệt suite kế nhiệm kỳ vọng scalar/status khác — **không** sửa suite đã phê duyệt;
   cancel không phải một kết luận thất bại.

Lịch sử source-patch vẫn phải khả dụng khi đóng băng candidate mới; patch chỉ-Markdown hay mount host tùy ý không đủ
điều kiện cho profile này. Báo cáo đã đóng băng từ trước **không** cần worker/session live hay tải source-patch live để
hiển thị.

### Cần gì để bật TestForge thật

Xin mentor/operator **repository broker/backend TestForge** (không chỉ plugin này) hoặc một deployment pin cùng tài liệu
API tiếp cận được; xin suite/session/profile, schema result/JUnit/ artifact và revision runner. Sau đó review/triển khai
upload/materialization có xác thực và giới hạn, thực thi no-heal/no-model, readiness target candidate hiện tại, test
account scoped, cleanup an toàn, reconciliation operation-key và huỷ có xác nhận; đóng băng recipe/environment và attest
artifact thật trước khi bật provider opt-in mới. Phát triển localhost là chấp nhận được; không cần deployment public.
Phần implementation/contract còn thiếu không thể bù bằng provider API key hay chỉ đổi broker URL. Ràng buộc `my-codex /
cx/gpt-5.6-luna` vẫn áp dụng cho mọi route exploration/healing backed by model trong tương lai; các route đó vẫn tắt ở
đây.

### Disable / rollback

Huỷ và quan sát job active trước. Đặt `ADLC_REPLAY_ENABLED=false` cho ADLC và chỉ dừng worker được bảo vệ mới. Không đổi
lock H4/H5/H6A cũ, không reset lần chạy coding, không xóa evidence đã lưu hay undo chỉnh sửa project của người dùng.
Archive đã lưu vẫn đọc được bởi owner khi feature tắt. Restart không chắc chắn: quan sát/tiếp nhận checkpoint gốc; không
bao giờ lặp lại create hay kill PID unproven chỉ để xóa badge. Job mới cần suite/intent tường minh mới.

### Kiểm chứng

- **78** test backend H6A/H6B: ngữ nghĩa scalar cố định (bool ≠ number), đúng suite/target/config, no-model/heal, JUnit
  an toàn với coverage bắt buộc, owner/source-session/freshness, huỷ, idempotence, retention qua restart và đường API
  thật → Node → Python → HTTP fixture → evidence ADLC.
- **42** test worker/native được bảo vệ (15 mới H6B): ĐẠT/TRƯỢT thật và nhiều HTTP case, socket đóng, timeout, huỷ
  process con thuộc sở hữu, không kill PID lưu, create mơ hồ, recovery chỉ-checkpoint, token yếu/thiếu, body giới hạn và
  từ chối CLI được bảo vệ/container dùng chung.
- **65** test UI/controller/Run Detail dùng chung (19 mới H6B): hành động tách biệt, readonly source scope, evidence
  zero/không nhất quán không thể hiển thị ĐẠT, XML escaped, download checksum, sửa draft nhiều case; UI QA đã phát hiện
  và sửa lỗi render tiêu chí có cấu trúc và scope iframe offline.
- **41** test regression lân cận H5 ĐẠT; cả hai bộ bảy schema export khớp runtime model; Ruff/Biome scoped đạt; frontend
  production build đạt (cảnh báo bundle-size/dynamic-import hiện có còn lại). TypeScript toàn repo vẫn có diagnostic
  ngoài path H6B; không còn diagnostic nào trên path H6B sau bản sửa draft criterion — không phải tuyên bố typecheck
  sạch toàn cục.
- Preview evidence ADLC offline và chiếu Harness native đã được kiểm tra thị giác, gồm JUnit đã lưu và pane read-only
  hẹp không có nút mutation — đây là UI QA, không phải chứng nhận auth/framing Harness thật hay TestForge staging.

Preview offline (fixture minh họa, **không** phải xác minh thật hay phê duyệt ADLC):

```powershell
cd D:\coding\ADLC\adlc-flow\frontend
node node_modules\vite\bin\vite.js --config tests\verification-viewer-preview\vite.config.mjs
```

- Evidence ADLC: `http://127.0.0.1:4178/tests/verification-viewer-preview/index.html?slice=h6b&theme=light`; demo
  approve/run: `...?slice=h6b&mode=draft&theme=light`; chiếu native Harness: `...?slice=h6b&host=harness&theme=light`.

Preview dùng đúng panel dùng chung và client native, tự intercept API, không nạp `.env` ứng dụng, không kiểm tra
JWT/SameSite/framing thật hay Harness live.

### Trạng thái

✅ **Pilot fixture HTTP-JSON cục bộ đã triển khai; tích hợp TestForge thật bị chặn** tới khi có backend/contract đã
review và provider/profile đăng ký riêng.

---

## Milestone H6C — Project memory tư vấn theo project

> Trạng thái: **✅ read-only adapter, context được lưu giữ, UI dùng chung và curated gateway cục bộ đã triển khai;
> chứng nhận live Cognee còn pending**. Triển khai/xác thực 2026-10-13 (Asia/Saigon). Xem
> [ADR 0019](../adr/0019-advisory-project-memory-and-protected-readonly-gateway.md).

### Mục tiêu

Cho phép run/agent đọc ngữ cảnh tư vấn của project qua một **read-only gateway** được bảo vệ, với danh tính nguồn có cấu
trúc, mà không biến memory thành authority hay evidence. Ranh giới schema: profile
`memory-profile:project-context/0.1.0`, gateway contract `gateway:adlc-memory-readonly/0.1.0` và [mười schema
máy-đọc-được](../../adlc-contracts/project-memory/v0.1/README.md).

### Phạm vi làm / không làm

**Làm:** scope suy từ owner đã xác thực của lần chạy và local project/commit được compiler pin; sổ đăng ký credential
backend-only; MCP adapter Streamable HTTP; archive context riêng biệt; UI dùng chung; ba agent tool tuỳ chọn; curated
gateway cục bộ có bảo vệ. **Không làm:** `memory_ask`, `remember`/tự cải thiện, upload, ingestion sau chấp nhận/outbox
và `forget`/deletion; không model, không embedding, không GraphRAG, không remote fetch, không shell, không ingest, không
xóa. Do đó không tuyên bố acceptance duplicate/retry/deletion cho ingestion; ràng buộc `my-codex / cx/gpt-5.6-luna` được
tôn trọng bằng cách **gọi đúng không model nào**.

### Thiết kế chính

- ADLC suy scope từ owner đã xác thực của lần chạy và local project/commit được compiler pin. **Không** có
  tenant/dataset/URL/file path/boolean quyền do caller khai. Context project legacy/chưa pin/mơ hồ bị từ chối.
- Sổ đăng ký credential backend-only với binding owner/project duy nhất và credential read-only phân biệt. Bắt buộc
  HTTPS trừ loopback host thật; không default upstream, không fallback về `opencode@local`.
- MCP adapter Streamable HTTP: initialize có xác thực, đàm phán protocol được hỗ trợ (`2025-03-26`, `2025-06-18`,
  `2025-11-25`), bắt buộc initialized notification/schema discovery, initialize-trước-scope, một lần reconnect
  read-only, serialized first-call/concurrency, session scoped, tách xoay credential, response JSON/SSE giới hạn và từ
  chối yêu cầu sampling của server.
- Định danh tài liệu/chunk nguồn có cấu trúc: revision, trích dẫn gốc, digest, ngày có timezone. Digest văn bản chunk
  được kiểm tra cục bộ; provenance tài liệu vẫn do backend khai (`source_provenance_verified=false`). Output Cognee dạng
  flattened thuần không hỗ trợ bị từ chối, không được trình bày như trích dẫn đã xác minh.
- Archive context SQLite riêng, durable read intent và replay command chính xác. Key lặp lại đã hoàn thành trả cùng
  snapshot mà không đọc lại; key thất bại/gián đoạn **không** tự retry, hỏi lại chủ đích với key mới. Archive hỏng và
  quota fail closed.
- UI dùng chung: panel Memory trong Run Detail và tab Memory native của Harness, hiển thị scope, provenance nguồn, raw
  JSON đã lưu, nhãn stale/expired/unknown-context; hành động query/kết nối tường minh **chỉ** trong ADLC đã đăng nhập.
  View/Refresh thụ động chỉ đọc archive, không tự query Cognee. Harness là read-only.
- Ba agent tool tuỳ chọn: `adlc_memory_context`, `adlc_memory_status`, `adlc_memory_health`. HMAC purpose/key riêng;
  danh tính từ execution context; kernel ADLC kiểm tra đúng request/attempt/session đang active — attempt terminal/stale
  không query được. View native giữ lịch sử đúng-session; các lần đọc run-shared của người vẫn hiển thị khi cùng project
  pin còn thiết lập được; đọc agent-only của session khác không bị trộn vào.
- Curated gateway cục bộ được bảo vệ `local-curated:0.1.0`: đọc MCP loopback có xác thực thật và tìm kiếm lexical trên
  các chunk do operator tuyển chọn, bất biến. Không model, không embedding, không Cognee, không GraphRAG, không remote
  fetch, không shell, không ingestion, không deletion.

Kiến trúc:

```text
Explicit ADLC owner query / optional signed current Harness tool
  -> coordinator-owned run + compiler-pinned project
  -> server-derived tenant/dataset -> reviewed per-scope credential
  -> authenticated initialize -> initialized -> required scope schemas
  -> raw CHUNKS/status only -> scoped structured provenance
  -> checksum-validated advisory archive -> shared protected renderer

Approved contract / expected values / Verify evidence / original TaskResult
  remain separate and unchanged throughout.
```

Memory là `ADVISORY_UNTRUSTED`, không bao giờ là chỉ thị hay authority; `verification_evidence=false`,
`models_used=false`. Connectivity check thành công không chứng nhận isolation, độ chính xác nguồn hay tính đúng của ứng
dụng. Cả chiếu capability live lẫn hướng dẫn đều giữ `live_certified=false` cho tới một sign-off được review riêng. Giới
hạn: 200 intent toàn cục / 16 MiB nội dung lưu giữ, 128 KiB mỗi record, 10 chunk, 8.192 ký tự mỗi chunk, query 2.000 ký
tự, 100 lần đọc mỗi trang; không GC tự động, không đọc chéo owner.

### Rollout: pilot cục bộ không cần model

Không cần provider API key mới, VPN, Docker broker hay thay đổi firewall. Backend ADLC và gateway riêng chạy trên cùng
Windows host. Không đặt gateway credential vào Harness, blueprint đã phê duyệt, file commit hay candidate mount.

1. Đăng nhập owner ADLC (`LANGFLOW_AUTO_LOGIN=false`). Dùng một lần chạy execution-plan gắn với **local project**; task
   phải có context project được compiler pin. Flow legacy hay task chưa start không có request là chưa đủ. Panel Memory
   hiển thị `project_id/base_commit`. ID owner đăng nhập là trường `id` từ `GET /api/v1/users/whoami` có xác thực (dùng
   session owner sẵn có của browser; không dán token vào script hay Harness).
2. Tạo thư mục host private ngoài `D:/coding/ADLC`, ngoài mọi coding source, project snapshot và mount Docker/model, ví
   dụ `C:/private-adlc-memory`. Hạn chế quyền Windows cho operator backend/gateway. Đây là cấu hình thuộc sở hữu
   operator, không phải artifact do agent viết.
3. Sinh **token gateway read-only ngẫu nhiên mới** (≥32 bytes). Đây không phải key OpenCode, Codex, 9router hay provider
   model. Dùng token khác cho mỗi owner/project.
4. Lưu `curated-memory.json` trong thư mục private với cấu trúc sau, thay bằng owner/project ID thật và token đã sinh.
   Danh sách document rỗng là hợp lệ và trả về không-context, không phải kiến thức bịa ra:

```json
{
  "schema_version": "0.1",
  "bindings": [{
    "owner_id": "<signed-in ADLC owner UUID>",
    "project_id": "<pinned ADLC project UUID>",
    "token": "<independent random read-only gateway token>",
    "documents": []
  }]
}
```

Để cung cấp context, thủ công thêm các object `MemoryChunk` khớp `memory-chunk.schema.json`: chunk/document ID,
revision, trích dẫn (`adlc:`, `urn:` hay HTTPS không credential, không query/fragment), SHA-256 tài liệu gốc, văn bản,
SHA-256 của đúng văn bản UTF-8 đó, ngày ghi/hết hạn có timezone, và commit Git nguồn hoặc `null`. Không bịa provenance
từ bản tóm tắt của agent. Khi không biết commit nguồn, UI ghi rõ "độ tươi không xác định". Gateway từ chối digest văn
bản sai, chunk trùng hay ngày provenance ở tương lai. Giữ seed dưới 1 MiB, 32 scope và 100 chunk mỗi scope. Seed **đóng
băng lúc khởi động**; sửa của operator cần cập nhật seed có review và restart gateway, không phải lệnh agent
`remember`/`forget`.

5. Trong terminal được bảo vệ riêng, khởi động gateway (CLI cố tình **không** nạp `.env` và chỉ bind `127.0.0.1`):

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
$env:ADLC_MEMORY_LOCAL_CONFIG='C:/private-adlc-memory/curated-memory.json'
node scripts/run-h6c-memory-gateway.mjs
```

Endpoint mặc định `http://127.0.0.1:8012/mcp`. `ADLC_MEMORY_LOCAL_PORT` (tuỳ chọn) phải trong 1024–65535. CLI từ chối
cấu hình nằm trong ADLC/Harness hay các root source/snapshot đã cấu hình (kể cả junction đã resolve). Bạn vẫn phải tự
kiểm tra mọi mount project/model khác; kiểm tra path không phải bằng chứng isolation của OS.

6. Lưu `memory-gateways.json` **riêng cho backend** trong cùng thư mục private:

```json
{
  "schema_version": "0.1",
  "bindings": [{
    "owner_id": "<same owner UUID>",
    "project_id": "<same pinned project UUID>",
    "url": "http://127.0.0.1:8012/mcp",
    "token": "<same read-only gateway token>",
    "backend_revision": "local-curated:0.1.0",
    "isolation_reviewed": true,
    "no_model_route_reviewed": true,
    "retention_reviewed": true
  }]
}
```

Ba cờ review đại diện cho **rà soát thực tế của operator**, không phải chứng nhận tự động hay quyền mà agent có thể tự
cấp. Review quyền truy nguồn, process host riêng, binding credential/dataset và quyền lưu snapshot nguồn. `expires_at`
là ngày độ tươi của context, **không phải** xoá tự động archive cục bộ của ADLC. H6C không có API xóa; thống nhất
retention archive trước khi lưu văn bản nguồn nhạy cảm; nếu retention cần xoá theo hết hạn, giữ nguồn đó tắt cho tới khi
có workflow deletion/retention được review.

7. Trong `.env` backend ADLC chỉ đặt cờ và đường dẫn registry private rồi restart backend — **không** cần giá trị token
   nào trong `.env`:

```dotenv
ADLC_MEMORY_ENABLED=true
ADLC_MEMORY_GATEWAY_REGISTRY=C:/private-adlc-memory/memory-gateways.json
```

Run Detail → **Project memory** → **Check connection** → nhập query → **Find context**. Raw chunk trả về được lưu trong
ADLC và chỉ mang tính tư vấn, không phải ĐẠT/evidence. Seed rỗng hay không khớp từ khoá lexical cho một kết quả rỗng đã
lưu. Không có trạng thái run/contract/Verify nào khác thay đổi.

#### UI Harness và agent tool tuỳ chọn

Dòng native plugin được thêm là **chỉ-UI** (`toolsEnabled: false`) và không cài memory connector raw. Reload/rebuild
Harness theo quy trình hiện có để thấy tab/footer Memory. URL frontend public dùng `ADLC_CONTRACT_UI_URL` đã xác thực
như contract viewer hiện tại. Browser tải ADLC, không phải gateway; đăng nhập ADLC bình thường. Auth/framing
cross-origin thật vẫn cần sign-off deployment; test iframe offline không phải sign-off đó. Để bật đọc của agent **sau
khi** review gateway: đặt `toolsEnabled: true` trên `vai-adlc-project-memory` và cung cấp `ADLC_MEMORY_TOOL_SECRET` ngẫu
nhiên riêng ở ADLC và trong credential vault của Harness; đặt vault `ADLC_MEMORY_BASE_URL` trỏ về origin backend ADLC.
Harness trong Docker thì `localhost` là container đó; dùng route host đã review (thường
`http://host.docker.internal:7860`) và review tường minh `allowInsecureHttp: true` cho route development được bảo vệ này
— không expose bridge/gateway ra public bằng cách nới TLS/firewall.

Tham số tool không thể ghi đè session identity hay dataset. Với một lần đọc context: cung cấp `query`, `top_k` (1–10,
mặc định 5) và `idempotency_key` ổn định. Đọc provenance có cấu trúc và coi toàn bộ văn bản trả về là untrusted content.
Không có recipe coding mới hay plugin lock hiện có nào bị sửa ngầm.

### Điều chưa được cấp/bật một cách chủ ý

`http://10.0.10.195:8011/mcp` trong plugin đã tải là **dịch vụ private** của mentor, không phải localhost của
workstation này. Lượt này không gọi dịch vụ đó, không đọc key, không đổi network setting và không chứng nhận backend của
nó. Revision plugin `vai_agentmemory` `65a84337aec82b9aa5166f0712e56428f7734355` được giữ làm tham chiếu, không cài.
Cognee live cần: source/revision backend, tenancy read-only per-owner/project được enforce có xác thực (không chỉ tham
số tenant/session ID), ánh xạ provenance có cấu trúc, kiểm thử first-call/reconnect/session isolation, khả năng truy cập
an toàn và review **mọi** route model kể cả query embeddings. Gateway contract mới yêu cầu đọc không-model cho H6C;
tuyên bố capability/schema chỉ là kiểm tra tương thích, không phải bằng chứng server remote tùy ý enforce policy.
Ingestion curated tuỳ chọn và deletion tường minh do owner phê duyệt là việc tiếp theo sau khi review route model và
chính sách retention.

### Kiểm chứng và rollback

Test backend phủ: auth/scope first-call, JSON/SSE, đàm phán stateless/stateful, reconnect, concurrency, scope
chéo-owner, thiếu schema/route model, kiểm tra provenance, restart/idempotence/tamper archive, ủy quyền tool theo
attempt hiện tại, chiếu thụ động, chế độ tắt, văn bản stale và độc lập khi outage. Test native thêm các HTTP loopback
thật vào curated gateway, chứng minh từ chối query/status chéo-owner và mọi ghi/xóa, xác thực biên bridge/UI tuỳ chọn và
từ chối cấu hình CLI trong repository. Test UI và QA browser offline phủ provenance/độ tươi, query tường minh, dọn dẹp
khi đổi owner, văn bản escaped, profile unavailable/disabled/unknown và control Harness read-only; các suite H5/H6A/H6B
trước đó được regression. Kết quả (2026-10-13): **285 test chọn lọc ĐẠT** — backend 151, UI/controller 78, protected
runtime/native/CLI 56 — gồm **59 test H6C mới**. Python adapter chạy với gateway Node curated thật qua loopback, không
chỉ mock transport; cả 24 schema export H6A/B/C khớp runtime model; frontend production build đạt với các cảnh báo hiện
có; Ruff/Biome và diff scoped đạt. TypeScript toàn project vẫn còn 652 dòng diagnostic hiện có ngoài các path H6. Một
lần chạy worker song song vướng timeout readiness 2 giây sẵn có của H6A dưới tải đồng thời; trọn bộ 56 test worker ĐẠT
khi chạy tuần tự, không đổi runner/lock/timeout.

Chạy test chọn lọc:

```powershell
cd D:\coding\ADLC\adlc-flow
$env:PYTHONPATH=$PWD.Path
$env:ADLC_MEMORY_DB_PATH=''
$env:ADLC_MEMORY_GATEWAY_REGISTRY=''
.\.venv\Scripts\python.exe -m pytest tests/unit/adlc/test_project_memory.py tests/unit/api/v1/test_adlc_project_memory.py -q
.\.venv\Scripts\python.exe scripts/generate_adlc_memory_schemas.py --check
cd frontend
node node_modules/jest/bin/jest.js --runInBand --runTestsByPath src/components/adlc/MemoryPanel/index.test.tsx src/controllers/API/project-memory.test.ts
```

Preview offline (chỉ fixture, không auth/API/memory/model thật):

```powershell
node node_modules/vite/bin/vite.js --config tests/verification-viewer-preview/vite.config.mjs
```

Mở `http://127.0.0.1:4178/tests/verification-viewer-preview/index.html?slice=h6c&theme=light`, hoặc chọn **H6C Harness
projection**. Mô phỏng query chỉ là dữ liệu UI minh họa trong bộ nhớ, không phải đọc gateway hay phê duyệt. Rollback:
đặt `ADLC_MEMORY_ENABLED=false`, `toolsEnabled:false`, tắt dòng Memory plugin mới nếu muốn và dừng process gateway
riêng. Context đã lưu và toàn bộ archive contract/Verify/run chính thức đều còn. Không xóa journal, không sửa
schema/lock plugin đã publish trước đó, không restore/ghi đè thay đổi của người khác.

### Trạng thái

✅ **Read-only adapter, context lưu giữ, UI dùng chung và curated gateway cục bộ đã triển khai.** Còn pending: chứng nhận
live Cognee (`live_certified=false`), ingestion tuỳ chọn và deletion có owner phê duyệt.

---

## Milestone H6D — UI evidence dùng chung và test proposal có kiểm soát

> Trạng thái: **✅ slice cục bộ có giới hạn đã triển khai; khám phá trình duyệt live, capture tự động và thực thi
> performance vẫn bị chặn**. Triển khai/xác thực 2026-10-13 (Asia/Saigon). Xem
> [ADR 0020](../adr/0020-proposal-only-test-extensions-and-supplementary-raster-evidence.md).

### Mục tiêu

Hai việc: (1) một **UI evidence dùng chung** cho replay giữa Run Detail ADLC và pane Verify được bảo vệ của Harness, gồm
lịch sử regression scoped; (2) **test proposal proposal-only** do tool tạo, với lãnh địa target/data tường minh và ngân
sách performance chỉ để lập kế hoạch — cùng sidecar ảnh PNG tham chiếu không bao giờ đổi được kết luận. Mười hai [schema
máy-đọc-được mới](../../adlc-contracts/test-extensions/v0.1/README.md), version riêng khỏi H6A/B/C. Receipt, runtime
bytes, lock, `TaskResult` coding, quality gate, callback và ngữ nghĩa Submit đã publish đều giữ nguyên.

### Đã giao

- UI replay dùng chung trong Run Detail ADLC và iframe Verify được bảo vệ hiện có của Harness: coverage case
  completed/passed/failed/unfinished, ánh xạ tiêu chí, giá trị expected/observed chính xác, JUnit/JSON đã lưu, target
  release và trạng thái huỷ. Cùng renderer đọc cùng archive được ủy quyền bởi owner; **không** có approval proxy hay
  owner credential mới nào được đặt vào Harness.
- Lịch sử regression scoped trong một lần chạy thuộc sở hữu hay đúng source session Harness. Chỉ so sánh khi trùng
  suite/case expectation, tham chiếu contract, target/config profile và project/file. Oracle đã đổi là **một chuẩn
  mới**, không bao giờ là kết luận cũ được "phục hồi"; lặp lại cùng candidate được nhãn riêng. Đây là so sánh fixture,
  không phải chứng nhận regression ứng dụng hay coverage contract đầy đủ.
- Proposal JSON đóng do tool tạo: `test-extension-profile:proposals/0.1.0`. Suite revision/repair, ý định khám phá và
  lập kế hoạch performance có giới hạn — với tham chiếu digest chính xác, revision đã review bất biến và lineage cha
  tường minh. Thay đổi sau khi đóng băng cần một bản kế nhiệm; approval và quyền **không** kế thừa. Thay đổi case đề
  xuất được hiển thị đối chiếu suite nguồn trước khi review.
- Lãnh địa target/data tường minh: HTTP-JSON fixture không-production dùng một lần; dữ liệu synthetic thuộc run; GET
  `/fixture`; target loopback có xác thực được cấp phát; account ephemeral; release target thuộc sở hữu và huỷ worker có
  xác nhận; thời lượng tối đa 1–60 giây. URL tùy ý, host path, mật khẩu, target production, DELETE cleanup, deployment
  và thao tác Git **không** là tham số authoring.
- Giới hạn performance chỉ-lập-kế-hoạch: 1–5 VU, 1–30 giây, 1–5 request/giây, tối đa 100 request được lập kế hoạch, p95
  latency và trần request thất bại bắt buộc; rate × thời lượng không được vượt trần request hay thời lượng cho phép. UI
  người dùng dùng preset tường minh 2 VU / 10 giây / 2 rps / 20 request (p95 ≤500 ms, 0 request thất bại); tool chỉnh
  được trong biên. Đây **không** phải phép đo hay profile k6 đang chạy; không có runner/profile performance nào được
  đăng ký.

### Vòng đời proposal và quyền hạn

```text
Six small authoring tools -> DRAFT -> validate/freeze -> READY_FOR_REVIEW
  -> explicit owner approval of the exact document -> APPROVED
  -> suite-revision only: materialize once -> a NEW H6B replay DRAFT
  -> review/approve exact replay -> Run -> real comparison -> manual Submit
```

Proposal exploration/performance có thể được review nhưng không thể thực thi hay materialize thành replay suite.
`execute` trả `TEST_EXTENSION_EXECUTION_NOT_AVAILABLE` kể cả với proposal owner đã phê duyệt. `role`, `approved_by`,
`heal`, broker URL hay boolean quyền do caller khai không thể né. Không có healing tự động hay job retry. Approval
proposal không phải replay approval, không phải quyền thực thi, không phải Submit kết quả hay ủy quyền release.
Expectation có-typed đã đổi vẫn cần con người review đối chiếu contract; profile fixture hiện có không tự enforce yêu
cầu ngôn ngữ tự nhiên.

Materialization dùng plan ID xác định và persistent key bền vững qua hai archive. Crash giữa lúc lưu replay mới và liên
kết về proposal phục hồi đúng bản nháp đó, không nhân đôi job; suite/TRƯỢT/ĐẠT cũ giữ nguyên. Candidate được kiểm tra
freshness lần nữa; source unknown/stale, digest đổi, tiêu chí chưa ánh xạ, suite bắt buộc rỗng hay owner khác đều bị từ
chối. Bản nháp không hợp lệ vẫn sửa được cho tới khi validate; bản nháp đã đóng băng không sửa tại chỗ.

Plugin tuỳ chọn `vai-adlc-test-proposals@0.1.0` có đúng **sáu** agent tool:

| Tool | Thao tác nhỏ |
| --- | --- |
| `adlc_test_proposal_init` | Tạo draft từ một frozen replay thuộc sở hữu, hoặc fork một cha đã review chính xác |
| `adlc_test_proposal_upsert_case` | Thêm/thay một case có-typed dùng tham chiếu chính xác hiện tại |
| `adlc_test_proposal_remove_case` | Xóa một case draft; suite rỗng không thể đóng băng |
| `adlc_test_proposal_set_permissions` | Ghi lại lãnh địa target/data đã review và ngân sách lập kế hoạch tuỳ chọn |
| `adlc_test_proposal_get_status` | Đọc JSON/reference/trạng thái proposal scoped |
| `adlc_test_proposal_validate` | Validate ánh xạ/giới hạn và đóng băng để **con người** review, không bao giờ phê duyệt |

Danh tính agent đến từ session active đã ký, owner/run/request/attempt của kernel và project được compiler pin; không có
owner/project/role do caller khai. Session stale/terminal/chưa gắn hay chéo-project bị từ chối; agent không sửa draft do
con người tự viết độc lập hay draft của session khác. Tool bridge có HMAC domain/key riêng, giới hạn input 24 KiB và
output 128 KiB, mặc định HTTPS hay loopback thật, không redirect và không mutation retry tự động. Key scoped lặp lại trả
record đã lưu; tham số đổi dưới cùng key là conflict. Agent tool không phê duyệt/materialize, không upload screenshot,
không gọi TestForge, không dùng model, không publish kết quả.

### Screenshot: tham chiếu đã lưu, không phải bằng chứng tái lập

`evidence-profile:supplementary-png/0.1.0` là **sidecar tham chiếu do owner upload**. Runner HTTP deterministic hiện tại
không capture trình duyệt, vì vậy UI và record yêu cầu `SUPPLEMENTARY_UNTRUSTED`, `capture_provenance_verified=false` và
`affects_verdict=false`. Ảnh không thể thỏa một assertion bắt buộc hay đổi báo cáo; không có agent upload tool; không có
screenshot URL nào được fetch từ input.

Chỉ evidence replay hoàn thành đã lưu mới gắn được tham chiếu; nó gắn đúng owner/run/plan/execution/candidate/case và
digest evidence. PNG input được kiểm SHA-256; mỗi chunk CRC được validate; ảnh động, SVG/HTML, raster lỗi/quá cỡ và
critical chunk lạ bị từ chối. Metadata phụ bị loại trước khi decode; PNG RGBA tĩnh được re-encode và lưu dưới checksum
mới. Giới hạn: 256 KiB trước/sau, 4096 mỗi chiều, 4 triệu pixel, bốn ảnh mỗi replay. Byte input gốc **không** được lưu
(chỉ digest); download/preview dùng ảnh đã sanitize. Download yêu cầu ủy quyền owner/run, trả header
no-store/nosniff/CSP và content-digest header chính xác. Browser kiểm scope, metadata, type/signature PNG, kích thước và
SHA-256 thực trước khi tạo Blob preview; object URL bị revoke khi đổi scope/unmount, response account/session đến muộn
không thể đổ vào view kế tiếp. Harness đọc/preview được nhưng không upload. Báo cáo TRƯỢT và evidence cũ vẫn đọc được
khi module tắt hay session Harness gốc đã mất.

Archive sidecar SQLite mặc định `adlc-flow/data/adlc-test-extensions.sqlite3`: 200 record proposal/ảnh toàn cục, 1000
authoring command key, tổng 8 MiB nội dung lưu giữ/sổ cái key; tối đa 100 record/trang. Không GC nền hay API xóa. Rà
soát độ nhạy screenshot, retention và backup có xác thực trước khi upload dữ liệu private. Quota/hỏng archive fail
closed thay vì xóa lịch sử.

### Rollout và kiểm tra thủ công

`.env`, secret, provider/model, database live và dịch vụ đang chạy **không** bị lượt này thay đổi. Tự bật trong `.env`
backend rồi restart:

```dotenv
ADLC_TEST_EXTENSIONS_ENABLED=true
LANGFLOW_AUTO_LOGIN=false
```

Đăng nhập tường minh bằng owner của lần chạy. Dùng một frozen replay H6B hiện có đứng sau candidate JSON đã capture và
contract đã phê duyệt; H6B phải được bật riêng để materialize/chạy bản kế nhiệm; xem [H6B worker
setup](#milestone-h6b--replay-đóng-băng-và-readiness-testforge).

1. Run Detail → Frozen replay: xem lịch sử/coverage và evidence nguồn.
2. Test proposals: chọn nguồn đó, tạo suite revision, lưu một thay đổi case, ghi lãnh địa target/data tường minh, rồi
   Freeze for review.
3. Soát case cũ–mới đề xuất, digest chính xác và permissions. Tick ô review và Approve đúng proposal. **Không** job nào
   được khởi động.
4. Tạo successor replay draft; review/phê duyệt suite mới đó độc lập, rồi Run và quan sát. Xác nhận báo cáo gốc không
   đổi. Submit riêng.
5. Trên báo cáo hoàn thành, Load screenshot archive → tùy chọn gắn một PNG tham chiếu nhỏ. Kiểm nhãn chưa-xác-minh và
   checksum; nó không được đổi kết luận.
6. Trong Harness native, mở Verify cho cùng source session: báo cáo được bảo vệ, proposals, tham chiếu screenshot và
   Memory tư vấn scoped dùng cùng dữ liệu ADLC. Không được có control approve/upload/run/Submit ở đó.

Dòng plugin mới **tắt tool** (`toolsEnabled: false`). Agent authoring tuỳ chọn cần `ADLC_TEST_PROPOSAL_TOOL_SECRET` ≥32
bytes sinh riêng ở backend và vault Harness, cùng vault `ADLC_TEST_PROPOSAL_BASE_URL`; chỉ bật dòng đó sau khi review
phạm vi deployment. Không tái sử dụng credential callback, contract, memory, broker, owner hay model. HTTP plaintext
container-to-host cần quyết định `allowInsecureHttp` đã review, không phải default public HTTP. Lock/recipe thực thi đã
publish không bị viết lại để bật tool này.

Preview offline (không API/model/approval thật):

```powershell
cd D:\coding\ADLC\adlc-flow\frontend
node node_modules/vite/bin/vite.js --config tests\verification-viewer-preview\vite.config.mjs
```

Mở `http://127.0.0.1:4178/tests/verification-viewer-preview/index.html?slice=h6d&theme=light`; thêm `&host=harness` cho
client native/iframe thật ở bề rộng hẹp. Fixture ĐẠT/TRƯỢT/ảnh/proposal chỉ minh họa, không phải evidence có chữ ký; QA
browser chỉ dùng preview cô lập này, không chạm auth hay phê duyệt live.

### Kiểm chứng và biên còn lại

Test phủ: revision/fork chính xác, từ chối sửa đã-đóng-băng, idempotence và cross-store recovery; auth owner tường minh;
từ chối role/approval giả; isolation session/project active; case bắt buộc có ánh xạ; input performance có biên; PNG
hash/normalize/giới hạn/hỏng; chiếu owner/session được bảo vệ; payload hiển thị lạ; dọn dẹp khi đổi account; tách
proposal/Run/Submit. Bộ sinh schema kiểm parity H6A/B/C/D. Các regression contract/recovery/archive, runtime và UI chọn
lọc trước đó cũng được chạy; không có model trả phí hay gọi TestForge remote nào. Kết quả regression chọn lọc: **241**
test backend, **136** test UI/controller/Run Detail và **61** test native/runtime/CLI ĐẠT (tổng **438**, gồm **70 test
H6D mới**). Cả 36 schema H6A/B/C/D khớp runtime model; Ruff/Biome scoped đạt; frontend production build đạt với các cảnh
báo bundle/import/style hiện có. Typecheck frontend toàn cục vẫn còn lỗi baseline không liên quan; các path
H6D/Replay/ContractHarness/preview đã lọc không còn diagnostic. Native CLI chạy với cấu hình interpreter test-only trỏ
vào virtualenv của project; `python3` mặc định của máy này resolve về MSYS2 và thỉnh thoảng trượt bounded readiness
probe sẵn có. Không runner/lock/timeout nào đã publish bị đổi. Với worker trên host, chọn tường minh project Python qua
`ADLC_REPLAY_PYTHON` / `ADLC_VERIFICATION_PYTHON` nếu cần; invocations test có thể dùng `ADLC_H6B_TEST_PYTHON` /
`ADLC_H6A_TEST_PYTHON`; không đổi interpreter container sang đường Windows. Preview PNG offline và review proposal đã
kiểm thị giác; lượt thị giác native iframe về sau bị gián đoạn, không coi là sign-off Harness live. Unit check
client/chiếu native ĐẠT.

Khám phá/replay/staging/performance TestForge live và screenshot **runner** có xác thực vẫn chưa khả dụng. Cần trước:
backend/runner đã review, target gắn owner và quyền synthetic-data, dispatch/lookup idempotent thật, huỷ có xác nhận,
cleanup thuộc sở hữu, đọc artifact attest và sổ cái đo/case bắt buộc. Mọi route backed by model phải audit/pin về
`my-codex / cx/gpt-5.6-luna`; một phê duyệt lập kế hoạch không thay thế được các control đó. Các prerequisite này vẫn
hiển thị trong capability response và cả hai mặt UI; không cờ môi trường nào bật được executor còn thiếu. Rollback: chỉ
tắt cờ/tool row mới. Proposal/ảnh tham chiếu đã lưu và toàn bộ kết quả gốc vẫn đọc được. Không xoá archive hay viết lại
lock cũ. Slice kế hoạch tiếp theo: **H6E** — import draft/template Vanguard có version, không phải thực thi live rộng
rãi.

### Trạng thái

✅ **Slice cục bộ có giới hạn đã triển khai.** Còn bị chặn: khám phá trình duyệt live, capture tự động, thực thi
performance/TestForge thật.

---

## Nguồn tổng hợp

Các tài liệu nguồn được lưu trữ trên nhánh git `agentHarness`, xem bằng `git show agentHarness:docs/<file>` (bản gốc
tiếng Anh cũng còn trong `docs/` của repo):

- `docs/harness-milestone-h6a.md` — H6A — Trusted reproduction and retained evidence (2026-10-12)
- `docs/harness-milestone-h6b.md` — H6B — Frozen replay and TestForge readiness (2026-10-12–13)
- `docs/harness-milestone-h6c.md` — H6C — Project-scoped advisory memory (2026-10-13)
- `docs/harness-milestone-h6d.md` — H6D — Shared evidence UI and controlled test proposals (2026-10-13)

Ranh giới schema máy-đọc-được tương ứng trong `adlc-contracts/`: `verification/v0.1` (H6A), `verification-replay/v0.1`
(H6B), `project-memory/v0.1` (H6C), `test-extensions/v0.1` (H6D) — tổng quan ở
[adlc-contracts/README.md](../../adlc-contracts/README.md). Liên quan: [ADR
0017](../adr/0017-independent-reproduction-and-evidence-foundation.md), [ADR
0018](../adr/0018-frozen-http-replay-and-testforge-readiness.md), [ADR
0019](../adr/0019-advisory-project-memory-and-protected-readonly-gateway.md), [ADR
0020](../adr/0020-proposal-only-test-extensions-and-supplementary-raster-evidence.md), [kế hoạch tích hợp Vanguard
plugin](../reference/tich-hop-vanguard-plugin.md). Milestone trước: `harness-h4-h5.md`. Milestone kế tiếp (quyền
theo project, bốn role): `harness-h7a-team-roles.md`.

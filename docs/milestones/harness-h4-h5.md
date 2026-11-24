# Milestone Harness H4–H5: review artifact, hợp đồng và bằng chứng máy

> Ngày: 2026-10-05 → 2026-10-08. Chuỗi H4 → H5 → H5B → H5C → H5D.
> Tài liệu lõi tiếng Việt tổng hợp từ năm tài liệu milestone lưu trên nhánh git `agentHarness`.
> Chuỗi milestone này là tiền đề trực tiếp cho H6/H7 — tài liệu tổng hợp tiếp theo: `../harness-h6.md`.

## Vị trí trong tiến trình tổng thể

Trước H4, lần chạy của agent trả về **URI do model tự khai báo**: người review không thể biết patch thật sự là gì, nằm ở đâu và có bị sửa sau đó hay không; toàn bộ trust nằm ở lời tự nhận của model. Chuỗi H4–H5 lần lượt nâng từng tầng của stack lên "nói thật bằng bằng chứng":

- **H4** — Bắt thật: lấy diff thật từ checkout riêng, gắn correlation và checksum, ADLC lưu/review/download bytes thật thay vì tin URI.
- **H5** — Hợp đồng hóa: roadmap dự án trở thành *contract* JSON versioned; agent chỉ được soạn thảo qua đúng sáu tool `skilltree_*`, human phê duyệt nội dung rồi nội dung bị khóa.
- **H5B** — Shared Skilltree viewer trên cả ADLC và Harness cùng dedicated authoring package; handoff của agent là reference đã ký, không phải assistant text tự nhận.
- **H5C** — Agent hành động trong ranh giới contract đã phê duyệt (guarded tools, path policy) và để lại machine evidence gắn với từng tiêu chí.
- **H5D** — Bằng chứng đứng vững khi có crash giữa chừng: verification checkpoint/recovery, không bao giờ recapture hay gọi lại model để "vá" bằng chứng.

Sau H5D, các vấn đề còn lại chuyển sang giai đoạn H6/H7: activation đầy đủ trên stack live, vận hành thực tế và các lớp chất lượng kế tiếp (xem `../harness-h6.md`).

---

## Milestone H4 — Artifact review và verification có bằng chứng

> Ngày: 2026-10-05. **H4A: đã triển khai. H4B: chưa triển khai.** Kiểm tra cuối: 2026-10-07 (repository-wide capture, backend/API và Harness; frontend được ghi nhận riêng ở dưới). Đây là mốc thứ tư của ADLC–Harness, không thay thế tài liệu `plan-materialization-slice-4.md` của Blueprint → mock runtime trước đây.
>
> **Trạng thái: ✅** (H4A nghiệm thu offline; live-model E2E chưa chạy)

### Mục tiêu

Agent tạo thay đổi trong checkout riêng; plugin lấy diff thật, gắn correlation và checksum, chuyển bytes để ADLC lưu/review/download. Không còn chỉ tin vào URI do model khai báo. H4A không chứng minh code đúng: lint/unit-test verifier thuộc H4B. Approve lifecycle và Submit kết quả vẫn là hai quyết định khác nhau; không thao tác nào ở đây tự apply patch, commit, push, merge hay deploy.

Phạm vi — làm: clone snapshot riêng, actual Git diff, artifact có checksum, preview/review UI, archive sau phê duyệt. Không làm: verifier chạy lint/unit-test (H4B), apply/commit/push/merge/deploy, transcript archive, multi-worker lease, automatic workspace cleanup.

### Thiết kế chính

#### Phân chia trách nhiệm

| Thành phần | Trách nhiệm |
| --- | --- |
| ADLC | Workflow/attempt, ownership, durable bytes, preview/review, result acceptance và lifecycle approval. |
| Harness kernel | Session state, correlation, plugin integrity, persistence, authenticated API và outbox/HMAC. |
| `vai-adlc-artifacts-git@0.2.0` | Clone committed snapshot riêng và lấy bounded Git diff trên mọi safe repo-relative path. |
| `vai-adlc-driver-deepseek@0.2.0` | Chạy agent ở cwd được cấp, nối interaction tới cùng session. |
| `vai-adlc-runtime@0.3.0` | Lưu prepared descriptor/private bytes trước khi release agent. |
| `vai-adlc-verify-structured@0.1.0` | Kiểm tra cấu trúc output, chưa chạy lint/test. |
| `coding-agent-deepseek-harness@0.3.2` | Recipe H4A repository-wide, exact plugin lock, mặc định MANUAL. |

Recipe H2 `0.1.0`, H3 `0.2.0`, H4A ban đầu `0.3.0` và ownership hotfix `0.3.1` giữ nguyên bytes đã publish. Tạo run H4A bằng package `0.3.2` và kế hoạch mới, không đổi package/lock của run đang chạy. Deployment H4 dùng plugin bytes mới; historical results vẫn đọc offline từ ADLC, nhưng lock cũ không tự được nâng cấp.

#### Luồng thực thi

1. ADLC lưu request/attempt trước dispatch, gửi profile `harness-profile:adlc-coding-artifacts/0.1.0` và lock H4.
2. Collector đọc committed HEAD của repository **do deployment cấu hình**. Local clone riêng không hardlink, không copy dirty working tree/config/hooks; checkout đúng base commit và bỏ remote. Không sửa checkout nguồn.
3. Driver tạo agent ở checkout riêng. FORM/APPROVAL và resume giữ nguyên session/cwd/base commit. Thiếu manifest khi resume thì fail, không tạo workspace thay thế.
4. Khi agent hoàn tất, collector lấy tracked diff so với base (kể cả staged) và file untracked không bị Git ignore. Không đọc URI hay file path do agent khai báo.
5. Snapshot `harness-git-diff-v1` chứa base commit và per-file diff. Artifact SOURCE_PATCH có run/task/attempt IDs, SHA-256, byte length, expiry. Runtime thay output URI bằng URI publisher-owned.
6. Descriptor và private payload được persist cùng prepared result trước khi dispose agent. Session/result/webhook chỉ có descriptor, không nhúng bytes.
7. MANUAL preview có thể đọc/cache trong ADLC, nhưng chưa accept/Submit result.
8. ADLC Submit giữ patch trước khi enqueue delivery. Signed callback hoặc reconciliation cũng phải giữ bytes thành công **trước** immutable acceptance. Duplicate accepted replay không phụ thuộc live Harness hay byte availability nữa.
9. Accepted patch dùng artifact API của ADLC: backend restart hoặc agent cleanup không làm mất nội dung chưa hết hạn. Artifact của attempt cũ đọc được từ attempt ledger.

Checkout isolation **không phải một OS security sandbox mới**. Tool/network/filesystem permissions vẫn do deployment Harness áp dụng. Publisher allowlist giới hạn nội dung được xuất, không tự giới hạn mọi hành động agent có thể thực hiện trong hệ điều hành.

#### Cấu hình và cách chạy

`plugins/patch.yml` quản lý source repo, vùng checkout và allowlist; workflow không được override các đường dẫn đó. Profile H4 pin provider `my-codex`, model `cx/gpt-5.6-luna`.

- Source trong container: `/app/artifact-source`, mount read-only.
- Checkout: `/app/workspace/adlc-runs/<session UUID>`.
- Manifest: `/app/data/adlc-artifact-workspaces/<session UUID>.json`.
- Allowlist deployment hiện tại: `allowedPaths: ['*']`. Marker `*` cho phép mọi safe repository-relative source path, gồm `DEPLOYMENT.md`, dotfiles thông thường và folder bất kỳ. Traversal/sensitive-path checks luôn chạy **trước** matcher; `*` không bypass chúng. Đây không phải filesystem glob hay quyền đọc/ghi cả máy. Exact file và directory-prefix allowlists cũ vẫn được hỗ trợ nếu operator muốn thu hẹp cấu hình deployment.
- Bubblewrap tạo device tree tối thiểu bằng `--dev /dev` để Git đọc `/dev/null`; không bind toàn bộ `/dev` của host vào sandbox.
- Collector dùng Git config tạm, riêng cho mỗi clone/probe, chỉ tin cậy canonical source root và actual Git directory. `GIT_CONFIG_GLOBAL` trỏ vào file này **chỉ** trong hai thao tác đó để local upload-pack nhận cùng trust; các lệnh Git khác vẫn bỏ account/system config. File nằm ngoài checkout, trong thư mục private của publisher và được dọn ở `finally`. Không chạy `git config --global`, không dùng `safe.directory=*`, không đổi ownership của source.

Chuẩn bị repo demo sạch, không chứa credentials, có ít nhất một commit. Không dùng checkout ADLC chính để thử model. Source phải là repository root; nội dung chưa commit không được đưa vào session.

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
$env:ADLC_HARNESS_SOURCE_REPO='D:/coding/adlc-h4a-demo'
docker compose up -d --build
```

Nếu không đặt biến, compose dùng `./artifact-source`; folder rỗng ở đó chưa đủ để chạy H4A. `ADLC_OPENCODE_SOURCE_REPOSITORY` chỉ dành cho OpenCode, không cấu hình mount của Harness. Nếu lưu `ADLC_HARNESS_SOURCE_REPO` trong root `D:\coding\ADLC\.env`, nạp rõ file đó:

```powershell
docker compose --env-file D:\coding\ADLC\.env up -d --force-recreate deepseek-harness
(docker inspect deepseek-harness-bwrap | ConvertFrom-Json).Mounts |
  Where-Object { $_.Destination -eq '/app/artifact-source' } |
  Select-Object Source, Destination, RW
```

Shell environment có độ ưu tiên cao hơn env file. Restart container cũ không đổi bind mount; phải recreate với đúng cấu hình. Lệnh kiểm tra trên tránh lỗi quoting Go template của PowerShell. API token, callback secret và provider key giữ cấu hình hiện có; H4A không thay credentials. Health trả `artifact_capture_ready` và trạng thái theo profile; source không tồn tại hoặc chưa có commit bị từ chối trước khi tạo session/model turn, không âm thầm dùng workspace khác. Readiness còn probe `upload-pack --strict --advertise-refs` bằng cùng private config như clone — đây là Git transport read-only, không clone/start model/create session workspace; không chỉ dựa vào `rev-parse HEAD`, vốn có thể thành công dù clone bị ownership check chặn. Request idempotent đã có session vẫn replay đúng session nếu source tạm thời không còn sẵn sàng. Source, manifest và workspace roots phải tách biệt; cấu hình chồng lấn bị từ chối trước khi tạo thư mục, kể cả đường dẫn đi qua alias/symlink. Trước khi deploy plugin mới, để session dùng lock cũ kết thúc; không restart Harness giữa model turn khi chỉ muốn kiểm thử ADLC recovery — lock mismatch vẫn fail closed.

#### API và contract

Request/result/delivery vẫn dùng version `0.1`. H4A bổ sung closed `artifact-read.schema.json`, không thêm field bắt buộc vào envelope cũ.

```text
Harness, bearer service token:
GET /api/v1/adlc-harness/sessions/{session_id}/artifacts/{artifact_id}

ADLC, authenticated run owner, preview:
GET /api/v1/adlc/runs/{run_id}/harness-sessions/{session_id}/artifacts/{artifact_id}

ADLC, authenticated run owner, accepted artifact:
GET /api/v1/adlc/runs/{run_id}/artifacts/{artifact_id}
```

Harness read trả `schema_version`, `session_id`, `correlation`, `artifact`, `payload_base64`. ADLC chỉ gọi configured Harness client theo opaque IDs, không follow artifact URI. Import kiểm tra exact correlation/descriptor, producer, format/media type, base commit, SHA-256 và bounds. ADLC hỗ trợ producer collector `0.1.0`, `0.1.1` và `0.2.0`; lúc import result, producer phải khớp collector required trong result lock; version chưa được hỗ trợ không được chấp nhận. Preview retention không biến result thành accepted; standard artifact route chưa phục vụ nó như accepted artifact. Read responses có `Cache-Control: no-store`; foreign owner nhận 404 trước khi có remote read.

#### Giới hạn và lỗi

- H4 capture: tối đa **512 KiB snapshot JSON**, **128 file**, **24 giờ**; cấu hình chỉ được giảm cap.
- ADLC dùng bounded durable store: 2 MiB/artifact, 32 MiB tổng, tối đa 24 giờ từ lần giữ đầu và không quá publisher expiry. Restart/read không gia hạn.
- Reject traversal/control characters/Windows ADS, file ngoài allowlist, `.env*`, credentials, secrets, private-key/VPN files. Đây không phải secret-content scanner hay DLP.
- Không publish symlink, submodule, binary/non-UTF-8 diff hoặc checkout có Git config/metadata bị thay đổi. H4A dành cho source repo text đơn giản, chưa phải general artifact archive.
- Empty actual diff hợp lệ được hiển thị là không có file thay đổi; không bịa patch.
- Capture lỗi → failed structured result, không publish partial patch như thành công. Code điển hình: `HARNESS_ARTIFACT_SOURCE_UNAVAILABLE`, `HARNESS_ARTIFACT_GIT_FAILED`, `HARNESS_ARTIFACT_PATH_NOT_ALLOWED`, `HARNESS_ARTIFACT_SENSITIVE_PATH`, `HARNESS_ARTIFACT_UNSUPPORTED_FILE`, `HARNESS_ARTIFACT_GIT_METADATA_CHANGED`.
- Import/checksum/storage lỗi → ADLC chưa accept result; outbox retry theo policy hiện có. Lỗi trả code an toàn, không log patch/credential.
- Hết hạn → 410; run/result/descriptor vẫn còn. Không re-execute model hay gia hạn để đọc. MANUAL Submit sau publisher expiry bị từ chối.
- Checkout/manifest là dữ liệu vận hành trên persistent volume. H4A không tự xóa workspace; cleanup/retention workspace là công việc riêng. Byte expiry được kiểm tra lúc đọc/startup.
- ADLC vẫn dùng một coordinator cho mỗi database pair; chưa có distributed worker lease.

#### Run Detail

**Changes to review** có task/attempt, **Preview — not submitted** hoặc **Saved artifact**, file list/diff plain text, base commit, checksum, bytes, expiry và **Download patch**. Diff không thực thi HTML/Markdown/script; download chỉ tạo `.patch` ở browser. Submit của session có H4 patch bị disable khi preview chưa tải được; backend vẫn kiểm tra retention khi Submit. Lifecycle approval kiểm tra patch của task hiện tại, không bị artifact lịch sử hết hạn chặn nhầm. Không có endpoint apply/commit/push.

#### Live acceptance checklist — chỉ Luna

1. Mount source repo demo, start Harness, restart ADLC để load code mới.
2. Chọn package `coding-agent-deepseek-harness@0.3.2`, MANUAL.
3. Requirement: "Chỉ trong checkout local riêng của session, thêm dòng `H4A demo` vào README.md. Hỏi xác nhận trước khi kết thúc. Không commit/push và không dùng remote VFS."
4. Compile → Accept plan → Start run; xử lý FORM/APPROVAL trong ADLC.
5. READY_FOR_SUBMISSION: review/download diff thật; source repo host vẫn nguyên; trước Submit, attempt chưa có accepted result.
6. Restart **chỉ ADLC**, reopen cùng run, giữ task/attempt/session, rồi Submit.
7. SUCCEEDED: Saved artifact giữ checksum. Khi run đã hoàn tất, tắt Harness/restart ADLC, đọc/tải lại patch chưa hết hạn từ cùng Run Detail.

Không fallback provider/model. Checklist cần deployment/credential do operator cấu hình; chưa ghi nhận là đã chạy model thật trong triển khai slice này.

### Proof/verification

H4A test dùng **Git, runtime persistence, outbox/HMAC và SQLite thật**, execution driver là fake có chủ đích; không gọi model. Fixture cross-language tạo actual diff rồi đi qua coordinator/HTTP: preview → restart → Submit → callback → offline archive → restart → expiry. Checksum sai chặn callback acceptance và Submit forwarding.

Từ `adlc-flow`:

```powershell
$env:ADLC_RUN_DB_PATH=' '
$env:ADLC_HARNESS_ATTEMPT_DB_PATH=' '
$env:ADLC_HARNESS_ENABLED='false'
$env:ADLC_OPENCODE_ENABLED='false'
.venv\Scripts\python.exe -m pytest tests/unit/adlc tests/unit/api/v1/test_adlc_runs.py tests/unit/api/v1/test_adlc_harness_results.py tests/unit/api/v1/test_adlc_artifacts.py tests/unit/api/v1/test_adlc_plans.py -q -o log_cli=false
```

Từ `agent-harness-server/deepseek-harness`:

```powershell
node --test plugins/vai-adlc-artifacts-git/tests/*.test.mjs plugins/vai-adlc-runtime/tests/*.test.mjs plugins/vai-adlc-driver-deepseek/tests/*.test.mjs
node scripts/sync-adlc-plugin-lock.mjs --check
```

Từ `adlc-flow/frontend`:

```powershell
npm test -- --runInBand --watch=false src/pages/RunDetailPage/SourcePatchReview.test.tsx src/pages/RunDetailPage/index.test.tsx src/pages/RunDetailPage/HarnessResults.test.tsx src/controllers/API/__tests__/adlc.test.ts src/pages/RunHistoryPage/index.test.tsx src/components/core/appHeaderComponent/__tests__/appHeader.a11y.test.tsx
npm run build
```

**Kết quả xác nhận — 2026-10-06:**

- Backend/API: **238 ĐẠT**, gồm integration cross-language dùng Git thật.
- Harness collector/runtime/driver: **40 ĐẠT**, gồm session-cwd, Luna pinning, source preflight, idempotent recovery và expiry tính từ một creation timestamp.
- Frontend: **42 ĐẠT / 6 suites**; preview → saved, download và preview lỗi chặn Submit.
- Frontend production build: đạt; còn các cảnh báo bundle/Tailwind hiện có.
- Ruff trên 15 file backend của slice và Biome trên 7 file frontend: đạt.
- Exact plugin-lock check và `git diff --check` ở cả hai repository: đạt.
- Full-repo TypeScript check **chưa đạt**: 645 dòng diagnostic ở ngoài các file ADLC được kiểm tra; không có diagnostic trong các file ADLC của slice. Không coi đây là full-repo green.
- Pytest còn 2 cảnh báo cấu hình timeout; không có test TRƯỢT hoặc bị skip trong bộ trên.
- Chưa chạy live E2E với model thật hoặc ghi nhận Docker deployment là đã nghiệm thu. Provider/model duy nhất cho live checklist vẫn là `my-codex` / `cx/gpt-5.6-luna`.

#### Hotfix 1 — device tree và allowlist — 2026-10-07

Mount source đúng vẫn có thể gặp `HARNESS_ARTIFACT_GIT_FAILED` nếu sandbox không có `/dev/null`. Đã tái hiện bằng Git read-only trong Bubblewrap: không có device tree thì Git báo `could not open '/dev/null'`; cùng lệnh với `--dev /dev` thành công.

- Startup đã thêm device tree tối thiểu, giữ source read-only, user namespace và cap-drop.
- Deployment allowlist đã thêm `client/` và `server/`; file `.env` bên trong vẫn bị reject.
- **42 Harness tests ĐẠT**, gồm hai regression tests mới; Bash syntax, exact plugin lock và whitespace checks đều đạt. Không đổi bytes/version của plugin production.
- Đã recreate riêng service `deepseek-harness`, dùng root `.env` và mount `D:/coding/Meta_ecom` read-only. Source HEAD/working tree không bị chỉnh sửa.
- Live authenticated health trả `ready: true`, `artifact_capture_ready: true`, `callback_ready: true`, `plugin_lock_ready: true`, `storage_ready: true` và `execution_driver_ready: true`; artifact profile không còn error code.
- Không gọi model, không tạo attempt/run mới, không đổi credential. Model route vẫn là `my-codex` / `cx/gpt-5.6-luna`. Đây là xác nhận deployment readiness, chưa phải live-model E2E.

Health ở bước này mới kiểm tra root/HEAD, chưa phát hiện ownership lỗi trong clone. Probe transport đã được bổ sung trong hotfix tiếp theo; không coi kết quả health cũ là bằng chứng clone thành công.

#### Hotfix 2 — Git ownership trong local upload-pack — 2026-10-07

Session `91d1ecae-dbf0-4cf0-a878-16d386db9f0f` lỗi sau 560 ms, trước khi driver/model bắt đầu. Source `.git` mount từ Windows có UID 65534, trong khi Harness chạy UID 1000. Parent `-c safe.directory` không được local upload-pack giữ lại, nên clone báo `detected dubious ownership in repository at '/app/artifact-source/.git'`.

- Collector `0.1.1` cấp exact private trust cho source/actual Git directory; local clone vẫn dùng `--no-local --no-checkout`, checkout đúng committed base và xóa origin.
- Health dùng cùng transport trust và fail closed khi upload-pack lỗi, kể cả khi HEAD đọc được.
- Phát hành recipe `0.3.1` với lock mới; sync tool chỉ target recipe mới và contract examples, không sửa `0.3.0`. Regression test giữ SHA-256 bytes cũ `0c767bbd2b2e6f34c7d60cac85e34c383902a59f308b1ce7aad9eb76914d989b`.
- **252 backend/API tests ĐẠT**, gồm cross-language Git capture → preview → restart → Submit → signed callback → offline archive, hai producer versions và lock mismatch guards.
- **47 Harness tests ĐẠT**. Git ownership regression dùng real Git/local upload-pack với [ownership test switch của Git upstream](https://github.com/git/git/blob/v2.46.2/t/t0033-safe-directory.sh), chỉ được test runner inject, không lấy từ production environment. Có thêm failure cleanup, readiness false-positive, concurrent private configs và published-recipe immutability checks.
- Ruff check/format trên 6 file backend đã đổi đạt; pytest còn 2 cảnh báo timeout config có sẵn. Không đổi frontend và không chạy lại bộ frontend trong hotfix này.
- Đã recreate riêng Harness sau khi xác nhận không có active execution/delivery. Live authenticated health trả `ready: true`, `artifact_capture_ready: true`, các readiness khác đều true và installed collector version `0.1.1`; route vẫn `my-codex` / `cx/gpt-5.6-luna`.
- Smoke test trong Bubblewrap dùng source thật `D:/coding/Meta_ecom` read-only: **323 tracked files** clone/checkout thành công; một file `client/` được tạo chỉ trong checkout tạm, capture actual diff và kiểm tra SHA-256/resume thành công. Source HEAD và status không đổi; checkout/manifest thử nghiệm đã được dọn. **0 model calls**.
- Không đổi credentials, không tự sửa plan/attempt cũ, không apply/commit/push source.

Sau hotfix, restart backend ADLC nếu chưa tự reload, refresh UI, đổi node sang package `coding-agent-deepseek-harness@0.3.1`, rồi Compile → Accept plan → Start run mới. Run đã FAILED không tự tiếp tục; retry trên accepted plan `0.3.0` vẫn mang lock cũ. Prepared/historical results không bị xóa hay đổi lock. Đây là nghiệm thu Git transport/capture, chưa phải live E2E với model thật.

#### Repository-wide source capture — 2026-10-07

Session `b242a6b1-824c-4f37-a6f9-59264a5436aa` đã chạy model và hoàn tất FORM, nhưng collector reject `DEPLOYMENT.md` vì file nằm ngoài allowlist cũ. Đây là policy xuất patch, không phải thiếu quyền admin/firewall. User đã chấp thuận mở mọi source path trong repo với hard guards giữ nguyên.

- Collector `0.2.0` thêm marker `*`, deployment dùng `allowedPaths: ['*']`. Exact file/directory-prefix policy vẫn hoạt động; wildcard chỉ match sau traversal và sensitive-path guards, không cấp quyền ra ngoài checkout hay đổi Git `safe.directory`.
- Chỉ export actual changed Git diff: tracked/staged/deleted và untracked không bị ignore. Dotfiles thông thường như `.gitignore`, `.github/` được phép; protected paths, binary, non-UTF-8, symlink/junction, submodule và metadata tamper vẫn bị từ chối. Caps vẫn **512 KiB / 128 file / 24 giờ**, không có secret-content scanner/DLP.
- Recipe mới `coding-agent-deepseek-harness@0.3.2`, MANUAL, pin collector `0.2.0` cùng exact lock. `0.3.0` và `0.3.1` giữ nguyên bytes; sync tool target `0.3.2`. Hash bytes `0.3.1` được regression test giữ cố định: `f96d16c29ef23e4d7a9408ffc9b76e31abbfdf806625372630d068e5cfffdb31`.
- ADLC importer hỗ trợ producer mới và vẫn đọc hai version cũ offline; required producer/lock, descriptor, correlation, checksum, byte bounds và expiry không bị bỏ qua.
- **261 backend/API tests ĐẠT**: fixture cross-language capture `DEPLOYMENT.md` và `docs/architecture.md` qua preview → restart → Submit → signed callback → offline archive. Test runner dùng fresh workspace basetemp/cache disabled vì shared Windows pytest temp folder gặp ACL error sau khi tool session bị ngắt; không đổi quyền folder hay production data. Còn 2 cảnh báo timeout config có sẵn.
- **79 Harness tests ĐẠT**, gồm secret paths/case/depth, traversal/ADS/control characters, dotfiles, Git ignore, staging/deletion, symlink/junction, non-UTF-8/binary, caps, immutable workspace policy và immutable published recipes. Không có skip/failure.
- Ruff check/format trên 6 file backend, collector/Bash syntax, exact plugin lock và whitespace checks đạt. Frontend không đổi và không chạy lại trong slice này.
- Đã recreate riêng Harness khi không có active execution/delivery; source vẫn mount `D:/coding/Meta_ecom` read-only. Live health/integrity đều ready, collector `0.2.0`; provider/model vẫn `my-codex` / `cx/gpt-5.6-luna`.
- Docker smoke dùng Bubblewrap với device tree, tmpfs `/tmp`, HOME/PATH như production: clone/checkout **323 tracked files**, capture **2 file** (root `DEPLOYMENT.md` và nested document), SHA-256/resume đạt, fake nested `.env` bị reject. Hai diagnostic tối giản trước đó bị clone timeout; full-runtime diagnostic và final capture đã đạt. Không đổi Git deadlines. Source HEAD/status không đổi; mọi diagnostic checkout/manifest đã được dọn.
- **0 model calls** trong triển khai/verification này. Chưa chạy live-model E2E cho recipe mới.

Restart backend ADLC nếu chưa reload, refresh UI và chọn package **`0.3.2`**, rồi Compile → Accept plan → Start run mới. Run FAILED cũ không tự hồi phục. Không chỉnh manifest/accepted plan để mở scope hồi tố: policy mismatch khi resume vẫn fail closed; prepared/historical results giữ nguyên và không bị xóa.

### Hạn chế còn lại

- Plugin artifact độc lập; ADLC vẫn là control plane, Harness là execution plane.
- Actual patch có correlation/checksum và checkout riêng, thay cho URI self-report.
- Preview trước Submit và archive sau acceptance trong ADLC, đọc được sau restart.
- Bounds, expiry, owner isolation và fail-closed acceptance.
- Chưa có lint/unit-test verifier thực thi (H4B), apply/merge/deploy, transcript archive, multi-worker lease hoặc automatic workspace cleanup; đó là các slice sau.

Tham khảo: [durable recovery](../reference/luc-chay-va-phuc-hoi.md) và [ADR 0011](../adr/0011-use-deepseek-harness-as-a-plugin-execution-hub.md).

---

## Milestone H5 — Contract-document plugins

> Ngày cập nhật: 2026-10-08. **H5A và H5B đã triển khai, opt-in. H5C/H5D chưa triển khai tại thời điểm H5.** Không thay thế H4A source-patch review; H4B verifier chạy lint/test vẫn là slice riêng, chưa hoàn thành.
>
> **Trạng thái: ✅** (H5A/H5B opt-in; live activation tắt mặc định)

### Mục tiêu

Milestone H5 đưa vào khái niệm **contract**: văn bản JSON có schema/manifest versioned mô tả roadmap/Skilltree của dự án, đọc được bởi human lẫn agent, và là đầu vào machine-enforce cho các chặng sau (H5C). H5A cung cấp:

- Schema/manifest versioned và JSON đầy đủ cho contract Skilltree, đọc được bởi human và agent.
- Sáu tool nhỏ, có ID ổn định, revision và idempotency; **ADLC writer tạo/lưu JSON**, không nhận một JSON tổng thể do model in ra hay viewer import.
- SQLite store riêng, lưu lịch sử durable, không dùng thời hạn 24 giờ của source patch.
- Validate cấu trúc và khai báo tiêu chí; human approve đúng `{schema_ref, contract_id, revision, content_digest}`.
- Approved content bị khóa; human fork tạo draft mới với `supersedes`, giữ nguyên contract/approval cũ.
- Owner-scoped API đọc/export JSON canonical/summary Markdown; bridge ký HMAC cho tool trong Harness.
- Agent guide, plugin template, ví dụ hợp lệ/không hợp lệ, ADR và script kiểm tra không cần model thật.

H5B đã thêm shared UI và published dedicated authoring recipe/profile; live activation vẫn tắt. Chi tiết boundary, rollout và checks ở chặng H5B. H5A khóa nội dung đã duyệt qua API. H5B vẫn chưa ép mọi hành động coding tuân thủ roadmap; binding approved contract → planning/execution/verifier thuộc H5C. Không thể thay enforcement bằng prompt.

### Thiết kế chính

#### Phân chia trách nhiệm

| Thành phần | Trách nhiệm |
| --- | --- |
| ADLC | Ownership/run/task/attempt binding, typed writer, canonical bytes, revision history, validation/approval/fork. |
| Harness | Context session thật, scoped transport, credential resolution, tool registration. |
| `vai-adlc-skilltree@0.1.0` | Sáu authoring tool, input-schema projection phù hợp SDK, model-visible JSON và agent guide. |
| Shared renderer (H5B) | Cùng semantic JSON/reference trên hai host; layout không đổi meaning/approval. |
| Policy adapter/verifiers (H5C) | Pin exact approved reference, giới hạn execution và kiểm tra evidence. |

ADLC là **một nguồn dữ liệu durable**, không đồng bộ hai bản JSON mutable ở hai server. Canonical document không chứa pixels, viewport, progress, owner secret hay `approved: true` do agent đặt. Read projection chứa document/reference, server binding, status và các receipt riêng. Export JSON là chính content; proof/status approval đọc từ owner-authorized API, không suy ra từ file được import.

#### Sáu tool và lifecycle

| Tool | Phạm vi |
| --- | --- |
| `skilltree_init` | Một draft: title/scope/constraints, expected revision 0; writer sinh contract ID. |
| `skilltree_upsert_node` | Thêm hoặc thay thế một node; writer sinh ID khi thêm. |
| `skilltree_remove_node` | Xóa một node không còn dependency. |
| `skilltree_set_dependency` | Thêm/xóa một cạnh `REQUIRES` hoặc `CONTAINS`. |
| `skilltree_get_status` | Đọc đúng document bound vào session, revision và receipt; hỗ trợ historical read. |
| `skilltree_validate` | Kiểm tra đúng draft revision, trả các check và digest; không chạy test/approve. |

Edit tạo revision mới và xóa validation trên revision mới. Validate/approve không sửa content bytes hay tăng revision. Identical retry dùng cùng key + normalized arguments được replay; đổi arguments với cùng key bị `CONTRACT_IDEMPOTENCY_CONFLICT`. Replay có thể đọc một revision cũ, không mutate lại. Stale edit/hash bị `REVISION_CONFLICT`. SQLite `BEGIN IMMEDIATE` fence cả hai writer process và race approve/edit.

Approve chỉ nhận exact current reference và declaration validation thành công. Sau approve, mọi new mutation bị `CONTRACT_LOCKED`, kể cả validate. Human fork giữ original, tạo contract ID mới, revision 1/DRAFT và cần approve lại. v0.1 title/scope/constraints chỉ đặt khi init; fork copy các trường này. Muốn đổi chúng phải init một draft riêng, không âm thầm sửa approved contract.

Node kinds: MILESTONE/TASK/DECISION. REQUIRES: prerequisite → dependent; CONTAINS: milestone → child. Một node tối đa một containing parent; combined graph phải acyclic. TASK phải có acceptance criteria. TEST/ARTIFACT criteria phải khai báo `verifier_ref`; đây không phải shell command và không chứng minh verifier đã chạy. Validation luôn có `criteria_executed: false`.

#### API và authentication

Tất cả route dưới `/api/v1/adlc`; default feature flag off trả 404.

| Route | Quyền/hiệu lực |
| --- | --- |
| `GET /runs/{run}/contracts` | Active owner; paginated current heads. |
| `GET /runs/{run}/contracts/{id}?revision=N` | Active owner; current/historical read. |
| `GET /runs/{run}/contracts/{id}/file?revision=N` | Canonical UTF-8 JSON download, SHA256 header. |
| `GET /runs/{run}/contracts/{id}/summary?revision=N` | Generated escaped Markdown; không phải bản editable thứ hai. |
| `POST /runs/{run}/tasks/{task}/contract-tools` | Explicit human login; cùng sáu typed writer commands. |
| `POST /runs/{run}/contracts/{id}/approve` | Explicit human owner, exact reference + idempotency key. |
| `POST /runs/{run}/contracts/{id}/fork` | Explicit human owner, exact approved reference + key. |
| `POST /contract-tools` | Separate HMAC bridge, registered active/current dedicated authoring attempt only. |
| `GET /contract-viewer` | H5B authenticated renderer/human-action capabilities. |
| `GET /harness-sessions/{id}/contracts` | H5B exact-session owner read, kể cả completed attempt. |
| `POST /contract-authoring-result` | H5B purpose-separated signed read of the active authoring attempt's only validated head. |

Reads giữ cơ chế active-user/owner authorization của ADLC. **Human writes/fork/approval yêu cầu `LANGFLOW_AUTO_LOGIN=false` và explicit user access token hoặc `access_token_lf` cookie.** Không nhận `x-api-key`, Harness bearer token, callback/model key hay tool HMAC làm approval authority. Inactive user bị từ chối. Không tự thay cấu hình login của deployment đang chạy. Các interaction FORM/APPROVAL của agent, lifecycle approval, contract approval và Submit result là quyết định khác nhau; approve contract không tự resume/submit/complete workflow.

Bridge secret mới: `ADLC_CONTRACT_TOOL_SECRET`, tối thiểu 32 UTF-8 bytes, không fallback sang secret cũ. HMAC input: `"adlc-contract-tools-v1\n" + timestamp + "\n" + exact_body`; headers `X-ADLC-Contract-Timestamp`, `X-ADLC-Contract-Signature: sha256=<hex>`; tolerance 300 giây. Không dùng H4 callback-signature format cho bridge này. Stable keys ngăn duplicate writes trong replay window.

`session_id` lấy từ `execution.agent.session.id`, không nằm trong model argument schemas. ADLC tự resolve owner và full correlation từ attempt đã register/bind. Unknown/finished/stale attempts bị từ chối. Frozen request phải dùng executor `agent-provider:deepseek-harness / skilltree-authoring`, profile `harness-profile:adlc-skilltree/0.1.0` và required `vai-adlc-skilltree@0.1.0` lock. Current H4 coding profiles không có quyền gọi bridge. Tool/metadata không được tự chọn owner, file path hoặc API URL.

#### Store và giới hạn

Default: `adlc-flow/data/adlc-contracts.sqlite3`; deployment override `ADLC_CONTRACT_DB_PATH`. Không expire/evict tự động. Empty/whitespace DB setting chỉ dùng in-memory cho test, **không dùng production**. Store kiểm tra lại canonical bytes/hash, ID/revision, graph và receipt bindings khi đọc; invalid data fail closed. Backup contract DB cùng run DB. H5A không chống được privileged administrator kiểm soát host/database.

- 256 KiB canonical content/document; 128 nodes; 256 edges; 512 revisions.
- 2,048 write-command receipts/document; 1,000 contracts; 32 MiB tổng canonical revision payloads.
- 32 KiB bridge request; 512 KiB client response; deadline 15 giây; list page tối đa 100.
- Title 200 characters, objective/description/criterion 4,000 characters; unsafe control/surrogate text bị chặn.
- Quota failure rollback, không xóa history. Tổng byte limit nói trên là content payloads, không phải toàn bộ SQLite file size.

Canonical hash tính trên full validated JSON với explicit defaults/nulls, sorted keys, compact separators, UTF-8/non-ASCII, không NaN. JSON được pretty-print hay Markdown summary **không** có cùng byte hash. Không follow/import workspace path do agent đưa ra. Declared allowlist chỉ là dữ liệu; chưa thay deployment H4 capture policy.

#### SDK compatibility và template provenance

Đã đọc mentor template từ [vai-skilltree trên Gitea](http://117.5.151.111:9981/admin/vai-skilltree), commit `2fc49b6733df2dcd1911eb21274ed4e5228bdce9`, package 1.9.0. Source thật có 12 registered tools, khác count trong README/log. H5A lấy ý tưởng semantic primitives + separate layout, không copy store/global broadcast/latest-session fallback/arbitrary file scanning/editable viewer behavior.

`contractPluginTemplate.md` trước đây chứa parallel-agent guide; đã giữ lại dưới `agent-harness-server/templates/references/dispatching-parallel-agents.md` và thay bằng project contract template.

SDK đang cài: DSH tools 0.1.5-rc.3, raw JSON Schema subset không hỗ trợ `$defs`/`$ref`, bounds/format/pattern hay `anyOf`. Adapter inline local definitions, chỉ chuyển disjoint nullable unions sang `oneOf`, giữ closed object/type/required/enums. Bounds/format/pattern được giữ thành model-visible annotation và **full ADLC validator vẫn enforce**. Unknown/external/recursive schema constructs fail; không đổi canonical schemas để làm SDK bỏ qua policy. Đã đối chiếu cả sáu declaration với `assertObjectJsonSchema`/`assertSupportedJsonSchema` trong SDK cài thật, bằng process kiểm tra riêng; không bật plugin/register vào live service và không tạo agent.

### Proof/verification

Không cần Docker, provider key, login token hay model thật cho test suite:

```powershell
cd D:\coding\ADLC
.\adlc-flow\scripts\test-adlc-contracts.ps1
# Bao gồm các regression ADLC/Harness hiện tại:
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression
# H5B shared UI / Run Detail checks và installed SDK boundary (Docker container đã có):
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression -Frontend -InstalledSdk
```

Script dùng existing `adlc-flow/.venv`, Node.js, fresh temporary DB/scratch dưới workspace, disable live executors, restore process environment và chỉ xóa exact validated scratch directory của nó. Test Node → Python dùng bytes/HMAC của client thật và ASGI API; fake transport, không gọi model. Script cũng check published H4 plugin locks ở chế độ read-only, không resync recipe lịch sử. Check schema riêng, từ `adlc-flow`:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_adlc_contract_document_schemas --check
```

Validation record (2026-10-07):

- Regression ADLC/API: **309 ĐẠT**; Harness: **88 ĐẠT** (79 existing + 9 Skilltree).
- Final focused H5A: **49 backend/API ĐẠT, 9 plugin ĐẠT**, gồm strict float-revision rejection được thêm sau regression snapshot ở trên.
- Schema parity, Ruff trên new/integration files và root/nested Git whitespace checks: đạt.
- Cả sáu tool input/output declarations được SDK cài thật chấp nhận; không tạo agent.
- Published H4 lock consumers: `stale: []`, `updated: false`.
- Venv hiện tại phát hai warning về config `timeout`/`timeout_method` chưa được nhận diện; không đổi/cài thêm dependency. Không chạy live model E2E hoặc shared UI test ở H5A snapshot này.
- H5B final record (2026-10-08): **323 backend/API, 102 Harness và 41 frontend tests ĐẠT**; installed SDK six-tool boundary và H4/H5B lock checks đạt. Full-frontend baseline type errors và browser sandbox visual-check limitation được ghi tại chặng H5B của tài liệu này.

Các test này cover: writer IDs/full text, graph/bounds, schema parity/examples, replay/conflict, edit invalidation, approval/fork immutability, multi-writer races, tamper detection, persistence without patch TTL, owner/session/attempt isolation, explicit human login, signed UTF-8 boundary, transport bounds/error safety và SDK input projection.

### Rollout

Root `.env.example` chỉ thêm tùy chọn **disabled**. Actual `.env`, tokens, login policy, current model/profile, running services và current recipes chưa đổi. Plugin mới `disabled: true` trong `plugins/patch.yml`; required lock của bốn H4 plugins giữ nguyên. Không cần restart live stack để chạy tests này.

Authoring profile H5B đã có; operator cấu hình backend feature/store/login, independent tool secret ở ADLC và Harness vault, và deployment-owned `ADLC_CONTRACT_BASE_URL`/`bridgeBaseUrl`. Root `.env` không tự nạp Harness vault hoặc tự forward mọi biến vào Docker/sandbox; environment plumbing/activation phải kiểm tra rõ ở rollout, không chỉ restart container cũ. Không chỉ bỏ `disabled: true` trên coding preset. Không load mentor `vai-skilltree` cùng plugin mới vì trùng tool names.

- **H5B** (đã triển khai, activation off): shared renderer với exact schema/ref, owner-scoped reads, JSON fallback; dedicated tool-restricted authoring recipe/profile, unchanged H4 bytes và new exact plugin locks. Chưa có live model/visual sign-off.
- **H5C** (đã triển khai, activation off): exact approved reference trong frozen plan/run, guarded repository tools, supported paths/actions và registered predicates/evidence. Không certify mọi câu chữ hoặc semantic correctness. Xem chặng H5C.
- **H5D** (implementation/offline campaign delivered; live sign-off pending): exact verification checkpoint/reconciliation, owner-scoped retry control, process-crash/callback/ADLC-restart campaign và bounded live runner. Chỉ `my-codex / cx/gpt-5.6-luna` khi test model. Xem chặng H5D.

Tài nguyên quy chuẩn: [schemas/API models](../../adlc-contracts/documents/v0.1/README.md), [ADR 0012](../adr/0012-tool-authored-approved-contract-documents.md); plugin template và agent guide nằm trong submodule `agent-harness-server`: `agent-harness-server/contractPluginTemplate.md`, `agent-harness-server/deepseek-harness/plugins/vai-adlc-skilltree/skills/vai-adlc-skilltree/SKILL.md`.

---

## Milestone H5B — Shared Skilltree viewer and six-tool authoring

> Ngày: 2026-10-08. **Đã triển khai, opt-in; chưa activate trên stack đang chạy.** Tiếp nối H5A và [ADR 0012](../adr/0012-tool-authored-approved-contract-documents.md). H5C đã thêm separate opt-in guarded execution/predicate evidence; H5D (live E2E/recovery campaign) còn lại. H5B authoring tự nó vẫn không enforce coding policy/criteria.
>
> **Trạng thái: ✅** (opt-in; activation off)

### Kết quả của slice

- ADLC Run Detail có graph Skilltree, scope, declared constraints, full node/criteria details, JSON/receipts, chọn historical revision và tải canonical JSON.
- Human owner approve **đúng reference đang xem** sau khi xác nhận review; approved content vẫn bị khóa. Human fork tạo draft mới, giữ nguyên original/receipt. Không có editor/import JSON trong UI này.
- Harness có tab **Contracts**. Nó embed cùng ADLC component ở protected route `/contracts/harness/{session_id}/`, read-only và owner/session-scoped; không giữ một bản JSON thứ hai.
- Package mới `skilltree-authoring-deepseek-harness@0.1.0` dùng dedicated profile `harness-profile:adlc-skilltree/0.1.0`, operation `skilltree-authoring`, **MANUAL** submission.
- Authoring driver chỉ cho sáu `skilltree_*` tools, pin `my-codex / cx/gpt-5.6-luna`, không parsing assistant JSON thành kết quả. Handoff reference lấy từ signed read của ADLC writer.
- H4 coding endpoint, published plugin bytes/locks và artifact retention không bị thay thế.

**Approved roadmap không đồng nghĩa task đã thực hiện đúng roadmap.** `criteria_executed=false` và `execution_policy_enforced=false` được ghi rõ trong UI/result. Human contract approval, agent interaction approval, accepted execution plan và **Submit result** là các quyết định riêng. Approve/fork không tự resume, submit hay complete run.

### Thiết kế chính

#### Component và authority

| Component | Quyền và dữ liệu |
| --- | --- |
| ADLC writer/store (H5A) | Canonical content, revision, ownership, validation, exact human approval/fork. |
| `vai-adlc-skilltree@0.1.0` | Sáu typed commands; session lấy từ execution context, không phải model argument. |
| `vai-adlc-contract-authoring@0.1.0` | Restricted agent scope, separate Harness runtime/API, authoritative handoff verifier. |
| ADLC `ContractViewer` / `ContractPanel` | Shared projection; review actions chỉ ở Run Detail, explicit human login. |
| `vai-adlc-contract-ui@0.1.0` | Native sidebar adapter, public frontend URL và exact selected session; read-only iframe. |

Renderer descriptor ở `adlc-contracts/renderers/skilltree/0.1/manifest.json` là resource riêng. Không sửa `renderer_available=false` trong published H5A producer manifest: producer không bundle UI; renderer nằm ở host ADLC. Unknown schema/renderer, malformed graph hoặc mismatched receipt fallback sang escaped JSON và không cho review actions. Layout không được ghi vào semantic document. Full criteria luôn đọc được, không suy ra progress/test success từ graph hoặc label màu.

ADLC panel poll có navigation/race fences. Historical revisions và failed/stale refresh không có approve/fork. Review confirmation gắn exact schema/ID/revision/digest; head đổi thì phải review lại. Idempotency key giữ ổn định cho identical retry; backend vẫn là authority trước mọi write.

#### Authoring boundary

Driver tạo unpublished agent với SDK setup hook, chuyển tool presentation sang **native**, restrict đúng sáu names, và thêm dispatch guard kiểm tra agent identity cùng identity của trusted tool definitions. Setup commit kiểm tra lại exact toolset trước khi agent được dùng; SDK bỏ qua setup/missing API thì dispose handle và fail closed **trước model follow-up**. Guard vẫn chặn scoped tool đăng ký sau restrict, tool shadowing và `run_code`; không sửa global coding tools của những session khác. Standard preset chỉ là SDK bootstrap, không phải coding capability grant.

Agent phải tạo đúng một draft bằng tool loop, thêm nodes/dependencies và validate declarations. Driver yêu cầu `turn/end` có reason `completed`; failed/aborted/unknown turns không trở thành successful handoff. Plain assistant text, kể cả forged reference/`approved:true`, không phải result. Reader resolve exact active/current registered attempt, kiểm tra full correlation, require đúng một current head VALIDATED/APPROVED. Không có latest/default/caller-selected-contract fallback. Verifier reread writer và so exact reference; nó **không** chạy acceptance tests.

Result schema riêng: `adlc://schemas/skilltree-authoring-result/0.1`, resource `adlc-contracts/documents/authoring/v0.1/skilltree-authoring-result.schema.json`. Output slot `contract_reference` dùng `adlc://schemas/contract-reference/0.1`. Schema đóng, summary cố định, status chỉ VALIDATED/APPROVED và hai execution flags luôn false. H5A document/tool schemas và frozen base execution schemas không đổi.

#### Endpoint và authentication additions

| Endpoint | Boundary |
| --- | --- |
| ADLC `GET /api/v1/adlc/contract-viewer` | Active user, capabilities không chứa secrets; human action availability chỉ là UI hint. |
| ADLC `GET /api/v1/adlc/harness-sessions/{id}/contracts` | Run owner + exact full session/attempt binding, filter trước pagination; đọc được completed attempts. |
| ADLC `POST /api/v1/adlc/contract-authoring-result` | Signed purpose-bound read; current active authoring attempt only, không có approve/write. |
| Harness `/api/v1/adlc-harness-authoring/*` | New opt-in runtime; existing Harness API bearer token, fixed MANUAL authoring profile only. |
| Harness `/api/v1/adlc-harness/*` | Existing H4 behavior và state directory giữ nguyên. |

Signed read dùng headers/timestamp tolerance như writer, nhưng domain riêng `adlc-contract-authoring-v1\n` thay vì writer `adlc-contract-tools-v1\n`. Read signatures không gọi writer được và ngược lại. Transport không follow redirects; response/timeout bounds và fixed secret-free errors vẫn áp dụng. Bearer/HMAC/model/callback key **không phải quyền human approval**.

ADLC client route session creation theo frozen profile tới một trong hai fixed API roots. Sau backend restart, GET probe H4 rồi authoring **chỉ khi H4 trả 404**; không fallback trên 401/5xx. Submit/respond/cancel dùng root đã resolve và không replay write sang endpoint khác. Đây là recovery mechanism được test offline, chưa phải kết luận H5D live E2E đã đạt.

#### Plugin locks và rollout mặc định

Dedicated recipe và `deepseek-harness/plugins/adlc-skilltree.plugin-lock.json` pin cùng năm exact versions/byte hashes: old driver `0.2.0`, old runtime `0.3.0`, Skilltree `0.1.0`, authoring `0.1.0`, UI `0.1.0`. Runtime kiểm tra installed bytes trước execution; plugin lock mismatch fail closed. Lock file để ngoài plugin directories để không self-hash. H4 lock consumers không resync. Sau publication, thay implementation bytes phải bump version và tạo recipe mới, không rewrite lock history.

Ba H5 rows vẫn `disabled: true` trong `plugins/patch.yml`; actual `.env`, login policy, vault, live provider/profile, running services và production DB không đổi trong slice này.

#### Operator setup — chưa được thực hiện tự động

1. Backup run/contract DB; dùng durable `ADLC_CONTRACT_DB_PATH` nếu đổi location. Không dùng blank/in-memory DB setting cho deployment.
2. Backend cần cả `ADLC_HARNESS_ENABLED=true`, `ADLC_CONTRACTS_ENABLED=true`, `ADLC_CONTRACT_AUTHORING_ENABLED=true` để package visible/authorized. Human approval cần **`LANGFLOW_AUTO_LOGIN=false`** và explicit active owner login. Việc đổi login ảnh hưởng cả deployment; operator phải chọn/cấu hình, không dùng API key để bypass.
3. Tạo independent `ADLC_CONTRACT_TOOL_SECRET` (tối thiểu 32 UTF-8 bytes) và cấu hình giống nhau ở ADLC backend và Harness vault/explicit container environment. Không reuse callback/model secret. Không đưa secret vào workflow requirement, public URL hoặc browser config.
4. Harness bridge `ADLC_CONTRACT_BASE_URL` là URL backend nhìn từ container, ví dụ `http://host.docker.internal:7860`; cả Skilltree/authoring rows có `allowInsecureHttp: true` cho local Docker-host setup. Production dùng HTTPS, không wildcard destinations. `ADLC_CONTRACT_UI_URL` là **public frontend URL**, ví dụ `http://localhost:3000`, không phải backend bridge URL. Dùng nhất quán localhost hoặc 127.0.0.1 khi sign in để đúng cookie origin.
5. Giữ existing `ADLC_HARNESS_API_TOKEN`, `ADLC_HARNESS_CALLBACK_URL` và `ADLC_HARNESS_CALLBACK_SECRET` của H4 matching giữa hai services; authoring runtime reuse vault resolution. Compose chỉ forward explicit H5 variables, không forward toàn bộ root `.env`/model keys.
6. Enable ba rows `vai-adlc-skilltree`, `vai-adlc-contract-authoring`, `vai-adlc-contract-ui` trong patch. Không enable Skilltree trên existing coding recipes hoặc load mentor `vai-skilltree` trùng tool names. `ADLC_CONTRACT_AUTHORING_ENABLED=true` phải có trong **Harness process environment**, không chỉ vault.
7. Restart backend/frontend theo startup workflow hiện tại. Nếu lấy H5 values từ root `.env`, recreate Harness bằng lệnh bên dưới sau khi operator điền/cấu hình keys; restart container cũ không thay environment:

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
docker compose --env-file ../../.env up -d --build
```

Existing model route phải có `my-codex / cx/gpt-5.6-luna`; slice này không tự thay provider hoặc gọi model khác. Authenticated `/api/v1/adlc-harness-authoring/health` và `/plugins` giúp operator kiểm tra new runtime/integrity. H4 health/inventory không thay cho new authoring readiness.

##### Browser embedding

Harness adapter inject **chỉ public frontend base URL**, không token/HMAC/vault credentials. Iframe sandbox `allow-scripts allow-same-origin`, no-referrer, không postMessage writes, import, forms, top-navigation hoặc popups. Login/review ở ADLC tab riêng qua link `Open / sign in to ADLC`. Không tự automate login/approval. Owner read ở backend vẫn enforce dù UI button bị sửa. Nếu reverse proxy có CSP/frame-ancestors hoặc browser chặn iframe cookies, mở link trong ADLC tab riêng; deployment có thể cấu hình **exact trusted Harness origin**, không wildcard, không tắt authentication hoặc bỏ iframe sandbox để chạy demo. Viewer không có independent permission bypass.

#### Manual authoring test sau khi operator activate

1. Sign in ADLC bằng owner; tạo Blueprint với package `skilltree-authoring-deepseek-harness@0.1.0`.
2. Requirement mô tả objective/scope/constraints/milestones/criteria của **roadmap**, không yêu cầu coding hay chạy test. Ví dụ: "Tạo roadmap 2 milestones cho cập nhật tài liệu, ngoài scope là commit/push/deploy; mỗi TASK có tiêu chí HUMAN rõ ràng. Dùng tools tạo và validate một contract, chưa thực thi roadmap."
3. Compile → Accept plan → Start run. Agent loop sáu tools; xem draft/current revision tại ADLC Run Detail hoặc Harness Contracts tab (same content/reference).
4. Sau declaration validation, review exact revision/digest ở ADLC, check review confirmation và Approve. Approval không tự Submit result. Có thể fork approved contract; original phải còn nguyên.
5. Run đạt `READY_FOR_SUBMISSION` → Submit riêng. SUCCEEDED ở authoring task chỉ nghĩa validated roadmap đã handoff qua callback, **không** nghĩa implementation/criteria đã executed.
6. Mở lại run sau Harness session cleanup: content/history/receipt vẫn nằm ở ADLC. Full restart/disconnect/callback recovery campaign và live model E2E sẽ được xác nhận ở H5D.

### Proof/verification

```powershell
cd D:\coding\ADLC
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression -Frontend
# Có existing Harness Docker container; kiểm tra SDK trong process riêng, không tạo agent:
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression -Frontend -InstalledSdk
```

Script dùng isolated DB/scratch, disable live executors, restore process environment và kiểm tra locks read-only. Không gọi model, activate plugin hay đọc production DB. `-Frontend` cần existing frontend node_modules; `-InstalledSdk` cần Docker/container đã có, không build/download/restart.

Validation record (2026-10-08):

- Full isolated ADLC/backend/API regression: **323 ĐẠT**, gồm actual resolution của authoring recipe.
- Harness regression: **102 ĐẠT** (79 existing + 9 Skilltree + 10 authoring + 4 UI adapter).
- Frontend: **41 ĐẠT / 5 suites**, gồm shared viewer/panel và toàn bộ Run Detail suites.
- Installed DSH SDK `0.1.5-rc.3`: six tools visible, five non-authoring dispatch paths denied, allowed writer call executed; **không tạo agent/model turn**.
- Generated schema parity, Ruff và Biome trên H5B-owned files: đạt.
- Root/nested tracked Git whitespace checks: đạt; H4 locks `stale: [] / updated: false`, H5B locks `stale: [] / initialized: false` ở final read-only check.
- Focused six-file frontend typecheck: **0 contract errors**; 13 unrelated imported-dependency errors. Full-project frontend typecheck vẫn có unrelated baseline errors; focused check không chứng minh toàn app đã sạch.
- Existing venv có hai pytest config warnings (`timeout`, `timeout_method`), không cài/thay dependencies để che warnings.

Không chạy live model E2E. Desktop browser preview bị sandbox-helper startup error kể cả bounded recovery; không download browser hoặc relax security để bypass. Chưa có visual/manual live sign-off. Temporary fixture server đã dừng; operator có thể chạy preview: `.\node_modules\.bin\vite.cmd --config tests/contract-viewer-preview/vite.config.mjs` từ `adlc-flow/frontend`, rồi mở `http://127.0.0.1:4177/tests/contract-viewer-preview/index.html`. Links ADLC/Harness/light theme dùng fixture và actual renderer/native adapter, không phải production contract. Server chỉ bind loopback, dùng riêng preview env/cache; đóng preview sau khi xem.

### Hạn chế còn lại

H5B authoring tự nó vẫn không enforce coding policy/criteria. Chặng kế tiếp H5C: pin approved reference vào accepted plan/new coding run; reject missing/stale/mismatched digest; map supported declared scope/paths/actions vào actual tool/OS policy; verifier thu evidence gắn exact node/criterion/reference. Không hứa enforce mọi natural-language sentence bằng prompt. Unsupported policies/verifier refs phải fail closed hoặc được human xử lý rõ ràng, không giả định accepted roadmap đã được thực hiện.

Tham khảo: [ADR 0013](../adr/0013-shared-contract-viewer-and-restricted-authoring.md); contract plugin template trong submodule: `agent-harness-server/contractPluginTemplate.md`.

---

## Milestone H5C — Approved contract → guarded execution → machine evidence

> Ngày: 2026-10-08. Slice opt-in; activation vẫn tắt. Tiếp nối H5A, H5B và [ADR 0014](../adr/0014-approved-contract-execution-policy-and-evidence.md).
>
> **Trạng thái: ✅** (opt-in; activation off)

### Kết quả

Recipe mới `coding-agent-contract-harness@0.1.0` dùng profile `harness-profile:adlc-contract-coding/0.1.0`, operation `contract-coding`, **MANUAL** submission, pin `my-codex / cx/gpt-5.6-luna`. Plugin `vai-adlc-contract-execution@0.1.0` có runtime/API/state riêng; H4/H5A/H5B published bytes và recipe locks không bị resync.

```text
Human-approved exact reference
  → Blueprint configuration → compile/accept/new-run checks
  → registered current attempt → signed immutable policy binding
  → isolated clone + 3/4 guarded repository tools
  → freeze/drain → actual source-patch capture → registered predicates
  → immutable ADLC proof + shared read-only evidence UI
  → human reviews/Submit → signed callback → independent coordinator gate
```

`approved_contract_ref` chứa đúng bốn trường schema/ID/revision/digest, không phải JSON document import. Nguồn có thể thuộc một authoring run khác của **cùng owner**. Backend kiểm tra exact approved receipt/content, đưa ref vào frozen resolved configuration/digest, rồi kiểm tra lại trước model và khi accept kết quả. Null default chỉ để package registry biểu diễn giai đoạn chưa cấu hình; null/absent **không compile được**. Không có latest/default/model-selected-contract fallback. Human fork không thu hồi ref cũ; draft kế tiếp cần approval độc lập và plan/run mới nếu muốn đổi binding.

### Thiết kế chính

#### Policy thực sự được enforce

| Tool | Giới hạn |
| --- | --- |
| `contract_get_context` | Đọc immutable approved document/reference và policy; không approve/fork/edit contract. |
| `contract_list_files` | Tối đa 128 in-scope paths; vượt giới hạn thì fail, không trả danh sách bị cắt. |
| `contract_read_file` | Một file UTF-8 text ≤64 KiB, trả nội dung và SHA256. |
| `contract_write_file` | Atomic create/replace text ≤64 KiB, previous SHA256 hoặc null cho file mới; optimistic, serialized. |

Read-only chỉ expose ba tools đầu và vẫn reject write khi dispatch. Bất kể declaration nào, **commit, push, deploy, network, shell, subagent, delete** luôn bị chặn. Tool schemas dùng closed-object/single-type/`oneOf` subset của SDK cài thật; dispatch tự enforce bounds/digest, không dựa vào unsupported schema keywords. Setup/commit và monotonic guard check agent identity + original tool definition; late/shadowed tools và `run_code` bị từ chối. Missing SDK setup không bắt đầu model follow-up. Native ask-user tools không nằm trong capability set: human review/Submit ở ADLC là HITL của recipe này. Existing interaction bridge vẫn xử lý host-native requests của session, không nới tool allowlist.

Path grammar chỉ gồm `*`, exact repo-relative file, hoặc directory prefix kết thúc một `/`; không phải glob. Ví dụ `demo.json`, `docs/`, `src/`. `src/*.json`, traversal, absolute/drive/backslash paths đều unsupported. Ngay cả `*` vẫn deny known sensitive names/extensions (`.git`, `.env`/`.env.*`, credentials, keys, VPN files…), Windows reserved/trailing-dot/space aliases, symlinks/junctions/hardlinks, binary/NUL, invalid UTF-8 và oversized text. Ignored writes bị deny. Capture check write ledger để `.gitignore` edit sau đó không giấu được earlier tool writes; no-op/reverted writes không cần nằm trong final patch.

Source mount read-only, local clone từ **committed** content, không fetch/push và không chép dirty source changes. Tool context được freeze/drain trước capture, late writes bị reject. Pinned Git collector tạo artifact ID, checksum của actual bytes, base commit và paths; agent không được tự khai báo các trường này. Capture cũng reject thay đổi ngoài approved paths hoặc read-only policy.

#### Machine predicates, không phải "mọi câu chữ đã đúng"

| `verifier_ref` | `verification` | Ý nghĩa cố định |
| --- | --- | --- |
| `verifier:contract-source-patch/0.1.0` | ARTIFACT | Accepted capture có ít nhất một changed file. |
| `verifier:contract-no-changes/0.1.0` | ARTIFACT | Accepted capture không có changed file. |
| `verifier:contract-json-syntax/0.1.0` | TEST | Có changed JSON và mọi changed JSON parse thành công. |

Mỗi criterion được key bởi node ID, criterion index và versioned verifier ref. Không suy ra completion từ label/assistant JSON/approval. TEST ở đây **không** chạy pytest/npm/arbitrary commands; description không phải custom test. HUMAN/unknown verifiers, verification-kind mismatch, unknown action names, contradictory no-change/change predicates, read-only+required changes đều fail **trước clone/model**; không silently skip hoặc đánh dấu passed.

Để tạo contract dùng được, H5A six-tool loop phải khai báo supported refs. Ví dụ một TASK:

```json
{
  "title": "Edit approved demo.json",
  "acceptance_criteria": [
    {"description": "Captured source has changes", "verification": "ARTIFACT", "verifier_ref": "verifier:contract-source-patch/0.1.0"},
    {"description": "Changed JSON parses", "verification": "TEST", "verifier_ref": "verifier:contract-json-syntax/0.1.0"}
  ]
}
```

Init constraints `{"read_only":false,"allowed_paths":["demo.json"],"forbidden_actions":["commit","push"]}`. Read-only demo dùng `read_only:true` và chỉ `contract-no-changes` ARTIFACT criteria. Default HUMAN criterion từ H5B không tự trở thành machine check: fork để sửa criteria hoặc init draft mới nếu cần đổi immutable scope/constraints, validate rồi human approve lại. Không sửa original approved document.

Proof ghi `criteria_executed=true`, `execution_policy_enforced=true`, **`natural_language_enforced=false`**. Scope/objective/in-out scope descriptions vẫn là hướng dẫn human/agent. H5C không chứng minh semantic correctness, execution chronology của DAG, arbitrary test/security completeness hay mọi lời hứa tự nhiên đã được thực hiện. Human contract approval, plan acceptance, interaction approval và Submit là các quyết định khác nhau.

#### Authority, persistence và UI

ADLC signed `POST /api/v1/adlc/contract-execution` nhận closed bind/report envelope, không cho caller chọn owner/ref/plan/workspace. Nó resolve current active registered session/attempt, trusted frozen request và exact source. Purpose `adlc-contract-execution-v1\n` dùng cùng independent tool secret/timestamp format nhưng không interchangeable với writer/authoring purposes. Command ≤32 KiB, response ≤512 KiB, redirect forbidden, fixed secret-free errors.

ADLC execution DB mặc định `adlc-flow/data/adlc-contract-executions.sqlite3`, override `ADLC_CONTRACT_EXECUTION_DB_PATH`. Immutable attempt binding/proof có canonical SHA checks, identical retry replay, conflicting binding/evidence bị reject. No TTL/eviction; 1,000 records/64 MiB payload bound, quota fail closed. Backup cùng contract, run, attempt và Harness state; không xóa DB để chữa conflict.

Proof gắn exact ref/policy digest/accepted plan + resolved digest/full correlation với real artifact ID/checksum, base commit, changed paths và all criterion checks. Submit reread proof; ADLC coordinator kiểm tra lại successful TaskResult với stored proof và actual artifact metadata. Thiếu/forged/stale proof không chuyển task SUCCEEDED; failure result không được quảng cáo thành success. H4 callback envelope/history vẫn giữ hành vi generic cũ.

Owner-only historical APIs (base `ADLC_CONTRACTS_ENABLED` vẫn cần bật):

- `GET /api/v1/adlc/runs/{id}/contract-executions?limit=100&offset=0`.
- `GET /api/v1/adlc/harness-sessions/{id}/contract-executions` — exact full session/attempt filter.

Đọc được khi C execution flag tắt hoặc run đã hoàn tất. Response `no-store`; reread source approval và policy digest. Run Detail và Harness Contracts protected route dùng cùng `ContractExecutionPanel`: exact binding/source graph, paths/actions, artifact/base/checksum, per-criterion machine evidence và explicit semantic caveat. Không có approve/fork/Submit/write controls trong evidence panel. Malformed/mismatched/out-of-scope proof fallback escaped JSON, không completion badge; stale refresh/navigation không dùng lại evidence của scope cũ. H5B authored-document session list không đổi để lẫn source của execution run vào authoring scope.

Evidence không theo patch TTL. Patch **bytes** vẫn ≤512 KiB/128 files, 24-hour retention như H4; historical proof không có nghĩa bytes còn download được. Clone cleanup vẫn do unchanged collector/runtime quản lý.

#### Rollout thủ công — chưa thực hiện trên stack hiện tại

1. Backup state và chọn committed demo Git repository; existing read-only `/app/artifact-source` mount lấy từ `ADLC_HARNESS_SOURCE_REPO`. Không dùng dirty source hoặc đổi mount trên một run đang chạy.
2. Backend bật `ADLC_HARNESS_ENABLED=true`, `ADLC_CONTRACTS_ENABLED=true`, `ADLC_CONTRACT_EXECUTION_ENABLED=true`. Human approve/fork cần `LANGFLOW_AUTO_LOGIN=false` và explicit owner login. Authoring flag chỉ cần nếu dùng H5B model authoring; human tools có thể tạo contract trước.
3. Dùng independent random `ADLC_CONTRACT_TOOL_SECRET` ≥32 UTF-8 bytes ở ADLC và Harness vault; giữ existing Harness bearer/callback credentials. Set deployment-owned `ADLC_CONTRACT_BASE_URL`/`bridgeBaseUrl`. Không đưa model keys vào Blueprint/reference/UI. Non-local transport cần HTTPS; local Docker-host HTTP phải opt-in.
4. Enable **new** `vai-adlc-contract-execution` row trong Harness `plugins/patch.yml`; C flag phải được forward vào container. Muốn Harness tab thì enable existing `vai-adlc-contract-ui`; muốn model authoring thì follow separate H5B rows. Root `.env` không tự nạp vault hoặc tự forward mọi biến. Compose đã có explicit C forwarding; operator có thể dùng `docker compose --env-file ../../.env up -d --build` để recreate theo root settings. Các thay đổi activation này chưa được agent thực hiện.
5. Kiểm tra new `/api/v1/adlc-harness-contract/health` và `/plugins` bằng existing bearer; readiness phải true, exact four-plugin lock phải khớp. Không resync historical locks để che lỗi.
6. Validate/human approve source contract có supported predicates. Copy **reference** từ server read projection (JSON/receipts trong viewer), không hash một pretty-printed document. Chọn recipe mới trong Blueprint stage, paste four-field JSON vào `approved_contract_ref (JSON)`. UI chặn malformed input; backend vẫn check ownership/approval. Có thể dùng API với `configuration_overrides.approved_contract_ref` là object tương tự.
7. Compile → Accept plan → Start new run. Xem bound roadmap/policy/evidence và actual captured patch trong Run Detail; kiểm tra caveat/criteria trước **Submit**. Source repository không được commit/push/apply/deploy tự động.

Actual `.env`, provider keys, login policy, live services và user data không bị thay đổi trong slice này.

### Proof/verification

Offline regression entry point:

```powershell
cd D:\coding\ADLC
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression -Frontend
```

Script override live flags/DB paths cho process test, dùng fresh scratch dưới workspace và restore environment; không load `.env`, không gọi model, không activate plugin. `-InstalledSdk` cần existing running container. Nếu stack đang tắt, kiểm tra C SDK riêng bằng **inspected existing local image ID**, không khởi động services:

```powershell
cd D:\coding\ADLC\agent-harness-server\deepseek-harness
node scripts/check-adlc-contract-execution-sdk.mjs --image <inspected-sha256-image-id>
```

Checker dùng read-only disposable container, network none, no workspace/vault mounts, no agent/model. Nó assert actual SDK schemas (including nullable previous digest), native 3/4-tool masks và dispatch/frozen/late-tool guards. Published H4/H5B/C lock checkers chạy read-only `--check`; `--initialize-h5c` chỉ dành new empty release trước publication.

Final validation (2026-10-08), sau fresh-process resume guard và final prerelease lock:

- **375 backend/API, 120 Harness và 70 frontend tests ĐẠT**; bao gồm các regression ADLC/H4/H5A/H5B trước đó.
- C plugin đóng góp 18 isolated policy/tool/real-Git/runtime tests, gồm write-ledger/ignore-rule và restart boundaries.
- Installed SDK actual native declarations/nullable digest và identity/frozen/late-tool guards đạt; không tạo agent/model.
- H5A/H5B/C schema parity, backend Ruff và root/nested Git whitespace checks đạt.
- Focused frontend type check: 12 files, 0 owned-file errors. Dependency graph rộng hơn có 14 typing issues hiện tồn tại trong các file shared UI/i18n/icons/input/message-store, không bị slice này thay đổi; đây **không** phải tuyên bố full-frontend type-pass.
- Existing venv phát hai pytest warning cho `timeout`/`timeout_method` chưa được nhận diện; không đổi dependencies.
- Read-only H4/H5B/C lock checks: `stale: []`. Final new C plugin digest: `sha256:353d8ac60417dd69c550059cb8acdd14171d096608feb7d0d049645c56de3231`.

Không tuyên bố live model E2E, service activation hay browser visual sign-off nào cho H5C.

### Hạn chế còn lại — dẫn hướng H5D

Opt-in recipe mới `0.2.0`/recovery companion nay thực hiện checkpointed verification window và offline campaign (xem chặng H5D). Các giới hạn sau là hành vi lịch sử đúng của H5C `0.1.0`; release đó không bị viết lại: full restart/reconciliation/recovery campaign, live owner-login/viewer/Submit delivery sign-off và operational cleanup còn thiếu. Fresh process không resume waiting execution nếu đã mất guarded write ledger: `CONTRACT_EXECUTION_RECOVERY_REQUIRED` trước bind/clone/model; in-process continuation giữ ledger vẫn được phép. Crash sau khi ADLC đã lưu proof nhưng Harness chưa lưu candidate có thể tạo evidence conflict khi capture lại: fail closed, explicit new attempt; không tự rerun model, không xóa/reset proof. Chưa có automatic cross-store completion. Provider/plugin/host admin hoặc direct DB/checkout/process access nằm ngoài tool capability boundary.

---

## Milestone H5D — Exact verification recovery and live sign-off campaign

> Ngày: 2026-10-08 (Asia/Saigon). **Implementation/offline campaign đã bàn giao; live activation, real-owner/browser/model/callback sign-off chưa hoàn thành.** Xây trên H5C và [ADR 0015](../adr/0015-exact-contract-verification-recovery.md).
>
> **Trạng thái: ✅ (offline); live sign-off còn pending**

### Mục tiêu và điều gì đã thay đổi

Recipe mới `coding-agent-contract-harness@0.2.0` và companion plugin `vai-adlc-contract-recovery@0.1.0`. H5C `0.1.0` và mọi bundle/recipe/lock của H4/H5A/H5B giữ nguyên. Five-plugin lock gồm exact original H5C bundle cộng companion mới. Boundary approved-reference/policy/schema/three-or-four-tool của H5C được tái sử dụng; không thêm agent tools, permissions, predicates hay semantic guarantees mới.

Fixed endpoint `/api/v1/adlc-harness-contract-recovery`; state `/app/data/adlc-contract-recovery`; clones `/app/workspace/adlc-contract-recovery-runs`. Coding profile/policy vẫn là exact version của H5C; `recovery_ref` và required plugin lock của frozen recipe chọn separate runtime này. Chỉ **`my-codex / cx/gpt-5.6-luna`** được dùng cho campaign này. Không có provider/model fallback.

Kernel lưu một verification checkpoint đầy đủ, bounded, có checksum **trước** external ADLC proof request. Checkpoint chứa exact request digest, immutable binding, original capture bytes, artifact ID/checksum/base/paths, proof/check timestamp và prepared result. Khi restart, nó validate các link này, reread registered ADLC binding/proof và hoặc publish **identical** proof hoặc adopt identical proof đã persist. Nó không bao giờ recapture artifact khác hay gọi model.

Recovery vẫn dừng ở **MANUAL `READY_FOR_SUBMISSION`**. Contract approval, plan acceptance, verification recovery và result Submit vẫn là bốn thao tác riêng biệt. `natural_language_enforced=false`.

### Ma trận recovery

| Failure/state | Hành vi H5D |
| --- | --- |
| Crash sau checkpoint, trước ADLC proof | Publish proof gốc và restore candidate gốc; zero model calls. |
| Crash sau ADLC proof, trước Harness candidate | Adopt identical stored proof/capture/result; zero model calls. |
| Proof đã accepted nhưng acknowledgement mất trong verification | Giữ checkpoint/`VERIFYING`, không bịa failure hay tạo capture mới. |
| Bridge tạm offline lúc restart | Để `VERIFYING`; owner có thể retry exact checkpoint sau khi khôi phục kết nối. |
| Binding/proof khác nhau, checkpoint corrupt/thiếu hoặc patch hết hạn | Fixed failure result, không có accepted patch; review và explicit start attempt mới. Không bao giờ reset proof. |
| Restart ở ACCEPTED/PROVISIONING/RUNNING/WAITING_INTERACTION không có checkpoint hoàn tất | Yêu cầu explicit new attempt; cancel stale pending questions. Không automatic start/resume khi mất write ledger. |
| Original in-flight verification đang chạy | Reject reconciliation command racing; không fail hay gián đoạn verification đang hoạt động. |
| Candidate MANUAL ready tại restart | Preserve candidate và chờ human Submit. |
| Callback accepted nhưng acknowledgement mất | Outbox signed hiện có retry cùng delivery ID và exact result; ADLC deduplicate. |
| ADLC restart sau callback acceptance | Coordinator adopt original accepted result đúng một lần và independently recheck stored contract evidence. |
| History đã hoàn tất, Harness offline/cleaned up | Evidence/result owned bởi ADLC vẫn đọc được; expired patch bytes không hồi sinh. |

Startup thực hiện đúng một checkpoint reconciliation attempt, không phải unbounded model/recovery loop. Chỉ các lỗi transport/registration hẹp còn ở trạng thái pending; các lỗi khác là explicit. Runtime mới không bao giờ tự động replay kể cả một ACCEPTED interrupted session. Đây là chính sách bảo thủ có chủ đích cho recipe mới, không phải thay đổi hành vi H4/H5B.

### Owner controls

Run Detail hiển thị **Retry verification recovery** chỉ cho session VERIFYING có event mới nhất là `execution.reconciliation_waiting`. Nó không submit result, không trả lời question, không tạo attempt. Sau recovery, control **Submit verified result** hiện có vẫn tách rời và patch review vẫn áp dụng.

ADLC endpoint:

```text
POST /api/v1/adlc/runs/{run_id}/harness-sessions/{session_id}/reconcile-verification
{}
```

Owner authentication thông thường, current attempt/plan/frozen recovery version, full correlation và VERIFYING state được kiểm tra trước khi thực hiện single fixed Harness write. Closed command rỗng cấm caller tự chọn proof, owner, workspace, status hay replacement run. Reads/controls của owner sai vẫn nhận 404. Điều này khác với control reconciliation observer/callback mức run hiện có `/harness/reconcile`.

Harness operator endpoint (cần existing bearer): `POST {fixed-root}/sessions/{id}/reconcile` với `{}`. Session discovery dùng fixed GET endpoints và chỉ fall through trên 404; POST writes không bao giờ fall back.

### Offline campaign

Từ `D:\coding\ADLC`:

```powershell
.\adlc-flow\scripts\test-adlc-contracts.ps1 -Regression -Frontend
```

Fresh workspace-owned fixtures; live flags disabled, process environment được restore và scratch cleanup bị giới hạn trong exact validated temporary directory. Không cần model, real-owner credentials, thay đổi actual `.env` hay production DB. H5C schema parity và published historical locks được kiểm tra read-only.

Campaign Harness H5D bao gồm OS process termination thật trong hai children: sau durable checkpoint và sau synthetic ADLC proof save. Một process tươi thứ ba restore cùng candidate. Đây là **process-crash tests thật với synthetic proof service**, không phải real model hay storage-hardware/power-loss tests. Một bộ test thật khác với temporary Git/tools/capture/verifier/runtime edit một isolated clone và chứng minh source không bị chạm tới. Các test ADLC dùng actual SQLite stores, signed receiver validation/deduplication, reopened coordinator objects và independent final outcome gate. Owner authentication của API trong các fixture này được mock.

Final isolated regression ngày 2026-10-08:

| Check | Kết quả |
| --- | --- |
| ADLC backend/API regression | **396 ĐẠT**, gồm 21 H5D recovery checks. |
| Harness regression | **145 ĐẠT**, gồm 25 H5D checkpoint/crash/Git/runner checks. |
| Contract/Run Detail frontend | **74 ĐẠT** trên 9 suites, gồm 4 recovery UI checks. |
| Focused frontend types | 15 owned files, 0 owned errors; 15 unrelated dependency errors còn lại. Đây không phải sạch toàn frontend. |
| Schema parity H5A/H5B/H5C và historical locks H4/H5B/H5C | Đạt read-only; published bundles và recipes không đổi. |
| Deployment lock H5D recipe mới | Đạt; recovery digest `sha256:5d16929b6919c74233619ff6674f5d1bde1e12075c6242efa06ffc0a039bf139`. |
| Scoped lint/format | Ruff: 8 files đạt; Biome: 10 files đạt với existing console-summary warning có sẵn trong type-check script. |
| Installed Docker SDK / real model / real-owner/browser sign-off | Không chạy lại/không hoàn tất: Docker và services đang tắt; xem trạng thái môi trường bên dưới. |

Pytest vẫn báo hai existing unknown-configuration warnings cho `timeout` và `timeout_method`. Các rejected recovery checkpoints được verify là sống sót qua một restart khác mà không reset proof, recapture hay model call. Không có live model call nào được thực hiện. Temporary test fixtures và isolated preview đã được dọn; actual `.env`, login policy, provider credentials, source checkout và production stores không bị campaign này thay đổi.

### Live activation — các bước operator bắt buộc

Không hot-switch plugins/mounts khi run đang active. Backup các store run, attempt, contract, execution và artifact của ADLC cùng Harness state. Giữ một coordinator và một Harness writer cho mỗi state directory.

1. Có sẵn authenticated owner account trước khi đặt `LANGFLOW_AUTO_LOGIN=false`. Implementation không đổi actual `.env`, account settings hay keys. Không dán passwords/keys vào chat.
2. Bật backend `ADLC_HARNESS_ENABLED`, `ADLC_CONTRACTS_ENABLED`, `ADLC_CONTRACT_EXECUTION_ENABLED` và **mới** `ADLC_CONTRACT_RECOVERY_ENABLED=true`. Authoring flag riêng và chỉ cần cho H5B model authoring.
3. Giữ row H5C `vai-adlc-contract-execution` **disabled**; enable row mới `vai-adlc-contract-recovery`. Cả hai cài cùng guarded tool names và phải không chạy cùng lúc/hot-switch trong một session. Enable existing contract UI row cho shared Harness pane. H5B authoring/Skilltree rows là riêng.
4. Dùng Harness bearer/callback URL/callback secret bình thường và `ADLC_CONTRACT_TOOL_SECRET` ≥32-byte independent giữa hai phía. Giữ secrets trong configured environment/vault; không đặt keys vào Blueprint JSON. Đảm bảo local Docker-host transport và committed source mount `/app/artifact-source:ro` đúng. Compose explicitly forward recovery flag mới mặc định disabled; root `.env` không tự forward toàn bộ.
5. Start Docker Desktop và ADLC backend/frontend theo quy trình bình thường của project. Recreate Harness bằng `docker compose --env-file ../../.env up -d` nếu dùng root settings; không rebuild/pull dependency versions chỉ để vá lock mismatch. Sửa installed bytes/config thật thay vì resync historical locks.
6. Đọc `/health` và `/plugins` mới với existing Harness bearer: readiness và năm exact plugins phải đạt, với profile route đúng `my-codex / cx/gpt-5.6-luna`. Bước này cũng preflight committed source trước model turn.

### Bounded live runner

Script mới `agent-harness-server/deepseek-harness/scripts/run-adlc-contract-live-e2e.mjs` mặc định là **GET-only preflight**. Nó không bao giờ approve contract, accept plan, click Submit, đổi flags/keys hay restart services. Không log credentials. URLs giới hạn loopback; redirects forbidden; HTTP timeout 10 giây, bounded 2-MiB JSON responses và total observation timeout ≤15 phút. Các thay đổi trạng thái được in ra làm tiến trình.

Chạy từ Harness directory:

```powershell
node scripts/run-adlc-contract-live-e2e.mjs --check --env-file ../../.env
```

Cung cấp `ADLC_H5D_ACCESS_TOKEN` **chỉ trong shell hiện tại**, lấy qua normal explicit owner login. Đó là ADLC user access token, không phải model key, Harness bearer hay callback secret. Không commit nó vào Blueprint/document hay gửi cho model. `ADLC_H5D_ADLC_BASE_URL` default là `http://127.0.0.1:7860`; normal `ADLC_HARNESS_BASE_URL` default là `http://127.0.0.1:3080`. Giá trị shell hiện có được ưu tiên hơn env-file loading.

Chuẩn bị workflow thật:

1. Trong planning/authoring run, dùng sáu typed Skilltree tools để init một contract nhỏ, upsert một TASK và validate. Cho demo đầu tiên an toàn, dùng read-only constraints với một committed file path và `verifier:contract-no-changes/0.1.0` / ARTIFACT. Cho demo patch, dùng isolated committed demo repo, `allowed_paths:["demo.json"]`, write-enabled constraints và nonempty-patch/JSON-syntax predicates của H5C.
2. Real owner review và approve exact validated reference trong ADLC. Không agent hay runner nào approve.
3. Blueprint chọn **`coding-agent-contract-harness@0.2.0`**, paste four-field `approved_contract_ref` JSON, thêm một bounded requirement, compile, review và accept plan. Smoke runner này chỉ support một task.

Hoặc start run qua ADLC và dùng `--observe`, hoặc cố tình gọi write duy nhất của runner:

```powershell
node scripts/run-adlc-contract-live-e2e.mjs --run --plan-id <approved-plan-uuid> --env-file ../../.env
```

Runner verify exact recipe/reference/lock, approved plan, MANUAL mode và pinned model **trước** materialization. Plan-specific idempotency key của nó replay cùng run trên các lần gọi lặp lại. Nó dừng ở READY, kiểm tra kernel proof và actual patch checksum, in các ID để human review/Submit. Nó không bao giờ chọn newer/latest contract.

4. Review cùng contract/evidence trong ADLC và native Harness shared pane (dark/light/narrow), preview captured patch, rồi click Submit trong ADLC. Quan sát final task/run success:

```powershell
node scripts/run-adlc-contract-live-e2e.mjs --observe --run-id <existing-run-uuid> --env-file ../../.env
```

Observation là read-only và có thể validate archived success với Harness offline. Nó kiểm tra final task result, original attempt ID, ADLC archived result và independent stored proof — chứ không chỉ generic Harness success status. `browser_and_restart_signoff: MANUAL_REQUIRED` có nghĩa runner không thể certify UI/login hay các kịch bản restart.

### Manual live/restart sign-off checklist

- Ghi exact reference, plan, run/task/request/attempt/session và artifact/checksum trước mỗi restart.
- Restart chỉ ADLC ở MANUAL READY. Reopen original run, cùng evidence/patch và IDs; không thêm model turn nào.
- Restart Harness ở MANUAL READY. Candidate vẫn đang chờ; chỉ owner submit.
- Với controlled verification crash, dùng **disposable test stack**, không dùng developer model turn hay production DB. Automated workers đã bao phủ cả hai checkpoint/proof windows. Không edit/delete DB rows để giả lập recovery.
- Bridge outage lúc checkpoint recovery: khôi phục kết nối; dùng Retry verification recovery, rồi review và Submit.
- Callback acknowledgement loss/double delivery: cùng delivery/result IDs, đúng một accepted outcome/task success.
- Restart ADLC sau SUCCEEDED, rồi đưa Harness offline: persisted result/evidence vẫn đọc được. Patch byte TTL giữ 24h.
- Second authenticated user không thể read/mutate run/session/document/evidence của owner đầu tiên.
- Evidence broken/missing/expired phải fail thấy được, không bao giờ hiện success badge hay implicit model rerun.

### Cleanup và giới hạn vận hành

Journal: ≤1 MiB/entry, ≤1,000 checkpoints/128 MiB. One writer. Files là private, atomic/fsynced/checksummed; Linux directory fsync được dùng khi hỗ trợ. Corruption/conflict fail closed. Success chỉ remove exact transient checkpoint của nó **sau** khi normal candidate được persist; recovery-rejected checkpoints còn lại để chẩn đoán qua các restart và Submit/delivery sau này. Không có automatic proof reset, database deletion hay clone purge. Operator cleanup phải resolve và validate exact inactive runtime-owned target, preserve diagnostic/result stores và retained bytes, và không bao giờ nhắm vào source mount/workspace root.

Evidence không TTL; patch bytes giữ bounded 24-hour expiry như H4. Clone/process/provider/plugin/host administrators nằm ngoài agent capability boundary. H5D không phải distributed multi-writer recovery, arbitrary turn resumption, semantic certification, new verifier execution, automatic deployment hay transactional cross-database commit.

### Trạng thái môi trường / sign-off hiện tại

Read-only preflight ngày 2026-10-08: ADLC backend/frontend và Harness không khả dụng; Docker daemon tắt; contract/execution/recovery feature flags chưa bật; explicit owner access token chưa được cung cấp. Existing Harness bearer có mặt khi env file được load, nhưng secret values không bao giờ được in ra. Cấu hình auto-login thực tế giữ nguyên. Implementation không tuyên bố real-owner/provider/callback success cho môi trường này.

Computer-use browser helper fail khởi động hai lần (kể cả reset), nên isolated preview không được kiểm tra trực quan. Loopback-only fixture server đã dừng. Browser fixtures chỉ mô phỏng UI state và không phải live approval/callback test. Component checks và reproducible preview được cung cấp:

```powershell
cd D:\coding\ADLC\adlc-flow\frontend
.\node_modules\.bin\vite.cmd --config tests/contract-viewer-preview/vite.config.mjs
# Mở /tests/contract-viewer-preview/index.html?recovery=true
# Harness pane: thêm &host=harness; light theme: thêm &theme=light
```

Live activation và owner/browser sign-off cần quyết định của operator/account; H5D chưa được đánh dấu là hoàn toàn live-signed-off.

---

## Nguồn tổng hợp

Các tài liệu nguồn được lưu trữ trên nhánh git `agentHarness`, xem bằng `git show agentHarness:docs/<file>`:

- `docs/harness-milestone-h4.md` — Milestone H4 — Artifact review và verification có bằng chứng (2026-10-05)
- `docs/harness-milestone-h5.md` — Milestone H5 — Contract-document plugins (2026-10-08)
- `docs/harness-milestone-h5b.md` — H5B — Shared Skilltree viewer and six-tool authoring (2026-10-08)
- `docs/harness-milestone-h5c.md` — H5C — Approved contract → guarded execution → machine evidence (2026-10-08)
- `docs/harness-milestone-h5d.md` — H5D — Exact verification recovery and live sign-off campaign (2026-10-08)

Liên quan: [ADR 0011](../adr/0011-use-deepseek-harness-as-a-plugin-execution-hub.md), [ADR 0012](../adr/0012-tool-authored-approved-contract-documents.md), [ADR 0013](../adr/0013-shared-contract-viewer-and-restricted-authoring.md), [ADR 0014](../adr/0014-approved-contract-execution-policy-and-evidence.md), [ADR 0015](../adr/0015-exact-contract-verification-recovery.md). Chuỗi H6/H7 tiếp nối ở `../harness-h6.md`.

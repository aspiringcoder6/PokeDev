# H8C — Lập kế hoạch chi tiết qua Harness theo chu kỳ

Trạng thái: **đã triển khai và bật local**, 2026-10-20. Kiểm thử tự động dùng transport giả lập, không dùng model trả phí. Kết nối plugin thật đã đạt kiểm tra readiness; **chưa nghiệm thu lượt lập kế hoạch Luna thật** vì đặc tả chu kỳ 2 chưa được người dùng chốt.

## 1. Phạm vi đã hoàn thành

Trên `/work/:delivery_id?cycle_id=:cycle_id`, chu kỳ tiếp theo có luồng:

**Chốt đầu vào → Harness đề xuất → kernel kiểm tra/biên dịch → xem graph → duyệt đúng graph.**

- Lưu thêm phiên bản `CycleSpec`: commit nền bất biến, định danh nguồn đã đăng ký, tree và nội dung/digest các file được phép đưa vào ngữ cảnh, tiêu chí cố định, giới hạn phân rã và workflow đã pin package digest. Không ghi lại workflow gốc.
- Chỉ đọc nội dung Git đã commit. Thay đổi chưa commit, symlink/submodule, credential-file và ngữ cảnh vượt giới hạn không được đưa vào prompt. Context của Task Loop gồm file được sửa và file kiểm thử cố định, không quét toàn repository.
- Tiêu chí/check và phạm vi Task Loop lấy từ workflow hiện có; H8C không tự sinh một bộ test mới rồi gọi nó là Verify. Thay đổi bộ tiêu chí/test hoặc triage backlog thuộc H8D.
- Ghi SQL operation, generation UUID và **đúng prompt** trước khi gọi Harness. Bấm lặp cùng command chỉ đọc receipt; khóa chu kỳ và giới hạn 3 lượt ngăn tạo thêm lượt khi một lượt chưa được đối soát.
- Plugin `vai-adlc-planner@0.1.0` tạo phiên mới, chỉ dùng `my-codex / cx/gpt-5.6-luna`. Chặn toàn bộ tools ở runtime; không có sandbox/file write/command, callback, approval hay Git authority. Không fallback model.
- Plugin ghi journal trước followup duy nhất, xác nhận native model/usage/turn, từ chối tool activity, retries, compaction, recalled context và output sai profile. Cost chưa đo được là `null`, không phải 0.
- Đề xuất là dữ liệu không tin cậy. Agent chỉ đề xuất task key, stage, tên/mục tiêu, dependency, criterion IDs và lý do. Không được cấp package, policy, capability, secret, input scope hay quyền thực thi.
- Dùng lại `ProposedPlan`, `ProposalValidator`, workflow expansion và compiler. Bổ sung coverage bắt buộc, đúng stage entry/exit và join, criterion/stage binding, giới hạn task, control-gate shape, pin package, bảo toàn config/profile/policy/secret references và edge condition/bindings. Input-binding có nhiều terminal producer không rõ ràng bị chặn; conditional edge chỉ phân rã khi giữ một-một.
- Preview graph lưu durable trong operation và execution-plan archive; UI graph/list/detail đọc chính snapshot đó. Duyệt kiểm tra lại baseline, quyền package hiện tại, spec/plan digest và archive; không biên dịch lại một graph khác khi duyệt.
- Phiên bản đề xuất và semantic diff dùng stable task keys. Khởi động lại backend không phụ thuộc proposal dictionary hoặc version counter process-local.
- Sửa mục tiêu tạo spec mới và vô hiệu hóa việc chốt đầu vào cũ. Đề xuất cũ vẫn xem được trong chẩn đoán nhưng không thể duyệt cho spec mới. Không sửa scope trong lúc generation chưa đối soát.

### Ranh giới cố ý giữ đóng

H8C **chưa** cấp quyền Start cho successor. `execution_ready=false`; compile/approve/start cũ và các API planning nâng cao vẫn không cho mượn authority chu kỳ 1. Graph được duyệt có riêng receipt trong chu kỳ 2, không sửa binding hay plan của chu kỳ 1.

Việc chọn baseline từ **kết quả đã chấp nhận**, đóng chu kỳ trước, tích hợp candidate nhiều task và chạy/Verify/phát hành successor thuộc phần nối vòng lặp H8D–H8E. H8C không phải bằng chứng Product Loop đã chạy trọn hai chu kỳ. Một đề xuất hợp lệ về cấu trúc cũng chưa chứng minh ứng dụng đã được xây đúng hoặc test đã chạy.

Task Loop có `task_loop_spec` phải giữ **một scheduler task** với nguyên spec/check/scope. APPROVAL/ROUTER/JOIN cũng giữ một task mỗi stage. Các stage thông thường mới được phân rã thành nhiều task; không vẽ thêm node từ bước suy nghĩ nội bộ của agent. Workflow hai stage hiện tại có thể vẫn ra hai task — đây không phải lỗi phân rã.

## 2. API và hợp đồng

Base: `/api/v1/adlc/deliveries/{delivery}/cycles/{cycle}/planning`.

| Endpoint | Tác dụng | Có gửi prompt? |
| --- | --- | --- |
| `GET /context` | Đọc source snapshot thuộc project/cấu hình, HEAD đề xuất, phạm vi và tiêu chí. | Không |
| `POST /freeze` | Tạo spec revision + receipt chốt input/workflow riêng chu kỳ. | Không |
| `POST /generate` | Reserve durable operation rồi gửi một generation đã pin. | Có, sau hành động xác nhận |
| `POST /generations/{operation_id}/reconcile` | Chỉ GET journal của generation cũ; validate/compile outcome nếu có. | Không |
| `POST /accept` | Duyệt exact archived preview bằng spec/plan digest. | Không |
| `GET /deliveries/{delivery}?cycle_id=...` | Projection SQL; không tự gọi Harness. | Không |

Commands kế thừa proof `expected_revision`, `workflow_digest`, `cycle_id`, `command_id` và thêm `spec_digest`. Freeze thêm `base_commit` (đúng 40 hex) và `limits`; Accept thêm operation `generation_id` và `plan_digest`. Không nhận actor/role/approval assertion từ browser.

`DetailedOutput` (Pydantic closed schema) có `tasks[]`, `assumptions[]`, `clarifications[]`. Mỗi task có `task_id`, `source_stage_id`, `name`, `objective`, `dependency_task_ids`, `criterion_ids`, `planning_rationale`. Clarification chưa giải quyết chặn duyệt.

SQL dùng các bảng H8B sẵn có: append-only `adlc_cycle_spec`, `adlc_cycle_operation` (`FREEZE_PLANNING`, `HARNESS_PLAN`, `ACCEPT_GRAPH`), `adlc_cycle_plan_revision`, cycle authority và execution-plan archive. **Không cần migration H8C**. Không đổi schema/receipt lịch sử của H8B.

Generation status: `RESERVED` / `UNCONFIRMED` / `SUCCEEDED` / `FAILED`. Result phase: `RESERVED`, `RUNNING`, `UNCONFIRMED`, `REVISION_REQUIRED`, `VALIDATED`, `ACCEPTED` hoặc `FAILED`. `SUCCEEDED` của generation chỉ nghĩa đã nhận kết quả, không có nghĩa graph đã duyệt hay task đã chạy. Release native chưa xác nhận tiếp tục khóa việc tạo lượt mới.

Private ownership + flow permissions vẫn được kiểm tra server-side. Shared/managed projects tiếp tục yêu cầu team adapter; endpoint mới không bypass H7B.

## 3. Cách sử dụng local

1. Đăng nhập [Workspace](http://localhost:3000/work).
2. Mở công việc, chọn chu kỳ tiếp theo; chỉnh mục tiêu khi cần.
3. Bấm **Chốt đầu vào**, đọc commit/phạm vi/tiêu chí, tích xác nhận rồi lưu. Bước này chưa gọi model.
4. Bấm **Tạo task chi tiết**, xác nhận một lượt Luna. UI quan sát generation đã reserve; lỗi kết nối chỉ có **Đối soát trạng thái**, không tự tạo lượt mới.
5. Xem graph/list, mở từng task, đọc findings và diff; chỉ bấm **Duyệt graph này** nếu chấp nhận exact snapshot. Không tự chạy task sau duyệt.

Chu kỳ hiện có để nghiệm thu:

[Mở chu kỳ 2](http://localhost:3000/work/57c730a8-b21c-4dfd-9fe3-d8a440afb4de?cycle_id=d743a50a-89ff-45bd-8550-affb596e5558).

Mục tiêu hiện còn mang tính chuẩn bị; hãy chỉnh thành phạm vi increment cụ thể trước khi chốt. Không tự dùng candidate chu kỳ 1 đang chờ duyệt/đã hết hạn làm baseline.

### Cấu hình và khởi động

Backend và Compose: `ADLC_CYCLE_PLANNING_ENABLED=true`. Planner dùng credential độc lập hiện có `ADLC_HARNESS_ITERATION_API_TOKEN`, không dùng API key model, callback secret hay token đăng nhập web. `ADLC_HARNESS_BASE_URL` xác định Harness; profile model cố định không lấy last selection từ UI.

Mã nguồn từ local-project đã đăng ký/kiểm tra ownership, hoặc `ADLC_TASK_LOOP_SOURCE_REPOSITORY` do operator cấu hình. HTTP caller không gửi đường dẫn hay remote URL mới.

Sau khi dừng run khác và đồng ý reload:

```powershell
cd D:\coding\ADLC\adlc-flow
$env:PYTHONPATH='D:\coding\ADLC\adlc-flow;D:\coding\ADLC\sdk'
.\.venv\Scripts\python.exe scripts\backup_product_cycles.py --label h8c --backup-only
.\.venv\Scripts\python.exe scripts\enable_delivery_iterations.py --reload-confirmed --enable-cycle-planning
.\scripts\start_delivery_services.ps1
```

Helper giữ credential trong bộ nhớ, giữ source mounts read-only và các deployment flags hiện có, chỉ reload một service Harness, kiểm tra release readiness; không tạo phiên/gửi prompt. Plugin lock pin planner và helpers hiện hữu, không thay release Task Loop.

Journal/lease: không xóa ledger hay retry một model call chưa xác nhận. Sau crash, chỉ operator được kiểm tra process cũ, journal, release và lease. Không xóa lease khi process sở hữu còn sống hoặc journal chưa giải phóng.

## 4. Kích hoạt và đối chiếu dữ liệu

- Backup 9 SQLite stores: `adlc-flow/data/backups/h8c-20261019T170024973409Z` (đầu ngày 20/10 giờ Việt Nam).
- Backend 7860, frontend 3000 và Harness 3080 đã bật; health backend `chat/db=ok`.
- Planner readiness: true, release `sha256:54715edab0ae2c920d9d69592b14fd162da08fccc717f30d4a64d673c3f5b01b`, Luna-only, tools disabled.
- Task Loop ban đầu bị khóa bởi lease cũ ngày 18/10. Kiểm tra container/process đã thay, journal chỉ có một record COMPLETED + released, không có canonical run RUNNING/QUEUED/CREATED. Chỉ đổi tên lease thành `/app/data/adlc-iteration-ledger/writer.lease.h8c-20261020`; giữ nguyên record, không xóa hoặc re-prompt. Task Loop readiness sau đó true. File lease cũ còn để phục hồi/đối chiếu.
- Đối chiếu sau startup: protected legacy records không đổi, cả sáu bảng cycle không đổi, toàn bộ canonical run records không đổi, foreign-key errors = 0. Alembic head vẫn `h8b1c2d3e4f5`.
- Không freeze/accept spec, không tạo generation, không duyệt candidate hoặc push thay người dùng trong lúc kích hoạt.
- Sau người dùng đăng nhập: mở đúng chu kỳ 2, xác nhận bản nháp spec v1, chưa có kế hoạch và 0/3 lượt lập kế hoạch. `GET /context` đọc được project `083d5688-1736-47d1-a72c-dfbd0d1aa407`, commit đề xuất `c5829b61e4d77f353105338ae1ae16e98e5de339`, hai file `app.py`/`test_acceptance.py` và ba tiêu chí từ workflow. Chỉ mở rà soát, chưa chốt dữ liệu. Đã sửa chiều cao/cuộn hộp rà soát khi mở đầy đủ tiêu chí; kiểm tra lại trên giao diện thật. Để sẵn hộp chỉnh mục tiêu, không lưu thay người dùng vì mục tiêu hiện còn là nội dung chuẩn bị.

## 5. Kiểm thử và giới hạn nghiệm thu

Đợt regression cuối đã chạy: **164 backend tests**, **298 frontend tests/30 suites**, **10 planner-plugin tests + 23 Task Loop plugin regression tests** đạt. Hai cảnh báo pytest `timeout`/`timeout_method` là cấu hình môi trường cũ; không có lỗi test. TypeScript trên 21 file workspace/API/preview và Ruff trên source thay đổi đạt; không tuyên bố full-repository build.

- SQL idempotency/concurrency/restart/uncertain ACK, spec invalidation, exact preview→accept digest và giữ nguyên cycle 1.
- Workflow 5 stages → 6 concrete tasks, hai branch nối đúng tại Verify; thiếu join/stage/criterion, gate duplication, cycle, package/control injection bị chặn.
- Parent-cycle validation không còn đệ quy vô hạn với input không tin cậy.
- UI: explicit confirmations, stale review, mismatched cycle/spec/graph, read-only permissions, accessible preview, accepted≠executed.
- Kiểm tra browser: Graph/List cùng 5 task/6 edges, một stage có hai task, drawer có tiêu chí đúng, thu phóng/keyboard hoạt động. Preview điện thoại dùng iframe riêng rộng danh định 390px (viewport đo 389px sau border/device scaling), page/body cùng 389px, không tràn ngang; không thay viewport hoặc thao tác trang đăng nhập thật.
- Native Harness driver: fresh Luna route, tools denied, one-turn journal, no compaction/retry/tool activity, proper disposal; tests dùng fake native handle, không gọi provider.

Artifacts local: `adlc-flow/data/h8c-backend-tests.xml`, `adlc-flow/data/h8c-frontend-tests.json`. Bản kiểm tra giao diện riêng (dữ liệu mẫu, readonly, không phải bằng chứng thực thi): `/tests/delivery-workspace-preview/index.html?scenario=cycle-planning` trên port preview 4178.

Ảnh giao diện **dữ liệu mẫu, không phải lượt chạy model**:

![Graph preview H8C](report/delivery-workspace/30-h8c-graph-preview.jpg)

[Bố cục điện thoại](report/delivery-workspace/31-h8c-mobile-390.jpg).

Đã kiểm tra UI trên tài khoản thật: [rà soát đầu vào](report/delivery-workspace/32-h8c-live-input-review.jpg), [chỉnh mục tiêu bản nháp](report/delivery-workspace/33-h8c-live-goal-review.jpg). Đây là bằng chứng đọc UI/context, không phải kết quả lập kế hoạch hoặc Verify.

Cần nghiệm thu tiếp bằng **spec đã được người dùng chốt** → một generation Luna thật → xem exact preview → người dùng duyệt. Readiness và dữ liệu mẫu không thay cho lượt nghiệm thu đó.

## 6. Source chính

- `adlc-flow/langflow/adlc/cycle_planning.py`, `cycle_planning_client.py`, `cycle_planning_release.py`.
- `adlc-flow/langflow/api/v1/adlc_cycle_planning.py`, integration projection ở `adlc_delivery.py`.
- `agent-harness-server/deepseek-harness/plugins/vai-adlc-planner/`, `adlc-planner.plugin-lock.json`, Compose/patch.
- `adlc-flow/frontend/src/features/delivery-workspace/cycle-planning.tsx`, task graph/list/detail chung, typed API ở `controllers/API/delivery.ts`.

Lưu ý Git: `agent-harness-server` là checkout riêng đang có thay đổi khác của người dùng. Cần giữ và commit phần H8C trong đúng repository khi bàn giao/merge; không gộp hoặc xóa các thay đổi khác.

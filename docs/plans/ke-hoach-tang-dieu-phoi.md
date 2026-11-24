# Kế hoạch xây Tầng Điều phối theo kiến trúc vAiPlatform — kèm prompt triển khai

> Trạng thái: Đề xuất (Draft) — bản kế hoạch thi công chi tiết của
> `docs/plans/ke-hoach-dieu-phoi-monarch.md`
> Nguyên tắc phạm vi: **chỉ xây tầng điều phối**. Tầng thực thi chỉ làm **hợp đồng
> kết nối (port/adapter) + executor giả để test** — executor thật (OpenCode/DSH)
> **để giai đoạn sau**.

---

## A. Phạm vi và kiến trúc

```
SAU (thi công ngay)                          |  SAU (không đụng trong kế hoạch này)
TẦNG 1  Interface: tiếp nhận Intent          |  Executor thật OpenCode/DSH
TẦNG 2  WORKFLOW control plane:              |  Sandbox Broker/VFS
        routing capability + gate + verdict  |  System Loop eval
TẦNG 3  (phần điều phối) Monarch não:        |
        Plan DAG + đề xuất routing +         |  (chỉ chốt HỢP ĐỒNG kết nối — G5)
        TaskContract + Reflection            |
TẦNG 4  Sandbox: chỉ định nghĩa điểm cắm     |
```

Luật chơi (từ bài thuyết trình): control plane enforce mọi quy tắc bằng code;
Monarch chỉ **đề xuất**; người **phê duyệt**; kết quả phải qua **verdict độc lập**
mới được DONE; tầng thực thi tương lai chỉ cần cắm đúng hợp đồng.

Thứ tự thi công: **G1 → G2 → G3 → G4 → G5 → G6** (mỗi gói = 1 PR riêng,
prompt bên dưới đã viết để chạy độc lập theo thứ tự).

---

## B. Các gói công việc + prompt

### G1 — Hạ tầng chuyển đổi an toàn (feature flag + baseline)

> Mục tiêu: mọi thay đổi sau này bật/tắt được, có test mốc so sánh.

```text
Bạn đang làm việc trong dự án VDT-ADLC (repo tại thư mục hiện tại). Nhiệm vụ: tạo hạ
tầng chuyển đổi an toàn cho việc nối orchestrator mới, KHÔNG thay đổi hành vi hiện có.

Bước 1 — Đọc trước: docs/plans/ke-hoach-tang-dieu-phoi.md (kế hoạch này),
adlc-flow/langflow/adlc/orchestrator_plugin/host.py,
adlc-flow/langflow/adlc/planning/materializer.py,
adlc-flow/tests/unit/adlc/test_orchestrator_plugin.py,
adlc-flow/tests/unit/adlc/test_executor_router.py,
adlc-flow/tests/unit/api/v1/test_adlc_runs.py.

Bước 2 — Thêm feature flag "ADLC_ORCHESTRATOR_ROUTING":
- Đọc cách dự án quản lý env/config hiện có (tìm trong adlc-flow cách env vars được
  khai báo, ví dụ ADLC_SUBTASK_PREP_CONCURRENCY) và làm theo đúng pattern đó.
- Mặc định TẮT. Khi tắt: toàn bộ path routing cũ chạy nguyên vẹn 100%.

Bước 3 — Chạy baseline test trên nhánh sạch, ghi lại danh sách test xanh vào
docs/plans/notes-orchestrator-baseline.md (chỉ ghi tên test + trạng thái, không sửa test).

Bước 4 — Quy ước routing: viết ADR ngắn (docs/plans/adr-orchestrator-auto.md) định nghĩa
giá trị đặc biệt spec.implementation.adapter_ref == "orchestrator:auto" nghĩa là
"executor do OrchestratorHost chọn lúc phê duyệt plan". Không hiện thực logic — chỉ chốt
quy ước, ví dụ lỗi, và điều kiện bật flag.

Ràng buộc: không sửa file khác ngoài những file nêu trên + file test/env mới tạo.
Nghiệm thu: toàn bộ test cũ còn xanh; flag tắt thì không có gì đổi; ADR tồn tại.
```

---

### G2 — Tầng 2: Nối OrchestratorHost vào production (routing seam)

> Mục tiêu: Monarch/tham gia quyết định "ai làm" LẦN ĐẦU TIÊN, tại thời điểm phê duyệt
> plan. Plan vẫn bất biến. Đây là gói lõi của lý thuyết bài thuyết trình ở Tầng 2.

```text
Bạn đang làm việc trong dự án VDT-ADLC. Gói G1 đã xong (feature flag
ADLC_ORCHESTRATOR_ROUTING đã có, ADR quy ước "orchestrator:auto" đã viết).

Nhiệm vụ: nối OrchestratorHost (hiện chỉ test dùng) vào path production để resolve
executor theo capability khi plan khai báo adapter_ref = "orchestrator:auto".

Đọc trước:
- adlc-flow/langflow/adlc/orchestrator_plugin/host.py (OrchestratorHost,
  find_capable, dispatch_plan, get_default_host)
- adlc-flow/langflow/adlc/orchestrator_plugin/interface.py (Intent, PluginMetadata)
- adlc-flow/langflow/adlc/orchestrator_plugin/plugins/monarch.py (MonarchPlugin)
- adlc-flow/langflow/adlc/orchestrator_plugin/plugins/deepseek_harness.py (stub, disabled)
- adlc-flow/langflow/adlc/planning/materializer.py (khối tạo ExecutorTarget, ~dòng 384,
  và request_metadata ~dòng 334)
- adlc-flow/langflow/adlc/resource_manager/capabilities.py (AgentCapability, CostTier)

Việc cần làm:
1. Factory production cho host: thêm hàm tạo OrchestratorHost mặc định đăng ký
   MonarchPlugin (enabled) + DeepSeekHarnessPlugin (disabled). Tôn trọng pattern
   get_default_host() hiện có.
2. Trong materializer, khi flag BẬT và adapter_ref == "orchestrator:auto":
   - Lấy capabilities cần thiết từ task (đang có ở ExecutorTarget capabilities).
   - Gọi find_capable(capabilities) để chọn plugin.
   - Không tìm thấy plugin nào → raise lỗi domain có mã "NO_CAPABLE_PLUGIN"
     (đi theo pattern lỗi hiện có của materializer/run_service), KHÔNG fallback im lặng.
   - Ghi vào request_metadata: routing_source="orchestrator", plugin_id được chọn,
     capabilities đã khớp. Khi adapter_ref là executor cụ thể → routing_source="user".
3. API: khi preview plan (endpoint xem trước materialization), trả kèm "routing proposal"
   — mỗi task sẽ chạy trên executor nào, theo capability nào — để người phê duyệt
   xem/sửa trước khi đóng băng.
4. Test mới (tests/unit/adlc/):
   a. orchestrator:auto + đúng capability → chọn đúng plugin.
   b. hai plugin cùng capability → chọn theo thứ tự đăng ký, có kiểm thử.
   c. không plugin đủ năng lực → lỗi NO_CAPABLE_PLUGIN, plan không materialize.
   d. flag TẮT → toàn bộ hành vi cũ nguyên vẹn (baseline test G1 vẫn xanh).

Ràng buộc: plan snapshot vẫn bất biến (resolve xảy ra TRƯỚC khi đóng băng);
không sửa executor nào; không sửa schema ExecutorTarget.
```

---

### G3 — Tầng 1: Cổng tiếp nhận Intent (Interface Layer)

> Mục tiêu: hiện thực điểm khởi đầu của vòng ADLC trong bài thuyết trình — yêu cầu từ
> user/webhook đổ về control plane dưới dạng Intent có cấu trúc, trả routing proposal.

```text
Bạn đang làm việc trong dự án VDT-ADLC. Gói G2 đã xong (OrchestratorHost đã nối
production, flag ADLC_ORCHESTRATOR_ROUTING hoạt động).

Nhiệm vụ: tạo cổng tiếp nhận Intent — biến yêu cầu thô (ý tưởng tính năng / bug /
nhiệm vụ) thành Intent có cấu trúc rồi yêu cầu plan đề xuất từ orchestrator plugin.

Đọc trước:
- adlc-flow/langflow/adlc/orchestrator_plugin/interface.py (Intent, IntentType,
  ExecutionPlan — model có sẵn, đừng tạo model mới lặp lại)
- adlc-flow/langflow/api/v1/adlc.py (pattern router, dependency injection, error handling)
- adlc-flow/langflow/adlc/orchestrator_plugin/host.py (dispatch_plan)
- Pattern phân loại hiện có nếu liên quan: subtask_generator.py, plan_orchestrator.py

Việc cần làm:
1. Endpoint POST /api/v1/adlc/intents/plan-proposals:
   - Body: intent_type (IntentType), description, context, required_capabilities.
   - Tạo Intent (model có sẵn), gọi host.dispatch_plan(intent) → trả ExecutionPlan
     dạng "proposal" (KHÔNG tạo run, KHÔNG materialize — đây chỉ là đề xuất).
   - Response gồm: plan_id, steps (tên, mô tả, capabilities, depends_on), plugin đề
     xuất, metadata. Người dùng duyệt/sửa rồi mới đi đường materialize hiện có.
2. Phân loại intent_type tự động nếu client không truyền: dùng rule đơn giản theo từ
   khóa (đúng tinh thần Intent Gate của Monarch: verbalize → classify), không gọi LLM
   trong gói này. Ghi rõ heuristic vào response để audit.
3. Idempotency: nhận idempotency_key trong body; gọi lại cùng key trả cùng proposal.
4. Phân quyền: yêu cầu đăng nhập như các endpoint adlc khác; intent được scope theo
   owner_id (dùng pattern owner-scoped hiện có).
5. Test (tests/unit/api/v1/): propose thành công; idempotent; intent_type không hợp lệ
   → 422; flag tắt → endpoint trả 503 với mã "ORCHESTRATOR_ROUTING_DISABLED".

Ràng buộc: không gọi LLM trong endpoint này (plan do plugin产 — plugin ở chế độ
plan-only hiện tại trả 1-step là chấp nhận được; gói G4 sẽ nâng nó lên DAG thật).
```

---

### G4 — Tầng 3 (phần điều phối): Monarch thành bộ não đề xuất

> Mục tiêu: biến Monarch từ "prompt orchestrator" thành generator thật cho
> ExecutionPlan DAG + TaskContract — và rào cứng nó bằng code ("brain không có tay").

```text
Bạn đang làm việc trong dự án VDT-ADLC. Gói G2, G3 đã xong. Cần có môi trường chạy
Monarch agent (adlc_components) — nếu không chạy được live thì mọi logic phải có
nhánh plan-only dự phòng đúng như pattern hiện tại của MonarchPlugin.

Phần 1 — plan() đa bước thật (adlc-flow/langflow/adlc/orchestrator_plugin/plugins/monarch.py):
- Bỏ stub 1-step ở phương thức plan(). Chế độ live (có monarch_agent): gọi agent với
  structured output để sinh ExecutionPlan nhiều PlanStep.
- Yêu cầu đầu ra của LLM phải bó schema: mỗi step có name, description (mục tiêu tự
  chứa), required_capabilities (từ enum AgentCapability), depends_on (tên step), and
  expected_outputs. Không dùng free-text JSON; dùng đường structured output có sẵn
  (xem json_response + output_schema trong adlc_components/custom_component/agents/
  orchestrator.py).
- Validate DAG sau sinh: không chu trình, depends_on trỏ tới step tồn tại, mọi step có
  ≥1 capability. Dùng/lặp pattern từ adlc-flow/langflow/adlc/plan_validator.py. DAG
  không hợp lệ → trả lỗi rõ ràng, KHÔNG tự sửa mù.
- Giữ chế độ plan-only (không monarch_agent) hành vi như cũ — để test không cần LLM.

QUY TẮC PHÂN RÃ (bắt buộc khi sinh DAG — đơn vị song song là TASK, không phải subagent):
- Mỗi PlanStep = MỘT deliverable mà MỘT agent hoàn thành trong MỘT attempt (một session
  thực thi). Song song giữa các đơn vị việc đến từ DAG của control plane, KHÔNG từ
  agent tự spawn subagent lúc chạy.
- Step cần nhiều loại năng lực (vd: code-gen + security-scan) PHẢI tách thành nhiều
  step, mỗi step một nhóm capability riêng — để router phân cho executor khác nhau.
- Công việc độc lập nhau PHẢI là các step riêng không có depends_on. Đánh đổi: plan
  mảnh quá chỉ tốn thêm gate; plan thô quá phá verdict, song song và routing —
  thiên về chia nhỏ.
- Tín hiệu plan kém phải sinh lại (không tự vá mù): chuỗi thẳng toàn bộ step (mọi step
  phụ thuộc step trước) trong khi mô tả cho thấy công việc độc lập; hoặc một step mô
  tả công việc của nhiều loại năng lực / nhiều deliverable.

Phần 2 — Brain không có tay (adlc_components/custom_component/agents/orchestrator.py):
- Thêm input cờ "orchestrator_mode" (BoolInput, mặc định True cho component Monarch).
- Trong get_agent_requirements(), sau khi gom tools: nếu orchestrator_mode bật, LOẠI
  khỏi self.tools mọi tool thực thi — theo danh sách tên/khớp: edit, write, patch,
  shell, và bất kỳ tool nào có thuộc tính nguy hiểm tương đương. Giữ: read-only tools,
  lsp_diagnostics, task tools, tool dạng agent-connector (Call_Agent).
- Ghi log các tool bị loại. Viết unit test khẳng định toolset sau lọc không chứa tool
  thực thi và mọi connector agent vẫn còn.

Phần 3 — Giao việc thành hợp đồng:
- Tách "mẫu 6 mục" trong system_prompts/orchestrator.py thành schema đầu ra có cấu
  trúc (task_name, objective, expected_files, scope_paths, must_not_do, acceptance_criteria)
  để nó có thể materialize thành TaskContract của hệ contract hiện có
  (adlc-flow/langflow/adlc/contract_authoring.py, contract_models.py — đọc trước).
- Cập nhật system prompt (system_prompts/orchestrator.py): bỏ trách nhiệm "tự đọc từng
  file của subagent để nghiệm thu" — Monarch chỉ đề xuất verdict từ evidence (quality
  gate sẽ nối ở gói G6). GIỮ nguyên Intent Gate và delegation framework.

Test: DAG ≥2 bước có depends_on hợp lệ từ mô tả; DAG thỏa quy tắc phân rã (công việc
độc lập là các step riêng; không step nào trộn nhiều nhóm capability); toolset Monarch
không còn tool thực thi; contract sinh khớp schema contract hiện có; chế độ plan-only
không bị phá.
```

---

### G5 — Hợp đồng kết nối tầng thực thi (chưa thực thi executor thật)

> Mục tiêu: tầng thực thi SAU NÀY chỉ cần "cắm vào cổng". Gói này chỉ chuẩn hóa cổng +
> executor giả để test, KHÔNG wire OpenCode/DSH thật. Đúng yêu cầu: phần thực thi
> chỉ làm nhiệm vụ kết nối với tầng điều phối, thực hiện sau.

```text
Bạn đang làm việc trong dự án VDT-ADLC. Gói G2–G4 đã xong.

Nhiệm vụ: chuẩn hóa "hợp đồng kết nối" giữa tầng điều phối (control plane) và tầng
thực thi, dựa trên các Protocol có sẵn, sao cho executor tương lai (OpenCode, DSH)
chỉ cần implement protocol là cắm được — không đụng control plane.

Đọc trước:
- adlc-flow/langflow/adlc/adapter_interfaces.py (AgentAdapter, SandboxAdapter,
  MemoryAdapter, TestingAdapter — cổng ổn định hiện có)
- adlc-flow/langflow/adlc/models.py (TaskRequest, TaskResult, ExecutorTarget)
- adlc-flow/langflow/adlc/executor_router.py (router tra theo service)
- adlc-flow/langflow/adlc/mock_executor.py và mock_adapters.py (pattern executor giả)
- adlc-flow/tests/unit/adlc/test_executor_router.py

Việc cần làm:
1. Tài liệu hóa hợp đồng v1 (docs/reference/hop-dong-executor.md, tiếng Việt):
   - Executor tương lai PHẢI: implement AgentAdapter; khai báo service_name duy nhất
     + capabilities; nhận TaskRequest với contract scope; trả TaskResult chỉ chứa
     summary + artifacts (không hội thoại); tôn trọng sandbox/memory do plane cấp.
   - Executor KHÔNG ĐƯỢC: gọi ngược vào run_service, tự đổi trạng thái task, trả về
     hội thoại/thống tin ngoài hợp đồng.
   - Executor ĐƯỢC PHÉP dùng session/subagent nội bộ của riêng nó (task loop iteration,
     subagent research, verification riêng cho candidate...) CHỈ KHI: (a) toàn bộ
     sub-work nằm trong scope_paths của contract; (b) tiêu tốn từ budget của task;
     (c) đầu ra trả control plane vẫn chỉ là summary + artifacts. Subagent nội bộ
     KHÔNG phải cơ chế phân task thứ hai — phân rã và phân bổ agent là việc của tầng
     điều phối, hoàn tất trước khi dispatch; bên trong một task, task loop chạy
     N iteration TUẦN TỰ với session fresh mỗi iteration (đúng thiết kế hiện có),
     không chạy song song qua subagent để né concurrency cap của scheduler.
   - Quy ước lỗi: ServiceError với error_id, code, retryable, correlation_id (pattern
     hiện có trong executor_router.py EXECUTOR_SERVICE_NOT_REGISTERED).
2. Kiểm tra và bổ sung (nếu thiếu) các trường cần cho giai đoạn sau trong
   TaskRequest/executor metadata: contract_scope (paths được phép), permission hints
   (deny shell/...), cost_tier mong muốn. Bổ sung theo kiểu backward-compatible
   (field optional, default None) — KHÔNG đổi field bắt buộc hiện có.
3. MockExecutors theo capability: 2 executor giả mới — "mock:opencode-like" (khai báo
   CODE_GENERATION) và "mock:dsh-like" (khai báo SECURITY_SCAN) — đăng ký vào router
   trong fixture test, để test mix-2-executor KHÔNG cần executor thật.
4. Test tích hợp mini (tests/unit/adlc/): một run 3 task — task 1 (CODE_GENERATION,
   mock:opencode-like), task 2 (SECURITY_SCAN, mock:dsh-like), task 3 phụ thuộc cả
   hai — chứng minh DAG chạy đúng thứ tự, kết quả qua router về đúng service, và
   TaskResult trả về chỉ chứa summary + artifacts (không có hội thoại hay dữ liệu
   nào ngoài hợp đồng).

Ràng buộc: KHÔNG wire executor thật; KHÔNG sửa run_service ngoài phần cần cho đăng ký
mock trong fixture test; hợp đồng văn bản là sản phẩm chính của gói này.
```

---

### G6 — Tầng 2: Quality gate nối vào vòng đời (verdict độc lập)

> Mục tiêu: hiện thực luận điểm "verdict độc lập với TaskResult" của bài thuyết trình —
> succeeded chưa đủ để DONE. Sau gói này, vòng đời điều phối là khép kín đủ dùng.

```text
Bạn đang làm việc trong dự án VDT-ADLC. Gói G2–G5 đã xong (routing hoạt động, có
executor giả, Monarch sinh DAG + contract).

Nhiệm vụ: nối quality gate + verdict độc lập + human gate vào state machine của
run_service, đúng ba chiều của bài thuyết trình: trạng thái thực thi / verdict theo
tiêu chí / quyết định chấp nhận.

Đọc trước:
- adlc-flow/langflow/adlc/run_service.py (state machine, scheduler dispatch, retry,
  pause/resume — tìm chỗ chuyển trạng thái sau khi executor trả kết quả)
- adlc-flow/langflow/adlc/quality_gate.py và verification_*.py, evidence_plane/
- adlc-flow/langflow/adlc/contract_models.py (tiêu chí nghiệm thu trong contract)
- docs/plans/ke-hoach-tang-dieu-phoi.md (phần G6 của kế hoạch tổng)

Việc cần làm:
1. Gate vào scheduler: sau khi executor trả TaskResult succeeded, kết quả PHẢI đi qua
   quality gate (chấm theo acceptance_criteria của contract trước khi được đánh DONE.
   Verdict fail → theo policy của task: retry còn lượt → retry; hết lượt → trạng thái
   CONCERNS/escalation có sẵn. KHÔNG tạo trạng thái mới — dùng trạng thái hiện có.
2. Verdict độc lập: verdict do quality_gate/verification module sinh từ EVIDENCE
   (artifact, test report), KHÔNG từ lời tự báo cáo của executor hay của Monarch.
   Cấu trúc verdict lưu vào kết quả (đường evidence có sẵn trong verification/evidence).
3. Human gate pin phiên bản: khi contract yêu cầu approval, trạng thái chờ phê duyệt
   phải gắn revision/digest của artifact đã xem; đổi artifact sau khi duyệt → gate
   PHẢI từ chối. Dùng hệ digest hiện có.
4. Reflection sau run: khi run kết thúc (thành công hoặc thất bại), gọi
   host.dispatch_reflect() để sinh ReflectionReport (successes/failures/suggestions)
   và lưu metadata của run.
5. Policy mặc định bật/tắt gate theo loại task (ví dụ mock task không cần gate) bằng
   cấu hình, KHÔNG hardcode.
6. Test (tests/unit/adlc/ + tests/unit/api/v1/test_adlc_runs.py):
   - succeeded + verdict fail → KHÔNG DONE, vào đúng trạng thái policy.
   - succeeded + verdict pass + human gate required + approval đúng digest → DONE.
   - approval sai digest → từ chối.
   - reflection được ghi cho cả run thành công lẫn thất bại.
   - flag gate tắt theo loại task → hành vi cũ nguyên vẹn.
```

---

## C. Thứ tự, phụ thuộc, cách dùng prompt

| Gói | Phụ thuộc | Kết quả | Bật flag? |
| --- | --- | --- | --- |
| G1 Baseline | — | Flag + ADR + test mốc | Không (chưa có gì để bật) |
| G2 Routing seam | G1 | `orchestrator:auto` hoạt động | Bật khi review, tắt khi rollback |
| G3 Intake Intent | G2 | API nhận yêu cầu → plan đề xuất | Theo flag |
| G4 Monarch não | G2 | DAG thật + contract + brain-no-hands | Theo flag |
| G5 Cổng thực thi | G2 | Hợp đồng v1 + 2 mock executor | Luôn bật (mock an toàn) |
| G6 Quality gate | G2, G5 | DONE cần verdict + human gate | Theo flag |

Cách dùng prompt:

1. Thực hiện **tuần tự từng gói**, mỗi gói một phiên/nhánh riêng, review + merge trước
   khi mở gói sau (các prompt có tham chiếu chéo trạng thái gói trước).
2. Dán prompt nguyên văn vào session AI trong thư mục dự án. Prompt đã tự chứa đường
   dẫn đọc trước + ràng buộc + tiêu chí nghiệm thu; nếu AI trôi, nhắc lại dòng
   "Ràng buộc" của gói tương ứng.
3. Sau mỗi gói: chạy toàn bộ test cũ + mới; xem diff; chỉ merge khi baseline vẫn xanh.
4. Executor thật (OpenCode/DSH), sandbox Broker/VFS và System Loop **không nằm trong
   kế hoạch này** — khi đến lúc, chúng chỉ là các AgentAdapter mới cắm vào cổng G5,
   đúng tinh thần "tầng thực thi chỉ kết nối với tầng điều phối".

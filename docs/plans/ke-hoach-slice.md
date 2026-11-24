# Kế hoạch triển khai ADLC theo slice

Tài liệu này tổng hợp toàn bộ lộ trình triển khai ADLC (Agent Development Life Cycle) theo các slice, từ nền tảng blueprint planning đến control plane của orchestrator. Toàn bộ các slice ghi trong tài liệu đều **ĐÃ HOÀN THÀNH** (bản gốc tiếng Anh lưu trữ trên nhánh git `agentHarness`, xem [Nguồn tổng hợp](#nguồn-tổng-hợp)).

## Bối cảnh và cách chia đợt

ADLC được xây trong Langflow theo hướng: người dùng soạn một **blueprint** (sơ đồ workflow cấp cao có marker `WORKFLOW_DEFINITION`), hệ thống biên dịch thành một `ExecutionPlan` bất biến, rồi materialize thành `WorkflowRun`/`TaskRun` và điều phối qua scheduler. Lộ trình chia làm hai giai đoạn lớn:

1. **Nền tảng blueprint → kế hoạch → runtime (slice 2 → 6C):** parse blueprint, phân giải node package, tạo kế hoạch, UI soạn thảo, materialize lần chạy, định tuyến thực thi, regeneration kế hoạch, phân quyền package, observability, và tích hợp OpenCode thật qua disposable Git worktree.
2. **Orchestrator control plane (slice 7 → 10):** biến coordinator trong tiến trình thành orchestrator có thể điều khiển và tự phục hồi, chia theo các đợt ưu tiên — **P0** lệnh điều khiển lần chạy (`cancel_run`, `pause_run`, `resume_run`); **P1** tự phục hồi (auto-retry với backoff, deadline watchdog, persistence SQL + crash recovery); **P2** trigger (cron/interval/webhook) và metrics/alerts/Prometheus; **P3** approval expiry, SLA breach, notification, dead-letter view (slice 9) cộng template expressions, webhook notification, ngưỡng alert theo environment (slice 10).

| Đợt | Slice | Phạm vi chính | Trạng thái |
|---|---|---|---|
| Nền tảng | Slice 2 | Blueprint parsing và execution planning | ✅ đã hoàn thành |
| Nền tảng | Planner proposal | Proposal → validation → approval → pipeline hiện có | ✅ đã hoàn thành |
| Nền tảng | Slice 3 → 4 | Blueprint UI, Plan Preview, materialize vào mock runtime | ✅ đã hoàn thành |
| Nền tảng | Slice 5A → 5D | Định tuyến tường minh, regeneration, phân quyền package, observability | ✅ đã hoàn thành |
| Nền tảng | Slice 6A → 6C | Ranh giới OpenCode, disposable Git worktree, review source patch | ✅ đã hoàn thành |
| P0 + P1 | Slice 7 | Orchestrator control plane | ✅ đã hoàn thành |
| P2 | Slice 8 | Run triggers và metrics | ✅ đã hoàn thành |
| P3 (đợt 1) | Slice 9 | Approval expiry, SLA, notification, dead-letter | ✅ đã hoàn thành |
| P3 (đợt 2) | Slice 10 | Template expressions, webhook notification, env thresholds | ✅ đã hoàn thành |

Quy ước đọc: giá trị enum/wire (`VALIDATED`, `INVALID`, `WAITING_APPROVAL`, `SUCCEEDED`, `FAILED`, `SUPERSEDED`…) giữ nguyên tiếng Anh vì thuộc hợp đồng state machine; tên endpoint, biến môi trường, đường dẫn file, lệnh CLI và tên test không dịch.

---

# Phần I — Nền tảng

## Nền tảng 1 — Blueprint parsing và execution planning (Slice 2)

Trạng thái: ✅ đã hoàn thành (đợt slice 2; được slice 4 và 5B mở rộng)

Mục tiêu: xác định ranh giới planning. Một blueprint ADLC là đồ thị `Flow.data` của Langflow có marker v0.1 tường minh. Ranh giới planning parse đồ thị, phân giải đúng phiên bản node package, validate DAG và logical slot, rồi tạo một `ExecutionPlan` chỉ đọc. Planning **không bao giờ** tạo `WorkflowRun`, `TaskRun`, yêu cầu phê duyệt, artifact, log hay sự kiện thực thi.

Chuỗi xử lý: `Flow.data` đã lưu → kiểm tra marker `WORKFLOW_DEFINITION/0.1` tường minh → blueprint parser (`WorkflowDefinition`) → exact package resolver (`ResolvedNodeSpec`) → DAG + input + slot validator → projection `ExecutionPlan` bất biến. Lỗi cấu trúc cho HTTP 422; lỗi phân giải/ngữ nghĩa cho kế hoạch `INVALID`; kế hoạch đã chấp nhận mới tiến tới runtime (Slice 4).

### Biểu diễn `Flow.data` đã lưu

Ví dụ thực thi đầy đủ: `adlc-contracts/workflow/v0.1/examples/langflow-blueprint-flow-data.json`. Ánh xạ được cố tình giữ nhỏ:

| Vị trí trên đồ thị Langflow | Ý nghĩa ADLC |
|---|---|
| `/adlc` | Marker cấp flow `WORKFLOW_DEFINITION`, phiên bản contract, workflow ID, version và defaults. |
| `/nodes/{index}/data/adlc` | Một `WORKFLOW_STAGE` với intent, direct inputs, expected outputs, tham chiếu package chính xác và allowed overrides. |
| `/nodes/{index}/position` | `WorkflowStage.position`; chỉ để hiển thị, bị loại khỏi semantic digest. |
| `/edges/{index}/source` và `/target` | Quan hệ dependency giữa hai giai đoạn, theo ReactFlow node ID. |
| `/edges/{index}/data/adlc` | Edge ID ổn định (tùy chọn), điều kiện `ON_SUCCESS`, named slot bindings và metadata. |
| `/viewport` | Trạng thái hiển thị canvas gốc; compiler bỏ qua. |

Marker bắt buộc của flow:

```json
{
  "document_type": "WORKFLOW_DEFINITION",
  "schema_version": "0.1",
  "workflow_definition_id": "11111111-1111-4111-8111-111111111111",
  "version": 1
}
```

Ở v0.1, `workflow_definition_id` phải bằng `Flow.id` của Langflow đã lưu. Đồ thị có marker yêu cầu mọi node không phải presentation đều mang metadata `WORKFLOW_STAGE`; `noteNode` và `groupNode` vẫn chỉ là presentation và bị bỏ qua. Flow không marker **không bao giờ** bị suy diễn thành blueprint.

### Chuỗi biên dịch

1. Đọc flow đã lưu qua cơ chế phân quyền flow hiện có.
2. Yêu cầu marker `WORKFLOW_DEFINITION`/`0.1` chính xác.
3. Chuẩn hóa stage node và dependency edge thành một `WorkflowDefinition` khép kín.
4. Từ chối stage ID trùng, endpoint thiếu, dependency trùng, thiếu root và có chu kỳ.
5. Phân giải từng `package_id@version` chính xác qua repository registry.
6. Áp dụng package defaults và chỉ cho override nằm trong allow-list của workflow/giai đoạn.
7. Validate tương thích package và các tham chiếu đáng tin: provider, model, prompt, rule, hook, capability, Memory, Sandbox.
8. Validate direct inputs, expected outputs, named edge bindings, slot multiplicity và sự bằng nhau tuyệt đối của `schema_ref` v0.1.
9. Tạo một snapshot (ảnh chụp trạng thái) `ResolvedNodeSpec` bất biến cho mỗi giai đoạn đã phân giải.
10. Sinh nhiệm vụ theo thứ tự topological deterministic và trả về kế hoạch `VALIDATED` hoặc `INVALID`.

Lỗi parse cấu trúc trả HTTP 422 và không lưu kế hoạch. Lỗi phân giải hay validate ngữ nghĩa trả kế hoạch `INVALID` với `validation_errors` ổn định, không chứa danh sách `PlanTask` thực thi được. Cả hai đều không đụng runtime coordinator.

### Determinism và traceability

Canonical SHA-256 digest bao gồm cấu hình semantic workflow/package, loại trừ vị trí canvas, viewport và timestamp phân giải; hai đồ thị semantic tương đương cho cùng digest bất kể thứ tự key JSON hay thứ tự node. `execution_plan_id`, `resolved_node_spec_id`, `plan_task_id` là UUIDv5 deterministic, suy từ identity + version + digest của nguồn.

Mỗi nhiệm vụ giữ source stage ID, resolved spec ID và digest, phiên bản package chính xác, dependencies, inputs, effective policies, provider và environment. Regeneration tăng `plan_version`, liên kết kế nhiệm qua `supersedes_plan_id`, giữ nguyên snapshot semantic cũ và chuyển lifecycle của nó thành `SUPERSEDED`.

### HTTP API đã triển khai

| Method | Route | Kết quả |
|---|---|---|
| `GET` | `/api/v1/adlc/node-packages` | Danh sách phiên bản package chính xác caller nhìn thấy, lifecycle status và registry digest. |
| `GET` | `/api/v1/adlc/node-packages/{package_id}/versions/{version}` | Một định nghĩa package chính xác cùng digest; phiên bản ẩn dùng posture 404. |
| `POST` | `/api/v1/adlc/workflow-definitions/{workflow_id}/plans` | Parse, phân giải, validate và tạo một phiên bản kế hoạch (có phân quyền). |
| `GET` | `/api/v1/adlc/execution-plans/{plan_id}` | Đọc snapshot kế hoạch bất biến, giới hạn theo owner. |
| `POST` | `/api/v1/adlc/execution-plans/{plan_id}/regenerate` | Idempotent: biên dịch và liên kết kế hoạch kế nhiệm với kế hoạch hiện tại. |
| `POST` | `/api/v1/adlc/execution-plans/{plan_id}/validate` | Chạy lại phân giải và validate, không mutation hay thực thi. |
| `POST` | `/api/v1/adlc/execution-plans/{plan_id}/approve` | Chấp nhận snapshot kế hoạch hợp lệ cần phê duyệt. |
| `POST` | `/api/v1/adlc/execution-plans/{plan_id}/runs` | Materialize snapshot đã chấp nhận vào mock runtime. |

Owner scoping trả `PLAN_NOT_FOUND` cho cả kế hoạch không tồn tại lẫn kế hoạch của người khác. Endpoint cũ `POST /api/v1/adlc/runs` vẫn nhận đồ thị cũ không marker, nhưng trả `BLUEPRINT_REQUIRES_EXECUTION_PLAN` nếu nhận blueprint có marker — không thể bypass biên dịch.

### Kết quả validate ổn định

`BLUEPRINT_MARKER_MISSING`, `BLUEPRINT_MARKER_INVALID`, `BLUEPRINT_NODE_INVALID`, `BLUEPRINT_EDGE_INVALID`; `STAGE_ID_DUPLICATE`, `STAGE_DEPENDENCY_MISSING`, `STAGE_DEPENDENCY_CYCLE`, `WORKFLOW_HAS_NO_ROOT`; các lỗi tra cứu package, visibility, deprecation, digest, tương thích, cấu hình, override, capability registration, capability authorization, raw-secret; `STAGE_INPUT_UNBOUND`, `STAGE_INPUT_UNKNOWN`, `STAGE_OUTPUT_UNKNOWN`, `STAGE_INPUT_AMBIGUOUS`, `STAGE_BINDING_INCOMPATIBLE`.

### Ranh giới lưu trữ

Node package nằm trong repository và bất biến. Execution plans hiện copy vào một in-process store giới hạn theo owner, thread-safe — đủ để kiểm chứng versioning, tính bất biến, ownership API và hành vi compiler, nhưng cố tình **không phải** persistence production: kế hoạch mất khi restart và không chia sẻ giữa các worker. Triển khai database có thể thay thế service này mà không đổi parser, compiler, validator hay hợp đồng HTTP. Slice 5B bổ sung lineage head theo owner/workflow và bản ghi idempotency regeneration; slice 5C bổ sung `PackageAccessPolicy` process-local và deprecation overlay ngoài băng.

Nghiệm thu: các mục đã tick trong bản gốc gồm — chỉ flow có marker mới vào parsing; blueprint hai giai đoạn biên dịch deterministic; DAG/tham chiếu package/override/required input/binding sai đều thất bại trước khi tạo runtime; plan task giữ traceability stage/package/spec/digest; endpoint package và plan ép authentication + owner scoping; blueprint có marker không bypass được qua endpoint run cũ; hành vi run cũ được test hồi quy; regeneration giữ lịch sử, reset phê duyệt, chặn run mới từ kế hoạch superseded; grant package/capability hiện hành được ép ở discovery/compilation/materialization; deprecation không đổi package digest hay snapshot đã chấp nhận. Hai mục reviewer còn mở: chấp nhận ánh xạ đồ thị + ngữ nghĩa lỗi, và chấp nhận in-process storage trước khi làm UI.

---

## Nền tảng 2 — Planner proposal: proposal → validation → approval → pipeline hiện có

Trạng thái: ✅ đã hoàn thành (đợt planner proposal)

Mục tiêu: người dùng soạn một **overview workflow** (blueprint có marker, các giai đoạn chỉ mô tả intent), rồi **Planner Agent** phân rã từng giai đoạn thành các nhiệm vụ cụ thể với dependency, tính song song, gán package và expected outputs. Ranh giới thực thi **không đổi** — scheduler, materializer, run service, task state machine, adapter, execution contract đều nguyên vẹn. Planner chỉ *đề xuất*; orchestrator mới validate và phê duyệt.

```text
USER (overview workflow)
  ↓
WorkflowDefinition (marked blueprint, unchanged)
  ↓
PLANNER AGENT (mock | LLM) — proposal only
  ↓
PROPOSED PLAN (GENERATED)
  ↓
ORCHESTRATOR VALIDATION (schema, DAG, deps, packages, limits)
  ↓ VALIDATED                     ↓ REVISION_REQUIRED
APPROVED (proposal)             Regenerate → new proposal
  ↓
EXISTING ExecutionPlan pipeline (BlueprintCompiler → approve → materializer → scheduler)
```

Slice chèn package `langflow/adlc/planning/proposals/` giữa `parse_blueprint_flow` và `BlueprintCompiler` hiện có:

| Module | Trách nhiệm |
|---|---|
| `models.py` | `ProposedPlan`, `ProposedTask`, `ProposalStatus`, limits, model request/response của API |
| `planner.py` | Protocol `PlannerAgent`, `MockPlannerAgent` (deterministic), `LLMPlannerAgent` (tương thích OpenAI, structured JSON output) |
| `validator.py` | Thẩm quyền orchestrator: hơn 15 kiểm tra trên proposal không đáng tin |
| `expansion.py` | Proposal đã phê duyệt → `WorkflowDefinition` tổng hợp cho compiler hiện có |
| `service.py` | Vòng đời giới hạn theo owner: generate / validate / regenerate / reject / approve |
| `errors.py` | Mã lỗi ổn định cho bề mặt API |

### Vòng đời proposal

| Trạng thái | Ý nghĩa |
|---|---|
| `GENERATED` | Planner đã sinh nhiệm vụ; chưa validate |
| `VALIDATED` | Validation của orchestrator đã qua; sẵn sàng phê duyệt |
| `REVISION_REQUIRED` | Validation thất bại; đã ghi lỗi; regenerate kèm phản hồi |
| `REJECTED` | Bị người dùng từ chối tường minh (trạng thái cuối) |
| `APPROVED` | Đã phê duyệt và materialize thành `ExecutionPlan` |

Khi kế hoạch materialized cần plan-level approval (`approval_required=true`, ví dụ có approval stage), phê duyệt proposal **bao luôn** plan approval — kế hoạch biên dịch xong được auto-approve, tái dùng ngữ nghĩa `ExecutionPlanService.approve_plan()` mà không sửa nó. Kế hoạch không có approval gate giữ `VALIDATED`, vốn được materializer hiện có chấp nhận trực tiếp.

### Quy tắc validation (ProposalValidator)

- Mã lỗi: `EMPTY_PROPOSAL`, `TASK_LIMIT_EXCEEDED`, `DEPTH_LIMIT_EXCEEDED`, `DUPLICATE_TASK_ID`, `INVALID_DEPENDENCY`, `SELF_DEPENDENCY`, `CIRCULAR_DEPENDENCY`, `INVALID_PARENT_TASK`, `PARENT_CYCLE`, `UNKNOWN_SOURCE_STAGE`, `UNKNOWN_PACKAGE`, `MISSING_EXPECTED_OUTPUTS`, `UNKNOWN_EXPECTED_OUTPUT`, `UNKNOWN_TASK_INPUT`, `MISSING_REQUIRED_INPUT`, `INVALID_TASK_FIELD`.
- Cảnh báo: `STAGE_WITHOUT_TASKS` (một giai đoạn không nhận được nhiệm vụ nào).

### Mock planner

Template deterministic theo loại giai đoạn, fallback theo keyword cho loại chưa biết. Ví dụ phân rã overview workflow 6 giai đoạn (Requirements → Design → Implementation → Testing → Review → Approval):

| Nhiệm vụ | Phụ thuộc | Ghi chú |
|---|---|---|
| T1 Requirements Analysis | — | |
| T2 System Architecture | T1 | |
| T3 API Contract | T2 | tuần tự trong giai đoạn |
| T4 Backend Implementation | T2, T3 | song song |
| T5 Frontend Implementation | T2, T3 | song song |
| T6 Database Implementation | T2, T3 | song song |
| T7 Unit Testing | T4, T5, T6 | join |
| T8 Integration Testing | T7 | |
| T9 Code Review | T7, T8 | |
| T10 Approval Gate | T9 | approval package |

Nhiệm vụ kế thừa package của giai đoạn; required package inputs thiếu được điền từ objective của giai đoạn.

### LLM planner

Bật bằng `ADLC_PLANNER_MODE=llm`, dùng chat endpoint tương thích OpenAI:

| Biến môi trường | Mặc định |
|---|---|
| `ADLC_PLANNER_BASE_URL` | `OPENCODE_BASE_URL` hoặc `https://opencode.ai/zen/v1` |
| `ADLC_PLANNER_API_KEY` | `OPENCODE_API_KEY` |
| `ADLC_PLANNER_MODEL` | `deepseek-v4-flash-free` |
| `ADLC_PLANNER_TIMEOUT_SECONDS` | `60` |

Output phải là JSON object khớp proposal schema (ép qua `json_repair` + Pydantic). Output lỗi định dạng → `PLANNER_MALFORMED_OUTPUT` (HTTP 503); timeout → `PLANNER_TIMEOUT` (504); lỗi endpoint → `PLANNER_UNAVAILABLE` (503). Payload luôn tham chiếu giai đoạn dạng `S1..Sn` và package từ danh sách registry; tham chiếu lạ được chuẩn hóa thành placeholder rồi bị validation từ chối — orchestrator không bao giờ tin định danh do LLM đưa ra.

### HTTP API

Tất cả endpoint nằm dưới router `/api/v1/adlc`, giới hạn theo owner, không trùng route cũ:

| Method | Path | Mục đích |
|---|---|---|
| POST | `/api/v1/adlc/workflow-definitions/{workflow_id}/plan-proposals` | Sinh proposal (body: `mode`, `maxTasks`, `maxTasksPerStage`, `maxDepth`) |
| GET | `/api/v1/adlc/plan-proposals/{proposal_id}` | Đọc một proposal |
| POST | `/api/v1/adlc/plan-proposals/{proposal_id}/validate` | Validation của orchestrator |
| POST | `/api/v1/adlc/plan-proposals/{proposal_id}/approve` | Phê duyệt → materialize thành `ExecutionPlan`; trả `{proposal, execution_plan}` |
| POST | `/api/v1/adlc/plan-proposals/{proposal_id}/regenerate` | Proposal kế nhiệm (ghi `supersedes_proposal_id`) |
| POST | `/api/v1/adlc/plan-proposals/{proposal_id}/reject` | Từ chối (trạng thái cuối) |

Lệnh phê duyệt kiểm tra thêm quyền `EXECUTE` trên flow, khớp endpoint run hiện có.

### Materialization và frontend

`ProposalService.approve_proposal` bung proposal đã validate thành `WorkflowDefinition` tổng hợp (mỗi nhiệm vụ một giai đoạn, mỗi dependency một edge), đưa cho `ExecutionPlanService.create_plan` hiện có, rồi gọi `approve_plan` hiện có khi cần. Proposal ghi `materialized_plan_id`; từ đó endpoint `/execution-plans/{plan_id}/runs` nguyên vẹn materialize lần chạy qua scheduler hiện có — **không có engine thực thi thứ hai**.

Frontend: nút toolbar **Generate Plan** (chỉ trên blueprint có marker); `features/plan-proposal/plan-proposal-dialog.tsx` — trình xem proposal với trạng thái, mode/phiên bản planner, validation errors, warnings, assumptions, clarifications và **task tree** SVG phân lớp (dependency vẽ mũi tên đứt, nhiệm vụ song song đặt cạnh nhau, tô sáng từng nhiệm vụ có vấn đề); các hành động **Validate**, **Regenerate**, **Approve & Create Execution Plan** (đưa kế hoạch sang hộp thoại Plan Preview hiện có, nơi **Start mock run** chạy như trước); `stores/adlcBlueprintStore.ts` thêm proposal state kiểu additive, Run Detail và Plan Preview không đổi.

Cách demo: tạo flow rỗng → **Create Blueprint** → thêm 6 giai đoạn Requirements/Design/Implementation/Testing/Review/Approval (tham chiếu `coding-agent@0.1.0`; approval dùng `approval@0.1.0`), nối tuần tự → **Generate Plan** để thấy cây 10 nhiệm vụ với nhánh song song Backend/Frontend/Database và các điểm join → **Validate** (trạng thái `VALIDATED`, cần plan approval vì có approval stage) → **Approve & Create Execution Plan** mở Plan Preview với kế hoạch 10 nhiệm vụ đã phê duyệt → **Start mock run**, nhiệm vụ approval dừng ở `WAITING_APPROVAL` → lặp lại với `ADLC_PLANNER_MODE=llm` và credentials `OPENCODE_*` hợp lệ.

### Kiểm thử tự động

`tests/unit/adlc/planning/test_plan_proposal.py` (18 test): phân rã deterministic và độc lập nhánh song song; trùng task ID, dependency lạ, dependency vòng, package lạ, thiếu expected outputs, thiếu required input; proposal hợp lệ → approve → materialize → run end-to-end; chặn approve trước validate; flow chỉnh sửa (supersession); giới hạn số nhiệm vụ; LLM planner parse có cấu trúc/timeout/lỗi endpoint/malformed output; isolation owner.

`tests/unit/api/v1/test_adlc_proposals.py` (7 test): HTTP generate → validate → approve → endpoint run hiện có; isolation owner qua HTTP; revision-required + regenerate qua HTTP; lỗi planner/malformed output ánh xạ mã HTTP ổn định; từ chối blueprint không marker; đăng ký route.

Hoãn lại: persistence bền vững cho proposal (hiện in-process); planning tự chủ nhiều vòng và phân rã đệ quy (MVP giới hạn độ sâu); sinh proposal streaming (SSE); package testing/review chuyên dụng để gán executor đúng capability (registry hiện chỉ có `coding-agent` và `approval`).

---

# Phần II — Các slice 3 → 6C (nền tảng blueprint → runtime)

## Slice 3 — Blueprint UI và Plan Preview

Trạng thái: ✅ đã hoàn thành (đợt slice 3)

Mục tiêu: thêm con đường soạn thảo workflow cấp cao bên cạnh canvas Langflow thường: chọn node package đã publish, cấu hình một giai đoạn, nối dependency, lưu đồ thị, rồi yêu cầu compiler tạo bản preview `ExecutionPlan` bất biến — không phải nối component model, prompt, hook, tool, Memory hay Sandbox. Ranh giới: chỉ compile và preview; không tạo `WorkflowRun`.

Luồng soạn thảo: flow rỗng → **Create Blueprint** → chọn đúng phiên bản package → cấu hình intent, inputs và allowed overrides của giai đoạn → thêm stage node cấp cao → nối dependency handles → tùy chọn bind logical slot tương thích schema → lưu flow → `POST workflow-definitions/{flowId}/plans` → kế hoạch hợp lệ cho Plan Preview chỉ đọc; không hợp lệ cho lỗi node/edge có địa chỉ path.

Chỉ flow có marker tường minh `Flow.data.adlc` `WORKFLOW_DEFINITION/0.1` mới vào Blueprint mode; flow thường giữ component editor và hành vi **Run as ADLC**. Sau khi đánh dấu, thêm component cấp thấp bị từ chối — giai đoạn phải thêm qua package picker; node ghi chú chỉ để presentation vẫn hợp lệ; Playground, deploy và nút run ADLC cũ bị ẩn, nên slice không mở đường thực thi nào. Blueprint chỉ đọc/khóa vẫn compile và inspect snapshot đã lưu.

### Cấu trúc frontend

| Khu vực | Trách nhiệm |
|---|---|
| `CustomNodes/AdlcStageNode` | Vẽ một giai đoạn với dependency handles, định danh package, tóm tắt provider/policy và trạng thái validation. |
| `CustomEdges/AdlcEdge.tsx` | Vẽ một dependency, sửa named slot binding tương thích, hiển thị lỗi edge. |
| `features/adlc-blueprint/stage-editor-dialog.tsx` | Package picker và cấu hình giai đoạn theo schema. |
| `features/adlc-blueprint/plan-preview-dialog.tsx` | Xem chỉ đọc: nhiệm vụ, thứ tự, dependency, cấu hình đã phân giải, policy, thành phần runtime, digest, warnings, errors. |
| `components/core/flowToolbarComponent/components/adlc-blueprint-controls.tsx` | Bật Blueprint mode, thêm giai đoạn, lưu, compile, mở preview. |
| `stores/adlcBlueprintStore.ts` | Giữ preview state và ánh xạ lỗi node/edge tạm thời ngoài ngữ nghĩa đồ thị được persist. |
| `utils/adlc-blueprint.ts` | Phát hiện marker, chuẩn hóa canvas, metadata tương thích, ánh xạ compiler-path → canvas. |
| `controllers/API/adlc.ts` | Lời gọi API typed cho catalogue package và execution plan. |

### Hành vi đồ thị đã lưu

Contract persist giữ nguyên ánh xạ đã phê duyệt ở Nền tảng 1: `Flow.data.adlc` chứa marker workflow; `node.data.adlc` chứa contract `WORKFLOW_STAGE`; `edge.data.adlc` chứa contract `WORKFLOW_EDGE` và named bindings; position/viewport là dữ liệu presentation; các trường tương thích của canvas Langflow không được backend compiler đọc. Khi load, stage record có marker được chuẩn hóa về renderer `adlcStageNode`/`adlcEdge`, giúp ví dụ canonical (node ReactFlow persist kiểu `genericNode`) mở an toàn. Flow store giờ giữ metadata cấp cao lạ khi node/edge thay đổi, nên `Flow.data.adlc` sống qua chỉnh sửa, autosave và mở lại.

### Quy tắc cấu hình giai đoạn

Editor lấy package từ `GET /api/v1/adlc/node-packages` và pin đúng `package_id@version`. Trường chung: tên giai đoạn và objective; direct logical inputs lấy từ input interface của package (required input có thể thay bằng edge binding); expected outputs lấy từ output interface; control cấu hình package chỉ sinh từ `configuration_schema.properties`. Control timeout/model chỉ hiện khi JSON Pointer tương ứng nằm trong `override_allowlist`; defaults thuộc package, đồ thị chỉ lưu giá trị override; raw secret và control secret bị loại bỏ cố ý.

Edge luôn nghĩa là "target phụ thuộc source"; hộp thoại binding chỉ cung cấp cặp output/input cùng `schema_ref`, nếu không có thì edge là dependency-only và target dùng direct input.

### Hành vi compile và lỗi

**Validate & Preview** lưu canvas mới nhất trước rồi gọi `POST /api/v1/adlc/workflow-definitions/{flowId}/plans`:

- Kế hoạch `VALIDATED` hiển thị thứ tự nhiệm vụ topological, phiên bản package, dependency, cấu hình/policy hiệu lực, tham chiếu provider/Memory/Sandbox và digest; kế hoạch `INVALID` hiển thị `validation_errors` ổn định, không có nhiệm vụ thực thi được.
- HTTP `422` cấu trúc đọc `ServiceError.details.issues` và dùng cùng preview.
- Finding tại `/nodes/{index}`, `/stages/{index}` tô sáng giai đoạn; `/edges/{index}` tô sáng dependency; finding đồ thị `/edges` tô sáng mọi ADLC dependency; tô sáng là tạm thời, biến mất sau khi chỉnh đồ thị.
- Copy/nhân đôi giai đoạn hay dependency gán contract ID mới (tránh trùng identity); gom nhóm giai đoạn bị tắt vì group sẽ phá đơn vị soạn một-giai-một-nhiệm-vụ.

Slice 3 ban đầu dừng ở preview chỉ đọc; slice 4 sau đó thêm **Accept plan** và **Start mock run** mà không đổi cách soạn giai đoạn.

### Review thủ công

Backend từ `adlc-flow`: `.venv\Scripts\python.exe -m langflow.__main__ run --port 7860 --backend-only`; frontend từ `adlc-flow/frontend`: `npm run dev`. Sau đó: tạo flow rỗng → **Create Blueprint** (đồ thị component có sẵn cố tình không được chuyển tại chỗ) → thêm giai đoạn `coding-agent@0.1.0` và `approval@0.1.0` → dựng `Plan -> Implement Backend`, `Plan -> Implement UI`, cả hai đổ vào `Verify`, rồi `Verify -> Approval` (kéo từ handle phải sang handle trái của giai đoạn phụ thuộc) → kiểm tra binding qua nút liên kết tròn trên edge (các mock package thường dependency-only vì schema khác nhau) → **Validate & Preview**: kế hoạch `VALID`, 5 nhiệm vụ đúng thứ tự, plan approval bắt buộc → xóa direct `requirement` của một coding stage rồi compile lại: preview báo `STAGE_INPUT_UNBOUND`, node bị tô sáng → mở lại flow: marker, giai đoạn, edge, phiên bản package, cấu hình, position còn nguyên → flow không marker vẫn chạy **Run as ADLC** qua đường cũ.

### Ranh giới persistence

Blueprint bền vững qua record Langflow Flow hiện có; kế hoạch sinh ra nằm trong in-process store theo owner (Slice 2). Trước production/multi-worker, thay plan store bằng database phía sau planning service interface hiện có — UI và API contract không cần đổi.

---

## Slice 4 — Từ kế hoạch đã chấp nhận đến mock runtime

Trạng thái: ✅ đã hoàn thành (đợt slice 4)

Mục tiêu: đóng đường đi đầu tiên từ package đến runtime — blueprint đã lưu → compile → kế hoạch `VALIDATED` (snapshot đã phân giải + digests) → Accept plan nếu `approval_required` → plan materializer → `WorkflowRun` + một `TaskRun` cho mỗi `PlanTask` → scheduler hiện có → port `TaskExecutor` → mock Sandbox + Memory, Agent + Testing adapters; giai đoạn approval cho `WAITING_APPROVAL`, Approve → `SUCCEEDED`, Reject → `FAILED`. Đường `POST /api/v1/adlc/runs` cũ dành cho flow không marker (slice 5A làm rõ mode `LEGACY_FLOW`). Blueprint có marker chỉ chạy từ một `ExecutionPlan` đã chấp nhận; materializer không chuẩn hóa node canvas hay tra lại package registry.

Vòng đời kế hoạch: kế hoạch hợp lệ `approval_required=false` materialize từ `VALIDATED`; kế hoạch `approval_required=true` phải đi `VALIDATED` → `APPROVED` trước; sau khi aggregate runtime đầu tiên được tạo, kế hoạch chuyển `EXECUTING`; kế hoạch `INVALID`, chưa phân giải, cần phê duyệt mà chưa được duyệt, bị từ chối hay đã superseded không materialize được; phê duyệt kế hoạch và materialization đều theo owner.

Plan approval và workflow approval là hai chuyện khác nhau:

| Quyết định | Ý nghĩa | Xảy ra khi nào |
|---|---|---|
| **Accept plan** | Chấp nhận đồ thị nhiệm vụ, phiên bản package đã phân giải, cấu hình, policy và digest làm đầu vào runtime. | Trước khi lần chạy được tạo. |
| **Approve / Reject** | Giải quyết một nhiệm vụ `Approval` đã nằm trong workflow đang chạy. | Khi scheduler đi tới giai đoạn đó. |

### HTTP API

Chấp nhận kế hoạch:

```http
POST /api/v1/adlc/execution-plans/{planId}/approve
Content-Type: application/json

{}
```

Có thể kèm `{ "comment": "..." }` để ghi bối cảnh review; response là cùng kế hoạch với `status=APPROVED`, `approved_by`, `approved_at`.

Tạo lần chạy từ kế hoạch đã chấp nhận:

```http
POST /api/v1/adlc/execution-plans/{planId}/runs
Content-Type: application/json

{ "idempotencyKey": "one-caller-generated-key" }
```

Endpoint kiểm tra quyền `EXECUTE` hiện hành trên Langflow flow nguồn trước khi materialize. Cùng owner + plan ID + idempotency key trả cùng lần chạy trong bộ nhớ; key khác có thể tạo lần chạy khác từ cùng snapshot.

Mã xung đột ổn định của slice: `PLAN_NOT_ACCEPTED` (kế hoạch không hợp lệ hoặc chưa nhận plan approval bắt buộc), `PLAN_INTEGRITY_MISMATCH` (snapshot đã lưu không còn hash khớp digest đã ghi), `PLAN_STATE_CONFLICT` (lệnh lifecycle không hợp lệ cho trạng thái kế hoạch), `PLAN_GATE_UNSUPPORTED` (runtime mock v0.1 không giữ được ngữ nghĩa gate đã yêu cầu).

### Ánh xạ materialization

| Nguồn kế hoạch | Đích runtime |
|---|---|
| `ExecutionPlan.execution_plan_id` | `WorkflowRun.execution_plan_id` và payload sự kiện workflow |
| `PlanTask.plan_task_id` | `TaskRun.task_definition_id`, khóa định nghĩa runtime ổn định, và traceability |
| `dependency_task_ids` | `dependency_task_run_ids` |
| `inputs` | `TaskRequest.input.namedInputs` |
| `input_bindings` | Named inputs đã phân giải cộng `TaskRequest.context.resolved_input_bindings` |
| Kết quả/artifact thượng nguồn | `TaskRequest.context.upstream_results` và `artifact_refs` |
| Implementation của package | `TaskRequest.executor.service` và `operation` |
| Execution profile | Capability executor, tham chiếu Memory/Sandbox, metadata request |
| Effective policies | Timeout, số lần thử tối đa, priority, permissions, resources trong `TaskRequest.constraints` |
| Cấu hình package | Mock delay, lỗi giả lập, tên artifact, phần trình bày approval |

Mọi `TaskRun`, sự kiện nhiệm vụ, `TaskRequest`, `TaskResult`, `Artifact` và `ApprovalRequest` runtime suy từ kế hoạch đều mang:

```text
execution_plan_id
plan_task_id
source_workflow_stage_id
resolved_node_spec_id
package_id
package_version
package_content_digest
resolved_node_digest
```

Trước khi ánh xạ, materializer tính lại từng `ResolvedNodeSpec.resolved_digest` từ snapshot đã lưu, dùng package content digest và các trường đã phân giải đúng như lưu — cập nhật registry sau đó không thể âm thầm đổi lần chạy này.

### Quyền sở hữu runtime

- `ExecutionPlanMaterializer` validate snapshot đã chấp nhận và tạo định nghĩa runtime đã chuẩn hóa; `AdlcRunService` vẫn là người viết duy nhất của trạng thái `WorkflowRun`, `TaskRun`, phê duyệt và sự kiện.
- Scheduler tiếp tục mở khóa dependency và dispatch qua port `TaskExecutor` hiện có; `MockSandboxAdapter`, `MockMemoryAdapter`, `MockAgentAdapter`, `MockTestingAdapter` vẫn là thành phần thực thi mặc định — chưa nối OpenCode hay Sandbox/Memory/Testing thật.
- Retry tuân thủ `max_attempts` của kế hoạch; cờ mock `simulate_failure` được xóa cho lần retry, giữ demo phục hồi deterministic.
- Package approval mặc định dùng gate `ACTION`: phê duyệt phát `WAITING_APPROVAL -> RUNNING -> SUCCEEDED` trên cùng lần thử; từ chối phát `WAITING_APPROVAL -> FAILED`, khớp task state machine đóng băng.

### Review thủ công và kiểm thử

Review: mở blueprint 5 giai đoạn → **Validate & Preview** (`VALID`, **Plan approval: Required**) → **Accept plan** → **Start mock run**: Plan, Implement Backend, Implement UI, Verify đạt `SUCCEEDED`, Approval ở `WAITING APPROVAL`, mỗi nhiệm vụ hiển thị phiên bản package và plan-task identity rút gọn → **Approve** để workflow thành `SUCCEEDED` → lặp lại với `simulate_failure=true` để thấy lần chạy tạm dừng, **Retry** mở khóa việc hạ nguồn, rồi tới runtime approval → flow không marker vẫn đi đường legacy.

Kiểm thử tự động phủ: vòng lifecycle plan approval và isolation owner; từ chối kế hoạch bắt buộc phê duyệt trước khi tạo runtime; materialize trực tiếp khi không cần phê duyệt; revalidate digest trước materialization; thực thi 5 nhiệm vụ theo dependency, nhánh song song, runtime approval; ánh xạ TaskRequest và traceability end-to-end trên results/artifacts/approvals/events; retry và mở khóa hạ nguồn từ cấu hình package; bề mặt HTTP authorization và tạo plan-to-run idempotent; hồi quy runtime legacy saved-flow.

Persistence hoãn lại: plans, plan approvals, idempotency records, runs, events, results, artifacts vẫn process-local; slice tương lai cần persist phía sau service boundary hiện có với unique key `(owner_id, execution_plan_id, idempotency_key)`. Slice 5B bổ sung lineage regeneration theo [ADR 0005](../adr/0005-versioned-plan-regeneration-and-supersession.md).

---

## Slice 5A — Định tuyến thực thi tường minh và di chuyển thủ công

Trạng thái: ✅ đã hoàn thành (đợt slice 5A)

Mục tiêu: siết ranh giới giữa prototype saved-flow ban đầu và Blueprint runtime dựa trên package. Execution mode giờ là trường tường minh của request và runtime; nhãn canvas hay display name của component không bao giờ chọn đường runtime hay tạo ngữ nghĩa phê duyệt.

Hợp đồng định tuyến:

| Nguồn | Điểm vào | Mode bắt buộc/gán | Đầu vào semantic |
|---|---|---|---|
| Canvas ADLC cũ không marker | `POST /api/v1/adlc/runs` | Caller phải gửi `LEGACY_FLOW` | Saved nodes và edges chuẩn hóa lúc request |
| Blueprint có marker | `POST /api/v1/adlc/execution-plans/{planId}/runs` | Server gán `EXECUTION_PLAN` | Kế hoạch bất biến đã chấp nhận + resolved-node snapshot |
| Demo workflow đóng băng | `POST /api/v1/adlc/mock/runs` | Server gán `MOCK_WORKFLOW` | Fixture 5 nhiệm vụ sở hữu bởi code |
| Workflow Langflow thuần | Các API Langflow hiện có | Ngoài hợp đồng mode ADLC | Thực thi đồ thị Langflow native |

Request legacy phải tường minh:

```json
{
  "flowId": "<flow UUID>",
  "executionMode": "LEGACY_FLOW",
  "delayMs": 50
}
```

Thiếu `executionMode` → lỗi request validation `422`; gửi mode khác tới `/api/v1/adlc/runs` → `409` với `EXECUTION_MODE_MISMATCH`; gửi blueprint có marker tới endpoint legacy vẫn trả `BLUEPRINT_REQUIRES_EXECUTION_PLAN`. Mọi response `WorkflowRun` và payload sự kiện đầu tiên ghi mode đã chọn. `AdlcRunService` từ chối plan ID nếu mode không phải `EXECUTION_PLAN`, và từ chối `EXECUTION_PLAN` thiếu plan ID — bất biến được giữ cả dưới tầng HTTP.

### Ranh giới legacy normalizer

`flow_dag.py` cũ đổi tên thành `langflow/adlc/legacy_flow_normalizer.py::normalize_legacy_flow_graph`; `flow_dag.py::read_adlc_task_graph` giữ làm alias tương thích. Khả năng tương thích cố ý hẹp: mọi node không phải note/group thành nhiệm vụ mock; canvas edge thành dependency; `data.adlc.enabled=false` cho node từ chối tham gia; phê duyệt yêu cầu metadata sở hữu bởi ADLC.

Node tên `Approval` hay component có display type `Approval` giờ là nhiệm vụ thường. Để tạo approval gate legacy, lưu khai báo tường minh trên node:

```json
{ "data": { "adlc": { "approvalGate": "AFTER_TASK" } } }
```

Hai dạng tương thích `{ "approval": true }` và `{ "kind": "approval" }` cũng được nhận. Blueprint mới không dùng các trường legacy: approval stage phân giải `approval@0.1.0`, và policy snapshot bất biến của package định nghĩa gate.

### Di chuyển orchestrator thủ công

Fixture nguồn cấp thấp còn tại `adlc_components/flow/orchestrator.json` (7 component Langflow nối tay, không marker) — giữ làm tham chiếu phát triển package. `adlc_components/flow/orchestrator-blueprint.json` là bản di chuyển thủ công đã review: một giai đoạn cấp cao `Orchestrator` pin `coding-agent@0.1.0`, một direct input `requirement`, không wiring component nội bộ.

| Mối quan tâm của component nguồn | Biểu diễn dựa trên package |
|---|---|
| Agent component | package `implementation.adapter_ref` và `entrypoint` |
| OpenCode model component | `execution_profile.model_ref` (tham chiếu mock ở v0.1) |
| Orchestrator prompt builder | `execution_profile.system_prompt_ref` |
| Task toolkit | capability `tool_refs` |
| Task system hook | `hook_refs` |
| Chat input/output wiring | logical input `requirement` và output `source_patch` |
| Memory và Sandbox wiring | tham chiếu policy của package, cả hai mock ở v0.1 |

Đây là di chuyển semantic thủ công, không phải thuật toán chuyển tự động; không nối OpenCode hay provider thật nào.

### Tính bất biến của kế hoạch đã chấp nhận

Materialization chỉ tiêu thụ bản sao kế hoạch do `ExecutionPlanService` giữ, không gọi package resolver hay đọc lại canvas; trước khi tạo lần chạy nó tính lại plan digest và resolved-node digest, và các nhiệm vụ runtime giữ nguyên digest đã chấp nhận. Hồi quy tắt toàn bộ quyền truy cập resolver sau khi kế hoạch được chấp nhận, materialize lần chạy và kiểm tra traceability lịch sử khớp chính xác snapshot — thay đổi catalogue package sau đó không thể ảnh hưởng kế hoạch đã chấp nhận hay lần chạy đã lưu; muốn dùng phiên bản package mới phải compile và chấp nhận phiên bản kế hoạch mới.

UI: flow không marker hiển thị **Legacy flow** cạnh **Run as ADLC**; flow có marker hiển thị **Blueprint plan** cạnh các control kế hoạch; Run Detail hiển thị mode nguồn đã ghi của lần chạy.

Review thủ công: flow không marker có nhãn **Legacy flow** ở cả toolbar lẫn Run Detail; node thường tên `Approval` không kèm metadata gate chạy xong không dừng phê duyệt; thêm `data.adlc.approvalGate=AFTER_TASK` rồi chạy lại thì dừng với **Approve**/**Reject**; import `adlc_components/flow/orchestrator-blueprint.json` hiện một giai đoạn `Orchestrator` và nhãn **Blueprint plan**; validate phân giải `coding-agent@0.1.0`; chấp nhận và chạy thấy traceability package/digest trên nhiệm vụ; `orchestrator.json` gốc vẫn là fixture 7 node không marker.

Hoãn cho các slice 5 sau: persistence database cho plans/runs/idempotency records/events/results/artifacts; persistence bền vững cho lịch sử supersession (Slice 5B); grant package bền vững và metadata lifecycle (Slice 5C); telemetry storage bền vững, metrics, dashboard, alerting (Slice 5D); chuyển đổi tự động đồ thị component tùy ý; OpenCode hay Sandbox/Memory/Testing thật.

---

## Slice 5B — Regeneration và supersession của kế hoạch

Trạng thái: ✅ đã hoàn thành (đợt slice 5B)

Mục tiêu: kế hoạch blueprint có lineage phiên bản tường minh. Regeneration biên dịch blueprint đã lưu mới nhất thành snapshot (ảnh chụp trạng thái) mới, liên kết với phiên bản trước, reset plan approval, và biến kế hoạch cũ thành lịch sử. Nội dung đã phân giải của kế hoạch cũ và mọi lần chạy đã tạo từ nó giữ nguyên.

Luồng: `POST /execution-plans/{v1}/regenerate` (kèm `idempotencyKey`) → đọc blueprint đã lưu mới nhất → biên dịch kế nhiệm từ v1 → lưu v2 với `supersedes_plan_id=v1` → đánh dấu v1 `SUPERSEDED` → trả v2 `VALIDATED` hoặc `INVALID` với phê duyệt đã xóa → người dùng chấp nhận v2 (khi cần) → chạy từ v2.

### Hành vi API

Sinh kế hoạch đầu tiên hoặc mới nhất: `POST /api/v1/adlc/workflow-definitions/{workflowId}/plans`. Lần gọi đầu tạo version 1; nếu service đã có kế hoạch hiện hành cho cặp owner/workflow, endpoint tạo phiên bản kế tiếp, liên kết và supersede kế hoạch hiện hành — fallback giữ lineage đúng sau khi reload trang trong khi storage còn process-local.

Regenerate tường minh: `POST /api/v1/adlc/execution-plans/{planId}/regenerate` với request:

```json
{
  "idempotencyKey": "4a73b7a6-6a25-4ddb-8f73-8b1ab09caf25"
}
```

Response thành công là `ExecutionPlan` mới, bao gồm:

```json
{
  "plan_version": 2,
  "status": "VALIDATED",
  "supersedes_plan_id": "<version-1-plan-id>"
}
```

- Request được xác thực, theo owner, chỉ đọc flow nguồn gắn với tiền nhiệm; lặp lại cùng idempotency key trả cùng kế hoạch kế nhiệm; regenerate tiền nhiệm đã superseded hoặc không phải mới nhất với key khác → `409 PLAN_STATE_CONFLICT`; kế nhiệm không bao giờ thừa kế `approved_by`, `approved_at`, hay trạng thái `APPROVED`.

`GET /execution-plans/{planId}` vẫn trả kế hoạch đã superseded, nhưng các lệnh sau bị từ chối trên nó: `POST /execution-plans/{planId}/validate`, `POST /execution-plans/{planId}/approve`, và request mới `POST /execution-plans/{planId}/runs`. Nếu kế hoạch cũ đã tạo lần chạy, replay đúng materialization idempotency key trả cùng lần chạy; lần chạy có thể tiếp tục qua retry nhiệm vụ hay runtime approval vì trạng thái runtime độc lập với lifecycle kế hoạch.

### Bất biến snapshot

Khi version 2 supersede version 1:

| Trường/hành vi | Version 1 | Version 2 |
|---|---|---|
| Trạng thái kế hoạch | Chỉ đổi sang `SUPERSEDED` | `VALIDATED` hoặc `INVALID` mới |
| Nhiệm vụ và resolved specs | Giữ nguyên | Biên dịch lại từ blueprint đã lưu mới nhất |
| Digests | Giữ nguyên | Tính lại từ nội dung semantic mới nhất |
| Provenance phê duyệt | Giữ lại cho lịch sử | Rỗng; cần quyết định mới |
| Lần chạy mới | Bị từ chối | Chỉ cho phép sau khi qua validate/phê duyệt |
| Lần chạy hiện có | Tiếp tục và đọc được | Không bị ảnh hưởng |

Lỗi parse cấu trúc không tạo kế hoạch mới. Lỗi biên dịch ngữ nghĩa tạo kế hoạch kế nhiệm `INVALID` và supersede kế hoạch cũ — tránh vô tình chạy một cấu hình cũ đã chấp nhận.

Frontend: Plan Preview hiển thị cả lifecycle status lẫn validation status, đúng phiên bản kế hoạch, chỉ ra tiền nhiệm khi có `supersedes_plan_id`, giải thích rằng phê duyệt không kế thừa, cung cấp **Generate new plan** với request idempotent, và ẩn các hành động chấp nhận/chạy với kế hoạch `SUPERSEDED`. Canvas và giao diện Langflow thường không đổi.

Kiểm thử tự động phủ: phiên bản tăng đơn điệu và liên kết tiền nhiệm; nội dung kế hoạch cũ và provenance phê duyệt giữ nguyên sau supersession; approval reset trên kế nhiệm; regeneration cùng key idempotent; tiền nhiệm stale từ chối request regeneration khác key; kế hoạch superseded không revalidate hay chạy lần chạy mới được; lần chạy lịch sử vẫn đọc được và kết thúc runtime approval; ownership kế hoạch ép qua cả service lẫn HTTP; định tuyến API frontend bao phủ lệnh regeneration.

Quy trình phê duyệt thủ công: validate blueprint chứa approval stage → Plan Preview hiện version 1, `VALIDATED`, cần plan approval → chấp nhận (có thể chạy mock run) → **Generate new plan** → version 2 hiện ra, tham chiếu kế hoạch trước, lại yêu cầu chấp nhận → version 1 báo `SUPERSEDED`, không chạy lần chạy mới được → nếu version 1 đã tạo lần chạy, hoàn tất runtime Approval, lần chạy vẫn thành công → đổi một direct input, lưu, validate lại để sinh phiên bản mới với nội dung phân giải mới, các phiên bản cũ giữ nguyên lịch sử.

Persistence database hoãn lại: `ExecutionPlanService`, regeneration idempotency records, materialization idempotency records và runtime records vẫn trong bộ nhớ tiến trình. Repository tương lai nên dùng một transaction khóa lineage head owner/workflow, chèn kế nhiệm, đánh dấu tiền nhiệm superseded và ghi idempotency key; ràng buộc khuyến nghị nằm trong [ADR 0005](../adr/0005-versioned-plan-regeneration-and-supersession.md). Thay đổi này không đổi scheduler hay luồng Plan Preview.

---

## Slice 5C — Phân quyền package và capability

Trạng thái: ✅ đã hoàn thành (đợt slice 5C)

Mục tiêu: thêm ranh giới authorization đầu tiên quanh hệ thống node package dựa trên repository, không thêm database hay đổi scheduler. Package discovery lọc theo caller; blueprint compilation kiểm tra cả grant package lẫn capability; materialization mới của execution plan kiểm tra lại quyền hiện hành từ snapshot đã chấp nhận. Vẫn dùng `MockAgentAdapter`, `MockSandboxAdapter`, `MockMemoryAdapter`, `MockTestingAdapter`.

Các ranh giới đã triển khai:

| Ranh giới | Hành vi |
|---|---|
| Danh sách package | Chỉ trả phiên bản chính xác mà `current_user.id` nhìn thấy. |
| Đọc package chính xác | Phiên bản ẩn và không tồn tại cùng dùng posture HTTP 404; phiên bản ẩn mang `PACKAGE_NOT_VISIBLE`. |
| Compiler | Đưa plan owner làm authorization subject cho từng lần phân giải package. |
| Trusted references | Tham chiếu lạ thất bại trước với `CAPABILITY_NOT_REGISTERED`. |
| Capability authorization | Tham chiếu đã đăng ký nhưng không được cấp thất bại với `CAPABILITY_NOT_AUTHORIZED`. |
| Plan materialization | Kiểm tra lại định danh package và tham chiếu chính xác trước khi tạo lần chạy mới. |
| Đọc lịch sử | Plans và runs theo owner vẫn đọc được sau khi quyền bị thu hồi. |
| Idempotent replay | Request đã tạo lần chạy trả cùng lần chạy, không tạo việc mới. |
| Deprecation | `lifecycle_status` báo `DEPRECATED` mà không đổi `status` đã ký của package; phân giải mới thất bại với `PACKAGE_DEPRECATED`. |

### Triển khai policy

`PackageAccessPolicy` là application port thay thế được; `InMemoryPackageAccessPolicy` là triển khai đầu tiên, giữ: phiên bản package chính xác mặc định được nhìn thấy; tham chiếu opaque mặc định được cấp quyền; override grant hoàn chỉnh theo subject (tùy chọn); và tập phiên bản package deprecated ngoài băng. Factory mặc định cấp các package hiện hành `coding-agent@0.1.0` và `approval@0.1.0` cùng các tham chiếu mock/control. API sở hữu một policy process-local cache và đưa cùng object cho catalogue projection, compiler resolution và materialization. Đây là cấu hình kiểm thử được, không phải kho identity production; không đưa thêm hệ thống authorization thứ hai vào scheduler.

### Hành vi compile

Với từng giai đoạn, phân giải kiểm tra theo thứ tự: (1) load package chính xác từ repository registry đáng tin; (2) subject có thấy phiên bản chính xác đó; (3) áp trạng thái deprecation bên ngoài; (4) validate tương thích engine và execution contract; (5) chỉ áp override được package cho phép và validate cấu hình; (6) mọi tham chiếu implementation, provider, model, prompt, rule, hook, Memory, Sandbox, tool, skill, plugin, MCP đều đã đăng ký; (7) subject được cấp quyền cho tất cả các tham chiếu đó.

Lỗi truy cập được chuyển thành `PlanValidationIssue` bình thường có địa chỉ path kèm `stage_id` bị ảnh hưởng, nên Plan Preview dùng danh sách lỗi và tô sáng node hiện có mà không cần đường lỗi frontend riêng.

### Hành vi materialization và frontend

Materialization không tra JSON package hiện hành: đọc yêu cầu truy cập từ từng `ResolvedNodeSpec` đã chấp nhận, kiểm tra grant hiện hành, validate kế hoạch và digest đã lưu, rồi mới gọi run service hiện có. Nhờ đó thay đổi package không thể đổi ngữ nghĩa đã chấp nhận, và thu hồi quyền có thể chặn lần thực thi mới. Riêng deprecation không thu hồi quyền truy cập kế hoạch đã chấp nhận; thu hồi tường minh visibility hay capability grant mới có.

Frontend: package không truy cập được vắng mặt vì package query tiêu thụ API đã lọc; package visible nhưng deprecated hiển thị badge **Deprecated** trong picker và trên stage card; mục picker deprecated và hành động lưu stage bị tắt cho soạn mới; lỗi truy cập từ compiler xuất hiện trong Plan Preview và tô sáng giai đoạn.

### Mã lỗi ổn định

| Mã | Ý nghĩa | Kết quả planning | Posture HTTP trực tiếp/runtime |
|---|---|---|---|
| `PACKAGE_NOT_VISIBLE` | Phiên bản chính xác tồn tại nhưng bị ẩn với subject. | Vấn đề kế hoạch `INVALID` | 404 |
| `CAPABILITY_NOT_AUTHORIZED` | Tham chiếu đáng tin nhưng không được cấp cho subject. | Vấn đề kế hoạch `INVALID` | 403 |
| `CAPABILITY_NOT_REGISTERED` | Tham chiếu không có trong registry deployment đáng tin. | Vấn đề kế hoạch `INVALID` | Không áp dụng |
| `PACKAGE_DEPRECATED` | Phiên bản đã nghỉ cho công việc planning mới. | Vấn đề kế hoạch `INVALID` | Catalogue vẫn đọc được |

Phạm vi xác minh: subject hạn chế chỉ thấy package được cấp và không fetch được phiên bản ẩn; tham chiếu tay tới package ẩn sinh `PACKAGE_NOT_VISIBLE` trên giai đoạn; package visible chứa tool bị từ chối sinh `CAPABILITY_NOT_AUTHORIZED`; deprecation đổi trạng thái catalogue mà không đổi byte/digest package; revalidation sau deprecation báo `PACKAGE_DEPRECATED` mà không đụng kế hoạch đã chấp nhận; kế hoạch đã chấp nhận dù deprecated vẫn chạy khi grant còn hiệu lực; thu hồi capability chặn materialization mới trong khi idempotent run hiện có và lần đọc run lịch sử vẫn khả dụng.

Reviewer walkthrough (tóm lược): picker chỉ chứa package của catalogue đã xác thực; fixture chỉ cấp `approval@0.1.0` thì Coding Agent biến mất và tra cứu trực tiếp trả `PACKAGE_NOT_VISIBLE`; khôi phục visibility nhưng gỡ `tool:mock-artifact` thì Plan Preview báo `CAPABILITY_NOT_AUTHORIZED` trên stage Coding Agent; đánh dấu `coding-agent@0.1.0` deprecated trong lifecycle overlay thì digest không đổi, badge xuất hiện, compilation mới báo `PACKAGE_DEPRECATED`; snapshot đã chấp nhận không đổi và chạy được khi grant còn; thu hồi tool grant thì lần chạy mới bị từ chối nhưng lần chạy cũ vẫn đọc được. Quyết định ràng buộc: [ADR 0006](../adr/0006-package-and-capability-authorization.md).

---

## Slice 5D — Observability vận hành

Trạng thái: ✅ đã hoàn thành (đợt slice 5D)

Mục tiêu: thêm seam observability có kiểu, thay thế được, an toàn secret quanh đường package-to-runtime: người vận hành đối chiếu được package resolution, plan validation, plan materialization và mọi lần dispatch runtime mà không đổi scheduler, adapter, state machine, API response hay frontend. Composition production xuất observation qua structured logger của Langflow; test và exporter tương lai inject `AdlcObservabilitySink` khác (kèm in-memory sink kiểm chứng độc lập toàn đường). Vẫn chỉ dùng adapter mock.

Bốn event type được phát qua sink: `adlc.package_resolution.completed` (mỗi attempt phân giải giai đoạn; phân giải thành công thêm phiên bản package đáng tin, resolved spec và digests), `adlc.plan_validation.completed` (mỗi lần gọi compiler; kèm số resolved/task/error và mã issue ổn định), `adlc.plan_materialization.completed` (mỗi request materialization; kèm số nhiệm vụ, cờ replay), `adlc.task_dispatch.completed` (mỗi attempt nhiệm vụ runtime kể cả retry; kèm plan/run/task/attempt IDs, phiên bản package và digests, executor service, số artifact).

### Contract v0.1

`AdlcOperationObservation` là model đóng — trường lạ làm validation thất bại. Mỗi record có observation ID, event type, outcome cardinality thấp, completion time theo timezone, duration đơn điệu. Kết quả: `SUCCEEDED`, `DENIED`, `FAILED` (dispatch thêm `CANCELLED`).

Kế hoạch `INVALID` do người dùng soạn là kết quả được quan sát `INVALID`, không phải lỗi hạ tầng. Lần phân giải package hay materialization bị từ chối đơn lẻ là `DENIED`; kết quả compiler bao ngoài vẫn là kế hoạch `INVALID`. Observation thất bại chứa `error_code` máy ổn định; message và chi tiết exception thô không bao giờ được chiếu ra.

### Chính sách dữ liệu

Contract observation chỉ allow-list: ID workflow, plan, run, giai đoạn, nhiệm vụ, attempt, resolved-spec đã sinh; định danh package đáng tin, phiên bản chính xác, package digest và resolved-node digest sau khi phân giải thành công; event type, outcome, timestamp, duration, executor service, mã lỗi/validation ổn định; các số đếm không chứa nội dung (nhiệm vụ, resolved node, issue, artifact, số attempt).

Cố ý **không có** trường cho: tên giai đoạn, objective, prompt, requirement, direct input, giá trị binding đã phân giải, output thượng nguồn; cấu hình package, execution context, biến, thân policy, kết quả nhiệm vụ, tên/URI/nội dung artifact, log; exception thô, authorization subject, credential, raw secret, tham chiếu secret opaque.

Structured sink đưa projection đã rút gọn vào logging pipeline hiện có của Langflow, nên redaction và JSON rendering đã cấu hình vẫn áp dụng, cùng correlation OpenTelemetry và log export khi bật. Lỗi observation contract và telemetry export bị chặn, chỉ sinh cảnh báo tối thiểu `adlc.observability.emit_failed`; record hỏng hay exporter không khả dụng không thể đổi hành vi planning hay thực thi.

### Traceability runtime

Với lần chạy theo execution plan, một dispatch record mang cùng chuỗi trace bất biến vốn có trên metadata của `TaskRun`, `TaskResult`, `Artifact` và `RunEvent` thay đổi trạng thái:

```text
workflow_definition_id
  -> execution_plan_id
  -> plan_task_id
  -> source_workflow_stage_id
  -> resolved_node_spec_id
  -> package_id + package_version + package_content_digest
  -> resolved_node_digest
  -> workflow_run_id
  -> task_run_id
  -> attempt_id
```

Lần chạy legacy saved-flow cũng phát dispatch observation nhưng thiếu các trường đối chiếu plan/package vì đường đó không có `ExecutionPlan` đã chấp nhận. Prototype độc lập `/adlc/mock/*` vẫn tách riêng; cả thực thi theo kế hoạch lẫn legacy đều dùng `AdlcRunService` và đều được phủ kiểm thử.

Observation vận hành khác `RunEvent` ở chỗ: `RunEvent` dành cho Run Detail và lịch sử workflow (thay đổi trạng thái workflow/nhiệm vụ/phê duyệt sau khi lần chạy tồn tại, lưu trong projection `WorkflowRun` process-local, sequence theo từng lần chạy, payload sự kiện miền run); `AdlcOperationObservation` dành cho người vận hành và telemetry (hoàn tất thao tác planning + runtime, lưu trong logging pipeline có cấu trúc / in-memory sink trong test, thứ tự theo completion timestamp và observation ID, payload các trường đối chiếu đóng, không chứa nội dung). Slice này không thêm observation nào vào timeline Run Detail và không có endpoint API công khai mới.

Phạm vi xác minh: phân giải package thành công/thất bại đều sinh một record với correlation package/stage chính xác; từ chối raw-secret lộ `RAW_SECRET_FORBIDDEN` nhưng không lộ secret hay yêu cầu của giai đoạn; kế hoạch `INVALID` do compiler báo `INVALID` kèm plan ID, số lỗi, mã issue ổn định; kế hoạch 5 nhiệm vụ đã chấp nhận sinh 5 dispatch observation với correlation plan-task/stage/package/digest/run/task/attempt; idempotent materialization replay báo `idempotent_replay=true` và không sinh thêm dispatch record; telemetry sink hỏng không làm hỏng thao tác đang quan sát; các test planning/materialization/retry/approval/legacy-run hiện có vẫn xanh.

Reviewer walkthrough (tóm lược): validate blueprint 5 giai đoạn — một resolution observation mỗi giai đoạn cộng một validation observation thành công; xóa direct `requirement` bắt buộc — validation được quan sát `INVALID` với `STAGE_INPUT_UNBOUND`, không giá trị requirement/cấu hình node nào xuất hiện trong record; khôi phục, chấp nhận, chạy — 5 dispatch observation mang phiên bản package và digests đã chấp nhận trong khi timeline Run Detail vẫn dừng ở Approval; chạy lại cùng kế hoạch với cùng idempotency key — run ID không đổi, observation materialization mới có `idempotent_replay=true`, không nhiệm vụ nào dispatch lại; phê duyệt — timeline state-change đạt `SUCCEEDED` mà không đổi hành vi UI. Quyết định đề xuất: [ADR 0007](../adr/0007-secret-safe-operational-observability.md).

---

## Slice 6A — Ranh giới provider OpenCode

Trạng thái: ✅ đã hoàn thành (đợt slice 6A; đã được chấp nhận — chi tiết kích hoạt bị Slice 6B thay thế)

Mục tiêu: thêm OpenCode client dạng production và một `AgentAdapter` mà không đổi scheduler hay mở workspace live không an toàn. Mock workflow hiện có, đường legacy flow, catalogue package blueprint, Memory/Sandbox/Testing adapter vẫn là mặc định. Chuỗi: scheduler → port `TaskExecutor` → `AgentAdapter` (opt-in) → `OpenCodeAgentAdapter` → `OpenCodeClient` → OpenCode headless server (provider credentials sở hữu bởi OpenCode) → workspace VCS diff → `TaskResult` + tham chiếu Artifact.

Những gì đã triển khai:

- Protocol `OpenCodeClient` cô lập transport provider; `OpenCodeHttpClient` gọi các endpoint health/session/prompt-async/message, workspace VCS diff, abort và instance-dispose theo tài liệu. Thực thi prompt: chụp các message ID hiện có, gửi bất đồng bộ, poll trong deadline nhiệm vụ để chờ message assistant terminal mới; các bước trung gian `finish=tool-calls` và `finish=unknown` vẫn in-flight; response terminal hay lỗi ổn định mới kết thúc polling.
- `OpenCodeAgentAdapter` ánh xạ `TaskRequest` v0.1 thành prompt có phạm vi và response ngược thành `TaskResult`; provider/model, token usage, cost, finish reason, session/message IDs, số file thay đổi được chuẩn hóa. Workspace VCS diff nhận về được checksum hóa và biểu diễn bằng tham chiếu Artifact `opencode://`; các patch event qua message assistant trung gian được gộp để báo cáo số file thay đổi.
- Timeout/cancellation trigger abort session best-effort; mỗi lần adapter thoát đều dispose OpenCode instance theo thư mục để file watcher và subprocess không giữ workspace Sandbox đã hoàn thành. Lỗi HTTP và lỗi assistant chuyển thành mã `ServiceError` ổn định, đã làm sạch; từ chối HTTP plain từ xa, credential nhúng trong URL, chuyển tiếp response-body và metadata tùy ý.
- Fake OpenCode client và HTTP mock transport phủ: chấp nhận bất đồng bộ, poll pending-to-complete, lỗi xác thực, timeout, abort, cấu hình hỏng, allow-list prompt, biểu diễn an toàn secret.

Kiểm tra tương thích live: OpenCode 1.18.31 được validate với model `aigateway/MiniMax/MiniMax-M3` vào 2026-09-16 — gọi trực tiếp gateway, streaming và thực thi async đều thành công. Endpoint message đồng bộ persisted response thành công nhưng không đóng HTTP response, nên client cố ý dùng `prompt_async` cộng message polling có giới hạn. Dòng OpenCode này để endpoint session-diff legacy trống, nên adapter chụp `/vcs/diff?mode=git` trong khi workspace dùng một lần còn tồn tại.

Ranh giới kích hoạt của slice 6A: không package OpenCode nào visible trong Blueprint mode, không route executor production nào trỏ tới adapter mới. `MockSandboxAdapter` trả URI mô tả `mock://` và không sở hữu filesystem, nên adapter OpenCode yêu cầu `opencode_directory` riêng từ sandbox và từ chối mock session theo mặc định — phê duyệt 6A là chấp nhận ranh giới tích hợp, không phải cấp quyền cho agent sửa checkout ADLC.

Cấu hình kết nối headless-server (khi dựng adapter tường minh):

| Biến | Ý nghĩa | Secret? |
|---|---|---:|
| `ADLC_OPENCODE_SERVER_URL` | Origin server OpenCode; mặc định loopback port 4096 | Không |
| `ADLC_OPENCODE_SERVER_USERNAME` | Username HTTP Basic; mặc định `opencode` | Không |
| `ADLC_OPENCODE_SERVER_PASSWORD` | Mật khẩu HTTP Basic bảo vệ headless server | Có |
| `ADLC_OPENCODE_MODEL` | Chọn `provider/model` tùy chọn | Không |
| `ADLC_OPENCODE_AGENT` | Tên OpenCode agent tùy chọn | Không |

Các biến chính thức của OpenCode `OPENCODE_SERVER_USERNAME`/`OPENCODE_SERVER_PASSWORD` được nhận làm fallback; chúng xác thực ADLC tới server, không phải LLM provider key.

Về file JSON chứa credential: không copy/commit vào repository, không dán giá trị vào blueprint. OpenCode `auth.json` — OpenCode tự load từ user data directory, ADLC không bao giờ đọc; OpenCode `opencode.json` — chạy OpenCode với cấu hình project/global bình thường hoặc trỏ `OPENCODE_CONFIG` tới nó; provider/service-account JSON — cấu hình provider đó trong tiến trình OpenCode theo tài liệu provider; JSON tùy chỉnh không nhận dạng được — định nghĩa bước chuyển đổi/cấu hình local một lần, không bao giờ thêm generic secret JSON loader vào ADLC.

Xác minh từ `adlc-flow` (không test nào gọi mạng hay đọc credential local):

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/adlc/test_opencode_adapter.py tests/unit/adlc/test_opencode_client.py -q
.venv\Scripts\python.exe -m ruff check langflow/adlc/opencode_adapter.py langflow/adlc/opencode_client.py
```

Checklist đã chấp nhận: OpenCode tích hợp qua `AgentAdapter`, không qua scheduler hay model node Langflow; OpenCode vẫn sở hữu provider credentials; server API được chấp nhận làm transport ban đầu; mock workspace vẫn bị từ chối theo mặc định; kích hoạt package/routing live tách vào Slice 6B; ADR 0008 được Accept.

---

## Slice 6B — Kích hoạt OpenCode opt-in trong disposable Git worktree

Trạng thái: ✅ đã hoàn thành (đợt slice 6B)

Mục tiêu: blueprint đã chấp nhận có thể chọn `coding-agent-opencode@0.1.0`; nhiệm vụ được route tới OpenCode và chạy trong một Git worktree detached, dùng một lần; các giai đoạn `coding-agent@0.1.0` hiện có vẫn đi qua mock deterministic. Chuỗi: kế hoạch đã chấp nhận → task materialization → scheduler không đổi → router theo `ExecutorTarget.service` (`agent-provider:mock` → MockExecutor; `agent-provider:opencode` → AdapterTaskExecutor) → `LocalWorktreeSandboxAdapter` + `MockMemoryAdapter` + `OpenCodeAgentAdapter` + `MockTestingAdapter` → worktree cấp thư mục cách ly cho agent → OpenCode server đã xác thực → chụp workspace VCS diff → dọn worktree trên mọi đường terminal.

### Kích hoạt

Thực thi live tắt theo mặc định. Đặt các giá trị sau vào môi trường backend rồi restart:

| Biến | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `ADLC_OPENCODE_ENABLED` | Có | Phải là `true`, `1`, `yes`, hay `on` để lộ package và đăng ký route. |
| `ADLC_OPENCODE_SOURCE_REPOSITORY` | Có | Git top-level tuyệt đối làm nguồn đã commit cho disposable worktree. |
| `ADLC_OPENCODE_BASE_REF` | Không | Git revision cho từng worktree detached; mặc định `HEAD`. |
| `ADLC_OPENCODE_WORKTREE_ROOT` | Không | Root cấp phát rời rạc; mặc định thư mục temp của OS dưới `adlc-worktrees`. |
| `ADLC_OPENCODE_SERVER_URL` | Không | Origin headless server; mặc định `http://127.0.0.1:4096`. |
| `ADLC_OPENCODE_SERVER_USERNAME` | Không | Username HTTP Basic; mặc định `opencode`. |
| `ADLC_OPENCODE_SERVER_PASSWORD` | Tùy deployment | Secret chỉ dùng giữa ADLC và headless server. |
| `ADLC_OPENCODE_MODEL` | Có cho package này | Phải là `aigateway/MiniMax/MiniMax-M3` cho `coding-agent-opencode@0.1.0`. |
| `ADLC_OPENCODE_AGENT` | Không | Chọn OpenCode agent tùy chọn. |

Provider key vẫn nằm trong environment/cấu hình của OpenCode — không đặt vào blueprint ADLC, package, `TaskRequest`, `.env` commit lên Git hay readiness response. Deployment local cũng cần network tunnel đã cấu hình hoạt động trước khi OpenCode gọi được provider — dependency của người vận hành, không thuộc execution contract.

### Readiness

Sau restart, gọi endpoint đã xác thực `GET /api/v1/adlc/executors/opencode/readiness`. Runtime dùng được báo cả ba dependency check true:

```json
{
  "enabled": true,
  "ready": true,
  "service": "agent-provider:opencode",
  "package": "coding-agent-opencode@0.1.0",
  "server_ready": true,
  "server_version": "1.18.31",
  "model_configured": true,
  "model_ref": "aigateway/MiniMax/MiniMax-M3",
  "sandbox_ready": true,
  "error_code": null
}
```

Response không bao giờ chứa mật khẩu server hay provider credential; readiness không chạy model hay sửa repository.

### Lỗi checkout worktree trên Windows

Repository nguồn có thể qua readiness nhưng nhiệm vụ vẫn thất bại khi Git checkout disposable worktree: thư mục temp mặc định cộng tên file dài theo relative path có thể vượt giới hạn đường dẫn Git, Git báo `Filename too long` trước khi OpenCode được gọi. Worktree adapter giờ truyền `-c core.longpaths=true` cho subprocess Git của chính nó, không đổi cấu hình Git toàn cục của người dùng.

Sau khi cập nhật code: restart backend, mở lại blueprint đã lưu, compile/chấp nhận kế hoạch lần nữa, chạy một lần chạy **mới** (trạng thái plan và run là process-local trong slice này). Package `coding-agent-opencode@0.1.0` cho phép một lần thử, nên nhiệm vụ đã thất bại không retry tại chỗ được; `409 Conflict` khi Retry là kỳ vọng cho nhiệm vụ cũ. Run Detail hiển thị mã lỗi nhiệm vụ an toàn và giới hạn attempt; nếu lần chạy mới vẫn thất bại ở ranh giới worktree, xem `result.error.code` — adapter giữ mã `LOCAL_WORKTREE_*` mà không lộ Git stderr hay credential. Một `500` từ Langflow Store API (tùy chọn) là request riêng, không xác định lý do nhiệm vụ ADLC thất bại.

### Dùng trong blueprint

Chạy/restart backend với các biến kích hoạt → mở Blueprint mode, thêm **Coding Agent (OpenCode)** cho một coding stage → cung cấp direct input `requirement` bắt buộc hoặc bind từ output thượng nguồn tương thích → compile và xem kế hoạch: nhiệm vụ đã phân giải có service `agent-provider:opencode`, phiên bản package đúng `0.1.0` → chấp nhận và chạy bình thường; các giai đoạn mock và approval giữ hành vi hiện có.

Thiếu cờ kích hoạt thì package OpenCode bị ẩn; nhiệm vụ đã chấp nhận trước đó yêu cầu service chưa đăng ký thất bại với `EXECUTOR_SERVICE_NOT_REGISTERED`, không bao giờ bị mock fallback thực thi. Giai đoạn `approval@0.1.0` khác nhiệm vụ agent: `control:approval` do run coordinator xử lý, không đăng ký với executor router; khi dependency thành công, lần chạy vào `WAITING_APPROVAL` và Run Detail đưa ra Approve/Reject; phê duyệt ghi output `approval_decision` và tiếp tục nhiệm vụ hạ nguồn, từ chối làm lần chạy thất bại. Lần chạy đã thất bại với `EXECUTOR_SERVICE_NOT_REGISTERED` trên approval stage không sửa tại chỗ được — restart backend, compile/chấp nhận lại, chạy lần chạy mới.

### Vòng đời workspace và đảm bảo

Một attempt nhận một đường đặt tên từ attempt UUID dưới allocation root đã cấu hình; đường nguồn phải là Git top-level hợp lệ và base ref phải resolve tới một commit; allocation root không được bằng, chứa hay nằm trong source repository. OpenCode chỉ nhận đường đã cấp phát qua `SandboxSession.metadata.opencode_directory`; main checkout không bị sửa, file chưa commit không được copy vào worktree; cleanup chạy sau success, failure, adapter error, cancellation và chỉ xóa đường do adapter instance này cấp phát và theo dõi.

Worktree VCS diff được đọc và checksum trước cleanup; Artifact `SOURCE_PATCH` mang correlation URI opaque `opencode://.../captured-vcs-diff` và metadata các file thay đổi. Ở slice 6B payload patch **không được giữ lại** sau cleanup và URI chưa phải endpoint tải xuống (Slice 6C giữ payload có giới hạn cho review). Các patch event OpenCode từ mọi bước assistant tool-call cũng được gộp, vì message assistant cuối không nhất thiết lặp lại danh sách file thay đổi. Trước Git cleanup, ADLC gọi instance-dispose theo thư mục của OpenCode để nhả file watcher, language server, plugin, handle subprocess; OpenCode session ID vẫn có cho correlation nhưng endpoint session-diff legacy không giữ patch VCS đã chụp.

### Xác minh

Từ `adlc-flow` (suite unit dùng repository local tạm thời và fake client):

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/adlc tests/unit/api/v1/test_adlc_runs.py -q
.venv\Scripts\python.exe -m ruff check langflow/adlc tests/unit/adlc tests/unit/api/v1/test_adlc_runs.py
```

Live smoke check riêng (cần OpenCode server đã cấu hình và quyền truy cập provider):

```powershell
$env:ADLC_RUN_OPENCODE_LIVE_TEST = "true"
$env:LANGFLOW_TEST_HARD_TIMEOUT = "0"
.venv\Scripts\python.exe -m pytest tests/integration/test_adlc_opencode_live.py -q
```

Test đó tạo repository đã commit tạm thời, route một nhiệm vụ thật tới OpenCode, xác minh metadata Artifact suy từ VCS diff và các chuyển trạng thái, xác nhận source checkout không đổi và disposable worktree bị xóa. Watchdog 120 giây của root suite chỉ tắt cho provider smoke test opt-in này; request nhiệm vụ vẫn tự áp deadline thực thi 180 giây.

Hoãn: persistence run/event/result dựa trên database; durable artifact bytes độc lập với session retention của OpenCode; ranh giới bảo mật Sandbox container/remote; Memory và Testing thật; streaming sự kiện tool/progress đã redact và yêu cầu quyền tương tác; badge readiness trên frontend (catalogue package là thay đổi UI duy nhất liên quan kích hoạt). Quyết định ràng buộc: [ADR 0009](../adr/0009-route-live-agents-through-disposable-git-worktrees.md).

---

## Slice 6C — Source patch OpenCode có thể rà soát

Trạng thái: ✅ đã hoàn thành (đợt slice 6C)

Mục tiêu: một lần coding OpenCode chụp workspace VCS diff trong khi disposable worktree vẫn tồn tại. ADLC checksum và giữ một JSON snapshot nhỏ bất biến, xóa worktree, và lộ snapshot cho chủ sở hữu workflow run. Run Detail hiển thị patch từng file thay đổi phía trên các control phê duyệt; UI chỉ bật **Approve** sau khi mọi patch đã chụp được tải, **Reject** luôn khả dụng. Không gì tự động apply patch vào main checkout.

Chuỗi: OpenCode trong disposable worktree → chụp VCS diff → bounded process-local payload store → xóa worktree → read API đã xác thực → review patch trong Run Detail → quyết định phê duyệt của con người.

### Artifact và read API

Artifact `SOURCE_PATCH` có ID ổn định cho một attempt, checksum SHA-256, byte length, thời hạn, URI `adlc://runs/{runId}/artifacts/{artifactId}` — URI là tham chiếu, không phải đường dẫn filesystem hay URL tải công khai. Định dạng payload `opencode-vcs-diff-v1`: danh sách tên file tương đối, unified patch thô, số dòng thêm/bớt, cùng các file thay đổi đã báo cáo.

```text
GET /api/v1/adlc/runs/{runId}/artifacts/{artifactId}
```

API đã xác thực trước tiên kiểm tra ownership của lần chạy và rằng Artifact `SOURCE_PATCH` thuộc một trong các nhiệm vụ của nó, rồi đối chiếu run/task/attempt/checksum với byte đã giữ. Response thành công chứa Artifact và patch snapshot với `Cache-Control: no-store`; run/artifact thiếu hay không thuộc sở hữu trả `404`; payload hết hạn, mất hay không khả dụng trả `410` với `ARTIFACT_PAYLOAD_UNAVAILABLE`. Đừng đưa response này vào log công khai: source patch có thể chứa secret của ứng dụng.

### Retention và hành vi thất bại

Giới hạn mặc định: 2 MiB mỗi artifact, 32 MiB tổng mỗi backend process, 24 giờ. Mục hết hạn bị dọn khi store được truy cập; mục đang hoạt động không bị đuổi để nhường chỗ — quá cỡ hoặc cạn dung lượng làm nhiệm vụ OpenCode thất bại với mã đã làm sạch `ARTIFACT_PAYLOAD_TOO_LARGE` hay `ARTIFACT_PAYLOAD_STORE_FULL`, thay vì claiming một thay đổi thành công nhưng không thể review. Restart backend làm mất trạng thái run và byte patch đã giữ; đây là giới hạn mặc định trong code cho slice này, không phải chính sách storage bền vững.

Patch được giữ trước khi dispose OpenCode instance và cleanup worktree; cả hai bước cleanup vẫn chạy ngay cả khi retention thất bại. Worktree sandbox không bao giờ ghi vào main checkout; phê duyệt chỉ giải quyết workflow gate — không merge, apply hay commit patch. Kiểm tra "đã đọc patch trước khi phê duyệt" hiện là gate của UI Run Detail, không phải yêu cầu phía API; API client phải tự sắp xếp review trước khi gọi Approve.

### Cách thử và xác minh

Kích hoạt OpenCode theo Slice 6B, chạy blueprint đã chấp nhận với giai đoạn `coding-agent-opencode@0.1.0` theo sau bởi Approval. Trong Run Detail, chờ nhiệm vụ coding xong, mở **Changes to review**, chọn từng nhiệm vụ và đọc danh sách file cùng raw patch (chỉ đọc). Tại approval gate, **Approve** khả dụng sau khi mọi patch được tải; patch không khả dụng thì khung hiển thị lỗi và cho **Retry loading**, **Reject** vẫn dùng được. Xác nhận source checkout không đổi; nếu thay đổi được muốn ngoài prototype, vẫn cần cơ chế apply/merge riêng đã review.

Xác minh: unit/API test phủ đối chiếu checksum và identity, kích thước/dung lượng/hết hạn, ownership và `410`, disposable Git worktree thật với fake OpenCode client, frontend patch view; live provider smoke test vẫn opt-in. Tiếp theo: persistence run/event/artifact bền vững, cơ chế apply patch riêng có review, chính sách phê duyệt phía API nếu cần, preview đã redact cho diff nhạy cảm, container/remote Sandbox cho code không đáng tin. Tham khảo [ADR 0010](../adr/0010-retain-reviewable-source-patches-temporarily.md).

---

# Phần III — Orchestrator control plane (slice 7 → 10)

## Slice 7 — Orchestrator control plane (P0 + P1)

Trạng thái: ✅ đã hoàn thành (đợt slice 7)

Phạm vi: lệnh cancel/pause lần chạy, ranh giới persistence bền vững, crash recovery khi khởi động, auto-retry với backoff, deadline watchdog của coordinator. Contract workflow/task/command state machine v0.1 vẫn đóng băng — không đổi trạng thái hay chuyển tiếp nào. Persistence: SQL snapshot store compose vào production run service; recovery replay từ snapshot.

Topology: owner gọi các lệnh run (`cancel_run`, `pause_run`, `resume_run`, `retry_task` thủ công) vào `AdlcRunService`; scheduler loop dispatch qua port `TaskExecutor` (mock / OpenCode / Harness); reap + failure funnel nhận cả callback trạng thái lẫn deadline watchdog; auto-retry + backoff đưa nhiệm vụ quay lại scheduler; coordinator persist tại ranh giới vào SQL snapshot store, và startup recovery replay từ store về scheduler.

### Lệnh lần chạy mới (P0)

| Lệnh | API | Quy tắc |
|---|---|---|
| `cancel_run` | `POST /adlc/runs/{run_id}/cancel` | Chỉ cho lần chạy chưa terminal. Attempt executor đang chạy bị cancel hợp tác; nhiệm vụ PENDING/READY/RUNNING/WAITING_APPROVAL chuyển `CANCELLED`; yêu cầu phê duyệt đang chờ bị cancel cùng lần chạy; lần chạy thành `CANCELLED` (terminal). Actor được ghi trong event payload. |
| `pause_run` | `POST /adlc/runs/{run_id}/pause` | Chỉ lần chạy QUEUED/RUNNING; lần chạy bị chặn bởi approval bị từ chối theo state machine đóng băng. Scheduler ngừng dispatch và chuyển lần chạy sang `PAUSED` khi các attempt đang chạy tới ranh giới an toàn; lần chạy không có scheduler sống pause ngay. |
| `resume_run` | `POST /adlc/runs/{run_id}/resume` (đã có) | Xóa cờ pause/cancel, giữ đủ điều kiện manual-retry, re-dispatch lần chạy executor async trong background scheduler thay vì chặn caller. |

Ownership pause/cancel ép bởi owner scoping hiện có; cả hai lệnh phát sự kiện chuẩn `workflow_run.paused` / `workflow_run.cancelled` và `task_run.cancelled` qua timeline `RunEvent` có thứ tự. `emit_event` từ ngoài không còn tự resume lần chạy bị người dùng pause; sự kiện được ghi và có hiệu lực khi resume tường minh. Các pause nội bộ của `_finalize` phân biệt bằng reason (`retry_available`, `waiting_for_events`) và persist trong pause event payload, nên `retry_task` thủ công chỉ được chấp nhận cho pause reason `retry_available` kể cả sau restart.

### Auto-retry (P1)

Trigger: executor báo `FAILED` với `ServiceError` có kiểu và cờ `retryable` là true. Ngân sách: `constraints.max_attempts` mỗi nhiệm vụ (mặc định 2; attempt hiện tại được tính). Backoff: `constraints.retry_backoff_ms` làm base (mặc định 500 ms), nhân đôi mỗi lần retry, trần 30 s; scheduler ngủ tới deadline backoff sớm nhất trước khi re-dispatch. Định danh: cùng `TaskRun` mở lại qua chuyển tiếp đóng băng `RUNNING -> READY` với sự kiện `task_run.retry_scheduled` mang `retry_count`, `backoff_ms`, `error_code` gốc; mỗi attempt mới nhận `attempt_id` và idempotency key mới. Manual retry (`POST /adlc/tasks/{task_id}/retry`) không đổi và vẫn là con đường hồi sinh duy nhất sau khi ngân sách cạn (`FAILED -> READY`), giờ gate bởi pause reason `retry_available`. Lỗi không retryable bỏ qua auto-retry hoàn toàn và pause lần chạy như trước.

### Deadline watchdog của coordinator (P1)

Mỗi attempt ghi `TaskRun.deadline_at` (từ `constraints.timeout_ms`) và một `worker_id` trong tiến trình cho audit. Coordinator ép deadline độc lập với executor: executor treo bị cancel, attempt thất bại với kết quả có kiểu `TASK_DEADLINE_EXCEEDED` (`TIMEOUT`, retryable), rồi đi qua đường auto-retry/manual-retry chuẩn. Gia hạn deadline: khi nhiệm vụ đang `WAITING_APPROVAL` (gate con người), deadline được gia hạn mỗi chu kỳ hết hạn vì quyết định con người cố ý không bị chặn thời gian; callback terminal của executor mà bỏ qua báo cáo `RUNNING` trung gian cũng giải cứu được lần chạy kẹt ở `WAITING_APPROVAL`.

### Persistence bền vững và crash recovery (P1)

`SqlAdlcRunPersistence` compose vào production `AdlcRunService` (`get_adlc_run_service`), lưu một JSON snapshot nguyên tử mỗi lần chạy (state + events + definitions trong một row/transaction). Coordinator persist tại mọi ranh giới mutation: sau mỗi batch hoàn thành được reap, sau mỗi lệnh (start/cancel/pause/resume/retry/approve/reject/event), và trước khi scheduler thoát — một crash mất nhiều nhất phần việc còn đang chạy. Startup recovery chạy một lần (`_ensure_hydrated`, lần dùng service đầu mỗi tiến trình): khôi phục mọi snapshot, replay runtime event đã phát, khôi phục pause reason bền vững, requeue attempt `RUNNING` mồ côi thành `READY` (`task_run.resumed`, reason `orchestrator_recovery`), re-dispatch lần chạy QUEUED/RUNNING trong background scheduler; lần chạy PAUSED và WAITING_APPROVAL tiếp tục chờ lệnh tường minh hay quyết định phê duyệt. Cấp đảm bảo: at-least-once; attempt được replay mang idempotency key mới, executor hạ nguồn tự dedupe theo key (attempt ledger của Harness đã làm sẵn). `READY` giờ là trạng thái scheduler dispatchable (trước đây chỉ dispatch-in-transit) — chính điều này khiến orphan đã resume/recovered nhập lại scheduler thay vì deadlock giữa hai trạng thái.

Ghi chú race và lỗi đã xử lý: scheduler re-selection loại nhiệm vụ đang chạy theo identity, READY-as-dispatchable đòi loại trừ `dispatched_ids` tường minh để tránh re-dispatch vô hạn trong một vòng lặp; `TaskMetrics.duration_ms` là int, timeout metrics của coordinator chuyển từ float monotonic; backoff tính trước khi bộ đếm retry tăng (lần retry đầu = delay base).

Ngoài phạm vi (các slice kế): trigger (cron/webhook), tổng hợp metrics/alerting, external worker queue, dynamic fan-out và sub-workflow, DLQ/compensation (cần contract v0.2), approval expiry/SLA, RBAC đầy đủ, template expressions — theo dõi trong bảng roadmap README.

Xác minh: `tests/unit/adlc/test_orchestration_control.py` phủ cancel giữa chừng (nhiệm vụ, approvals, sự kiện, từ chối terminal, owner scoping), pause/resume với executor background, chặn sự kiện khi user pause, auto-retry thành công/backoff/cạn ngân sách/không-retryable, deadline failure của coordinator, gia hạn deadline qua gate con người, restart recovery của attempt mồ côi, bảo toàn lần chạy paused, khôi phục pause reason, đếm ranh giới persistence. Toàn bộ test orchestration, flow, mock, planning, contract hiện có vẫn xanh.

---

## Slice 8 — Run triggers và metrics (P2)

Trạng thái: ✅ đã hoàn thành (đợt slice 8)

Phạm vi: trigger lần chạy theo lịch và webhook, tổng hợp metrics trên dòng observation, alert rules, export Prometheus. Thực thi qua external-worker queue cố ý giao cho tích hợp DeepSeek Harness thay vì generic queue song song (xem quyết định bên dưới). Contract state machine v0.1 vẫn đóng băng; trigger chỉ *khởi động* lần chạy qua các lệnh run công khai hiện có.

Topology: các nguồn trigger (cron expression, fixed interval, inbound webhook token) đưa vào `AdlcTriggerService` với hai policy (overlap `SKIP`/`ALLOW`; missed `SKIP`/`CATCH_UP`), trạng thái trigger nằm trong các row `adlc_run_trigger`; trigger gọi `AdlcRunService.start_run`; dòng observation đi qua `CompositeAdlcObservabilitySink` tỏa ra structured logger và `AdlcMetricsCollector`, tổng hợp thành `AdlcMetricsSnapshot` + alerts và exposition tại `GET /adlc/metrics/prometheus`.

### Run triggers

Definition snapshot: tạo trigger chuẩn hóa flow đã lưu (cùng kiểm tra quyền và từ chối blueprint-marker như đường run thủ công) và đóng băng định nghĩa nhiệm vụ lên trigger; lần chạy được kích phát replay snapshot đó, sửa flow sau này không âm thầm đổi lịch. Lịch: fixed interval (30 s .. 30 d) hoặc cron 5 trường (`langflow/adlc/cron.py` cài cú pháp chuẩn với list, range, step, tên tháng/thứ, quy tắc OR dom/dow; không có trường giây hay múi giờ).

Anti-overlap: `SKIP` (mặc định) hoãn lần kích khi lần chạy do cùng trigger khởi động trước đó còn active; `ALLOW` cho chạy đồng thời. Lần chạy active suy lại qua run service nên phép kiểm tra sống qua restart và tự xóa khi lần chạy terminal hay bị xóa. Chính sách lịch bị lỡ (sau downtime): `SKIP` nhảy tới mốc đến hạn tương lai gần nhất; `CATCH_UP` kích phát một lần ngay; chính sách chỉ resolve cho trigger khôi phục từ row bền vững, không cho trigger vừa tạo trong tiến trình sống.

Webhook: mỗi trigger có thể mang token opaque (`secrets.token_urlsafe`), xoay vòng qua `POST /adlc/triggers/{id}/rotate-webhook-token`; `POST /adlc/triggers/webhook/{token}` không cần user session; token lạ trả 404; kích khi lần chạy trước còn active báo `SKIPPED_OVERLAP` thay vì âm thầm chồng lần chạy. API: `POST/GET /adlc/triggers`, `GET/PATCH/DELETE /adlc/triggers/{id}`, `GET /adlc/triggers/{id}/next-runs` (xem trước thời điểm kích), rotate-webhook-token, webhook fire; trigger view không bao giờ chứa webhook token, token chỉ lộ đúng một lần lúc create/rotate. Persistence: một JSON row mỗi trigger (`adlc_run_trigger`) với cột owner và token đánh chỉ mục; background loop mặc định tick 30 s, persist trạng thái tại mọi fire/skip/fail, sống qua exception của một trigger.

### Metrics, alerts và dashboard

`AdlcMetricsCollector` là `AdlcObservabilitySink` thread-safe trên cửa sổ trượt (mặc định 15 phút, 20k sự kiện): counter outcome theo event type, counter mã lỗi ổn định, độ trễ p50/p95/p99/max theo loại thao tác. Composition production: `CompositeAdlcObservabilitySink` phát mọi observation tới structured logger và collector, nên metrics không bao giờ nuốt hay đổi hành vi logging.

Alert rules sẵn có trên cửa sổ: tỷ lệ dispatch thất bại >= 50% với >= 10 mẫu (`ERROR`); bất kỳ `TASK_DEADLINE_EXCEEDED` nào (`WARNING`); >= 3 dispatch bị từ chối (`WARNING`). Alert mang mã ổn định, được đưa vào snapshot; ngưỡng là hằng số, chờ cấu hình theo tenant. API: `GET /adlc/metrics` (JSON snapshot) và `GET /adlc/metrics/prometheus` (text exposition: counter `adlc_*_total`, summary `adlc_*_duration_ms`, counter lỗi theo mã, alert gauge) sẵn sàng cho Prometheus/Grafana scrape.

Quyết định: không xây generic queue thứ hai cho P2-3 — mục "external worker/queue execution phía sau port `TaskExecutor`" đã được tích hợp DeepSeek Harness giao (slices 6D/6E): `HarnessExecutor` dispatch attempt tới external worker service, attempt ledger SQLite cung cấp claim semantics bền vững, callback delivery được dedupe, reconciliation phục hồi session gián đoạn sau restart. Generic queue song song sẽ nhân bản logic transport/lease/dedup mà không có consumer thêm, nên phần external-execution còn lại chuyển vào tầng hardening P3 (worker identity đa tenant, queue depth metrics).

Ngoài phạm vi: node dynamic fan-out/loop/sub-workflow, DLQ và compensation (cần contract v0.2), approval expiry/SLA escalation, RBAC/secrets/encryption đầy đủ, template expressions, cấu hình alert theo tenant — theo dõi trong roadmap README.

Xác minh: `tests/unit/adlc/test_cron.py` (13 test) — parsing, ngữ nghĩa OR dom/dow, chuyển năm, next-fire; `tests/unit/adlc/test_triggers.py` (13 test) — definition snapshot, đánh giá đến hạn, overlap skip/allow, missed-skip so catch-up sau restart, webhook fire/rotation/owner scoping, ghi failure, background loop; `tests/unit/api/v1/test_adlc_triggers.py` — SQL trigger persistence round-trip và toàn vòng lifecycle HTTP kể cả webhook fire; `tests/unit/adlc/test_metrics.py` (8 test) — windowing, counter, percentile, cả ba alert rule, composite fan-out, Prometheus rendering, HTTP endpoint metrics. Toàn bộ test orchestration, harness, planning, contract hiện có vẫn xanh.

---

## Slice 9 — Approval expiry, SLA breach, notification và dead-letter (P3 đợt 1)

Trạng thái: ✅ đã hoàn thành (đợt slice 9)

Phạm vi: approval TTL expiry với state machine đóng băng, phát hiện SLA breach của lần chạy, seam notification hướng owner, dead-letter view, ngưỡng alert cấu hình được cho collector. Mọi chuyển tiếp mới chỉ dùng các edge contract đã định nghĩa. Slice khép các khoảng trống về sự chú ý của con người: phê duyệt có thể hết hạn thay vì chặn vĩnh viễn, lần chạy tuyên bố được SLA breach, người vận hành nhận notification qua seam thay thế được, các nhiệm vụ cần quyết định con người tập trung ở một dead-letter view.

### Approval expiry

- Nguồn TTL: task definition có thể mang `constraints.approval_ttl_seconds`; `ApprovalRequest` tạo ra ghi `expires_at`. Definition không có TTL giữ phê duyệt mở vĩnh viễn (tương thích ngược).
- Quét: `expire_due_approvals()` (cộng background sweeper loop, mặc định tick 30 s, do API composition khởi động) làm hết hạn mọi phê duyệt PENDING quá hạn chỉ bằng các chuyển tiếp đóng băng — phê duyệt: `PENDING -> EXPIRED` với sự kiện `approval_request.expired`; nhiệm vụ: `WAITING_APPROVAL -> FAILED` với kết quả có kiểu `APPROVAL_EXPIRED` (`TIMEOUT`, non-retryable); lần chạy: `WAITING_APPROVAL -> FAILED` — gate con người đã qua hạn nên lần chạy terminalize như mọi thất bại khác, lần chạy mới là con đường hồi sinh đúng (contract cố ý không có cạnh `WAITING_APPROVAL -> PAUSED`, và auto-retry vòng lặp phê duyệt sẽ spam lại reviewer).
- Expiry idempotent, persist từng lần chạy bị ảnh hưởng, chịu được lỗi theo từng lần chạy.

### SLA breach của lần chạy

- `CreateWorkflowRunRequest` nhận `slaSeconds` tùy chọn (1 s .. 30 d); lần chạy ghi `sla_deadline_at`. `check_run_slas()` của sweeper đánh dấu lần breach đầu tiên của mỗi lần chạy chưa terminal bằng `sla_breached_at`, một sự kiện `workflow_run.sla_breached`, và một notification `SLA_BREACHED`. Phát hiện breach không bao giờ đổi trạng thái lần chạy — chỉ ghi và thông báo.

### Seam notification và dead-letter view

- `langflow/adlc/notifications.py` định nghĩa `AdlcNotification` (kind ổn định: `APPROVAL_REQUIRED`, `APPROVAL_EXPIRED`, `SLA_BREACHED`), port `AdlcNotificationSink`, in-memory recorder cho test, structured-log sink. Production run service compose với structured-log sink; lỗi notification bị nuốt theo contract — không bao giờ phá đường điều phối.
- `GET /adlc/dead-letters` liệt kê các nhiệm vụ FAILED theo owner mà auto-recovery không hồi sinh được: ngân sách attempt cạn (`retry_count + 1 >= max_attempts`) hoặc lỗi đã ghi không retryable (kể cả hết hạn phê duyệt). Mỗi mục mang định danh run/task, mã lỗi ổn định, bộ đếm attempt, thời điểm thất bại. View chỉ đọc; hồi sinh là lệnh manual-retry hiện có hay một lần chạy mới.
- `AdlcAlertThresholds` biến ba alert rule của slice 8 thành cấu hình được cho từng collector instance (tỷ lệ thất bại, số mẫu tối thiểu, deadline breach, dispatch bị từ chối) thay vì hằng số module — tinh chỉnh theo deployment ngay, theo tenant sau.

Ngoài phạm vi: node dynamic fan-out/loop/sub-workflow và compensation/rollback của dead-letter cần contract v0.2; RBAC/secrets/encryption đầy đủ, template expressions, cấu hình alert theo tenant còn là phần P3 còn lại.

Xác minh: `tests/unit/adlc/test_approval_sla.py` (9 test) phủ projection TTL, chuyển tiếp và sự kiện expiry, terminalize lần chạy, dead-letter lộ approval hết hạn, miễn nhiễm TTL tương lai, breach đúng một lần, miễn nhiễm lần chạy terminal, sweeper thời gian thực, ghi notification, ngưỡng metrics cấu hình được. Toàn bộ test orchestration, trigger, metrics, harness, planning, contract hiện có vẫn xanh.

---

## Slice 10 — Template expressions, webhook notification và env thresholds (P3 đợt 2)

Trạng thái: ✅ đã hoàn thành (đợt slice 10)

Phạm vi: phân giải template `{{root.path}}` nghiêm ngặt cho input nhiệm vụ, kênh notification webhook với composition fan-out, ngưỡng alert metrics cấu hình qua environment. Contract state machine v0.1 vẫn đóng băng; template chỉ định hình request input, không bao giờ đổi trạng thái run hay task. Slice hoàn thành các mục P3 còn khả thi mà không cần contract v0.2; phần còn lại của roadmap (dynamic fan-out/loop/sub-workflow, dead-letter compensation, RBAC/secrets/encryption đầy đủ) cần contract v0.2 hoặc công việc cấp nền tảng và tiếp tục được theo dõi.

### Template expressions

- Cú pháp: `{{root.path.segments}}` với các root `task.<key>.output...` và `run.<field>` (`id`, `name`, `run_number`, `workflow_key`, `status`), phân giải mỗi lần dispatch từ trạng thái coordinator đóng băng (`AdlcRunService._template_roots`).
- Ngữ nghĩa: tham chiếu chiếm toàn bộ chuỗi giữ nguyên kiểu của giá trị được tham chiếu (dict, list, số); tham chiếu nhúng trong chuỗi dài hơn thay bằng văn bản; phân giải đệ quy qua dict và list; khoét output khớp quy ước input-binding hiện có (wrapper `outputs` được tham chiếu khi có).
- Tính nghiêm ngặt: root lạ, key thiếu, list index không phải số nguyên, index ngoài phạm vi đều raise `TemplateResolutionError` với đúng đường dẫn chấm; `_prepare_attempt` chuyển thành `INPUT_RESOLUTION_FAILED` (`AdlcRunStateError`), làm attempt thất bại qua crash funnel chuẩn — lần chạy pause chờ manual retry thay vì dispatch request bind một phần.
- Template phân giải trước input bindings, nên hai cơ chế kết hợp được; definition có sẵn không dùng template hành vi đúng như trước.

### Kênh notification và ngưỡng alert từ environment

- `CompositeAdlcNotificationSink` phát một notification tới nhiều sink; lỗi của một sink không bao giờ phá anh em hay coordinator.
- `WebhookAdlcNotificationSink` POST JSON notification tới URL của người vận hành (bearer token tùy chọn, timeout 2 s). Delivery nghiêm ngặt best-effort: lỗi mạng và response non-2xx được ghi log (`adlc.notification.webhook_failed` / `adlc.notification.webhook_rejected`) và nuốt. Composition: `ADLC_NOTIFY_WEBHOOK_URL` (cộng `ADLC_NOTIFY_WEBHOOK_TOKEN` tùy chọn) bật kênh webhook cạnh kênh structured-log trong `get_adlc_notification_sink()`.
- `thresholds_from_environment()` dựng `AdlcAlertThresholds` từ `ADLC_METRICS_FAILURE_RATE`, `ADLC_METRICS_FAILURE_MIN_SAMPLES`, `ADLC_METRICS_DEADLINE_BREACHES`, và `ADLC_METRICS_DENIED_DISPATCHES`; giá trị không hợp lệ fallback mặc định kèm cảnh báo. `get_adlc_metrics_collector()` compose các ngưỡng này — alert rule slice 8 tinh chỉnh được theo deployment mà không đổi code (cấu hình theo tenant vẫn chờ một tenant model).

Ngoài phạm vi (cần contract v0.2 hay công việc nền tảng): dynamic fan-out (map), node loop/foreach, sub-workflow; hành động compensation/rollback của dead-letter; RBAC, secret reference, encryption at rest đầy đủ; ngưỡng và kênh notification theo tenant.

Xác minh: `tests/unit/adlc/test_expressions_notifications.py` (12 test) phủ full match giữ kiểu, thay thế nhúng, phân giải lồng sâu, đường thất bại nghiêm ngặt (root lạ, key thiếu, khoét trên non-container, index ngoài phạm vi), giá trị pass-through, phân giải dispatch end-to-end vào `request.input.namedInputs`, pause lần chạy khi template không phân giải được, composite fan-out, POST webhook payload/bearer token, nuốt lỗi mạng, parse ngưỡng environment với fallback khi nhận rác, phát notification qua composed sink. Toàn bộ test orchestration, trigger, metrics, approval/SLA, harness, planning, contract hiện có vẫn xanh.

---

## Nguồn tổng hợp

Tài liệu này được tổng hợp từ 15 tài liệu kế hoạch slice, bản gốc tiếng Anh, **lưu trữ trên nhánh git `agentHarness`** (đọc bằng `git show agentHarness:docs/<file>`; các file không còn ở working tree):

1. `docs/blueprint-planning.md` — nền tảng Slice 2: parse blueprint, phân giải node package, tạo kế hoạch.
2. `docs/planner-proposal-slice.md` — Planner Agent: proposal → validation → approval → pipeline hiện có.
3. `docs/blueprint-ui-slice-3.md` — Slice 3: Blueprint UI và Plan Preview.
4. `docs/plan-materialization-slice-4.md` — Slice 4: từ kế hoạch đã chấp nhận đến mock runtime.
5. `docs/execution-routing-slice-5a.md` — Slice 5A: định tuyến thực thi tường minh và di chuyển thủ công.
6. `docs/plan-regeneration-slice-5b.md` — Slice 5B: regeneration và supersession của kế hoạch.
7. `docs/package-authorization-slice-5c.md` — Slice 5C: phân quyền package và capability.
8. `docs/observability-slice-5d.md` — Slice 5D: observability vận hành.
9. `docs/opencode-adapter-slice-6a.md` — Slice 6A: ranh giới provider OpenCode.
10. `docs/opencode-activation-slice-6b.md` — Slice 6B: OpenCode opt-in trong disposable Git worktree.
11. `docs/opencode-artifact-review-slice-6c.md` — Slice 6C: source patch OpenCode có thể rà soát.
12. `docs/orchestrator-control-plane-slice-7.md` — Slice 7: orchestrator control plane (P0 + P1).
13. `docs/orchestrator-triggers-metrics-slice-8.md` — Slice 8: run triggers và metrics (P2).
14. `docs/orchestrator-approval-sla-slice-9.md` — Slice 9: approval expiry, SLA, notification, dead-letter (P3 đợt 1).
15. `docs/orchestrator-expressions-notifications-slice-10.md` — Slice 10: template expressions, webhook notification, env thresholds (P3 đợt 2).

Các slice 6D/6E (tích hợp DeepSeek Harness) được các tài liệu nguồn nhắc tới như công việc đã giao nhưng không nằm trong 15 file nguồn này.

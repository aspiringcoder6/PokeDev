# ADR: Quy ước `adapter_ref = "orchestrator:auto"` — executor do OrchestratorHost chọn lúc phê duyệt plan

- Trạng thái: **Proposed** (chốt quy ước trong Gói G1; hiện thực logic thuộc Gói G2)
- Ngày: 2026-10-19
- Phạm vi: routing executor của execution plan (materializer / run runtime)
- Feature flag: `ADLC_ORCHESTRATOR_ROUTING`
- Liên quan: `docs/plans/ke-hoach-tang-dieu-phoi.md` (G1, G2), `docs/plans/notes-orchestrator-baseline.md`

## Bối cảnh

Hiện tại `spec.implementation.adapter_ref` của một `ResolvedNodeSpec` luôn là **tên service executor cụ thể**
(ví dụ `"mock"`, `"agent-provider:mock"`, các service harness). Giá trị này bị đóng băng vào plan snapshot khi
plan được biên dịch, nên quyết định "ai làm" bị chốt quá sớm — trước khi người phê duyệt xem plan và trước khi
orchestrator có đủ thông tin về năng lực (capability) của từng executor.

Kế hoạch tầng điều phối (Gói G2) sẽ cho `OrchestratorHost` tham gia quyết định này **lần đầu tiên tại thời điểm
phê duyệt plan**: plan vẫn bất biến, nhưng executor được chọn theo capability ngay trước khi đóng băng. Cần một
cách khai báo "để orchestrator tự chọn" mà không phá hợp đồng plan v0.1.

## Quyết định

### 1. Giá trị đặc biệt

```
spec.implementation.adapter_ref == "orchestrator:auto"
```

**Ý nghĩa:** *"executor cho task này do OrchestratorHost chọn lúc phê duyệt plan"* — tức là lúc materialize,
dựa trên capabilities yêu cầu của task (`ExecutorTarget.capabilities`), host gọi `find_capable()` để chọn plugin
đủ năng lực theo **thứ tự đăng ký** (deterministic: plugin đầu tiên thắng).

- Giá trị này **chỉ là quy ước dữ liệu** trong G1 — chưa có code nào diễn giải nó. G2 mới hiện thực.
- Khi adapter_ref là executor cụ thể (mọi giá trị khác), ý nghĩa giữ nguyên như cũ: routing do **user** chỉ định.

### 2. Thời điểm resolve

- Resolve xảy ra **TRƯỚC khi đóng băng (materialize)**: kết quả chọn plugin được ghi vào
  `request_metadata` của task (`routing_source="orchestrator"`, `plugin_id`, capabilities đã khớp).
- Plan snapshot **vẫn bất biến**: không trường nào trong `ResolvedNodeSpec`/`PlanTask` bị ghi đè sau phê duyệt.
- Khi `adapter_ref` là executor cụ thể → `routing_source="user"`.

### 3. Điều kiện bật flag

Việc diễn giải `"orchestrator:auto"` **chỉ xảy ra khi**:

1. `ADLC_ORCHESTRATOR_ROUTING` bật tường minh (`1|true|yes|on`, không phân biệt hoa/thường — helper
   `orchestrator_routing_enabled()` trong `langflow/adlc/orchestrator_routing.py`); **và**
2. `adapter_ref == "orchestrator:auto"`.

**Flag TẮT (mặc định):** `"orchestrator:auto"` **không được diễn giải đặc biệt** — nó được coi như một tên
service executor bình thường, và vì không executor nào đăng ký service đó, chạy sẽ fail theo cơ chế hiện có
(`EXECUTOR_SERVICE_NOT_REGISTERED`). Toàn bộ path routing cũ chạy nguyên vẹn 100%. Flag tắt là trạng thái
an toàn để rollback.

### 4. Ví dụ lỗi (hợp đồng lỗi của G2)

Không plugin nào đủ năng lực → lỗi domain **không fallback im lặng**, materialize thất bại, plan không chạy:

```json
{
  "error": "NO_CAPABLE_PLUGIN",
  "message": "No enabled plugin supports capabilities: ['CODE_GENERATION']",
  "details": {
    "plan_id": "…",
    "plan_task_id": "…",
    "required_capabilities": ["CODE_GENERATION"],
    "adapter_ref": "orchestrator:auto"
  }
}
```

Các lỗi routing khác giữ cơ chế hiện có:

| Tình huống | Mã lỗi | Kênh |
| --- | --- | --- |
| Không plugin nào đủ capability khi `orchestrator:auto` | `NO_CAPABLE_PLUGIN` | `ExecutionPlanStateError` (G2) |
| Service không đăng ký (flag tắt / executor cụ thể lạ) | `EXECUTOR_SERVICE_NOT_REGISTERED` | `TaskResult.error` (router hiện có) |

### 5. Điều kiện nghiệm thu khi bật flag (cho G2+)

- Toàn bộ baseline test (xem `notes-orchestrator-baseline.md`) vẫn xanh đúng như mốc
  (4 test `test_adlc_runs.py` FAIL có sẵn trước G1 — chỉ yêu cầu **không red thêm**).
- Flag tắt → hành vi hiện tại giống hệt baseline (không có gì đổi).
- Chỉ bật flag trên môi trường có OrchestratorHost đăng ký tối thiểu `MonarchPlugin` (enabled).

## Hệ quả

### Lợi

- Người phê duyệt thấy executor được đề xuất theo capability **trước khi** đóng băng (G2 sẽ trả kèm routing proposal ở API preview).
- Thêm executor mới = đăng ký plugin mới, không sửa plan/blueprint đã duyệt.
- Rollback an toàn: tắt flag là về đúng hành vi cũ.

### Chi phí / rủi ro

- `"orchestrator:auto"` trở thành từ khóa dành riêng: các blueprint **không được** đặt tên service executor trùng giá trị này.
- Lựa chọn phụ thuộc thứ tự đăng ký plugin → cần test khóa thứ tự (G2, trường hợp hai plugin cùng capability).
- Plan cũ đã đóng băng với `"orchestrator:auto"` khi flag tắt sẽ fail rõ ràng ở router (`EXECUTOR_SERVICE_NOT_REGISTERED`) — chấp nhận được vì chưa bao giờ bật.

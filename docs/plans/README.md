# docs/plans/ — Kế hoạch PokeDev và tài liệu nền ADLC

Kế hoạch mới cho PokeDev nằm cùng các tài liệu nền kế thừa từ ADLC. Các trạng thái hoàn thành trong tài liệu ADLC phản ánh baseline của dự án nguồn; cần đối chiếu khi áp dụng vào PokeDev.

Kế hoạch hiện tại: [LarkSuite và giai đoạn nhận yêu cầu](./lark-intake-slices.md), gồm LI-00 → LI-10 cho pilot và các adapter mở rộng LI-11 → LI-13. LI-01 đã triển khai. LI-02 đã có backend, connector, UI và kiểm tra tự động; thử liên kết/DM thật chờ xác nhận danh tính. LI-00 đã kiểm tra offline và DM hai chiều trên tenant thật, còn các bài thử mention/callback/tài liệu/phục hồi. Xem [kết quả và cách chạy](../lark-intake-implementation.md).

Các tài liệu tổng hợp ADLC bên dưới tham chiếu nhánh `agentHarness` của repository nguồn, không phải nhánh có sẵn trong lịch sử Git mới của PokeDev.

## Nội dung thư mục

| File | Nội dung |
|---|---|
| [`lark-intake-slices.md`](./lark-intake-slices.md) | Hồ sơ yêu cầu trước Spec, agent chủ động hỏi lại, tương tác Lark/web, tài liệu/file, chốt brief và bàn giao native Harness; có phụ thuộc và tiêu chí nghiệm thu cho từng slice. |
| [`li02-implementation.md`](./li02-implementation.md) | Phạm vi ảnh hưởng, nghiệm thu, kiểm tra và đối chiếu diff cho liên kết danh tính và DM intake. |
| [`ke-hoach-slice.md`](./ke-hoach-slice.md) | **Tài liệu lõi** (~900 dòng). Kể lại toàn bộ lộ trình slice 2 → 10: nền tảng blueprint → kế hoạch → runtime, Planner proposal, Blueprint UI và Plan Preview, materialization vào mock runtime, định tuyến thực thi, regeneration/supersession, phân quyền package, observability, tích hợp OpenCode (6A/6B/6C), và orchestrator control plane theo các đợt P0 → P3 (slice 7 → 10). Mỗi phần có mục tiêu, phạm vi, thiết kế quan trọng, deliverable + test chính và dòng trạng thái. |
| `lo-trinh-san-pham.md` | Lộ trình sản phẩm (đang được soạn song song bởi agent khác — bổ sung đường dẫn khi sẵn sàng). |

## Thứ tự đọc đề xuất

1. **[`ke-hoach-slice.md`](./ke-hoach-slice.md)** — bắt đầu từ mục "Bối cảnh và cách chia đợt" ở đầu file để có bản đồ tổng thể (nền tảng slice 2 → 6C, rồi orchestrator P0 → P3 ở slice 7 → 10) và bảng trạng thái các đợt.
2. Đọc tiếp các phần theo nhu cầu:
   - Người mới tìm hiểu luồng cốt lõi: **Phần I** (nền tảng blueprint planning + planner proposal) rồi **Slice 3 → 4** (UI soạn thảo và materialize vào mock runtime).
   - Người quan tâm bảo mật/quyền: **Slice 5A → 5C** (định tuyến tường minh, regeneration kế hoạch, phân quyền package/capability).
   - Người quan sát hệ thống: **Slice 5D** và **Slice 8** (observation, metrics, alerts, Prometheus).
   - Người quan tâm agent thật: **Slice 6A → 6C** (OpenCode client, disposable Git worktree, review source patch).
   - Người vận hành orchestrator: **Slice 7 → 10** (lệnh điều khiển lần chạy, tự phục hồi, trigger, SLA, notification, template expressions).
3. **`lo-trinh-san-pham.md`** — đọc sau để đặt các slice trong bức tranh sản phẩm dài hạn.

## Bản đồ slice nhanh

| Slice | Tên | Đợt |
|---|---|---|
| 2 | Blueprint parsing và execution planning | Nền tảng |
| — | Planner proposal (proposal → validation → approval) | Nền tảng |
| 3 | Blueprint UI và Plan Preview | Nền tảng |
| 4 | Accepted plan → mock runtime | Nền tảng |
| 5A | Định tuyến thực thi tường minh | Nền tảng |
| 5B | Regeneration và supersession | Nền tảng |
| 5C | Phân quyền package và capability | Nền tảng |
| 5D | Observability vận hành | Nền tảng |
| 6A | Ranh giới provider OpenCode | Nền tảng |
| 6B | OpenCode opt-in trong disposable Git worktree | Nền tảng |
| 6C | Reviewable OpenCode source patches | Nền tảng |
| 7 | Orchestrator control plane | P0 + P1 |
| 8 | Run triggers và metrics | P2 |
| 9 | Approval expiry, SLA, notification, dead-letter | P3 đợt 1 |
| 10 | Template expressions, webhook notification, env thresholds | P3 đợt 2 |

## Quy ước thuật ngữ trong thư mục này

- Thuật ngữ tiếng Anh giữ nguyên vì là khái niệm kỹ thuật hoặc định danh: blueprint, node package, plan (danh từ kỹ thuật trong UI/API), worktree, harness, OpenCode, Langflow, webhook, SLA, dead-letter, artifact, trigger, flow, snapshot.
- Từ điển dịch bắt buộc: Stage → "giai đoạn", Task → "nhiệm vụ", Run → "lần chạy", Plan → "kế hoạch", Approval → "phê duyệt", PASS/FAIL → "ĐẠT/TRƯỢT" (trong văn xuôi; giá trị enum/wire như `PASS`, `VALIDATED`, `WAITING_APPROVAL` giữ nguyên), snapshot → "snapshot (ảnh chụp trạng thái)" lần đầu rồi dùng "snapshot", trigger → "trigger", flow → "flow", artifact → "artifact".
- Không dịch: tên file, đường dẫn, mã định danh, tên biến, lệnh CLI, tên test.
- Bảng, JSON, SQL, code block giữ nguyên cấu trúc dữ liệu của bản gốc.
- Mỗi phần lớn của `ke-hoach-slice.md` có dòng "Trạng thái: ✅ đã hoàn thành (đợt …)" phản ánh trạng thái ghi trong tài liệu nguồn.

## Nguồn

Bản gốc 15 tài liệu nằm trên nhánh `agentHarness` (không còn ở working tree), đọc bằng:

```bash
git show agentHarness:docs/<tên-file>.md
```

Danh sách đầy đủ 15 file kèm ghi chú nằm ở mục "Nguồn tổng hợp" cuối [`ke-hoach-slice.md`](./ke-hoach-slice.md). Các slice 6D/6E (tích hợp DeepSeek Harness) được tài liệu nguồn nhắc tới nhưng không nằm trong 15 file đó.

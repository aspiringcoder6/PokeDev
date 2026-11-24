# Task loop — vòng lặp nhiệm vụ

Thư mục này tài liệu hóa **task loop** của ADLC: cơ chế cho phép một nhiệm vụ (Task) chạy nhiều vòng lặp (iteration) có checkpoint, ngân sách và kiểm soát của con người, tách biệt runtime thực thi.

## Nội dung

| File | Nội dung |
|---|---|
| [`task-loop.md`](task-loop.md) | Ba đợt bàn giao A → B → C: nền móng, khả năng runtime, tích hợp cho người vận hành |
| [`bien-gioi-runtime.md`](bien-gioi-runtime.md) | Biên giới runtime thay thế được (protocol v0.1/v0.2) và adapter Harness proposal-only (2026-10-14) |

## Thứ tự đọc

1. `task-loop.md` — hiểu vòng lặp làm gì và ba đợt bàn giao đã thêm gì.
2. `bien-gioi-runtime.md` — hiểu biên giới protocol và cách Harness gắn vào như một runtime tùy chọn.

## Liên quan

- ADR 0021 — runtime-neutral task loop iteration & checkpoint boundary: [`../adr/0021-runtime-neutral-task-loop-iteration-and-checkpoint-boundary.md`](../adr/0021-runtime-neutral-task-loop-iteration-and-checkpoint-boundary.md)
- ADR 0022 — native Harness proposal-only task loop adapter: [`../adr/0022-native-harness-proposal-only-task-loop-adapter.md`](../adr/0022-native-harness-proposal-only-task-loop-adapter.md)
- Hợp đồng protocol: `../../adlc-contracts/task-loop-runtime/`
- Milestone liên quan: [`../milestones/harness-h6.md`](../milestones/harness-h6.md)

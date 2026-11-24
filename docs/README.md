# Tài liệu dự án ADLC (vAIPlatform)

Đây là kho tài liệu kỹ thuật của hệ thống **ADLC** — vòng đời phát triển phần mềm có agent, trong đó con người phê duyệt từng bước. Tài liệu được tổ chức **theo loại**, mỗi thư mục có `README.md` riêng dẫn đường.

## Thứ tự đọc gợi ý cho người mới

1. `../Readme.md` — ý tưởng sản phẩm và cách chạy dự án.
2. [`architecture.md`](architecture.md) — kiến trúc tổng thể.
3. [`state-machine.md`](state-machine.md) — máy trạng thái thực thi v0.1.
4. [`node-package-architecture.md`](node-package-architecture.md) — kiến trúc node package theo phiên bản.
5. [`adr/README.md`](adr/README.md) — các quyết định kiến trúc (ADR 0001–0022).
6. Tùy nhu cầu: [`plans/`](plans/), [`milestones/`](milestones/), [`task-loop/`](task-loop/), [`reference/`](reference/), [`operations/`](operations/), [`demos/`](demos/).

Các tính năng desktop mới: [phân loại issue và chính sách tự động](issue-triage-risk-policy.md), [canvas có điều kiện, cổng duyệt và thống kê](workflow-controls-and-project-metrics.md), [môi trường dự án, phục hồi và bàn giao Gitea](project-environment-recovery-handover.md).

Trang `/work` mở [dashboard và hàng chờ cần xử lý](workspace-dashboard-and-inbox.md). Bấm **Project mới** trong sidebar để mở kết nối repo, điều phối và xây dựng mới. Ở cấp workspace có Tổng quan, Yêu cầu & tài liệu, Lịch sử công việc và Kết quả; chọn một project để mở Công việc, Yêu cầu & tài liệu của project, Issue Gitea, Workflow, Kết quả, Thống kê, Môi trường và Cài đặt của project đó.

Hướng dẫn [thương hiệu vAIPlatform và bot Slack hiện có](vaiplatform-brand-and-slack.md): Cài đặt → Slack & Workloop, kiểm tra kết nối và mở bot để hỏi đáp/soạn tài liệu.

[Khảo sát UI/UX Workloop và lộ trình vAIPlatform](workloop-ux-review-2026-10-28.md): các thao tác web còn thiếu, sai lệch trạng thái và ba đợt cải tiến đề xuất.

Hướng dẫn [trình thiết kế workflow desktop](workflow-designer-desktop.md): chỉnh task theo từng mục, chọn file từ repo, mẫu luồng, lịch sử chỉnh sửa và nhập/xuất JSON.

Hướng dẫn [hành trình công việc và Workloop trong project](project-workloop-journey.md): canvas tiến trình cập nhật trực tiếp, diễn biến task, liên kết job, phản hồi và điều khiển theo quyền project.

Hướng dẫn [tiếp nhận tài liệu Slack và triển khai trong vAIPlatform](slack-document-journey.md): hộp yêu cầu tự cập nhật ở workspace/project, liên kết channel, duyệt theo phiên bản, chọn workflow và nối sang lượt chạy, kiểm thử và bàn giao.

Tài liệu [xây dựng Slack bot cho quy trình ADLC](slack-bot-implementation.md): cài đặt app, Socket Mode, quản lý phiên theo thread, luồng triển khai và phạm vi đã có so với các tương tác Slack cần bổ sung.

Báo cáo [tiếp nhận yêu cầu và tích hợp LarkSuite](report/intake-clarification-and-larksuite-research-20261124.md): agent hỏi làm rõ qua nhiều kênh, hồ sơ câu hỏi/câu trả lời, tài liệu tham chiếu, phương án App Bot Lark và lộ trình thử nghiệm.

## Cấu trúc thư mục

| Thư mục | Chứa gì |
|---|---|
| `adr/` | 22 quyết định kiến trúc (ADR 0001–0022) + mục lục |
| `plans/` | Kế hoạch triển khai theo slice (3→10) và lộ trình sản phẩm/UI/package |
| `milestones/` | Nhật ký các chặng milestone H4→H7 của Agent Harness |
| `task-loop/` | Vòng lặp nhiệm vụ: 3 đợt bàn giao + biên giới runtime & adapter Harness |
| `reference/` | Hợp đồng kỹ thuật, tích hợp agent, lịch sử chạy/phục hồi, map codebase, đánh giá Vanguard |
| `operations/` | Runbook vận hành: dịch vụ cục bộ, kết nối live |
| `demos/` | Kịch bản demo hiện hành + tổng hợp demo lịch sử |

## Dòng thời gian tóm tắt

| Giai đoạn | Nội dung | Tài liệu |
|---|---|---|
| Nền móng | Orchestrator ngoài, adapter thật, blueprint → execution plan | `plans/lo-trinh-san-pham.md` |
| Slice 3–6C | Planning, materialization, routing, authorization, observability, OpenCode | `plans/ke-hoach-slice.md` |
| Slice 7–10 | Orchestrator control plane, trigger/metrics, SLA, notification | `plans/ke-hoach-slice.md` |
| H4–H5 | Artifact review, hợp đồng đã duyệt, bằng chứng máy, phục hồi xác minh | `milestones/harness-h4-h5.md` |
| H6 | Tái lập độc lập, replay đóng băng, project memory, test proposal | `milestones/harness-h6.md` |
| H7 | Quyền theo project, bốn vai trò | `milestones/harness-h7a-team-roles.md` |
| Task loop | Đợt bàn giao A→C, biên giới runtime, adapter Harness | `task-loop/` |

> Các tài liệu nguồn gốc tiếng Anh đã được tổng hợp và viết lại bằng tiếng Việt; bản gốc vẫn lưu trong lịch sử git và trên nhánh `agentHarness` (mục `Nguồn tổng hợp` ở cuối mỗi tài liệu ghi rõ file nguồn).

[Rà soát repo Gitea cho Slack và vAIPlatform](gitea-integration-review-2026-10-28.md): nguồn liên quan, bản sửa Workloop mới, phản hồi tài liệu về Slack và cách triển khai máy chủ.

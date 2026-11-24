# Quyết định kiến trúc (Architecture Decision Records — ADR)

Mỗi ADR ghi lại một quyết định kiến trúc quan trọng của ADLC: bối cảnh, quyết định, hệ quả, các phương án đã cân nhắc và ràng buộc triển khai. **Bản thân các file ADR giữ nguyên tiếng Anh** vì là bản ghi quyết định chính thức; bảng dưới là tóm tắt tiếng Việt.

Trạng thái ADR:

- **Proposed (đề xuất)** — đang thảo luận, chưa ràng buộc.
- **Accepted (đã chấp nhận)** — triển khai phải theo quyết định này.
- **Superseded (bị thay thế)** — có ADR mới thay thế, phải được liên kết.
- **Deprecated (không dùng nữa)** — giữ để lưu sử, không dùng cho công việc mới.

## Danh mục quyết định

| ADR | Trạng thái | Quyết định (tóm tắt tiếng Việt) |
|---|---|---|
| [0001](./0001-versioned-node-packages.md) | Accepted | Biểu diễn khối thực thi tái sử dụng dưới dạng node package bất biến, đánh đúng phiên bản. |
| [0002](./0002-compile-blueprints-to-execution-plans.md) | Accepted | Biên dịch và kiểm tra blueprint ADLC trước khi tạo các aggregate runtime. |
| [0003](./0003-standard-stage-interface.md) | Accepted | Nối các giai đoạn cao cấp qua logical slot chuẩn và cạnh phụ thuộc không chu kỳ. |
| [0004](./0004-snapshot-resolution-and-legacy-compatibility.md) | Accepted | Snapshot các package đã phân giải, giữ tương thích Langflow thuần và ADLC cũ. |
| [0005](./0005-versioned-plan-regeneration-and-supersession.md) | Accepted | Tái tạo kế hoạch thành phiên bản kế nhiệm có đánh phiên bản, giữ snapshot và lần chạy lịch sử. |
| [0006](./0006-package-and-capability-authorization.md) | Accepted | Ủy quyền cho việc khám phá package, lập kế hoạch và materialize lần chạy mới mà không phá lịch sử bất biến. |
| [0007](./0007-secret-safe-operational-observability.md) | Accepted | Phát quan sát planning/dispatch không chứa nội dung qua sink cô lập lỗi, có thể thay thế. |
| [0008](./0008-integrate-opencode-through-agent-adapter.md) | Accepted | Tích hợp OpenCode sau `AgentAdapter` qua API server headless có xác thực. |
| [0009](./0009-route-live-agents-through-disposable-git-worktrees.md) | Superseded by 0010 | Điều phối executor cụ thể và cô lập lần chạy live trong worktree Git dùng một lần; quy tắc không giữ artifact đã bị 0010 thay thế. |
| [0010](./0010-retain-reviewable-source-patches-temporarily.md) | Accepted | Giữ source patch có giới hạn để chủ sở hữu review sau khi dọn worktree dùng một lần. |
| [0011](./0011-use-deepseek-harness-as-a-plugin-execution-hub.md) | Accepted | ADLC giữ vai trò control plane; DeepSeek Harness tích hợp như hub thực thi bất đồng bộ theo plugin. |
| [0012](./0012-tool-authored-approved-contract-documents.md) | Accepted | Dùng một typed writer duy nhất của ADLC cho sửa đổi hợp đồng bền vững và phê duyệt của con người đúng ngữ nghĩa; các tool Harness và cả hai UI chỉ là adapter/projection. |
| [0013](./0013-shared-contract-viewer-and-restricted-authoring.md) | Accepted | Chia sẻ viewer có xác thực giữa các host; authoring theo profile sáu tool fail-closed, giữ các khóa H4 và phê duyệt của con người tách biệt. |
| [0014](./0014-approved-contract-execution-policy-and-evidence.md) | Accepted | Gắn thực thi có giám sát vào tham chiếu đã được con người phê duyệt chính xác và bằng chứng do kernel ghi, không tuyên bố đúng đắn từ ngôn ngữ tự nhiên. |
| [0015](./0015-exact-contract-verification-recovery.md) | Accepted | Đối soát evidence/candidate đã checkpoint mà không chạy lại model, không viết lại bằng chứng bất biến, không biến Submit thủ công thành tự động. |
| [0016](./0016-adlc-contract-v0.2-control-flow-compensation-durable-events.md) | Proposed | Nâng hợp đồng lên v0.2: task điều khiển luồng (MAP/WHILE/SUBWORKFLOW) với runtime expansion, compensation kiểu saga cho rollback, và event row bền vững cho từng chuyển tiếp. |
| [0017](./0017-independent-reproduction-and-evidence-foundation.md) | Accepted (JSON fixture; remote rollout pending) | Tách biệt phê duyệt kế hoạch đóng băng, tái lập thật được bảo vệ, so sánh tất định và bằng chứng retained khỏi việc thành công của coding/review. |
| [0018](./0018-frozen-http-replay-and-testforge-readiness.md) | Accepted (HTTP fixture; TestForge blocked) | Đóng băng replay nhiều ca, yêu cầu bằng chứng target/JUnit chính xác và hủy có xác nhận; giữ nguyên H6A, các route TestForge chưa review vẫn tắt. |
| [0019](./0019-advisory-project-memory-and-protected-readonly-gateway.md) | Accepted (curated local pilot; Cognee pending) | Phái sinh project scope có xác thực, giữ provenance advisory và context retained; không có tổng hợp, ingestion hay xóa. |
| [0020](./0020-proposal-only-test-extensions-and-supplementary-raster-evidence.md) | Accepted (local UI/authoring; live extensions blocked) | Đóng băng proposal do tool tạo để chủ sở hữu review chính xác; tạo replay draft mới mà không "chữa" bằng chứng cũ; ảnh chỉ là bổ sung, thực thi rủi ro vẫn chặn. |
| [0021](./0021-runtime-neutral-task-loop-iteration-and-checkpoint-boundary.md) | Accepted (OpenCode; Harness adapter pending) | Chuẩn hóa binding runtime/candidate/checkpoint theo từng iteration; giữ xác minh/phê duyệt trong ADLC, phân biệt protocol có thể thay thế với thực thi thống nhất của Harness. |
| [0022](./0022-native-harness-proposal-only-task-loop-adapter.md) | Accepted (offline conformance; live sign-off pending) | Thêm iteration proposal Harness thuần, opt-in chính xác; chọn runtime tường minh và hạch toán chi phí chưa biết mà không dời Verify hay phê duyệt ra khỏi ADLC. |

## Định dạng ADR

Mỗi ADR ghi lại: bối cảnh, quyết định, hệ quả, các phương án thay thế và ràng buộc triển khai. ADR đã Accepted là bất biến, chỉ được bổ sung làm rõ. Một quyết định khác biệt về bản chất phải lập ADR mới thay thế bản cũ.

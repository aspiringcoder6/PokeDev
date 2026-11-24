# Kiểm chứng demo vAIPlatform — 30/10/2026

Đã kiểm chứng thật đoạn Slack/Confluence → nhận tài liệu → đọc → duyệt tại
vAIPlatform → bắt đầu lập kế hoạch. Chưa bàn giao quay toàn luồng thực hiện
và kiểm thử BE; chưa chạy task sửa code hoặc triển khai tính năng.

## Kiểm thử nhanh bổ sung lúc 11:34–11:39 GMT+7

Theo yêu cầu người dùng, không coi việc rollout Workloop PR #31 là điều kiện
chặn đoạn demo nhận link, đọc và duyệt. Không thêm bản tài liệu biên tập local.

- Đọc yêu cầu #22 qua API vAIPlatform thành công: page 4718649, v2,
  10.223 ký tự, không dùng cache lỗi; đúng project BE đã gắn.
- Duyệt đúng digest qua API thật nhận 200. Lượt sửa tài liệu cũ vẫn FAILED,
  không được đổi thành UPDATED để che lỗi publication.
- Lập kế hoạch qua API thật nhận 202, tạo duy nhất run
  `97d8b6e8-3b51-5b43-85ac-7333ad6fb17a`, phase `planning`.
  Origin giữ đúng document #22, page v2, digest và lifecycle nguồn.
- Gửi lại cùng command ID nhận đúng run đó, không tạo lượt hoặc agent mới.
  Đọc tài liệu khi chưa đăng nhập nhận 401.
- Harness đang xử lý P01 phân tích/soạn tài liệu; tại 11:39 vẫn PLANNING,
  chưa có kế hoạch task hoàn chỉnh. Model giữ Netmind/GLM-5.3-Flash.
- Kiểm tra lịch sử chính session P01 sau đó thấy turn kết thúc với
  `RATE_LIMIT`/HTTP 429: quota requests/team của GLM-5.3-Flash còn 0/300,
  reset được server báo là 04:40:52 UTC. Contract lúc kiểm tra vẫn
  IN_PROGRESS, nên không coi trạng thái PLANNING là bằng chứng model còn
  tạo nội dung hoặc kế hoạch đã hoàn tất. Không đổi model, không tăng quota
  và không dừng các job khác. Metadata không chứa nội dung suy luận được
  lưu ở `quick-handoff-session-metadata.json`.
- Thông báo Slack mới đã SENT lúc 11:34:56, đúng thread gốc:
  https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793334896226839?thread_ts=1793288792.857159&cid=C0CD66L5D4L
- Báo cáo Confluence 5079041 đã SYNCED trạng thái lượt chạy mới.
- 16 kiểm thử UI intake đạt, gồm nhận mới không dán link thủ công, duyệt
  digest, mở đúng run, không chạy khi chỉ đọc, xử lý mất phản hồi và archive.
  Công cụ browser vẫn không khởi tạo được (`failed to write kernel assets`),
  nên lượt thật được kiểm chứng qua API của UI, không phải thao tác hình ảnh.
- Gitea main BE vẫn `4a5e41b1e9d580c3b2a7fb9415c912c128fe6fe1`.
- Catalog đã có thêm source #23 cùng page/lifecycle từ lần revision cũ;
  không duyệt hoặc tạo run thứ hai cho receipt này. Cần xử lý hiển thị các
  receipt trùng trước khi coi toàn bộ trải nghiệm inbox đã hoàn tất.

Mở lượt thử:
http://127.0.0.1:7861/work?project=a22e1770-c121-4327-a057-088205b10605&run=97d8b6e8-3b51-5b43-85ac-7333ad6fb17a

Bằng chứng: `adlc-flow/data/slack-actions-check/intake-handoff-22-*`,
`quick-run-22.json`, `quick-inbox-22.json`, `quick-attention-22.json`.
Helper `deploy/verify_intake_handoff.py` mặc định chỉ đọc; `--apply` chỉ duyệt
và tạo kế hoạch, lưu command trước POST và không gọi execute task.

## Những phần đã xác minh

- Reset cũ có backup, 19 yêu cầu đã lưu trữ, 6 trang Confluence cũ ở Trash.
  Xem `military-youth-demo-reset-2026-10-29.md` và thư mục bằng chứng riêng
  `adlc-flow/data/demo-reset/20261029T143624Z/`.
- Một yêu cầu Slack thật đã gửi vào thread `1793288792.857159`, channel
  `C0CD66L5D4L`, lifecycle `lc-6L5D4L-8792857159`.
- Tài liệu tự vào vAIPlatform thành **yêu cầu #22**, page **4718649**.
  Page hiện vẫn v2, chỉ có phần 1–3. Chưa duyệt vì thiếu phần yêu cầu và
  nghiệm thu. Source Workloop có link không phải bằng chứng nội dung đầy đủ.
- Gắn đúng project BE `a22e1770-c121-4327-a057-088205b10605`; bật quy tắc
  channel → project, chia sẻ tiến độ và thông báo Slack. Không bật tự duyệt.
- Gửi góp ý qua **API của chính vAIPlatform** để hoàn thiện đủ phần 1–6,
  giữ các quy tắc year/joinDate, trạng thái, quyền xem và phạm vi BE/test.
  Không sửa trang chính bằng connector để giả làm kết quả của bot.
- Lệnh góp ý `da6061f7-8364-47f0-91d4-fd8283ed9c44`, invocation
  `ag-031007-b78b8c`, đã được theo dõi. Agent báo done nhưng trang không
  thay đổi; vAIPlatform ghi **FAILED / INTAKE_REVISION_NO_UPDATE**, không
  ghi UPDATED. Bản nháp đầy đủ còn trong bằng chứng để chẩn đoán.
- Sửa lỗi background publisher: archived source từng gây exception trước
  khối xử lý và làm ngừng cả vòng nền. Nay bỏ qua archived, cô lập nguồn
  biến mất/hỏng; các tài liệu khác và hàng đợi Slack vẫn tiếp tục.
- **70 kiểm thử backend đạt**. Ba ca hồi quy mới thử nguồn archived,
  removed và invalid trong vòng nền thực, kiểm tra tài liệu kế tiếp và
  delivery vẫn được xử lý. Không ghi nội dung riêng tư vào log lỗi.
- Sau restart đã có báo cáo tiến độ thật **5079041**, trạng thái SYNCED;
  thông báo thật trạng thái SENT, có liên kết đúng channel/thread:
  https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793330429050659?thread_ts=1793288792.857159&cid=C0CD66L5D4L

## Bản sửa Workloop đã chuẩn bị

[PR #31](http://10.0.10.195:3000/admin/workloop/pulls/31), nhánh
`codex/confluence-storage-publication`, commit
`918cab52f8e91ab43c76f5e85c670af18e189702`, base
`agent-docs-langflow-dag` tại `485b8e61825bb94dfa46c8bd6b3d7066b03c4a4b`.
Kiểm tra lại qua API Gitea sau phản hồi của người dùng: PR đã bỏ tiền tố
WIP, trạng thái closed và merged=true; head vẫn là commit trên. Chưa có
bằng chứng dịch vụ đang chạy đã triển khai bản sửa. Repo hiện chỉ có
workflow `lint-docs.yaml`, không có workflow tự triển khai trong repo.
Công cụ attachment của Codex từ chối URL Gitea; link trực tiếp và
head/files của PR đã được kiểm tra qua API.

Phép thử trực tiếp qua API Workloop nhận:
`502`, detail `Confluence 500: INTERNAL_SERVER_ERROR`. Đây là lỗi ghi ở
Confluence; bản nháp đầy đủ 17.598 ký tự không ghi thành công qua converter
wiki hiện tại. Không tiếp tục thử cắt nội dung trên trang chính.

Bản sửa chuyển Markdown thành XHTML trước khi ghi `representation=storage`,
giữ đề mục/bảng/code và escape HTML đầu vào. Thêm dependency được khóa
`markdown-it-py==4.2.0`, `mdurl==0.1.2`; giữ bước tăng version khi update.

- **5 kiểm thử publication đạt**, bao gồm tài liệu hơn 20.000 ký tự, đủ
  phần cuối, XML hợp lệ, code/bảng, HTML an toàn, create/update/version.
- Render bản nháp thật: XHTML 22.596 ký tự, text 17.182; yêu cầu lập kế hoạch
  sau ghép metadata 17.496, trong giới hạn 20.000 hiện tại của vAIPlatform.
- Thử ghi độc lập bằng connector HTML của Confluence thành công: đủ 6 phần,
  14 bảng, 1 khối code. Trang thử **4980739 đã archive** sau đọc lại.
  Phép thử này không thay cho kiểm chứng REST storage của Workloop sau deploy.
- Probe wiki thất bại có UUID riêng, tra cứu đúng title không có trang
  current. Không lặp lại POST không rõ kết quả hoặc tạo nhiều bản probe.

File để rebuild/review ở `integration-sources/workloop-confluence-fix/`.
Hướng dẫn rollout/rollback nằm trong PR và
`integration-sources/workloop-confluence-fix/docs/confluence-publication-fix.md`.
`deploy/publish_confluence_fix.py` mặc định audit; `--apply` đã dùng để
đưa đúng 4 file vào nhánh riêng, không đẩy toàn bộ checkout ADLC đang có
nhiều thay đổi khác.

## Điều kiện cần để tiếp tục

Người dùng hỏi merge PR có đủ không. API xác nhận PR đã merge, nhưng
chưa có cách truy cập SSH/console hoặc xác nhận người quản lý server
đã rollout bản mới. Merge mã nguồn chưa thay thế bước triển khai dịch vụ.

- Repo runner: không có. Admin runner: `sandbox-runner`, nhãn `linux-host`,
  **offline**. Không tạo runner/token hoặc mở thêm quyền.
- Docker CLI trên máy này chỉ có context local Windows/Docker Desktop;
  không có context tới server. Không dò cổng hay đổi VPN.
- Compose trong repo build image `workloop:latest`, không mount source Python
  backend; sync Factory chỉ nạp persona/workflow, không triển khai Python.
  Cần rollout backend có dependency mới, giữ data/vault/factory/workspace
  và cấu hình hiện có. Nếu MCP dùng image riêng, đồng bộ image tương ứng.

Sau khi có đường triển khai, tiếp tục:

1. Triển khai bản sửa, giữ nguyên dữ liệu và credential; kiểm tra dịch vụ.
2. Retry đúng góp ý của yêu cầu #22 bằng request ID mới, chỉ sau khi đã
   đối soát lần cũ FAILED. Đọc version mới và đầy đủ phần 1–6 từ Confluence.
3. Kiểm tra các receipt Spec mới cùng page/lifecycle có tạo thêm dòng inbox
   hay không; giữ đúng nguồn của góp ý, không duyệt bản cũ chỉ vì có link.
4. Duyệt đúng digest/version, lập kế hoạch, duyệt task, chạy và kiểm chứng
   sơ đồ trạng thái, điểm cần người phản hồi, test, diff/PR và Slack thật.
5. Giữ `main` BE trước tính năng để quay lượt khác; không tự merge feature
   demo vào baseline. Chạy nhánh/PR thử riêng.

## Các giới hạn nghiệm thu còn lại

- BE gốc đã chạy trên commit import: 63 test, 5 failure, 0 error. Đã sửa
  lỗi môi trường Mockito bằng javaagent; 5 failure của mã gốc còn nguyên
  (DefenseDiplomacy, YouthUnionMapper, TechnicalStructure). Không bỏ test
  hoặc đổi trạng thái để báo xanh.
- Profile BE revision 6; Java 21/Maven, thư viện nội bộ đã chuẩn bị. Preview
  API có database/auth thật chưa được kiểm chứng; chưa cấu hình preview.
- Sau cập nhật công cụ, `node_repl` không khởi tạo được (`failed to write
  kernel assets`), kể cả một lần reset và thử lại. Không tuyên bố đã kiểm
  tra UI trực tiếp trong phiên 30/10. Các bằng chứng browser 29/10 vẫn còn;
  kiểm chứng 30/10 dùng API. Không dùng CLI/CDP để vượt lỗi công cụ UI.
- App local có thể cần chạy lại `deploy/start.ps1` sau khi thoát app hoặc
  reboot. Script dùng đúng env/DB/key đã lưu. Không thêm autostart hoặc sửa
  cấu hình VPN.

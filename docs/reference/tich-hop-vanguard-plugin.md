# Kế hoạch tích hợp plugin Vanguard: Sandbox, TestForge và Agent Memory

Trạng thái: **Kế hoạch tích hợp; H6A/B pilot cục bộ, H6C ngữ cảnh read-only và H6D UI/authoring có
giới hạn đã triển khai; kích hoạt từ xa còn đang chờ**. Đã kiểm tra/tải ngày 2026-10-12
(Asia/Saigon). Các ghi chú tải trước đó dưới đây mô tả kho thượng nguồn chưa hoạt động.

**Cập nhật 19/10/2026:** theo yêu cầu mới, đã cài `vai_testforge@1.0.0` và
`vai_agentmemory@1.0.0` từ Gitea nội bộ vào profile `web` của Harness trong project;
đăng ký tool và hai health check đã đạt. Sau lượt cài đã khởi động Docker Harness
`0.1.5-rc.2`; sau khi người dùng bật VPN, cả hai tool health trả `status: ok` và
hiển thị kết quả thật trên UI. ADLC vẫn báo `testforge_ready: false`; chưa hoàn tất
adapter/kiểm chứng ở kế hoạch dưới đây. Xem [biên bản cài plugin](../operations/cai-plugin-testforge-agentmemory.md)
và [kết quả kiểm tra UI sau VPN](../operations/kiem-tra-plugin-testforge-agentmemory-ui-20261019.md).

## 1. Kết quả mong muốn và nguồn đã tải

Tích hợp ba năng lực mặt thực thi phía sau control plane hiện có của ADLC:

- Sandbox: tái tạo candidate trong một môi trường cô lập, có giới hạn.
- TestForge: thực thi các check replay/regression/performance đã phê duyệt và thu thập bằng chứng.
- Agent Memory: cung cấp ngữ cảnh project có phạm vi và lưu giữ tri thức đã tuyển chọn sau khi được
  chấp nhận.

Các nguồn nằm trên máy này tại `D:/coding/ADLC/integration-sources/harness-plugins/`. Chúng là các
checkout tham chiếu chưa hoạt động, cố ý tách biệt với deployment hiện có.

| Nguồn | Commit đã pin | Giao diện đã kiểm tra |
| --- | --- | --- |
| [vai-sandbox](http://117.5.151.111:9981/admin/agent-harness-server/src/branch/master/deepseek-harness/plugins/vai-sandbox) | `8c892b2491bc6f8be0f2b439fe782707b7ad169a` | `vai-sandbox@1.0.0`; 27 tool `sandbox_*` |
| [vai-testforce](http://117.5.151.111:9981/admin/agent-harness-server/src/branch/master/deepseek-harness/plugins/vai-testforce) | `8c892b2491bc6f8be0f2b439fe782707b7ad169a` | `vai-testforce@1.0.0`; 7 tool `testforge_*`; tên dịch vụ/sản phẩm là TestForge |
| [vai_agentmemory](http://117.5.151.111:9981/admin/vai_agentmemory) | `65a84337aec82b9aa5166f0712e56428f7734355` | package `vai_agentmemory@1.0.0`, tên runtime `vai-agentmemory`; 6 tool `memory_*` |

[Source lock](../../integration-sources/harness-plugins/source-lock.json) ghi checksum cho
13 tệp đã chọn. Đây là metadata provenance, không phải một `plugin_lock` dùng để deployment. Cả hai
repository đều detached tại commit đã ghi; Harness dùng sparse checkout cho hai thư mục được yêu
cầu. Checkout của chúng bị repository cha bỏ qua, còn kho hàng (inventory) và kế hoạch có thể được
version hóa.

Không có plugin, patch, tệp môi trường, secret, cài đặt model, dịch vụ hay cơ sở dữ liệu hiện có
nào bị thay đổi. Không thực thi script cài đặt/phụ thuộc thượng nguồn, tool plugin, job test từ xa
hay model. Ba điểm vào vượt qua parsing chỉ kiểm tra cú pháp và các tệp JSON package đọc được. Điều
này chưa thiết lập tương thích runtime hay độ sẵn sàng backend.

Điểm vào sandbox cục bộ expose 20 tool, trong khi điểm vào đã tải expose 27 tool. Cả hai khai báo
phiên bản `1.0.0` nhưng nội dung khác nhau. Không ghi đè bản đang hoạt động hay suy ra tương thích
chỉ từ chuỗi phiên bản.

## 2. Quyết định kiến trúc

ADLC vẫn là nguồn quyết định cho định nghĩa workflow, kế hoạch được chấp nhận, phê duyệt, owner,
định danh nhiệm vụ/attempt, ngân sách retry và chấp nhận kết quả cuối. Harness là mặt thực thi.
Phản hồi của dịch vụ bên thứ ba và JSON do agent viết là đầu vào, không phải quyền cấp phép hay
quyết định thành công.

Dùng [ranh giới tích hợp](../adr/0011-use-deepseek-harness-as-a-plugin-execution-hub.md)
và [đường scheduler/phục hồi hợp nhất](tich-hop-coding-agent.md)
hiện có. Không thêm một scheduler workflow thứ hai dùng Python runner của Vanguard.

Luồng đề xuất:

```text
Ngữ cảnh memory có phạm vi, nếu cần
  -> soạn roadmap / đề xuất test
  -> phê duyệt của con người cho contract + kế hoạch xác minh chính xác
  -> chấp nhận kế hoạch thực thi ADLC
  -> đóng băng candidate và test input đã phê duyệt
  -> cấp phát sandbox / staging target scoped theo lần chạy
  -> chạy TestForge suite đã phê duyệt (hoặc fixture runner tất định)
  -> import bằng chứng có xác thực
  -> so sánh bằng chứng với tiêu chí cố định
  -> preview xác minh dùng chung
  -> Submit thủ công / callback có chữ ký / chấp nhận của ADLC
  -> publish memory tuyển chọn tùy chọn
```

Phê duyệt contract, chấp nhận kế hoạch thực thi, ủy quyền tác động phụ, Submit kết quả và phê
duyệt release là các thao tác riêng biệt. Một báo cáo pass không thể ủy quyền cho deployment, xoá
dữ liệu hay Git push.

| Adapter đề xuất (mới, version riêng) | Trách nhiệm | Không được nắm |
| --- | --- | --- |
| `vai-adlc-sandbox-runtime` | Giải quyết snapshot project; cấp phát/đối chiếu sandbox sở hữu; đóng băng môi trường; giới hạn thực thi và vòng đời | Lập lịch workflow, truy cập host rộng, quyết định phê duyệt |
| `vai-adlc-verify-testforge` | Submit/đối chiếu job có phạm vi; xác thực kết quả; công bố receipt và báo cáo so sánh | Test oracle chỉnh sửa được, tự phê duyệt, tải không giới hạn |
| `vai-adlc-memory` | Giải quyết dataset owner/project; truy xuất provenance; công bố tri thức đã chấp nhận được tuyển chọn | Contract chính thức, phán quyết chính thức, lịch sử lần chạy |
| `vai-adlc-verify-ui` | Render một projection bằng chứng được bảo vệ trong ADLC và Harness | Credential, proxy phê duyệt ẩn, trạng thái độc lập |

Các tên này là đề xuất, không phải module đã cài. Giữ client thượng nguồn thô phía sau các adapter;
không expose mọi tool thượng nguồn cho mọi agent. Cô lập dịch vụ/profile mới để việc đăng ký một
verifier không thể thay thế verifier của một runtime H4/H5 hiện có.

Bảo toàn tệp, recipe, lock và ngữ nghĩa bằng chứng H4/H5 đã công bố. Đưa vào schema đóng mới,
recipe opt-in và hồ sơ xác minh version riêng thay vì mở rộng các verifier literal H5C hiện có tại
chỗ. Các check patch/không-thay-đổi/cú-pháp-JSON hiện tại của nó không chứng minh hành vi chức năng.

## 3. Năng lực thực tế và khoảng trống tích hợp

### Sandbox Kit

Client bọc các route quản lý broker, thực thi, VFS, Git và cổng. Nó thêm các thao tác lifecycle,
ingestion project từ host, xử lý DinD và chỉ số tái dùng phiên trong phạm vi tiến trình. Workspace
VFS là bền vững; phiên sandbox là dùng một lần. Plugin không phải broker hay phần triển khai cô lập
của nó.

Các thay đổi bắt buộc tại ranh giới tích hợp:

- Suy ra quyền sở hữu workspace/phiên từ owner, project, lần chạy và attempt của ADLC. Không để
  agent chọn session ID hay workspace khác. Map `projectSessions` toàn cục của module không phải
  quyền sở hữu bền, fencing hay tạo exactly-once.
- Dùng tham chiếu nguồn local-project đã pin hiện có và patch/tree digest thực tế của candidate.
  `host_path` nghĩa là đường dẫn trên **broker host**, không tự động là đường dẫn `D:/coding/...`
  của máy này. Chuyển một snapshot có giới hạn đã phê duyệt khi hai host khác nhau.
- Niêm phong (seal) snapshot VFS theo từng attempt trước khi xác minh. Broker thượng nguồn re-sync
  nội dung VFS có thể thay đổi trước các lời gọi shell; không niêm phong thì một test sau đó có thể
  chạy mã khác với patch đã xem xét.
- Chọn image digest, lệnh, tài nguyên, TTL, đường dẫn scratch ghi được và chính sách mạng từ một
  profile đáng tin. Bắt đầu với runner đã pin đơn giản; yêu cầu profile cô lập đã được xem xét trước
  workload DinD.
- Giữ commit, push, force-push, URL repository tùy ý và vai trò đặc quyền ngoài các profile
  coding/xác minh ban đầu. Các tool Git thượng nguồn expose `role: human` do người gọi cung cấp;
  quyền backend có xác thực, chứ không phải chuỗi đó, phải quyết định thẩm quyền. Không bao giờ dùng
  bearer token của sandbox làm fallback Git PAT.
- Không biến tool tải script lên thành lối thoát chính sách. Mã nguồn của nó ghi rõ broker kiểm tra
  shell wrapper chứ không phải phần thân script. Dùng các thao tác runner có giới hạn đáng tin; mã
  candidate tùy ý vẫn phải bị giam bởi các kiểm soát sandbox, mạng và filesystem.
- Thay thế việc dùng `sandbox_save_file` chung chung làm trình import bằng chứng. Nó chấp nhận URL
  fetch tùy ý và ghi bên dưới gốc HOME của toàn tiến trình bằng kiểm tra path lexical. Chỉ import
  artifact job có xác thực, nằm trong allowlist, với giới hạn kích thước, kiểm tra redirect, bảo vệ
  real-path/symlink và lưu trữ scoped theo attempt.
- Xem xét retry cho mutation. Phản hồi bị mất cho create, thực thi hay ghi Git là một kết quả không
  chắc chắn, không phải quyền lặp lại tác động phụ. Phục hồi qua operation key bền; tạm dừng nếu
  broker không thể đối chiếu an toàn.

Các hướng dẫn vận hành thượng nguồn có chỉ dẫn health-check mâu thuẫn: một nơi dùng health flag của
Docker trong khi playbook DinD nói flag này có thể không khả dụng. Readiness phải dùng một probe
thật có giới hạn, định nghĩa bởi profile, không phải chờ vô hạn hay văn bản chép lại.

### TestForge

Bảy tool bọc health, testcase recall, exploration, replay, staging regression, performance testing
và job polling. Plugin nộp job HTTP tới một broker Windows; nó không bao gồm broker, Playwright
runner, k6 hay các deployment dịch vụ của chúng.

Phân tách bắt buộc:

- `explore` sinh testcase/phiên **nháp**. Nó có thể tương tác với ứng dụng và tạo dữ liệu; không
  phải read-only và không phải xác minh với một tiêu chuẩn đã cố định sẵn.
- `replay`/`staging` xác minh một suite đã đóng băng, đã phê duyệt. Xác minh ban đầu dùng
  `heal=false`; việc sửa chữa tạo đề xuất/revision mới và yêu cầu phê duyệt trước khi dùng lại.
  Không âm thầm thay đổi kết quả mong đợi, bỏ qua assertion hay "chữa" một test đã đóng băng thành
  pass.
- `perf` chỉ chạy workload đã phê duyệt cố định vào một test target được phép. Chuỗi `approved_by`
  do model cung cấp không phải receipt phê duyệt. Suy ủy quyền từ ADLC; các lần chạy stress/high-load
  yêu cầu ủy quyền tường minh và trần tài nguyên.
- Template dọn dẹp có thể gọi DELETE. Giới hạn chúng cho dữ liệu fixture do lần chạy tạo và một thao
  tác dọn dẹp được phê duyệt trước; không bao giờ chấp nhận đường dẫn dọn dẹp production tùy ý.
- Client expose đường dẫn tới tệp trên broker Windows. `input_inline` tồn tại cho exploration, nhưng
  staging suite/profile và yêu cầu performance vẫn là đường dẫn trên broker host. Cần một contract
  upload/materialization và đọc artifact có giới hạn; không giả định tệp ADLC cục bộ tồn tại ở đó.
- Lưu intent yêu cầu và `job_id` bên ngoài trước khi dựa vào polling. HTTP wrapper hiện tại retry
  các POST nhưng không cung cấp idempotency key nhìn thấy được. Xác nhận/thêm idempotency và lookup
  phía broker trước khi bật retry tự động. Một ledger phía client một mình không thể xử lý POST
  timeout có thể đã khởi động một job.
- Polling timeout hay yêu cầu bị hủy không dừng job từ xa. Bề mặt bảy tool không có thao tác hủy.
  Có/thêm contract hủy có phạm vi, hoặc tường minh hiển thị job không chắc chắn/vẫn đang chạy cho đến
  khi vòng đời có giới hạn của nó kết thúc; không báo nó đã dừng nếu chưa có xác nhận.
- `status=completed` chỉ chứng minh job hoàn thành. Có schema kết quả có kiểu của broker và artifact
  assertion/JUnit/đo lường thực tế. Log hay đuôi JSON đã parse là chẩn đoán, không phải ledger đầy
  đủ các case bắt buộc.

Tiêu chí performance nên ánh xạ tới ngưỡng k6 cố định và giá trị đo được; k6 định nghĩa ngưỡng là
điều kiện pass/fail, ngưỡng fail gây exit khác 0 cho tiến trình. Xác thực cả tập đo lường bắt buộc
lẫn exit status.
[Ngưỡng k6 chính thức](https://grafana.com/docs/k6/latest/using-k6/thresholds/)

### Agent Memory / Cognee

Sáu tool bọc một dịch vụ MCP: health, câu trả lời tổng hợp, ngữ cảnh thô, ingestion, trạng thái
ingestion và xoá. Backend database, graph/vector store, xác thực và cấu hình model không nằm trong
repository plugin này.

Các thay đổi bắt buộc:

- Suy phạm vi tenant/dataset từ định danh owner/project ADLC có xác thực và thực thi nó ở dịch
  vụ/gateway. Không dùng chung `opencode@local` mặc định hay cho phép tên dataset tùy ý. Nếu Cognee
  thuần không thực thi được cô lập multi-owner, không bật truy cập dùng chung cho đến khi có gateway
  thực thi hay các deployment cô lập.
- Khởi tạo và cache schema thành công **trước khi** áp dụng đối số tenant. Các call site hiện tại
  đánh giá `withTenant` trước handshake lazy đầu tiên của client; cache ban đầu rỗng. Việc dò schema
  best-effort không được âm thầm tắt tenancy bắt buộc. Kiểm tra hành vi lần gọi đầu, reconnect và
  handshake đồng thời.
- Thêm phân giải transport/credential có xác thực. Trao đổi MCP hiện tại không gửi authorization
  header; đối số tenant hay session ID MCP không phải xác thực người dùng. Đàm phán tương thích giao
  thức, xử lý JSON/SSE đúng và giữ phiên scoped theo định danh có xác thực liên quan.
  [Yêu cầu transport/bảo mật của MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- Bảo toàn document ID nguồn, revision, digest, timestamp và trích dẫn, thay vì chỉ văn bản phẳng mà
  `extractText` hiện trả về. Nội dung truy xuất là ngữ cảnh không đáng tin, có thể cũ. Nó không thể
  ghi đè contract đã phê duyệt hay tự động trở thành kết quả mong đợi.
- Bắt đầu chỉ với `memory_context`/trạng thái có phạm vi và readiness. Bật `memory_ask` tổng hợp và
  ingestion sau khi xem xét routing model backend và chi phí. Ingestion mặc định là tự cải thiện và
  có thể thay đổi tri thức vượt ngoài văn bản đã nộp.
- Giữ ghi memory tự động ở trạng thái tắt ban đầu. Sau này, công bố tóm tắt đã chấp nhận được tuyển
  chọn, đã che secret, qua một outbox tùy chọn bền. Sự cố memory không được xoá hay làm mất hiệu lực
  kết quả đã chấp nhận của ADLC. Liên kết mỗi mục về contract/báo cáo/artifact digest nguồn của nó.
- Giữ `memory_forget` tắt với agent. `confirm=true` là boolean do người gọi cung cấp, không phải
  quyết định của con người. Dùng phê duyệt owner tường minh cho một mục/dataset cụ thể. Thực thi kích
  thước upload đã giải mã, chính sách retention và xoá; giới hạn upload 10 MB được ghi tài liệu
  không được client này thực thi nhìn thấy được.

Không expose connector MCP Cognee thô cùng với adapter giới hạn trong cùng một profile: điều đó sẽ
bypass các kiểm soát dataset và ghi/xoá.

## 4. Contract xác minh máy đọc được đề xuất

Tạo các đối tượng đóng, có phiên bản mới, lưu trong ADLC và đọc được bởi cả con người lẫn agent:

| Bản ghi | Các binding và nội dung bắt buộc |
| --- | --- |
| `VerificationPlan` | Tham chiếu roadmap đã phê duyệt chính xác; ID tiêu chí/case; assertion có kiểu và giá trị mong đợi; suite/config digest đã đóng băng; tham chiếu target/môi trường đã phê duyệt; phiên bản runner/verifier; hạng rủi ro, timeout, workload, tác động phụ được phép và chính sách skip |
| `ExecutionReceipt` | Phạm vi owner/lần chạy/nhiệm vụ/attempt/yêu cầu; execution ID và job/sandbox ID của broker; plan digest; candidate/nguồn/build digest chính xác; suite/image/config digest thực tế; thời gian bắt đầu/kết thúc, exit/trạng thái, hoàn thành theo case và mô tả bằng chứng có checksum, có xác thực |
| `VerificationReport` | Tham chiếu plan/receipt/candidate; mong đợi so với quan sát theo từng tiêu chí; tham chiếu bằng chứng; độ bao phủ case hoàn thành; phiên bản comparator; phán quyết so sánh hoàn thành và chẩn đoán thực thi |

Con người phê duyệt đúng revision kế hoạch đó. Chỉnh sửa sau đó fork ra bản kế nhiệm; chúng không
cập nhật tiêu chuẩn đã phê duyệt đang chạy. Độ tươi của candidate được kiểm tra lại trước khi chấp
nhận hay một hành động được ủy quyền riêng.

Cho việc soạn thảo, đề xuất sáu tool nhỏ: `verify_init`, `verify_upsert_case`, `verify_remove_case`,
`verify_set_target`, `verify_get_status`, `verify_validate`. Schema xác thực assertion có kiểu và
tham chiếu thao tác/target đã biết. Đây là đề xuất, không phải tool hiện có. Phê duyệt và thực thi
đáng tin vẫn nằm ngoài các tool mutation đó; văn bản của agent không bao giờ trở thành lệnh thực thi
được hay credential.

Xác minh = tái tạo thật + so sánh tất định. Lỗi thực thi khác với một phép so sánh đã hoàn thành:

| Điều kiện | Ý nghĩa báo cáo đề xuất | Projection Harness hiện có |
| --- | --- | --- |
| Các assertion bắt buộc được thực thi với bằng chứng khớp và tất cả đạt tiêu chuẩn cố định | PASS | PASSED |
| Phép so sánh hoàn thành hợp lệ mâu thuẫn ít nhất một assertion bắt buộc | FAIL | FAILED |
| Timeout, lỗi tool, binding cũ, thiếu bằng chứng, target không hỗ trợ hay case bắt buộc chưa hoàn thành | NOT VERIFIED; không có phán quyết nhị phân | ERROR / chẩn đoán chặn |
| Check tùy chọn được cho phép tường minh bị bỏ qua | SKIPPED; không bao giờ là PASS bắt buộc | SKIPPED |

Không âm thầm thêm giá trị NOT_VERIFIED không được hỗ trợ vào enum Harness v0.1 đã công bố. Giữ ý
nghĩa chi tiết trong một bản ghi có kiểu mới và projection nó một cách cố ý. Một lần chạy fail hay
lỗi vẫn giữ bằng chứng chẩn đoán; nó không thể được chấp nhận như một kết quả đã xác minh thành công.

Từ chối suite rỗng, không có test nào được thu, case bắt buộc toàn bị skip, định danh case ngoài dự
kiến, target/candidate digest không khớp và receipt bịa. JUnit/JSON phải được parse với giới hạn
byte/độ sâu và xử lý XML an toàn. Tệp do candidate tạo ra không tự động là chứng nhận runner đáng
tin; đối chiếu quan sát qua runner đáng tin và assertion cố định.

[Quality gate](../../adlc-flow/langflow/adlc/quality_gate.py) hiện có đọc metadata testing.
Với các recipe đã xác minh mới, chỉ cung cấp metadata đó sau khi validator chấp nhận đã xác thực
receipt/báo cáo gắn kết. Thêm check bắt buộc có test và bắt buộc có đo lường vào chính sách mới.
`testing.outcome=PASSED` của agent, log sạch hay trạng thái nhiệm vụ hoàn thành không được phép vượt
qua việc xác thực bằng chứng. Bảo toàn hành vi recipe cũ.

## 5. Quyền sở hữu target, job và bằng chứng

Dùng `environment_ref`, `broker_ref`, `credential_ref` và `dataset_ref` thuộc sở hữu deployment.
Giải quyết URL, mật khẩu và đường dẫn host thật phía server. Không nhúng secret hay đích
callback/artifact tùy ý trong blueprint JSON.

Sandbox có thể chạy trên Linux trong khi TestForge chạy trên một host Windows khác. TestForge phải
truy tới **instance candidate được cấp phát**, không phải một deployment staging mặc định không liên
quan. Cấp phát một endpoint dịch vụ riêng tư/có xác thực có giới hạn, ghi lại định danh instance/build
của nó và chứng minh target sẵn sàng trước khi nộp job. Giới hạn origin, cổng và redirect được phép.
Không tự động expose một cổng ứng dụng công khai.

Lưu kế hoạch đã phê duyệt, receipt, JSON so sánh và bằng chứng trong kho lưu trữ ADLC scoped theo
owner/lần chạy/nhiệm vụ/attempt trước khi giải phóng phiên bên ngoài. Khái quát hóa interface
artifact với các kiểu mới và hạn ngạch retention/kích thước tường minh cho JUnit, JSON, screenshot,
trace và video; không âm thầm tái dụng hay nới giới hạn source-patch hiện có của H4. Bằng chứng
thiếu/hết hạn vẫn hiển thị là không khả dụng, không bị thay thế từ memory.

Phục hồi sau restart gắn lại job/phiên đã ghi và nhận các receipt đã lưu. Nó không khởi động một
lượt model khác hay nộp job khác chỉ vì polling đã dừng. Hủy, dọn dẹp và giữ bằng chứng là tách
biệt; dọn dẹp không thể vứt bằng chứng cần cho xác thực cuối.

## 6. Giao diện người dùng dùng chung

Tái sử dụng mẫu trình bày ADLC được bảo vệ theo owner và pattern projection Harness hiện có:

- Roadmap/Contract: hiển thị tham chiếu và revision đã phê duyệt chính xác.
- Bảng Verify: hiển thị kế hoạch, candidate/target, trạng thái job, độ bao phủ và so sánh mong
  đợi/quan sát theo từng tiêu chí.
- Bảng Bằng chứng: preview/tải xuống có xác thực cho JSON/JUnit/screenshot/trace có checksum; thất
  bại cũng được giữ lại.
- Ngữ cảnh Memory: hiển thị phạm vi dataset, liên kết nguồn gốc và độ tươi; gán nhãn là tham vấn,
  không phải bằng chứng xác minh.
- Hành động: phê duyệt/fork trong ADLC dưới xác thực owner; hiển thị Submit thủ công chỉ theo quy
  tắc lifecycle hiện có của nó. Harness hiển thị projection được bảo vệ và không lấy credential ADLC
  hay proxy phê duyệt.

Render chuỗi, log và tệp báo cáo an toàn. Không nhúng HTML runner tùy ý hay để render của plugin trở
thành thẩm quyền UI thực thi được. Huy hiệu PASS màu sắc phải luôn liên kết tới kế hoạch chính xác
và bằng chứng đã ghi.

## 7. Các đợt bàn giao và chấp nhận

### H6A — Nền tảng tái tạo đáng tin và bằng chứng

Trạng thái triển khai (2026-10-12): nền tảng JSON-fixture có giới hạn và UI dùng chung đã triển
khai. Xem milestones/harness-h6.md. Broker được cấp đã được kiểm tra read-only; thực thi từ xa chưa
được chứng nhận live và vẫn tắt. Tích hợp TestForge, memory và quality-gate còn là các đợt sau.

Giữ khuyến nghị H6A trước đó: một vòng xác minh thật, tất định trước tự động hóa rộng. Định nghĩa
schema plan/receipt/báo cáo đóng và cổng dịch vụ; xem xét contract broker Sandbox và profile cô lập;
triển khai sandbox adapter có phạm vi; lưu trữ bằng chứng và cung cấp bảng Verify dùng chung tối
thiểu.

Dùng một fixture/test runner hiện có có giới hạn, không phải linter Vanguard chưa xây. Chứng minh
một PASS và một FAIL assertion thật, cộng với thiếu bằng chứng, không có test, timeout, từ chối
cross-owner và từ chối candidate cũ. Minh họa quan sát sau restart mà không chạy lại candidate/model.
Nếu broker không cung cấp được đối chiếu thao tác hay quan sát đáng tin, dừng an toàn và ghi lại
năng lực backend còn thiếu.

### H6B — TestForge replay/regression đóng băng

Trạng thái triển khai: pilot fixture HTTP-JSON đóng băng riêng biệt, binding suite/config/candidate
chính xác, JSON/JUnit giữ lại có xác thực, hủy đã xác nhận, phục hồi chỉ-quan-sát và UI ADLC/Harness
dùng chung đã triển khai. Xem milestones/harness-h6.md. Master hiện tại của repository được yêu cầu
vẫn trỏ tới revision đã pin ở trên và chỉ chứa client TestForge, không có broker/runner. TestForge
từ xa bị tắt. Điều này **không** hoàn thành phần chấp nhận TestForge staging/browser thật dưới đây.

Có được OpenAPI/schema kết quả của broker và mã nguồn/revision backend. Bổ sung upload/materialization,
đọc artifact có xác thực, lookup idempotency và hủy ở nơi còn thiếu. Triển khai replay/staging đóng
băng với `heal=false`, tài khoản test đã phê duyệt và dọn dẹp có phạm vi. Tái sử dụng bản
ghi/validator/UI của H6A.

Chấp nhận: một suite đã phê duyệt thực thi với candidate đã ghi; các case bắt buộc và artifact thực
tế khớp; case fail/thiếu/skip chặn thành công; phản hồi create bị mất không thể gây job trùng lặp tự
động. Bắt đầu với fixture phi production, không phải exploration hay load test tùy ý.

### H6C — Memory scoped theo project

Trạng thái triển khai (2026-10-13): schema ngữ cảnh project đóng, API đọc owner/phiên được bảo vệ,
MCP adapter initialize-trước-scope có xác thực, provenance được giữ và UI Memory ADLC/Harness dùng
chung đã triển khai. Một gateway tuyển chọn loopback riêng cung cấp lượt đọc lexical tất định không
cần model. Xem milestones/harness-h6.md. Cognee live chưa được chứng nhận; plugin/connector thô,
synthesis, ingestion và xoá vẫn tắt. Việc xem xét backend và chấp nhận ingestion/xóa tuyển chọn dưới
đây tường minh không được pilot cục bộ hoàn thành.

Triển khai routing tenant/dataset có xác thực, initialize-trước-tenancy, lượt đọc bảo toàn
provenance và test lần-gọi-đầu/reconnect/đồng thời. Bật ngữ cảnh read-only ban đầu. Bổ sung ingestion
tuyển chọn sau chấp nhận tùy chọn chỉ sau khi xem xét chính sách model và retention; giữ xoá có cổng
owner.

Chấp nhận: hai owner không thể truy vấn, xem trạng thái, ghi hay xoá dataset của nhau; ngữ cảnh cũ
không thể sửa kế hoạch đã phê duyệt; mất memory không che kết quả chính thức. Retry không nhân đôi
ingestion.

### H6D — UI và phần mở rộng có kiểm soát tác động phụ

Trạng thái triển khai (2026-10-13): độ bao phủ chi tiết dùng chung, lịch sử regression
cùng-tiêu-chuẩn, tham chiếu PNG bổ sung được bảo vệ, revision đề xuất do tool tạo chính xác và xem
xét owner tường minh đã triển khai. Cùng một projection Verify cũng hiển thị Memory có phạm vi mang
tính tham vấn. Xem milestones/harness-h6.md. Exploration/performance chỉ là đề xuất planning; không
có executor browser/load hay nhà cung cấp chụp screenshot tự động đáng tin nào được đăng ký. Các
đường đó vẫn bị chặn cho đến khi các điều kiện tiên quyết target/dữ liệu đã xem xét, idempotence,
hủy, dọn dẹp, artifact và route model tồn tại. Phê duyệt hay `role`/`approved_by` của người gọi
không thể kích hoạt chúng.

Mở rộng các bảng dùng chung cho độ bao phủ case chi tiết, screenshot, lịch sử regression và ngữ
cảnh có phạm vi. Thêm exploration như một workflow đề xuất với quyền target/dữ liệu tường minh.
Thêm profile performance có giới hạn chỉ sau khi các kiểm soát phê duyệt/dọn dẹp/hủy tồn tại.

Chấp nhận: cả hai bề mặt hiển thị cùng báo cáo được bảo vệ; phê duyệt owner tách biệt với Submit;
self-healing tạo ra revision test mới thay vì PASS âm thầm; profile rủi ro không thể được gọi với
đối số `approved_by` hay `role` bịa.

### H6E — Template factory Vanguard

Import manifest 41 nhiệm vụ dưới dạng bản nháp có phiên bản và ánh xạ các node được hỗ trợ tới
recipe/profile đã đăng ký thực tế. Preview có thể được thêm sớm hơn mà không thực thi gì. Skill/brief
là dữ liệu soạn thảo, không phải grant quyền. Sửa các đường dẫn SDK/brief đã cũ, sự không khớp phụ
thuộc W3 so với CH2 và phê duyệt dựa trên comment. Thêm ủy quyền trước-publish tường minh trước chữ
ký hậu-release hiện có.

Ánh xạ các thực thi mutation/performance của W4 là Verify bất kể label Review của nó. Quét tĩnh của
W5 không phải xác thực runtime nếu ứng dụng chưa từng chạy. Linter Java/Spring đã hoạch định vẫn là
sản phẩm tương lai; hiện nó không bao phủ backend Python của ADLC.

Chấp nhận: import là tất định, owner có thể xem xét/chấp nhận nó, các năng lực không hỗ trợ vẫn bị
chặn, và một pilot ba node (candidate -> Verify -> cổng con người) hoàn thành trước chiến dịch đầy
đủ. Feedback tạo kế hoạch/contract kế nhiệm, không phải sửa các tiêu chuẩn đang chạy đã chấp nhận.
Hành động release/Git vẫn là profile được ủy quyền riêng.

### H6F — Chiến dịch ký duyệt live và phục hồi

Xác minh khả năng truy cập dịch vụ, xác thực và tương thích phụ thuộc runtime trước. Chạy các case
PASS/FAIL kiểm soát, giao trùng, phản hồi mất, broker restart, ADLC/Harness restart, hủy, bằng chứng
hết hạn và cross-owner. Xác thực hành vi callback/Submit có chữ ký và lịch sử UI bền. Tài liệu hóa
kích hoạt và quy trình rollback chỉ cho các hàng/profile opt-in mới; không xoá bằng chứng đã lưu
trữ hay viết lại lock cũ.

Mọi test dựa trên model phải tôn trọng giới hạn `my-codex / cx/gpt-5.6-luna` hiện có. TestForge
exploration/self-healing và Cognee synthesis/ingestion có thể gọi các model cấu hình phía backend
mà các client này không chọn. Kiểm toán/pin các route đó trước khi gọi; nếu một model backend bắt
buộc không thể tuân thủ, giữ đường đó tắt và xin quyết định riêng. Không có lời gọi model trả phí
nào được thực hiện cho lần tải này.

## 8. Cấu hình và điều kiện tiên quyết còn thiếu

| Năng lực | Cấu hình thượng nguồn | Quyết định deployment bắt buộc |
| --- | --- | --- |
| Sandbox | `VAI_SANDBOX_BROKER_URL`, `VAI_SANDBOX_TOKEN`; `VAI_GIT_TOKEN` riêng chỉ cho các hành động Git được ủy quyền | Broker truy cập được; credential có phạm vi; isolation/image digest; chuyển nguồn và VFS thuộc lần chạy; đối chiếu idempotency/thao tác |
| TestForge | `TESTFORGE_BROKER_URL`, `TESTFORGE_BROKER_TOKEN`; tham chiếu credential tài khoản staging được phép | Mã nguồn Windows runner/backend và schema API; kết nối target; kết quả/bằng chứng có kiểu; API chuyển tệp, idempotency và hủy |
| Memory | `AGENT_MEMORY_MCP_URL`, `AGENT_MEMORY_TENANT_ID` ở thượng nguồn; vẫn cần phân giải credential có xác thực | Revision backend Cognee/MCP; tenancy/xác thực được thực thi; dataset đã phê duyệt; chính sách model/retention/xóa |

Các mặc định riêng `10.0.10.195` và fallback Sandbox công khai là mô tả về các deployment thượng
nguồn, không phải bằng chứng rằng máy này hay container Harness truy cập được chúng. Cấu hình
endpoint an toàn truy cập được; dùng HTTPS hay một mạng được bảo vệ đã xem xét tường minh, không
phải bearer token qua một kết nối HTTP công khai tùy ý. Không thay đổi cài đặt firewall/VPN hay
suy ra ánh xạ subnet tự động.

Các nguồn đã tải không bao gồm ba deployment backend. Chúng tôi chưa xác minh health, tương thích
API, ủy quyền, cô lập sandbox hay routing model của chúng. Truy cập contract/mã nguồn backend là
điều kiện tiên quyết để tuyên bố hệ thống hoàn chỉnh; sao chép các wrapper vào patch.yml là không
đủ.

Định nghĩa hoàn thành: một owner phê duyệt contract và kế hoạch xác minh cố định; candidate chính
xác chạy trong môi trường đã phê duyệt; assertion và bằng chứng thật quyết định phán quyết; cả hai
giao diện hiển thị cùng kết quả được giữ; submission tường minh trao kết quả có chữ ký đã chấp nhận
cho ADLC; memory tùy chọn có phạm vi và mang tính tham vấn; các test restart/hủy/retry và quyền pass
mà không có tác động phụ trùng lặp. Shipping vẫn là một hành động được ủy quyền độc lập.

## Nguồn tổng hợp

Tài liệu này được dịch và biên tập từ các file sau (lưu trữ trên nhánh git `agentHarness`, đọc bằng
`git show agentHarness:docs/<file>`):

- `docs/harness-vanguard-plugin-integration-plan.md` — Vanguard: Sandbox, TestForge and Agent
  Memory integration plan (phạm vi, kiến trúc plugin, các phận sự, checklist triển khai H6A–H6F).

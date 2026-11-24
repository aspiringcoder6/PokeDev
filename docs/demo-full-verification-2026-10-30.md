# Kiểm chứng toàn luồng vAIPlatform — đang thực hiện

Người dùng yêu cầu thử lại từ đầu tới cuối sau khi sửa Confluence, cho phép
đổi sang model khác đã có trong Harness nếu Netmind/GLM bị giới hạn.
Chưa xác nhận demo toàn luồng đạt. Lượt mới đã duyệt tài liệu #32 và đang
lập kế hoạch; chưa chạy task sửa BE trong lượt này.

## Model và dịch vụ

- Đã khởi động lại app local với đúng `.env.remote`, database và khóa cũ.
- Catalog thật lấy bằng RPC `session/modelCatalog` (không phải `model/list`).
  DeepSeek official được liệt kê nhưng probe báo MISSING_CREDENTIAL.
- Probe `netmind / MiniMax/MiniMax-M3` trả đúng marker, hoàn tất trong 12,6s.
- Đổi model mặc định local và Factory sang MiniMax-M3. Gitea
  `admin/factory-wilson` commit `eed6af458c6b493fdb8d628b368b30b28b97ca7c`,
  hot reload đúng commit; giữ mọi scalar khác. Không đổi credential/VPN.
  Helper `deploy/use_harness_model.py` mặc định audit. Không chạy lại apply
  nếu chưa đối soát runtime/source; pointer Factory có thể chứa credential,
  không in raw pointer hoặc URL có userinfo.
- Session Spec `session-d22dee36-e6af-46c1-a018-0c06d2802c85` thực tế xác nhận
  provider Netmind/model MiniMax-M3, context 1M.

## Những thay đổi local đã kiểm thử

- Tài liệu Confluence mới có 20.045 ký tự trước metadata. Nâng giới hạn
  requirement native từ 20.000 lên 80.000, dùng chung trong `CreateDelivery`
  và intake, giữ nguyên toàn bộ nội dung đã duyệt. Parser page vẫn giới hạn
  60.000 và instructions 16.000; không cắt để lọt giới hạn.
- Sửa sơ đồ thực thi: giữ đo kích thước/vị trí đã kéo, giữ node object khi
  payload poll tương đương, ổn định edges và chặn feedback chọn task trước
  khi URL/parent nhận thay đổi. Browser đã thấy React #185 với `setNodes`
  ở bản cũ; cần kiểm chứng lại bản build mới bằng browser.
- **32 kiểm thử UI đạt** (3 suite: graph, model, intake), gồm regression
  parent render loop và giữ vị trí khi poll/state thay đổi.
- Thêm kiểm tra trang nguồn còn xuất bản: MCP get-by-ID có thể vẫn trả body
  của trang bị xóa; kiểm tra thêm `confluence_search id=... AND type=page`
  khi không có status. Trang không có bằng chứng current bị chặn duyệt,
  thu hồi approval nhưng giữ cache đọc, khôi phục phải duyệt lại.
- **75 kiểm thử backend đạt**, 2 warnings; xem
  `adlc-flow/data/slack-actions-check/full-demo-current-page-tests.log`.
  Pytest dùng `-p no:cacheprovider -o addopts=` và basetemp unique trong
  thư mục bằng chứng; `.pytest_cache/v` có ACL lỗi, không dùng cache-clear.
- Build giao diện input limit đã đạt; build graph đã đạt (2m38s).
  Build UI guard đã đạt (`full-demo-final-ui-build.log`) và backend đã
  restart trước lượt #32. Đừng restart khi có `project_worker.py` đang chạy.

## Nguồn tài liệu và Slack hiện tại

- #22/run `97d8b6e8-3b51-5b43-85ac-7333ad6fb17a`: FAILED planning,
  LIVE_DAG_INCOMPLETE, có 3 tài liệu BA nhưng chưa có task plan.
- #29/page `4980813`, v3, run
  `2666054d-6888-5f08-98f6-0803c479761c`: FAILED planning tương tự, source
  CHANGED vì v3 thay v2. Main BE vẫn commit import `4a5e41b1e9d580c3b2a7fb9415c912c128fe6fe1`.
- Tài liệu #29 đủ 6 phần nhưng year đang chỉ là nhãn kỳ báo cáo, trái quyết
  định trước của người dùng rằng year lọc năm joinDate. Không duyệt v3 đó.
- Đã bật Slack và gửi góp ý **bằng UI thật** ở #29:
  request `d603cdd4-540b-43e7-b324-04e5118c134b`, invocation
  `ag-070239-4da970`, session `session-d22dee36-e6af-46c1-a018-0c06d2802c85`.
  Sau đó cancel đúng session này (accepted=true) khi browser thấy source ở
  Trash. Biên nhận ở `cancel-trashed-page-revision.json`. Không gửi lại.
- CUA đã hoạt động trở lại. Từng thấy page4980813 và report5144613 ở Trash,
  mở link báo Page Not Found; sau đó reload + connector/search xác nhận
  page4980813 current/mở được. Trạng thái nguồn đang thay đổi; không suy ra
  dữ liệu vẫn bị xóa chỉ từ snapshot cũ. Không tự phục hồi/xóa trang nào.
- Trong khi kiểm tra, Thu (BA) đã gửi yêu cầu Slack mới lúc 14:07:45:
  channel `C0CD66L5D4L`, thread `1793344065.240609`, lifecycle dự kiến
  `lc-6L5D4L-4065240609` (phải xác minh từ catalog thực tế).
  https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793344065240609
- Bot chạy `ag-070817-73800b`, nhưng trả lại link trang cũ4980813, nội dung
  year là nhãn. Vì vậy đã phản hồi trong chính thread mới này, dưới tài
  khoản Hieu Le, mention bot thật; yêu cầu tạo trang MỚI, year lọc joinDate,
  đủ API/test/quyền, giữ schema, chưa chạy code/merge/deploy. Tin thật lúc
  14:15:51: `1793344551.096009`.
- Bot đã nhận và chạy **`ag-071630-6c311b`** lúc 14:16:36. Chờ kết quả này,
  không gửi thêm yêu cầu trùng. Đây là nguồn ưu tiên cho lượt kiểm chứng
  đầy đủ, trước khi tạo native run mới. Yêu cầu người dùng không phải chép
  link thủ công: đọc catalog Workloop để thấy source/page mới tự xuất hiện.

## Các bước tiếp theo

1. Đối soát ag-071630-6c311b, trang mới phải current, đúng year/joinDate và
   lifecycle/thread mới. Đọc lại và kiểm tra link thật bằng browser/connector.
2. Hoàn tất build UI guard, restart backend khi không có native worker;
   giữ model MiniMax-M3 đã lưu, DB/key/token. Xem UI graph trực tiếp bản mới.
3. Trên tài liệu mới: bật Slack, share progress, lưu channel→project rule
   có notifications; gắn BE `a22e1770-c121-4327-a057-088205b10605`, duyệt
   digest/version thật trên UI. Chưa tạo run mới khi source chưa đúng.
4. Bắt đầu native plan, xem BA docs + DAG, duyệt kế hoạch/task thực tế,
   chạy qua engine và kiểm tra HITL, bằng chứng unit/API test/diff/PR/Slack.
5. Không tự viết sẵn feature BE thay agent và không merge feature vào main
   (giữ baseline để người dùng tự quay lượt tiếp theo).

Lưu ý BE: profile revision6 Java21/Maven/Mockito javaagent. Bộ test gốc
63 tests có 5 failures, 0 errors; không được nói toàn bộ BE đã xanh.
Preview API với DB/auth thật chưa được cấu hình. Cần quyết định kiểm chứng
đúng phạm vi tính năng và ghi rõ failures gốc, không bỏ/sửa tests để báo xanh.

## Cập nhật lúc 15:28 ngày 30/10

- Người dùng chốt kiểm thử riêng tính năng mới, ghi rõ 5 lỗi gốc, không mở
  rộng sửa baseline. Profile đã lưu revision7, digest
  `a2cee2ef957a521216378a463cc043c4ffdeccfed8ece56ff814d62c27de8283`.
  Selector `*YouthUnion*Stats*Test`, `failIfNoTests=true`, Java21/Mockito.
  Helper `deploy/configure_military_youth_feature_verification.py` dùng
  API bình thường; base chỉ gửi repository_id/commit (không gửi readonly repository).
- Bot mới `ag-071630-6c311b` hoàn tất, tạo page5079126 v1 (20.604 ký tự),
  tự xuất hiện thành native #32 và tự gắn BE project. Đúng joinDate/year,
  đủ 6 phần. Source guard current-page đã đọc thành công.
- Lượt native **`0dd61306-3f13-54eb-ad4d-10fe4eba532d`**, khởi tạo
  15:24:35, base BE `4a5e41b1e9d580c3b2a7fb9415c912c128fe6fe1`,
  frozen environment7, model netmind/MiniMax-M3, source32/page5079126v1.
  Native approve200/plan202 qua helper có durable command; browser đã xác
  nhận Đã duyệt và Mở lượt chạy. P01 đang chạy trong session
  `session-6bb87bf8-7445-44c3-a573-3a21491e320f`; P02 chờ.
- Slack báo lập kế hoạch SENT, report Confluence SYNCED. Link notice:
  https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793348683729399?thread_ts=1793344065.240609&cid=C0CD66L5D4L
- **Đã tái hiện lỗi chọn task vẫn còn trên build mới**: mở run2666054d,
  chọn P02 làm URL quay P01 và React185. Guard cũ chưa đủ; đang bổ sung
  regression thật cho controlled selection rồi sửa phản hồi onSelectionChange.
  Không được kết luận hết lỗi cho đến khi kiểm tra trực tiếp lại bằng browser.
- CUA có lúc `browser.user is unavailable`; reset REPL rồi getState/getTab
  cùng browser2 đã khôi phục. Không cần user đăng nhập lại. Tab2 lượt mới,
  tab4 tạm tái hiện graph; không đóng tab2. Có thể reset chỉ khi lỗi tái diễn.
- Startup source_files đang gọi git riêng từng file nên khoảng 2 phút mới
  xuất hiện P01/P02; cần phân biệt startup chậm với run bị treo. Không hủy
  worker mới. `deploy/watch_native_demo.py` audit-only đọc/snapshot run,
  stdout bỏ script dài và nội dung source, không in prompt/credentials.

## Cập nhật lúc 15:59 ngày 30/10

- Lỗi React185 **đã tái hiện và sửa thêm đúng nguyên nhân**: callback
  `onSelectionChange` phát lựa chọn cũ trong khi parent cập nhật lựa chọn
  mới. Bỏ vòng phản hồi đó; nhận selection từ `onNodesChange` và click,
  vẫn giữ keyboard/list selection và node dimensions/drag positions.
- 9/9 kiểm thử execution graph + workflow canvas đạt, regression mô phỏng
  việc chọn task khác với parent nhận lại controlled selection. Build
  `task-selection-frontend-build.log` đạt, App `App-Y9ykHRQk.js` (đối soát
  tên chính xác trong log nếu cần). Browser đã thử P01↔P02 ở graph, list
  và trong lượt đang poll; không crash và URL/chi tiết đổi đúng task.
- IAB đã reset REPL một lần để hết `browser.user is unavailable`; binding
  hiện tại vaiTab(tab2,lượt mới), graphTestTab(tab4,tạm). Browser viewport
  capability không làm thay đổi vùng capture hẹp; đã reset override. Ảnh
  hẹp lưu `task-selection-fixed-live.jpg`, không dùng làm bằng chứng layout
  desktop đầy đủ. Thử native Chrome đọc AX được nhưng input geometry lỗi,
  screenshot lại trả cửa sổ Codex khác; **không tiếp tục native input**,
  không thao tác Google Docs hay Codex UI. Dùng CUA browser DOM cho flow.
- BA P01 hoàn tất lúc **15:46:21**, 3 tài liệu SPEC8547 / DESIGN7045 /
  TESTS7502 ký tự. Planner P02 session
  `session-4d66d690-40a4-483a-89dd-8d3a76a849e1` đang xử lý.
- Netmind thực tế bị RATE_LIMIT token800k theo phút. Probe Hung GPT6Luna1m
  thất bại SERVER; probe **codevquan / MiniMax-M3 thành công 5,3s**.
  Đã chọn model qua RPC công khai cho đúng session P01 rồi P02, không đổi
  prompt/workspace/contract hoặc credential. Requested route trong frozen
  run vẫn netmind; operator session overrides được ghi riêng, không nói
  model_route đã tự đổi. Biên nhận P01 `native-demo-P01-model-switch.json`,
  P02 `native-model-override-0dd61306-3f13-54eb-ad4d-10fe4eba532d-P02.json`.
  Helper `deploy/switch_native_demo_model.py` audit mặc định; apply chỉ cho
  session RUNNING thuộc run đã auth và route đã có successful probe.
- Sau lỗi model, P02 có lúc native session idle nhưng contract vẫn
  IN_PROGRESS và UI vẫn RUNNING. Đã đối soát và gửi **một** continuation
  trong cùng session/contract (accepted=true lúc15:55:51), kèm ràng buộc
  commands500chars/timeout5–600, test selector và no preview. Không tạo
  task mới, không replay prompt gốc, không tự viết feature.
  Biên nhận `native-demo-P02-resume-after-model-switch.json`. Không gửi
  lại một cách mù quáng. `native-demo-P02-format-guidance.json` không được
  tạo vì phép thử trước đó thấy session_idle và không gửi.
- Phát hiện thêm lỗi source context: giới hạn1,2MB tiêu hết ở domain nên
  thiếu YouthUnionService/Resource, đồng thời bỏ `.properties`; agent
  không có baseline các file được sửa, sau đó sẽ bị SOURCE_CONTEXT_MISSING.
  Đã thêm `source_files(required_paths=...)`, ưu tiên toàn bộ file trong
  plan (và selected workflow), giữ nguyên tree/budget/secret exclusions,
  hỗ trợ .properties và fail rõ nếu file đã có không đọc nguyên vẹn được.
  Worker execution mới sẽ nạp module mới từ đĩa; worker planning đang chạy
  giữ module cũ, không restart/cancel nó.
- Preflight với BE thật đã xác nhận đủ Service/Resource/Repository/
  Permission/i18n, context1199973bytes, tree774, selected316; SHA lưu ở
  `required-source-real-be.json`.
- Đã sửa thứ tự chuẩn hóa plan: dùng `apply_environment(result, frozen)`
  rồi validate kế hoạch cuối, thay vì chặn commands do Planner đề xuất
  trước khi thay bằng commands môi trường đã duyệt. Không môi trường vẫn
  validate đầy đủ; task paths/dependencies không được nới. Prompt tương lai
  cũng ghi giới hạn argv/timeout. Worker planning hiện tại chưa nạp sửa
  này; continuation đã nhắc định dạng tránh lỗi cũ.
- **30 kiểm thử source context / environment / workflow đạt**,
  `planning-source-tests.log`. Không cần build UI lại vì các sửa mới chỉ
  Python worker/module. Backend app chưa restart để không hủy worker hiện
  tại; lần spawn execution đọc worker mới. Sau khi không còn worker phải
  restart nạp Python API modules trước lượt demo người dùng.

## Cập nhật 16:44 — đã có code thật, đang thử lại sau lỗi nền tảng

- P02 hoàn tất, native plan sẵn sàng khoảng16:00. Đã review và chỉnh
  **bằng canvas web thật**, JSON nâng cao: gộp thành DEV, TEST_SERVICE,
  TEST_API, REVIEW; 2 Tester phụ thuộc DEV rồi chạy song song, runner
  chèn SYS_VERIFY trước REVIEW và SYS_HANDOVER sau cùng.
- Workflow **`07843ab8-c766-42fb-b153-2ae7f976358a` v1**,
  tên `Military Youth BE · Developer → Test song song → Review`.
  Đã bấm Lưu và Áp dụng vào kế hoạch thành công. Bản JSON ở
  `reviewed-workflow-draft.json`. Digest plan **`ca38966cbd55971a0f9b5a1173ddc5786b11db7615bbb3f024f0e0a23904c541`**.
  Tester service được giao thêm YouthUnionStatsRepositoryTest chạy query
  thật bằng H2 test-only, không mock để nhận đã phủ joinDate. DEV được
  phép sửa pom.xml để thêm H2 scope test. Không đổi schema/FE/test gốc.
- Backend có ExecuteCommand.model_route và RetryCommand.model_route
  optional, xác minh route trong catalog trước dispatch. Lưu route chọn
  cho phase execution, giữ planning_model_route, không cho đổi route bằng
  replay/inflight. Atomic state/owner/approval checks giữ nguyên.
- Probe Codevquan MiniMax thành công; đổi default Factory và .env.remote
  sang `codevquan / MiniMax/MiniMax-M3`, Factory commit
  **`b87e0c54abfcfeebb193f4a3a066eb84e41e6814`**, hot reload xác nhận.
  Đã restart app an toàn lúc không có worker trước thực thi.
- Duyệt native execute qua API chuẩn với exact digest + route codevquan,
  HTTP202. Helper `deploy/execute_native_demo.py` audit mặc định, durable
  intent `native-execution-intent-0dd61306-3f13-54eb-ad4d-10fe4eba532d.json`.
- **DEV đã DONE, code được apply vào candidate thật**, session
  `session-a0b243d1-5560-4d5e-a8c1-d1dc3b5cd41d`.
  Artifact SHA **47da2dae9531fc9a82d344391f98a35888117e4151dba5f69815d0d7006c1882**,
  6 files: projection, DTO, YouthRepository, YouthUnionService,
  YouthUnionResource, i18n. Không có pom.xml dù được phép/được yêu cầu H2.
  Chưa gọi đây là kết quả đã kiểm chứng; chưa có test/build/PR.
- Review thực tế thấy **endpoint hiện SAI prefix**: class Resource có
  `@RequestMapping("/api/military-youth/youth-unions")`, method mới ghi
  `@GetMapping("/api/v1/youth-union-stats")`. URL bị nối, test phải giữ
  đúng /api/v1, không sửa kỳ vọng để xanh. Query/service cơ bản đúng theo
  diff. YouthUnionRepository có findAllByIdIn(Collection), nên overload
  dùng được; PermissionService trả List<String> đúng. Cần runner bắt lỗi
  URL và H2 dependency, agent sửa code, không tự viết feature thay agent.
  Nếu cần tạo controller riêng thì hiện grant DEV chưa có file mới đó;
  **không sửa manifest/DB để lén nới scope**. Có thể cần luồng sửa kế hoạch
  rồi thử lại sau khi lỗi thực tế xác nhận. Chưa triển khai amendment.
- TEST_SERVICE và TEST_API đã bắt đầu song song, nhưng cả hai FAILED
  **do WinError5 rename result.tmp→result.json**, không phải test fail.
  Root run **0dd61306… hiện FAILED/LIVE_DAG_INCOMPLETE**.
  Job DB `execution/workloop.sqlite3` jobs.error xác nhận chính xác path
  rename; worker.log chỉ có generic DAG error. Hai session:
  `session-d97be155-391a-48cd-9376-ae3b6fac4648` và
  `session-1a0a4078-39bb-4aad-a693-f41a1f125283`.
- Đã thêm `atomic_data.py`: unique temp, fsync, serialized writer,
  bounded retry PermissionError của rename/read. Worker snapshot và
  WorkerCheckpoint đều dùng. Reader LiveService.observe cũng dùng read
  retry để không tạo UNCONFIRMED giả trong lúc replace. Hết retry raise
  SnapshotBusyError recoverable (không lặp agent/job). Test cạnh tranh
  thực tế trên Windows đã tái hiện reader PermissionError, sau đó sửa.
  **45 tests atomic/recovery/live/model/source đạt**, file
  `atomic-read-write-tests.log`. Không nhận 5 lỗi BE gốc đã sửa.
- Native input packaging mới `native_source_context.py`: file plaintext
  nguyên vẹn + source-index.json ánh xạ path→input/SHA; chia context MD
  theo byte UTF8 thay vì cắt nội dung; wire budget đo cả ensure_ascii của
  SDK dưới1,45MB, từng input dưới180k. Review chỉ gửi baseline các file
  thay đổi thay vì nhân đôi toàn bộ repo (sẽ vượt bridge1,5MB).
  Giữ nguyên toàn bộ file trong grant; context tham khảo thêm tối đa250k
  wire bytes để giảm token. Tên lớp tham chiếu trong Java được ưu tiên
  đọc sau files trong grant. Reviewer prompt đã đổi sang source-index.
- Lỗi UI thêm đã sửa: Journey không đếm P01/P02 thành task implementation
  đã xong (PLAN_READY hiển thị 0/4 chưa bắt đầu). Reader cũng tiếp tục poll
  PLAN_READY để bắt thao tác bắt đầu từ nơi khác. 17 tests graph+model rồi
  22 model tests đạt; build mới **App-DfSgpjao.js**, `live-reader-build.log`
  đạt1m19s. Không cần build lại vì sửa atomic/model retry chỉ Python.
- Probe **codev2 / zai-org/GLM-5.3-Flash thành công 5s**; các GPT routes
  Hung và Quanhnh80 thất bại SERVER, không dùng. Codevquan M3 vẫn có
  token quota1M/min, nên lượt thử lại sẽ dùng GLM Codev2. Helper
  `deploy/retry_native_demo.py` audit mặc định, --apply chỉ gọi API retry
  đúng run FAILED/approved, lưu UUID child trước POST. **Chưa gọi apply**.
- **VỪA restart app lúc16:44** sau khi xác nhận worker cũ đã dừng, để nạp
  atomic readers + RetryCommand.model_route. Cần chờ /health200 rồi gọi
  retry cho parent0dd61306… với helper. Native retry giữ parent, cùng plan,
  base/profile/source và tái dùng artifact DEV DONE, không sinh code lại.
  Child run_id sẽ nằm trong `native-retry-intent-<parent>.json` sau apply.
- Slack notice RUNNING SENT vào thread gốc, progress Confluence SYNCED
  lúc16:24:56. Source32 vẫn v1/staleFalse. Link notice lúc16:19:
  https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793351978967089?thread_ts=1793344065.240609&cid=C0CD66L5D4L
- Tiếp tục: retry an toàn, xem tester/runner thật, xử lý lỗi test/build
  bằng agent/luồng UI và scope approval hợp lệ; kiểm tra graph chọn task,
  HITL nếu phát sinh, Slack/report, source diff, publish verified branch/PR
  **không merge main**. Main vẫn baseline4a5e… để người dùng tự quay.

Bằng chứng riêng ở `adlc-flow/data/slack-actions-check/`, đặc biệt
`full-demo-source-before.json`, `full-demo-environment-before.json`,
`harness-model-catalog-20261030.json`, `harness-model-change-result.json`.

Browser hiện tại: IAB browser id2. CUA REPL có các binding `vaiTab` (tab2,
request29), `confluenceTab` (tab1,page4980813), `slackTab` (tab3, thread mới).
Chỉ dùng CUA APIs cho UI; không dùng CDP/Playwright ngoài tool. Browser docs
đã đọc đầy đủ. Cần save screenshot và embed proof khi hoàn thành thao tác.

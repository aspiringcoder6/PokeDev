# Reset để kiểm chứng lại demo Military Youth

Yêu cầu ngày 29/10/2026: dọn tài liệu và lịch sử tính năng thống kê trong
`admin/tcct-be-military-youth`, thử lại hành trình sản phẩm trước khi người
dùng tự quay. Người dùng cho phép thao tác trình duyệt. Chỉ kiểm tra desktop.

## Những thay đổi đã áp dụng và xác minh

- `main` từ `8300bb5024cd4f89563989cf4d3e32b4427fe7fa` trở về
  `4a5e41b1e9d580c3b2a7fb9415c912c128fe6fe1`, bản import ban đầu, còn 1 commit.
  Bảy commit của lần thử thống kê không còn trong lịch sử `main`.
- Đóng PR #11; gỡ hai nhánh thống kê
  `feature/lc-lc-F9SRKP-4062301049-r3` và
  `feature/lc-lc-6L5D4L-7084542699`. Push theo lease của từng ref và cập nhật
  nguyên tử để tránh ghi đè thay đổi đồng thời. Giữ nhánh doanh thu
  `feature/lc-lc-F9SRKP-4590750179` và PR #4 thuộc công việc khác.
- Sao lưu và đưa 6 trang Confluence vào trạng thái `archived`, có thể phục hồi:
  `3014667`, `4718598`, `4096070`, `3866652`, `3801092`, `3866626`.
  Connector hiện có hỗ trợ lưu trữ; không thực hiện xóa vĩnh viễn.
  Trang `4325432` đã không còn ở trạng thái current khi kiểm tra (404).
- Lưu trữ cả 19 tài liệu/yêu cầu cũ trong vAIPlatform. Danh sách đang xử lý
  hiện rỗng. Tài liệu #7 tuy thiếu tiêu đề đã được đối chiếu qua lifecycle,
  xác nhận đúng yêu cầu thống kê của repo này trước khi lưu trữ.
- Dừng đồng bộ báo cáo và thông báo của các yêu cầu cũ. Giữ kết nối bot đã
  lưu để dùng cho lượt mới. Chưa sửa hoặc xóa tin nhắn Slack cũ.
- Thêm **Lưu trữ yêu cầu**, bộ lọc **Đã lưu trữ**, **Khôi phục yêu cầu** trên
  web. Nguồn Workloop đồng bộ lại hoặc phản hồi muộn của lifecycle đã lưu
  trữ không đưa yêu cầu cũ vào hộp đang xử lý. Thread/lifecycle mới vẫn vào
  bình thường. Khôi phục yêu cầu cần xem lại và duyệt lại; không tự bật chia
  sẻ tiến độ/thông báo. Lượt đang chạy hoặc sửa tài liệu chưa đối soát được
  chặn lưu trữ; giữ lịch sử lượt đã hoàn tất.
- Sửa metadata BE trong `factory-wilson/projects.yaml`: `fastapi` →
  `spring-boot`. Commit `d6399d024149f017a4df16cf0fc56cc56efc9e53` đã được
  `factory_sync` nạp đúng SHA. Không đổi provider/model Netmind.

## Bằng chứng và phục hồi

Thư mục riêng, đã đặt `.gitignore` để tránh đưa backup vào Git:

`adlc-flow/data/demo-reset/20261029T143624Z/`

- `repository-before-reset.bundle`: Git bundle đã kiểm tra, chứa refs/source
  trước reset. `repository.git` là mirror dùng để thao tác, không dùng mirror
  này để push toàn bộ refs.
- `git-reset-plan.json`, `git-reset-result.json`, `branches.json`, `pulls.json`:
  mốc trước/sau, nhánh giữ lại và kết quả xác minh từ Gitea.
- `confluence-*.json`, `confluence-archive-*.json`: nội dung, phiên bản và
  biên nhận lưu trữ từng trang.
- `intake-before.sqlite3`, `live-before.sqlite3`, `memory-before.sqlite3`,
  `workloop-before.sqlite3`: bản SQLite nhất quán trước khi dọn. Không ghi
  đè cả database đang chạy để phục hồi một yêu cầu; dùng nút Khôi phục.
- `native-archive-final.json`: không còn yêu cầu đang xử lý, 19 yêu cầu được
  lưu trữ.
- `factory-projects-*.yaml`, `factory-stack-update.json`: backup metadata
  trước thay đổi và commit đã nạp.

`deploy/reset_military_youth_git.py` mặc định chỉ xem kế hoạch; `--apply` chỉ
chấp nhận bộ backup đã kiểm tra, giữ các ref ngoài hai nhánh demo được chỉ
rõ. Không dùng script đó để xóa nhánh của lượt kiểm chứng mới.

## Kiểm thử đã chạy

- 64 kiểm thử backend intake/archive/revision/progress/Slack: đạt.
- 21 kiểm thử frontend intake/integration: đạt.
- Build frontend production: đạt, xuất bản từ staging bằng cách thay index
  cuối cùng; giữ assets cũ cho tab đang mở.
- API thực tế xác nhận 19 yêu cầu đã lưu trữ và không còn yêu cầu đang xử lý.
- Đã bắt đầu kiểm tra môi trường BE trên đúng commit import ban đầu, không
  gọi model: check `9adc64e2-eea4-4990-beaa-84b3f23e368a`, project
  `a22e1770-c121-4327-a057-088205b10605`, profile revision 5. Biên nhận nằm ở
  `baseline-after-reset-result.json`; kết quả cuối ở phần dưới.

### Kết quả kiểm tra mã gốc và cấu hình test Java

Check `9adc64e2-eea4-4990-beaa-84b3f23e368a` đã kết thúc `FAILED`:
63 test, 5 failure, 12 error. Năm failure có từ mã gốc: 3 kiểm tra trạng thái
DefenseDiplomacy so sánh enum với số; YouthUnionMapper không bảo toàn
`createdBy`; TechnicalStructureTest phát hiện phụ thuộc sai tầng. Không bỏ
hoặc sửa kỳ vọng các test này để làm xanh lượt kiểm tra.

12 error còn lại do Mockito tự attach Java agent không được trong gVisor,
không phải do tính năng thống kê. Đã đối chiếu báo cáo Surefire thật trong
chính môi trường kiểm tra, lưu `baseline-surefire-diagnosis.json` và
`baseline-mockito-root-cause.json` trong thư mục backup.

`deploy/prepare_be_project.py` đã cập nhật: Maven giải quyết đúng phiên bản
`mockito-core` của project, xác minh manifest hỗ trợ `PremainAttach`, rồi
khởi động test với `-javaagent` ngay từ đầu. Giữ nguyên inline mocking,
không chèn MockMaker thay thế, không sửa source BE hoặc xóa test. Cách khởi
động này theo [tài liệu Mockito](https://javadoc.io/static/org.mockito/mockito-core/5.21.0/org.mockito/org/mockito/Mockito.html#mockito-instrumentation)
và dùng [Maven dependency:build-classpath](https://maven.apache.org/plugins/maven-dependency-plugin/build-classpath-mojo.html)
để tránh chọn sai phiên bản từ cache.

Profile mới revision 6, digest
`dc706d69392fb89c38a032535ca682fc2c8c322334c2860eff4ef8c81a7e99e1`,
check `62c61e1c-dda6-4425-9c5b-f342dd5f836f`, vẫn trên source gốc
`4a5e41b1e9d580c3b2a7fb9415c912c128fe6fe1`.
Biên nhận mới: `baseline-instrumented-result.json`. Kết quả cuối `FAILED`:
63 test, 5 failure, **0 error**. Setup/giải quyết agent đạt; 12 lỗi Mockito
đã hết. Năm failure mã gốc còn nguyên, chưa thể gọi toàn bộ BE là đạt test.

Sau khi thêm archive, bổ sung kiểm tra quyền cho danh sách quy tắc channel
độc lập với số tài liệu đang hiện, để quy tắc vẫn quản lý được khi hộp yêu
cầu đã trống. Quy tắc của project không có quyền vẫn bị ẩn. Lượt kiểm tra
intake/archive mới: 24 test đạt, bao gồm 2 trường hợp quyền mới; các suite
revision/progress/Slack trước đó vẫn có biên nhận 64 test đạt trước chỉnh
sửa này. Backend đã được khởi động lại và `/health` trả 200, đăng nhập API
đạt, active inbox 0, không stale. Route mới đã được nạp. Khi mở lại Codex,
đã quan sát app local dừng dù dùng launcher WMI; chưa khẳng định launcher
sẽ luôn sống qua việc thoát Codex. `deploy/start.ps1` khởi động lại được
với đúng cấu hình/DB/token cũ.

### Lượt Slack mới sau khi phục hồi browser

Công cụ browser đã khởi tạo thành công sau khi mở lại Codex. Slack vẫn
đăng nhập đúng workspace ADLC Factory và người dùng Hieu Le (Tech Lead).
Đã gửi đúng **một** yêu cầu mới bằng giao diện Slack trong
`#tcct-be-military-youth`, có mention bot thật, phạm vi BE/schema không đổi,
year bắt buộc và theo joinDate. Tin đã được máy chủ Slack xác nhận, bot
đã thả reaction; chưa coi reaction là bằng chứng tài liệu đã tạo xong.

- Thread nguồn: `1793288792.857159`
- Channel: `C0CD66L5D4L`
- [Mở thread mới](https://adlcfactory.slack.com/archives/C0CD66L5D4L/p1793288792857159)
- Không gửi lại yêu cầu này nếu bot đang chạy. Chờ và kiểm tra chính thread
  và lifecycle mới, không tái dùng tài liệu/lượt của 19 nguồn đã lưu trữ.

### Kiểm chứng tiếp bằng browser và sửa lỗi được phát hiện

- Đã chuyển tiếp cả 6 trang cũ từ archive sang **Trash** bằng UI Confluence,
  đúng yêu cầu xóa. Xác minh từng ID có link Restore trong trang Trash.
  Không bấm Purge/Purge All. Các mục trash khác không thay đổi. Bằng chứng:
  `confluence-trash-proof.json` và `confluence-trash-proof.png` trong backup.
  Trang cũ `4325432` được xác nhận đã ở Trash từ trước.
- UI vAIPlatform đã được kiểm tra: active inbox rỗng; filter Đã lưu trữ có
  đủ 19 mục; đọc được nội dung cached và thấy nút Khôi phục. Ảnh:
  `inbox-cleared.png`, `archived-request-ui.png`.
- Lifecycle mới `lc-6L5D4L-8792857159`. Invocation đầu
  `ag-154738-4dfcb0` thất bại `missing_confluence_link`; phiên Spec thực tế
  `session-a4771ca2-afca-4b0a-8098-c304ae7f3448` gặp quota 429 và sau đó
  max-tokens. Không coi text trung gian là đã tạo tài liệu.
- Bot đã tự retry invocation `ag-155224-0b2425`, Spec session
  `session-52537eb5-59e7-4019-a447-33b441ccfff2`. Đã tạo trang **4718649**,
  nhưng gặp HTTP 502 khi gửi bản đầy đủ. Trang hiện được cập nhật từng phần,
  chưa được duyệt. Không ghi đè bằng connector khi agent còn chạy. Đừng tạo
  lại một yêu cầu Slack khác cho cùng lượt này.
- Đã thêm quy tắc soạn gọn, đúng nguồn hiện tại và không xuất bản trang đệm/
  nửa bản nháp vào `factory-wilson/agents/spec.md`. Commit
  `97794e48c719b9c2314d229c40d1a48d496fc8ce` đã hot reload, SHA/runtime
  và persona xác minh khớp. Không thay model Netmind, template hay nội dung
  yêu cầu. Persona của invocation đang chạy không được giả định đã thay đổi;
  quy tắc mới áp dụng lần dispatch sau. Script:
  `deploy/refine_spec_writer.py` (mặc định audit, `--apply` mới sửa), backup
  `factory-spec-before-refinement.json` và biên nhận tương ứng.
- Workloop ghi cả invocation Spec thất bại vào catalog với page/link rỗng
  (đã thấy source #20 và #21). Đã sửa native inbox để các dòng audit chưa có
  trang không bị tính thành tài liệu cần chọn project/duyệt. Vẫn giữ trong
  store; nếu nguồn được bổ sung page thật thì tự hiện, không cần nhập link
  bằng tay. Không gán link dựa trên tiêu đề hay lifecycle tương tự.
- Lượt kiểm thử backend cuối: **67 passed**, 3 warning cấu hình/cache pytest
  có từ trước, log `data/slack-actions-check/reset-final-backend-tests.log`.
  Backend đã được khởi động lại để nạp thay đổi inbox này; cần kiểm tra health
  và inbox sau startup.

## Việc tiếp tục trước khi bàn giao quay

Chưa tuyên bố đã nghiệm thu trọn luồng sau reset.

1. Lỗi browser trước khi mở lại Codex: `failed to write
   kernel assets` (Windows path not found). Reset kernel không khắc phục.
   Atlassian connector đã kết nối và dùng được để thao tác Confluence.
   Browser hiện đã phục hồi và gửi được yêu cầu bằng tài khoản người dùng,
   không dùng tin nhắn do bot tự gửi để giả làm đầu vào người dùng.
2. Theo dõi thread Slack mới ở trên, đã @mention bot.
   Nội dung: thống kê đoàn viên đang hoạt động/đã rời theo đơn vị có quyền xem;
   `year` lọc năm của `joinDate`, giữ schema; `year` bắt buộc, thiếu/sai trả
   400; chỉ BE API/unit test, không sửa frontend. Stack BE là Java/Spring Boot.
3. Chờ tài liệu mới tự vào vAIPlatform, gắn project BE, đọc/duyệt tài liệu,
   lập kế hoạch, duyệt task rồi chạy. Thử một góp ý web → bot trên tài liệu
   mới và đối chiếu phiên bản Confluence thật. Giữ đúng lifecycle/thread.
4. Theo dõi sơ đồ task, một điểm cần người phản hồi, test/diff, PR và thông
   báo Slack thật. API preview với database/quyền thật vẫn cần kiểm chứng.
   Lỗi baseline cũ không được bỏ test hoặc đổi trạng thái để báo xanh.
5. Bàn giao lượt thử qua nhánh/PR thử, giữ `main` trước tính năng để người
   dùng có thể quay lượt mới. Chỉ công bố sẵn sàng quay sau khi có kết quả
   thật cho các bước trên.

Web local được chạy lại bằng `deploy/start.ps1`; nếu mất listener sau một
lần thoát Codex, kiểm tra tiến trình và dùng launcher này, giữ nguyên cấu
hình và dữ liệu đã lưu.

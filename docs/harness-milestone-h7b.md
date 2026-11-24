# H7B — Không gian làm việc chung và phê duyệt theo trách nhiệm

Cập nhật: 18/10/2026. Trạng thái: **đã triển khai trong source, chưa kích hoạt
trên database đang dùng**. Kế hoạch tổng: [Team Collaboration & Access Control](adlc-team-roles-plan.md).
Nền tảng quyền: [H7A](harness-milestone-h7a.md).

## Kết quả và giới hạn

Team có thể cùng soạn contract, tạo workflow, compile kế hoạch bằng compiler
ADLC hiện có, duyệt đúng người/đúng phiên bản và chuẩn bị cùng một `WorkflowRun`.
UI không tạo hệ thống task hoặc trạng thái thực thi thứ hai.

| Phần | H7B đã có |
| --- | --- |
| Project | Scope SQL bền vững, quyền theo membership hiện tại, lọc trước phân trang |
| Requirement/contract | Sáu công cụ Skilltree, revision bất biến, gửi duyệt và yêu cầu chỉnh sửa |
| Workflow/plan | `WorkflowDefinition`, `Flow`, compiler và archive `ExecutionPlan` hiện có |
| Run Detail | Cùng ID run, task và timeline coordinator cho người được cấp quyền |
| Quyết định | Actor thật, trách nhiệm độc lập, revision/digest/policy/dependency và thời hạn |
| Suite/candidate/Verify | Suite khai báo được khóa; giữ candidate và bằng chứng lịch sử bất biến |
| Lịch sử private | Preview manifest và chia sẻ có chọn lọc; không tự suy project từ folder hiện tại |

**Chuẩn bị run không phải khởi chạy:** run ở `CREATED`, task ở `PENDING`,
`execution_enabled=false`. H7B không gọi model, sandbox, memory, Verify worker,
webhook hoặc GitHub. Scheduler/recovery và API owner-only không được dispatch
run đã gắn project. Quyền agent, broker, duyệt publication và merge/push thuộc
H7C, kể cả khi Admin đã chuẩn bị grant trong ma trận.

## Triển khai trước khi dùng UI

1. Chọn cửa sổ bảo trì, dừng các process cùng dùng database và sao lưu. Giữ lại
   cả các kho contract, artifact và Verify nếu cần chia sẻ lịch sử.
2. Triển khai đồng bộ source backend/frontend và áp dụng migration tới
   `h7b3c4d5e6f7` (bản sửa naming, sau `h7b2c3d4e5f6` và `h7a1b2c3d4e5`),
   bằng cơ chế migration của backend.
   Không `stamp` để bỏ qua migration.
3. Migration H7B ban đầu (`h7b2c3d4e5f6`) chỉ thêm bốn store rỗng: `adlc_project_resource`,
   `adlc_project_revision`, `adlc_project_decision`, `adlc_project_command`.
   Không cấp role, không đổi mode project, không chuyển dữ liệu private.
   Schema tạo sẵn chỉ được nhận nếu còn rỗng và đúng cấu trúc đã đóng băng;
   mọi table được kiểm tra trước khi tạo table còn thiếu. Bản sửa tiếp theo
   `h7b3c4d5e6f7` chỉ chuẩn hóa tên constraint, cho cả store đã có dữ liệu.
4. Authorization provider phải hỗ trợ `TEAM_POLICY_VERSION=0.1` và
   `COLLABORATION_PROTOCOL_VERSION=0.1`. Provider mặc định đã hỗ trợ; backend
   từ chối provider thay thế không có hợp đồng tương ứng. Bật một cờ AUTHZ
   không thay thế việc enforcement.
5. Đăng nhập ADLC bằng tài khoản cá nhân. API key, auto-login và token của agent
   không được dùng làm danh tính người duyệt.

Không tự chạy migration, reload dịch vụ hay gán quyền cho tài khoản thật trong
lượt triển khai source H7B này. Downgrade tự động bị từ chối để giữ scope và bằng
chứng quyết định; rollback cần phương án bảo toàn dữ liệu/quyền, không xóa table
hay chạy bản cũ không hiểu project cộng tác.

## Luồng sử dụng cho team

### 1. Admin chuẩn bị project và người duyệt

Mở [Thành viên & quyền](http://localhost:3000/team-access/). Operator hiện có tạo
project rỗng; Admin project gán người dùng đã tồn tại vào bốn role theo H7A.

Mở [Không gian nhóm](http://localhost:3000/collaboration/), chọn project rồi bấm
**Thiết lập cộng tác cho project này** và xác nhận. Chỉ project quản trị rỗng,
không có flow hoặc folder con, mới chuyển từ `CONFIGURATION_ONLY` sang
`COLLABORATION`. Không có thao tác bật cộng tác ngầm cho project cũ.

Chuẩn bị ít nhất một người soạn và một người duyệt độc lập cho mỗi cổng cần dùng:

- BA soạn contract; một người khác có `contract:approve` duyệt nghiệp vụ.
- Developer soạn/compile workflow; người khác có `plan:approve` duyệt kỹ thuật.
- Tester soạn suite và người đủ quyền đánh giá bằng chứng Verify.
- Admin quản trị quyền; không mặc định có quyền ký thay BA/Developer/Tester.

Một người có nhiều role hoặc là superuser vẫn không được duyệt tài nguyên mà
mình chịu trách nhiệm soạn. Không có reviewer độc lập hợp lệ thì gửi contract
hoặc compile plan bị từ chối. Admin cần bố trí người/grant phù hợp, không tắt chốt.

### 2. BA soạn và gửi contract

Trong **Soạn yêu cầu**, nhập tên contract và mục tiêu, bấm **Tạo bản nháp bằng
công cụ Skilltree**. Chọn contract, thêm task/node và tiêu chí nghiệm thu bằng
form. API sử dụng sáu công cụ và reducer Skilltree hiện có; client không gửi một
document đã tự đánh dấu approved.

Bấm **Gửi duyệt nghiệp vụ**. Validation ở đây kiểm tra cấu trúc/declaration,
**không phải Verify**. Reviewer mở **Việc chờ duyệt**, đọc đúng revision/digest,
nhập nhận xét và tích xác nhận trước khi duyệt hoặc yêu cầu chỉnh sửa.

Bản đã gửi/duyệt không sửa tại chỗ. **Tạo revision chỉnh sửa** mở phiên bản mới;
nội dung và quyết định cũ còn để đối chiếu, không tự chuyển chữ ký sang bản mới.

### 3. Developer tạo workflow và kế hoạch

Chọn contract đã duyệt trong **Từ contract đã duyệt**, đặt tên workflow và tạo.
Form có Stage JSON nâng cao; schema và compiler hiện có vẫn là nguồn quyết định.
Server tự gắn contract đúng revision/digest vào đầu vào requirement và metadata.
Creator/project không lấy từ thông tin actor do client khai.

Workflow mặc định dùng `coding-agent@0.3.0`. Package visibility vẫn tuân cấu hình
opt-in hiện có, gồm `ADLC_TASK_LOOP_HARNESS_ENABLED` khi dùng package này. H7B
không tự bật cờ, đổi provider/model hoặc mở quyền thực thi. Nếu compiler báo
package chưa được phép, sửa cấu hình deployment/policy hợp lệ; không bỏ guard
hoặc thay bằng kết quả compile giả.

Bấm **Compile và gửi duyệt kỹ thuật**. Kế hoạch hợp lệ được lưu bất biến, người
đủ quyền khác duyệt trong hộp việc. Lỗi compiler hiển thị để chỉnh workflow,
không tạo task giả hoặc cho client tự nhận kế hoạch hợp lệ.

Sau khi duyệt, bấm **Chuẩn bị run · không dispatch**. Cùng một plan chỉ chuẩn bị
một run, có event tạo run theo model coordinator. Mở **Run Detail** để BA,
Developer và Tester cùng xem task/trạng thái/timeline theo quyền được cấp.

Đường dẫn: `/collaboration/runs/<run-id>/?project=<project-id>`.
Chưa có nút thực thi hoặc push GitHub cho run dùng chung trong H7B.

### 4. Tester chuẩn bị suite và đánh giá bằng chứng

Trong form từ contract, chọn **Test suite khai báo**. Case JSON dùng schema H6:
`case_id`, `pointer`, `expected`, `criterion_node_id`, `criterion_index`.
Node/index phải tồn tại trong đúng contract đã duyệt; không nhận trường PASS
hoặc report tự khai từ client. Bấm **Khóa test suite** để đóng băng revision.

Suite khai báo có `criteria_executed=false`; không coi việc khóa suite là đã chạy
test. API hỗ trợ cập nhật draft; UI slice này mới có form JSON tạo suite và thao
tác khóa/revision, chưa phải trình sửa suite trực quan đầy đủ.

Với bằng chứng lịch sử được chia sẻ, người có `verification:accept` có thể ghi
quyết định độc lập. Backend tính lại report từ plan + receipt và kiểm tra digest
bằng comparator H6. Chỉ bằng chứng PASS hợp lệ mới được chấp nhận; có thể yêu
cầu chỉnh sửa với report FAIL thật, nhưng không sửa report/verdict. Verify một
phần không chứng minh toàn bộ contract đạt.

### 5. Chia sẻ có chọn lọc lịch sử private

Trong **Chia sẻ snapshot lịch sử**, nhập Run ID, xem preview manifest, số task,
artifact, contract, plan và report Verify, rồi xác nhận phạm vi chia sẻ.

Chỉ **người tạo gốc đồng thời có quyền quản trị project đích** được thực hiện.
Run phải kết thúc (`SUCCEEDED`, `FAILED`, `CANCELLED`) trong SQL archive và chưa
gắn project. Snapshot trong runtime store cũ không có SQL archive chưa được
import tự động. Không mượn `owner_id` của người khác để đọc dữ liệu của họ.

Manifest khóa digest của run/plan và danh sách contract/Verify. Backend kiểm
tra lại đúng manifest và policy revision trước khi ghi transaction. Chuyển
động nguồn hoặc quyền thay đổi thì phải preview và xác nhận lại.

- Giữ ID run và provenance; không đổi owner hoặc ghi lại raw runtime row cũ.
  Binding SQL mới là ranh giới quyền, projection chia sẻ được lưu riêng bất biến.
- Bỏ dispatch request, pending result, runtime metadata, artifact URI và các
  approval có thể thực thi của phiên private. Không fetch URI bất kỳ.
- Giữ metadata artifact; giữ source patch khi payload còn trong kho đã lưu.
  Candidate thực có patch mới được đưa vào cổng `candidate:review`.
- Giữ contract đã approved ở nguồn nhưng yêu cầu quyết định project mới; plan
  lịch sử là `RETAINED`, không tái dùng chữ ký cũ để dispatch.
- Bằng chứng Verify chỉ gắn candidate/attempt/checksum khớp và report/receipt
  hợp lệ; không cho người import tự khai PASS.

Snapshot vẫn chứa nội dung nghiệp vụ, structured output và source diff được
chia sẻ có chủ ý. Đây không phải bộ dò secret trong mọi văn bản: người chia sẻ
phải kiểm tra nội dung nguồn, không đặt credential vào requirement/output/diff.
Không tự chia sẻ memory hoặc integration credentials.

## Các bất biến quyền và quyết định

- Quyền dùng cùng engine/preset H7A. Deny thắng allow; luôn kiểm tra membership
  hiện tại và quyền project. Quyền đọc các nguồn nhúng được kiểm tra đệ quy:
  chặn requirement thì không đọc nó gián tiếp qua workflow/plan/run.
- API mới lọc quyền trước pagination, total và inbox. Legacy Flow read/list cũng
  kiểm tra nguồn contract; legacy project owner không được lấy graph bằng owner
  override, và bộ lọc team chạy trước SQL pagination/count của danh sách flow.
- Mutation khóa policy revision trong transaction rồi kiểm tra lại quyền; audit
  cùng transaction. Lỗi audit không để lại quyết định hoặc resource nửa vời.
- Mỗi quyết định khóa actor/action, resource revision/digest, policy revision,
  dependency references và thời hạn 24 giờ. Cùng revision chỉ có một quyết định
  thắng, kể cả hai reviewer bấm đồng thời.
- Đổi policy/membership làm chữ ký cũ không còn dùng được. Hết hạn hoặc đổi nguồn
  thì tạo/duyệt revision hoặc compile lại; không tự rebase hay phát lại quyết định.
- UI khóa thao tác khi đang tải/lỗi quyền, stale tab hoặc nguồn đã đổi. Modal
  quyết định giữ phiên bản lúc mở, yêu cầu nhận xét và checkbox, không tự gửi lại.
- SSE run events có kết nối hữu hạn; mỗi frame đọc lại JWT và quyền trong SQL
  session mới. Thu hồi quyền hoặc lookup lỗi đóng stream bằng thông báo cố định.
- Route owner-only ADLC và coordinator legacy không serve/resume shared snapshot;
  recovery không biến run `CREATED` của team thành lượt gọi agent.

## API chính

Prefix `/api/v1/adlc/collaboration`; mọi mutation yêu cầu user JWT và policy
revision. Command trên tài nguyên hiện có còn khóa resource revision/digest.

| Nhóm route | Hành vi |
| --- | --- |
| `/projects`, `/projects/{id}` | Project nhìn thấy, workspace, inbox và quyền hiệu lực |
| `POST /projects/{id}/enable` | Admin xác nhận mở cộng tác cho project rỗng |
| `/projects/{id}/resources/{rid}` | Snapshot/revision, provenance, reviewer và quyết định |
| `POST .../contracts/tools` | Sáu công cụ Skilltree với idempotency theo actor |
| `POST .../resources/{rid}/submit`, `/revise`, `/decisions` | Gửi/khóa, mở revision mới, quyết định độc lập |
| `POST/PUT .../workflows[/{rid}]`, `POST .../workflows/{rid}/compile` | Authoring và compiler thật |
| `POST .../plans/{rid}/prepare` | Tạo canonical run, không dispatch |
| `POST/PUT .../suites[/{rid}]` | Suite khai báo gắn tiêu chí contract |
| `GET .../imports/runs/{rid}`, `POST .../imports/runs` | Preview manifest và chia sẻ có xác nhận |
| `GET .../runs/{rid}/events[/stream]` | Timeline cùng scope và revalidation |

Lỗi thường gặp: `TEAM_INDEPENDENT_REVIEWER_REQUIRED`,
`TEAM_RESOURCE_REVISION_CONFLICT`, `TEAM_POLICY_REVISION_CONFLICT`,
`TEAM_CURRENT_APPROVAL_REQUIRED`, `TEAM_DEPENDENCY_CHANGED`,
`TEAM_VERIFIED_PASS_REQUIRED`, `TEAM_COLLABORATION_PROVIDER_REQUIRED`.
Khôi phục quyền/cấu hình hoặc tạo phiên bản duyệt mới; không tắt enforcement.

### Sửa lỗi startup do tên revision constraint bị lặp

Nếu log có `AutogenerateDiffsDetected` với hai cặp tên sau:

- `ck_adlc_project_access_ck_adlc_project_access_revision` thay vì
  `ck_adlc_project_access_revision`.
- `ck_adlc_project_resource_ck_adlc_project_resource_revision` thay vì
  `ck_adlc_project_resource_revision`.

Đây là lỗi naming của bản H7A/H7B ban đầu: migration đã đưa tên đầy đủ cho
convention `ck_%(table_name)s_%(constraint_name)s`, nên Alembic thêm prefix lần
nữa. Điều kiện `revision >= 1` vẫn còn; không phải lỗi API token hay thiếu quyền.

Bản vá cố định tên cuối bằng `conv`/`op.f`, đồng thời thêm forward migration
`h7b3c4d5e6f7` cho database đã chạy bản cũ. Không reseed role, đổi mode/policy,
ghi lại revision hay xóa quyết định. PostgreSQL đổi tên trực tiếp; SQLite dùng
batch DDL để giữ nguyên các hàng, index, khóa ngoại và điều kiện kiểm tra.

Cách khôi phục:

1. Dừng các process backend dùng chung database và sao lưu database hiện tại.
2. Dùng source đã vá và khởi động backend bằng cách thông thường. Startup gọi
   upgrade tới revision mới rồi kiểm tra schema lại. Không cần đổi `.env`, model
   hoặc API key, cũng không cần restart Harness chỉ để sửa lỗi này.
3. Xác nhận log không còn hai cặp diff ở trên trước khi thử UI H7B.

Không xóa database, `stamp head`, bỏ schema check hoặc bật vòng tự động
downgrade/upgrade để che lỗi. Migration preflight cả hai table trước DDL; nếu
phát hiện constraint khác quy cách, custom SQLite trigger cần bảo toàn, hoặc
connection SQLite bật FK enforcement không phù hợp cho batch DDL, nó dừng lại
thay vì tự tháo các bảo vệ. Dùng connection bảo trì Alembic của ứng dụng và lập
phương án bảo toàn riêng nếu database đã được tùy biến.

Bản vá được thử trên database test, chưa tự áp dụng vào database đang dùng.
Regression tái hiện convention thật, kiểm tra drift trước/sau, dữ liệu/grant/
evidence/index/foreign key được giữ, chạy lại không đổi kết quả và từ chối
trường hợp không an toàn trước DDL. Chưa chạy migration này trên PostgreSQL thật.

Kiểm tra bản vá ngày 18/10/2026: 6 ca regression naming/repair mới và bộ hồi quy
352 test backend đều đạt; Ruff/format trên 6 file liên quan đạt. Một bộ mở rộng
riêng về database migration có 83 test đạt, 1 test cũ thất bại vì so sánh đường
dẫn Unix cố định với `Path` trên Windows (`test_explicit_downgrade_uses_configured_database_and_script_location`);
source/test của ca đó không được đổi trong bản vá này. Không coi toàn repository
hoặc PostgreSQL live là đã được kiểm chứng.

## Kiểm chứng

Test dùng SQLite thật, compiler/materializer thật, HTTP ASGI và React Query/UI
fixtures. Không dùng model hay GitHub thật để kiểm tra quyền. Có ca BA → Dev →
reviewer độc lập → cùng run cho Tester, với cả package `0.1.0` và `0.3.0` khi
được cấu hình opt-in trong test.

Các ca an toàn gồm: cách ly project, API actor giả/extra fields, self-approval,
hai reviewer race, stale revision/policy, thu hồi chữ ký/stream, audit rollback,
manifest import, nguồn nhúng qua API legacy, chặn resume/recovery, suite đóng
băng và tính lại Verify khi report đã bị sửa dù digest được tính lại.

Kiểm tra tập trung có thể chạy từ `adlc-flow`, trong môi trường test của dự án:

```powershell
$env:PYTHONPATH='D:\coding\ADLC\adlc-flow'
.\.venv\Scripts\python.exe -m pytest tests/unit/adlc/test_collaboration.py tests/unit/adlc/test_collaboration_migration.py -q -p no:cacheprovider -o addopts=
```

Kết quả ngày 18/10/2026:

| Kiểm tra | Kết quả |
| --- | --- |
| H7B và migration | 30 test backend đạt |
| Hồi quy H7B + H7A/factory/guards/visibility/public access/API quyền + persistence/SLA/contract/materialization | 346 test backend đạt |
| UI/client H7B và hồi quy UI/client H7A | 24 test đạt, 4 suite |
| Ruff và format cho 11 module/test collaboration, migration, provider/listing liên quan | Đạt |
| Biome trên 4 file page/client/test H7B | Đạt |
| TypeScript semantic check cho page/client H7B | 0 diagnostic trong phạm vi H7B |

Không coi đây là toàn bộ repository/build đã xanh. TypeScript còn 13 diagnostic
ở dependency/source ngoài H7B. Hai module route legacy `flows.py`, `projects.py`
có tổng cộng 13 diagnostic Ruff đã đối chiếu tồn tại ở HEAD trước thay đổi;
không chỉnh đồng loạt các phần đó trong slice này. Môi trường pytest còn cảnh
báo cấu hình timeout/timeout_method chưa có plugin tương ứng, nhưng các test
được nêu đều hoàn tất.

Chưa chạy browser E2E với database triển khai thật hoặc chuỗi team → agent →
GitHub. Không coi unit/component tests là bằng chứng shared live execution.
